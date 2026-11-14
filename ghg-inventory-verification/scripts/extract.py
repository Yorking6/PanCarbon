# -*- coding: utf-8 -*-
"""Stage 1 orchestration - vouchers to a pending activity ledger (M4).

Every candidate row keeps its source file, confidence, period trace and an
empty confirmation block. Nothing is inferred silently: unreadable vouchers,
ambiguous units and amount-only rows are marked needs_manual.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from extractors import EXTRACTORS
from ghg_common import SKILL_ROOT, canonical_hash, jsonable, load_json, write_json
from normalize_units import canonical_unit

RULES_PATH = SKILL_ROOT / "assets" / "extraction_rules.json"


def _number(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    token = match.group(0)
    return float(token) if "." in token else int(token)


def collect_records(root: Path, hint: dict[str, Any]) -> dict[str, Any]:
    """Walk a directory and dispatch every file to a supporting extractor."""
    instances = [cls() for cls in EXTRACTORS]
    records: list[Any] = []
    warnings: list[str] = []
    stats: dict[str, int] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        matches = [extractor for extractor in instances if extractor.supports(path)]
        if not matches:
            warnings.append(f"{path.name}: no supporting extractor; skipped")
            continue
        for extractor in matches:
            try:
                result = extractor.extract(path, hint)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                warnings.append(f"{path.name}: {extractor.name} failed: {exc}")
                continue
            records.extend(result.records)
            warnings.extend(f"{path.name}: {item}" for item in result.warnings)
            stats[extractor.name] = stats.get(extractor.name, 0) + 1
    return {"records": records, "warnings": warnings, "stats": stats}


def _period_of(record: dict) -> dict:
    metadata = record.get("metadata") or {}
    period = dict(metadata.get("period") or {})
    if not period.get("start"):
        single = str(record.get("voucher_period") or "")
        if single:
            period = {"start": single, "end": single, "basis": "estimated",
                      "billing_note": None, "confidence": "low",
                      "needs_manual": True,
                      "warnings": ["single date only; consumption period unconfirmed"]}
        else:
            period = {"start": "", "end": "", "basis": "estimated",
                      "billing_note": None, "confidence": "low",
                      "needs_manual": True,
                      "warnings": ["no period resolved; manual entry required"]}
    return {
        "start": str(period.get("start") or ""),
        "end": str(period.get("end") or ""),
        "basis": str(period.get("basis") or "estimated"),
        "billing_note": period.get("billing_note"),
        "confidence": str(period.get("confidence") or "low"),
        "needs_manual": bool(period.get("needs_manual", True)),
        "warnings": list(period.get("warnings") or []),
    }


def build_pending(input_dir: Path, cfg: dict, hint: dict[str, Any]) -> dict:
    rules = load_json(RULES_PATH)
    hint = dict(hint)
    hint["rules"] = rules
    hint["reporting_year"] = cfg.get("reporting_year")
    collected = collect_records(input_dir, hint)

    rows: list[dict] = []
    for index, record in enumerate(collected["records"], start=1):
        data = record.as_dict()
        metadata = data.get("metadata") or {}
        period = _period_of(data)
        raw_value = data.get("observed_value")
        unit = canonical_unit(str(data.get("observed_unit") or ""))
        warnings = list(period.get("warnings") or [])
        if raw_value is None:
            warnings.append("no numeric quantity extracted; manual entry required")
        if not unit:
            warnings.append("unit unresolved; manual entry required")
        period["warnings"] = warnings

        rows.append({
            "row_id": f"P{index:03d}",
            "entity_ref": hint.get("entity_ref"),
            "source_key": hint.get("source_key"),
            "scope": hint.get("scope"),
            "s3_category": hint.get("s3_category"),
            "gas": hint.get("gas") or "CO2",
            "scope2_mode": hint.get("scope2_mode"),
            "period": period,
            "raw": {
                "value": raw_value,
                "unit": unit,
                "source_file": str(data.get("source_file") or ""),
                "source_locator": data.get("source_locator"),
                "extractor": str(data.get("extractor") or ""),
                "confidence": str(data.get("confidence") or "low"),
            },
            "normalized": {"value": _number(raw_value), "unit": unit},
            "conversion_chain": [],
            "data_quality": {"activity": "Z", "factor": "C", "instrument": "S"},
            "estimated": False,
            "estimation_note": None,
            "carry_over_from": None,
            "evidence_files": [str(data.get("source_file") or "")],
            "confirmation": {"signed_by": None, "signed_at": None},
            "needs_manual": (bool(data.get("needs_manual"))
                             or bool(period.get("needs_manual"))
                             or raw_value is None or not unit),
            "exclude": False,
            "warnings": warnings,
            "metadata": {k: v for k, v in metadata.items() if k != "period"},
        })

    return {
        "schema_version": "1.0",
        "config_hash": canonical_hash(cfg),
        "rows": rows,
        "warnings": collected["warnings"],
        "extractor_stats": collected["stats"],
    }


def extract_from_run(run: Path, input_dir: Path, hint_path: Path | None = None) -> dict:
    cfg = load_json(run / "org_config.json")
    hint: dict[str, Any] = {}
    default_hint = input_dir / "extraction_hint.json"
    if hint_path and hint_path.is_file():
        hint = load_json(hint_path)
    elif default_hint.is_file():
        hint = load_json(default_hint)
    pending = build_pending(input_dir, cfg, hint)
    write_json(run / "pending_ledger.json", jsonable(pending))
    return pending
