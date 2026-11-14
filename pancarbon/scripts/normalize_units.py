# -*- coding: utf-8 -*-
"""Unit normalization and the dimensional contract (M1).

The Skill never stores prices, exchange rates, calorific values or any other
organization-specific conversion constant. Those arrive at run time inside
``activity_ledger.rows[].conversion_chain`` and are applied here with a full
trace. Only generic unit aliases and physical scale ratios live in this module.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any

UNIT_ALIASES: dict[str, str] = {
    "kg": "kg", "kilogram": "kg", "kilograms": "kg", "千克": "kg", "公斤": "kg",
    "g": "g", "克": "g",
    "t": "t", "tonne": "t", "tonnes": "t", "吨": "t",
    "L": "L", "l": "L", "litre": "L", "liter": "L", "升": "L",
    "m3": "m3", "立方米": "m3",
    "kWh": "kWh", "度": "kWh", "MWh": "MWh",
    "km": "km", "公里": "km",
    "tkm": "tkm", "tonne.km": "tkm", "吨公里": "tkm",
    "pkm": "pkm", "人公里": "pkm",
    "CNY": "CNY", "元": "CNY", "万元": "CNY", "USD": "USD", "美元": "USD",
    "bottle": "bottle", "瓶": "bottle",
    "roomnight": "roomnight", "间夜": "roomnight",
    "unit": "unit", "件": "unit",
}

# Conversion ratio from a unit to the base unit of its dimension.
TO_BASE: dict[str, Fraction] = {
    "g": Fraction(1, 1000), "kg": Fraction(1, 1), "t": Fraction(1000, 1),
    "kWh": Fraction(1, 1000), "MWh": Fraction(1, 1),
    "km": Fraction(1, 1), "tkm": Fraction(1, 1), "pkm": Fraction(1, 1),
    "L": Fraction(1, 1), "m3": Fraction(1, 1),
    "CNY": Fraction(1, 1), "USD": Fraction(1, 1),
    "bottle": Fraction(1, 1), "roomnight": Fraction(1, 1), "unit": Fraction(1, 1),
}

DIMENSION_OF: dict[str, str] = {
    "g": "mass", "kg": "mass", "t": "mass",
    "kWh": "energy", "MWh": "energy",
    "km": "distance", "tkm": "freight", "pkm": "passenger",
    "L": "volume", "m3": "volume",
    "CNY": "currency", "USD": "currency",
    "bottle": "count", "roomnight": "count", "unit": "count",
}

# Every operation except identity, divide and none multiplies by ``factor``.
OP_MODE: dict[str, str] = {
    "identity": "none",
    "multiply": "mul",
    "divide": "div",
    "fee_to_volume": "mul",
    "fee_to_distance": "mul",
    "container_to_mass": "mul",
    "currency_conversion": "mul",
    "ratio_split": "mul",
    "mass_times_distance": "mul",
    "sample_amplification": "mul",
    "wtt": "mul",
    "custom": "mul",
}

# Numerator of a factor unit expressed as tonnes of CO2e.
CO2E_NUMERATOR_TO_T: dict[str, Fraction] = {
    "kgCO2e": Fraction(1, 1000),
    "tCO2e": Fraction(1, 1),
    "gCO2e": Fraction(1, 1000000),
}


class UnitError(ValueError):
    """Raised when a unit contract cannot be resolved."""


def canonical_unit(unit: str) -> str:
    key = str(unit).strip()
    return UNIT_ALIASES.get(key, key)


def as_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise UnitError("boolean is not a numeric activity value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnitError(f"value {value!r} is not numeric") from exc


def apply_conversion_chain(raw_value: Any, raw_unit: str,
                           chain: list[dict] | None) -> dict[str, Any]:
    """Apply a conversion chain and return value, unit, trace and errors.

    No exception is raised on a bad chain: errors are returned so that the
    calling stage can mark the row unusable instead of silently guessing.
    """
    value = as_decimal(raw_value)
    unit = canonical_unit(raw_unit)
    applied: list[dict[str, Any]] = []
    errors: list[str] = []

    for index, step in enumerate(chain or []):
        if not isinstance(step, dict):
            errors.append(f"conversion_chain[{index}]: not an object")
            continue
        op = str(step.get("op", "custom"))
        mode = OP_MODE.get(op)
        if mode is None:
            errors.append(f"conversion_chain[{index}]: unknown op {op!r}")
            continue
        if not str(step.get("note", "")).strip():
            errors.append(f"conversion_chain[{index}]: note is mandatory for traceability")

        expected_from = step.get("from_unit")
        if expected_from and canonical_unit(str(expected_from)) != unit:
            errors.append(
                f"conversion_chain[{index}]: from_unit {expected_from!r} "
                f"does not match current unit {unit!r}"
            )

        if mode == "none":
            next_value = value
        else:
            factor = step.get("factor")
            if factor is None:
                errors.append(f"conversion_chain[{index}]: factor is mandatory for op {op!r}")
                continue
            try:
                ratio = as_decimal(factor)
            except UnitError as exc:
                errors.append(f"conversion_chain[{index}]: {exc}")
                continue
            if mode == "div":
                if ratio == 0:
                    errors.append(f"conversion_chain[{index}]: division by zero")
                    continue
                next_value = value / ratio
            else:
                next_value = value * ratio

        target = step.get("to_unit")
        next_unit = canonical_unit(str(target)) if target else unit
        value, unit = next_value, next_unit
        applied.append({
            "index": index,
            "op": op,
            "from_unit": expected_from or unit,
            "to_unit": unit,
            "factor": step.get("factor"),
            "reference": step.get("reference"),
            "note": step.get("note"),
            "result": str(value),
        })

    return {"value": value, "unit": unit, "applied": applied, "errors": errors}


def parse_factor_unit(ef_unit: str) -> tuple[str, str]:
    """Split a factor unit such as kgCO2e/tkm into numerator and denominator."""
    text = str(ef_unit).strip()
    if "/" not in text:
        raise UnitError(f"factor unit {ef_unit!r} must be expressed as <mass CO2e>/<activity unit>")
    numerator, denominator = text.split("/", 1)
    numerator, denominator = numerator.strip(), canonical_unit(denominator.strip())
    if numerator not in CO2E_NUMERATOR_TO_T:
        raise UnitError(f"unsupported factor numerator {numerator!r}")
    return numerator, denominator


def conversion_ratio(ad_unit: str, denominator: str) -> Fraction:
    """Ratio that turns one ad_unit into one denominator unit."""
    ad_unit = canonical_unit(ad_unit)
    if ad_unit == denominator:
        return Fraction(1, 1)
    if DIMENSION_OF.get(ad_unit) != DIMENSION_OF.get(denominator):
        raise UnitError(
            f"dimension mismatch: activity {ad_unit!r} vs factor denominator {denominator!r}"
        )
    if ad_unit not in TO_BASE or denominator not in TO_BASE:
        raise UnitError(f"unknown unit pair {ad_unit!r}/{denominator!r}")
    return TO_BASE[ad_unit] / TO_BASE[denominator]


def derive_scale(ad_unit: str, ef_unit: str) -> Fraction:
    """Derive the only dimensionally valid divisor for tco2e = ad*ef*gwp/scale.

    scale = 1 / (conv(ad -> factor denominator) * numerator_to_tonnes)
    """
    numerator, denominator = parse_factor_unit(ef_unit)
    conv = conversion_ratio(ad_unit, denominator)
    per_tonne = CO2E_NUMERATOR_TO_T[numerator]
    if conv * per_tonne == 0:
        raise UnitError("derived scale is zero")
    return Fraction(1, 1) / (conv * per_tonne)


def dimension_compatible(ad_unit: str, ef_unit: str) -> dict[str, Any]:
    """Return compatibility, derived scale and a human-readable reason."""
    try:
        scale = derive_scale(ad_unit, ef_unit)
    except UnitError as exc:
        return {"compatible": False, "scale": None, "reason": str(exc)}
    return {"compatible": True, "scale": scale, "reason": "units reconcile"}


def scale_matches(ad_unit: str, ef_unit: str, declared_scale: Any) -> dict[str, Any]:
    """Verify that a factor's explicit scale matches the unit contract."""
    contract = dimension_compatible(ad_unit, ef_unit)
    if not contract["compatible"]:
        return {"match": False, **contract}
    try:
        declared = Fraction(str(declared_scale))
    except (ValueError, ZeroDivisionError):
        return {"match": False, "scale": str(contract["scale"]),
                "reason": "declared scale is not a rational number"}
    expected = contract["scale"]
    return {
        "match": declared == expected,
        "scale": str(expected),
        "declared_scale": str(declared),
        "reason": "scale matches" if declared == expected else
                  f"declared scale {declared} differs from derived {expected}",
    }
