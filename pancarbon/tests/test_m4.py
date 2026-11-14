# -*- coding: utf-8 -*-
"""M4 acceptance tests: voucher extraction and the human confirmation gate.

All vouchers are generated synthetically at run time; no organization data is
stored in this file or in the Skill package.
"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cli  # noqa: E402
import confirm_gate  # noqa: E402
import extract  # noqa: E402
from extractors import EXTRACTORS  # noqa: E402
from extractors.zip_bundle import restore_zip_name  # noqa: E402
from ghg_common import canonical_hash, load_json, load_schema, validate_schema, write_json  # noqa: E402
from parse_period import parse_period, resolve_period  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
ASSETS = ROOT / "assets"
RULES = load_json(ASSETS / "extraction_rules.json")


def make_pdf(path: Path, lines: list[str]) -> None:
    """Write a minimal text PDF that pypdf can extract."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=320, height=240)
    chunks = []
    for index, line in enumerate(lines):
        safe = line.replace("(", "[").replace(")", "]")
        chunks.append(f"BT /F1 10 Tf 10 {220 - index * 14} Td ({safe}) Tj ET")
    content = DecodedStreamObject()
    content.set_data("\n".join(chunks).encode("ascii", "replace"))
    page[NameObject("/Contents")] = writer._add_object(content)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    })
    page[NameObject("/Resources")] = resources
    with open(str(path), "wb") as handle:
        writer.write(handle)


def make_monthly_xlsx(path: Path, total: object = 200) -> None:
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "monthly"
    sheet.append(["类型"] + [f"{i}月" for i in range(1, 13)] + ["合计"])
    sheet.append(["数量/50公斤"] + [10] * 12 + [total])
    sheet.append(["金额"] + [5] * 12 + ["=SUM(B3:M3)"])
    book.save(str(path))


def make_detail_xlsx(path: Path) -> None:
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "detail"
    sheet.append(["序号", "品名", "数量", "单位", "金额", "发票号码"])
    sheet.append([1, "synthetic item", 12.5, "L", 100, "SYN-0001"])
    sheet.append([2, "fee only", None, "", 250, "SYN-0002"])
    book.save(str(path))


def make_image(path: Path) -> None:
    from PIL import Image
    Image.new("RGB", (24, 24), (240, 240, 240)).save(str(path))


def make_zip(path: Path, lines: list[str]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        inner = Path(tmp) / "inner.pdf"
        make_pdf(inner, lines)
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(inner, arcname="nested_invoice.pdf")


def prepare_run(run: Path) -> dict:
    cfg = load_json(FIXTURES / "org_config.m1.json")
    factors = load_json(FIXTURES / "factor_library.m1.json")
    write_json(run / "org_config.json", cfg)
    write_json(run / "factor_library.json", factors)
    return cfg


def human_fill(pending: dict) -> dict:
    """Simulate the human review of the pending confirmation table."""
    for row in pending["rows"]:
        if row["raw"]["extractor"] == "image_voucher" and \
           row["normalized"]["value"] is None:
            row["raw"]["value"] = 50
            row["normalized"] = {"value": 50, "unit": "kg"}
        if row["normalized"]["value"] is None:
            row["exclude"] = True
            continue
        if not row["period"]["start"]:
            row["period"] = {
                "start": "2000-01-01", "end": "2000-01-31",
                "basis": "consumption", "billing_note": None,
                "confidence": "medium", "needs_manual": True,
                "warnings": ["period supplied during human review"],
            }
    return pending


def hint_for(name: str = "voucher_image.jpg") -> dict:
    return {
        "entity_ref": "E1",
        "source_key": "fuel_combustion",
        "scope": "S1",
        "s3_category": None,
        "scope2_mode": None,
        "gas": "CO2",
        "vision_candidates": {
            name: {
                "value": 50,
                "unit": "kg",
                "period": {
                    "start": "2000-01-01", "end": "2000-01-31",
                    "basis": "consumption", "confidence": "low",
                    "needs_manual": True, "warnings": [],
                },
            }
        },
    }


class TestPeriodParsing(unittest.TestCase):
    def test_year_month_marker_in_remark(self):
        period = parse_period("Remark: ym:200001", RULES, 2000)
        self.assertEqual(period["start"], "2000-01-01")
        self.assertEqual(period["end"], "2000-01-31")
        self.assertEqual(period["basis"], "consumption")
        self.assertFalse(period["needs_manual"])

    def test_billing_window_and_cross_month_warning(self):
        period = parse_period("period 2000-01-11至2000-02-10", RULES, 2000)
        self.assertEqual(period["start"], "2000-01-11")
        self.assertEqual(period["end"], "2000-02-10")
        self.assertEqual(period["basis"], "billing")
        self.assertTrue(any("cross" in w.lower() for w in period["warnings"]))

    def test_template_year_mismatch_is_flagged(self):
        period = parse_period("ym:199901", RULES, 2000)
        self.assertTrue(period["warnings"])

    def test_issue_date_is_not_consumption_period(self):
        period = resolve_period(None, "2000-02-11", RULES, 2000)
        self.assertFalse(period["start"])
        self.assertTrue(period["needs_manual"])
        self.assertTrue(period["warnings"])

    def test_remark_preferred_over_issue_date(self):
        period = resolve_period("ym:200001", "2000-02-11", RULES, 2000)
        self.assertEqual(period["start"], "2000-01-01")
        self.assertFalse(period["needs_manual"])


class TestExtractors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hint = {"rules": RULES, "reporting_year": 2000}

    def tearDown(self):
        self.tmp.cleanup()

    def _dispatch(self, path: Path):
        for cls in EXTRACTORS:
            extractor = cls()
            if extractor.supports(path):
                return extractor.extract(path, self.hint)
        self.fail(f"no extractor supports {path.name}")

    def test_pdf_invoice_fields_and_period(self):
        path = self.root / "invoice.pdf"
        make_pdf(path, [
            "Item: synthetic fuel", "Quantity: 100 kg", "Unit: kg",
            "Total: 500", "Invoice No: SYN-0001",
            "Issue Date: 2000-02-11", "Remark: ym:200001",
        ])
        result = self._dispatch(path)
        self.assertEqual(len(result.records), 1)
        record = result.records[0].as_dict()
        self.assertEqual(float(record["observed_value"]), 100)
        self.assertEqual(record["observed_unit"], "kg")
        self.assertEqual(record["voucher_period"], "2000-01-01")
        self.assertFalse(record["needs_manual"])

    def test_pdf_no_text_layer_is_manual(self):
        path = self.root / "blank.pdf"
        make_pdf(path, [])
        result = self._dispatch(path)
        self.assertTrue(result.records[0].needs_manual)
        self.assertTrue(result.warnings)

    def test_pdf_amount_only_is_not_converted(self):
        path = self.root / "amount.pdf"
        make_pdf(path, ["Total: 500", "Remark: ym:200001", "Unit: CNY"])
        result = self._dispatch(path)
        self.assertIsNone(result.records[0].observed_value)
        self.assertTrue(result.records[0].needs_manual)
        self.assertTrue(any("amount" in w.lower() for w in result.warnings))

    def test_excel_monthly_unit_from_label(self):
        path = self.root / "monthly.xlsx"
        make_monthly_xlsx(path, 200)
        result = self._dispatch(path)
        records = [r.as_dict() for r in result.records]
        self.assertTrue(any(r["observed_unit"] == "kg" and
                            r["observed_value"] == 200 for r in records))

    def test_excel_broken_total_is_flagged(self):
        path = self.root / "broken.xlsx"
        make_monthly_xlsx(path, None)
        result = self._dispatch(path)
        self.assertTrue(all(r.needs_manual for r in result.records))
        self.assertTrue(any("formula" in w.lower() or "missing total" in w.lower()
                            for w in result.warnings))

    def test_excel_detail_and_amount_only_row(self):
        path = self.root / "detail.xlsx"
        make_detail_xlsx(path)
        result = self._dispatch(path)
        records = [r.as_dict() for r in result.records]
        self.assertTrue(any(r["observed_value"] == 12.5 and
                            r["observed_unit"] == "L" for r in records))
        self.assertTrue(any(r["observed_value"] is None and r["needs_manual"]
                            for r in records))

    def test_zip_member_is_dispatched(self):
        path = self.root / "bundle.zip"
        make_zip(path, ["Quantity: 30 kg", "Unit: kg", "Remark: ym:200001"])
        result = self._dispatch(path)
        self.assertEqual(len(result.records), 1)
        self.assertIn("bundle.zip::", result.records[0].source_file)
        self.assertEqual(float(result.records[0].observed_value), 30)

    def test_gbk_member_name_restoration(self):
        info = zipfile.ZipInfo()
        info.filename = "发票01.pdf".encode("gbk").decode("cp437")
        info.flag_bits = 0
        self.assertEqual(restore_zip_name(info), "发票01.pdf")

    def test_image_requires_manual_and_accepts_vision_candidate(self):
        path = self.root / "voucher_image.jpg"
        make_image(path)
        plain = self._dispatch(path)
        self.assertTrue(plain.records[0].needs_manual)
        self.assertIsNone(plain.records[0].observed_value)
        richer = dict(self.hint, vision_candidates=hint_for()["vision_candidates"])
        candidate = None
        for cls in EXTRACTORS:
            instance = cls()
            if instance.supports(path):
                candidate = instance.extract(path, richer).records[0]
        self.assertIsNotNone(candidate)
        self.assertEqual(float(candidate.observed_value), 50)
        self.assertTrue(candidate.needs_manual)


class TestPendingAndGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        self.cfg = prepare_run(self.run)
        self.vouchers = self.run / "vouchers"
        self.vouchers.mkdir()
        make_pdf(self.vouchers / "invoice.pdf", [
            "Item: synthetic fuel", "Quantity: 100 kg", "Unit: kg",
            "Remark: ym:200001"])
        make_monthly_xlsx(self.vouchers / "monthly.xlsx", 200)
        make_image(self.vouchers / "voucher_image.jpg")
        make_zip(self.vouchers / "bundle.zip", [
            "Quantity: 30 kg", "Unit: kg", "Remark: ym:200001"])
        write_json(self.run / "hint.json", hint_for())

    def tearDown(self):
        self.tmp.cleanup()

    def _extract(self):
        return extract.extract_from_run(self.run, self.vouchers, self.run / "hint.json")

    def test_pending_ledger_matches_schema_and_keeps_trace(self):
        pending = self._extract()
        self.assertEqual(validate_schema(pending, load_schema("pending_ledger")), [])
        self.assertGreaterEqual(len(pending["rows"]), 4)
        self.assertTrue(all(row["confirmation"]["signed_by"] is None
                            for row in pending["rows"]))
        self.assertTrue(all(row["raw"]["source_file"] for row in pending["rows"]))
        self.assertTrue(any(row["needs_manual"] for row in pending["rows"]))
        self.assertEqual(pending["config_hash"], canonical_hash(self.cfg))

    def test_confirm_rejects_unsigned_rows(self):
        pending = self._extract()
        ledger, report = confirm_gate.confirm(pending, self.cfg)
        self.assertIsNone(ledger)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(len(report["unsigned"]), len(pending["rows"]))

    def test_confirm_rejects_missing_estimate_reason(self):
        pending = self._extract()
        signoff = {"signed_by": "Synthetic Reviewer", "signed_at": "2000-12-31T00:00:00"}
        pending["rows"][0]["estimated"] = True
        pending["rows"][0]["estimation_note"] = None
        ledger, report = confirm_gate.confirm(pending, self.cfg, signoff)
        self.assertIsNone(ledger)
        self.assertTrue(any("estimation_note" in e for e in report["errors"]))

    def test_batch_signoff_produces_valid_ledger(self):
        pending = human_fill(self._extract())
        signoff = {"signed_by": "Synthetic Reviewer", "signed_at": "2000-12-31T00:00:00"}
        ledger, report = confirm_gate.confirm(pending, self.cfg, signoff)
        self.assertIsNotNone(ledger)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(validate_schema(ledger, load_schema("activity_ledger")), [])
        self.assertTrue(all(row["confirmation"]["method"] == "batch_signoff"
                            for row in ledger["rows"]))

    def test_cli_extract_confirm_then_pipeline(self):
        self.assertEqual(cli.main(["extract", "--run-dir", str(self.run),
                                   "--input-dir", str(self.vouchers),
                                   "--hint", str(self.run / "hint.json")]), 0)
        pending = human_fill(load_json(self.run / "pending_ledger.json"))
        write_json(self.run / "pending_ledger.json", pending)
        signoff_path = self.run / "batch_signoff.json"
        write_json(signoff_path, {"signed_by": "Synthetic Reviewer",
                                  "signed_at": "2000-12-31T00:00:00"})
        self.assertEqual(cli.main(["confirm", "--run-dir", str(self.run),
                                   "--batch-signoff", str(signoff_path)]), 0)
        checks_report = load_json(self.run / "confirm_check.json")
        self.assertEqual(checks_report["status"], "pass")
        self.assertEqual(cli.main(["pipeline", "--run-dir", str(self.run)]), 0)
        checks = load_json(self.run / "checks.json")
        self.assertEqual(checks["status"], "pass")
        self.assertEqual(checks["rules_deferred"], {})
        self.assertTrue((self.run / "delivery_manifest.json").is_file())

    def test_delivery_bundle_exists_after_pipeline(self):
        self.assertEqual(cli.main(["extract", "--run-dir", str(self.run),
                                   "--input-dir", str(self.vouchers),
                                   "--hint", str(self.run / "hint.json")]), 0)
        pending = human_fill(load_json(self.run / "pending_ledger.json"))
        write_json(self.run / "pending_ledger.json", pending)
        signoff_path = self.run / "batch_signoff.json"
        write_json(signoff_path, {"signed_by": "Synthetic Reviewer",
                                  "signed_at": "2000-12-31T00:00:00"})
        self.assertEqual(cli.main(["confirm", "--run-dir", str(self.run),
                                   "--batch-signoff", str(signoff_path)]), 0)
        self.assertEqual(cli.main(["pipeline", "--run-dir", str(self.run)]), 0)
        manifest = load_json(self.run / "delivery_manifest.json")
        self.assertEqual(manifest["status"], "pass")
        self.assertTrue(Path(manifest["bundle"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
