# -*- coding: utf-8 -*-
"""M0 acceptance tests.

All fixtures are synthetic. Organization-specific literals used by the purity
audit are assembled at run time so that no such literal is stored in this file.

Run:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_purity  # noqa: E402
import cli  # noqa: E402
import validate_config  # noqa: E402
from ghg_common import canonical_hash, load_json, load_schema, validate_schema  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"

# Assembled at run time: the package must not contain any organization name or
# real factor value, including inside the test suite.
ORG_PATTERNS = [
    "贝" + "发",
    "Be" + "ifa",
    "绿碳" + "智汇",
    "博" + "汇",
    "新" + "贝" + "发",
    "Sophia" + " Wang",
    "凌芯" + "智能",
]
FACTOR_PATTERNS = [
    "3" + r"\.173",
    "2" + r"\.7002",
    "0" + r"\.5153",
    "6" + r"\.7261",
]


class TestFrontmatter(unittest.TestCase):
    def test_frontmatter_matches_official_validator_rules(self):
        content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        self.assertIsNotNone(match)
        block = match.group(1)
        self.assertIn("name:", block)
        self.assertIn("description:", block)
        name_match = re.search(r"name:\s*(.+)", block)
        self.assertIsNotNone(name_match)
        name = name_match.group(1).strip()
        self.assertRegex(name, r"^[a-z0-9-]+$")
        self.assertFalse(name.startswith("-") or name.endswith("-") or "--" in name)
        desc_match = re.search(r"description:\s*(.+)", block)
        self.assertIsNotNone(desc_match)
        self.assertNotIn("<", desc_match.group(1))
        self.assertNotIn(">", desc_match.group(1))
        self.assertIn("agent_created: true", block)


class TestPurity(unittest.TestCase):
    def test_purity_audit_passes(self):
        result = audit_purity.scan(ROOT, ORG_PATTERNS + FACTOR_PATTERNS)
        self.assertEqual(
            result["status"], "pass",
            msg=json.dumps(result["findings"], ensure_ascii=False, indent=2),
        )
        self.assertGreater(result["files_scanned"], 10)

    def test_audit_detects_injected_organization_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sample.md"
            target.write_text("synthetic line " + ORG_PATTERNS[0], encoding="utf-8")
            result = audit_purity.scan(Path(tmp), ORG_PATTERNS)
            self.assertEqual(result["status"], "fail")
            self.assertTrue(any(f["rule"].startswith("R_EXTRA") for f in result["findings"]))


class TestStage0(unittest.TestCase):
    def test_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = validate_config.validate(ROOT / "assets" / "config_template.json",
                                              Path(tmp) / "run")
            self.assertEqual(report["status"], "fail")
            self.assertTrue(report["placeholder_hits"])
            self.assertTrue(report["schema_errors"])
            self.assertFalse((Path(tmp) / "run" / "inputs").exists())

    def test_synthetic_config_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for name in ("org_config.valid.json", "factor_library.valid.json",
                         "activity_ledger.valid.json"):
                shutil.copy2(FIXTURES / name, work / name)
            cfg = load_json(work / "org_config.valid.json")
            ledger = load_json(work / "activity_ledger.valid.json")
            ledger["config_hash"] = canonical_hash(cfg)
            (work / "activity_ledger.valid.json").write_text(
                json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            run_dir = work / "run"
            report = validate_config.validate(work / "org_config.valid.json", run_dir)
            self.assertEqual(report["status"], "pass",
                             msg=json.dumps(report, ensure_ascii=False, indent=2))
            self.assertEqual(report["warnings"], [])
            self.assertTrue((run_dir / "config_check.json").is_file())
            self.assertTrue((run_dir / "inputs").is_dir())
            self.assertTrue((run_dir / "outputs").is_dir())

    def test_mode_b_requires_assurance_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            cfg = load_json(FIXTURES / "org_config.valid.json")
            cfg["assurance"] = {"level": None, "materiality": None, "verifier": None}
            cfg["report"]["signoff_ref"] = None
            cfg["factor_library_ref"] = "factor_library.valid.json"
            cfg["activity_ledger_ref"] = "activity_ledger.valid.json"
            (work / "org_config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            report = validate_config.validate(work / "org_config.json", work / "run")
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any("assurance" in e for e in report["semantic_errors"]))


class TestSchemas(unittest.TestCase):
    def test_all_four_fixtures_validate(self):
        pairs = [
            ("org_config", "org_config.valid.json"),
            ("factor_library", "factor_library.valid.json"),
            ("activity_ledger", "activity_ledger.valid.json"),
            ("results", "results.valid.json"),
        ]
        for schema_name, fixture in pairs:
            with self.subTest(schema=schema_name):
                errors = validate_schema(load_json(FIXTURES / fixture),
                                         load_schema(schema_name))
                self.assertEqual(errors, [])

    def test_confirmation_gate_contract(self):
        ledger = load_json(FIXTURES / "activity_ledger.valid.json")
        del ledger["rows"][0]["confirmation"]["signed_by"]
        errors = validate_schema(ledger, load_schema("activity_ledger"))
        self.assertTrue(any("signed_by" in e for e in errors))

    def test_results_rejects_unknown_status(self):
        results = load_json(FIXTURES / "results.valid.json")
        results["versions"][0]["status"] = "unknown"
        errors = validate_schema(results, load_schema("results"))
        self.assertTrue(any("enum" in e for e in errors))

    def test_factor_requires_explicit_scale(self):
        factors = load_json(FIXTURES / "factor_library.valid.json")
        del factors["factors"][0]["scale"]
        errors = validate_schema(factors, load_schema("factor_library"))
        self.assertTrue(any("scale" in e for e in errors))

    def test_canonical_hash_ignores_key_order(self):
        a = {"x": 1, "y": {"b": 2, "a": 3}}
        b = {"y": {"a": 3, "b": 2}, "x": 1}
        self.assertEqual(canonical_hash(a), canonical_hash(b))


class TestCli(unittest.TestCase):
    def test_deps_and_audit_commands(self):
        self.assertEqual(cli.main(["deps"]), 0)
        self.assertEqual(cli.main(["audit"]), 0)

    def test_no_remaining_unimplemented_milestones(self):
        # All M0-M5 stages landed; unknown commands still fail cleanly.
        self.assertEqual(cli.MILESTONE_OF_UNIMPLEMENTED, {})
        self.assertEqual(cli.main(["no-such-stage"]), 2)

    def test_unknown_command_fails(self):
        self.assertEqual(cli.main(["no-such-command"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
