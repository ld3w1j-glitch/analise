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
        supplier_col = (
            find_column(columns, "FORNECEDOR")
            or find_column(columns, "FORNEC")
            or find_column(columns, "SUPPLIER")
        )
        diff_col = find_column(columns, "DIFERENCA") or find_column(columns, "DIVERGENCIA")
        month_cols = [col for col in columns if MONTH_RE.match(str(col))]

        score = 0
        score += 3 if loja_col else 0
        score += 3 if linha_col else 0
        score += 3 if desc_col else 0
        score += 3 if diff_col else 0
        score += len(month_cols)
        candidates.append((score, sheet_name, data, header_idx, loja_col, linha_col, desc_col, supplier_col, diff_col, month_cols))

    if not candidates:
        raise RuntimeError("Não encontrei nenhuma tabela válida dentro do Excel.")

    candidates.sort(key=lambda x: x[0], reverse=True)
    score, sheet_name, data, header_idx, loja_col, linha_col, desc_col, supplier_col, diff_col, month_cols = candidates[0]

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
        ignored = {c for c in [loja_col, linha_col, desc_col, supplier_col] if c}
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
        "supplier_col": supplier_col,
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
    supplier_col = meta.get("supplier_col")
    month_cols = meta.get("month_cols", []) or []
    month_values = {str(col): parse_number(row.get(col, 0)) for col in month_cols}
    return {
        "loja": str(row.get(loja_col, "") or "") if loja_col else "",
        "linha": str(row.get(linha_col, "") or "") if linha_col else "",
        "descricao": str(row.get(desc_col, "") or ""),
        "fornecedor": str(row.get(supplier_col, "") or "") if supplier_col else "",
        "month_values": month_values,
        "month_values_fmt": {month: brl(value, signed=True) for month, value in month_values.items()},
        "diferenca": diff,
        "diferenca_fmt": brl(diff, signed=True),
        "abs_diferenca": abs_diff,
        "status": "positivo" if diff > 0 else "negativo" if diff < 0 else "zerado",
    }





def summarize_group_records(
    records: List[Dict[str, Any]],
    label_key: str,
    fallback_label: str,
    code_key: str | None = None,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Group divergence records for interactive category/supplier tabs."""
    grouped: Dict[str, Dict[str, Any]] = {}

    for rec in records:
        label = str(rec.get(label_key, "") or "").strip()
        code = str(rec.get(code_key, "") or "").strip() if code_key else ""
        if not label and not code:
            label = fallback_label
        elif not label:
            label = code

        group_id = f"{code}|{label}" if code_key else label
        item = grouped.setdefault(group_id, {
            "label": label,
            "code": code,
            "item_count": 0,
            "positive_total": 0.0,
            "negative_total": 0.0,
            "net_total": 0.0,
            "abs_total": 0.0,
        })
        diff = float(rec.get("diferenca", 0) or 0)
        item["item_count"] += 1
        item["net_total"] += diff
        item["abs_total"] += abs(diff)
        if diff > 0:
            item["positive_total"] += diff
        elif diff < 0:
            item["negative_total"] += diff

    groups = sorted(grouped.values(), key=lambda item: item["abs_total"], reverse=True)[:limit]
    max_abs = max([item["abs_total"] for item in groups] + [1])
    for item in groups:
        net = item["net_total"]
        item["status"] = "positivo" if net > 0 else "negativo" if net < 0 else "zerado"
        item["bar_width"] = round(item["abs_total"] / max_abs * 100, 1)
        item["positive_total_fmt"] = brl(item["positive_total"])
        item["negative_total_fmt"] = brl(abs(item["negative_total"]))
        item["net_total_fmt"] = brl(net, signed=True)
        item["abs_total_fmt"] = brl(item["abs_total"])
    return groups


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

    category_groups = summarize_group_records(records, "descricao", "Categoria não identificada", "linha")
    supplier_groups = []
    if meta.get("supplier_col") and any(str(rec.get("fornecedor", "")).strip() for rec in records):
        supplier_groups = summarize_group_records(records, "fornecedor", "Fornecedor não identificado")

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
        "category_groups": category_groups,
        "supplier_groups": supplier_groups,
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
    supplier_col = meta.get("supplier_col")
    source_name = source_file or Path(file_path).name
    for _, row in data.iterrows():
        loja = str(row.get(loja_col, "") or "") if loja_col else ""
        linha = str(row.get(linha_col, "") or "") if linha_col else ""
        descricao = str(row.get(desc_col, "") or "") if desc_col else ""
        fornecedor = str(row.get(supplier_col, "") or "") if supplier_col else ""
        if not descricao.strip():
            continue
        months = {str(col): parse_number(row.get(col, 0)) for col in month_cols}
        rows.append({
            "loja": loja,
            "linha": linha,
            "descricao": descricao,
            "fornecedor": fornecedor,
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
            "fornecedor": row.get("fornecedor", ""),
            "months": {},
            "month_sources": {},
        })
        current["loja"] = row.get("loja", current.get("loja", ""))
        current["linha"] = row.get("linha", current.get("linha", ""))
        current["descricao"] = row.get("descricao", current.get("descricao", ""))
        current["fornecedor"] = row.get("fornecedor", current.get("fornecedor", ""))
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
            "FORNECEDOR": row.get("fornecedor", ""),
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
    suppliers = [str(r.get("fornecedor", "")).strip() for r in store.get("rows", {}).values() if str(r.get("fornecedor", "")).strip()]
    loja = Counter(stores).most_common(1)[0][0] if stores else "Não identificada"
    meta = {
        "sheet_name": "Histórico acumulado",
        "header_row": 1,
        "loja_col": "LOJA",
        "linha_col": "LINHA",
        "desc_col": "DESCRIÇÃO LINHA",
        "supplier_col": "FORNECEDOR" if suppliers else None,
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


# -----------------------------------------------------------------------------
# Relatório de Equilíbrio / Apuração de Custo de Produção
# -----------------------------------------------------------------------------

DATE_FULL_RE = re.compile(r"^\s*\d{2}/\d{2}/\d{4}\s*$")


def _is_equilibrium_header(row: pd.Series) -> bool:
    cells = [normalize_text(v) for v in row.tolist()]
    joined = " | ".join(cells)
    return "CUSTOPRODUCAO" in joined and "DIFERENCA" in joined and "TOTAL CMV" in joined


def _find_equilibrium_sheet(sheets: Dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame, int] | None:
    """Return the sheet/header row for the Relatório de Equilíbrio layout."""
    for sheet_name, raw in sheets.items():
        if raw is None or raw.empty:
            continue
        title = normalize_text(raw.iloc[0, 0]) if raw.shape[0] and raw.shape[1] else ""
        max_rows = min(len(raw), 20)
        for idx in range(max_rows):
            if _is_equilibrium_header(raw.iloc[idx]):
                return sheet_name, raw, idx
    return None


def detect_production_cost_report(file_path: str | Path) -> bool:
    """Detects files in the Relatório de Equilíbrio format.

    This format is not an inventory divergence table. It is hierarchical by
    Data -> Empresa -> Linha and contains the CustoProdução column.
    """
    try:
        sheets = read_excel_file(file_path)
        return _find_equilibrium_sheet(sheets) is not None
    except Exception:
        return False


def _unique_headers(headers: List[Any]) -> List[str]:
    clean: List[str] = []
    seen: Dict[str, int] = {}
    for idx, raw in enumerate(headers):
        label = str(raw).strip() if raw is not None and str(raw).lower() != "nan" else ""
        if idx == 0:
            label = label or "Dia/Empresa/Linha"
        if not label:
            label = f"COL_{idx+1}"
        if label in seen:
            seen[label] += 1
            label = f"{label}_{seen[label]}"
        else:
            seen[label] = 1
        clean.append(label)
    return clean


def _sort_full_date_label(value: str) -> tuple[int, int, int, str]:
    match = re.match(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$", str(value))
    if not match:
        return (9999, 99, 99, str(value))
    day, month, year = map(int, match.groups())
    return (year, month, day, str(value))


def prepare_production_cost_records(file_path: str | Path) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    sheets = read_excel_file(file_path)
    found = _find_equilibrium_sheet(sheets)
    if not found:
        raise RuntimeError("Não encontrei o layout do Relatório de Equilíbrio com a coluna CustoProdução.")

    sheet_name, raw, header_idx = found
    raw = raw.dropna(how="all").dropna(axis=1, how="all").reset_index(drop=True)
    headers = _unique_headers(raw.iloc[header_idx].tolist())
    if headers and normalize_text(headers[0]).startswith("COL_"):
        headers[0] = "Dia/Empresa/Linha"

    # Some exports put the first-column label one line above the numeric headers.
    if raw.shape[0] > 1:
        first_col_title = str(raw.iloc[max(header_idx - 1, 0), 0] or "").strip()
        if first_col_title and normalize_text(headers[0]).startswith("COL_"):
            headers[0] = first_col_title
        elif first_col_title and normalize_text(first_col_title) == "DIA/EMPRESA/LINHA":
            headers[0] = first_col_title

    records: List[Dict[str, Any]] = []
    current_date = ""
    current_company = ""
    data_rows = raw.iloc[header_idx + 1 :].copy()
    data_rows.columns = headers

    key_col = headers[0]
    metric_cols = [col for col in headers[1:] if not str(col).startswith("COL_")]
    for _, row in data_rows.iterrows():
        label_raw = row.get(key_col, "")
        label = str(label_raw).strip() if label_raw is not None and str(label_raw).lower() != "nan" else ""
        if not label:
            continue
        label_norm = normalize_text(label)

        if DATE_FULL_RE.match(label):
            current_date = label
            current_company = ""
            continue
        if label_norm.startswith("TOTAL"):
            continue

        numeric_total = sum(abs(parse_number(row.get(col, 0))) for col in metric_cols)
        looks_like_company = (
            "LTDA" in label_norm
            or "EMPRESA" in label_norm
            or "(CD)" in label_norm
            or label_norm.startswith("MR")
        ) and numeric_total == 0
        if looks_like_company:
            current_company = label
            continue

        rec: Dict[str, Any] = {
            "data": current_date,
            "empresa": current_company,
            "linha": label,
        }
        for col in metric_cols:
            rec[col] = parse_number(row.get(col, 0))
        records.append(rec)

    if not records:
        raise RuntimeError("Encontrei a coluna CustoProdução, mas não consegui montar os registros por linha.")

    meta = {
        "sheet_name": sheet_name,
        "header_row": header_idx + 1,
        "date_col": key_col,
        "metric_cols": metric_cols,
        "linha_col": "linha",
        "report_title": "Relatório de Equilíbrio",
    }
    return records, meta


def _sum_record_metric(records: List[Dict[str, Any]], metric: str) -> float:
    return sum(parse_number(rec.get(metric, 0)) for rec in records)


def _format_production_record(rec: Dict[str, Any], max_cost: float) -> Dict[str, Any]:
    cost = parse_number(rec.get("CustoProdução", 0))
    diff = parse_number(rec.get("Diferença", 0))
    cmv = parse_number(rec.get("Total CMV", 0))
    output = parse_number(rec.get("Total Saída", 0))
    input_total = parse_number(rec.get("Total Entrada", 0))
    total_variation = parse_number(rec.get("TotalVariação", 0))
    status = "positivo" if cost > 0 else "zerado"
    return {
        **rec,
        "loja": rec.get("empresa", ""),
        "descricao": rec.get("linha", ""),
        "custo_producao": cost,
        "custo_producao_fmt": brl(cost),
        "custo_admin": parse_number(rec.get("CustoAdmin.", 0)),
        "custo_admin_fmt": brl(parse_number(rec.get("CustoAdmin.", 0))),
        "total_cmv": cmv,
        "total_cmv_fmt": brl(cmv, signed=True),
        "total_saida": output,
        "total_saida_fmt": brl(output, signed=True),
        "total_entrada": input_total,
        "total_entrada_fmt": brl(input_total, signed=True),
        "diferenca": diff,
        "diferenca_fmt": brl(diff, signed=True),
        "total_variacao": total_variation,
        "total_variacao_fmt": brl(total_variation, signed=True),
        "quebra_producao": parse_number(rec.get("QuebraProdução", 0)),
        "quebra_producao_fmt": brl(parse_number(rec.get("QuebraProdução", 0)), signed=True),
        "quebra_saida": parse_number(rec.get("QuebraSaída", 0)),
        "quebra_saida_fmt": brl(parse_number(rec.get("QuebraSaída", 0)), signed=True),
        "status": status,
        "risk": "Com custo" if cost > 0 else "Sem custo",
        "bar_width": round(safe_div(abs(cost), max_cost) * 100, 1) if max_cost else 0,
        "month_values": {},
        "month_values_fmt": {},
    }


def _group_production_by(records: List[Dict[str, Any]], key: str, total_cost: float, limit: int = 12) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for rec in records:
        label = str(rec.get(key, "") or "Não informado")
        item = grouped.setdefault(label, {
            "label": label,
            "records": 0,
            "active_records": 0,
            "cost": 0.0,
            "admin_cost": 0.0,
            "cmv": 0.0,
            "output": 0.0,
            "input": 0.0,
            "difference": 0.0,
            "variation": 0.0,
            "break_production": 0.0,
            "break_output": 0.0,
        })
        cost = parse_number(rec.get("CustoProdução", 0))
        item["records"] += 1
        item["active_records"] += 1 if cost else 0
        item["cost"] += cost
        item["admin_cost"] += parse_number(rec.get("CustoAdmin.", 0))
        item["cmv"] += parse_number(rec.get("Total CMV", 0))
        item["output"] += parse_number(rec.get("Total Saída", 0))
        item["input"] += parse_number(rec.get("Total Entrada", 0))
        item["difference"] += parse_number(rec.get("Diferença", 0))
        item["variation"] += parse_number(rec.get("TotalVariação", 0))
        item["break_production"] += parse_number(rec.get("QuebraProdução", 0))
        item["break_output"] += parse_number(rec.get("QuebraSaída", 0))

    groups = sorted(grouped.values(), key=lambda item: abs(item["cost"]), reverse=True)[:limit]
    max_cost = max([abs(item["cost"]) for item in groups] + [1])
    for item in groups:
        item["cost_fmt"] = brl(item["cost"])
        item["admin_cost_fmt"] = brl(item["admin_cost"])
        item["cmv_fmt"] = brl(item["cmv"], signed=True)
        item["output_fmt"] = brl(item["output"], signed=True)
        item["input_fmt"] = brl(item["input"], signed=True)
        item["difference_fmt"] = brl(item["difference"], signed=True)
        item["variation_fmt"] = brl(item["variation"], signed=True)
        item["break_production_fmt"] = brl(item["break_production"], signed=True)
        item["break_output_fmt"] = brl(item["break_output"], signed=True)
        item["share_pct"] = round(safe_div(item["cost"], total_cost) * 100, 1) if total_cost else 0
        item["share_pct_fmt"] = pct(item["share_pct"])
        item["bar_width"] = round(safe_div(abs(item["cost"]), max_cost) * 100, 1) if max_cost else 0
        item["status"] = "positivo" if item["cost"] > 0 else "zerado"
    return groups


def build_production_cost_analysis(records_raw: List[Dict[str, Any]], meta: Dict[str, Any]) -> Dict[str, Any]:
    """Build the Custo de Produção dashboard from already-normalized records."""
    total_cost = _sum_record_metric(records_raw, "CustoProdução")
    total_admin = _sum_record_metric(records_raw, "CustoAdmin.")
    total_cmv = _sum_record_metric(records_raw, "Total CMV")
    total_output = _sum_record_metric(records_raw, "Total Saída")
    total_input = _sum_record_metric(records_raw, "Total Entrada")
    total_difference = _sum_record_metric(records_raw, "Diferença")
    total_variation = _sum_record_metric(records_raw, "TotalVariação")
    total_break_prod = _sum_record_metric(records_raw, "QuebraProdução")
    total_break_output = _sum_record_metric(records_raw, "QuebraSaída")

    max_record_cost = max([abs(parse_number(rec.get("CustoProdução", 0))) for rec in records_raw] + [1])
    records = [_format_production_record(rec, max_record_cost) for rec in records_raw]
    active_records = [rec for rec in records if abs(rec["custo_producao"]) > 0]

    line_groups = _group_production_by(records_raw, "linha", total_cost, limit=20)
    daily_groups = _group_production_by(records_raw, "data", total_cost, limit=999)
    daily_groups = sorted(daily_groups, key=lambda item: _sort_full_date_label(item["label"]))
    daily_costs = [item["cost"] for item in daily_groups]
    daily_labels = [item["label"][:5] for item in daily_groups]
    max_daily_cost = max([abs(item["cost"]) for item in daily_groups] + [1])
    for item in daily_groups:
        item["height"] = max(8, round(safe_div(abs(item["cost"]), max_daily_cost) * 100, 1)) if max_daily_cost else 8

    top_records = sorted(records, key=lambda rec: abs(rec["custo_producao"]), reverse=True)[:20]
    active_days = len([item for item in daily_groups if abs(item["cost"]) > 0])
    day_count = len(daily_groups)
    top_line = line_groups[0] if line_groups else None
    top_day = max(daily_groups, key=lambda item: abs(item["cost"])) if daily_groups else None

    production = {
        "line_groups": line_groups,
        "daily_summary": daily_groups,
        "top_records": top_records,
        "trend": {
            "values": daily_costs,
            "labels": daily_labels,
            "points": make_trend_points(daily_costs),
            "point_objects": make_trend_point_objects(daily_costs, daily_labels),
        },
        "breakdown": [
            {"label": "CustoProdução", "value": total_cost, "value_fmt": brl(total_cost), "status": "positivo" if total_cost >= 0 else "negativo"},
            {"label": "CustoAdmin.", "value": total_admin, "value_fmt": brl(total_admin, signed=True), "status": "positivo" if total_admin >= 0 else "negativo"},
            {"label": "QuebraProdução", "value": total_break_prod, "value_fmt": brl(total_break_prod, signed=True), "status": "positivo" if total_break_prod >= 0 else "negativo"},
            {"label": "QuebraSaída", "value": total_break_output, "value_fmt": brl(total_break_output, signed=True), "status": "positivo" if total_break_output >= 0 else "negativo"},
            {"label": "Diferença", "value": total_difference, "value_fmt": brl(total_difference, signed=True), "status": "positivo" if total_difference >= 0 else "negativo"},
        ],
    }

    analysis = {
        "report_type": "production_cost",
        "meta": {
            **meta,
            "month_cols": [],
            "loja": records[0].get("empresa", "Não identificada") if records else "Não identificada",
        },
        "kpis": {
            "loja": records[0].get("empresa", "Não identificada") if records else "Não identificada",
            "total_rows": len(records),
            "active_records": len(active_records),
            "day_count": day_count,
            "active_days": active_days,
            "line_count": len(line_groups),
            "total_cost_production": total_cost,
            "total_cost_production_fmt": brl(total_cost),
            "total_cost_admin": total_admin,
            "total_cost_admin_fmt": brl(total_admin, signed=True),
            "total_cmv": total_cmv,
            "total_cmv_fmt": brl(total_cmv, signed=True),
            "total_output": total_output,
            "total_output_fmt": brl(total_output, signed=True),
            "total_input": total_input,
            "total_input_fmt": brl(total_input, signed=True),
            "net_difference": total_difference,
            "net_difference_fmt": brl(total_difference, signed=True),
            "total_variation": total_variation,
            "total_variation_fmt": brl(total_variation, signed=True),
            "break_production": total_break_prod,
            "break_production_fmt": brl(total_break_prod, signed=True),
            "break_output": total_break_output,
            "break_output_fmt": brl(total_break_output, signed=True),
            "cost_vs_cmv_pct": round(safe_div(total_cost, abs(total_cmv)) * 100, 1) if total_cmv else 0,
            "cost_vs_output_pct": round(safe_div(total_cost, abs(total_output)) * 100, 1) if total_output else 0,
            "cost_vs_cmv_pct_fmt": pct(round(safe_div(total_cost, abs(total_cmv)) * 100, 1) if total_cmv else 0),
            "cost_vs_output_pct_fmt": pct(round(safe_div(total_cost, abs(total_output)) * 100, 1) if total_output else 0),
            "avg_cost_day": safe_div(total_cost, day_count),
            "avg_cost_day_fmt": brl(safe_div(total_cost, day_count)),
            "top_line": top_line["label"] if top_line else "Não identificado",
            "top_line_cost_fmt": top_line["cost_fmt"] if top_line else "R$ 0,00",
            "top_day": top_day["label"] if top_day else "Não identificado",
            "top_day_cost_fmt": top_day["cost_fmt"] if top_day else "R$ 0,00",
        },
        "production": production,
        "records": records,
        "notes": [
            "Este arquivo foi tratado como Relatório de Equilíbrio, separado da análise de inventário rotativo.",
            "CustoProdução é apurado como movimento de produção por dia e por linha, não como divergência positiva/negativa.",
            "Use o ranking por linha para identificar onde o CPP concentra mais valor e compare com CMV, saída e diferença.",
        ],
    }
    return analysis


def analyze_production_cost(file_path: str | Path) -> Dict[str, Any]:
    records_raw, meta = prepare_production_cost_records(file_path)
    return build_production_cost_analysis(records_raw, meta)


def make_production_row_key(row: Dict[str, Any]) -> str:
    parts = [row.get("data", ""), row.get("empresa", ""), row.get("linha", "")]
    return "|".join(normalize_text(part) for part in parts)


def empty_production_store() -> Dict[str, Any]:
    return {"version": 1, "source_files": [], "rows": {}}


def load_production_store(path: str | Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return empty_production_store()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_production_store()
    if not isinstance(data, dict):
        return empty_production_store()
    # Migração simples caso alguma versão antiga tenha usado lista em "records".
    if "rows" not in data and isinstance(data.get("records"), list):
        rows = {}
        for rec in data.get("records", []):
            key = make_production_row_key(rec)
            if key:
                rows[key] = rec
        data["rows"] = rows
    if "rows" not in data:
        return empty_production_store()
    data.setdefault("source_files", [])
    return data


def save_production_store(store: Dict[str, Any], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def add_file_to_production_store(store: Dict[str, Any], file_path: str | Path, source_file: str | None = None) -> Dict[str, Any]:
    """Add a Relatório de Equilíbrio to the saved production-cost history.

    The key Data + Empresa + Linha is replaced by the newest import. This avoids
    duplicate counting when the same period is imported again.
    """
    records, meta = prepare_production_cost_records(file_path)
    source_name = source_file or Path(file_path).name
    store.setdefault("version", 1)
    store.setdefault("source_files", [])
    store.setdefault("rows", {})

    imported_dates = sorted({str(rec.get("data", "")) for rec in records if str(rec.get("data", "")).strip()}, key=_sort_full_date_label)
    total_cost = _sum_record_metric(records, "CustoProdução")
    for rec in records:
        key = make_production_row_key(rec)
        if not key:
            continue
        rec = dict(rec)
        rec["source_file"] = source_name
        store["rows"][key] = rec

    store["source_files"].append({
        "filename": source_name,
        "dates": imported_dates,
        "rows": len(records),
        "total_cost": total_cost,
        "total_cost_fmt": brl(total_cost),
    })
    return store


def production_store_records(store: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = store.get("rows", {})
    if isinstance(rows, dict):
        return list(rows.values())
    if isinstance(rows, list):
        return rows
    return []


def analyze_production_cost_store(store: Dict[str, Any]) -> Dict[str, Any]:
    records_raw = production_store_records(store)
    if not records_raw:
        raise RuntimeError("Não há histórico de Custo de Produção salvo.")

    metric_cols = sorted({key for rec in records_raw for key in rec.keys() if key not in {"data", "empresa", "linha", "source_file"}})
    meta = {
        "sheet_name": "Histórico acumulado de Custo de Produção",
        "header_row": 1,
        "date_col": "data",
        "metric_cols": metric_cols,
        "linha_col": "linha",
        "report_title": "Relatório de Equilíbrio acumulado",
        "is_accumulated": True,
    }
    analysis = build_production_cost_analysis(records_raw, meta)

    summary = summarize_production_store(store)
    analysis["store"] = {
        "file_count": summary["file_count"],
        "import_count": summary["import_count"],
        "source_files": store.get("source_files", []),
        "unique_filenames": summary["unique_filenames"],
        "month_count": summary["day_count"],
        "period_count": summary["day_count"],
        "period_label": "dia(s)",
        "month_range": summary["date_range"],
        "months": summary["dates_short"],
        "periods": summary["dates_short"],
    }
    analysis["notes"].insert(0, "Histórico acumulado de Custo de Produção: arquivos do Relatório de Equilíbrio ficam salvos por dia, empresa e linha.")
    return analysis


def summarize_production_store(store: Dict[str, Any]) -> Dict[str, Any]:
    records = production_store_records(store)
    dates = sorted({str(rec.get("data", "")) for rec in records if str(rec.get("data", "")).strip()}, key=_sort_full_date_label)
    source_files = store.get("source_files", [])
    unique = []
    seen = set()
    for item in source_files:
        name = item.get("filename", "")
        if name and name not in seen:
            seen.add(name)
            unique.append(name)
    total_cost = _sum_record_metric(records, "CustoProdução") if records else 0.0
    return {
        "has_data": bool(records),
        "row_count": len(records),
        "file_count": len(unique),
        "import_count": len(source_files),
        "unique_filenames": unique,
        "day_count": len(dates),
        "dates": dates,
        "dates_short": [date[:5] for date in dates],
        "date_range": f"{dates[0]} até {dates[-1]}" if dates else "Nenhuma data salva",
        "total_cost": total_cost,
        "total_cost_fmt": brl(total_cost),
        "latest_files": list(reversed(source_files[-5:])),
    }


def save_analysis_json(analysis: Dict[str, Any], path: str | Path) -> None:
    Path(path).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")


def load_analysis_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
