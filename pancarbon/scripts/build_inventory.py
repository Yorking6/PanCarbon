# -*- coding: utf-8 -*-
"""Stage 6 - formula-driven GHG inventory workbook (M2).

Creates the workbook from assets/inventory_template.json rather than copying a
historic workbook, so no organization data, residual years or broken external
links can leak in. Every emission cell is a formula referencing other cells;
no value or divisor is baked into a formula string.

Outputs:
    ghg_inventory.xlsx        formula-driven workbook
    formula_cache.json        expected values for every formula cell
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ghg_common import SKILL_ROOT, canonical_hash, jsonable, load_json, write_json

TEMPLATE_PATH = SKILL_ROOT / "assets" / "inventory_template.json"
DATA_ROW_START = 2
AIGC_NOTE = "AI-assisted generation; verify before external use"


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def _styles(template: dict) -> dict[str, Any]:
    styles = template.get("styles", {}) or {}
    return {
        "header": PatternFill("solid", fgColor=styles.get("header_fill", "DDEBF7")),
        "total": PatternFill("solid", fgColor=styles.get("total_fill", "F2F2F2")),
        "note": PatternFill("solid", fgColor=styles.get("note_fill", "FFF2CC")),
        "number_format": styles.get("number_format", "#,##0.00"),
    }


def _header(ws, labels: list[str], style: dict) -> None:
    for col, label in enumerate(labels, start=1):
        cell = ws.cell(row=1, column=col, value=label)
        cell.font = Font(bold=True)
        cell.fill = style["header"]
        cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"


def _widths(ws, labels: list[str]) -> None:
    for col, label in enumerate(labels, start=1):
        ws.column_dimensions[ws.cell(row=1, column=col).column_letter].width = max(
            12, min(34, len(str(label)) + 6))


def _put(ws, row: int, values: list[Any], style: dict, *, total: bool = False) -> None:
    for col, value in enumerate(values, start=1):
        cell = ws.cell(row=row, column=col, value=value)
        if total:
            cell.fill = style["total"]
            cell.font = Font(bold=True)
        if isinstance(value, float) or isinstance(value, Decimal):
            cell.number_format = style["number_format"]


def build(cfg: dict, ledger: dict, factors_lib: dict, classification: dict,
          matched: dict, results: dict, template: dict,
          out_path: Path, checks: dict | None = None) -> dict:
    """Create the workbook and its formula expectation cache."""
    style = _styles(template)
    wb = Workbook()
    wb.remove(wb.active)

    version = None
    for item in results.get("versions", []):
        if item.get("version_id") == results.get("final_version_id"):
            version = item
    if version is None:
        raise ValueError("results.json has no version matching final_version_id")
    result_by_row = {str(l.get("row_id")): l for l in version.get("lines", [])}
    total = _dec(version.get("total"))

    ledger_rows = ledger.get("rows", []) or []
    factor_rows = factors_lib.get("factors", []) or []
    matched_lines = matched.get("lines", []) or []

    # ---------- 1. boundary ----------
    ws = wb.create_sheet("boundary")
    _header(ws, ["field", "value"], style)
    boundary_pairs = [
        ("organization.name", cfg.get("organization", {}).get("name")),
        ("organization.boundary_description", cfg.get("organization", {}).get("boundary_description")),
        ("reporting_year", cfg.get("reporting_year")),
        ("base_year", cfg.get("base_year")),
        ("consolidation_method", cfg.get("consolidation_method")),
        ("gwp_version", cfg.get("gwp_version")),
        ("scope2.modes", ",".join(cfg.get("scope2", {}).get("modes", []))),
        ("scope3.enabled_categories", ",".join(
            str(x) for x in cfg.get("scope3", {}).get("enabled_categories", []))),
        ("currency.code", cfg.get("currency", {}).get("code")),
    ]
    for entity in cfg.get("entities", []):
        boundary_pairs.append((f"entity.{entity.get('id')}", entity.get("name")))
    for row, (key, value) in enumerate(boundary_pairs, start=DATA_ROW_START):
        _put(ws, row, [key, value], style)
    _widths(ws, ["field", "value"])

    # ---------- 2. source_identification ----------
    ws = wb.create_sheet("source_identification")
    labels = ["category_key", "applicable", "enabled", "row_ids", "reason_if_not"]
    _header(ws, labels, style)
    categories = classification.get("categories", {}) or {}
    for row, (key, info) in enumerate(categories.items(), start=DATA_ROW_START):
        _put(ws, row, [key, bool(info.get("applicable")), info.get("enabled"),
                       ",".join(info.get("row_ids", []) or []),
                       info.get("reason_if_not")], style)
    _widths(ws, labels)

    # ---------- 3. activity_data ----------
    ws = wb.create_sheet("activity_data")
    labels = ["row_id", "entity_ref", "source_key", "scope", "s3_category",
              "raw_value", "raw_unit", "normalized_value", "normalized_unit",
              "period_start", "period_end", "period_basis", "estimated",
              "evidence_files"]
    _header(ws, labels, style)
    activity_row_map: dict[str, int] = {}
    for index, row in enumerate(ledger_rows):
        excel_row = DATA_ROW_START + index
        activity_row_map[str(row.get("row_id"))] = excel_row
        period = row.get("period", {}) or {}
        raw, norm = row.get("raw", {}) or {}, row.get("normalized", {}) or {}
        _put(ws, excel_row, [
            row.get("row_id"), row.get("entity_ref"), row.get("source_key"),
            row.get("scope"), row.get("s3_category"),
            raw.get("value"), raw.get("unit"), norm.get("value"), norm.get("unit"),
            period.get("start"), period.get("end"), period.get("basis"),
            bool(row.get("estimated")),
            ",".join(row.get("evidence_files", []) or []),
        ], style)
    _widths(ws, labels)

    # ---------- 4. factors ----------
    ws = wb.create_sheet("factors")
    labels = ["factor_id", "value", "unit", "activity", "region", "year",
              "method", "source_name", "source_version", "gwp_version",
              "scale", "quality", "gwp_used"]
    _header(ws, labels, style)
    factor_row_map: dict[str, int] = {}
    gwp_by_factor: dict[str, Any] = {}
    for line in matched_lines:
        fid = str(line.get("factor_id"))
        if fid and fid not in gwp_by_factor and line.get("gwp") is not None:
            gwp_by_factor[fid] = line.get("gwp")
    for index, factor in enumerate(factor_rows):
        excel_row = DATA_ROW_START + index
        fid = str(factor.get("id"))
        factor_row_map[fid] = excel_row
        app = factor.get("applicability", {}) or {}
        source = factor.get("source", {}) or {}
        _put(ws, excel_row, [
            fid, factor.get("value"), factor.get("unit"), app.get("activity"),
            app.get("region"), app.get("year"), app.get("method"),
            source.get("name"), source.get("version"), factor.get("gwp_version"),
            factor.get("scale"), factor.get("quality"), gwp_by_factor.get(fid, 1),
        ], style)
    _widths(ws, labels)

    cache: dict[str, float] = {}
    formula_cells: list[str] = []

    def cell_key(sheet: str, col: str, row: int) -> str:
        return f"{sheet}!{col}{row}"

    def calc_lines_block(sheet_name: str, lines: list[dict]) -> int:
        """Write one emission calculation block; return last data row number."""
        ws = wb.create_sheet(sheet_name)
        labels = ["row_id", "scope_marker", "category", "source_key", "ad",
                  "ad_unit", "ef", "gwp", "scale", "tco2e", "share"]
        _header(ws, labels, style)
        last_row = DATA_ROW_START - 1
        for line in lines:
            row_no = last_row + 1
            rid = str(line.get("row_id"))
            ad_row = activity_row_map.get(rid)
            factor_row = factor_row_map.get(str(line.get("factor_id")))
            if ad_row is None or factor_row is None:
                raise ValueError(f"row {rid}: missing activity_data or factors row")
            formulas = {
                "E": f"=activity_data!H{ad_row}",
                "G": f"=factors!B{factor_row}",
                "H": f"=factors!M{factor_row}",
                "I": f"=factors!K{factor_row}",
                "J": f"=E{row_no}*G{row_no}*H{row_no}/I{row_no}",
                "K": f"=J{row_no}/summary!$B$5",
            }
            _put(ws, row_no, [
                rid, line.get("scope"), line.get("s3_category") or line.get("scope2_mode"),
                line.get("source_key"), formulas["E"], line.get("ad_unit"),
                formulas["G"], formulas["H"], formulas["I"],
                formulas["J"], formulas["K"],
            ], style)
            expected = _dec((result_by_row.get(rid) or {}).get("tco2e") or 0)
            for col, formula in formulas.items():
                key = cell_key(sheet_name, col, row_no)
                formula_cells.append(key)
                if col == "E":
                    cache[key] = float(_dec(line.get("ad")))
                elif col == "G":
                    cache[key] = float(_dec(line.get("ef")))
                elif col == "H":
                    cache[key] = float(_dec(line.get("gwp")))
                elif col == "I":
                    cache[key] = float(_dec(line.get("scale")))
                elif col == "J":
                    cache[key] = float(expected)
                elif col == "K":
                    cache[key] = float(expected / total) if total != 0 else 0.0
            last_row = row_no
        _widths(ws, labels)
        return last_row

    # ---------- 5. s12_calc ----------
    s1_lines = [l for l in matched_lines if l.get("scope") == "S1"]
    s2_loc = [l for l in matched_lines if l.get("scope") == "S2"
              and (l.get("scope2_mode") or "location_based") == "location_based"]
    s2_mkt = [l for l in matched_lines if l.get("scope") == "S2"
              and l.get("scope2_mode") == "market_based"]
    s12_lines = s1_lines + s2_loc + s2_mkt
    last = calc_lines_block("s12_calc", s12_lines)
    ws = wb["s12_calc"]

    def s12_subtotal(label: str, start: int, end: int, expected: float) -> int:
        nonlocal last
        last += 1
        formula = f"=SUM(J{start}:J{end})" if end >= start else "=0"
        _put(ws, last, [label, "", "", "", "", "", "", "", "", formula, ""],
             style, total=True)
        key = cell_key("s12_calc", "J", last)
        formula_cells.append(key)
        cache[key] = expected
        return last

    s1_total_row = s12_subtotal("S1 subtotal", DATA_ROW_START,
                                DATA_ROW_START + len(s1_lines) - 1,
                                float(_dec(version["by_scope"]["S1"])))
    s2_loc_total_row = s12_subtotal(
        "S2 location subtotal", DATA_ROW_START + len(s1_lines),
        DATA_ROW_START + len(s1_lines) + len(s2_loc) - 1,
        float(_dec(version["by_scope"]["S2"]["location_based"])))
    s2_mkt_total_row = s12_subtotal(
        "S2 market subtotal",
        DATA_ROW_START + len(s1_lines) + len(s2_loc),
        DATA_ROW_START + len(s1_lines) + len(s2_loc) + len(s2_mkt) - 1,
        float(_dec(version["by_scope"]["S2"]["market_based"])))

    # ---------- 6. repeated Scope 3 category sheets ----------
    s3_by_cat: dict[int, list[dict]] = {}
    for line in matched_lines:
        if line.get("scope") == "S3" and isinstance(line.get("s3_category"), int):
            s3_by_cat.setdefault(line["s3_category"], []).append(line)
    s3_subtotal_refs: list[tuple[str, int]] = []
    for cat in sorted(s3_by_cat):
        sheet_name = f"S3_C{cat}"
        last_s3 = calc_lines_block(sheet_name, s3_by_cat[cat])
        ws = wb[sheet_name]
        subtotal_row = last_s3 + 1
        formula = f"=SUM(J{DATA_ROW_START}:J{last_s3})"
        _put(ws, subtotal_row, [f"S3-{cat} subtotal", "", "", "", "", "", "", "",
                                "", formula, ""], style, total=True)
        key = cell_key(sheet_name, "J", subtotal_row)
        formula_cells.append(key)
        cache[key] = float(_dec(version["by_scope"]["S3"].get(f"S3-{cat}", 0)))
        s3_subtotal_refs.append((sheet_name, subtotal_row))

    # ---------- 7. data_quality ----------
    ws = wb.create_sheet("data_quality")
    labels = ["row_id", "activity_grade", "factor_grade", "instrument_grade",
              "activity_score", "factor_score", "instrument_score",
              "average_score", "share", "weighted_score", "note"]
    _header(ws, labels, style)
    scores = (cfg.get("quality", {}) or {}).get("scores", {}) or {}
    for index, row in enumerate(ledger_rows):
        excel_row = DATA_ROW_START + index
        rid = str(row.get("row_id"))
        dq = row.get("data_quality", {}) or {}
        a, f, i = dq.get("activity"), dq.get("factor"), dq.get("instrument")
        av = scores.get(f"activity.{a}")
        fv = scores.get(f"factor.{f}")
        iv = scores.get(f"instrument.{i}")
        share = (result_by_row.get(rid) or {}).get("share")
        if None in (av, fv, iv):
            # Score tables are supplied by configuration, never hardcoded here.
            _put(ws, excel_row, [rid, a, f, i, "N/A", "N/A", "N/A",
                                 "N/A", "N/A", "N/A",
                                 "score table not supplied in org_config.quality.scores"],
                 style)
        else:
            avg = (av + fv + iv) / 3
            share_value = float(_dec(share or 0))
            _put(ws, excel_row, [rid, a, f, i, av, fv, iv, avg,
                                 share_value, avg * share_value, ""], style)
    _widths(ws, labels)

    # ---------- 8. quality_gaps ----------
    ws = wb.create_sheet("quality_gaps")
    gaps: list[list[Any]] = []
    gap_id = 0

    def add_gap(category: str, item: str, description: str,
                treatment: str, impact: str, source: str) -> None:
        nonlocal gap_id
        gap_id += 1
        gaps.append([f"G{gap_id:02d}", category, item, description,
                     treatment, impact, source])

    for row in ledger_rows:
        rid = str(row.get("row_id"))
        if row.get("estimated"):
            add_gap("activity_data", rid, "estimated activity value",
                    str(row.get("estimation_note") or "reason missing"),
                    "review before external use", "activity_ledger")
        if row.get("carry_over_from"):
            add_gap("carry_over", rid, "value carried over from an earlier run",
                    str(row.get("estimation_note") or "reason missing"),
                    "re-quantify when source data is available", "activity_ledger")
        if (row.get("raw", {}) or {}).get("confidence") == "low":
            add_gap("evidence", rid, "low-confidence voucher reading",
                    "human confirmation recorded", "verify voucher image", "activity_ledger")
    for line in matched_lines:
        if line.get("status") != "matched":
            add_gap("method", str(line.get("row_id")),
                    f"line status {line.get('status')}",
                    "candidate factors or method decision required",
                    "row excluded from totals", "matched")
    if not scores:
        add_gap("quality", "score_table", "data quality score table not configured",
                "supply org_config.quality.scores", "data_quality sheet shows N/A", "org_config")
    if checks:
        for warning in checks.get("warnings", []) or []:
            if warning.get("rule") != "V15":
                add_gap("check", warning.get("rule", ""), warning.get("message", ""),
                        "review finding", "informational", "checks")
    for rule, milestone in (checks or {}).get("rules_deferred", {}).items():
        if isinstance(milestone, str):
            add_gap("deferred_rule", rule, f"rule deferred to {milestone}",
                    "implement in the target milestone", "not yet verified", "checks")

    header_row = 1
    _header(ws, ["gap_id", "category", "data_item", "description",
                 "treatment", "impact", "source"], style)
    row_no = header_row + 1
    for gap in gaps:
        _put(ws, row_no, gap, style)
        row_no += 1
    row_no += 1
    _put(ws, row_no, ["METHOD CHANGES", "", "", "", "", "", ""], style, total=True)
    row_no += 1
    for item in results.get("versions", []):
        _put(ws, row_no, [item.get("version_id"), item.get("method"),
                          item.get("status"), str(item.get("note") or ""),
                          "", "", "results.versions"], style)
        row_no += 1
    row_no += 1
    _put(ws, row_no, ["TOTALS", "tco2e", "", "", "", "", ""], style, total=True)
    row_no += 1
    for label, ref in (("S1", "B2"), ("S2 location_based", "B3"),
                       ("S3", "B4"), ("total", "B5"), ("S2 market_based", "B6")):
        _put(ws, row_no, [label, f"=summary!{ref}", "", "", "", "", "summary"], style)
        key = cell_key("quality_gaps", "B", row_no)
        formula_cells.append(key)
        row_no += 1
    _widths(ws, ["gap_id", "category", "data_item", "description",
                 "treatment", "impact", "source"])

    # ---------- 9. summary ----------
    ws = wb.create_sheet("summary")
    _header(ws, ["scope", "tco2e", "share"], style)
    s3_formula = ("=" + "+".join(f"'{name}'!J{r}" for name, r in s3_subtotal_refs)
                  if s3_subtotal_refs else "=0")
    summary_rows = [
        ("S1", f"=s12_calc!J{s1_total_row}", float(_dec(version["by_scope"]["S1"]))),
        ("S2 location_based", f"=s12_calc!J{s2_loc_total_row}",
         float(_dec(version["by_scope"]["S2"]["location_based"]))),
        ("S3", s3_formula, float(sum(_dec(x) for x in version["by_scope"]["S3"].values()))),
        ("total", "=B2+B3+B4", float(total)),
        ("S2 market_based", f"=s12_calc!J{s2_mkt_total_row}",
         float(_dec(version["by_scope"]["S2"]["market_based"]))),
    ]
    for index, (label, formula, expected) in enumerate(summary_rows):
        row_no = DATA_ROW_START + index
        _put(ws, row_no, [label, formula, f"=B{row_no}/$B$5"], style,
             total=(label == "total"))
        key = cell_key("summary", "B", row_no)
        formula_cells.append(key)
        cache[key] = expected
        share_key = cell_key("summary", "C", row_no)
        formula_cells.append(share_key)
        cache[share_key] = float(_dec(expected) / total) if total != 0 else 0.0
    _widths(ws, ["scope", "tco2e", "share"])

    # quality_gaps B-column references resolve to the same summary cells.
    qg = wb["quality_gaps"]
    for row in qg.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("=summary!B"):
                ref = cell.value.split("!")[1]
                key = cell_key("quality_gaps", "B", cell.row)
                cache[key] = cache.get(cell_key("summary", "B", int(ref[1:])), 0.0)

    # ---------- workbook hygiene ----------
    wb._external_links = []
    wb.properties.title = "GHG emission inventory (AI-assisted generation)"
    wb.properties.creator = "PanCarbon skill"
    wb.properties.description = AIGC_NOTE
    wb.properties.keywords = "GHG,inventory,AI-generated"
    wb.properties.category = "GHG inventory"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))

    payload = {
        "workbook": out_path.name,
        "formula_pattern": template.get("formula_pattern"),
        "config_hash": canonical_hash(cfg),
        "final_version_id": results.get("final_version_id"),
        "sheets": list(wb.sheetnames),
        "formula_cell_count": len(formula_cells),
        "formula_cells": sorted(set(formula_cells)),
        "cells": cache,
        "key_cells": {
            "S1": "summary!B2",
            "S2_location_based": "summary!B3",
            "S3": "summary!B4",
            "total": "summary!B5",
            "S2_market_based": "summary!B6",
            "s1_subtotal": f"s12_calc!J{s1_total_row}",
            "s2_location_subtotal": f"s12_calc!J{s2_loc_total_row}",
            "s2_market_subtotal": f"s12_calc!J{s2_mkt_total_row}",
        },
        "quality_gaps": len(gaps),
        "aigc_note": AIGC_NOTE,
    }
    write_json(out_path.parent / "formula_cache.json", jsonable(payload))
    return payload


def build_from_run(run: Path, include_checks: bool = False) -> dict:
    """Convenience loader following the run-directory filename convention.

    Stage 6 runs before Stage 7 in the pipeline, so a stale checks.json from a
    previous run is ignored by default; gaps are derived from the signed ledger
    and the matched results instead.
    """
    cfg = load_json(run / "org_config.json")
    ledger = load_json(run / "activity_ledger.json")
    factors = load_json(run / "factor_library.json")
    classification = load_json(run / "classification.json")
    matched = load_json(run / "matched.json")
    results = load_json(run / "results.json")
    checks_path = run / "checks.json"
    checks = (load_json(checks_path)
              if include_checks and checks_path.is_file() else None)
    template = load_json(TEMPLATE_PATH)
    return build(cfg, ledger, factors, classification, matched, results,
                 template, run / "ghg_inventory.xlsx", checks)
