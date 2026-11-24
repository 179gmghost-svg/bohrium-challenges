#!/usr/bin/env python3
"""Harbor case intake and one-shot packaging for the Academic Language Polishing skill.

Two subcommands keep the runtime path short (the Harbor budget is 900 s / 64 requests):

    python3 scripts/harbor_case.py init \
        --case /input/case.json --work /app/work [--task task.md]

    python3 scripts/harbor_case.py finalize \
        --case /input/case.json --work /app/work --output /app/output \
        [--polished /app/work/polished.txt] [--edit-log /app/work/edit_log.json] \
        [--glossary /app/work/glossary.json] [--genre journal_article]

`init` never invents content: it locates the manuscript text, glossary and target
register inside an unknown case schema, writes them to the work directory, and
records every field it could not resolve as an explicit uncertainty.

`finalize` runs the deterministic five-module audit and then the output packager,
so the whole Phase 3-4 loop is one command.

Python 3.9+ standard library only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from package_result import package_outputs  # noqa: E402
from verify_polish import run_full_audit  # noqa: E402

TEXT_KEYS = (
    "original_text", "source_text", "manuscript_text", "text", "manuscript",
    "draft", "body", "abstract_text", "abstract", "section_text", "input_text",
    "raw_text", "content",
)
GLOSSARY_KEYS = ("glossary", "term_base", "terminology", "glossary_terms", "terms")
GENRE_KEYS = ("genre", "register", "document_type", "target_genre", "style", "text_type")
LANGUAGE_KEYS = ("language", "lang", "target_language")
KNOWN_GENRES = (
    "journal_article", "thesis_dissertation", "grant_proposal",
    "peer_review_rebuttal", "bilingual_abstract",
)
GENRE_ALIASES = {
    "journal": "journal_article", "paper": "journal_article", "article": "journal_article",
    "期刊论文": "journal_article", "论文": "journal_article",
    "thesis": "thesis_dissertation", "dissertation": "thesis_dissertation",
    "学位论文": "thesis_dissertation", "毕业论文": "thesis_dissertation",
    "grant": "grant_proposal", "proposal": "grant_proposal", "基金申请书": "grant_proposal",
    "rebuttal": "peer_review_rebuttal", "response": "peer_review_rebuttal",
    "审稿回复": "peer_review_rebuttal", "回复审稿意见": "peer_review_rebuttal",
    "abstract": "bilingual_abstract", "摘要": "bilingual_abstract",
}


def _walk(node: Any, path: str = "$") -> list[tuple[str, Any]]:
    """Depth-first (path, value) listing of every node in a JSON structure."""
    items: list[tuple[str, Any]] = [(path, node)]
    if isinstance(node, dict):
        for k, v in node.items():
            items.extend(_walk(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            items.extend(_walk(v, f"{path}[{i}]"))
    return items


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_stringify(v) for v in value]
        return "\n\n".join(p for p in parts if p.strip())
    return ""


def _find_text(case: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Return (text, provenance_paths, candidate_paths_rejected)."""
    nodes = _walk(case)
    by_key: dict[str, list[tuple[str, Any]]] = {}
    for path, value in nodes:
        key = path.split(".")[-1].split("[")[0].lower()
        by_key.setdefault(key, []).append((path, value))

    for key in TEXT_KEYS:
        for path, value in by_key.get(key, []):
            text = _stringify(value)
            if text.strip():
                return text, [path], []
    # Fallback: the longest string anywhere that is not obviously instructions.
    rejected: list[str] = []
    best = ("", "")
    for path, value in nodes:
        if not isinstance(value, str) or len(value) < 120:
            continue
        leaf = path.split(".")[-1].lower()
        if any(tag in leaf for tag in ("instruction", "task", "rubric", "note", "description", "prompt")):
            rejected.append(path)
            continue
        if len(value) > len(best[1]):
            best = (path, value)
    return best[1], ([best[0]] if best[1] else []), rejected


def _find_glossary(case: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    for path, value in _walk(case):
        leaf = path.split(".")[-1].split("[")[0].lower()
        if leaf in GLOSSARY_KEYS:
            if isinstance(value, dict) and isinstance(value.get("terms"), list):
                return value, path
            if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                return {"terms": value}, path
    return None, None


def _normalize_genre(raw: str | None) -> tuple[str, str]:
    """Map a free-form register label onto one of the five supported profiles.

    Returns (genre, status) with status in {"explicit", "alias", "default"}.
    Matching is exact first, then longest-alias-first: short aliases such as 论文
    must not pre-empt the more specific 学位论文.
    """
    if raw:
        key = raw.strip().lower()
        if key in KNOWN_GENRES:
            return key, "explicit"
        if key in GENRE_ALIASES:
            return GENRE_ALIASES[key], "alias"
        for alias in sorted(GENRE_ALIASES, key=len, reverse=True):
            if alias in key:
                return GENRE_ALIASES[alias], "alias"
    return "journal_article", "default"


def _find_scalar(case: dict[str, Any], keys: tuple[str, ...]) -> tuple[str | None, str | None]:
    for path, value in _walk(case):
        leaf = path.split(".")[-1].split("[")[0].lower()
        if leaf in keys and isinstance(value, str) and value.strip():
            return value.strip(), path
    return None, None


def cmd_init(args: argparse.Namespace) -> int:
    case_path = Path(args.case)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    if not case_path.exists():
        print(json.dumps({"status": "failed", "error": f"case file not found: {case_path}"}, ensure_ascii=False, indent=2))
        return 1
    try:
        case = json.loads(case_path.read_text(encoding="utf-8-sig", errors="replace"))
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "failed", "error": f"case.json is not valid JSON: {exc}"}, ensure_ascii=False, indent=2))
        return 1
    if not isinstance(case, dict):
        case = {"content": case}

    text, provenance, rejected = _find_text(case)
    glossary, glossary_path = _find_glossary(case)
    raw_genre, genre_path = _find_scalar(case, GENRE_KEYS)
    raw_lang, lang_path = _find_scalar(case, LANGUAGE_KEYS)
    genre, genre_status = _normalize_genre(raw_genre)

    uncertainties: list[str] = []
    material_gaps: list[str] = []
    if not text.strip():
        material_gaps.append("未能在 case.json 中定位到稿件正文；已写入空 original.txt，需人工确认输入结构。")
    if genre_status == "default":
        uncertainties.append(
            f"目标文体未给出或无法映射（raw={raw_genre!r}），已按 journal_article 处理。"
        )
    elif genre_status == "alias":
        uncertainties.append(f"目标文体标注为 {raw_genre!r}，已映射到 {genre}。")
    if glossary is None:
        uncertainties.append("case.json 中未提供术语表；已跳过术语统一检查（Module 3 仅做缩写自检）。")
    if rejected:
        uncertainties.append("以下长文本字段被判定为任务说明而非正文，未纳入润色范围：" + ", ".join(rejected))

    (work / "original.txt").write_text(text, encoding="utf-8")
    if glossary is not None:
        (work / "glossary.json").write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "genre.txt").write_text(genre, encoding="utf-8")

    case_id = case.get("case_id") or case.get("id") or "unknown_case"
    contract = case.get("output_contract") if isinstance(case.get("output_contract"), dict) else {}
    brief = {
        "status": "ok",
        "case_id": case_id,
        "language": raw_lang or "auto",
        "language_path": lang_path,
        "genre": genre,
        "genre_path": genre_path,
        "genre_status": genre_status,
        "glossary_path": glossary_path,
        "glossary_term_count": len(glossary.get("terms", [])) if glossary else 0,
        "text_provenance": provenance,
        "char_count": len(text),
        "line_count": len(text.splitlines()),
        "output_contract_fields": sorted(contract.keys()),
        "written": ["original.txt"] + (["glossary.json"] if glossary is not None else []) + ["genre.txt"],
        "material_gaps": material_gaps,
        "uncertainties": uncertainties,
    }
    (work / "case_brief.json").write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(brief, ensure_ascii=False, indent=2))
    return 0


def cmd_finalize(args: argparse.Namespace) -> int:
    work = Path(args.work)
    output = Path(args.output)
    polished_path = Path(args.polished) if args.polished else work / "polished.txt"
    edit_log_path = Path(args.edit_log) if args.edit_log else work / "edit_log.json"
    glossary_path = Path(args.glossary) if args.glossary else work / "glossary.json"
    genre_path = work / "genre.txt"

    for required in (polished_path, edit_log_path):
        if not required.exists():
            print(json.dumps({
                "status": "failed",
                "error": f"missing input for finalize: {required}",
                "next": "Write the polished manuscript and the sentence-level edit_log.json first.",
            }, ensure_ascii=False, indent=2))
            return 1

    genre = args.genre
    if not genre and genre_path.exists():
        genre = genre_path.read_text(encoding="utf-8").strip() or "journal_article"
    genre = genre or "journal_article"

    glossary = None
    if glossary_path.exists():
        try:
            glossary = json.loads(glossary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(json.dumps({
                "status": "failed",
                "error": f"glossary is not valid JSON: {glossary_path}",
            }, ensure_ascii=False, indent=2))
            return 1

    original_path = Path(args.original) if args.original else work / "original.txt"
    original = original_path.read_text(encoding="utf-8", errors="replace") if original_path.exists() else ""
    polished = polished_path.read_text(encoding="utf-8", errors="replace")
    edit_log = json.loads(edit_log_path.read_text(encoding="utf-8"))

    audit = run_full_audit(original, polished, edit_log, glossary, genre=genre)
    audit_path = work / "verification_audit.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    brief_path = work / "case_brief.json"
    brief = json.loads(brief_path.read_text(encoding="utf-8")) if brief_path.exists() else {}
    status = args.status or "completed"
    package_outputs(
        case_json_path=Path(args.case) if args.case else None,
        polished_path=polished_path,
        edit_log_path=edit_log_path,
        audit_report_path=audit_path,
        output_dir=output,
        status=status,
        material_gaps=brief.get("material_gaps", []),
        conflicts=[],
        uncertainties=brief.get("uncertainties", []),
    )

    summary = {
        "status": "ok" if audit["overall_passed"] else "needs_revision",
        "overall_passed": audit["overall_passed"],
        "genre": genre,
        "audit": str(audit_path),
        "output_dir": str(output),
        "artifacts": sorted(p.name for p in output.glob("*")),
        "blocking_items": {
            "anchor_mismatches": audit["modules"]["1_anchor_preservation"]["mismatch_count"],
            "hedging_warnings": audit["modules"]["2_hedging_conservation"]["warning_count"],
            "glossary_issues": (
                len(audit["modules"]["3_glossary_and_abbreviations"]["glossary_conflicts"])
                + len(audit["modules"]["3_glossary_and_abbreviations"]["forbidden_variant_hits"])
                + len(audit["modules"]["3_glossary_and_abbreviations"]["abbreviation_issues"])
            ),
            "register_issues": audit["modules"]["4_register_and_chinglish"]["issue_count"],
            "unlogged_changed_sentences": len(
                audit["modules"]["5_edit_log_completeness"]["unlogged_changed_sentences"]
            ),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if audit["overall_passed"] else 2


def main() -> None:
    try:  # keep Chinese diagnostics readable when the console default is not UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description="Harbor case intake and one-shot packaging.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Read case.json and stage original.txt / glossary.json / genre.")
    p_init.add_argument("--case", required=True, help="Path to /input/case.json")
    p_init.add_argument("--work", default="/app/work", help="Work directory (default /app/work)")
    p_init.set_defaults(func=cmd_init)

    p_fin = sub.add_parser("finalize", help="Run the five-module audit and package /app/output.")
    p_fin.add_argument("--case", help="Path to /input/case.json")
    p_fin.add_argument("--work", default="/app/work", help="Work directory (default /app/work)")
    p_fin.add_argument("--output", default="/app/output", help="Output directory (default /app/output)")
    p_fin.add_argument("--original", help="Override original text path")
    p_fin.add_argument("--polished", help="Polished text path (default <work>/polished.txt)")
    p_fin.add_argument("--edit-log", help="Edit log JSON path (default <work>/edit_log.json)")
    p_fin.add_argument("--glossary", help="Glossary JSON path (default <work>/glossary.json)")
    p_fin.add_argument("--genre", help="Override target genre")
    p_fin.add_argument("--status", choices=["completed", "partial_material_gap", "failed"])
    p_fin.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
