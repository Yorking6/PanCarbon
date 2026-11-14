# -*- coding: utf-8 -*-
"""Minimal deterministic spreadsheet formula evaluator (M2 fallback).

Supports exactly the formula shapes produced by build_inventory.py: cell
references (including cross-sheet and absolute references), SUM over a single
rectangular range, and arithmetic. It is the last recalculation fallback when
neither LibreOffice nor the formulas package is available; it is never used to
invent values, only to re-evaluate what is written in the workbook.
"""
from __future__ import annotations

import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string, get_column_letter

SUM_RANGE = re.compile(
    r"SUM\(\s*(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_]*))!)?"
    r"\$?([A-Z]{1,3})\$?(\d+)\s*:\s*\$?([A-Z]{1,3})\$?(\d+)\s*\)",
    re.IGNORECASE,
)
CELL_REF = re.compile(
    r"(?<![\w])(?:(?:'([^']+)'|([A-Za-z_][A-Za-z0-9_]*))!)?"
    r"\$?([A-Z]{1,3})\$?(\d+)(?![\w])"
)
SAFE_EXPRESSION = re.compile(r"^[0-9eE+\-*/().,\s_A-Za-z']+$")


class FormulaEvalError(ValueError):
    """Raised when a formula cannot be evaluated deterministically."""


class WorkbookEvaluator:
    def __init__(self, path: str | Path):
        self.wb = load_workbook(str(path), data_only=False)
        self.memo: dict[tuple[str, str], float] = {}
        self.visiting: set[tuple[str, str]] = set()
        self.current_sheet = self.wb.sheetnames[0]

    def close(self) -> None:
        self.wb.close()

    def value(self, sheet: str, col: str, row: int) -> float:
        name = self.wb.sheetnames[[s.upper() for s in self.wb.sheetnames].index(sheet.upper())]
        coord = f"{col.upper()}{row}"
        key = (name, coord)
        if key in self.memo:
            return self.memo[key]
        if key in self.visiting:
            raise FormulaEvalError(f"circular reference at {name}!{coord}")
        self.visiting.add(key)
        try:
            raw = self.wb[name][coord].value
            resolved = self._resolve(name, raw)
        finally:
            self.visiting.discard(key)
        self.memo[key] = resolved
        return resolved

    def _resolve(self, sheet: str, raw) -> float:
        if raw is None:
            return 0.0
        if isinstance(raw, bool):
            raise FormulaEvalError("boolean in a numeric formula")
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str) and raw.startswith("="):
            previous = self.current_sheet
            self.current_sheet = sheet
            try:
                return self.evaluate(sheet, raw)
            finally:
                self.current_sheet = previous
        raise FormulaEvalError(f"non-numeric cell value {raw!r}")

    def _compile(self, sheet: str, formula: str) -> str:
        expr = formula[1:] if formula.startswith("=") else formula
        slots: dict[str, str] = {}

        def slot(code: str) -> str:
            token = f"__SLOT{len(slots)}X__"
            slots[token] = code
            return token

        def sum_sub(match) -> str:
            target = match.group(1) or match.group(2) or sheet
            return slot(f"_srange({target!r},{match.group(3)!r},{int(match.group(4))},"
                        f"{match.group(5)!r},{int(match.group(6))})")

        def ref_sub(match) -> str:
            target = match.group(1) or match.group(2) or sheet
            return slot(f"_ref({target!r},{match.group(3)!r},{int(match.group(4))})")

        expr = SUM_RANGE.sub(sum_sub, expr)
        expr = CELL_REF.sub(ref_sub, expr)
        for token, code in slots.items():
            expr = expr.replace(token, code)
        if not SAFE_EXPRESSION.match(expr):
            raise FormulaEvalError(f"unsupported formula characters in {formula!r}")
        if any(word in expr for word in ("import", "open", "exec", "eval", "__")):
            raise FormulaEvalError(f"unsafe formula expression in {formula!r}")
        return expr

    def _ref(self, sheet: str, col: str, row: int) -> float:
        return self.value(sheet, col, row)

    def _srange(self, sheet: str, c1: str, r1: int, c2: str, r2: int) -> float:
        first, last = column_index_from_string(c1), column_index_from_string(c2)
        total = 0.0
        for index in range(first, last + 1):
            column = get_column_letter(index)
            for row in range(r1, r2 + 1):
                total += self.value(sheet, column, row)
        return total

    def evaluate(self, sheet: str, formula: str) -> float:
        expr = self._compile(sheet, formula)
        scope = {
            "_ref": self._ref,
            "_srange": self._srange,
            "__builtins__": {},
        }
        try:
            result = eval(expr, scope, {})  # noqa: S307 - expression is whitelisted above
        except FormulaEvalError:
            raise
        except Exception as exc:  # noqa: BLE001 - converted into a reported failure
            raise FormulaEvalError(f"evaluation failed for {formula!r}: {exc}") from exc
        if not isinstance(result, (int, float)) or isinstance(result, bool):
            raise FormulaEvalError(f"non-numeric result for {formula!r}")
        return float(result)

    def evaluate_all(self) -> dict[str, float]:
        """Return a value for every formula cell, keyed as SHEET!CELL."""
        results: dict[str, float] = {}
        for name in self.wb.sheetnames:
            ws = self.wb[name]
            for row in ws.iter_rows():
                for cell in row:
                    if isinstance(cell.value, str) and cell.value.startswith("="):
                        results[f"{name}!{cell.coordinate}"] = self.evaluate(name, cell.value)
        return results
