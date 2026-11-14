# -*- coding: utf-8 -*-
"""Stage 1 - voucher period normalization (M4).

Invoice issue dates are not consumption periods. This module prefers explicit
billing windows and year-month markers found in voucher remarks, and marks
everything else for human resolution instead of guessing.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any

EMPTY_PERIOD: dict[str, Any] = {
    "start": "",
    "end": "",
    "basis": "estimated",
    "billing_note": None,
    "confidence": "low",
    "needs_manual": True,
    "warnings": [],
}


def _parse_date(text: str) -> date | None:
    match = re.search(r"(\d{4})\s*[-/年]\s*(\d{1,2})\s*[-/月]\s*(\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _month_bounds(year: int, month: int) -> tuple[date, date] | None:
    if not 1 <= month <= 12:
        return None
    try:
        last = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last)
    except (ValueError, calendar.IllegalMonthError):
        return None


def _result(start: date | None, end: date | None, basis: str,
            note: str | None, confidence: str,
            warnings: list[str]) -> dict[str, Any]:
    return {
        "start": start.isoformat() if start else "",
        "end": end.isoformat() if end else "",
        "basis": basis,
        "billing_note": note,
        "confidence": confidence,
        "needs_manual": not (start and end) or confidence == "low",
        "warnings": warnings,
    }


def parse_period(text: str, rules: dict | None = None,
                 reporting_year: int | None = None,
                 *, is_issue_date: bool = False) -> dict[str, Any]:
    """Resolve a period from a voucher fragment; never infer silently."""
    patterns = ((rules or {}).get("period_patterns") or {})
    reasons = ((rules or {}).get("manual_reasons") or {})
    raw = str(text or "").strip()
    if not raw:
        return dict(EMPTY_PERIOD, warnings=[str(reasons.get("missing_unit", "no period text"))])

    warnings: list[str] = []
    # An issue date is never a consumption period. Do not attempt to parse it
    # into a month: that would silently invent the reporting period.
    if is_issue_date:
        warnings.append(str(reasons.get(
            "issue_date_only", "issue date is not the consumption period")))
        return _result(None, None, "estimated", raw, "low", warnings)

    date_range = re.search(patterns.get("date_range", r"$^") , raw)
    if date_range:
        start, end = _parse_date(date_range.group(1)), _parse_date(date_range.group(2))
        if start and end:
            if (start.year, start.month) != (end.year, end.month):
                warnings.append(str(reasons.get("cross_month", "cross-month billing window")))
            return _result(start, end, "billing",
                           date_range.group(0), "high", warnings)

    ym = re.search(patterns.get("yyyymm", r"$^"), raw, re.IGNORECASE)
    if ym:
        token = ym.group(1)
        bounds = _month_bounds(int(token[:4]), int(token[4:6]))
        if bounds:
            if reporting_year and bounds[0].year != reporting_year:
                warnings.append(str(reasons.get("template_year", "year mismatch")))
            return _result(bounds[0], bounds[1], "consumption",
                           ym.group(0), "high", warnings)

    single = _parse_date(raw)
    if single:
        return _result(single, single, "consumption", raw, "medium", warnings)

    # Only a plain year-month token reaches here; a full ISO date was handled
    # above, so "2000-02-11" can never be mistaken for a February period.
    slash = re.search(patterns.get("yyyymm_slash", r"$^"), raw)
    if slash:
        bounds = _month_bounds(int(slash.group(1)), int(slash.group(2)))
        if bounds:
            return _result(bounds[0], bounds[1], "consumption",
                           slash.group(0), "medium", warnings)

    return dict(EMPTY_PERIOD, warnings=[f"unresolved period text: {raw[:80]}"])


def resolve_period(remark: str | None, issue_date: str | None,
                   rules: dict | None = None,
                   reporting_year: int | None = None) -> dict[str, Any]:
    """Prefer the remark (billing window / year-month) over the issue date."""
    if remark:
        candidate = parse_period(remark, rules, reporting_year)
        if candidate["start"] and candidate["end"]:
            return candidate
    if issue_date:
        return parse_period(issue_date, rules, reporting_year, is_issue_date=True)
    return dict(EMPTY_PERIOD)
