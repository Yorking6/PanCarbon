# -*- coding: utf-8 -*-
"""M5 acceptance tests: delivery bundle, evidence index and V20."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cli  # noqa: E402
import package_delivery  # noqa: E402
from ghg_common import canonical_hash, load_json, write_json  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def prepare_run(run: Path) -> None:
    cfg = load_json(FIXTURES / "org_config.m1.json")
    factors = load_json(FIXTURES / "factor_library.m1.json")
    ledger = load_json(FIXTURES / "activity_ledger.m1.json")
    ledger["config_hash"] = canonical_hash(cfg)
    write_json(run / "org_config.json", cfg)
    write_json(run / "factor_library.json", factors)
    write_json(run / "activity_ledger.json", ledger)


class DeliveryTestBase(unittest.TestCase):
    """Build one clean run, then copy it for each isolated assertion."""

    @classmethod
    def setUpClass(cls):
        cls._shared = tempfile.TemporaryDirectory()
        base = Path(cls._shared.name) / "base"
        base.mkdir()
        prepare_run(base)
        assert cli.main(["pipeline", "--run-dir", str(base)]) == 0
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls._shared.cleanup()

    def setUp(self):
        self._local = tempfile.TemporaryDirectory()
        self.run = Path(self._local.name) / "run"
        shutil.copytree(self.base, self.run)
        self.manifest = load_json(self.run / "delivery_manifest.json")

    def tearDown(self):
        self._local.cleanup()

    def bundle_path(self) -> Path:
        return self.run / "delivery" / Path(self.manifest["bundle"]).name


class TestDeliveryArtifacts(DeliveryTestBase):
    def test_manifest_status_and_required_roles(self):
        self.assertEqual(self.manifest["status"], "pass")
        self.assertEqual(self.manifest["rules_deferred"], {})
        roles = {item["role"] for item in self.manifest["items"]}
        for role in package_delivery.REQUIRED_FILES.values():
            self.assertIn(role, roles)
        self.assertIn("report_document", roles)
        self.assertIn("report_chart", roles)
        self.assertTrue(all(item["present"] for item in self.manifest["items"]
                            if item["required"]))

    def test_hashes_and_sizes(self):
        for item in self.manifest["items"]:
            self.assertTrue(item["present"], msg=item["path"])
            self.assertGreater(item["bytes"], 0)
            self.assertEqual(len(item["sha256"]), 64)
            self.assertEqual(item["sha256"], package_delivery._sha256(self.run / item["path"]))

    def test_aigc_and_version_consistency(self):
        self.assertIn("AI", self.manifest["aigc_note"])
        results = load_json(self.run / "results.json")
        self.assertEqual(self.manifest["final_version_id"], results["final_version_id"])
        self.assertEqual(self.manifest["config_hash"], results["config_hash"])
        version = next(v for v in results["versions"]
                       if v["version_id"] == results["final_version_id"])
        self.assertAlmostEqual(float(self.manifest["total_tco2e"]),
                               float(version["total"]), places=6)

    def test_evidence_index_is_reverse_mapped(self):
        index = load_json(self.run / "evidence_index.json")
        ledger = load_json(self.run / "activity_ledger.json")
        self.assertEqual(index["row_count"], len(ledger["rows"]))
        self.assertGreater(index["evidence_count"], 0)
        self.assertEqual(index["evidence_count"], self.manifest["evidence_count"])
        known = {name for row in ledger["rows"] for name in row["evidence_files"]}
        self.assertEqual({entry["file"] for entry in index["evidence"]}, known)
        self.assertTrue(all(entry["rows"] for entry in index["evidence"]))

    def test_bundle_contains_every_item(self):
        path = self.bundle_path()
        self.assertTrue(path.is_file())
        with zipfile.ZipFile(str(path)) as archive:
            names = set(archive.namelist())
        for item in self.manifest["items"]:
            self.assertIn(item["path"], names)
        self.assertIn("delivery_manifest.json", names)
        self.assertIn("evidence_index.json", names)
        self.assertGreater(len(names), 12)

    def test_checks_are_clean_and_all_rules_run(self):
        checks = load_json(self.run / "checks.json")
        self.assertEqual(checks["status"], "pass")
        self.assertEqual(checks["errors"], [])
        self.assertEqual(checks["milestone"], "M1+M2+M3+M5")
        self.assertIn("V20", checks["rules_run"])
        self.assertTrue(checks["delivery_ready"])
        self.assertEqual(checks["rules_deferred"], {})


class TestDeliveryGuards(DeliveryTestBase):
    def test_dirty_checks_block_delivery(self):
        checks = load_json(self.run / "checks.json")
        checks["status"] = "fail"
        checks["errors"] = [{"rule": "V04", "object": "total",
                             "message": "synthetic failure"}]
        write_json(self.run / "checks.json", checks)
        result = package_delivery.deliver(self.run)
        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["bundle"])
        self.assertEqual(cli.main(["deliver", "--run-dir", str(self.run)]), 2)

    def test_missing_required_file_returns_incomplete(self):
        (self.run / "ghg_inventory.xlsx").unlink()
        result = package_delivery.deliver(self.run)
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("ghg_inventory.xlsx", result["missing"])

    def test_v20_detects_missing_artifact(self):
        (self.run / "classification.json").unlink()
        self.assertEqual(cli.main(["check", "--run-dir", str(self.run)]), 2)
        checks = load_json(self.run / "checks.json")
        self.assertTrue(any(e["rule"] == "V20" and "classification.json" in e["object"]
                            for e in checks["errors"]))

    def test_v20_detects_missing_report_document(self):
        report = next(d["path"] for d in
                      load_json(self.run / "report_manifest.json")["documents"]
                      if d["mode"] == "A")
        (self.run / report).unlink()
        self.assertEqual(cli.main(["check", "--run-dir", str(self.run)]), 2)
        checks = load_json(self.run / "checks.json")
        self.assertTrue(any(e["rule"] == "V20" and report in e["object"]
                            for e in checks["errors"]))

    def test_v20_summates_prior_errors(self):
        results = load_json(self.run / "results.json")
        results["versions"][0]["total"] = 999
        write_json(self.run / "results.json", results)
        self.assertEqual(cli.main(["check", "--run-dir", str(self.run)]), 2)
        checks = load_json(self.run / "checks.json")
        self.assertTrue(any(e["rule"] == "V20" for e in checks["errors"]))
        self.assertFalse(checks["delivery_ready"])

    def test_no_remaining_milestones(self):
        self.assertEqual(cli.MILESTONE_OF_UNIMPLEMENTED, {})

    def test_delivery_refuses_to_overwrite_on_blocked_checks(self):
        before = (self.run / "delivery_manifest.json").read_text(encoding="utf-8")
        checks = load_json(self.run / "checks.json")
        checks["status"] = "fail"
        write_json(self.run / "checks.json", checks)
        self.assertEqual(cli.main(["deliver", "--run-dir", str(self.run)]), 2)
        after = (self.run / "delivery_manifest.json").read_text(encoding="utf-8")
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
