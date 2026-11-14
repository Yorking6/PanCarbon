# -*- coding: utf-8 -*-
"""M3 acceptance tests: bilingual dual-mode reports and V07/V12/V13."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_report  # noqa: E402
import cli  # noqa: E402
import recalc_check  # noqa: E402
from docx import Document  # noqa: E402
from ghg_common import canonical_hash, load_json, load_schema, validate_schema, write_json  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
ASSETS = ROOT / "assets"


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


def doc_text(path: Path) -> str:
    document = Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def valid_signoff() -> dict:
    return {
        "signed_by": "Synthetic Verifier",
        "signed_at": "2000-12-31T00:00:00",
        "assurance_level": "limited",
        "materiality": 5,
        "verifier": "Synthetic Verification Body",
        "statement": "Synthetic verification statement supplied by the authorized verifier.",
        "procedures": [{"name": "sampling", "status": "completed"}],
        "findings": [{"description": "no exceptions", "category": "data", "status": "closed"}],
    }


class TestReportArtifacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        full_run(self.run)
        self.manifest = load_json(self.run / "report_manifest.json")
        self.phrases = load_json(ASSETS / "phrases.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_four_documents_and_charts(self):
        names = sorted(d["path"] for d in self.manifest["documents"])
        self.assertEqual(names, [
            "report_A_en.docx", "report_A_zh.docx",
            "report_B_en_draft.docx", "report_B_zh_draft.docx",
        ])
        for name in names:
            self.assertTrue((self.run / name).is_file())
        charts = sorted(p.name for p in self.run.glob("chart_*.png"))
        self.assertEqual(charts, [
            "chart_category_en.png", "chart_category_zh.png",
            "chart_scope_en.png", "chart_scope_zh.png",
        ])
        self.assertFalse(self.manifest["signoff_valid"])
        self.assertEqual(sum(1 for d in self.manifest["documents"] if d["draft"]), 2)

    def test_phrases_paired_and_nonempty(self):
        zh, en = self.phrases["zh"], self.phrases["en"]
        self.assertEqual(set(zh), set(en))
        self.assertTrue(all(str(value).strip() for value in zh.values()))
        self.assertTrue(all(str(value).strip() for value in en.values()))
        self.assertTrue(self.manifest["phrases_paired"])

    def test_chart_data_matches_results(self):
        results = load_json(self.run / "results.json")
        version = next(v for v in results["versions"]
                       if v["version_id"] == results["final_version_id"])
        for document in self.manifest["documents"]:
            data = document["chart_data"]
            self.assertAlmostEqual(data["total"], float(version["total"]), places=6)
            self.assertAlmostEqual(data["scope"]["S1"],
                                   float(version["by_scope"]["S1"]), places=6)
            self.assertAlmostEqual(
                sum(data["category"].values()),
                sum(float(v) for v in version["by_scope"]["S3"].values()), places=6)

    def test_mode_a_structure(self):
        path = self.run / "report_A_zh.docx"
        document = Document(str(path))
        headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
        self.assertGreaterEqual(len(headings), 9)
        self.assertGreaterEqual(len(document.tables), 6)
        text = doc_text(path)
        self.assertIn(self.phrases["zh"]["report.end_marker"], text)
        self.assertIn(self.phrases["zh"]["report.A.conclusion"], text)
        self.assertIn(self.phrases["zh"]["report.A.section.uncertainty"], text)

    def test_embedded_images_present(self):
        for name in ("report_A_zh.docx", "report_B_zh_draft.docx"):
            document = Document(str(self.run / name))
            self.assertGreaterEqual(len(document.inline_shapes), 2)

    def test_dynamic_numbers_only_in_tables(self):
        document = Document(str(self.run / "report_A_zh.docx"))
        prose = "\n".join(p.text for p in document.paragraphs)
        tables = "\n".join(cell.text for table in document.tables
                           for row in table.rows for cell in row.cells)
        self.assertIn("7.16", tables)
        self.assertNotIn("7.16", prose)

    def test_draft_guardrail_in_manifest_and_text(self):
        for document in self.manifest["documents"]:
            if document["mode"] != "B":
                continue
            self.assertTrue(document["draft"])
            self.assertFalse(document["statement_rendered"])
            self.assertTrue(document["statement_is_placeholder"])
            self.assertIn("_draft", document["path"])
            placeholder = self.phrases[document["language"]]["report.B.statement_placeholder"]
            self.assertIn(placeholder, doc_text(self.run / document["path"]))
            self.assertIn(self.phrases[document["language"]]["report.B.draft_notice"],
                          doc_text(self.run / document["path"]))


class TestSignoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        full_run(self.run)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_signoff_renders_final(self):
        write_json(self.run / "signoff.json", valid_signoff())
        self.assertEqual(cli.main(["report", "--run-dir", str(self.run)]), 0)
        manifest = load_json(self.run / "report_manifest.json")
        self.assertTrue(manifest["signoff_valid"])
        self.assertEqual(manifest["signoff_issues"], [])
        for document in manifest["documents"]:
            if document["mode"] != "B":
                continue
            self.assertFalse(document["draft"])
            self.assertTrue(document["statement_rendered"])
            self.assertFalse(document["statement_is_placeholder"])
            self.assertNotIn("_draft", document["path"])
            text = doc_text(self.run / document["path"])
            self.assertIn(valid_signoff()["statement"], text)
            self.assertNotIn(
                load_json(ASSETS / "phrases.json")[document["language"]]
                ["report.B.statement_placeholder"], text)
        self.assertEqual(cli.main(["check", "--run-dir", str(self.run)]), 0)
        checks = load_json(self.run / "checks.json")
        self.assertEqual(checks["status"], "pass")
        self.assertNotIn("V12", {e["rule"] for e in checks["errors"]})

    def test_invalid_signoff_stays_draft(self):
        invalid = valid_signoff()
        del invalid["statement"]
        write_json(self.run / "signoff.json", invalid)
        self.assertEqual(cli.main(["report", "--run-dir", str(self.run)]), 0)
        manifest = load_json(self.run / "report_manifest.json")
        self.assertFalse(manifest["signoff_valid"])
        self.assertTrue(manifest["signoff_issues"])
        self.assertEqual(sum(1 for d in manifest["documents"] if d["draft"]), 2)

    def test_signoff_schema_required_fields(self):
        schema = load_schema("verification_signoff")
        self.assertEqual(validate_schema(valid_signoff(), schema), [])
        broken = valid_signoff()
        del broken["signed_by"]
        self.assertTrue(any("signed_by" in e for e in validate_schema(broken, schema)))
        bad_level = valid_signoff()
        bad_level["assurance_level"] = "unsupported"
        self.assertTrue(any("enum" in e for e in validate_schema(bad_level, schema)))

    def test_no_conclusion_text_generated_for_draft(self):
        text = doc_text(self.run / "report_B_zh_draft.docx")
        self.assertNotIn("无重大错报", text)
        self.assertNotIn("合理保证结论", text)
        phrases = load_json(ASSETS / "phrases.json")["zh"]
        self.assertIn(phrases["report.B.prose.statement_hint"], text)


class TestReportRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        full_run(self.run)
        self.cfg = load_json(self.run / "org_config.json")
        self.ledger = load_json(self.run / "activity_ledger.json")
        self.matched = load_json(self.run / "matched.json")
        self.factors = load_json(self.run / "factor_library.json")
        self.results = load_json(self.run / "results.json")
        self.phrases = load_json(ASSETS / "phrases.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _rules(self, manifest=None):
        report = recalc_check.run_checks(
            self.cfg, self.ledger, self.matched, self.factors, self.results,
            None, manifest, phrases=self.phrases, run=self.run)
        return {e["rule"] for e in report["errors"]}, report

    def test_full_pipeline_checks_status(self):
        checks = load_json(self.run / "checks.json")
        self.assertEqual(checks["status"], "pass")
        self.assertEqual(checks["milestone"], "M1+M2+M3+M5")
        self.assertEqual(checks["reports_checked"], 4)
        self.assertEqual(checks["rules_deferred"], {})
        self.assertTrue(checks["delivery_ready"])
        for rule in ("V06", "V07", "V12", "V13"):
            self.assertIn(rule, checks["rules_run"])

    def test_v07_detects_cn_en_mismatch(self):
        manifest = copy.deepcopy(load_json(self.run / "report_manifest.json"))
        for document in manifest["documents"]:
            if document["mode"] == "A" and document["language"] == "en":
                document["fields"]["total"] = 99
        rules, _ = self._rules(manifest)
        self.assertIn("V07", rules)

    def test_v07_detects_chart_mismatch(self):
        manifest = copy.deepcopy(load_json(self.run / "report_manifest.json"))
        for document in manifest["documents"]:
            if document["mode"] == "A" and document["language"] == "en":
                document["chart_data"]["scope"]["S1"] = 99
        rules, _ = self._rules(manifest)
        self.assertIn("V07", rules)

    def test_v12_detects_forged_final(self):
        manifest = copy.deepcopy(load_json(self.run / "report_manifest.json"))
        for document in manifest["documents"]:
            if document["mode"] == "B":
                document["statement_rendered"] = True
                document["statement_is_placeholder"] = False
        rules, _ = self._rules(manifest)
        self.assertIn("V12", rules)

    def test_v13_detects_unresolved_placeholder(self):
        manifest = copy.deepcopy(load_json(self.run / "report_manifest.json"))
        manifest["documents"][0]["unresolved_placeholders"] = 1
        rules, _ = self._rules(manifest)
        self.assertIn("V13", rules)

    def test_v13_detects_template_token_in_docx(self):
        path = self.run / "report_A_zh.docx"
        document = Document(str(path))
        document.tables[0].cell(1, 1).text = "{{unresolved}}"
        document.save(str(path))
        manifest = load_json(self.run / "report_manifest.json")
        rules, _ = self._rules(manifest)
        self.assertIn("V13", rules)

    def test_v06_detects_report_total_tamper(self):
        manifest = copy.deepcopy(load_json(self.run / "report_manifest.json"))
        manifest["documents"][0]["fields"]["total"] = 99
        rules, _ = self._rules(manifest)
        self.assertIn("V06", rules)

    def test_v06_detects_wrong_final_version(self):
        manifest = copy.deepcopy(load_json(self.run / "report_manifest.json"))
        manifest["final_version_id"] = "V-OTHER"
        rules, _ = self._rules(manifest)
        self.assertIn("V06", rules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
