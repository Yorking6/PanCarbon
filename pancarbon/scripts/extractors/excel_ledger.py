# -*- coding: utf-8 -*-
"""Spreadsheet ledger extractor (M4).

Handles two shapes seen in real vouchers: monthly columns with a total column,
and row-per-invoice ledgers. Units hidden in row labels, broken SUM formulas,
amount-only rows and Wingdings check marks are all flagged for human review.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import BaseExtractor, ExtractorResult, RawRecord
from normalize_units import canonical_unit


def _read_grids(path: Path) -> list[tuple[str, list[list[Any]]]]:
    grids: list[tuple[str, list[list[Any]]]] = []
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path))
        for sheet in book.sheets():
            grid = [[sheet.cell_value(r, c) for c in range(sheet.ncols)]
                    for r in range(sheet.nrows)]
            grids.append((sheet.name, grid))
        return grids
    from openpyxl import load_workbook
    book = load_workbook(str(path), data_only=True, read_only=True)
    try:
        for sheet in book.worksheets:
            grid = [list(row) for row in sheet.iter_rows(values_only=True)]
            grids.append((sheet.title, grid))
    finally:
        book.close()
    return grids


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


def _unit_from_label(label: str, rules: dict) -> str:
    for pattern in rules.get("unit_in_label_patterns", []) or []:
        match = re.search(pattern, str(label))
        if match and match.lastindex and match.lastindex >= 2:
            return canonical_unit(match.group(2))
    for hint in rules.get("unit_hints", []) or []:
        if str(hint) in str(label):
            return canonical_unit(str(hint))
    return ""


def _find_header(grid: list[list[Any]], rules: dict) -> tuple[int, str] | None:
    months = set(rules.get("month_columns", []) or [])
    for index, row in enumerate(grid[:12]):
        cells = [str(cell).strip() if cell is not None else "" for cell in row]
        month_hits = sum(1 for cell in cells if cell in months)
        if month_hits >= 3:
            return index, "monthly"
        joined = " ".join(cells)
        if ("数量" in joined or "Quantity" in joined) and \
           ("单位" in joined or "Unit" in joined):
            return index, "detail"
    return None


class ExcelLedgerExtractor(BaseExtractor):
    name = "excel_ledger"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in (".xlsx", ".xlsm", ".xls")

    def extract(self, path: Path, hint: dict[str, Any] | None = None) -> ExtractorResult:
        hint = hint or {}
        rules = hint.get("rules") or {}
        reasons = rules.get("manual_reasons") or {}
        checkboxes = set(rules.get("checkbox_symbols") or [])
        records: list[RawRecord] = []
        warnings: list[str] = []

        for sheet_name, grid in _read_grids(path):
            found = _find_header(grid, rules)
            if found is None:
                warnings.append(f"{sheet_name}: no recognizable header; sheet skipped")
                continue
            header_row, kind = found
            headers = [str(cell).strip() if cell is not None else ""
                       for cell in grid[header_row]]

            total_idx = next((i for i, cell in enumerate(headers)
                              if cell in ("合计", "Total")), None)
            qty_idx = next((i for i, cell in enumerate(headers)
                            if cell in ("数量", "Quantity", "Qty")), None)
            unit_idx = next((i for i, cell in enumerate(headers)
                             if cell in ("单位", "Unit")), None)
            amount_idx = next((i for i, cell in enumerate(headers)
                               if cell in ("金额", "Amount", "价税合计")), None)

            for row_no in range(header_row + 1, len(grid)):
                row = grid[row_no]
                if not row or all(cell in (None, "") for cell in row):
                    continue
                label = " ".join(str(cell) for cell in row[:2] if cell is not None)
                checked = any(str(cell).strip() in checkboxes
                              for cell in row if cell is not None)
                if checked:
                    warnings.append(f"{sheet_name}!{row_no + 1}: check mark noted, not a quantity")

                if kind == "monthly":
                    value = _number(row[total_idx]) if total_idx is not None \
                        and total_idx < len(row) else None
                    monthly = [_number(cell) for cell in row]
                    unit = _unit_from_label(label, rules)
                    needs_manual = value is None or not unit
                    if value is None:
                        warnings.append(f"{sheet_name}!{row_no + 1}: " +
                                        str(reasons.get("broken_formula", "missing total")))
                    if not unit:
                        warnings.append(f"{sheet_name}!{row_no + 1}: " +
                                        str(reasons.get("missing_unit", "missing unit")))
                    metadata = {"sheet": sheet_name, "row": row_no + 1,
                                "shape": "monthly", "monthly_values": monthly,
                                "label": label}
                else:
                    value = _number(row[qty_idx]) if qty_idx is not None \
                        and qty_idx < len(row) else None
                    unit = canonical_unit(
                        str(row[unit_idx]) if unit_idx is not None
                        and unit_idx < len(row) and row[unit_idx] is not None else "")
                    if not unit:
                        unit = _unit_from_label(label, rules)
                    amount = _number(row[amount_idx]) if amount_idx is not None \
                        and amount_idx < len(row) else None
                    needs_manual = value is None or not unit
                    if value is None and amount is not None:
                        warnings.append(f"{sheet_name}!{row_no + 1}: " +
                                        str(reasons.get("amount_only", "amount only")))
                    if not unit:
                        warnings.append(f"{sheet_name}!{row_no + 1}: " +
                                        str(reasons.get("missing_unit", "missing unit")))
                    metadata = {"sheet": sheet_name, "row": row_no + 1,
                                "shape": "detail", "label": label,
                                "monetary_amount": amount}

                records.append(RawRecord(
                    source_file=path.name, extractor=self.name,
                    observed_value=value, observed_unit=unit,
                    source_locator=f"{sheet_name}!R{row_no + 1}",
                    voucher_period="", confidence="medium" if not needs_manual else "low",
                    needs_manual=needs_manual, metadata=metadata))
        return ExtractorResult(records, warnings)
