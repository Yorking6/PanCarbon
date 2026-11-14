# -*- coding: utf-8 -*-
"""Stage 3 - emission source identification (M1).

Maps signed activity ledger rows to Scope 1/2/3 and the 15 GHG Protocol Scope 3
categories. Nothing is inferred silently: unmapped or contradictory rows are
reported for human resolution.
"""
from __future__ import annotations

from typing import Any

from ghg_common import canonical_hash

DEFAULT_SCOPE2_MODE = "location_based"


def _year_of(value: Any) -> int | None:
    text = str(value or "")
    if len(text) >= 4 and text[:4].isdigit():
        return int(text[:4])
    return None


def classify(cfg: dict, ledger: dict) -> dict:
    entity_ids = {e.get("id") for e in cfg.get("entities", [])}
    reporting_year = cfg.get("reporting_year")
    s2_modes = set(cfg.get("scope2", {}).get("modes", []))
    enabled = set(cfg.get("scope3", {}).get("enabled_categories", []))
    reasons = cfg.get("scope3", {}).get("not_applicable_reasons", {})
    gases = set(cfg.get("gases", []))

    out: dict[str, Any] = {
        "stage": 3,
        "status": "fail",
        "config_hash": canonical_hash(cfg),
        "rows": [],
        "categories": {},
        "unmapped": [],
        "errors": [],
        "warnings": [],
    }

    # Hard confirmation gate, repeated defensively before any calculation.
    for row in ledger.get("rows", []):
        conf = row.get("confirmation", {}) or {}
        if not str(conf.get("signed_by") or "").strip() or not str(conf.get("signed_at") or "").strip():
            out["errors"].append(f"row {row.get('row_id')}: missing human sign-off")
    if out["errors"]:
        return out

    if ledger.get("config_hash") not in (None, "", "SYNTHETIC_HASH", out["config_hash"]):
        out["errors"].append("ledger.config_hash does not match org_config")
    if out["errors"]:
        return out

    for row in ledger.get("rows", []):
        row_id = row.get("row_id")
        scope = row.get("scope")
        source_key = row.get("source_key")
        entity_ref = row.get("entity_ref")
        s3_cat = row.get("s3_category")
        period = row.get("period", {}) or {}
        issues: list[str] = []

        if entity_ref not in entity_ids:
            issues.append(f"entity_ref {entity_ref!r} not present in org_config.entities")
        if not source_key:
            issues.append("source_key is missing")
        if scope not in ("S1", "S2", "S3"):
            issues.append(f"scope {scope!r} is invalid")

        start_year, end_year = _year_of(period.get("start")), _year_of(period.get("end"))
        if reporting_year and {start_year, end_year} == {None}:
            issues.append("period has no resolvable start/end")
        elif reporting_year and start_year and end_year:
            if start_year != reporting_year and end_year != reporting_year:
                issues.append("period lies entirely outside the reporting year")
            elif start_year != reporting_year or end_year != reporting_year:
                out["warnings"].append(
                    f"row {row_id}: period crosses the reporting year boundary; "
                    f"explicit split required by V19"
                )
        if period.get("basis") == "estimated" and not row.get("estimation_note"):
            out["warnings"].append(f"row {row_id}: estimated period without estimation_note")

        gas = row.get("gas") or "CO2"
        if gas not in gases:
            issues.append(f"gas {gas!r} not declared in org_config.gases")

        s2_mode = row.get("scope2_mode")
        if scope == "S2":
            s2_mode = s2_mode or DEFAULT_SCOPE2_MODE
            if s2_mode not in s2_modes:
                issues.append(f"scope2_mode {s2_mode!r} not enabled in org_config.scope2.modes")

        if scope == "S3":
            if not isinstance(s3_cat, int) or not 1 <= s3_cat <= 15:
                issues.append("S3 row requires s3_category within 1..15")
            elif s3_cat not in enabled:
                issues.append(
                    f"Scope 3 category {s3_cat} carries data but is not enabled in org_config"
                )
        elif s3_cat not in (None, ""):
            out["warnings"].append(f"row {row_id}: s3_category set on a non-S3 row; ignored")

        if row.get("estimated") and not row.get("estimation_note"):
            out["warnings"].append(f"row {row_id}: estimated value without estimation_note")
        if row.get("carry_over_from") and not row.get("estimation_note"):
            out["warnings"].append(f"row {row_id}: carry-over without estimation_note")

        applicable = not issues
        entry = {
            "row_id": row_id,
            "entity_ref": entity_ref,
            "scope": scope,
            "iso_category": row.get("iso_category"),
            "s3_category": s3_cat if scope == "S3" else None,
            "source_key": source_key,
            "gas": gas,
            "scope2_mode": s2_mode,
            "applicable": applicable,
            "reason_if_not": "; ".join(issues) if issues else None,
        }
        out["rows"].append(entry)
        if not applicable:
            out["unmapped"].append({"row_id": row_id, "reason": entry["reason_if_not"]})

    # Always list all 15 Scope 3 categories, with a reason when not applicable.
    category_map: dict[str, list[str]] = {"S1": [], "S2": []}
    for key in range(1, 16):
        category_map[f"S3-{key}"] = []
    for entry in out["rows"]:
        if not entry["applicable"]:
            continue
        if entry["scope"] == "S3":
            category_map[f"S3-{entry['s3_category']}"].append(entry["row_id"])
        else:
            category_map[entry["scope"]].append(entry["row_id"])

    for key, row_ids in category_map.items():
        if key.startswith("S3-"):
            number = int(key.split("-")[1])
            is_enabled = number in enabled
            out["categories"][key] = {
                "applicable": bool(row_ids) and is_enabled,
                "enabled": is_enabled,
                "row_ids": row_ids,
                "reason_if_not": (
                    str(reasons.get(str(number), reasons.get(number, ""))).strip()
                    if not is_enabled else None
                ),
            }
            if row_ids and not is_enabled:
                out["warnings"].append(f"{key}: rows present but category disabled")
        else:
            out["categories"][key] = {"applicable": bool(row_ids), "row_ids": row_ids,
                                      "reason_if_not": None}

    out["status"] = "pass" if not out["errors"] else "fail"
    return out
