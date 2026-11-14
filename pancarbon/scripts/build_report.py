# -*- coding: utf-8 -*-
"""Stage 8 - bilingual, dual-mode report generation (M3).

Mode A: organizational GHG calculation report (ISO 14064-1 + GHG Protocol).
Mode B: third-party verification report (ISO 14064-3).

Hard guardrail: a mode B verification statement is rendered only when a valid,
human-supplied verification_signoff.json is present. Without it the document
is a draft whose statement section contains a placeholder. This module never
generates, infers or completes an assurance conclusion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import chart_gen
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches

from ghg_common import SKILL_ROOT, canonical_hash, jsonable, load_json, load_schema, validate_schema, write_json

ASSET_DIR = SKILL_ROOT / "assets"
LAYOUT_PATH = ASSET_DIR / "report_layout.json"
PHRASES_PATH = ASSET_DIR / "phrases.json"
BLANK = "—"


def _fmt(value: Any) -> str:
    return f"{float(value):,.2f}"


def _fmt4(value: Any) -> str:
    return f"{float(value):.4f}"


def load_signoff(run: Path, cfg: dict) -> tuple[dict | None, list[str]]:
    """Load and validate the human-supplied verification sign-off."""
    ref = (cfg.get("report", {}) or {}).get("signoff_ref")
    if not ref:
        return None, []
    path = Path(str(ref))
    if not path.is_absolute():
        path = run / path
    if not path.is_file():
        return None, [f"sign-off file not found: {ref}"]
    try:
        payload = load_json(path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a warning
        return None, [f"sign-off file unreadable: {exc}"]
    errors = validate_schema(payload, load_schema("verification_signoff"))
    if errors:
        return None, [f"sign-off invalid: {e}" for e in errors]
    if not str(payload.get("statement") or "").strip():
        return None, ["sign-off statement is empty"]
    return payload, []


def _cjk_font(doc: Document) -> None:
    try:
        normal = doc.styles["Normal"]
        normal.font.name = "Microsoft YaHei"
        rpr = normal.element.get_or_add_rPr()
        fonts = rpr.find(qn("w:rFonts"))
        if fonts is not None:
            fonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    except (AttributeError, KeyError, ValueError):
        pass


def _table(doc: Document, headers: list[str], rows: list[list[Any]]) -> None:
    table = doc.add_table(rows=1, cols=len(headers))
    try:
        table.style = "Table Grid"
    except KeyError:
        pass
    for index, header in enumerate(headers):
        table.cell(0, index).text = str(header)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = "" if value is None else str(value)


def _add_prose(doc: Document, text: str) -> None:
    doc.add_paragraph(str(text))


def _signature(doc: Document, words: dict, signoff: dict | None) -> None:
    _table(doc, [words["label.item"], words["label.value"]], [
        [words["signature.reviewer"], signoff["signed_by"] if signoff else BLANK],
        [words["signature.approver"], signoff["verifier"] if signoff else BLANK],
        [words["signature.date"], signoff["signed_at"] if signoff else BLANK],
    ])


def _doc_text(doc: Document) -> str:
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


def _source_rows(source: str, ctx: dict) -> tuple[list[list[Any]], dict[str, Any]]:
    words, cfg, version = ctx["words"], ctx["cfg"], ctx["version"]
    signoff, checks = ctx["signoff"], ctx["checks"]
    numeric: dict[str, Any] = {}
    rows: list[list[Any]] = []

    if source == "basic_info":
        rows = [
            [words["label.organization"], cfg.get("organization", {}).get("name")],
            [words["label.reporting_year"], str(cfg.get("reporting_year"))],
            [words["label.boundary"], cfg.get("organization", {}).get("boundary_description")],
            [words["label.criteria"], words[ctx["standard_key"]]],
            [words["label.value"], ", ".join(str(e.get("name")) for e in cfg.get("entities", []))],
        ]
        numeric["reporting_year"] = cfg.get("reporting_year")
    elif source == "overview":
        rows = [
            [words["label.base_year"], str(cfg.get("base_year"))],
            [words["label.criteria"], words[ctx["standard_key"]]],
            [words["label.value"], words.get("report.A.conclusion", "")],
            [words["label.total"], _fmt(version["total"])],
        ]
        numeric["base_year"] = cfg.get("base_year")
        numeric["total"] = float(version["total"])
    elif source == "scope_summary":
        by_scope = version.get("by_scope", {}) or {}
        s2 = by_scope.get("S2", {}) or {}
        s3 = sum(float(v or 0) for v in (by_scope.get("S3", {}) or {}).values())
        total = float(version["total"])
        entries = [
            ("S1", "label.scope1", float(by_scope.get("S1") or 0)),
            ("S2_location", "label.scope2_location", float(s2.get("location_based") or 0)),
            ("S2_market", "label.scope2_market", float(s2.get("market_based") or 0)),
            ("S3", "label.scope3", s3),
            ("total", "label.total", total),
        ]
        for key, label_key, value in entries:
            share = value / total if total else 0.0
            rows.append([words[label_key], _fmt(value), _fmt4(share)])
            numeric[key] = value
            numeric[f"share.{key}"] = share
    elif source == "calculation_lines":
        for line in version.get("lines", []):
            rid = str(line.get("row_id"))
            keys = ("ad", "ef", "gwp", "scale", "tco2e")
            values = [line.get(key) for key in keys]
            rows.append([rid, line.get("method")] +
                        [_fmt(v) if v is not None else "" for v in values])
            for key, value in zip(keys, values):
                if value is not None:
                    numeric[f"line.{rid}.{key}"] = float(value)
    elif source == "factor_list":
        for factor in ctx["factors"]:
            src = (factor.get("source") or {}).get("name", "")
            rows.append([factor.get("id"), _fmt(factor.get("value")),
                         factor.get("unit"), src, factor.get("gwp_version")])
            numeric[f"factor.{factor.get('id')}.value"] = float(factor.get("value"))
    elif source == "evidence_list":
        evidence = sorted({name for row in ctx["ledger"].get("rows", [])
                           for name in (row.get("evidence_files") or [])})
        rows = [[str(index + 1), name] for index, name in enumerate(evidence)]
        numeric["evidence_count"] = len(evidence)
    elif source == "assurance":
        placeholder = words["report.B.statement_placeholder"]
        labels = ["label.assurance_level", "label.materiality", "label.verifier",
                  "label.signed_by", "label.signed_at", "label.status"]
        if signoff:
            values = [signoff["assurance_level"], _fmt(signoff["materiality"]),
                      signoff["verifier"], signoff["signed_by"],
                      signoff["signed_at"], "signed"]
            numeric["assurance.materiality"] = float(signoff["materiality"])
        else:
            values = [placeholder, placeholder, placeholder, placeholder,
                      placeholder, "draft"]
        rows = [[words[key], value] for key, value in zip(labels, values)]
    elif source == "procedures":
        if signoff and signoff.get("procedures"):
            rows = [[item.get("name"), item.get("status")]
                    for item in signoff["procedures"]]
        else:
            rows = [[words["report.B.statement_placeholder"], "draft"]]
    elif source == "findings":
        if signoff and signoff.get("findings"):
            rows = [[item.get("description"), item.get("category"), item.get("status")]
                    for item in signoff["findings"]]
        else:
            warnings = (checks or {}).get("warnings", []) or []
            rows = [[item.get("message", ""), item.get("rule", ""), "warning"]
                    for item in warnings]
            if not rows:
                rows = [[words["report.B.statement_placeholder"], "draft", "draft"]]
        numeric["finding_count"] = len(rows)
    else:
        raise ValueError(f"unknown report data source {source!r}")
    return rows, numeric


def build_reports(cfg: dict, ledger: dict, factors: dict, classification: dict,
                  matched: dict, results: dict, checks: dict | None,
                  layout: dict, phrases: dict, run: Path,
                  signoff: dict | None, signoff_issues: list[str]) -> dict:
    version = next((v for v in results.get("versions", [])
                    if v.get("version_id") == results.get("final_version_id")), None)
    if version is None:
        raise ValueError("results.json has no final version")
    modes = (cfg.get("report", {}) or {}).get("modes", []) or []
    languages = (cfg.get("report", {}) or {}).get("languages", []) or []
    documents: list[dict] = []

    for mode in modes:
        spec = (layout.get("modes", {}) or {}).get(mode)
        if spec is None:
            raise ValueError(f"report layout has no definition for mode {mode!r}")
        for language in languages:
            words = phrases.get(language) or {}
            ctx = {
                "words": words, "cfg": cfg, "version": version,
                "ledger": ledger, "factors": factors.get("factors", []),
                "classification": classification, "matched": matched,
                "results": results, "checks": checks, "signoff": signoff,
                "standard_key": spec.get("standard_key", "cover.standard"),
            }
            charts = chart_gen.generate_charts(results, phrases, language, run)
            doc = Document()
            _cjk_font(doc)
            doc.add_heading(str(words.get(spec.get("title_key", "cover.title"), "")), level=0)
            doc.add_paragraph(str(words.get(spec.get("standard_key", "cover.standard"), "")))
            doc.add_paragraph(str(cfg.get("organization", {}).get("name", "")))
            doc.add_paragraph(f"{words.get('label.reporting_year', '')}: {cfg.get('reporting_year')}")

            fields: dict[str, Any] = {}
            section_ids: list[str] = []
            for section in spec.get("sections", []):
                section_ids.append(section["id"])
                kind = section["kind"]
                if kind == "prose":
                    doc.add_heading(str(words.get(section["heading_key"], "")), level=1)
                    _add_prose(doc, words.get(section.get("text_key", ""), ""))
                elif kind in ("key_value", "table"):
                    doc.add_heading(str(words.get(section["heading_key"], "")), level=1)
                    rows, numeric = _source_rows(section["source"], ctx)
                    columns = section.get("columns") or ["label.item", "label.value"]
                    headers = [words.get(key, key) for key in columns]
                    _table(doc, headers, rows)
                    fields.update(numeric)
                elif kind == "guarded_statement":
                    doc.add_heading(str(words.get(section["heading_key"], "")), level=1)
                    if signoff:
                        _add_prose(doc, signoff["statement"])
                    else:
                        _add_prose(doc, words["report.B.draft_notice"])
                        _add_prose(doc, words["report.B.statement_placeholder"])
                        _add_prose(doc, words["report.B.prose.statement_hint"])
                elif kind == "charts":
                    doc.add_heading(str(words.get(section["heading_key"], "")), level=1)
                    if (cfg.get("report", {}) or {}).get("charts", True):
                        for filename in charts["files"]:
                            path = run / filename
                            if path.is_file():
                                doc.add_picture(str(path), width=Inches(5.8))
                    for key, value in charts["scope"].items():
                        fields[f"chart.scope.{key}"] = value
                    for key, value in charts["category"].items():
                        fields[f"chart.category.{key}"] = value
                    fields["chart.total"] = charts["total"]
                else:
                    raise ValueError(f"unknown section kind {kind!r}")

            if mode == "A" and spec.get("conclusion_key"):
                doc.add_heading(str(words.get("report.A.section.summary", "")), level=1)
                _add_prose(doc, words.get(spec["conclusion_key"], ""))
            _signature(doc, words, signoff)
            _add_prose(doc, words.get("report.end_marker", ""))

            draft = mode == "B" and signoff is None
            filename = f"report_{mode}_{language}" + ("_draft" if draft else "") + ".docx"
            doc.save(str(run / filename))
            text = _doc_text(doc)
            documents.append({
                "path": filename,
                "mode": mode,
                "language": language,
                "draft": draft,
                "signoff": signoff is not None,
                "statement_rendered": bool(mode == "B" and signoff is not None),
                "statement_is_placeholder": bool(mode == "B" and signoff is None),
                "fields": fields,
                "chart_data": {"scope": charts["scope"],
                               "category": charts["category"],
                               "total": charts["total"]},
                "unresolved_placeholders": sum(1 for v in fields.values() if v is None),
                "template_tokens_found": text.count("{{"),
                "sections": section_ids,
                "chart_files": charts["files"],
            })

    manifest = {
        "schema_version": "1.0",
        "run_id": results.get("run_id"),
        "config_hash": canonical_hash(cfg),
        "final_version_id": results.get("final_version_id"),
        "signoff_valid": signoff is not None,
        "signoff_issues": signoff_issues,
        "phrases_paired": set(phrases.get("zh", {})) == set(phrases.get("en", {})),
        "documents": documents,
    }
    write_json(run / "report_manifest.json", jsonable(manifest))
    return manifest


def build_from_run(run: Path) -> dict:
    """Convenience loader following the run-directory filename convention."""
    cfg = load_json(run / "org_config.json")
    ledger = load_json(run / "activity_ledger.json")
    factors = load_json(run / "factor_library.json")
    classification = load_json(run / "classification.json")
    matched = load_json(run / "matched.json")
    results = load_json(run / "results.json")
    signoff, issues = load_signoff(run, cfg)
    return build_reports(cfg, ledger, factors, classification, matched, results,
                         None, load_json(LAYOUT_PATH), load_json(PHRASES_PATH),
                         run, signoff, issues)
