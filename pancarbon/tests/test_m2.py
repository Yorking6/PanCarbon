# -*- coding: utf-8 -*-
"""M2 acceptance tests: formula-driven workbook, V06 and V09.

All data is synthetic; no organization-specific literal is stored here.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_inventory  # noqa: E402
import cli  # noqa: E402
import recalc_check  # noqa: E402
from formula_eval import WorkbookEvaluator  # noqa: E402
from ghg_common import canonical_hash, load_json, write_json  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
TOLERANCE = 1e-9


def prepare_run(run: Path) -> None:
    cfg = load_json(FIXTURES / "org_config.m1.json")
    factors = load_json(FIXTURES / "factor_library.m1.json")
    ledger = load_json(FIXTURES / "activity_ledger.m1.json")
    ledger["config_hash"] = canonical_hash(cfg)
    write_json(run / "org_config.json", cfg)
    write_json(run / "factor_library.json", factors)
    write_json(run / "activity_ledger.json", ledger)


def full_run(run: Path) -> None:
    prepare_run(run)
    assert cli.main(["pipeline", "--run-dir", str(run)]) == 0


def context(run: Path) -> dict:
    return {"path": run / "ghg_inventory.xlsx",
            "cache": load_json(run / "formula_cache.json")}


class TestWorkbookStructure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        full_run(self.run)
        self.wb_path = self.run / "ghg_inventory.xlsx"
        self.cache = load_json(self.run / "formula_cache.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_sheet_layout(self):
        wb = load_workbook(self.wb_path)
        try:
            names = wb.sheetnames
            for key in ("boundary", "source_identification", "activity_data",
                        "factors", "s12_calc", "data_quality", "quality_gaps", "summary"):
                self.assertIn(key, names)
            s3 = [n for n in names if n.startswith("S3_C")]
            self.assertEqual(len(s3), 8)
            self.assertGreaterEqual(len(names), 15)
            self.assertEqual(wb["summary"]["B5"].value, "=B2+B3+B4")
            self.assertTrue(str(wb["summary"]["C5"].value).endswith("$B$5"))
            self.assertIn("AI", str(wb.properties.title or ""))
            self.assertIn("AI", str(wb.properties.description or ""))
        finally:
            wb.close()

    def test_formulas_reference_cells_only(self):
        wb = load_workbook(self.wb_path)
        try:
            for name in ("s12_calc", *[n for n in wb.sheetnames if n.startswith("S3_C")]):
                ws = wb[name]
                for row in range(2, ws.max_row + 1):
                    j = ws.cell(row=row, column=10).value
                    if isinstance(j, str) and j.startswith("=E"):
                        self.assertRegex(j, r"^=E\d+\*G\d+\*H\d+/I\d+$",
                                         msg=f"{name}!J{row}")
                    k = ws.cell(row=row, column=11).value
                    if isinstance(k, str) and k.startswith("="):
                        self.assertIn("summary!$B$5", k)
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith("="):
                            self.assertNotIn("#REF!", cell.value)
                            self.assertNotIn("[", cell.value)
        finally:
            wb.close()

    def test_no_external_links(self):
        wb = load_workbook(self.wb_path)
        try:
            self.assertEqual(len(wb._external_links or []), 0)
        finally:
            wb.close()
        with zipfile.ZipFile(self.wb_path) as archive:
            self.assertFalse([n for n in archive.namelist() if "externalLinks" in n])

    def test_formula_cache_is_complete(self):
        wb = load_workbook(self.wb_path)
        try:
            found = []
            for ws in wb.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith("="):
                            found.append(f"{ws.title}!{cell.coordinate}")
        finally:
            wb.close()
        self.assertEqual(len(found), self.cache["formula_cell_count"])
        self.assertEqual(sorted(found), sorted(set(self.cache["formula_cells"])))
        for key in found:
            self.assertIn(key, self.cache["cells"])
        self.assertEqual(self.cache["cells"]["summary!B5"], 7.16)
        self.assertEqual(self.cache["cells"]["summary!B4"], 5.96)

    def test_quality_gaps_and_no_hardcoded_scores(self):
        wb = load_workbook(self.wb_path)
        try:
            dq = wb["data_quality"]
            self.assertEqual(dq["E2"].value, "N/A")
            self.assertIn("score table", str(dq["K2"].value))
            qg = wb["quality_gaps"]
            labels = [str(qg.cell(row=r, column=1).value or "")
                      for r in range(1, qg.max_row + 1)]
            self.assertTrue(any(label.startswith("G") for label in labels))
            self.assertIn("METHOD CHANGES", labels)
            self.assertIn("TOTALS", labels)
            self.assertTrue(any(str(qg.cell(row=r, column=2).value or "").startswith("=summary!")
                              for r in range(1, qg.max_row + 1)))
        finally:
            wb.close()


class TestRecalculation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        full_run(self.run)
        self.ctx = context(self.run)

    def tearDown(self):
        self.tmp.cleanup()

    def _compare(self, values: dict) -> tuple[int, float]:
        normalized = {k.upper(): v for k, v in values.items()}
        checked, biggest = 0, 0.0
        for key, expected in self.ctx["cache"]["cells"].items():
            got = normalized.get(key.upper())
            if got is None:
                continue
            checked += 1
            biggest = max(biggest, abs(float(got) - float(expected)))
        return checked, biggest

    def test_formulas_engine_matches_cache(self):
        values = recalc_check._recalc_formulas(self.ctx["path"])
        self.assertIsNotNone(values)
        checked, delta = self._compare(values)
        self.assertEqual(checked, self.ctx["cache"]["formula_cell_count"])
        self.assertLess(delta, TOLERANCE)

    def test_builtin_fallback_matches_cache(self):
        evaluator = WorkbookEvaluator(self.ctx["path"])
        try:
            values = evaluator.evaluate_all()
        finally:
            evaluator.close()
        checked, delta = self._compare(values)
        self.assertEqual(checked, self.ctx["cache"]["formula_cell_count"])
        self.assertLess(delta, TOLERANCE)

    def test_v09_report_from_pipeline(self):
        checks = load_json(self.run / "checks.json")
        v09 = checks["v09"]
        self.assertEqual(checks["status"], "pass")
        self.assertEqual(v09["formula_cells"], self.ctx["cache"]["formula_cell_count"])
        self.assertEqual(v09["cells_checked"], self.ctx["cache"]["formula_cell_count"])
        self.assertEqual(v09["external_links"], 0)
        self.assertEqual(v09["issues"], [])
        self.assertLess(v09["max_delta"], TOLERANCE)
        self.assertEqual(checks["milestone"], "M1+M2+M3+M5")
        self.assertIn("V06", checks["rules_run"])
        self.assertIn("V09", checks["rules_run"])
        # M3 added V07/V12/V13 and M5 added V20; nothing stays deferred.
        self.assertIn("V20", checks["rules_run"])
        self.assertEqual(checks["rules_deferred"], {})

    def test_skip_workbook_keeps_v06_v09_deferred(self):
        # Also skip reports so the assertion isolates the M1 rule subset.
        self.assertEqual(cli.main(["check", "--run-dir", str(self.run),
                                   "--skip-workbook", "--skip-reports"]), 0)
        checks = load_json(self.run / "checks.json")
        self.assertEqual(checks["milestone"], "M1")
        self.assertEqual(len(checks["rules_deferred"]), 6)
        self.assertIn("V06", checks["rules_deferred"])
        self.assertIn("V09", checks["rules_deferred"])
        self.assertIn("V07", checks["rules_deferred"])


class TestV06V09Detection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        full_run(self.run)
        self.cfg = load_json(self.run / "org_config.json")
        self.ledger = load_json(self.run / "activity_ledger.json")
        self.matched = load_json(self.run / "matched.json")
        self.factors = load_json(self.run / "factor_library.json")
        self.results = load_json(self.run / "results.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _rules(self, workbook=None):
        report = recalc_check.run_checks(self.cfg, self.ledger, self.matched,
                                         self.factors, self.results, workbook)
        return {e["rule"] for e in report["errors"]}, report

    def test_v06_detects_tampered_total(self):
        ctx = context(self.run)
        ctx["cache"] = copy.deepcopy(ctx["cache"])
        ctx["cache"]["cells"]["summary!B5"] = 99
        rules, _ = self._rules(ctx)
        self.assertIn("V06", rules)

    def test_v09_detects_recalc_mismatch(self):
        ctx = context(self.run)
        ctx["cache"] = copy.deepcopy(ctx["cache"])
        ctx["cache"]["cells"]["s12_calc!E2"] = 999
        rules, _ = self._rules(ctx)
        self.assertIn("V09", rules)

    def test_v09_detects_formula_count_mismatch(self):
        ctx = context(self.run)
        ctx["cache"] = copy.deepcopy(ctx["cache"])
        ctx["cache"]["formula_cell_count"] = 5
        rules, _ = self._rules(ctx)
        self.assertIn("V09", rules)

    def test_v09_detects_broken_reference(self):
        broken = self.run / "broken.xlsx"
        shutil.copy2(self.run / "ghg_inventory.xlsx", broken)
        wb = load_workbook(broken)
        wb["s12_calc"]["J2"] = "=E2*#REF!"
        wb.save(broken)
        wb.close()
        ctx = context(self.run)
        ctx["path"] = broken
        rules, report = self._rules(ctx)
        self.assertIn("V09", rules)
        self.assertTrue(any("#REF" in x for x in report["v09"]["issues"]))

    def test_v09_detects_external_link_part(self):
        injected = self.run / "linked.xlsx"
        with zipfile.ZipFile(self.run / "ghg_inventory.xlsx") as source:
            with zipfile.ZipFile(injected, "w", zipfile.ZIP_DEFLATED) as target:
                for item in source.infolist():
                    target.writestr(item, source.read(item.filename))
                target.writestr("xl/externalLinks/externalLink1.xml",
                                "<externalLink xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"/>")
        ctx = context(self.run)
        ctx["path"] = injected
        errors: list = []
        warnings: list = []
        report = recalc_check.rule_v09(ctx, errors, warnings)
        self.assertGreater(report["external_links"], 0)
        self.assertTrue(any(e["rule"] == "V09" for e in errors))

    def test_v06_checks_every_emission_line(self):
        ctx = context(self.run)
        ctx["cache"] = copy.deepcopy(ctx["cache"])
        ctx["cache"]["cells"]["S3_C5!J2"] = 999
        rules, _ = self._rules(ctx)
        self.assertIn("V06", rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
