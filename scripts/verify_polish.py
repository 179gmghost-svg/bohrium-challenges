#!/usr/bin/env python3
"""Deterministic 5-Module Verification Suite for Academic Language Polishing (v2.0).

Audits (original, polished, edit_log, glossary) across:
1. Immutable Anchor Preservation (numbers, units, stats, citations, refs, LaTeX math/labels)
2. Epistemic Hedging, Causal-vs-Correlational, Negation Scope, Conditional & Quantifier Conservation
3. Glossary Conflict Detection & Terminology / Abbreviation Consistency Sweep
4. EN/ZH Register, Promotional Hype, Oral Fillers & Chinglish Lint
5. Edit-Log Completeness, Unlogged-Edit Detection & Minimal-Edit Ratio
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import difflib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from extract_anchors import extract_anchors

SKILL_ROOT = Path(__file__).resolve().parent.parent
LEXICON_PATH = SKILL_ROOT / "references" / "hedging_lexicon.json"
TAXONOMY_PATH = SKILL_ROOT / "references" / "edit_taxonomy.json"

REQUIRED_EDIT_FIELDS = (
    "edit_id",
    "location",
    "original",
    "revised",
    "edit_type",
    "review_tier",
    "rationale",
    "requires_human_confirmation",
)

CONTRACTIONS_RE = re.compile(
    r"\b(?:don't|doesn't|didn't|can't|couldn't|won't|wouldn't|shouldn't|isn't|aren't|wasn't|weren't|haven't|hasn't|hadn't|it's|that's|there's|we're|they're|you're|I'm)\b",
    re.IGNORECASE,
)

SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z0-9\\$\u4e00-\u9fff])")

APOSTROPHE_RE = re.compile(r"[\u2018\u2019\u00b4`]")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_anchors(original: str, polished: str) -> dict[str, Any]:
    orig_report = extract_anchors(original)
    pol_report = extract_anchors(polished)
    diffs: list[dict[str, Any]] = []

    for category, orig_counts in orig_report["anchors"].items():
        pol_counts = pol_report["anchors"].get(category, {})
        all_keys = set(orig_counts.keys()) | set(pol_counts.keys())
        for key in sorted(all_keys):
            c_orig = orig_counts.get(key, 0)
            c_pol = pol_counts.get(key, 0)
            if c_orig != c_pol:
                diffs.append({
                    "category": category,
                    "token": key,
                    "original_count": c_orig,
                    "polished_count": c_pol,
                    "severity": "CRITICAL" if category in (
                        "latex_math_display", "latex_math_inline", "latex_labels",
                        "latex_citations", "numeric_citations", "author_year_citations",
                        "cross_refs", "stat_values"
                    ) else "HIGH",
                })

    return {
        "passed": len(diffs) == 0,
        "mismatch_count": len(diffs),
        "mismatches": diffs,
        "source_encoding_anomalies": orig_report["encoding_anomalies"],
        "polished_encoding_anomalies": pol_report["encoding_anomalies"],
    }


def _norm_apostrophes(text: str) -> str:
    """Normalize typographic apostrophes so `don’t`, `don't` and `don`t` compare equal."""
    return APOSTROPHE_RE.sub("'", text)


def _marker_pattern(word: str, lexicon: dict[str, Any]) -> str:
    """Build the regex for one epistemic marker.

    Reporting verbs such as `show`/`demonstrate` only carry evidential force in a
    complement clause ("shows that X"), so they are matched with a mandatory `that`.
    In attributive or descriptive use ("does not show hysteresis") they are ordinary
    verbs whose substitution must not be read as a change of claim strength.
    """
    claim_verbs = lexicon.get("claim_verbs_requiring_that", [])
    if word.lower() in {w.lower() for w in claim_verbs}:
        return rf"\b{re.escape(word.lower())}\s+that\b"
    return rf"\b{re.escape(word.lower())}\b"


def _find_tier_hits(text: str, lexicon: dict[str, Any]) -> dict[int, list[str]]:
    text = _norm_apostrophes(text)
    lower = text.lower()
    hits: dict[int, list[str]] = {}
    for _, tier_info in lexicon["tiers"].items():
        rank = tier_info["rank"]
        matched: list[str] = []
        for word in tier_info["en"]:
            if re.search(_marker_pattern(word, lexicon), lower):
                matched.append(word)
        for word in tier_info["zh"]:
            if word in text:
                matched.append(word)
        if matched:
            hits[rank] = sorted(set(matched))
    return hits


def _tier_counts(text: str, lexicon: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """Return {marker: (rank, occurrence_count)} for every epistemic marker in `text`."""
    text = _norm_apostrophes(text)
    lower = text.lower()
    found: dict[str, tuple[int, int]] = {}
    for _, tier_info in lexicon["tiers"].items():
        rank = tier_info["rank"]
        for word in tier_info["en"]:
            n = len(re.findall(_marker_pattern(word, lexicon), lower))
            if n:
                found[word] = (rank, n)
        for word in tier_info["zh"]:
            n = text.count(word)
            if n:
                found[word] = (rank, n)
    return found


def _compare_strength(orig: str, rev: str, lexicon: dict[str, Any]) -> dict[str, Any]:
    """Compare the epistemic marker profile of two spans.

    Returns a dict with `kind` in {None, HEDGING_WEAKENED, HEDGING_STRENGTHENED,
    ABSOLUTE_CLAIM_INTRODUCED, MARKER_SUBSTITUTION} plus the supporting evidence.
    A marker *substitution* at the same maximum tier is reported as advisory only.
    """
    o = _tier_counts(orig, lexicon)
    r = _tier_counts(rev, lexicon)
    if not o and not r:
        return {"kind": None}

    max_o = max((rank for rank, _ in o.values()), default=0)
    max_r = max((rank for rank, _ in r.values()), default=0)
    lost = {m: v for m, v in o.items() if r.get(m, (0, 0))[1] < v[1]}
    gained = {m: v for m, v in r.items() if o.get(m, (0, 0))[1] < v[1]}
    tot_o = sum(v[1] for v in o.values())
    tot_r = sum(v[1] for v in r.values())

    evidence = {
        "original_max_tier": max_o,
        "revised_max_tier": max_r,
        "lost_markers": {m: v[0] for m, v in lost.items()},
        "gained_markers": {m: v[0] for m, v in gained.items()},
    }

    if max_o == 0 and max_r >= 4:
        return {"kind": "ABSOLUTE_CLAIM_INTRODUCED", **evidence}
    if max_r > max_o:
        kind = "ABSOLUTE_CLAIM_INTRODUCED" if max_r >= 4 and max_o <= 1 else "HEDGING_STRENGTHENED"
        return {"kind": kind, **evidence}
    if max_r < max_o:
        return {"kind": "HEDGING_WEAKENED", **evidence}
    if tot_r < tot_o:
        return {"kind": "HEDGING_WEAKENED", **evidence}
    if tot_r > tot_o:
        return {"kind": "HEDGING_STRENGTHENED", **evidence}
    if o != r:
        return {"kind": "MARKER_SUBSTITUTION", **evidence}
    return {"kind": None, **evidence}


def _has_any(text: str, terms_en: list[str], terms_zh: list[str]) -> list[str]:
    text = _norm_apostrophes(text)
    lower = text.lower()
    found: list[str] = []
    for w in terms_en:
        if re.search(rf"\b{re.escape(w.lower())}\b", lower):
            found.append(w)
    for w in terms_zh:
        if w in text:
            found.append(w)
    return found


def audit_hedging(
    edit_log: list[dict[str, Any]],
    lexicon: dict[str, Any],
    original: str = "",
    polished: str = "",
) -> dict[str, Any]:
    """Check every edited span for epistemic, causal, negation, conditional, and quantifier conservation.

    Two independent channels are audited:
    * span level  -- each edit_log entry's original/revised pair (works even when the log is incomplete);
    * document level -- whole-text epistemic marker profile, catching silent weakening that never
      reached the edit log (the classic "整段重写后限定词消失" failure).
    """
    warnings: list[dict[str, Any]] = []
    advisory: list[dict[str, Any]] = []
    span_lost: set[str] = set()
    cc = lexicon["causal_vs_correlational"]
    neg = lexicon.get("negation_markers", {"en": [], "zh": []})
    cond = lexicon.get("conditional_markers", {"en": [], "zh": []})
    quant = lexicon.get("quantifier_tiers", {})

    for entry in edit_log:
        orig = str(entry.get("original", ""))
        rev = str(entry.get("revised", ""))
        if not orig or not rev or orig == rev:
            continue
        eid = entry.get("edit_id", "UNKNOWN")
        loc = entry.get("location", "")

        # 1. Epistemic strength tier check
        strength = _compare_strength(orig, rev, lexicon)
        span_lost.update(strength.get("lost_markers", {}).keys())
        if strength["kind"] in ("HEDGING_STRENGTHENED", "HEDGING_WEAKENED", "ABSOLUTE_CLAIM_INTRODUCED"):
            direction = "STRENGTHENED" if strength["kind"] != "HEDGING_WEAKENED" else "WEAKENED"
            warnings.append({
                "edit_id": eid,
                "location": loc,
                "issue": strength["kind"],
                "original_max_tier": strength["original_max_tier"],
                "revised_max_tier": strength["revised_max_tier"],
                "lost_markers": strength["lost_markers"],
                "gained_markers": strength["gained_markers"],
                "message": f"Epistemic strength shifted ({direction}); verify the author's claim scope is preserved.",
            })
        elif strength["kind"] == "MARKER_SUBSTITUTION":
            advisory.append({
                "edit_id": eid,
                "location": loc,
                "issue": strength["kind"],
                "lost_markers": strength["lost_markers"],
                "gained_markers": strength["gained_markers"],
                "message": "Epistemic markers were substituted at the same strength tier; confirm the domain sense.",
            })

        # 2. Causal vs correlational drift
        orig_corr = _has_any(orig, cc["correlational_en"], cc["correlational_zh"])
        orig_caus = _has_any(orig, cc["causal_en"], cc["causal_zh"])
        rev_corr = _has_any(rev, cc["correlational_en"], cc["correlational_zh"])
        rev_caus = _has_any(rev, cc["causal_en"], cc["causal_zh"])

        if orig_corr and not orig_caus and rev_caus:
            warnings.append({
                "edit_id": eid,
                "location": loc,
                "issue": "CORRELATION_UPGRADED_TO_CAUSATION",
                "original_markers": orig_corr,
                "revised_markers": rev_caus,
                "message": "Original correlational phrasing was upgraded to causal phrasing.",
            })
        elif orig_caus and not orig_corr and rev_corr and not rev_caus:
            warnings.append({
                "edit_id": eid,
                "location": loc,
                "issue": "CAUSATION_DOWNGRADED_TO_CORRELATION",
                "original_markers": orig_caus,
                "revised_markers": rev_corr,
                "message": "Original causal phrasing was downgraded to correlational phrasing.",
            })

        # 3. Negation polarity parity check
        orig_neg = _has_any(orig, neg["en"], neg["zh"])
        rev_neg = _has_any(rev, neg["en"], neg["zh"])
        if bool(orig_neg) != bool(rev_neg):
            warnings.append({
                "edit_id": eid,
                "location": loc,
                "issue": "NEGATION_SCOPE_SHIFT",
                "original_markers": orig_neg,
                "revised_markers": rev_neg,
                "message": "Negation presence changed between original and revised span; verify polarity is preserved.",
            })

        # 4. Conditional boundary preservation check
        orig_cond = _has_any(orig, cond["en"], cond["zh"])
        rev_cond = _has_any(rev, cond["en"], cond["zh"])
        if orig_cond and not rev_cond:
            warnings.append({
                "edit_id": eid,
                "location": loc,
                "issue": "CONDITIONAL_BOUNDARY_DROPPED",
                "original_markers": orig_cond,
                "revised_markers": rev_cond,
                "message": "A conditional qualifier (e.g., 'if', 'unless', '若') present in the original was dropped.",
            })

        # 5. Quantifier scope drift (partial <-> universal)
        orig_part = _has_any(orig, quant.get("partial_en", []), quant.get("partial_zh", []))
        orig_univ = _has_any(orig, quant.get("universal_en", []), quant.get("universal_zh", []))
        rev_part = _has_any(rev, quant.get("partial_en", []), quant.get("partial_zh", []))
        rev_univ = _has_any(rev, quant.get("universal_en", []), quant.get("universal_zh", []))
        if orig_part and not orig_univ and rev_univ:
            warnings.append({
                "edit_id": eid,
                "location": loc,
                "issue": "QUANTIFIER_OVERGENERALIZED",
                "original_markers": orig_part,
                "revised_markers": rev_univ,
                "message": "Partial quantifier (e.g., 'some/few/部分') was overgeneralized to universal ('all/every/所有').",
            })

    document_level: dict[str, Any] = {"checked": False}
    if original and polished and original != polished:
        doc = _compare_strength(original, polished, lexicon)
        document_level = {
            "checked": True,
            "classification": doc.get("kind"),
            "original_max_tier": doc.get("original_max_tier"),
            "revised_max_tier": doc.get("revised_max_tier"),
            "lost_markers": doc.get("lost_markers", {}),
            "gained_markers": doc.get("gained_markers", {}),
        }
        if doc.get("kind") == "HEDGING_WEAKENED":
            unexplained = {m: r for m, r in doc["lost_markers"].items() if m not in span_lost}
            document_level["unexplained_lost_markers"] = unexplained
            if unexplained:
                warnings.append({
                    "edit_id": "DOCUMENT",
                    "location": "whole_text",
                    "issue": "DOC_HEDGING_WEAKENED",
                    "severity": "document_level",
                    "lost_markers": unexplained,
                    "gained_markers": doc["gained_markers"],
                    "message": (
                        "The whole-text epistemic profile lost hedging markers that no logged edit explains; "
                        "this is the classic silent weakening caused by paragraph-level rewriting."
                    ),
                })
        elif doc.get("kind") in ("HEDGING_STRENGTHENED", "ABSOLUTE_CLAIM_INTRODUCED"):
            advisory.append({
                "edit_id": "DOCUMENT",
                "location": "whole_text",
                "issue": f"DOC_{doc['kind']}",
                "severity": "document_level",
                "lost_markers": doc["lost_markers"],
                "gained_markers": doc["gained_markers"],
                "message": "The whole-text epistemic profile became stronger; confirm this was intended.",
            })
        elif doc.get("kind") == "MARKER_SUBSTITUTION":
            advisory.append({
                "edit_id": "DOCUMENT",
                "location": "whole_text",
                "issue": "DOC_MARKER_SUBSTITUTION",
                "severity": "document_level",
                "lost_markers": doc["lost_markers"],
                "gained_markers": doc["gained_markers"],
                "message": "Same-tier epistemic markers were swapped across the document; confirm the domain sense.",
            })

    return {
        "passed": len(warnings) == 0,
        "warning_count": len(warnings),
        "warnings": warnings,
        "advisory_count": len(advisory),
        "advisory": advisory,
        "document_level": document_level,
    }


def audit_glossary_and_abbreviations(
    polished: str, glossary: dict[str, Any] | None
) -> dict[str, Any]:
    """Detect internal glossary conflicts, leftover forbidden variants, and undefined first-use abbreviations."""
    conflicts: list[dict[str, Any]] = []
    forbidden_hits: list[dict[str, Any]] = []
    abbrev_issues: list[dict[str, Any]] = []

    if glossary and isinstance(glossary.get("terms"), list):
        abbrev_map: dict[str, set[str]] = {}
        for item in glossary["terms"]:
            pref_en = str(item.get("preferred_en", "")).strip()
            pref_zh = str(item.get("preferred_zh", "")).strip()
            abbr = str(item.get("abbrev", "")).strip()
            if abbr:
                abbrev_map.setdefault(abbr, set()).add(pref_en or pref_zh)

        for abbr, targets in abbrev_map.items():
            if len(targets) > 1:
                conflicts.append({
                    "type": "GLOSSARY_ABBREV_CONFLICT",
                    "key": abbr,
                    "conflicting_targets": sorted(targets),
                    "message": f"Glossary defines abbreviation '{abbr}' with multiple conflicting expansions; flag for human confirmation.",
                })

        for item in glossary["terms"]:
            case_sens = bool(item.get("case_sensitive", False))
            flags = 0 if case_sens else re.IGNORECASE
            pref_en = item.get("preferred_en", "")
            pref_zh = item.get("preferred_zh", "")
            for bad in item.get("forbidden_variants", []):
                if not bad:
                    continue
                is_ascii = all(ord(c) < 128 for c in bad)
                pat = rf"\b{re.escape(bad)}\b" if is_ascii else re.escape(bad)
                matches = re.findall(pat, polished, flags=flags)
                if matches:
                    forbidden_hits.append({
                        "term_id": item.get("term_id", ""),
                        "forbidden_variant": bad,
                        "count": len(matches),
                        "preferred_en": pref_en,
                        "preferred_zh": pref_zh,
                    })

            abbr = str(item.get("abbrev", "")).strip()
            if abbr and item.get("define_on_first_use", True):
                use_matches = list(re.finditer(rf"\b{re.escape(abbr)}\b", polished))
                if use_matches:
                    def_pat = re.compile(rf"[（(]{re.escape(abbr)}[）)]")
                    def_match = def_pat.search(polished)
                    if not def_match:
                        abbrev_issues.append({
                            "abbrev": abbr,
                            "issue": "ABBREV_NEVER_DEFINED",
                            "message": f"Abbreviation '{abbr}' appears {len(use_matches)} time(s) without an explicit '(ABBR)' definition.",
                        })
                    elif use_matches[0].start() < def_match.start():
                        abbrev_issues.append({
                            "abbrev": abbr,
                            "issue": "ABBREV_USED_BEFORE_DEFINITION",
                            "message": f"Abbreviation '{abbr}' is used before its first '(ABBR)' definition.",
                        })

    return {
        "passed": not conflicts and not forbidden_hits and not abbrev_issues,
        "glossary_conflicts": conflicts,
        "forbidden_variant_hits": forbidden_hits,
        "abbreviation_issues": abbrev_issues,
    }


def audit_register_and_chinglish(
    polished: str, lexicon: dict[str, Any], genre: str
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    for m in CONTRACTIONS_RE.finditer(polished):
        issues.append({
            "type": "COLLOQUIAL_CONTRACTION",
            "match": m.group(0),
            "message": f"Colloquial contraction '{m.group(0)}' found in formal academic text ({genre}).",
        })

    lower = polished.lower()
    for hype in lexicon.get("promotional_hype_en", []):
        if re.search(rf"\b{re.escape(hype.lower())}\b", lower):
            issues.append({
                "type": "PROMOTIONAL_HYPE_EN",
                "match": hype,
                "message": f"Promotional/non-objective EN term '{hype}' detected.",
            })

    for zh_bad in lexicon.get("promotional_or_oral_zh", []):
        if zh_bad in polished:
            issues.append({
                "type": "PROMOTIONAL_OR_ORAL_ZH",
                "match": zh_bad,
                "message": f"Oral or overstated ZH academic expression '{zh_bad}' detected.",
            })

    for item in lexicon.get("chinglish_patterns_en", []):
        m = re.search(item["pattern"], polished, flags=re.IGNORECASE)
        if m:
            issues.append({
                "type": "CHINGLISH_PATTERN",
                "match": m.group(0),
                "suggestion": item["suggestion"],
            })

    return {
        "passed": len(issues) == 0,
        "issue_count": len(issues),
        "issues": issues,
    }


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in SENT_SPLIT_RE.split(text.strip()) if s.strip()]
    return parts


def audit_edit_log(
    original: str,
    polished: str,
    edit_log: list[dict[str, Any]],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    schema_errors: list[str] = []
    valid_types = set(taxonomy["edit_types"].keys())
    valid_tiers = set(taxonomy["review_tiers"].keys())
    unmatched_originals: list[str] = []
    unmatched_revisions: list[str] = []

    logged_rev_spans: list[str] = []
    for idx, entry in enumerate(edit_log):
        eid = entry.get("edit_id", f"index_{idx}")
        for field in REQUIRED_EDIT_FIELDS:
            if field not in entry or entry[field] is None or (isinstance(entry[field], str) and not entry[field].strip()):
                schema_errors.append(f"{eid}: missing or empty required field '{field}'")
        etype = entry.get("edit_type")
        if etype and etype not in valid_types:
            schema_errors.append(f"{eid}: invalid edit_type '{etype}'")
        tier = entry.get("review_tier")
        if tier and tier not in valid_tiers:
            schema_errors.append(f"{eid}: invalid review_tier '{tier}'")

        orig_span = str(entry.get("original", "")).strip()
        rev_span = str(entry.get("revised", "")).strip()
        if orig_span and orig_span not in original:
            unmatched_originals.append(eid)
        if rev_span and rev_span not in polished:
            unmatched_revisions.append(eid)
        if rev_span:
            logged_rev_spans.append(rev_span)

    # Reverse Unlogged-Edit Detection: check changed sentences in polished are covered by edit_log
    orig_sents = set(_split_sentences(original))
    pol_sents = _split_sentences(polished)
    unlogged_changed_sentences: list[str] = []
    for ps in pol_sents:
        if ps in orig_sents:
            continue
        covered = any((span in ps or ps in span) for span in logged_rev_spans)
        if not covered:
            unlogged_changed_sentences.append(ps[:100])

    similarity = difflib.SequenceMatcher(None, original, polished).ratio()
    tier_counts = Counter(e.get("review_tier", "UNKNOWN") for e in edit_log)
    type_counts = Counter(e.get("edit_type", "UNKNOWN") for e in edit_log)

    return {
        "passed": (
            len(schema_errors) == 0
            and len(unmatched_originals) == 0
            and len(unmatched_revisions) == 0
            and len(unlogged_changed_sentences) == 0
        ),
        "total_edits": len(edit_log),
        "schema_errors": schema_errors,
        "unmatched_original_spans": unmatched_originals,
        "unmatched_revised_spans": unmatched_revisions,
        "unlogged_changed_sentences": unlogged_changed_sentences,
        "text_similarity_ratio": round(similarity, 4),
        "minimal_edit_warning": similarity < 0.45 and len(original) > 80,
        "counts_by_tier": dict(tier_counts),
        "counts_by_type": dict(type_counts),
    }


def run_full_audit(
    original: str,
    polished: str,
    edit_log: list[dict[str, Any]],
    glossary: dict[str, Any] | None = None,
    genre: str = "journal_article",
) -> dict[str, Any]:
    lexicon = _load_json(LEXICON_PATH)
    taxonomy = _load_json(TAXONOMY_PATH)

    m1 = audit_anchors(original, polished)
    m2 = audit_hedging(edit_log, lexicon, original=original, polished=polished)
    m3 = audit_glossary_and_abbreviations(polished, glossary)
    m4 = audit_register_and_chinglish(polished, lexicon, genre)
    m5 = audit_edit_log(original, polished, edit_log, taxonomy)

    overall_passed = all(m["passed"] for m in (m1, m2, m3, m4, m5))
    return {
        "overall_passed": overall_passed,
        "genre": genre,
        "modules": {
            "1_anchor_preservation": m1,
            "2_hedging_conservation": m2,
            "3_glossary_and_abbreviations": m3,
            "4_register_and_chinglish": m4,
            "5_edit_log_completeness": m5,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify academic language polishing output.")
    parser.add_argument("--original", required=True, help="Path to original manuscript text.")
    parser.add_argument("--polished", required=True, help="Path to polished manuscript text.")
    parser.add_argument("--edit-log", required=True, help="Path to JSON array of edit log entries.")
    parser.add_argument("--glossary", help="Optional path to JSON glossary file.")
    parser.add_argument("--genre", default="journal_article", help="Target academic genre.")
    parser.add_argument("--output", help="Optional path to write JSON audit report.")
    args = parser.parse_args()

    original = Path(args.original).read_text(encoding="utf-8", errors="replace")
    polished = Path(args.polished).read_text(encoding="utf-8", errors="replace")
    edit_log = json.loads(Path(args.edit_log).read_text(encoding="utf-8"))
    glossary = json.loads(Path(args.glossary).read_text(encoding="utf-8")) if args.glossary else None

    report = run_full_audit(original, polished, edit_log, glossary, args.genre)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(encoded, encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
