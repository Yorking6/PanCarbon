# -*- coding: utf-8 -*-
"""Pure-abstraction audit (M0 acceptance tool).

Scans the Skill package for anything that must never be shipped: absolute
paths to an external workspace, organization names, e-mail addresses, report
years, high-precision factor-like numbers, and references to a legacy delivery
pipeline. Rules are expressed as generic patterns; organization-specific
literals are supplied at run time through --extra-pattern and are never stored
in the package.

Usage:
    python scripts/audit_purity.py [--root <skill-dir>] [--extra-pattern <regex>]...
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from ghg_common import SKILL_ROOT, setup_stdout

TEXT_SUFFIXES = {".md", ".json", ".py", ".txt", ".yaml", ".yml", ".cfg", ".toml"}
SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache"}

# Patterns are written with character classes so that this module does not
# match its own rules when it scans itself.
RULES: list[tuple[str, str, str, str]] = [
    ("R_PATH", r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"'<>]{2,}",
     "absolute filesystem path", "ERROR"),
    ("R_ORG", r"有[限]公[司]|有[限]责任公[司]|集[团]公[司]|\bCo\.,?\s?Ltd\b|\bInc\.|\bLLC\b",
     "organization name", "ERROR"),
    ("R_EMAIL", r"[\w.+-]+@[\w-]+\.[\w.-]+", "e-mail address", "ERROR"),
    ("R_YEAR", r"\b20[2-9]\d\b", "specific reporting year", "ERROR"),
    ("R_FACTOR", r"\b\d+\.\d{4,}\b", "high-precision numeric literal (factor-like)", "ERROR"),
    ("R_LEGACY", r"0[9]24|data[_]dump|template[_]dump|calc[.]json|recalc[_]vals",
     "reference to a one-off delivery pipeline", "ERROR"),
]

# Lines containing these tokens are allowed to carry a year-like number,
# because standard designations and schema dialect identifiers are not data.
YEAR_WHITELIST = ("$schema", "draft/", "ISO ", "IPCC ", "AR6", "version")

# URL-bearing lines (schema dialect identifiers) are not filesystem paths.
URL_MARKER = "://"


def iter_text_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def scan(root: Path, extra_patterns: list[str] | None = None) -> dict[str, Any]:
    compiled = [(rid, re.compile(pattern), desc, sev) for rid, pattern, desc, sev in RULES]
    for index, pattern in enumerate(extra_patterns or []):
        compiled.append((f"R_EXTRA{index + 1}", re.compile(pattern),
                         "caller-supplied organization-specific literal", "ERROR"))

    findings: list[dict[str, Any]] = []
    files = list(iter_text_files(root))
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError) as exc:
            findings.append({"file": str(path.relative_to(root)), "line": 0,
                             "rule": "R_ENCODING", "severity": "ERROR",
                             "detail": f"unreadable: {exc}"})
            continue
        for line_no, line in enumerate(lines, start=1):
            for rid, regex, desc, severity in compiled:
                if not regex.search(line):
                    continue
                if rid == "R_YEAR" and any(token in line for token in YEAR_WHITELIST):
                    continue
                if rid == "R_PATH" and URL_MARKER in line:
                    continue
                findings.append({
                    "file": str(path.relative_to(root)),
                    "line": line_no,
                    "rule": rid,
                    "severity": severity,
                    "detail": desc,
                    "excerpt": line.strip()[:160],
                })

    errors = [f for f in findings if f["severity"] == "ERROR"]
    return {
        "status": "fail" if errors else "pass",
        "root": str(root),
        "files_scanned": len(files),
        "rules": [{"id": r[0], "detail": r[2]} for r in compiled],
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    setup_stdout()
    parser = argparse.ArgumentParser(description="Pure-abstraction audit")
    parser.add_argument("--root", default=str(SKILL_ROOT), help="skill package root")
    parser.add_argument("--extra-pattern", action="append", default=[],
                        help="additional regex of organization-specific literals (repeatable)")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args(argv)

    result = scan(Path(args.root).resolve(), args.extra_pattern)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Purity audit: {result['status'].upper()} "
              f"({result['files_scanned']} files, {len(result['rules'])} rules)")
        for finding in result["findings"]:
            print(f"  [{finding['rule']}] {finding['file']}:{finding['line']} "
                  f"{finding['detail']} :: {finding.get('excerpt', '')}")
    return 0 if result["status"] == "pass" else 3


if __name__ == "__main__":
    sys.exit(main())
