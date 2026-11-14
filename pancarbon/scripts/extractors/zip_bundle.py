# -*- coding: utf-8 -*-
"""ZIP bundle extractor (M4).

Chinese member names written without the UTF-8 flag are decoded as cp437 by
zipfile; this module restores them via gbk and dispatches every member through
the regular extractor chain. Nothing is written outside a temporary directory.
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .base import BaseExtractor, ExtractorResult


def restore_zip_name(info: zipfile.ZipInfo) -> str:
    """Return a readable member name, restoring gbk bytes when needed."""
    name = info.filename
    if not (info.flag_bits & 0x800):
        try:
            return name.encode("cp437").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name
    return name


class ZipBundleExtractor(BaseExtractor):
    name = "zip_bundle"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".zip"

    def extract(self, path: Path, hint: dict[str, Any] | None = None) -> ExtractorResult:
        from extract import collect_records  # delayed to avoid an import cycle

        hint = hint or {}
        warnings: list[str] = []
        name_map: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            with zipfile.ZipFile(str(path)) as archive:
                for index, info in enumerate(archive.infolist()):
                    if info.is_dir():
                        continue
                    decoded = restore_zip_name(info)
                    if decoded != info.filename:
                        warnings.append(f"{info.filename}: restored gbk member name -> {decoded}")
                    safe = Path(decoded).name or "member"
                    disk_name = f"{index:04d}_{safe}"
                    (target / disk_name).write_bytes(archive.read(info))
                    name_map[disk_name] = decoded
            nested = collect_records(target, hint)
            for record in nested["records"]:
                original = name_map.get(record.source_file, record.source_file)
                record.source_file = f"{path.name}::{original}"
            warnings.extend(nested["warnings"])
            return ExtractorResult(nested["records"], warnings)
