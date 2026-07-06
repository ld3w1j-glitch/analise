from __future__ import annotations

import json
import os
import re
import uuid
import sys
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, Response, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from analysis import (
    add_file_to_inventory_store,
    add_file_to_production_store,
    analyze_inventory,
    analyze_inventory_store,
    analyze_production_cost,
    analyze_production_cost_store,
    detect_production_cost_report,
    empty_production_store,
    load_analysis_json,
    load_inventory_store,
    load_production_store,
    save_analysis_json,
    save_inventory_store,
    save_production_store,
    summarize_inventory_store,
    summarize_production_store,
)

APP_ROOT = Path(__file__).resolve().parent
BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_ROOT
# No Railway, você pode configurar INVENTARIO_STORAGE_DIR para um volume persistente.
# Localmente, o sistema continua salvando na própria pasta do projeto.
STORAGE_ROOT = Path(os.environ.get("INVENTARIO_STORAGE_DIR", str(BASE_DIR))).resolve()
UPLOAD_ROOT = STORAGE_ROOT / "uploads"
REPORT_ROOT = STORAGE_ROOT / "reports"
PROCESSED_ROOT = STORAGE_ROOT / "processed"
DATA_DIR = STORAGE_ROOT / "data"
USERS_FILE = DATA_DIR / "users.json"
ALLOWED_EXTENSIONS = {"xls", "xlsx", "xlsm"}

for folder in (UPLOAD_ROOT, REPORT_ROOT, PROCESSED_ROOT, DATA_DIR):
    folder.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024
app.secret_key = os.environ.get("INVENTARIO_SECRET_KEY", "inventario-dashboard-local-secret-key")

PAGES = {
    "resumo": {"label": "Resumo Geral", "endpoint": "dashboard_summary"},
    "divergencias": {"label": "Divergências", "endpoint": "dashboard_divergences"},
    "custo_producao": {"label": "Custo de Produção", "endpoint": "dashboard_production_cost"},
    "detalhes": {"label": "Detalhes & Exportação", "endpoint": "dashboard_details"},
}


def safe_username(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9_.-]+", "_", value)
    value = value.strip("._-")
    return value[:40]


def load_users() -> dict[str, Any]:
    if not USERS_FILE.exists():
        return {"version": 1, "users": {}}
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        if "users" not in data:
            return {"version": 1, "users": {}}
        return data
    except Exception:
        return {"version": 1, "users": {}}


def save_users(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def current_username() -> str | None:
    return session.get("username")


def get_user_display() -> str:
    users = load_users().get("users", {})
    username = current_username() or ""
    return users.get(username, {}).get("display_name") or username or "Usuário"


def user_base_dir(username: str | None = None) -> Path:
    username = username or current_username()
    if not username:
        raise RuntimeError("Usuário não autenticado.")
    path = DATA_DIR / "usuarios" / username
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_upload_dir(username: str | None = None) -> Path:
    username = username or current_username()
    path = UPLOAD_ROOT / "usuarios" / username
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_report_dir(username: str | None = None) -> Path:
    username = username or current_username()
    path = REPORT_ROOT / "usuarios" / username
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_store_path(username: str | None = None) -> Path:
    return user_base_dir(username) / "inventario_acumulado.json"


def user_production_store_path(username: str | None = None) -> Path:
    return user_base_dir(username) / "custo_producao_acumulado.json"


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_username():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def report_path(report_id: str) -> Path:
    return user_report_dir() / f"{report_id}.json"


def load_report_or_redirect(report_id: str):
    path = report_path(report_id)
    if not path.exists():
        return None
    return load_analysis_json(path)


def empty_store() -> dict[str, Any]:
    return {"version": 1, "source_files": [], "rows": {}}


def create_report_from_store(report_id: str | None = None):
    store = load_inventory_store(user_store_path())
    if not store.get("rows"):
        return None, None
    report_id = report_id or uuid.uuid4().hex[:12]
    analysis = analyze_inventory_store(store)
    analysis["source_file"] = "Histórico acumulado"
    analysis["report_id"] = report_id
    save_analysis_json(analysis, report_path(report_id))
    return report_id, analysis


def create_production_report_from_store(report_id: str | None = None):
    store = load_production_store(user_production_store_path())
    if not store.get("rows"):
        return None, None
    report_id = report_id or uuid.uuid4().hex[:12]
    analysis = analyze_production_cost_store(store)
    analysis["source_file"] = "Histórico acumulado de Custo de Produção"
    analysis["report_id"] = report_id
    save_analysis_json(analysis, report_path(report_id))
    return report_id, analysis


@app.context_processor
def inject_globals():
    return {
        "PAGES": PAGES,
        "current_username": current_username(),
        "current_user_display": get_user_display() if current_username() else None,
    }


@app.get("/login")
def login():
    if current_username():
        return redirect(url_for("index"))
    return render_template("login.html", error=None, next_url=request.args.get("next", ""))


@app.post("/login")
def login_post():
    username = safe_username(request.form.get("username", ""))
    password = request.form.get("password", "")
    next_url = request.form.get("next_url") or url_for("index")
    users = load_users().get("users", {})
    user = users.get(username)
    if not user or not check_password_hash(user.get("password_hash", ""), password):
        return render_template("login.html", error="Usuário ou senha inválidos.", next_url=next_url), 400
    session.clear()
    session["username"] = username
    return redirect(next_url if next_url.startswith("/") else url_for("index"))


@app.get("/cadastro")
def register():
    if current_username():
        return redirect(url_for("index"))
    return render_template("register.html", error=None)


@app.post("/cadastro")
def register_post():
    display_name = (request.form.get("display_name") or "").strip()
    username = safe_username(request.form.get("username", ""))
    password = request.form.get("password", "")
    password2 = request.form.get("password2", "")

    if len(username) < 3:
        return render_template("register.html", error="Informe um usuário com pelo menos 3 caracteres."), 400
    if len(password) < 4:
        return render_template("register.html", error="A senha precisa ter pelo menos 4 caracteres."), 400
    if password != password2:
        return render_template("register.html", error="As senhas não conferem."), 400

    data = load_users()
    users = data.setdefault("users", {})
    if username in users:
        return render_template("register.html", error="Esse usuário já existe."), 400

    users[username] = {
        "display_name": display_name or username,
        "password_hash": generate_password_hash(password),
    }
    save_users(data)
    user_base_dir(username).mkdir(parents=True, exist_ok=True)
    user_upload_dir(username).mkdir(parents=True, exist_ok=True)
    user_report_dir(username).mkdir(parents=True, exist_ok=True)
    if not user_store_path(username).exists():
        save_inventory_store(empty_store(), user_store_path(username))
    if not user_production_store_path(username).exists():
        save_production_store(empty_production_store(), user_production_store_path(username))

    session.clear()
    session["username"] = username
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def render_import_page(error: str | None = None):
    store_summary = summarize_inventory_store(load_inventory_store(user_store_path()))
    production_store_summary = summarize_production_store(load_production_store(user_production_store_path()))
    return render_template(
        "index.html",
        error=error,
        store_summary=store_summary,
        production_store_summary=production_store_summary,
    )


@app.get("/")
@login_required
def index():
    return render_import_page()


@app.post("/upload")
@login_required
def upload_file():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return render_import_page("Selecione um arquivo Excel para continuar."), 400

    if not allowed_file(uploaded.filename):
        return render_import_page("Formato inválido. Envie .xls, .xlsx ou .xlsm."), 400

    original_name = secure_filename(uploaded.filename)
    report_id = uuid.uuid4().hex[:12]
    saved_name = f"{report_id}_{original_name}"
    saved_path = user_upload_dir() / saved_name
    uploaded.save(saved_path)

    mode = request.form.get("mode", "accumulate")
    target_endpoint = "dashboard_summary"
    try:
        # Relatório de Equilíbrio: trata como apuração de Custo de Produção,
        # separado do histórico de inventário para não misturar estruturas.
        if detect_production_cost_report(saved_path):
            if mode == "single":
                analysis = analyze_production_cost(saved_path)
                analysis["source_file"] = original_name
            else:
                production_store = load_production_store(user_production_store_path())
                if request.form.get("reset_before") == "1":
                    production_store = empty_production_store()
                production_store = add_file_to_production_store(production_store, saved_path, original_name)
                save_production_store(production_store, user_production_store_path())
                analysis = analyze_production_cost_store(production_store)
                analysis["source_file"] = "Histórico acumulado de Custo de Produção"
            analysis["report_id"] = report_id
            save_analysis_json(analysis, report_path(report_id))
            target_endpoint = "dashboard_production_cost"
        elif mode == "single":
            analysis = analyze_inventory(saved_path)
            analysis["source_file"] = original_name
            analysis["report_id"] = report_id
            save_analysis_json(analysis, report_path(report_id))
        else:
            store = load_inventory_store(user_store_path())
            if request.form.get("reset_before") == "1":
                store = empty_store()
            store = add_file_to_inventory_store(store, saved_path, original_name)
            save_inventory_store(store, user_store_path())
            analysis = analyze_inventory_store(store)
            analysis["source_file"] = "Histórico acumulado"
            analysis["report_id"] = report_id
            save_analysis_json(analysis, report_path(report_id))
    except Exception as exc:
        saved_path.unlink(missing_ok=True)
        return render_import_page(str(exc)), 400

    return redirect(url_for(target_endpoint, report_id=report_id))

@app.post("/reset-store")
@login_required
def reset_store():
    save_inventory_store(empty_store(), user_store_path())
    return redirect(url_for("index"))


@app.post("/reset-production-store")
@login_required
def reset_production_store():
    save_production_store(empty_production_store(), user_production_store_path())
    return redirect(url_for("index"))


@app.get("/dashboard/acumulado")
@login_required
def dashboard_accumulated():
    report_id, _analysis = create_report_from_store()
    if not report_id:
        return redirect(url_for("index"))
    return redirect(url_for("dashboard_summary", report_id=report_id))


@app.get("/dashboard/custo-producao/acumulado")
@login_required
def dashboard_production_accumulated():
    report_id, _analysis = create_production_report_from_store()
    if not report_id:
        return redirect(url_for("index"))
    return redirect(url_for("dashboard_production_cost", report_id=report_id))


@app.get("/dashboard/<report_id>")
@login_required
def dashboard_root(report_id: str):
    analysis = load_report_or_redirect(report_id)
    if analysis and analysis.get("report_type") == "production_cost":
        return redirect(url_for("dashboard_production_cost", report_id=report_id))
    return redirect(url_for("dashboard_summary", report_id=report_id))


@app.get("/dashboard/<report_id>/resumo")
@login_required
def dashboard_summary(report_id: str):
    analysis = load_report_or_redirect(report_id)
    if analysis is None:
        return redirect(url_for("index"))
    if analysis.get("report_type") == "production_cost":
        return redirect(url_for("dashboard_production_cost", report_id=report_id))
    return render_template("dashboard_summary.html", analysis=analysis, active_page="resumo")


@app.get("/dashboard/<report_id>/divergencias")
@login_required
def dashboard_divergences(report_id: str):
    analysis = load_report_or_redirect(report_id)
    if analysis is None:
        return redirect(url_for("index"))
    if analysis.get("report_type") == "production_cost":
        return redirect(url_for("dashboard_production_cost", report_id=report_id))
    return render_template("dashboard_divergences.html", analysis=analysis, active_page="divergencias")


@app.get("/dashboard/<report_id>/custo-producao")
@login_required
def dashboard_production_cost(report_id: str):
    analysis = load_report_or_redirect(report_id)
    if analysis is None:
        return redirect(url_for("index"))
    if analysis.get("report_type") != "production_cost":
        return redirect(url_for("dashboard_summary", report_id=report_id))
    return render_template("dashboard_production_cost.html", analysis=analysis, active_page="custo_producao")


@app.get("/dashboard/<report_id>/detalhes")
@login_required
def dashboard_details(report_id: str):
    analysis = load_report_or_redirect(report_id)
    if analysis is None:
        return redirect(url_for("index"))
    return render_template("dashboard_details.html", analysis=analysis, active_page="detalhes")


@app.get("/download/json/<report_id>")
@login_required
def download_json(report_id: str):
    path = report_path(report_id)
    if not path.exists():
        return redirect(url_for("index"))
    return send_file(path, as_attachment=True, download_name=f"analise_inventario_{report_id}.json")


@app.get("/download/csv/<report_id>")
@login_required
def download_csv(report_id: str):
    path = report_path(report_id)
    if not path.exists():
        return redirect(url_for("index"))

    analysis = load_analysis_json(path)
    if analysis.get("report_type") == "production_cost":
        fieldnames = [
            "data", "empresa", "linha", "custo_producao", "custo_admin",
            "total_entrada", "total_saida", "total_cmv", "diferenca",
            "total_variacao", "quebra_producao", "quebra_saida", "risk"
        ]
        output = [";".join(fieldnames)]
        for row in analysis.get("records", []):
            values = [str(row.get(field, "")).replace(";", ",") for field in fieldnames]
            output.append(";".join(values))
    else:
        month_cols = analysis.get("meta", {}).get("month_cols", [])
        fieldnames = ["loja", "linha", "descricao"] + list(month_cols) + ["diferenca", "status", "risk"]
        output = [";".join(fieldnames)]
        for row in analysis.get("records", []):
            values = []
            for field in fieldnames:
                value = row.get("month_values", {}).get(field, row.get(field, ""))
                values.append(str(value).replace(";", ","))
            output.append(";".join(values))

    content = "\n".join(output)
    return Response(
        content,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=analise_inventario_{report_id}.csv"},
    )


@app.errorhandler(413)
def too_large(_):
    if current_username():
        return render_import_page("Arquivo muito grande. Limite atual: 32 MB."), 413
    return redirect(url_for("login"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Dashboard iniciado em: http://{host}:{port}")
    app.run(host=host, port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
