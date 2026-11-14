# -*- coding: utf-8 -*-
"""Stage 8 - embedded report charts (M3).

Chart data comes only from results.json. Titles, axis labels and fonts come from
the runtime configuration and assets/phrases.json, so the CN and EN versions
are labelled consistently and carry identical numeric data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

BAR_COLOR = "#4C78A8"
CATEGORY_COLOR = "#72B7B2"
CJK_FONT = "Microsoft YaHei"
LATIN_FONT = "DejaVu Sans"


def _font_for(language: str) -> str:
    if language != "zh":
        return LATIN_FONT
    available = {font.name for font in font_manager.fontManager.ttflist}
    return CJK_FONT if CJK_FONT in available else LATIN_FONT


def scope_series(results: dict) -> dict[str, float]:
    version = next((v for v in results.get("versions", [])
                    if v.get("version_id") == results.get("final_version_id")), None)
    if version is None:
        raise ValueError("results.json has no final version")
    by_scope = version.get("by_scope", {}) or {}
    s2 = by_scope.get("S2", {}) or {}
    s3 = by_scope.get("S3", {}) or {}
    return {
        "S1": float(by_scope.get("S1") or 0),
        "S2": float(s2.get("location_based") or 0),
        "S3": float(sum(float(value or 0) for value in s3.values())),
    }


def category_series(results: dict) -> dict[str, float]:
    version = next((v for v in results.get("versions", [])
                    if v.get("version_id") == results.get("final_version_id")), None)
    if version is None:
        raise ValueError("results.json has no final version")
    s3 = (version.get("by_scope", {}) or {}).get("S3", {}) or {}
    return {str(key): float(value or 0) for key, value in s3.items()
            if float(value or 0) != 0}


def _bar_chart(labels: list[str], values: list[float], title: str,
               ylabel: str, path: Path, font: str, color: str) -> None:
    plt.rcParams["font.sans-serif"] = [font, LATIN_FONT]
    plt.rcParams["axes.unicode_minus"] = False
    fig, axis = plt.subplots(figsize=(6.4, 3.2), dpi=150)
    try:
        axis.bar(range(len(labels)), values, color=color, width=0.62)
        axis.set_xticks(range(len(labels)))
        axis.set_xticklabels(labels, fontsize=8)
        axis.set_ylabel(ylabel, fontsize=9)
        axis.set_title(title, fontsize=11)
        axis.grid(axis="y", linestyle=":", alpha=0.5)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
        fig.tight_layout()
        fig.savefig(str(path), bbox_inches="tight")
    finally:
        plt.close(fig)


def generate_charts(results: dict, phrases: dict, language: str,
                    out_dir: Path) -> dict[str, Any]:
    """Write two PNG charts and return the numeric snapshot used by V07."""
    if language not in ("zh", "en"):
        raise ValueError(f"unsupported language {language!r}")
    words = phrases.get(language, {}) or {}
    font = _font_for(language)
    out_dir.mkdir(parents=True, exist_ok=True)

    scope = scope_series(results)
    categories = category_series(results)
    charts = {
        "scope": {
            "path": out_dir / f"chart_scope_{language}.png",
            "title_key": "chart.scope_breakdown",
            "data": scope,
            "color": BAR_COLOR,
        },
        "category": {
            "path": out_dir / f"chart_category_{language}.png",
            "title_key": "chart.category_breakdown",
            "data": categories,
            "color": CATEGORY_COLOR,
        },
    }
    files: list[str] = []
    for chart in charts.values():
        data: dict[str, float] = chart["data"]
        labels = list(data.keys())
        values = [data[key] for key in labels]
        _bar_chart(labels, values, str(words.get(chart["title_key"], "")),
                   str(words.get("chart.axis.tco2e", "tCO2e")),
                   Path(chart["path"]), font, str(chart["color"]))
        files.append(Path(chart["path"]).name)

    return {
        "language": language,
        "font": font,
        "files": files,
        "scope": scope,
        "category": categories,
        "total": float(next(v for v in results["versions"]
                            if v["version_id"] == results["final_version_id"])["total"]),
    }
