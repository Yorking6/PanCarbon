# -*- coding: utf-8 -*-
"""Stage 4 - method selection and emission factor matching (M1).

Ambiguity is never resolved by the engine: multiple equally ranked factors,
missing factors, incompatible units or unreconciled conversion chains are
reported as candidates/issues and produce no calculated emission.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ghg_common import canonical_hash
from normalize_units import (
    apply_conversion_chain,
    as_decimal,
    canonical_unit,
    scale_matches,
)

WILDCARD = "*"


def _method_for(cfg: dict, source_key: str) -> tuple[str | None, str]:
    meth = cfg.get("methodology", {}) or {}
    per_source = meth.get("per_source", {}) or {}
    entry = per_source.get(source_key)
    if isinstance(entry, dict):
        return entry.get("method"), "per_source"
    if isinstance(entry, str) and entry.strip():
        return entry, "per_source"
    default = meth.get("default")
    if isinstance(default, str) and default.strip():
        return default, "default"
    return None, "missing"


def _year_ok(value: Any, reporting_year: int | None) -> bool:
    if value in (None, "", WILDCARD):
        return True
    try:
        return int(value) == reporting_year
    except (TypeError, ValueError):
        return False


def _period_ok(factor: dict, reporting_year: int | None) -> bool:
    if reporting_year is None:
        return True
    lo, hi = factor.get("valid_from"), factor.get("valid_to")
    try:
        if lo not in (None, "") and reporting_year < int(str(lo)[:4]):
            return False
        if hi not in (None, "") and reporting_year > int(str(hi)[:4]):
            return False
    except (TypeError, ValueError):
        return False
    return True


def _eligible(factor: dict, source_key: str, method: str, region: str | None,
              cfg: dict) -> bool:
    app = factor.get("applicability", {}) or {}
    if str(app.get("activity") or "") not in (source_key, WILDCARD):
        return False
    if str(app.get("method") or "") not in (method, WILDCARD):
        return False
    fac_region = app.get("region")
    if fac_region not in (None, "", WILDCARD) and fac_region != region:
        return False
    if not _year_ok(app.get("year"), cfg.get("reporting_year")):
        return False
    gwp_version = factor.get("gwp_version")
    if gwp_version not in (cfg.get("gwp_version"), "not_applicable"):
        return False
    return _period_ok(factor, cfg.get("reporting_year"))


def match(cfg: dict, ledger: dict, classification: dict, library: dict) -> dict:
    out: dict[str, Any] = {
        "stage": 4,
        "status": "fail",
        "config_hash": canonical_hash(cfg),
        "lines": [],
        "candidates": [],
        "errors": [],
        "warnings": [],
    }
    if classification.get("status") != "pass":
        out["errors"].append("classification status is not pass")
        return out
    if classification.get("config_hash") != out["config_hash"]:
        out["errors"].append("classification.config_hash does not match org_config")
        return out

    factors = library.get("factors", []) or []
    if not factors:
        out["errors"].append("factor library is empty")
        return out

    ledger_rows = {r.get("row_id"): r for r in ledger.get("rows", [])}
    entities = {e.get("id"): e for e in cfg.get("entities", [])}
    reporting_year = cfg.get("reporting_year")

    for entry in classification.get("rows", []):
        if not entry.get("applicable"):
            continue
        row_id = entry["row_id"]
        row = ledger_rows.get(row_id)
        if row is None:
            out["errors"].append(f"row {row_id}: missing from activity ledger")
            continue

        source_key = entry.get("source_key")
        method, method_origin = _method_for(cfg, source_key)
        region = (entities.get(entry.get("entity_ref")) or {}).get("grid_region_ref")
        raw = row.get("raw", {}) or {}
        normalized = row.get("normalized", {}) or {}
        ad_unit = canonical_unit(str(normalized.get("unit") or ""))
        chain = row.get("conversion_chain", []) or []

        replay = apply_conversion_chain(raw.get("value"), raw.get("unit", ""), chain)
        line: dict[str, Any] = {
            "row_id": row_id,
            "entity_ref": entry.get("entity_ref"),
            "scope": entry.get("scope"),
            "s3_category": entry.get("s3_category"),
            "scope2_mode": entry.get("scope2_mode"),
            "source_key": source_key,
            "gas": entry.get("gas"),
            "method": method,
            "method_origin": method_origin,
            "factor_id": None,
            "ad": as_decimal(normalized.get("value")),
            "ad_unit": ad_unit,
            "ef": None,
            "ef_unit": None,
            "gwp": None,
            "scale": None,
            "derived_scale": None,
            "status": "missing",
            "candidates": [],
            "warnings": [],
            "applied_conversion": replay["applied"],
        }
        for issue in replay["errors"]:
            line["warnings"].append(f"conversion_chain: {issue}")

        if method is None:
            line["status"] = "ambiguous"
            line["warnings"].append("no calculation method resolved for this source")
        else:
            eligible = [f for f in factors
                        if _eligible(f, source_key, method, region, cfg)]
            eligible.sort(key=lambda f: int(f.get("priority") or 0))
            line["candidates"] = [
                {"factor_id": f.get("id"), "priority": f.get("priority"),
                 "value": f.get("value"), "unit": f.get("unit"),
                 "source": (f.get("source") or {}).get("name")}
                for f in eligible
            ]
            if not eligible:
                line["status"] = "missing"
                line["warnings"].append("no eligible factor for activity/method/region/year")
            else:
                top_priority = int(eligible[0].get("priority") or 0)
                top = [f for f in eligible
                       if int(f.get("priority") or 0) == top_priority]
                if len(top) > 1:
                    line["status"] = "ambiguous"
                    line["warnings"].append(
                        f"{len(top)} equally ranked factors; human decision required")
                    out["candidates"].append({"row_id": row_id, "factor_ids":
                                              [f.get("id") for f in top]})
                else:
                    factor = top[0]
                    line.update({
                        "factor_id": factor.get("id"),
                        "ef": as_decimal(factor.get("value")),
                        "ef_unit": factor.get("unit"),
                        "scale": factor.get("scale"),
                        "status": "matched",
                    })
                    gases = factor.get("gases", {}) or {}
                    gas = entry.get("gas") or "CO2"
                    if not gases:
                        line["gwp"] = Decimal(1)
                    elif gas in gases:
                        line["gwp"] = as_decimal(gases[gas])
                    else:
                        line["status"] = "ambiguous"
                        line["warnings"].append(
                            f"factor has no GWP entry for gas {gas!r}; no implicit fallback")

                    contract = scale_matches(ad_unit, str(factor.get("unit") or ""),
                                             factor.get("scale"))
                    line["derived_scale"] = contract.get("scale")
                    if not contract.get("match"):
                        line["status"] = "dimension_mismatch"
                        line["warnings"].append(
                            "scale contract: " + str(contract.get("reason")))

        # Replay consistency: raw value must reproduce the declared normalized value.
        try:
            declared = as_decimal(normalized.get("value"))
            if replay["value"] != declared or replay["unit"] != ad_unit:
                line["status"] = "conversion_mismatch"
                line["warnings"].append(
                    f"conversion chain yields {replay['value']} {replay['unit']}, "
                    f"ledger declares {declared} {ad_unit}")
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed silently
            line["status"] = "conversion_mismatch"
            line["warnings"].append(f"normalized value unreadable: {exc}")

        if method == "spend_based":
            ops = {str(step.get("op")) for step in chain if isinstance(step, dict)}
            if "currency_conversion" not in ops:
                line["warnings"].append(
                    "spend_based method without a currency_conversion step in the chain")

        if row.get("carry_over_from") and not row.get("estimation_note"):
            line["warnings"].append("carry-over row lacks estimation_note")

        out["lines"].append(line)
        out["warnings"].extend(f"row {row_id}: {w}" for w in line["warnings"])

    out["status"] = ("pass" if all(l["status"] == "matched" for l in out["lines"])
                     and not out["errors"] else "partial")
    return out
