# -*- coding: utf-8 -*-
"""Stage 7 - reconciliation rule engine (M1 subset).

The M1 subset covers every rule that does not need an xlsx workbook or a
generated report. V06/V07/V09/V12/V13/V20 are registered as deferred to M2/M3
so their absence is explicit rather than silent.

V01 uses an independent Fraction-based recomputation, giving a dual-track
reconciliation against the Decimal path used by compute.py.
"""
from __future__ import annotations

import shutil
import zipfile
from fractions import Fraction
from pathlib import Path
from typing import Any

from ghg_common import SKILL_ROOT, canonical_hash
from normalize_units import dimension_compatible, scale_matches

TOLERANCE = Fraction(1, 10 ** 9)
FLOAT_TOLERANCE = 1e-9
DEFERRED_ALWAYS: dict[str, str] = {}
DEFERRED_WITHOUT_WORKBOOK = {
    "V06": "M2 - workbook totals vs results.json",
    "V09": "M2 - workbook recalculation and external links",
}
DEFERRED_WITHOUT_REPORTS = {
    "V07": "M3 - CN/EN numeric parity",
    "V12": "M3 - report mode B sign-off guard",
    "V13": "M3 - unresolved report placeholders",
}
V20_DEFERRED = {
    "V20": "M5 - delivery completeness requires workbook, reports and a run directory"
}
# checks.json is excluded: it is written by this very run.
V20_REQUIRED_FILES = (
    "org_config.json", "factor_library.json", "activity_ledger.json",
    "classification.json", "matched.json", "results.json",
    "ghg_inventory.xlsx", "formula_cache.json", "report_manifest.json",
)
HEURISTIC_KEYWORDS = ("total", "合计", "sum", "grand")
V14_SCAN_EXCLUDE = {"recalc_check.py"}


def _frac(value: Any) -> Fraction | None:
    if value is None:
        return None
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None


def _close(a: Fraction | None, b: Fraction | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCE


def _err(errors: list, rule: str, obj: str, observed: Any, expected: Any, msg: str) -> None:
    errors.append({"rule": rule, "object": obj,
                   "observed": str(observed), "expected": str(expected), "message": msg})


def _warn(warnings: list, rule: str, obj: str, msg: str) -> None:
    warnings.append({"rule": rule, "object": obj, "message": msg})


def rule_v01(results: dict, errors: list, warnings: list) -> dict[str, Any]:
    """Independent Fraction recomputation of every non-null line."""
    checked = 0
    max_delta = Fraction(0)
    for version in results.get("versions", []):
        for line in version.get("lines", []):
            if line.get("tco2e") is None:
                continue
            ad, ef = _frac(line.get("ad")), _frac(line.get("ef"))
            gwp, scale = _frac(line.get("gwp")), _frac(line.get("scale"))
            actual = _frac(line.get("tco2e"))
            if None in (ad, ef, gwp, scale, actual) or scale == 0:
                _err(errors, "V01", str(line.get("row_id")), "unusable operand", "numeric",
                     "line operands cannot be recomputed")
                continue
            expected = ad * ef * gwp / scale
            delta = abs(expected - actual)
            max_delta = max(max_delta, delta)
            checked += 1
            if delta > TOLERANCE:
                _err(errors, "V01", str(line.get("row_id")), str(float(actual)),
                     str(float(expected)), "tco2e fails independent recomputation")
            for warning in line.get("warnings", []) or []:
                _warn(warnings, "V01", str(line.get("row_id")), str(warning))
    return {"status": "match" if not any(e["rule"] == "V01" for e in errors) else "mismatch",
            "lines_checked": checked, "max_delta": str(max_delta)}


def rule_v02(matched: dict, errors: list) -> None:
    for line in matched.get("lines", []):
        if line.get("status") != "matched":
            continue
        contract = scale_matches(str(line.get("ad_unit") or ""),
                                 str(line.get("ef_unit") or ""),
                                 line.get("scale"))
        if not contract.get("match"):
            _err(errors, "V02", str(line.get("row_id")), line.get("scale"),
                 contract.get("scale"),
                 "scale or dimension contract: " + str(contract.get("reason")))
        else:
            dim = dimension_compatible(str(line.get("ad_unit") or ""),
                                       str(line.get("ef_unit") or ""))
            if not dim.get("compatible"):
                _err(errors, "V02", str(line.get("row_id")), line.get("ef_unit"),
                     "reconcilable unit", str(dim.get("reason")))


def rule_v03_v04(results: dict, errors: list) -> None:
    for version in results.get("versions", []):
        vid = str(version.get("version_id"))
        by_cat = version.get("by_category", {}) or {}
        by_scope = version.get("by_scope", {}) or {}
        s1 = _frac(by_scope.get("S1"))
        s2_obj = by_scope.get("S2", {}) or {}
        s2_loc = _frac(s2_obj.get("location_based"))
        s3_obj = by_scope.get("S3", {}) or {}
        s3_sum = sum((_frac(v) or Fraction(0) for v in s3_obj.values()), Fraction(0))
        total = _frac(version.get("total"))

        cat_sum = (_frac(by_cat.get("S1")) or Fraction(0)) + \
                  (_frac(by_cat.get("S2")) or Fraction(0)) + \
                  sum((_frac(v) or Fraction(0) for k, v in by_cat.items()
                       if str(k).startswith("S3-")), Fraction(0))
        if not _close(cat_sum, s1 + s2_loc + s3_sum if None not in (s1, s2_loc) else None):
            _err(errors, "V03", vid, str(float(cat_sum)), "by_scope sum",
                 "by_category detail does not reconcile with by_scope subtotals")
        for key, value in s3_obj.items():
            if not _close(_frac(by_cat.get(key)), _frac(value)):
                _err(errors, "V03", f"{vid}/{key}", str(by_cat.get(key)), str(value),
                     "category subtotal mismatch")
        if not _close(total, (s1 or Fraction(0)) + (s2_loc or Fraction(0)) + s3_sum):
            _err(errors, "V04", vid, str(version.get("total")),
                 str(float((s1 or Fraction(0)) + (s2_loc or Fraction(0)) + s3_sum)),
                 "total must equal S1 + S2(location-based) + all S3 categories")


def rule_v05(results: dict, errors: list) -> None:
    for version in results.get("versions", []):
        total = _frac(version.get("total"))
        if total in (None, 0):
            continue
        for line in version.get("lines", []):
            share, value = _frac(line.get("share")), _frac(line.get("tco2e"))
            if share is None or value is None:
                continue
            if not _close(share, value / total):
                _err(errors, "V05", str(line.get("row_id")), str(line.get("share")),
                     str(float(value / total)),
                     "share denominator differs from the current report total")


def rule_v08(results: dict, errors: list) -> None:
    finals = [v.get("version_id") for v in results.get("versions", [])
              if v.get("status") == "final"]
    if len(finals) != 1:
        _err(errors, "V08", "versions", str(finals), "exactly one final",
             "multiple or zero final versions; reports must cite one authoritative result")
    target = results.get("final_version_id")
    if target not in finals:
        _err(errors, "V08", "final_version_id", str(target), str(finals),
             "final_version_id does not point to a final version")


def rule_v10(cfg: dict, matched: dict, library: dict, errors: list, warnings: list) -> None:
    factors = {f.get("id"): f for f in library.get("factors", [])}
    entities = {e.get("id"): e for e in cfg.get("entities", [])}
    year = cfg.get("reporting_year")
    for line in matched.get("lines", []):
        factor = factors.get(line.get("factor_id"))
        if factor is None:
            continue
        rid = str(line.get("row_id"))
        if factor.get("gwp_version") not in (cfg.get("gwp_version"), "not_applicable"):
            _err(errors, "V10", rid, str(factor.get("gwp_version")),
                 str(cfg.get("gwp_version")), "factor GWP version mismatch")
        app = factor.get("applicability", {}) or {}
        if app.get("year") not in (None, "", "*", year):
            _err(errors, "V10", rid, str(app.get("year")), str(year),
                 "factor applicability year mismatch")
        region = (entities.get(line.get("entity_ref")) or {}).get("grid_region_ref")
        if app.get("region") not in (None, "", "*") and app.get("region") != region:
            _err(errors, "V10", rid, str(app.get("region")), str(region),
                 "factor region does not match the entity")
        if not str((factor.get("source") or {}).get("version") or "").strip():
            _err(errors, "V10", rid, "empty", "non-empty",
                 "factor source version is mandatory")
        if line.get("status") != "matched":
            _warn(warnings, "V10", rid,
                  f"line status {line.get('status')!r} produced no emission")


def rule_v11(ledger: dict, errors: list) -> None:
    for row in ledger.get("rows", []):
        conf = row.get("confirmation", {}) or {}
        if not str(conf.get("signed_by") or "").strip() or not str(conf.get("signed_at") or "").strip():
            _err(errors, "V11", str(row.get("row_id")), "unsigned", "signed",
                 "calculation input is not signed by a human")


def rule_v14(errors: list, warnings: list) -> dict[str, Any]:
    """Detect total-picking heuristics in the calculation scripts."""
    scripts = SKILL_ROOT / "scripts"
    scanned: list[str] = []
    hits: list[str] = []
    for path in sorted(scripts.rglob("*.py")):
        if path.name in V14_SCAN_EXCLUDE or "__pycache__" in path.parts:
            continue
        scanned.append(path.name)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            lowered = line.lower()
            if "max(" in lowered and any(k in lowered for k in HEURISTIC_KEYWORDS):
                hits.append(f"{path.name}:{number}")
    for hit in hits:
        _err(errors, "V14", hit, "max() near a total", "explicit subtotal field",
             "heuristic total extraction is forbidden")
    return {"files_scanned": len(scanned), "hits": hits,
            "status": "clean" if not hits else "violation"}


def rule_v15_v16_v17(cfg: dict, ledger: dict, matched: dict,
                     results: dict, warnings: list) -> None:
    version = None
    for item in results.get("versions", []):
        if item.get("version_id") == results.get("final_version_id"):
            version = item
    if version:
        s2 = version.get("by_scope", {}).get("S2", {}) or {}
        loc, market = _frac(s2.get("location_based")), _frac(s2.get("market_based"))
        if loc is not None and market is not None and loc != market:
            _warn(warnings, "V15", str(version.get("version_id")),
                  "Scope 2 location-based and market-based differ; explain in the report")
        if loc is not None and market is not None and loc == market:
            _warn(warnings, "V15", str(version.get("version_id")),
                  "market-based result mirrors location-based; verify market instruments")

        threshold = cfg.get("quality", {}).get("volatility_warn_pct")
        totals = [(v.get("version_id"), _frac(v.get("total")))
                  for v in results.get("versions", [])]
        usable = [(k, t) for k, t in totals if t not in (None, 0)]
        if threshold and len(usable) > 1:
            base = usable[0][1]
            for vid, value in usable[1:]:
                change = abs((value - base) / base) * 100
                if change > Fraction(str(threshold)):
                    _warn(warnings, "V16", str(vid),
                          f"total differs from {usable[0][0]} by {float(change)} percent")

    rows = ledger.get("rows", []) or []
    estimated = [r.get("row_id") for r in rows if r.get("estimated")]
    if rows and len(estimated) * 2 > len(rows):
        _warn(warnings, "V17", "ledger", "more than half of the rows are estimates")
    for row in rows:
        if row.get("carry_over_from") and not row.get("estimation_note"):
            _warn(warnings, "V17", str(row.get("row_id")), "carry-over lacks a reason")
    for line in matched.get("lines", []):
        if line.get("status") != "matched":
            _warn(warnings, "V17", str(line.get("row_id")),
                  f"unmatched line ({line.get('status')}) excluded from totals")


def rule_v19(cfg: dict, ledger: dict, errors: list, warnings: list) -> None:
    year = cfg.get("reporting_year")
    for row in ledger.get("rows", []):
        period = row.get("period", {}) or {}
        rid = str(row.get("row_id"))
        start, end = str(period.get("start") or ""), str(period.get("end") or "")
        if start and end and start > end:
            _err(errors, "V19", rid, f"{start}..{end}", "start <= end", "inverted period")
        years = {text[:4] for text in (start, end) if len(text) >= 4 and text[:4].isdigit()}
        if year and years and str(year) not in years:
            _err(errors, "V19", rid, ",".join(sorted(years)), str(year),
                 "period lies outside the reporting year")
        if period.get("basis") == "billing" and not period.get("billing_note"):
            _warn(warnings, "V19", rid, "billing period without a billing_note")


def run_checks(cfg: dict, ledger: dict, matched: dict, library: dict,
               results: dict, workbook: dict | None = None,
               manifest: dict | None = None, phrases: dict | None = None,
               run: Path | None = None) -> dict:
    """Run the M1 rule subset plus whichever M2/M3 artifacts are available.

    Missing artifacts keep their rules explicitly deferred instead of being
    silently skipped.
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    deferred = dict(DEFERRED_ALWAYS)
    if workbook is None:
        deferred.update(DEFERRED_WITHOUT_WORKBOOK)
    if manifest is None:
        deferred.update(DEFERRED_WITHOUT_REPORTS)
    delivery_ready = (run is not None and workbook is not None
                      and manifest is not None)
    if not delivery_ready:
        deferred.update(V20_DEFERRED)
    parts = ["M1"]
    if workbook is not None:
        parts.append("M2")
    if manifest is not None:
        parts.append("M3")
    if delivery_ready:
        parts.append("M5")
    report: dict[str, Any] = {
        "stage": 7,
        "milestone": "+".join(parts),
        "status": "pass",
        "config_hash": canonical_hash(cfg),
        "rules_run": [],
        "rules_deferred": deferred,
        "errors": errors,
        "warnings": warnings,
    }

    if results.get("config_hash") != report["config_hash"]:
        _err(errors, "V10", "results.config_hash", results.get("config_hash"),
             report["config_hash"], "results do not match the active configuration")

    dual = rule_v01(results, errors, warnings)
    report["dual_track"] = dual
    rule_v02(matched, errors)
    rule_v03_v04(results, errors)
    rule_v05(results, errors)
    rule_v08(results, errors)
    rule_v10(cfg, matched, library, errors, warnings)
    rule_v11(ledger, errors)
    report["v14"] = rule_v14(errors, warnings)
    rule_v15_v16_v17(cfg, ledger, matched, results, warnings)
    rule_v19(cfg, ledger, errors, warnings)
    report["rules_run"] = ["V01", "V02", "V03", "V04", "V05", "V08",
                          "V10", "V11", "V14", "V15", "V16", "V17", "V19"]

    if workbook is not None or manifest is not None:
        rule_v06(results, errors, workbook, manifest)
        report["rules_run"].append("V06")
    if workbook is not None:
        report["v09"] = rule_v09(workbook, errors, warnings)
        report["rules_run"].append("V09")
    if manifest is not None:
        rule_v07(manifest, errors)
        rule_v12(manifest, errors, phrases=phrases, run=run)
        rule_v13(manifest, errors, run=run)
        report["rules_run"].extend(["V07", "V12", "V13"])
        report["reports_checked"] = len(manifest.get("documents", []))

    if delivery_ready:
        prior = [item for item in errors if item["rule"] != "V20"]
        rule_v20(run, manifest, errors, prior)
        report["rules_run"].append("V20")
        report["delivery_ready"] = not any(item["rule"] == "V20" for item in errors)

    report["status"] = "fail" if errors else "pass"
    return report


def _v06_workbook(results: dict, workbook: dict, errors: list) -> None:
    """Verify workbook totals and every emission line against results.json."""
    version = next((v for v in results.get("versions", [])
                    if v.get("version_id") == results.get("final_version_id")), None)
    if version is None:
        _err(errors, "V06", "results", "no final version", "one final version",
             "cannot reconcile workbook without a final result")
        return
    cells = workbook["cache"].get("cells", {}) or {}
    keys = workbook["cache"].get("key_cells", {}) or {}
    by_scope = version.get("by_scope", {}) or {}
    s3_sum = sum(float(v or 0) for v in (by_scope.get("S3", {}) or {}).values())
    expectations = [
        (keys.get("S1", "summary!B2"), float(by_scope.get("S1") or 0)),
        (keys.get("S2_location_based", "summary!B3"),
         float((by_scope.get("S2") or {}).get("location_based") or 0)),
        (keys.get("S3", "summary!B4"), s3_sum),
        (keys.get("total", "summary!B5"), float(version.get("total") or 0)),
        (keys.get("S2_market_based", "summary!B6"),
         float((by_scope.get("S2") or {}).get("market_based") or 0)),
    ]
    for cell, expected in expectations:
        got = cells.get(cell)
        if got is None or abs(float(got) - expected) > FLOAT_TOLERANCE:
            _err(errors, "V06", str(cell), str(got), str(expected),
                 "workbook total does not match results.json")

    from openpyxl import load_workbook

    lines_by_id = {str(l.get("row_id")): l.get("tco2e") for l in version.get("lines", [])}
    wb = load_workbook(str(workbook["path"]), data_only=False)
    try:
        for name in wb.sheetnames:
            if name != "s12_calc" and not name.startswith("S3_C"):
                continue
            ws = wb[name]
            for row in range(2, ws.max_row + 1):
                rid = str(ws.cell(row=row, column=1).value or "")
                if rid not in lines_by_id:
                    continue  # subtotal row
                expected = lines_by_id[rid]
                if expected is None:
                    continue
                key = f"{name}!J{row}"
                got = cells.get(key)
                if got is None or abs(float(got) - float(expected)) > FLOAT_TOLERANCE:
                    _err(errors, "V06", key, str(got), str(expected),
                         "workbook emission line does not match results.json")
    finally:
        wb.close()


def _recalc_libreoffice(path: Path) -> dict[str, float] | None:
    import subprocess
    import tempfile
    from openpyxl import load_workbook

    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            done = subprocess.run(
                [exe, "--headless", "--convert-to", "xlsx", "--outdir", tmp, str(path)],
                capture_output=True, timeout=120)
            if done.returncode != 0:
                return None
            out = Path(tmp) / path.name
            if not out.is_file():
                return None
            wb = load_workbook(str(out), data_only=True)
            try:
                values = {}
                for ws in wb.worksheets:
                    for row in ws.iter_rows():
                        for cell in row:
                            if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool):
                                values[f"{ws.title}!{cell.coordinate}"] = float(cell.value)
                return values or None
            finally:
                wb.close()
    except (OSError, subprocess.SubprocessError):
        return None


def _recalc_formulas(path: Path) -> dict[str, float] | None:
    try:
        import formulas
    except ImportError:
        return None
    try:
        solution = formulas.ExcelModel().loads(str(path)).finish().calculate()
    except Exception:  # noqa: BLE001 - engine failure falls through to the next
        return None
    values: dict[str, float] = {}
    for key, raw in solution.items():
        if "]" not in key or "!" not in key:
            continue
        try:
            sheet = key.split("]", 1)[1].split("'", 1)[0]
            coord = key.rsplit("!", 1)[1]
            candidate = getattr(raw, "value", raw)
            while hasattr(candidate, "__len__") and not isinstance(candidate, (str, bytes)):
                candidate = candidate[0]
            values[f"{sheet}!{coord}"] = float(candidate)
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
    return values or None


def _recalc_builtin(path: Path) -> dict[str, float] | None:
    from formula_eval import WorkbookEvaluator

    evaluator = WorkbookEvaluator(path)
    try:
        return evaluator.evaluate_all() or None
    except Exception:  # noqa: BLE001 - a failed engine is reported, not hidden
        return None
    finally:
        evaluator.close()


def rule_v09(workbook: dict, errors: list, warnings: list) -> dict[str, Any]:
    """Static formula hygiene plus independent recalculation."""
    from openpyxl import load_workbook

    path = Path(workbook["path"])
    cache = workbook["cache"]
    report: dict[str, Any] = {
        "engine": None, "formula_cells": 0, "cells_checked": 0,
        "max_delta": 0.0, "external_links": 0, "issues": [],
    }

    wb = load_workbook(str(path), data_only=False)
    formula_keys: list[str] = []
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        key = f"{ws.title}!{cell.coordinate}"
                        formula_keys.append(key)
                        if "#REF!" in cell.value:
                            report["issues"].append(f"{key}: #REF! broken reference")
                        if "[" in cell.value:
                            report["issues"].append(f"{key}: external link marker")
        report["external_links"] += len(wb._external_links or [])
    finally:
        wb.close()
    with zipfile.ZipFile(str(path)) as archive:
        report["external_links"] += sum(
            1 for name in archive.namelist() if "externalLinks" in name)
    report["formula_cells"] = len(formula_keys)

    for issue in report["issues"]:
        _err(errors, "V09", issue, "broken formula", "clean formula", issue)
    if report["external_links"]:
        _err(errors, "V09", "workbook", report["external_links"], 0,
             "external links are forbidden in the delivered inventory")
    declared = int(cache.get("formula_cell_count") or 0)
    if declared and len(formula_keys) != declared:
        _err(errors, "V09", "formula count", len(formula_keys), declared,
             "formula cell count differs from formula_cache.json")

    values: dict[str, float] | None = None
    for name, engine in (("libreoffice", _recalc_libreoffice),
                         ("formulas", _recalc_formulas),
                         ("builtin", _recalc_builtin)):
        values = engine(path)
        if values:
            report["engine"] = name
            break
    if not values:
        _err(errors, "V09", "recalculation", "no engine", "one working engine",
             "LibreOffice, formulas and the builtin evaluator all failed")
        return report

    normalized = {key.upper(): value for key, value in values.items()}
    expected_cells = cache.get("cells", {}) or {}
    biggest = 0.0
    for key, expected in expected_cells.items():
        got = normalized.get(key.upper())
        if got is None:
            _err(errors, "V09", key, "missing", str(expected),
                 "recalculation produced no value for this formula cell")
            continue
        delta = abs(float(got) - float(expected))
        if delta > biggest:
            biggest = delta
        report["cells_checked"] += 1
        if delta > FLOAT_TOLERANCE:
            _err(errors, "V09", key, str(got), str(expected),
                 "recalculated value differs from the deterministic cache")
    report["max_delta"] = biggest
    _warn(warnings, "V09", "workbook",
          f"recalculated with {report['engine']} across {report['cells_checked']} cells")
    return report


def _v06_reports(results: dict, manifest: dict, errors: list) -> None:
    """Verify that report summary figures equal results.json."""
    version = next((v for v in results.get("versions", [])
                    if v.get("version_id") == results.get("final_version_id")), None)
    if version is None:
        return
    by_scope = version.get("by_scope", {}) or {}
    s2 = by_scope.get("S2", {}) or {}
    expected = {
        "total": float(version.get("total") or 0),
        "S1": float(by_scope.get("S1") or 0),
        "S2_location": float(s2.get("location_based") or 0),
        "S2_market": float(s2.get("market_based") or 0),
        "S3": sum(float(v or 0) for v in (by_scope.get("S3", {}) or {}).values()),
    }
    if manifest.get("final_version_id") != results.get("final_version_id"):
        _err(errors, "V06", "report manifest", manifest.get("final_version_id"),
             results.get("final_version_id"), "report cites a non-final version")
    for document in manifest.get("documents", []):
        for key, value in expected.items():
            got = (document.get("fields") or {}).get(key)
            if got is None or abs(float(got) - value) > FLOAT_TOLERANCE:
                _err(errors, "V06", f"{document.get('path')}:{key}", str(got),
                     str(value), "report summary figure differs from results.json")


def rule_v06(results: dict, errors: list,
             workbook: dict | None = None,
             manifest: dict | None = None) -> None:
    """Dispatch V06 over whichever artifacts are available."""
    if workbook is not None:
        _v06_workbook(results, workbook, errors)
    if manifest is not None:
        _v06_reports(results, manifest, errors)


def rule_v07(manifest: dict, errors: list) -> None:
    """CN/EN numeric parity across every rendered field and chart."""
    if not manifest.get("phrases_paired"):
        _err(errors, "V07", "phrases", "unpaired", "paired",
             "CN and EN phrase key sets must be identical")
    by_mode: dict[str, dict[str, dict]] = {}
    for document in manifest.get("documents", []):
        by_mode.setdefault(str(document.get("mode")), {})[
            str(document.get("language"))] = document
    for mode, languages in by_mode.items():
        if not {"zh", "en"}.issubset(languages):
            continue
        zh, en = languages["zh"], languages["en"]
        zh_fields, en_fields = zh.get("fields") or {}, en.get("fields") or {}
        if set(zh_fields) != set(en_fields):
            _err(errors, "V07", f"mode {mode}", sorted(set(zh_fields) ^ set(en_fields)),
                 "identical field key sets", "CN/EN reports expose different fields")
        for key in set(zh_fields) & set(en_fields):
            left, right = zh_fields[key], en_fields[key]
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                same = abs(float(left) - float(right)) <= FLOAT_TOLERANCE
            else:
                same = str(left) == str(right)
            if not same:
                _err(errors, "V07", f"mode {mode}/{key}", str(left), str(right),
                     "CN/EN numeric values differ")
        for chart_key in ("scope", "category", "total"):
            if (zh.get("chart_data") or {}).get(chart_key) != \
               (en.get("chart_data") or {}).get(chart_key):
                _err(errors, "V07", f"mode {mode}/chart.{chart_key}", "different",
                     "identical", "CN/EN chart data differ")


def _docx_text(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def rule_v12(manifest: dict, errors: list, *,
             phrases: dict | None = None, run: Path | None = None) -> None:
    """Mode B guardrail: no sign-off means draft plus a placeholder statement."""
    mode_b = [d for d in manifest.get("documents", []) if d.get("mode") == "B"]
    for document in mode_b:
        name = str(document.get("path") or "")
        signed = bool(document.get("signoff"))
        if signed:
            if (document.get("draft") or "_draft" in name
                    or not document.get("statement_rendered")
                    or document.get("statement_is_placeholder")):
                _err(errors, "V12", name, "draft-like", "signed final",
                     "signed verification report must render its statement as final")
        else:
            if (not document.get("draft") or "_draft" not in name
                    or document.get("statement_rendered")
                    or not document.get("statement_is_placeholder")):
                _err(errors, "V12", name, "final-like", "draft with placeholder",
                     "unsigned verification report must stay a draft with a placeholder statement")
        if phrases and run:
            path = run / name
            if path.is_file():
                words = phrases.get(str(document.get("language")), {}) or {}
                placeholder = str(words.get("report.B.statement_placeholder", ""))
                if placeholder:
                    try:
                        text = _docx_text(path)
                    except Exception as exc:  # noqa: BLE001 - reported, not hidden
                        _err(errors, "V12", name, str(exc), "readable docx",
                             "cannot read the verification report")
                        continue
                    if not signed and placeholder not in text:
                        _err(errors, "V12", name, "missing", placeholder,
                             "unsigned report lacks the required statement placeholder")
                    if signed and placeholder in text:
                        _err(errors, "V12", name, "placeholder present", "rendered statement",
                             "signed report still contains the placeholder")


def rule_v13(manifest: dict, errors: list, run: Path | None = None) -> None:
    """No unresolved template variables may survive into a delivered report."""
    for document in manifest.get("documents", []):
        name = str(document.get("path") or "")
        if int(document.get("unresolved_placeholders") or 0):
            _err(errors, "V13", name, document.get("unresolved_placeholders"), 0,
                 "unresolved numeric placeholders in the report")
        if int(document.get("template_tokens_found") or 0):
            _err(errors, "V13", name, document.get("template_tokens_found"), 0,
                 "unresolved template tokens found in the document text")
        if run:
            path = run / name
            if path.is_file():
                try:
                    text = _docx_text(path)
                except Exception:  # noqa: BLE001 - covered by V12 readability check
                    continue
                if "{{" in text:
                    _err(errors, "V13", name, text.count("{{"), 0,
                         "unresolved template tokens found in the delivered docx")


def rule_v20(run: Path, manifest: dict, errors: list,
             prior_errors: list) -> None:
    """Delivery completeness: every required artifact exists and checks are clean."""
    for name in V20_REQUIRED_FILES:
        path = run / name
        if not path.is_file() or path.stat().st_size == 0:
            _err(errors, "V20", name, "missing or empty", "non-empty file",
                 "required deliverable is absent")
    for document in manifest.get("documents", []):
        name = str(document.get("path") or "")
        if name and not (run / name).is_file():
            _err(errors, "V20", name, "missing", "report document",
                 "report listed in the manifest is absent")
    if prior_errors:
        _err(errors, "V20", "checks", len(prior_errors), 0,
             "ERROR-level findings block delivery")


def embed(results: dict, report: dict) -> dict:
    """Write the compact verdict back into results.checks."""
    results["checks"] = {
        "status": "fail" if report["errors"] else "pass",
        "errors": report["errors"],
        "warnings": report["warnings"],
    }
    return results
