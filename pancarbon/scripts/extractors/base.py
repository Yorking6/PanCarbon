# -*- coding: utf-8 -*-
"""Extractor interface for Stage 1 (implementation scheduled for M4).

M0 ships only the data contract so that later extractors produce a stable
shape. No extractor is executable at M0; `cli.py extract` returns
NOT_IMPLEMENTED.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RawRecord:
    """One voucher-level observation before confirmation.

    Values stay un-normalized here. Unit conversion and period resolution are
    recorded later in activity_ledger.conversion_chain.
    """

    source_file: str
    extractor: str
    observed_value: Any
    observed_unit: str
    source_locator: str = ""
    voucher_period: str = ""
    confidence: str = "high"
    needs_manual: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "extractor": self.extractor,
            "observed_value": self.observed_value,
            "observed_unit": self.observed_unit,
            "source_locator": self.source_locator,
            "voucher_period": self.voucher_period,
            "confidence": self.confidence,
            "needs_manual": self.needs_manual,
            "metadata": self.metadata,
        }


@dataclass
class ExtractorResult:
    records: list[RawRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "records": [r.as_dict() for r in self.records],
            "warnings": list(self.warnings),
        }


class BaseExtractor(ABC):
    """Contract for voucher extractors.

    Implementations must never guess a value: ambiguous unit, period or amount
    produces a record with needs_manual=True, to be resolved at the Stage 2
    human confirmation gate.
    """

    name: str = "base"

    @abstractmethod
    def supports(self, path: Path) -> bool:
        """Return whether this extractor can read the given file."""

    @abstractmethod
    def extract(self, path: Path, hint: dict[str, Any] | None = None) -> ExtractorResult:
        """Return raw records plus warnings; never raise on dirty vouchers."""
