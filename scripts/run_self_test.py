#!/usr/bin/env python3
"""Self-Test & Stress-Test Suite for Academic Language Polishing Skill (v2.2)."""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import json
import shutil
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import harbor_case
from package_result import package_outputs
from verify_polish import run_full_audit


def _temp_dir():
    """Writable scratch dir: system temp first, then the current directory.

    Some sandboxes hand out a temp directory that exists but refuses writes, so
    each candidate is probed with a real write before it is accepted.
    """
    for base in (Path(tempfile.gettempdir()), Path.cwd()):
        try:
            d = Path(tempfile.mkdtemp(prefix="alp_selftest_", dir=base))
            probe = d / ".write_probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            return d
        except OSError:
            continue
    fallback = Path.cwd() / ".alp_selftest_tmp"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def test_positive_en_journal_latex() -> None:
    orig = (
        r"With the rapid development of battery systems, the solid electrolyte interface "
        r"play a very important role in capacity retention \cite{wang2024}. "
        r"As shown in Fig. 1, the impedance dropped from $42.3 \pm 1.2\ \Omega$ to $18.6 \pm 0.8\ \Omega$ "
        r"(p < 0.01, n = 12). These observations may suggest that the additive is associated with "
        r"reduced parasitic reactions, which is very good for long-term cycling."
    )
    pol = (
        r"In battery systems, the solid-electrolyte interphase (SEI) "
        r"plays a critical role in capacity retention \cite{wang2024}. "
        r"As shown in Fig. 1, the impedance dropped from $42.3 \pm 1.2\ \Omega$ to $18.6 \pm 0.8\ \Omega$ "
        r"(p < 0.01, n = 12). These observations may suggest that the additive is associated with "
        r"reduced parasitic reactions, which is favorable for long-term cycling."
    )
    edit_log = [
        {
            "edit_id": "E001",
            "location": "S1",
            "original": r"With the rapid development of battery systems, the solid electrolyte interface play a very important role in capacity retention \cite{wang2024}.",
            "revised": r"In battery systems, the solid-electrolyte interphase (SEI) plays a critical role in capacity retention \cite{wang2024}.",
            "edit_type": "CHINGLISH",
            "review_tier": "B_STYLE_REGISTER",
            "rationale": "Removed Chinglish boilerplate, fixed subject-verb agreement, enforced glossary SEI, preserved LaTeX citation.",
            "requires_human_confirmation": False,
        },
        {
            "edit_id": "E002",
            "location": "S3",
            "original": "which is very good for long-term cycling.",
            "revised": "which is favorable for long-term cycling.",
            "edit_type": "REGISTER",
            "review_tier": "B_STYLE_REGISTER",
            "rationale": "Replaced colloquial 'very good' with 'favorable' while preserving hedging and correlation.",
            "requires_human_confirmation": False,
        },
    ]
    glossary = {
        "terms": [
            {
                "term_id": "T002",
                "preferred_en": "solid-electrolyte interphase",
                "preferred_zh": "固体电解质界面膜",
                "abbrev": "SEI",
                "define_on_first_use": True,
                "case_sensitive": False,
                "forbidden_variants": ["solid electrolyte interface"],
            }
        ]
    }
    report = run_full_audit(orig, pol, edit_log, glossary, genre="journal_article")
    assert report["overall_passed"], f"Expected PASS, got: {json.dumps(report, indent=2, ensure_ascii=False)}"


def test_positive_zh_thesis_and_si_spacing() -> None:
    # Tests ZH scientific words ("无机", "不同") do NOT trigger false negation shift, and SI spacing "25°C -> 25 °C" passes
    orig = "众所周知，不同无机涂层在25°C下的电化学交流阻抗谱表现特别好[3]。如图 2 所示，部分样品的界面阻抗可能与膜厚相关。"
    pol = "在 25 °C 条件下，各类无机涂层的电化学阻抗谱（EIS）表现较为理想[3]。如图 2 所示，部分样品的界面阻抗可能与膜厚相关。"
    edit_log = [
        {
            "edit_id": "E001",
            "location": "S1",
            "original": "众所周知，不同无机涂层在25°C下的电化学交流阻抗谱表现特别好[3]。",
            "revised": "在 25 °C 条件下，各类无机涂层的电化学阻抗谱（EIS）表现较为理想[3]。",
            "edit_type": "REGISTER",
            "review_tier": "B_STYLE_REGISTER",
            "rationale": "去除口语套话“众所周知”与“特别好”，规范 SI 单位空格（25 °C），按术语表统一为“电化学阻抗谱（EIS）”，保留引用[3]。",
            "requires_human_confirmation": False,
        }
    ]
    glossary = {
        "terms": [
            {
                "term_id": "T001",
                "preferred_zh": "电化学阻抗谱",
                "abbrev": "EIS",
                "define_on_first_use": True,
                "forbidden_variants": ["电化学交流阻抗谱"],
            }
        ]
    }
    report = run_full_audit(orig, pol, edit_log, glossary, genre="thesis_dissertation")
    assert report["overall_passed"], f"Expected ZH PASS, got: {json.dumps(report, indent=2, ensure_ascii=False)}"


def test_negative_anchor_hedging_negation_conditional_quantifier() -> None:
    orig = (
        "If annealed at 300 °C [2], some samples did not degrade and may suggest that "
        "surface vacancies are associated with 94.2% selectivity."
    )
    bad_pol = (
        "Annealed at 300 °C, all samples degraded and proves that "
        "surface vacancies causes 95.0% selectivity."
    )
    edit_log = [
        {
            "edit_id": "E001",
            "location": "S1",
            "original": orig,
            "revised": bad_pol,
            "edit_type": "REGISTER",
            "review_tier": "B_STYLE_REGISTER",
            "rationale": "Aggressive rewrite.",
            "requires_human_confirmation": False,
        }
    ]
    report = run_full_audit(orig, bad_pol, edit_log, None, genre="journal_article")
    assert not report["overall_passed"]
    assert not report["modules"]["1_anchor_preservation"]["passed"]
    issues = {w["issue"] for w in report["modules"]["2_hedging_conservation"]["warnings"]}
    for expected in (
        "HEDGING_STRENGTHENED",
        "CORRELATION_UPGRADED_TO_CAUSATION",
        "NEGATION_SCOPE_SHIFT",
        "CONDITIONAL_BOUNDARY_DROPPED",
        "QUANTIFIER_OVERGENERALIZED",
    ):
        assert expected in issues, f"Missing {expected} in {issues}"


def test_negative_glossary_conflict_and_register() -> None:
    orig = "The AC impedance spectra don't show groundbreaking changes, and EIS was recorded. 毫无疑问结果非常大。"
    pol = orig
    glossary = {
        "terms": [
            {
                "term_id": "T1",
                "preferred_en": "electrochemical impedance spectroscopy",
                "abbrev": "EIS",
                "define_on_first_use": True,
                "forbidden_variants": ["AC impedance spectra"],
            },
            {
                "term_id": "T2",
                "preferred_en": "electron impact spectrometry",
                "abbrev": "EIS",
                "define_on_first_use": True,
                "forbidden_variants": [],
            },
        ]
    }
    report = run_full_audit(orig, pol, [], glossary, genre="journal_article")
    m3 = report["modules"]["3_glossary_and_abbreviations"]
    m4 = report["modules"]["4_register_and_chinglish"]
    assert len(m3["glossary_conflicts"]) == 1
    assert len(m3["forbidden_variant_hits"]) == 1
    assert len(m3["abbreviation_issues"]) >= 1
    issue_types = {i["type"] for i in m4["issues"]}
    assert "COLLOQUIAL_CONTRACTION" in issue_types
    assert "PROMOTIONAL_HYPE_EN" in issue_types
    assert "PROMOTIONAL_OR_ORAL_ZH" in issue_types


def test_negative_unlogged_edit_detection() -> None:
    orig = "First sentence stays unchanged. Second sentence was silently rewritten."
    pol = "First sentence stays unchanged. Second sentence has been quietly altered."
    report = run_full_audit(orig, pol, [], None, genre="journal_article")
    m5 = report["modules"]["5_edit_log_completeness"]
    assert not m5["passed"], "Should fail when a changed sentence is unlogged"
    assert len(m5["unlogged_changed_sentences"]) == 1


def test_positive_contraction_negation_parity() -> None:
    """don’t -> do not is a register fix, not a change of negation polarity."""
    orig = "The device don’t show hysteresis at 25 °C."
    pol = "The device does not exhibit hysteresis at 25 °C."
    edit_log = [
        {
            "edit_id": "E001",
            "location": "S1",
            "original": orig,
            "revised": pol,
            "edit_type": "GRAMMAR",
            "review_tier": "A_SAFE_MECHANICAL",
            "rationale": "Expanded the contraction and fixed subject-verb agreement; negation polarity unchanged.",
            "requires_human_confirmation": False,
        }
    ]
    report = run_full_audit(orig, pol, edit_log, None, genre="journal_article")
    m2 = report["modules"]["2_hedging_conservation"]
    assert m2["passed"], f"Contraction expansion must not be a negation shift: {json.dumps(m2, ensure_ascii=False)}"


def test_negative_document_level_hedge_loss() -> None:
    """A paraphrase that drops an unlogged 'may' must fail the document-level channel."""
    orig = (
        "The additive may improve stability. "
        "The film was annealed at 300 °C for 30 min."
    )
    pol = (
        "The additive improves stability. "
        "The film was annealed at 300 °C for 30 min."
    )
    report = run_full_audit(orig, pol, [], None, genre="journal_article")
    m2 = report["modules"]["2_hedging_conservation"]
    assert not m2["passed"]
    issues = {w["issue"] for w in m2["warnings"]}
    assert "DOC_HEDGING_WEAKENED" in issues, issues


def test_harbor_case_intake_nested_schema() -> None:
    """Unknown nested case schemas are mapped to original.txt / glossary.json / genre."""
    import contextlib
    import io

    tmp = _temp_dir()
    try:
        case = {
            "case_id": "intake-001",
            "task": "请润色下面的学位论文片段。" * 5,
            "input": {"genre": "学位论文", "language": "zh", "manuscript": "众所周知，该材料性能特别好[1]。"},
            "glossary": {"terms": [{"term_id": "T1", "preferred_zh": "钝化层", "forbidden_variants": ["钝化膜"]}]},
            "output_contract": {"case_id": "intake-001", "polished_text": None},
        }
        case_path = tmp / "case.json"
        case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        work = tmp / "work"
        with contextlib.redirect_stdout(io.StringIO()):
            rc = harbor_case.cmd_init(argparse.Namespace(case=str(case_path), work=str(work)))
        assert rc == 0
        brief = json.loads((work / "case_brief.json").read_text(encoding="utf-8"))
        assert brief["genre"] == "thesis_dissertation", brief["genre"]
        assert brief["text_provenance"] == ["$.input.manuscript"], brief["text_provenance"]
        assert brief["glossary_term_count"] == 1
        assert (work / "original.txt").read_text(encoding="utf-8").startswith("众所周知")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_harbor_packaging() -> None:
    tmp = _temp_dir()
    try:
        tdir = tmp
        pol_p = tdir / "polished.txt"
        log_p = tdir / "edit_log.json"
        aud_p = tdir / "audit.json"
        out_dir = tdir / "output"
        pol_p.write_text("Polished academic text [1].", encoding="utf-8")
        log_p.write_text(json.dumps([
            {
                "edit_id": "E001",
                "location": "S1",
                "original": "Raw academic text [1].",
                "revised": "Polished academic text [1].",
                "edit_type": "REGISTER",
                "review_tier": "B_STYLE_REGISTER",
                "rationale": "Improved register.",
                "requires_human_confirmation": True,
            }
        ]), encoding="utf-8")
        aud_p.write_text(json.dumps({"overall_passed": True, "modules": {}}), encoding="utf-8")

        res = package_outputs(
            case_json_path=SCRIPT_DIR.parent / "examples" / "sample_case_input.json",
            polished_path=pol_p,
            edit_log_path=log_p,
            audit_report_path=aud_p,
            output_dir=out_dir,
        )
        assert res["case_id"] == "illustrative-example-001"
        assert res["deliverable_type"] == "academic_language_polishing"
        assert res["human_review_flags"] and res["human_review_flags"][0]["edit_id"] == "E001"
        assert (out_dir / "result.json").exists()
        assert (out_dir / "edit_log.md").exists()
        assert (out_dir / "edit_log.csv").exists()
        assert (out_dir / "human_review_flags.md").exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    tests = [
        ("Positive EN Journal + LaTeX", test_positive_en_journal_latex),
        ("Positive ZH Thesis + SI Spacing + Non-False-Positive", test_positive_zh_thesis_and_si_spacing),
        ("Negative Anchor/Hedging/Negation/Conditional/Quantifier Drift", test_negative_anchor_hedging_negation_conditional_quantifier),
        ("Negative Glossary Conflict & EN/ZH Register", test_negative_glossary_conflict_and_register),
        ("Negative Unlogged-Edit Detection", test_negative_unlogged_edit_detection),
        ("Positive Contraction Negation Parity", test_positive_contraction_negation_parity),
        ("Negative Document-Level Hedge Loss", test_negative_document_level_hedge_loss),
        ("Harbor Case Intake (nested schema)", test_harbor_case_intake_nested_schema),
        ("Harbor Output Contract Packaging", test_harbor_packaging),
    ]
    for name, fn in tests:
        fn()
        print(f"[PASS] {name}")
    print(f"\nAll {len(tests)}/{len(tests)} self-tests passed.")


if __name__ == "__main__":
    main()
