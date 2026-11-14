# -*- coding: utf-8 -*-
"""Single entry point for the GHG inventory verification skill.

M0: deps, audit, init, validate-skill.
M1: classify, match, compute, check, pipeline.
Remaining stages fail loudly instead of producing partial artifacts.

A run directory holds the whole chain with conventional filenames:
    org_config.json, factor_library.json, activity_ledger.json,
    classification.json, matched.json, results.json, checks.json

Usage:
    python scripts/cli.py pipeline --run-dir <dir> [--config <org_config.json>]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from ghg_common import SKILL_ROOT, load_json, setup_stdout, write_json
import audit_purity
import classify
import compute
import method_factor
import recalc_check
import validate_config

MILESTONE_OF_UNIMPLEMENTED: dict[str, str] = {}

OPTIONAL_DEPS = [
    ("openpyxl", "openpyxl"),
    ("xlrd", "xlrd"),
    ("pypdf", "pypdf"),
    ("formulas", "formulas"),
    ("python-docx", "docx"),
    ("matplotlib", "matplotlib"),
    ("jsonschema", "jsonschema"),
]

RUN_FILES = {
    "config": "org_config.json",
    "factors": "factor_library.json",
    "ledger": "activity_ledger.json",
    "classification": "classification.json",
    "matched": "matched.json",
    "results": "results.json",
    "checks": "checks.json",
    "workbook": "ghg_inventory.xlsx",
    "cache": "formula_cache.json",
    "manifest": "report_manifest.json",
    "pending": "pending_ledger.json",
    "confirm": "confirm_check.json",
}


def cmd_deps(args: argparse.Namespace) -> int:
    print("M0/M1 core (standard library only): READY")
    print("Optional dependencies for M2 onward:")
    for label, module in OPTIONAL_DEPS:
        state = "READY" if importlib.util.find_spec(module) else "MISSING"
        print(f"  {label:<14} {state}")
    print("Formula recalculation chain: LibreOffice -> formulas -> ERROR")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    return audit_purity.main(["--root", str(SKILL_ROOT),
                              *(item for p in args.extra_pattern
                                for item in ("--extra-pattern", p))])


def cmd_init(args: argparse.Namespace) -> int:
    if not args.config:
        print("ERROR: init requires --config <org_config.json>")
        return 2
    forwarded = ["--config", args.config]
    if args.run_dir:
        forwarded += ["--run-dir", args.run_dir]
    return validate_config.main(forwarded)


def cmd_validate_skill(args: argparse.Namespace) -> int:
    validator = args.validator or os.environ.get("SKILL_CREATOR_VALIDATOR")
    if not validator:
        scripts = os.environ.get("SKILL_CREATOR_SCRIPTS")
        if scripts:
            validator = str(Path(scripts) / "quick_validate.py")
    if not validator or not Path(validator).is_file():
        print("ERROR: quick_validate.py not found. Pass --validator <path> or set "
              "SKILL_CREATOR_SCRIPTS / SKILL_CREATOR_VALIDATOR.")
        return 2
    result = subprocess.run([sys.executable, str(validator), str(SKILL_ROOT)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode


def _run_dir(args: argparse.Namespace) -> Path:
    return Path(args.run_dir).resolve() if args.run_dir else Path.cwd().resolve()


def _read(run: Path, key: str, override: str | None = None) -> dict:
    path = Path(override).resolve() if override else run / RUN_FILES[key]
    if not path.is_file():
        raise FileNotFoundError(f"{key} file not found: {path}")
    return load_json(path)


def _write(run: Path, key: str, payload: dict) -> None:
    write_json(run / RUN_FILES[key], payload)


def _brief(stage: str, status: str, detail: str) -> None:
    print(f"Stage {stage}: {status.upper()} | {detail}")


def cmd_extract(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    input_dir = (Path(args.input_dir).resolve() if args.input_dir
                 else run / "vouchers")
    if not input_dir.is_dir():
        print(f"ERROR: voucher directory not found: {input_dir}")
        return 2
    try:
        import extract
        hint_path = Path(args.hint) if args.hint else None
        pending = extract.extract_from_run(run, input_dir, hint_path)
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        print(f"ERROR: voucher extraction failed: {exc}")
        return 2
    manual = sum(1 for row in pending["rows"] if row["needs_manual"])
    _brief("1", "pass",
           f"rows={len(pending['rows'])} needs_manual={manual} "
           f"warnings={len(pending['warnings'])} extractors={pending['extractor_stats']}")
    for warning in pending["warnings"][:5]:
        print(f"    - {warning}")
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        import confirm_gate
        signoff_path = Path(args.batch_signoff) if args.batch_signoff else None
        _, report = confirm_gate.confirm_from_run(run, signoff_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        print(f"ERROR: confirmation gate failed: {exc}")
        return 2
    _brief("2", report["status"],
           f"rows={report['rows']} unsigned={len(report['unsigned'])} "
           f"errors={len(report['errors'])} warnings={len(report['warnings'])}")
    for error in report["errors"][:8]:
        print(f"    - {error}")
    return 0 if report["status"] == "pass" else 2


def cmd_classify(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        cfg = _read(run, "config", args.config)
        ledger = _read(run, "ledger", args.ledger)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    out = classify.classify(cfg, ledger)
    _write(run, "classification", out)
    _brief("3", out["status"],
           f"rows={len(out['rows'])} unmapped={len(out['unmapped'])} "
           f"errors={len(out['errors'])} warnings={len(out['warnings'])}")
    for err in out["errors"]:
        print(f"    - {err}")
    return 0 if out["status"] == "pass" else 2


def cmd_match(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        cfg = _read(run, "config", args.config)
        ledger = _read(run, "ledger", args.ledger)
        classification = _read(run, "classification", args.classification)
        library = _read(run, "factors", args.factors)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    out = method_factor.match(cfg, ledger, classification, library)
    _write(run, "matched", out)
    matched = sum(1 for l in out["lines"] if l["status"] == "matched")
    _brief("4", out["status"],
           f"matched={matched}/{len(out['lines'])} candidates={len(out['candidates'])} "
           f"errors={len(out['errors'])}")
    for err in out["errors"]:
        print(f"    - {err}")
    return 0 if not out["errors"] else 2


def cmd_compute(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        cfg = _read(run, "config", args.config)
        ledger = _read(run, "ledger", args.ledger)
        matched = _read(run, "matched", args.matched)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    existing = None
    results_path = run / RUN_FILES["results"]
    if args.append and results_path.is_file():
        existing = load_json(results_path)
    try:
        out = compute.compute(cfg, ledger, matched,
                              version_id=args.version_id,
                              method=args.method,
                              status=args.status,
                              existing=existing,
                              note=args.note)
    except compute.GateError as exc:
        print(f"ERROR: {exc}")
        return 2
    _write(run, "results", out)
    version = compute.final_version(out) or out["versions"][-1]
    _brief("5", "pass",
           f"version={version['version_id']} final={out['final_version_id']} "
           f"total={float(version['total'])} null_lines="
           f"{sum(1 for l in version['lines'] if l['tco2e'] is None)}")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        import build_inventory
        payload = build_inventory.build_from_run(run)
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        print(f"ERROR: workbook build failed: {exc}")
        return 2
    _brief("6", "pass",
           f"sheets={len(payload['sheets'])} "
           f"formula_cells={payload['formula_cell_count']} "
           f"gaps={payload['quality_gaps']} -> {payload['workbook']}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        import build_report
        manifest = build_report.build_from_run(run)
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        print(f"ERROR: report generation failed: {exc}")
        return 2
    drafts = sum(1 for item in manifest["documents"] if item["draft"])
    _brief("8", "pass",
           f"documents={len(manifest['documents'])} drafts={drafts} "
           f"signoff_valid={manifest['signoff_valid']}")
    for issue in manifest["signoff_issues"]:
        print(f"    - sign-off: {issue}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        cfg = _read(run, "config", args.config)
        ledger = _read(run, "ledger", args.ledger)
        matched = _read(run, "matched", args.matched)
        library = _read(run, "factors", args.factors)
        results = _read(run, "results", args.results)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    workbook = None
    workbook_path = run / RUN_FILES["workbook"]
    cache_path = run / RUN_FILES["cache"]
    if not args.skip_workbook and workbook_path.is_file() and cache_path.is_file():
        workbook = {"path": workbook_path, "cache": load_json(cache_path)}
    manifest = None
    phrases = None
    manifest_path = run / RUN_FILES["manifest"]
    if not args.skip_reports and manifest_path.is_file():
        manifest = load_json(manifest_path)
        phrases = load_json(SKILL_ROOT / "assets" / "phrases.json")
    report = recalc_check.run_checks(cfg, ledger, matched, library, results,
                                     workbook, manifest, phrases=phrases, run=run)
    _write(run, "checks", report)
    _write(run, "results", recalc_check.embed(results, report))
    v09 = report.get("v09") or {}
    _brief("7", report["status"],
           f"errors={len(report['errors'])} warnings={len(report['warnings'])} "
           f"dual_track={report['dual_track']['status']} "
           f"deferred={len(report['rules_deferred'])} "
           f"workbook_engine={v09.get('engine', 'n/a')} "
           f"recalc_cells={v09.get('cells_checked', 0)} "
           f"reports={report.get('reports_checked', 0)}")
    for err in report["errors"]:
        print(f"    - [{err['rule']}] {err['object']}: {err['message']}")
    return 0 if report["status"] == "pass" else 2


def cmd_deliver(args: argparse.Namespace) -> int:
    run = _run_dir(args)
    try:
        import package_delivery
        out = Path(args.out) if args.out else None
        delivery = package_delivery.deliver(run, out)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - surfaced, never hidden
        print(f"ERROR: delivery packaging failed: {exc}")
        return 2
    if delivery.get("status") != "pass":
        _brief("9", delivery["status"],
               f"{delivery.get('reason', 'delivery blocked')} "
               f"missing={delivery.get('missing', [])}")
        return 2
    _brief("9", "pass",
           f"items={len(delivery['items'])} evidence={delivery['evidence_count']} "
           f"deferred={len(delivery['rules_deferred'])} -> {delivery['bundle']}")
    return 0


def cmd_pipeline(args: argparse.Namespace) -> int:
    # Stage 8 precedes Stage 7 so the final check can also validate reports;
    # Stage 9 runs last and only packages a clean reconciliation result.
    for name, handler in (("classify", cmd_classify), ("match", cmd_match),
                          ("compute", cmd_compute), ("inventory", cmd_inventory),
                          ("report", cmd_report), ("check", cmd_check),
                          ("deliver", cmd_deliver)):
        code = handler(args)
        if code != 0:
            print(f"PIPELINE STOPPED at {name} (exit {code})")
            return code
    print("PIPELINE COMPLETE: Stage 3 -> 4 -> 5 -> 6 -> 8 -> 7 -> 9")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="GHG inventory verification skill CLI")
    parser.add_argument("command", help="stage command")
    parser.add_argument("--config", help="path to org_config.json")
    parser.add_argument("--run-dir", help="run output directory")
    parser.add_argument("--ledger", help="override activity_ledger.json path")
    parser.add_argument("--factors", help="override factor_library.json path")
    parser.add_argument("--classification", help="override classification.json path")
    parser.add_argument("--matched", help="override matched.json path")
    parser.add_argument("--results", help="override results.json path")
    parser.add_argument("--skip-workbook", action="store_true",
                        help="run Stage 7 without workbook V06/V09 checks")
    parser.add_argument("--skip-reports", action="store_true",
                        help="run Stage 7 without report V07/V12/V13 checks")
    parser.add_argument("--input-dir", help="Stage 1 voucher directory")
    parser.add_argument("--hint", help="Stage 1 extraction hint JSON")
    parser.add_argument("--batch-signoff", help="Stage 2 batch sign-off JSON")
    parser.add_argument("--out", help="Stage 9 delivery bundle output path")
    parser.add_argument("--extra-pattern", action="append", default=[],
                        help="purity audit extra regex (repeatable)")
    parser.add_argument("--validator", help="path to quick_validate.py")
    parser.add_argument("--version-id", default="V1", help="results version id")
    parser.add_argument("--method", help="method label for this version")
    parser.add_argument("--status", default="final",
                        choices=["draft", "final", "superseded"])
    parser.add_argument("--append", action="store_true",
                        help="append a version to an existing results.json")
    parser.add_argument("--note", help="free-text note stored on the version")
    args = parser.parse_args(argv)

    commands = {
        "deps": cmd_deps,
        "audit": cmd_audit,
        "init": cmd_init,
        "validate-skill": cmd_validate_skill,
        "extract": cmd_extract,
        "confirm": cmd_confirm,
        "classify": cmd_classify,
        "match": cmd_match,
        "compute": cmd_compute,
        "inventory": cmd_inventory,
        "report": cmd_report,
        "check": cmd_check,
        "deliver": cmd_deliver,
        "pipeline": cmd_pipeline,
    }
    if args.command in commands:
        return commands[args.command](args)
    milestone = MILESTONE_OF_UNIMPLEMENTED.get(args.command)
    if milestone:
        print(f"NOT_IMPLEMENTED: command '{args.command}' is scheduled for {milestone}. "
              f"No artifacts were created.")
        return 4
    print(f"ERROR: unknown command '{args.command}'. "
          f"Available: {', '.join(sorted(commands))}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
