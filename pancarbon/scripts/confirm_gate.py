# -*- coding: utf-8 -*-
"""Stage 2 - human confirmation gate (M4).

No calculation is possible until every row carries a non-empty human sign-off.
Missing values, unresolved units, empty periods and unjustified estimates or
carry-overs are hard rejections, reported as an unsigned/incomplete list.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ghg_common import canonical_hash, jsonable, load_json, load_schema, validate_schema, write_json


def confirm(pending: dict, cfg: dict,
            signoff: dict | None = None) -> tuple[dict | None, dict]:
    errors: list[str] = []
    warnings: list[str] = []
    unsigned: list[str] = []
    excluded: list[str] = []
    rows: list[dict] = []
    expected_hash = canonical_hash(cfg)

    if pending.get("config_hash") != expected_hash:
        errors.append("pending_ledger.config_hash does not match org_config")

    for row in pending.get("rows", []):
        row_id = str(row.get("row_id"))
        if row.get("exclude"):
            excluded.append(row_id)
            warnings.append(f"{row_id}: excluded by human review; not an activity row")
            continue
        confirmation = dict(row.get("confirmation") or {})
        if not str(confirmation.get("signed_by") or "").strip() or \
           not str(confirmation.get("signed_at") or "").strip():
            if signoff and str(signoff.get("signed_by") or "").strip() and \
               str(signoff.get("signed_at") or "").strip():
                confirmation["signed_by"] = signoff["signed_by"]
                confirmation["signed_at"] = signoff["signed_at"]
                confirmation["method"] = "batch_signoff"
            else:
                unsigned.append(row_id)
                errors.append(f"{row_id}: missing human sign-off")

        normalized = row.get("normalized") or {}
        if normalized.get("value") is None:
            errors.append(f"{row_id}: normalized value is missing")
        if not str(normalized.get("unit") or "").strip():
            errors.append(f"{row_id}: normalized unit is missing")

        period = row.get("period") or {}
        if not str(period.get("start") or "").strip() or \
           not str(period.get("end") or "").strip():
            errors.append(f"{row_id}: consumption period is incomplete")
        if period.get("basis") == "estimated":
            warnings.append(f"{row_id}: estimated period; verify before delivery")

        if row.get("estimated") and not str(row.get("estimation_note") or "").strip():
            errors.append(f"{row_id}: estimated value lacks estimation_note")
        if row.get("carry_over_from") and not str(row.get("estimation_note") or "").strip():
            errors.append(f"{row_id}: carry-over lacks estimation_note")
        if row.get("needs_manual"):
            warnings.append(f"{row_id}: voucher required manual review; sign-off accepted")

        clean = {key: value for key, value in row.items()
                 if key not in ("needs_manual", "metadata", "exclude")}
        clean["confirmation"] = confirmation
        rows.append(clean)

    report = {
        "stage": 2,
        "status": "fail" if errors else "pass",
        "rows": len(rows),
        "unsigned": unsigned,
        "excluded": excluded,
        "errors": errors,
        "warnings": warnings,
        "batch_signoff": bool(signoff),
        "config_hash": expected_hash,
    }
    if errors:
        return None, report

    ledger = {
        "schema_version": "1.0",
        "config_hash": expected_hash,
        "rows": rows,
    }
    schema_errors = validate_schema(ledger, load_schema("activity_ledger"))
    if schema_errors:
        report["status"] = "fail"
        report["errors"] = list(errors) + schema_errors
        return None, report
    return ledger, report


def confirm_from_run(run: Path, signoff_path: Path | None = None) -> tuple[dict | None, dict]:
    cfg = load_json(run / "org_config.json")
    pending = load_json(run / "pending_ledger.json")
    signoff = load_json(signoff_path) if signoff_path and signoff_path.is_file() else None
    ledger, report = confirm(pending, cfg, signoff)
    write_json(run / "confirm_check.json", jsonable(report))
    if ledger is not None:
        write_json(run / "activity_ledger.json", jsonable(ledger))
    return ledger, report
