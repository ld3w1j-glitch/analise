from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

MONTH_RE = re.compile(r"^\s*\d{1,2}/\d{2,4}\s*$")


def normalize_text(value: Any) -> str:
    """Normalize text to compare Excel headers with accents/case safely."""
    if value is None:
        return ""
    text = str(value).strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text)
    return text.upper()


def parse_number(value: Any) -> float:
    """Convert numbers that may come from Excel or Brazilian text formats."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-"}:
        return 0.0

    text = text.replace("R$", "").replace("%", "").replace(" ", "")
    # Handles Brazilian format: 1.234,56
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")

    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        return float(text)
    except ValueError:
        return 0.0


def brl(value: float, signed: bool = False) -> str:
    """Format currency/value in Brazilian visual style."""
    prefix = "+" if signed and value > 0 else ""
    negative = value < 0
    value_abs = abs(value)
    formatted = f"{value_abs:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{prefix}{'-' if negative else ''}R$ {formatted}"


def pct(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")


def safe_div(a: float, b: float) -> float:
    return 0.0 if not b else a / b


def _convert_xls_with_libreoffice(path: Path) -> Path | None:
    """Optional fallback for machines that have LibreOffice installed."""
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        return None

    temp_dir = Path(tempfile.mkdtemp(prefix="inventario_convert_"))
    try:
        subprocess.run(
            [executable, "--headless", "--convert-to", "xlsx", "--outdir", str(temp_dir), str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
        )
    except Exception:
        return None

    converted = temp_dir / f"{path.stem}.xlsx"
    return converted if converted.exists() else None


def read_excel_file(path: str | Path) -> Dict[str, pd.DataFrame]:
    """Read .xls/.xlsx with all sheets as raw tables (header=None)."""
    path = Path(path)
    suffix = path.suffix.lower()
    engine = None

    if suffix == ".xls":
        engine = "xlrd"
    elif suffix in {".xlsx", ".xlsm"}:
        engine = "openpyxl"

    try:
        return pd.read_excel(path, sheet_name=None, header=None, engine=engine)
    except ImportError as exc:
        if suffix == ".xls":
            converted = _convert_xls_with_libreoffice(path)
            if converted:
                return pd.read_excel(converted, sheet_name=None, header=None, engine="openpyxl")
            raise RuntimeError(
                "Para importar arquivos .xls, instale a dependência xlrd: pip install xlrd. "
                "Ou salve o arquivo como .xlsx e importe novamente."
            ) from exc
        raise
    except Exception as exc:
        if suffix == ".xls":
            converted = _convert_xls_with_libreoffice(path)
            if converted:
                return pd.read_excel(converted, sheet_name=None, header=None, engine="openpyxl")
        raise RuntimeError(f"Não foi possível ler o Excel: {exc}") from exc


def header_score(row: pd.Series) -> int:
    cells = [normalize_text(v) for v in row.tolist() if str(v).strip() and str(v).lower() != "nan"]
    joined = " | ".join(cells)
    score = 0
    if "LOJA" in cells:
        score += 2
    if "LINHA" in cells:
        score += 2
    if any("DESCRICAO" in c for c in cells):
        score += 3
    if any("DIFERENCA" in c for c in cells):
        score += 3
    if any(MONTH_RE.match(str(c)) for c in cells):
        score += 2
    if "SALDO" in joined:
        score += 1
    if "VENDA" in joined:
        score += 1
    return score


def table_from_raw(raw: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    if raw.empty:
        raise ValueError("A planilha está vazia.")

    max_rows_to_scan = min(len(raw), 25)
    scores = [(idx, header_score(raw.iloc[idx])) for idx in range(max_rows_to_scan)]
    header_idx, best_score = max(scores, key=lambda x: x[1])
    if best_score < 4:
        header_idx = 0

    headers = raw.iloc[header_idx].tolist()
    clean_headers: List[str] = []
    seen: Dict[str, int] = {}
    for idx, h in enumerate(headers):
        label = str(h).strip() if h is not None and str(h).lower() != "nan" else f"COL_{idx+1}"
        if label in seen:
            seen[label] += 1
            label = f"{label}_{seen[label]}"
        else:
            seen[label] = 1
        clean_headers.append(label)

    data = raw.iloc[header_idx + 1 :].copy()
    data.columns = clean_headers
    data = data.dropna(how="all")
    return data.reset_index(drop=True), header_idx


def find_column(columns: List[str], *keywords: str) -> str | None:
    normalized = [(col, normalize_text(col)) for col in columns]
    for col, norm in normalized:
        if all(key in norm for key in keywords):
            return col
    return None


def prepare_dataframe(file_path: str | Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    sheets = read_excel_file(file_path)
    candidates = []

    for sheet_name, raw in sheets.items():
        try:
            data, header_idx = table_from_raw(raw)
        except Exception:
            continue

        columns = list(data.columns)
        loja_col = find_column(columns, "LOJA")
        linha_col = find_column(columns, "LINHA")
        desc_col = find_column(columns, "DESCRICAO") or find_column(columns, "DESCR")
        diff_col = find_column(columns, "DIFERENCA") or find_column(columns, "DIVERGENCIA")
        month_cols = [col for col in columns if MONTH_RE.match(str(col))]

        score = 0
        score += 3 if loja_col else 0
        score += 3 if linha_col else 0
        score += 3 if desc_col else 0
        score += 3 if diff_col else 0
        score += len(month_cols)
        candidates.append((score, sheet_name, data, header_idx, loja_col, linha_col, desc_col, diff_col, month_cols))

    if not candidates:
        raise RuntimeError("Não encontrei nenhuma tabela válida dentro do Excel.")

    candidates.sort(key=lambda x: x[0], reverse=True)
    score, sheet_name, data, header_idx, loja_col, linha_col, desc_col, diff_col, month_cols = candidates[0]

    if not desc_col:
        raise RuntimeError("Não encontrei a coluna de descrição da linha/produto.")

    # Remove repeated headers or total rows when present.
    data = data.copy()
    for col in data.columns:
        data[col] = data[col].where(data[col].notna(), None)

    if loja_col:
        data = data[data[loja_col].apply(lambda x: normalize_text(x) not in {"", "LOJA"})]
    data = data[data[desc_col].apply(lambda x: normalize_text(x) not in {"", "DESCRICAO LINHA", "TOTAL", "TOTAIS"})]

    numeric_cols = list(dict.fromkeys(month_cols + ([diff_col] if diff_col else [])))
    for col in numeric_cols:
        data[col] = data[col].apply(parse_number)

    if not month_cols:
        # Use all numeric-looking columns except identifiers as fallback.
        ignored = {c for c in [loja_col, linha_col, desc_col] if c}
        possible = [c for c in data.columns if c not in ignored and c != diff_col]
        numeric_scores = []
        for col in possible:
            vals = data[col].apply(parse_number)
            if vals.abs().sum() > 0:
                numeric_scores.append(col)
        month_cols = numeric_scores

    if diff_col:
        data["__DIFERENCA__"] = data[diff_col].apply(parse_number)
    elif month_cols:
        data["__DIFERENCA__"] = data[month_cols].apply(lambda row: sum(parse_number(v) for v in row), axis=1)
    else:
        raise RuntimeError("Não encontrei coluna DIFERENÇA nem colunas mensais para calcular o resultado.")

    if loja_col:
        stores = [str(v).strip() for v in data[loja_col].tolist() if str(v).strip() and str(v).lower() != "nan"]
        loja = Counter(stores).most_common(1)[0][0] if stores else "Não identificada"
    else:
        loja = "Não identificada"

    meta = {
        "sheet_name": sheet_name,
        "header_row": header_idx + 1,
        "loja_col": loja_col,
        "linha_col": linha_col,
        "desc_col": desc_col,
        "diff_col": diff_col,
        "month_cols": month_cols,
        "loja": loja,
    }
    return data.reset_index(drop=True), meta


def bar_height(value: float, values: List[float]) -> int:
    max_abs = max([abs(v) for v in values] + [1])
    return max(8, int(abs(value) / max_abs * 100))


def make_trend_points(values: List[float], width: int = 500, height: int = 170, pad: int = 18) -> str:
    if not values:
        return ""
    if len(values) == 1:
        values = values * 2
    min_v, max_v = min(values), max(values)
    if min_v == max_v:
        min_v -= 1
        max_v += 1
    points = []
    for i, value in enumerate(values):
        x = pad + i * ((width - 2 * pad) / (len(values) - 1))
        y = height - pad - ((value - min_v) / (max_v - min_v)) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)



def make_trend_point_objects(values: List[float], labels: List[str] | None = None, width: int = 500, height: int = 170, pad: int = 18) -> List[Dict[str, Any]]:
    """Return normalized point data for interactive HTML overlays on the trend chart."""
    if not values:
        return []
    original_values = list(values)
    if len(values) == 1:
        values = values * 2
    min_v, max_v = min(values), max(values)
    if min_v == max_v:
        min_v -= 1
        max_v += 1
    point_objects: List[Dict[str, Any]] = []
    for i, value in enumerate(values):
        x = pad + i * ((width - 2 * pad) / (len(values) - 1))
        y = height - pad - ((value - min_v) / (max_v - min_v)) * (height - 2 * pad)
        source_value = original_values[i] if i < len(original_values) else original_values[-1]
        label = labels[i] if labels and i < len(labels) else f"Ponto {i + 1}"
        point_objects.append({
            "x_pct": round((x / width) * 100, 2),
            "y_pct": round((y / height) * 100, 2),
            "label": str(label),
            "value": source_value,
            "value_fmt": brl(source_value, signed=True),
        })
    return point_objects


def row_record(row: pd.Series, meta: Dict[str, Any]) -> Dict[str, Any]:
    diff = float(row.get("__DIFERENCA__", 0) or 0)
    abs_diff = abs(diff)
    desc_col = meta.get("desc_col")
    linha_col = meta.get("linha_col")
    loja_col = meta.get("loja_col")
    month_cols = meta.get("month_cols", []) or []
    month_values = {str(col): parse_number(row.get(col, 0)) for col in month_cols}
    return {
        "loja": str(row.get(loja_col, "") or "") if loja_col else "",
        "linha": str(row.get(linha_col, "") or "") if linha_col else "",
        "descricao": str(row.get(desc_col, "") or ""),
        "month_values": month_values,
        "month_values_fmt": {month: brl(value, signed=True) for month, value in month_values.items()},
        "diferenca": diff,
        "diferenca_fmt": brl(diff, signed=True),
        "abs_diferenca": abs_diff,
        "status": "positivo" if diff > 0 else "negativo" if diff < 0 else "zerado",
    }



def sort_month_label(label: str) -> tuple[int, int, str]:
    """Sort labels like 01/26, 12/2026 chronologically."""
    match = re.match(r"^\s*(\d{1,2})/(\d{2,4})\s*$", str(label))
    if not match:
        return (9999, 99, str(label))
    month = int(match.group(1))
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return (year, month, str(label))


def build_analysis_from_prepared_data(data: pd.DataFrame, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build the same dashboard structure from an already prepared dataframe."""
    diffs = [float(v or 0) for v in data["__DIFERENCA__"].tolist()]
    total_rows = len(diffs)
    positive_values = [v for v in diffs if v > 0]
    negative_values = [v for v in diffs if v < 0]
    zero_values = [v for v in diffs if v == 0]
    net_total = sum(diffs)
    positive_total = sum(positive_values)
    negative_total = sum(negative_values)
    absolute_total = sum(abs(v) for v in diffs)
    diverging_count = len(positive_values) + len(negative_values)

    accuracy_by_rows = safe_div(len(zero_values), total_rows) * 100
    balance_score = max(0.0, min(100.0, 100.0 - safe_div(abs(net_total), absolute_total) * 100.0)) if absolute_total else 100.0

    month_cols = meta.get("month_cols", [])
    monthly_summary = []
    monthly_values = []
    monthly_positive_values = []
    monthly_negative_values = []
    monthly_divergences = []
    for col in month_cols:
        values = data[col].apply(parse_number).tolist() if col in data.columns else []
        total = sum(values)
        positive_month = sum(v for v in values if v > 0)
        negative_month = sum(v for v in values if v < 0)
        monthly_values.append(total)
        monthly_positive_values.append(positive_month)
        monthly_negative_values.append(abs(negative_month))
        monthly_summary.append(
            {
                "label": str(col),
                "value": total,
                "value_fmt": brl(total, signed=True),
                "height": bar_height(total, monthly_values + diffs),
                "status": "positivo" if total >= 0 else "negativo",
                "tooltip": f"{col} • {brl(total, signed=True)}",
            }
        )
        monthly_divergences.append(
            {
                "label": str(col),
                "positive": positive_month,
                "positive_fmt": brl(positive_month),
                "negative": abs(negative_month),
                "negative_fmt": brl(abs(negative_month)),
                "net": total,
                "net_fmt": brl(total, signed=True),
                "pos_height": 8,
                "neg_height": 8,
            }
        )

    if monthly_summary:
        all_month_values = [m["value"] for m in monthly_summary]
        for item in monthly_summary:
            item["height"] = bar_height(item["value"], all_month_values)
        max_pos = max(monthly_positive_values + [1])
        max_neg = max(monthly_negative_values + [1])
        for item in monthly_divergences:
            item["pos_height"] = max(8, round((item["positive"] / max_pos) * 100, 1)) if max_pos else 8
            item["neg_height"] = max(8, round((item["negative"] / max_neg) * 100, 1)) if max_neg else 8

    records = [row_record(row, meta) for _, row in data.iterrows()]
    records_sorted_abs = sorted(records, key=lambda r: r["abs_diferenca"], reverse=True)
    top_records = records_sorted_abs[:12]
    max_abs_top = max([r["abs_diferenca"] for r in top_records] + [1])
    for rec in top_records:
        rec["bar_width"] = round(rec["abs_diferenca"] / max_abs_top * 100, 1)

    top_positive = sorted([r for r in records if r["diferenca"] > 0], key=lambda r: r["diferenca"], reverse=True)[:8]
    top_negative = sorted([r for r in records if r["diferenca"] < 0], key=lambda r: r["diferenca"])[:8]

    trend_values = monthly_values or [sum(diffs[: i + 1]) for i in range(min(len(diffs), 12))]

    chart_total = positive_total + abs(negative_total)
    positive_pct = safe_div(positive_total, chart_total) * 100
    negative_pct = safe_div(abs(negative_total), chart_total) * 100

    trend_labels = [str(c) for c in month_cols] if month_cols else [f"Item {i + 1}" for i in range(len(trend_values))]
    trend_points = make_trend_point_objects(trend_values, trend_labels)
    divergence_line_values = monthly_positive_values or [abs(v) for v in positive_values[:12]]
    negative_line_values = monthly_negative_values or [abs(v) for v in negative_values[:12]]
    line_labels = trend_labels if month_cols else [f"Item {i + 1}" for i in range(max(len(divergence_line_values), len(negative_line_values)))]

    risk_threshold = 0
    non_zero_abs = sorted([abs(v) for v in diffs if v != 0])
    if non_zero_abs:
        risk_threshold = non_zero_abs[int(len(non_zero_abs) * 0.75) - 1] if len(non_zero_abs) > 3 else non_zero_abs[-1]
    for rec in records:
        rec["risk"] = "Alto" if rec["abs_diferenca"] >= risk_threshold and rec["abs_diferenca"] > 0 else "Baixo" if rec["abs_diferenca"] > 0 else "Sem divergência"

    positive_line_points = make_trend_point_objects(divergence_line_values, line_labels)
    negative_line_points = make_trend_point_objects(negative_line_values, line_labels)

    analysis = {
        "meta": meta,
        "kpis": {
            "loja": meta.get("loja", "Não identificada"),
            "total_rows": total_rows,
            "diverging_count": diverging_count,
            "zero_count": len(zero_values),
            "positive_count": len(positive_values),
            "negative_count": len(negative_values),
            "net_total": net_total,
            "net_total_fmt": brl(net_total, signed=True),
            "positive_total": positive_total,
            "positive_total_fmt": brl(positive_total),
            "negative_total": negative_total,
            "negative_total_fmt": brl(abs(negative_total)),
            "absolute_total": absolute_total,
            "absolute_total_fmt": brl(absolute_total),
            "accuracy_by_rows": round(accuracy_by_rows, 1),
            "accuracy_by_rows_fmt": pct(accuracy_by_rows),
            "balance_score": round(balance_score, 1),
            "balance_score_fmt": pct(balance_score),
            "positive_pct": round(positive_pct, 1),
            "negative_pct": round(negative_pct, 1),
            "month_count": len(month_cols),
            "month_range": f"{month_cols[0]} até {month_cols[-1]}" if month_cols else "Sem meses identificados",
        },
        "monthly_summary": monthly_summary,
        "monthly_divergences": monthly_divergences,
        "divergence_chart": {
            "positive_points": make_trend_points(divergence_line_values),
            "negative_points": make_trend_points(negative_line_values),
            "positive_point_objects": positive_line_points,
            "negative_point_objects": negative_line_points,
            "labels": line_labels,
            "positive_values": divergence_line_values,
            "negative_values": negative_line_values,
        },
        "trend": {
            "values": trend_values,
            "points": make_trend_points(trend_values),
            "point_objects": trend_points,
            "labels": trend_labels,
        },
        "top_records": top_records,
        "top_positive": top_positive,
        "top_negative": top_negative,
        "records": records,
        "notes": [
            "DIFERENÇA positiva indica sobra/ganho no inventário.",
            "DIFERENÇA negativa indica perda/falta no inventário.",
            "O score de controle mede o equilíbrio entre saldo líquido e volume total de divergências.",
        ],
    }
    return analysis


def analyze_inventory(file_path: str | Path) -> Dict[str, Any]:
    data, meta = prepare_dataframe(file_path)
    return build_analysis_from_prepared_data(data, meta)


def inventory_rows_from_file(file_path: str | Path, source_file: str | None = None) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Extract normalized row/month data from one Excel file for cumulative storage."""
    data, meta = prepare_dataframe(file_path)
    month_cols = meta.get("month_cols", [])
    if not month_cols:
        raise RuntimeError("Para acumular histórico, o arquivo precisa ter colunas mensais, como 01/26, 02/26, 03/26.")

    rows: List[Dict[str, Any]] = []
    loja_col = meta.get("loja_col")
    linha_col = meta.get("linha_col")
    desc_col = meta.get("desc_col")
    source_name = source_file or Path(file_path).name
    for _, row in data.iterrows():
        loja = str(row.get(loja_col, "") or "") if loja_col else ""
        linha = str(row.get(linha_col, "") or "") if linha_col else ""
        descricao = str(row.get(desc_col, "") or "") if desc_col else ""
        if not descricao.strip():
            continue
        months = {str(col): parse_number(row.get(col, 0)) for col in month_cols}
        rows.append({
            "loja": loja,
            "linha": linha,
            "descricao": descricao,
            "months": months,
            "source_file": source_name,
        })
    return rows, meta


def make_row_key(row: Dict[str, Any]) -> str:
    parts = [row.get("loja", ""), row.get("linha", ""), row.get("descricao", "")]
    return "|".join(normalize_text(part) for part in parts)


def empty_inventory_store() -> Dict[str, Any]:
    return {"version": 1, "source_files": [], "rows": {}}


def load_inventory_store(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return empty_inventory_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_inventory_store()
    if not isinstance(data, dict) or "rows" not in data:
        return empty_inventory_store()
    return data


def save_inventory_store(store: Dict[str, Any], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def add_file_to_inventory_store(store: Dict[str, Any], file_path: str | Path, source_file: str | None = None) -> Dict[str, Any]:
    """Add a new Excel file into cumulative history.

    Existing month labels are replaced by the newest import instead of duplicated.
    This avoids double counting overlaps such as 04/26 appearing in two cloud exports.
    """
    rows, meta = inventory_rows_from_file(file_path, source_file)
    source_name = source_file or Path(file_path).name
    imported_months = sorted([str(m) for m in meta.get("month_cols", [])], key=sort_month_label)

    for row in rows:
        key = make_row_key(row)
        if not key:
            continue
        current = store["rows"].setdefault(key, {
            "loja": row.get("loja", ""),
            "linha": row.get("linha", ""),
            "descricao": row.get("descricao", ""),
            "months": {},
            "month_sources": {},
        })
        current["loja"] = row.get("loja", current.get("loja", ""))
        current["linha"] = row.get("linha", current.get("linha", ""))
        current["descricao"] = row.get("descricao", current.get("descricao", ""))
        for month, value in row.get("months", {}).items():
            current["months"][str(month)] = float(value or 0)
            current.setdefault("month_sources", {})[str(month)] = source_name

    store.setdefault("source_files", []).append({
        "filename": source_name,
        "months": imported_months,
        "rows": len(rows),
    })
    return store


def store_to_prepared_dataframe(store: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    all_months = sorted(
        {month for row in store.get("rows", {}).values() for month in row.get("months", {}).keys()},
        key=sort_month_label,
    )
    rows = []
    for row in store.get("rows", {}).values():
        item = {
            "LOJA": row.get("loja", ""),
            "LINHA": row.get("linha", ""),
            "DESCRIÇÃO LINHA": row.get("descricao", ""),
        }
        diff = 0.0
        for month in all_months:
            value = parse_number(row.get("months", {}).get(month, 0))
            item[month] = value
            diff += value
        item["DIFERENÇA"] = diff
        item["__DIFERENCA__"] = diff
        rows.append(item)
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=["LOJA", "LINHA", "DESCRIÇÃO LINHA", "DIFERENÇA", "__DIFERENCA__"])
    stores = [str(r.get("loja", "")).strip() for r in store.get("rows", {}).values() if str(r.get("loja", "")).strip()]
    loja = Counter(stores).most_common(1)[0][0] if stores else "Não identificada"
    meta = {
        "sheet_name": "Histórico acumulado",
        "header_row": 1,
        "loja_col": "LOJA",
        "linha_col": "LINHA",
        "desc_col": "DESCRIÇÃO LINHA",
        "diff_col": "DIFERENÇA",
        "month_cols": all_months,
        "loja": loja,
        "is_accumulated": True,
    }
    return df, meta


def analyze_inventory_store(store: Dict[str, Any]) -> Dict[str, Any]:
    data, meta = store_to_prepared_dataframe(store)
    analysis = build_analysis_from_prepared_data(data, meta)
    source_files = store.get("source_files", [])
    unique_filenames = []
    seen = set()
    for item in source_files:
        name = item.get("filename", "")
        if name and name not in seen:
            seen.add(name)
            unique_filenames.append(name)
    months = meta.get("month_cols", [])
    analysis["store"] = {
        "file_count": len(unique_filenames),
        "import_count": len(source_files),
        "source_files": source_files,
        "unique_filenames": unique_filenames,
        "month_count": len(months),
        "month_range": f"{months[0]} até {months[-1]}" if months else "Sem meses",
        "months": months,
    }
    analysis["notes"].insert(0, "Histórico acumulado: novos arquivos mantêm os meses anteriores e adicionam os novos períodos.")
    return analysis


def summarize_inventory_store(store: Dict[str, Any]) -> Dict[str, Any]:
    months = sorted(
        {month for row in store.get("rows", {}).values() for month in row.get("months", {}).keys()},
        key=sort_month_label,
    )
    source_files = store.get("source_files", [])
    unique = []
    seen = set()
    for item in source_files:
        name = item.get("filename", "")
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    return {
        "has_data": bool(store.get("rows")),
        "row_count": len(store.get("rows", {})),
        "file_count": len(unique),
        "import_count": len(source_files),
        "month_count": len(months),
        "months": months,
        "month_range": f"{months[0]} até {months[-1]}" if months else "Nenhum mês salvo",
        "latest_files": list(reversed(source_files[-5:])),
    }

def save_analysis_json(analysis: Dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")


def load_analysis_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
