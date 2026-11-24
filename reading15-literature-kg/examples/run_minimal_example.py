#!/usr/bin/env python3
"""
ILLUSTRATIVE SYNTHETIC EXAMPLE ONLY — NOT A FORMAL COMPETITION TEST CASE.

Demonstrates the complete 6-stage pipeline of `scientific-literature-kg-builder`:
1. Source-isolated ingestion of 2 independent synthetic papers
2. Base KG build on primary paper
3. Incremental update with secondary paper (1 safe alias merge, 1 guarded homonym non-merge, 1 metric discrepancy)
4. 4 traceable queries (including 1 undeterminable relation)
5. Export of result.json, knowledge_graph.json, GraphML, and Markdown report
6. Automated audit via kg_validator.py (--schema, --audit-out, --embed-audit)
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run_cmd(cmd: list) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout.strip())
    if res.returncode != 0:
        if res.stderr:
            print(res.stderr.strip(), file=sys.stderr)
        raise SystemExit(res.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run illustrative synthetic self-test.")
    parser.add_argument("--save-sample-result", default=None, help="Optional path to copy the generated illustrative result.json")
    args = parser.parse_args()

    skill_root = Path(__file__).resolve().parent.parent
    scripts = skill_root / "scripts"
    rules = skill_root / "references" / "normalization_rules.json"
    schema = skill_root / "schemas" / "kg_schema.json"

    with tempfile.TemporaryDirectory(prefix="kg_example_") as tmp:
        tmp_path = Path(tmp)
        in_dir = tmp_path / "input"
        work_dir = tmp_path / "work"
        out_dir = tmp_path / "output"
        in_dir.mkdir()
        work_dir.mkdir()
        out_dir.mkdir()

        (in_dir / "case.json").write_text(json.dumps({
            "case_id": "ILLUSTRATIVE_SYNTHETIC_EXAMPLE_001",
            "note": "SYNTHETIC ILLUSTRATIVE EXAMPLE ONLY — NOT A FORMAL COMPETITION TEST CASE.",
            "doi": "10.0000/example.primary.2025",
            "title": "Illustrative Study A on NiFe-LDH for OER",
            "output_contract": {"required_fields": ["case_id", "status", "knowledge_graph", "query_results", "unreported_items"]},
        }, indent=2), encoding="utf-8")

        (in_dir / "corpus-manifest.json").write_text(json.dumps({
            "sources": [
                {
                    "source_id": "paper_primary",
                    "paper_role": "primary",
                    "doi": "10.0000/example.primary.2025",
                    "title": "Illustrative Study A on NiFe-LDH for OER",
                    "authors": ["A. Synthetic"],
                    "license": "CC-BY-4.0",
                },
                {
                    "source_id": "paper_secondary",
                    "paper_role": "secondary",
                    "doi": "10.0000/example.secondary.2026",
                    "title": "Illustrative Study B on DFT and NiFe-LDH",
                    "authors": ["B. Synthetic"],
                    "license": "CC-BY-4.0",
                },
            ]
        }, indent=2), encoding="utf-8")

        (in_dir / "primary-material.json").write_text(json.dumps({
            "source_id": "paper_primary",
            "doi": "10.0000/example.primary.2025",
            "paragraphs": [
                {
                    "paragraph_id": "p-001",
                    "section": "Results",
                    "text": "NiFe-LDH nanosheets catalyzed the oxygen evolution reaction (OER) in 1.0 M KOH with an overpotential of 240 mV at 10 mA cm-2.",
                },
                {
                    "paragraph_id": "p-002",
                    "section": "Methods",
                    "text": "We performed Density Functional Theory (DFT) calculations to estimate intermediate adsorption energies on NiFe-LDH.",
                },
            ],
        }, indent=2), encoding="utf-8")

        (in_dir / "secondary-material.json").write_text(json.dumps({
            "source_id": "paper_secondary",
            "doi": "10.0000/example.secondary.2026",
            "paragraphs": [
                {
                    "paragraph_id": "p-001",
                    "section": "Results",
                    "text": "Under 0.1 M KOH, NiFe-LDH showed an OER overpotential of 295 mV at 10 mA cm-2, higher than prior 1.0 M KOH reports.",
                },
                {
                    "paragraph_id": "p-002",
                    "section": "Signal Processing",
                    "text": "We applied a Discrete Fourier Transform (DFT) filter to remove high-frequency noise from the impedance spectra.",
                },
            ],
        }, indent=2), encoding="utf-8")

        run_cmd([sys.executable, str(scripts / "ingest_corpus.py"), "--input-dir", str(in_dir), "--output", str(work_dir / "corpus_index.json")])

        extract_primary = {
            "topic": "Electrocatalysis (SYNTHETIC ILLUSTRATIVE EXAMPLE)",
            "sources": [{"source_id": "paper_primary", "paper_role": "primary", "doi": "10.0000/example.primary.2025"}],
            "nodes": [
                {
                    "id": "n_mat_nife",
                    "name": "NiFe-LDH",
                    "type": "Material",
                    "scope": "concept_class",
                    "provenance": [{"source_id": "paper_primary", "paragraph_id": "p-001", "location_type": "jats_paragraph_id", "quote": "NiFe-LDH nanosheets catalyzed the oxygen evolution reaction (OER)", "evidence_strength": "direct_experimental"}],
                },
                {
                    "id": "n_task_oer",
                    "name": "oxygen evolution reaction",
                    "aliases": ["OER"],
                    "type": "Task",
                    "scope": "concept_class",
                    "provenance": [{"source_id": "paper_primary", "paragraph_id": "p-001", "location_type": "jats_paragraph_id", "quote": "oxygen evolution reaction (OER) in 1.0 M KOH", "evidence_strength": "direct_experimental"}],
                },
                {
                    "id": "n_meth_dft_quantum",
                    "name": "Density Functional Theory",
                    "aliases": ["DFT"],
                    "type": "Method",
                    "scope": "concept_class",
                    "provenance": [{"source_id": "paper_primary", "paragraph_id": "p-002", "location_type": "jats_paragraph_id", "quote": "Density Functional Theory (DFT) calculations", "evidence_strength": "direct_textual"}],
                },
            ],
            "edges": [
                {
                    "id": "e_prim_1",
                    "source": "n_mat_nife",
                    "target": "n_task_oer",
                    "relation": "APPLIES_TO",
                    "claim_origin": "author_primary",
                    "conditions": "1.0 M KOH, 10 mA cm-2",
                    "numeric_value": 240,
                    "unit": "mV",
                    "provenance": [{"source_id": "paper_primary", "paragraph_id": "p-001", "location_type": "jats_paragraph_id", "quote": "overpotential of 240 mV at 10 mA cm-2", "evidence_strength": "direct_experimental"}],
                },
                {
                    "id": "e_prim_2",
                    "source": "n_meth_dft_quantum",
                    "target": "n_mat_nife",
                    "relation": "APPLIES_TO",
                    "claim_origin": "author_primary",
                    "conditions": "adsorption energy estimation",
                    "provenance": [{"source_id": "paper_primary", "paragraph_id": "p-002", "location_type": "jats_paragraph_id", "quote": "estimate intermediate adsorption energies on NiFe-LDH", "evidence_strength": "direct_textual"}],
                },
            ],
            "unreported_items": [{"item": "Faradaic efficiency", "source_id": "paper_primary", "reason": "Not reported in the provided synthetic text."}],
        }

        extract_secondary = {
            "topic": "Electrocatalysis (SYNTHETIC ILLUSTRATIVE EXAMPLE)",
            "sources": [{"source_id": "paper_secondary", "paper_role": "secondary", "doi": "10.0000/example.secondary.2026"}],
            "nodes": [
                {
                    "id": "s_mat_nife",
                    "name": "NiFe-LDH",
                    "type": "Material",
                    "scope": "concept_class",
                    "provenance": [{"source_id": "paper_secondary", "paragraph_id": "p-001", "location_type": "jats_paragraph_id", "quote": "NiFe-LDH showed an OER overpotential of 295 mV", "evidence_strength": "direct_experimental"}],
                },
                {
                    "id": "s_task_oer",
                    "name": "OER",
                    "aliases": ["oxygen evolution reaction"],
                    "type": "Task",
                    "scope": "concept_class",
                    "provenance": [{"source_id": "paper_secondary", "paragraph_id": "p-001", "location_type": "jats_paragraph_id", "quote": "OER overpotential of 295 mV at 10 mA cm-2", "evidence_strength": "direct_experimental"}],
                },
                {
                    "id": "s_meth_dft_fft",
                    "name": "Discrete Fourier Transform",
                    "aliases": ["DFT"],
                    "type": "Method",
                    "scope": "concept_class",
                    "provenance": [{"source_id": "paper_secondary", "paragraph_id": "p-002", "location_type": "jats_paragraph_id", "quote": "Discrete Fourier Transform (DFT) filter", "evidence_strength": "direct_textual"}],
                },
            ],
            "edges": [
                {
                    "id": "e_sec_1",
                    "source": "s_mat_nife",
                    "target": "s_task_oer",
                    "relation": "APPLIES_TO",
                    "claim_origin": "author_primary",
                    "conditions": "0.1 M KOH, 10 mA cm-2",
                    "numeric_value": 295,
                    "unit": "mV",
                    "provenance": [{"source_id": "paper_secondary", "paragraph_id": "p-001", "location_type": "jats_paragraph_id", "quote": "Under 0.1 M KOH, NiFe-LDH showed an OER overpotential of 295 mV at 10 mA cm-2", "evidence_strength": "direct_experimental"}],
                },
            ],
            "unreported_items": [],
        }

        (work_dir / "extract_primary.json").write_text(json.dumps(extract_primary, indent=2), encoding="utf-8")
        (work_dir / "extract_secondary.json").write_text(json.dumps(extract_secondary, indent=2), encoding="utf-8")

        run_cmd([sys.executable, str(scripts / "kg_engine.py"), "build", "--extraction", str(work_dir / "extract_primary.json"), "--rules", str(rules), "--output", str(work_dir / "kg_primary.json")])
        run_cmd([sys.executable, str(scripts / "kg_engine.py"), "update", "--base-graph", str(work_dir / "kg_primary.json"), "--extraction", str(work_dir / "extract_secondary.json"), "--rules", str(rules), "--output", str(work_dir / "kg_merged.json")])

        queries = {
            "queries": [
                {"query_id": "Q1_nife_neighborhood", "query_type": "entity_neighborhood", "question": "What tasks and methods link to NiFe-LDH?", "params": {"entity_query": "NiFe-LDH"}},
                {"query_id": "Q2_cross_paper", "query_type": "cross_paper_compare", "question": "Which canonical concepts span both papers and how do their conditions/metrics compare?", "params": {"min_sources": 2}},
                {"query_id": "Q3_conflicts", "query_type": "conflict_audit", "question": "What homonym collisions or metric discrepancies exist?", "params": {"include_secondary_citations": True}},
                {"query_id": "Q4_undeterminable_path", "query_type": "path_check", "question": "Is Discrete Fourier Transform linked to NiFe-LDH?", "params": {"source_entity": "Discrete Fourier Transform", "target_entity": "NiFe-LDH", "max_hops": 3}},
            ]
        }
        (work_dir / "queries.json").write_text(json.dumps(queries, indent=2), encoding="utf-8")
        run_cmd([sys.executable, str(scripts / "kg_engine.py"), "query", "--graph", str(work_dir / "kg_merged.json"), "--queries", str(work_dir / "queries.json"), "--output", str(work_dir / "query_results.json")])

        run_cmd([
            sys.executable, str(scripts / "kg_engine.py"), "export",
            "--graph", str(work_dir / "kg_merged.json"),
            "--query-results", str(work_dir / "query_results.json"),
            "--case-json", str(in_dir / "case.json"),
            "--corpus-index", str(work_dir / "corpus_index.json"),
            "--output-dir", str(out_dir),
        ])

        run_cmd([
            sys.executable, str(scripts / "kg_validator.py"),
            "--result", str(out_dir / "result.json"),
            "--graph", str(out_dir / "knowledge_graph.json"),
            "--corpus-index", str(work_dir / "corpus_index.json"),
            "--case-json", str(in_dir / "case.json"),
            "--schema", str(schema),
            "--audit-out", str(out_dir / "quality_audit.json"),
            "--embed-audit",
        ])

        if args.save_sample_result:
            shutil.copy2(out_dir / "result.json", args.save_sample_result)

        print("[OK] Minimal illustrative example completed and passed all validation checks.")


if __name__ == "__main__":
    main()
