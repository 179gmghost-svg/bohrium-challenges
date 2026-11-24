#!/usr/bin/env python3
"""Harbor Output Contract Packager for Academic Language Polishing.

Generates:
1. /app/output/result.json (preserving all original output_contract fields + case_id)
2. polished_manuscript.md (clean editable polished text)
3. edit_log.md and edit_log.csv (auditable sentence-level change log)
4. human_review_flags.md (material gaps, conflicts, and author sign-off items)
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def render_edit_log_markdown(edit_log: list[dict[str, Any]]) -> str:
    lines = [
        "# 逐句修改说明（Sentence-Level Edit Log）",
        "",
        "| Edit ID | 位置 | 修改类型 | 复核分级 | 原文（Original） | 改文（Revised） | 修改理由（Rationale） | 需人工确认 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for e in edit_log:
        def _esc(val: Any) -> str:
            return str(val).replace("|", "\\|").replace("\n", " ").strip()

        confirm = "是（需确认）" if e.get("requires_human_confirmation") else "否"
        lines.append(
            f"| {_esc(e.get('edit_id', ''))} "
            f"| {_esc(e.get('location', ''))} "
            f"| {_esc(e.get('edit_type', ''))} "
            f"| {_esc(e.get('review_tier', ''))} "
            f"| {_esc(e.get('original', ''))} "
            f"| {_esc(e.get('revised', ''))} "
            f"| {_esc(e.get('rationale', ''))} "
            f"| {confirm} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_edit_log_csv(edit_log: list[dict[str, Any]], path: Path) -> None:
    fieldnames = [
        "edit_id",
        "location",
        "edit_type",
        "review_tier",
        "original",
        "revised",
        "rationale",
        "requires_human_confirmation",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for e in edit_log:
            writer.writerow({k: e.get(k, "") for k in fieldnames})


def render_human_flags_markdown(
    human_flags: list[dict[str, Any]],
    material_gaps: list[str],
    conflicts: list[str],
) -> str:
    lines = ["# 待人工确认与边界清单（Human Review & Boundaries）", ""]
    lines.append("## 1. 需作者确认的修改或疑点")
    if human_flags:
        for item in human_flags:
            lines.append(
                f"- **{item.get('location', 'N/A')}** ({item.get('edit_id', 'FLAG')}): "
                f"{item.get('reason', item.get('rationale', ''))}"
            )
    else:
        lines.append("- 无额外待确认修改项。")

    lines.append("")
    lines.append("## 2. 材料缺口（Material Gaps）")
    if material_gaps:
        for g in material_gaps:
            lines.append(f"- {g}")
    else:
        lines.append("- 未检测到影响润色的材料缺口。")

    lines.append("")
    lines.append("## 3. 术语/事实冲突（Conflicts）")
    if conflicts:
        for c in conflicts:
            lines.append(f"- {c}")
    else:
        lines.append("- 未检测到术语表或原文内部冲突。")
    lines.append("")
    return "\n".join(lines)


def package_outputs(
    case_json_path: Path | None,
    polished_path: Path,
    edit_log_path: Path,
    audit_report_path: Path,
    output_dir: Path,
    status: str = "completed",
    material_gaps: list[str] | None = None,
    conflicts: list[str] | None = None,
    uncertainties: list[str] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    polished_text = polished_path.read_text(encoding="utf-8")
    edit_log = json.loads(edit_log_path.read_text(encoding="utf-8"))
    audit_report = json.loads(audit_report_path.read_text(encoding="utf-8"))

    material_gaps = material_gaps or []
    conflicts = conflicts or []
    uncertainties = uncertainties or []

    case_data: dict[str, Any] = {}
    if case_json_path and case_json_path.exists():
        case_data = json.loads(case_json_path.read_text(encoding="utf-8"))

    result: dict[str, Any] = {}
    if isinstance(case_data.get("output_contract"), dict):
        result.update(case_data["output_contract"])

    case_id = case_data.get("case_id", "unknown_case")
    human_flags = [e for e in edit_log if e.get("requires_human_confirmation")]

    polished_out = output_dir / "polished_manuscript.md"
    polished_out.write_text(polished_text, encoding="utf-8")

    edit_md_out = output_dir / "edit_log.md"
    edit_md_out.write_text(render_edit_log_markdown(edit_log), encoding="utf-8")

    edit_csv_out = output_dir / "edit_log.csv"
    write_edit_log_csv(edit_log, edit_csv_out)

    flags_md_out = output_dir / "human_review_flags.md"
    flags_md_out.write_text(
        render_human_flags_markdown(human_flags, material_gaps, conflicts),
        encoding="utf-8",
    )

    audit_out = output_dir / "verification_audit.json"
    audit_out.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2), encoding="utf-8")

    result.update({
        "case_id": case_id,
        "status": status,
        "polished_text": polished_text,
        "edit_log": edit_log,
        "human_review_flags": human_flags,
        "verification_audit": {
            "overall_passed": audit_report.get("overall_passed", False),
            "anchor_mismatches": audit_report.get("modules", {}).get("1_anchor_preservation", {}).get("mismatch_count", 0),
            "hedging_warnings": audit_report.get("modules", {}).get("2_hedging_conservation", {}).get("warning_count", 0),
            "glossary_conflicts": len(audit_report.get("modules", {}).get("3_glossary_and_abbreviations", {}).get("glossary_conflicts", [])),
            "forbidden_variant_hits": len(audit_report.get("modules", {}).get("3_glossary_and_abbreviations", {}).get("forbidden_variant_hits", [])),
            "register_issues": audit_report.get("modules", {}).get("4_register_and_chinglish", {}).get("issue_count", 0),
            "unlogged_changed_sentences": len(audit_report.get("modules", {}).get("5_edit_log_completeness", {}).get("unlogged_changed_sentences", [])),
            "text_similarity_ratio": audit_report.get("modules", {}).get("5_edit_log_completeness", {}).get("text_similarity_ratio", 1.0),
        },
        "boundaries_and_uncertainty": {
            "human_confirmation_items": human_flags,
            "material_gaps": material_gaps,
            "conflicts": conflicts,
            "uncertainties": uncertainties,
        },
        "artifacts": {
            "polished_manuscript": polished_out.name,
            "edit_log_markdown": edit_md_out.name,
            "edit_log_csv": edit_csv_out.name,
            "human_review_flags": flags_md_out.name,
            "verification_audit": audit_out.name,
        },
    })

    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Package Harbor-compatible output for academic polishing.")
    parser.add_argument("--case-json", help="Path to /input/case.json (optional).")
    parser.add_argument("--polished", required=True, help="Path to polished manuscript file.")
    parser.add_argument("--edit-log", required=True, help="Path to edit_log.json.")
    parser.add_argument("--audit", required=True, help="Path to verification_audit.json.")
    parser.add_argument("--output-dir", required=True, help="Target output directory (e.g. /app/output).")
    parser.add_argument("--status", default="completed", choices=["completed", "partial_material_gap", "failed"])
    parser.add_argument("--material-gap", action="append", default=[])
    parser.add_argument("--conflict", action="append", default=[])
    parser.add_argument("--uncertainty", action="append", default=[])
    args = parser.parse_args()

    package_outputs(
        case_json_path=Path(args.case_json) if args.case_json else None,
        polished_path=Path(args.polished),
        edit_log_path=Path(args.edit_log),
        audit_report_path=Path(args.audit),
        output_dir=Path(args.output_dir),
        status=args.status,
        material_gaps=args.material_gap,
        conflicts=args.conflict,
        uncertainties=args.uncertainty,
    )


if __name__ == "__main__":
    main()
