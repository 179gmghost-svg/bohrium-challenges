# Field Dictionary & Controlled Vocabularies

This document defines every field, controlled vocabulary, quote-alignment rule, and deterministic ID rule used by `scientific-literature-kg-builder`.

## 1. Top-Level `result.json` Fields

| Field | Type | Required | Description |
| :--- | :--- | :---: | :--- |
| `case_id` | `string` | Yes | Must exactly match `case_id` in `/input/case.json`. |
| `status` | `enum` | Yes | One of `success`, `partial`, `undeterminable`, `refused`. |
| `sources` | `array<Source>` | Yes | Independent source papers with isolated metadata (`doi`, `title`, `authors`, `license`, `source_hash`, `location_type`). |
| `knowledge_graph` | `object` | Yes | Contains `node_count`, `edge_count`, `nodes`, and `edges`. |
| `alignment_log` | `array<AlignmentDecision>` | Yes | Explicit log of cross-paper `merged` and `kept_separate` decisions. |
| `conflict_log` | `array<ConflictRecord>` | Yes | Explicit log of metric discrepancies, directional contradictions, homonym collisions, and intra-source conflicts. |
| `update_history` | `array<object>` | Yes | Incremental update audit trail (`added_nodes`, `merged_nodes`, `kept_separate_count`, `added_edges`). |
| `query_results` | `array<QueryResult>` | Yes | At least 3 executed queries with subgraphs, provenance chains, and `undeterminable_reason` when applicable. |
| `unreported_items` | `array<object>` | Yes | Explicitly lists requested or domain-relevant items absent from the provided text (e.g., unprovided figure pixels or supplements). |
| `change_records` | `array<ChangeRecord>` | Yes | Records any post-extraction repairs or manual adjustments (`{change, reason, at}`). Empty array `[]` if no repairs were needed. |
| `quality_audit` | `object` | Yes | Summary written by `kg_validator.py` (`status`, `error_count`, `warning_count`, `quotes_verified`, `quotes_total`, `contract_fields`). |
| `warnings` | `array<string>` | Yes | Non-fatal ingestion or validation warnings (e.g., duplicate-format detection). |
| `artifacts` | `array<string>` | Yes | List of companion files written to `/app/output/`. |

Additional keys specified dynamically in `/input/case.json -> output_contract` (whether `output_contract` is a list or a dict using `required_fields`, `fields`, `required`, `keys`, or `output_fields`) are automatically populated and verified.

---

## 2. Controlled Vocabularies

### 2.1 Entity Types (`Node.type`)
- `Researcher`: Named author, research group, or attributed investigator.
- `Material`: Chemical compound, catalyst, alloy, polymer, biological specimen, or physical substrate.
- `Method`: Experimental protocol, computational algorithm, model architecture, or analytical technique.
- `Task`: Scientific problem, reaction, benchmark task, or clinical/engineering objective.
- `Metric`: Quantitative evaluation measure or physical property (e.g., overpotential, F1, yield).
- `Conclusion`: Explicit scientific finding or claim stated by authors.
- `Dataset`: Named corpus, benchmark split, or experimental dataset.
- `Condition`: Explicit experimental or computational boundary condition (electrolyte, temperature, pressure, sample size).

### 2.2 Entity Scopes (`Node.scope`)
- `concept_class`: General reusable scientific concept eligible for conservative cross-paper alignment.
- `paper_specific_instance`: Model checkpoint, study cohort, or method variant unique to one paper (**never merged across papers**).
- `experimental_sample`: Physical batch or specimen unique to one paper (**never merged across papers**).
- `metric_observation`: Paper-specific numeric measurement or conclusion (**never merged across papers**).

### 2.3 Relation Types (`Edge.relation`)
- `USES`: Entity A employs method, material, or dataset B.
- `COMPARES`: Paper compares entity A against entity B (including cross-paper protocol comparisons).
- `OUTPERFORMS`: Entity A achieves better performance than B under stated `conditions`.
- `MEASURES`: Method or study measures metric B.
- `SUPPORTS`: Evidence or finding A corroborates conclusion/hypothesis B.
- `CONTRADICTS`: Evidence or finding A conflicts with conclusion/claim B.
- `DERIVES_FROM`: Method, model, or material A is derived from or modifies B.
- `APPLIES_TO`: Material or method A is applied to task, dataset, or substrate B.

### 2.4 Claim Origin (`Edge.claim_origin`)
- `author_primary`: Directly measured, computed, or concluded by the paper's own authors.
- `cited_or_paraphrased`: Attributed to prior work in Background / Related Work / Discussion.
- `speculative`: Hedged hypothesis, future-work conjecture, or unverified suggestion.

### 2.5 Evidence Strength (`Provenance.evidence_strength`)
- `direct_experimental`: Directly supported by experimental/empirical measurement in the paper.
- `direct_textual`: Directly stated in Methods/Results/Abstract text without ambiguity.
- `secondary_citation`: Quoted or paraphrased from another cited work.
- `inferred_weak`: Weak indirect link (avoid creating edges at this level unless explicitly flagged).

### 2.6 Conflict Types (`ConflictRecord.conflict_type`)
- `metric_discrepancy`: Different numerical values reported for the same pair/relation (often under different conditions).
- `directional_contradiction`: Simultaneous `SUPPORTS` and `CONTRADICTS` relations for the same pair.
- `homonym_collision`: Shared acronym/surface form (e.g., `DFT`) with distinct or ambiguous domain senses.
- `condition_mismatch`: Apparent disagreement attributable to differing experimental or evaluation conditions.
- `intra_source_conflict`: Internal inconsistency detected within a single paper.

---

## 3. Quote Alignment & Location Rules

1. **Normalization for Verbatim Verification:** Both the cited `quote` and the target paragraph text in `corpus_index.json` are normalized by collapsing consecutive whitespace (`\s+` → single space) and lowercasing before substring verification. A quote passes only if it is an exact normalized substring of the cited `(source_id, paragraph_id)`.
2. **JATS Paragraph IDs vs. PDF Pages:** When `has_pdf_pagination` is `false` (JATS/JSON corpus), `location_type` must be `"jats_paragraph_id"` and `paragraph_id` must match the organizer's exact paragraph ID. Any `page N`, `p. N`, or `pp. N` string in `paragraph_id` triggers a `FABRICATED_PDF_PAGE` error.
3. **PDF Page Consistency:** When `location_type == "pdf_page_extracted"`, `paragraph_id` follows `p{page}_b{block}` (e.g., `p2_b1`). If a numeric `page` attribute is also present, it must match the `p{page}` prefix (mismatch triggers `PAGE_PARA_MISMATCH`).

---

## 4. Deterministic ID & Incremental Preservation Rules

- **Node ID:** `N_<TYPE3>_<sha1(type|canonical_key[|scope|source_id])[:8]>`
  - For `concept_class` nodes, the hash excludes `source_id` so canonical concepts map deterministically.
  - For `paper_specific_instance`, `experimental_sample`, and `metric_observation` nodes, `scope` and `source_id` are included in the hash to guarantee isolation across papers.
- **Edge ID:** `E_<sha1(source|relation|target|source_id|conditions)[:8]>`
- **Incremental Stability:** During `kg_engine.py update`, existing node IDs in the base graph are **never mutated**. Merged secondary concepts adopt the base node's ID and append their aliases, `source_ids`, and deduplicated `provenance`.
