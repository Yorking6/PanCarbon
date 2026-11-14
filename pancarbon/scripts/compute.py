# -*- coding: utf-8 -*-
"""Stage 5 - deterministic calculation engine (M1).

Pure functions only: the same inputs always produce the same results.json.
Every line carries its provenance, and unusable lines are recorded as null with
warnings instead of being silently treated as zero.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from ghg_common import canonical_hash
from normalize_units import as_decimal


class GateError(RuntimeError):
    """Raised when the human confirmation gate or a contract check is violated."""


def assert_confirmation_gate(ledger: dict) -> None:
    unsigned = []
    for row in ledger.get("rows", []):
        conf = row.get("confirmation", {}) or {}
        if not str(conf.get("signed_by") or "").strip() or not str(conf.get("signed_at") or "").strip():
            unsigned.append(str(row.get("row_id")))
    if unsigned:
        raise GateError(
            "confirmation gate blocked calculation; unsigned rows: " + ", ".join(unsigned)
        )


def _dec(value: Any) -> Decimal:
    try:
        return as_decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise GateError(f"non-numeric operand {value!r}: {exc}") from exc


def _calculate_line(line: dict) -> tuple[Decimal | None, list[str]]:
    warnings: list[str] = []
    if line.get("status") != "matched":
        return None, [f"line status is {line.get('status')!r}; emission left null"]
    try:
        ad = _dec(line.get("ad"))
        ef = _dec(line.get("ef"))
        gwp = _dec(line.get("gwp"))
        scale = _dec(line.get("scale"))
        if scale == 0:
            return None, ["scale is zero; emission left null"]
        value = ad * ef * gwp / scale
    except GateError as exc:
        return None, [str(exc)]
    if not value.is_finite():
        return None, ["calculated emission is not finite"]
    return value, warnings


def compute(cfg: dict, ledger: dict, matched: dict, *,
            version_id: str = "V1", method: str | None = None,
            status: str = "final", existing: dict | None = None,
            note: str | None = None) -> dict:
    """Build or extend results.json for one calculation version."""
    assert_confirmation_gate(ledger)

    config_hash = canonical_hash(cfg)
    if matched.get("config_hash") not in (None, "", config_hash):
        raise GateError("matched.config_hash does not match org_config")
    if matched.get("stage") != 4:
        raise GateError("matched payload is not a Stage 4 output")

    lines: list[dict[str, Any]] = []
    s1 = Decimal(0)
    s2: dict[str, Decimal] = {
        "location_based": Decimal(0),
        "market_based": Decimal(0),
    }
    s3: dict[str, Decimal] = {f"S3-{i}": Decimal(0) for i in range(1, 16)}
    by_category: dict[str, Decimal] = {"S1": Decimal(0), "S2": Decimal(0)}
    by_category.update({f"S3-{i}": Decimal(0) for i in range(1, 16)})
    null_rows: list[str] = []

    seen: set[str] = set()
    for line in matched.get("lines", []):
        row_id = str(line.get("row_id"))
        if row_id in seen:
            raise GateError(f"duplicate row_id {row_id!r} within one version")
        seen.add(row_id)

        tco2e, warnings = _calculate_line(line)
        if tco2e is None:
            null_rows.append(row_id)
        else:
            scope = line.get("scope")
            mode = line.get("scope2_mode") or "location_based"
            if scope == "S1":
                s1 += tco2e
                by_category["S1"] += tco2e
            elif scope == "S2":
                if mode not in s2:
                    s2[mode] = Decimal(0)
                s2[mode] += tco2e
                # Only the location-based view enters the inventory total; the
                # market-based view is a parallel presentation, never additive.
                if mode == "location_based":
                    by_category["S2"] += tco2e
            elif scope == "S3":
                key = f"S3-{line.get('s3_category')}"
                if key not in s3:
                    raise GateError(f"invalid Scope 3 category on row {row_id}")
                s3[key] += tco2e
                by_category[key] += tco2e
            else:
                warnings.append(f"unknown scope {scope!r}")

        lines.append({
            "row_id": row_id,
            "factor_id": line.get("factor_id"),
            "method": line.get("method"),
            "formula": "ad*ef*gwp/scale",
            "ad": line.get("ad"),
            "ef": line.get("ef"),
            "gwp": line.get("gwp"),
            "scale": line.get("scale"),
            "tco2e": tco2e,
            "warnings": warnings,
            "provenance": {
                "config_hash": config_hash,
                "ledger_row": row_id,
                "factor_id": line.get("factor_id"),
                "gwp_version": cfg.get("gwp_version"),
                "conversion_chain": line.get("applied_conversion", []),
            },
        })

    # A market-based result with no dedicated rows mirrors location-based and is
    # flagged by V15 in Stage 7 rather than being invented here.
    if not any(l.get("scope2_mode") == "market_based" for l in matched.get("lines", [])):
        s2["market_based"] = s2["location_based"]

    total = s1 + s2["location_based"] + sum(s3.values(), Decimal(0))
    for line in lines:
        line["share"] = (line["tco2e"] / total) if (line["tco2e"] is not None and total != 0) else None

    version = {
        "version_id": version_id,
        "method": method or cfg.get("methodology", {}).get("default") or "mixed",
        "status": status,
        "note": note,
        "lines": lines,
        "by_category": by_category,
        "by_scope": {
            "S1": s1,
            "S2": s2,
            "S3": s3,
        },
        "total": total,
    }

    versions = list((existing or {}).get("versions", []))
    if status == "final":
        for previous in versions:
            if previous.get("status") == "final":
                previous["status"] = "superseded"
    versions.append(version)
    final_version_id = (version_id if status == "final"
                        else (existing or {}).get("final_version_id"))

    warnings_all: list[dict[str, str]] = []
    for row_id in null_rows:
        warnings_all.append({"rule": "V01", "object": row_id,
                            "message": "emission is null; excluded from totals"})
    return {
        "run_id": (existing or {}).get("run_id") or f"RUN-{config_hash[:12]}",
        "config_hash": config_hash,
        "final_version_id": final_version_id,
        "versions": versions,
        "checks": {"status": "pending", "errors": [], "warnings": warnings_all},
    }


def final_version(results: dict) -> dict | None:
    target = results.get("final_version_id")
    for version in results.get("versions", []):
        if version.get("version_id") == target:
            return version
    return None
