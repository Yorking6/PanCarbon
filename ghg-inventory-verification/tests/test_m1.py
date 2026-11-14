# -*- coding: utf-8 -*-
"""M1 acceptance tests: unit contract, all method families, and Stage 7 rules.

All data is synthetic. Organization-specific literals are never stored here.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cli  # noqa: E402
import classify  # noqa: E402
import compute  # noqa: E402
import method_factor  # noqa: E402
import recalc_check  # noqa: E402
from ghg_common import canonical_hash, load_json, load_schema, validate_schema, write_json  # noqa: E402
from normalize_units import (  # noqa: E402
    apply_conversion_chain, derive_scale, dimension_compatible, scale_matches,
)

FIXTURES = ROOT / "tests" / "fixtures"
EXPECTED_TOTAL = 7.16


def load_m1_case() -> tuple[dict, dict, dict]:
    cfg = load_json(FIXTURES / "org_config.m1.json")
    factors = load_json(FIXTURES / "factor_library.m1.json")
    ledger = load_json(FIXTURES / "activity_ledger.m1.json")
    ledger["config_hash"] = canonical_hash(cfg)
    return cfg, ledger, factors


def make_run(root: Path) -> tuple[dict, dict, dict]:
    cfg, ledger, factors = load_m1_case()
    write_json(root / "org_config.json", cfg)
    write_json(root / "factor_library.json", factors)
    write_json(root / "activity_ledger.json", ledger)
    return cfg, ledger, factors


def full_chain(cfg: dict, ledger: dict, factors: dict) -> tuple[dict, dict, dict]:
    classification = classify.classify(cfg, ledger)
    matched = method_factor.match(cfg, ledger, classification, factors)
    results = compute.compute(cfg, ledger, matched)
    return classification, matched, results


class TestUnitContract(unittest.TestCase):
    def test_derived_scale_for_unit_pairs(self):
        cases = [
            ("kg", "kgCO2e/kg", Fraction(1000)),
            ("t", "kgCO2e/kg", Fraction(1)),
            ("kWh", "kgCO2e/kWh", Fraction(1000)),
            ("t", "tCO2e/t", Fraction(1)),
            ("USD", "kgCO2e/USD", Fraction(1000)),
        ]
        for ad_unit, ef_unit, expected in cases:
            with self.subTest(ad=ad_unit, ef=ef_unit):
                self.assertEqual(derive_scale(ad_unit, ef_unit), expected)

    def test_dimension_mismatch_is_rejected(self):
        self.assertFalse(dimension_compatible("kg", "kgCO2e/tkm")["compatible"])
        self.assertFalse(dimension_compatible("CNY", "kgCO2e/kWh")["compatible"])

    def test_extra_divisor_is_detected(self):
        """Reproduction of the historical double-1000 divisor incident."""
        ok = scale_matches("kg", "kgCO2e/kg", 1000)
        bad = scale_matches("kg", "kgCO2e/kg", 1000000)
        self.assertTrue(ok["match"])
        self.assertFalse(bad["match"])
        self.assertIn("differs", bad["reason"])

    def test_conversion_chain_is_traced_and_validated(self):
        chain = [
            {"op": "currency_conversion", "from_unit": "CNY", "to_unit": "USD",
             "factor": 0.2, "reference": "fx_table", "note": "synthetic rate"},
        ]
        result = apply_conversion_chain(10000, "CNY", chain)
        self.assertEqual(float(result["value"]), 2000.0)
        self.assertEqual(result["unit"], "USD")
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(result["errors"], [])

        bad_from = apply_conversion_chain(100, "kg", [
            {"op": "multiply", "from_unit": "t", "factor": 2,
             "note": "mismatched source unit"}])
        self.assertTrue(any("from_unit" in e for e in bad_from["errors"]))

        no_note = apply_conversion_chain(100, "kg", [
            {"op": "multiply", "from_unit": "kg", "factor": 2, "note": ""}])
        self.assertTrue(any("note" in e for e in no_note["errors"]))

        no_factor = apply_conversion_chain(100, "kg", [
            {"op": "multiply", "from_unit": "kg", "note": "missing factor"}])
        self.assertTrue(any("factor" in e for e in no_factor["errors"]))


class TestM1Pipeline(unittest.TestCase):
    def setUp(self):
        self.cfg, self.ledger, self.factors = load_m1_case()

    def test_all_method_families_calculate(self):
        classification, matched, results = full_chain(self.cfg, self.ledger, self.factors)
        self.assertEqual(classification["status"], "pass")
        self.assertEqual(len(classification["unmapped"]), 0)
        self.assertEqual(len(classification["categories"]), 17)  # S1, S2, S3-1..S3-15
        self.assertEqual(matched["status"], "pass")
        self.assertEqual(len(matched["lines"]), 12)
        version = compute.final_version(results)
        self.assertIsNotNone(version)
        self.assertEqual(len(version["lines"]), 12)
        self.assertTrue(all(l["tco2e"] is not None for l in version["lines"]))
        self.assertAlmostEqual(float(version["total"]), EXPECTED_TOTAL, places=6)
        self.assertAlmostEqual(float(version["by_scope"]["S1"]), 0.7, places=6)
        self.assertAlmostEqual(float(version["by_scope"]["S2"]["location_based"]), 0.5, places=6)
        self.assertAlmostEqual(float(version["by_scope"]["S2"]["market_based"]), 0.2, places=6)
        self.assertAlmostEqual(float(version["by_scope"]["S3"]["S3-5"]), 4.0, places=6)
        self.assertNotEqual(version["by_scope"]["S2"]["location_based"],
                            version["by_scope"]["S2"]["market_based"])

    def test_checks_pass_and_deferred_rules_are_registered(self):
        _, matched, results = full_chain(self.cfg, self.ledger, self.factors)
        report = recalc_check.run_checks(self.cfg, self.ledger, matched,
                                         self.factors, results)
        self.assertEqual(report["status"], "pass",
                         msg=json.dumps(report["errors"], ensure_ascii=False, indent=2))
        self.assertEqual(report["dual_track"]["status"], "match")
        self.assertEqual(report["dual_track"]["lines_checked"], 12)
        self.assertEqual(len(report["rules_deferred"]), 6)
        self.assertEqual(report["v14"]["status"], "clean")

    def test_cli_pipeline_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            make_run(run)
            self.assertEqual(cli.main(["pipeline", "--run-dir", str(run)]), 0)
            for name in ("classification.json", "matched.json",
                         "results.json", "checks.json"):
                self.assertTrue((run / name).is_file(), msg=name)
            checks = load_json(run / "checks.json")
            results = load_json(run / "results.json")
            self.assertEqual(checks["status"], "pass")
            self.assertEqual(results["checks"]["status"], "pass")
            self.assertAlmostEqual(
                float(compute.final_version(results)["total"]), EXPECTED_TOTAL, places=6)

    def test_m1_fixtures_validate_against_schemas(self):
        for name, schema in (("org_config.m1.json", "org_config"),
                             ("factor_library.m1.json", "factor_library"),
                             ("activity_ledger.m1.json", "activity_ledger")):
            with self.subTest(fixture=name):
                self.assertEqual(validate_schema(load_json(FIXTURES / name),
                                                 load_schema(schema)), [])


class TestHardGates(unittest.TestCase):
    def setUp(self):
        self.cfg, self.ledger, self.factors = load_m1_case()

    def test_unsigned_row_blocks_classify_and_compute(self):
        broken = copy.deepcopy(self.ledger)
        del broken["rows"][0]["confirmation"]["signed_by"]
        classification = classify.classify(self.cfg, broken)
        self.assertEqual(classification["status"], "fail")
        _, matched, _ = full_chain(self.cfg, self.ledger, self.factors)
        with self.assertRaises(compute.GateError):
            compute.compute(self.cfg, broken, matched)

    def test_dimension_mismatch_produces_null_not_zero(self):
        factors = copy.deepcopy(self.factors)
        factors["factors"][0]["scale"] = 1000000
        classification = classify.classify(self.cfg, self.ledger)
        matched = method_factor.match(self.cfg, self.ledger, classification, factors)
        self.assertEqual(matched["lines"][0]["status"], "dimension_mismatch")
        results = compute.compute(self.cfg, self.ledger, matched)
        first = compute.final_version(results)["lines"][0]
        self.assertIsNone(first["tco2e"])
        self.assertTrue(first["warnings"])

    def test_ambiguous_factors_are_not_guessed(self):
        factors = copy.deepcopy(self.factors)
        duplicate = copy.deepcopy(factors["factors"][0])
        duplicate["id"] = "F01B"
        factors["factors"].append(duplicate)
        classification = classify.classify(self.cfg, self.ledger)
        matched = method_factor.match(self.cfg, self.ledger, classification, factors)
        self.assertEqual(matched["lines"][0]["status"], "ambiguous")
        self.assertEqual(len(matched["candidates"]), 1)
        results = compute.compute(self.cfg, self.ledger, matched)
        self.assertIsNone(compute.final_version(results)["lines"][0]["tco2e"])

    def test_conversion_replay_mismatch_is_detected(self):
        ledger = copy.deepcopy(self.ledger)
        ledger["rows"][0]["normalized"]["value"] = 999
        classification = classify.classify(self.cfg, ledger)
        matched = method_factor.match(self.cfg, ledger, classification, self.factors)
        self.assertEqual(matched["lines"][0]["status"], "conversion_mismatch")


class TestStage7Rules(unittest.TestCase):
    def setUp(self):
        self.cfg, self.ledger, self.factors = load_m1_case()
        self.classification, self.matched, self.results = full_chain(
            self.cfg, self.ledger, self.factors)

    def _check(self, results=None, matched=None, ledger=None):
        return recalc_check.run_checks(
            self.cfg, ledger or self.ledger, matched or self.matched,
            self.factors, results or self.results)

    def _rules(self, report):
        return {e["rule"] for e in report["errors"]}

    def test_v03_detects_subtotal_mismatch(self):
        broken = copy.deepcopy(self.results)
        broken["versions"][0]["by_category"]["S1"] = 99
        self.assertIn("V03", self._rules(self._check(results=broken)))

    def test_v04_detects_total_mismatch(self):
        broken = copy.deepcopy(self.results)
        broken["versions"][0]["total"] = 99
        self.assertIn("V04", self._rules(self._check(results=broken)))

    def test_v05_detects_stale_share_denominator(self):
        broken = copy.deepcopy(self.results)
        broken["versions"][0]["lines"][0]["share"] = 0.5
        self.assertIn("V05", self._rules(self._check(results=broken)))

    def test_v08_detects_multiple_final_versions(self):
        broken = copy.deepcopy(self.results)
        extra = copy.deepcopy(broken["versions"][0])
        extra["version_id"] = "V2"
        broken["versions"].append(extra)
        self.assertIn("V08", self._rules(self._check(results=broken)))

    def test_v01_detects_wrong_line_value(self):
        broken = copy.deepcopy(self.results)
        broken["versions"][0]["lines"][0]["tco2e"] = 99
        self.assertIn("V01", self._rules(self._check(results=broken)))

    def test_v11_detects_unsigned_ledger(self):
        broken = copy.deepcopy(self.ledger)
        broken["rows"][1]["confirmation"]["signed_at"] = ""
        self.assertIn("V11", self._rules(self._check(ledger=broken)))

    def test_v19_detects_out_of_year_period(self):
        broken = copy.deepcopy(self.ledger)
        broken["rows"][0]["period"] = {
            "start": "1998-01-01", "end": "1998-12-31",
            "basis": "consumption", "billing_note": None}
        self.assertIn("V19", self._rules(self._check(ledger=broken)))

    def test_v14_detects_heuristic_total_picking(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            (scripts / "bad.py").write_text("total = max(values)\n", encoding="utf-8")
            with mock.patch.object(recalc_check, "SKILL_ROOT", Path(tmp)):
                result = recalc_check.rule_v14([], [])
            self.assertEqual(result["status"], "violation")
            self.assertTrue(any("bad.py" in hit for hit in result["hits"]))

    def test_append_version_keeps_single_final(self):
        extended = compute.compute(self.cfg, self.ledger, self.matched,
                                   version_id="V2", status="draft",
                                   existing=copy.deepcopy(self.results))
        finals = [v["version_id"] for v in extended["versions"]
                  if v["status"] == "final"]
        self.assertEqual(finals, ["V1"])
        self.assertEqual(extended["final_version_id"], "V1")
        self.assertEqual(self._check(results=extended)["status"], "pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)
