# -*- coding: utf-8 -*-
"""Image voucher extractor (M4).

The script never performs OCR. It registers the image as a manual-entry item;
an agent with visual capability may inject a low-confidence candidate through
hint['vision_candidates'], but human sign-off remains mandatory either way.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseExtractor, ExtractorResult, RawRecord
from normalize_units import canonical_unit

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}


class ImageVoucherExtractor(BaseExtractor):
    name = "image_voucher"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_SUFFIXES

    def extract(self, path: Path, hint: dict[str, Any] | None = None) -> ExtractorResult:
        hint = hint or {}
        rules = hint.get("rules") or {}
        reasons = rules.get("manual_reasons") or {}
        candidates = hint.get("vision_candidates") or {}
        candidate = (candidates.get(path.name)
                     or candidates.get(str(path))
                     or {})
        period = candidate.get("period") or {}
        value = candidate.get("value")
        unit = canonical_unit(str(candidate.get("unit") or ""))

        record = RawRecord(
            source_file=path.name, extractor=self.name,
            observed_value=value, observed_unit=unit,
            source_locator="image", voucher_period=str(period.get("start", "")),
            confidence="low", needs_manual=True,
            metadata={
                "vision_hint": str(reasons.get(
                    "image_voucher", "visual reading then human sign-off")),
                "vision_candidate_supplied": bool(candidate),
                "period": period,
                "image_file": path.name,
            })
        return ExtractorResult([record], [str(reasons.get(
            "image_voucher", "image voucher requires manual confirmation"))])
