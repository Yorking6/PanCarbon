# -*- coding: utf-8 -*-
"""Stage 0 - configuration validation and run directory initialization (M0).

Usage:
    python scripts/validate_config.py --config <org_config.json> [--run-dir <dir>]

Exit codes: 0 pass, 2 validation failed, 1 unexpected error.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from ghg_common import (
    canonical_hash,
    load_json,
    load_schema,
    scan_placeholders,
    setup_stdout,
    validate_schema,
    write_json,
)

S3_KEYS = set(range(1, 16))


def _resolve_ref(ref: str, config_path: Path, run_dir: Path) -> Path | None:
    """Resolve a runtime file reference without ever storing an absolute path."""
    candidate = Path(ref)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None
    for base in (config_path.parent, run_dir):
        probe = base / candidate
        if probe.exists():
            return probe
    return None


def _uses_spend_based(methodology: dict) -> bool:
    values: list[str] = []
    default = methodology.get("default")
    if isinstance(default, str):
        values.append(default)
    values.extend(str(v) for v in methodology.get("allowed_methods", []) if isinstance(v, str))
    for item in methodology.get("per_source", {}).values():
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            values.extend(str(v) for v in item.values() if isinstance(v, str))
    return any("spend_based" in v for v in values)


def semantic_checks(cfg: dict) -> list[str]:
    errors: list[str] = []
    year = cfg.get("reporting_year")
    current = date.today().year
    if not isinstance(year, int) or year < 1900 or year > current + 1:
        errors.append(f"$.reporting_year: {year!r} outside 1900..{current + 1}")

    base = cfg.get("base_year")
    if isinstance(base, int) and isinstance(year, int) and base > year:
        errors.append("$.base_year: base year must not be later than reporting year")

    entities = cfg.get("entities", [])
    ids = [e.get("id") for e in entities if isinstance(e, dict)]
    if len(ids) != len(set(ids)):
        errors.append("$.entities: duplicate entity ids")
    for entity in entities:
        if isinstance(entity, dict) and "grid_region_ref" not in entity:
            errors.append("$.entities[]: grid_region_ref key is required (null is allowed)")

    s2 = cfg.get("scope2", {})
    modes = s2.get("modes", [])
    if "location_based" not in modes:
        errors.append("$.scope2.modes: location_based is required as the total basis")
    if "market_based" in modes and not s2.get("market_instruments"):
        errors.append("$.scope2.market_instruments: required when market_based is enabled")

    s3 = cfg.get("scope3", {})
    enabled = set(i for i in s3.get("enabled_categories", []) if isinstance(i, int))
    if not enabled <= S3_KEYS:
        errors.append("$.scope3.enabled_categories: category ids must be within 1..15")
    reasons = s3.get("not_applicable_reasons", {})
    for key in sorted(S3_KEYS - enabled):
        if not str(reasons.get(str(key), reasons.get(key, ""))).strip():
            errors.append(f"$.scope3.not_applicable_reasons.{key}: reason required for disabled category")
    cutoff = s3.get("cutoff", {})
    if cutoff.get("threshold_pct", 0) > 0 and not cutoff.get("rule"):
        errors.append("$.scope3.cutoff.rule: required when threshold_pct > 0")

    methodology = cfg.get("methodology", {})
    has_method = bool(
        methodology.get("default")
        or methodology.get("per_source")
        or methodology.get("allowed_methods")
    )
    if not has_method:
        errors.append("$.methodology: at least one calculation method must be supplied")
    if _uses_spend_based(methodology) and not cfg.get("currency", {}).get("fx_table_ref"):
        errors.append("$.currency.fx_table_ref: required when a spend-based method is used")

    report = cfg.get("report", {})
    if "B" in report.get("modes", []):
        assurance = cfg.get("assurance", {})
        for field in ("level", "materiality", "verifier"):
            if assurance.get(field) in (None, ""):
                errors.append(f"$.assurance.{field}: required for report mode B")
        if not report.get("signoff_ref"):
            errors.append("$.report.signoff_ref: verification sign-off file required for report mode B")

    if not cfg.get("gases"):
        errors.append("$.gases: at least one greenhouse gas required")
    return errors


def validate(config_path: Path, run_dir: Path, write_report: bool = True) -> dict:
    report: dict[str, Any] = {
        "stage": "0",
        "milestone": "M0",
        "config_path": str(config_path),
        "run_dir": str(run_dir),
        "status": "fail",
        "config_hash": None,
        "placeholder_hits": [],
        "schema_errors": [],
        "semantic_errors": [],
        "ref_errors": [],
        "warnings": [],
    }

    try:
        cfg = load_json(config_path)
    except (OSError, json.JSONDecodeError) as exc:
        report["schema_errors"].append(f"config file unreadable: {exc}")
        if write_report:
            write_json(run_dir / "config_check.json", report)
        return report

    report["config_hash"] = canonical_hash(cfg)
    report["placeholder_hits"] = scan_placeholders(cfg)
    report["schema_errors"].extend(validate_schema(cfg, load_schema("org_config")))
    report["semantic_errors"].extend(semantic_checks(cfg))

    # Optional runtime references: validate when present, warn when absent.
    for ref_key, schema_name in (("factor_library_ref", "factor_library"),
                                 ("activity_ledger_ref", "activity_ledger")):
        ref = cfg.get(ref_key)
        if not ref:
            report["warnings"].append(f"{ref_key}: not supplied yet")
            continue
        target = _resolve_ref(str(ref), config_path, run_dir)
        if target is None:
            report["warnings"].append(f"{ref_key}: file not found at run time ({ref})")
            continue
        try:
            payload = load_json(target)
        except (OSError, json.JSONDecodeError) as exc:
            report["ref_errors"].append(f"{ref_key}: unreadable JSON ({exc})")
            continue
        errs = validate_schema(payload, load_schema(schema_name))
        report["ref_errors"].extend(f"{ref_key}{e[1:]}" for e in errs)
        if schema_name == "activity_ledger":
            expected = report["config_hash"]
            if payload.get("config_hash") != expected:
                report["warnings"].append(
                    "activity_ledger.config_hash differs from org_config; re-sign after Stage 2"
                )

    blocking = (
        report["placeholder_hits"]
        + report["schema_errors"]
        + report["semantic_errors"]
        + report["ref_errors"]
    )
    report["status"] = "fail" if blocking else "pass"

    run_dir.mkdir(parents=True, exist_ok=True)
    if not blocking:
        (run_dir / "inputs").mkdir(exist_ok=True)
        (run_dir / "outputs").mkdir(exist_ok=True)
    if write_report:
        write_json(run_dir / "config_check.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Stage 0 configuration validation")
    parser.add_argument("--config", required=True, help="path to org_config.json")
    parser.add_argument("--run-dir", default=None, help="output directory (default: alongside config)")
    args = parser.parse_args(argv)

    config_path = Path(args.config).resolve()
    run_dir = Path(args.run_dir).resolve() if args.run_dir else config_path.parent / "run"
    report = validate(config_path, run_dir)

    print(f"Stage 0: {report['status'].upper()}")
    print(f"  config_hash   : {report['config_hash']}")
    for key in ("placeholder_hits", "schema_errors", "semantic_errors", "ref_errors", "warnings"):
        items = report[key]
        print(f"  {key:<17}: {len(items)}")
        for item in items:
            print(f"      - {item}")
    print(f"  config_check  : {run_dir / 'config_check.json'}")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    sys.exit(main())
