# -*- coding: utf-8 -*-
"""Electronic invoice PDF extractor (M4).

Prefers the consumption period found in the invoice remark over the issue
date. Never converts a monetary amount into a physical quantity: that needs a
runtime price table and is flagged for human resolution instead.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import BaseExtractor, ExtractorResult, RawRecord
from normalize_units import canonical_unit
from parse_period import resolve_period


def _read_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:  # noqa: BLE001 - treated as an unreadable voucher
        return ""


def _parse_fields(text: str, aliases: dict[str, list[str]]) -> dict[str, str]:
    found: dict[str, str] = {}
    for key, candidates in aliases.items():
        for label in candidates:
            pattern = re.compile(
                re.escape(label) + r"\s*[:：]\s*([^\n\r|]{1,80})")
            match = pattern.search(text)
            if match:
                found[key] = match.group(1).strip()
                break
    return found


def _to_number(text: str | None) -> Any:
    if text is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(text).replace(",", ""))
    if not match:
        return None
    token = match.group(0)
    return float(token) if "." in token else int(token)


class PdfInvoiceExtractor(BaseExtractor):
    name = "pdf_invoice"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def extract(self, path: Path, hint: dict[str, Any] | None = None) -> ExtractorResult:
        hint = hint or {}
        rules = hint.get("rules") or {}
        reasons = rules.get("manual_reasons") or {}
        aliases = rules.get("field_aliases") or {}
        text = _read_text(path)
        warnings: list[str] = []

        if not text.strip():
            warnings.append(str(reasons.get("no_text_layer", "no text layer")))
            record = RawRecord(
                source_file=path.name, extractor=self.name,
                observed_value=None, observed_unit="",
                source_locator="page1", confidence="low", needs_manual=True,
                metadata={"reason": "no_text_layer"})
            return ExtractorResult([record], warnings)

        fields = _parse_fields(text, aliases)
        period = resolve_period(fields.get("remark"), fields.get("issue_date"),
                                rules, hint.get("reporting_year"))
        warnings.extend(period.get("warnings", []))

        quantity = _to_number(fields.get("quantity"))
        unit = canonical_unit(fields.get("unit", "") or "")
        total = _to_number(fields.get("total"))
        needs_manual = bool(period.get("needs_manual"))

        if quantity is None:
            needs_manual = True
            if total is not None:
                warnings.append(str(reasons.get("amount_only", "amount only")))
        if not unit:
            needs_manual = True
            warnings.append(str(reasons.get("missing_unit", "missing unit")))
        if period.get("confidence") == "low":
            needs_manual = True

        record = RawRecord(
            source_file=path.name, extractor=self.name,
            observed_value=quantity, observed_unit=unit,
            source_locator=f"page1:{fields.get('invoice_no', 'invoice')}",
            voucher_period=period.get("start", ""),
            confidence=str(period.get("confidence", "low")),
            needs_manual=needs_manual,
            metadata={
                "period": period,
                "fields": fields,
                "monetary_total": total,
                "item": fields.get("item"),
            })
        return ExtractorResult([record], warnings)
