# -*- coding: utf-8 -*-
"""Shared helpers for the GHG inventory verification skill (M0).

Standard library only. No organization data, no emission factor values, no
absolute paths to any external workspace are stored in this module.
"""
from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = SKILL_ROOT / "assets"
SCHEMA_DIR = ASSET_DIR / "schemas"
REFERENCE_DIR = SKILL_ROOT / "references"

PLACEHOLDER_TOKENS = ("__REQUIRED__", "TODO", "PLACEHOLDER")


def setup_stdout() -> None:
    """Make UTF-8 output safe on Windows consoles."""
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        pass


def load_json(path: str | Path) -> Any:
    with open(str(path), "r", encoding="utf-8") as fh:
        return json.load(fh)


def jsonable(obj: Any) -> Any:
    """Convert exact numeric types into JSON-native values before serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Fraction):
        return str(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {key: jsonable(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(value) for value in obj]
    return obj


def write_json(path: str | Path, obj: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(str(target), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(jsonable(obj), fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def canonical_hash(obj: Any) -> str:
    """Stable SHA-256 of a JSON-serializable object."""
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scan_placeholders(obj: Any, path: str = "$") -> list[str]:
    """Return every placeholder occurrence with its JSON path."""
    hits: list[str] = []
    if isinstance(obj, str):
        for token in PLACEHOLDER_TOKENS:
            if token in obj:
                hits.append(f"{path}: unresolved placeholder {token}")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            hits.extend(scan_placeholders(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            hits.extend(scan_placeholders(value, f"{path}[{index}]"))
    return hits


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    # Unknown type keyword is treated as permissive, never as a silent pass on data.
    return True


def validate_schema(obj: Any, schema: dict, path: str = "$") -> list[str]:
    """Minimal JSON Schema subset validator.

    Supported keywords: type (string or list), required, properties, items,
    enum, minItems, minLength, minimum, maximum. All other keywords (including
    $schema, title, description) are descriptive and ignored.
    """
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type is not None:
        types = [expected_type] if isinstance(expected_type, str) else list(expected_type)
        if not any(_type_ok(obj, t) for t in types):
            errors.append(f"{path}: expected type {'|'.join(types)}, got {type(obj).__name__}")
            return errors

    if "enum" in schema and obj not in schema["enum"]:
        errors.append(f"{path}: value {obj!r} not in enum {schema['enum']!r}")

    if isinstance(obj, dict):
        for key in schema.get("required", []):
            if key not in obj:
                errors.append(f"{path}.{key}: missing required field")
        for key, subschema in schema.get("properties", {}).items():
            if key in obj and isinstance(subschema, dict):
                errors.extend(validate_schema(obj[key], subschema, f"{path}.{key}"))

    if isinstance(obj, list):
        if "minItems" in schema and len(obj) < schema["minItems"]:
            errors.append(f"{path}: expected at least {schema['minItems']} items, got {len(obj)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(obj):
                errors.extend(validate_schema(item, item_schema, f"{path}[{index}]"))

    if isinstance(obj, str) and "minLength" in schema and len(obj) < schema["minLength"]:
        errors.append(f"{path}: string shorter than {schema['minLength']}")

    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            errors.append(f"{path}: {obj} below minimum {schema['minimum']}")
        if "maximum" in schema and obj > schema["maximum"]:
            errors.append(f"{path}: {obj} above maximum {schema['maximum']}")

    return errors


def load_schema(name: str) -> dict:
    return load_json(SCHEMA_DIR / f"{name}.schema.json")
