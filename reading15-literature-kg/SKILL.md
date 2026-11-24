---
name: scientific-literature-kg-builder
description: >-
  Evidence-grounded scientific literature knowledge graph (KG) construction,
  conservative cross-paper entity alignment, provenance binding (JATS paragraph
  IDs and verbatim quotes), incremental graph updating, and traceable querying
  for Harbor / Bohrium scientific reading tasks (阅读15｜文献知识图谱构建).
---

# Scientific Literature Knowledge Graph Builder (`scientific-literature-kg-builder`)

## 1. Purpose & Applicable Scope

This skill guides an agent inside Harbor (or any local workspace) to convert one or more scientific papers (structured JSON/JATS XML corpora or raw PDFs) into a **verifiable, queryable, provenance-bound scientific knowledge graph** and deliver `/app/output/result.json` alongside editable graph artifacts and an automated quality audit.

### Core Guarantees
1. **Accurate Extraction (抽得准):** Every node corresponds to an explicit scientific object in the source text (`Researcher`, `Material`, `Method`, `Task`, `Metric`, `Conclusion`, `Dataset`, `Condition`). Never hallucinate concepts or extrapolate from unprovided figure pixels, supplementary files, or external datasets.
2. **Accurate Relations (连得对):** Directed typed relations (`USES`, `COMPARES`, `OUTPERFORMS`, `MEASURES`, `SUPPORTS`, `CONTRADICTS`, `DERIVES_FROM`, `APPLIES_TO`) preserve direction, applicable conditions, and `claim_origin` (`author_primary`, `cited_or_paraphrased`, `speculative`). Co-occurrence alone never justifies an edge.
3. **Conservative Alignment (对得齐):** Cross-paper aliases and abbreviations are normalized via explicit rules while recording both **merge justifications** (`merged`) and **non-merge / conflict decisions** (`kept_separate`). Distinct physical samples, model checkpoints, datasets, experimental conditions, and numeric results from different papers are **never** collapsed into one claim.
4. **Queryable & Traceable (查得到、回得去):** Every substantive node and edge binds `source_id`, organizer JATS `paragraph_id` (never fabricated PDF page numbers), a verbatim `quote`, and `evidence_strength`. Executes ≥3 real queries with subgraph results, provenance chains, and explicit `undeterminable` reporting.
5. **Incremental Update (增量更新):** Integrating a secondary paper preserves all existing node IDs, records `update_history` and `change_records`, and exports clean JSON, GraphML, and Markdown reports.

---

## 2. Harbor Runtime Contract, Budget & Path Conventions

- **Skill Installation Directory (`SKILL_DIR`):** In Harbor, this skill is installed at `/skills/weekly-skill`. Because the agent's working directory is `/app/work`, **always invoke scripts and reference files via `$SKILL_DIR`** rather than relative paths:
  ```bash
  SKILL_DIR="${SKILL_DIR:-/skills/weekly-skill}"
  ```
- **Execution Budget:** `64` model requests, `900` seconds total wall time, `16,384` tokens per response (including reasoning). Keep intermediate steps concise and script-driven.
- **Runtime Inputs:** `/input/case.json`, `/input/task.md`, and case materials (`corpus-manifest.json`, `material.json`, `primary-material.json`, `secondary-material.json`, `secondary-publisher.xml`, or raw `.pdf` files).
- **Working Directory:** `/app/work` (store `corpus_index.json`, paper-scoped extractions, intermediate graphs, and query specs here).
- **Outputs (`/app/output/`):**
  - `/app/output/result.json` — Must include `case_id`, `status`, all fields required by `output_contract` in `/input/case.json`, `knowledge_graph`, `alignment_log`, `conflict_log`, `query_results`, `change_records`, `quality_audit`, and `unreported_items`.
  - `/app/output/quality_audit.json` — Machine-readable audit report produced by `kg_validator.py`.
  - `/app/output/knowledge_graph.json` — Standalone canonical KG file.
  - `/app/output/knowledge_graph.graphml` — Standard GraphML XML for Gephi/Cytoscape/NetworkX.
  - `/app/output/knowledge_graph_report.md` — Human-readable summary with Mermaid diagram, alignment log, conflicts, and query results.
- **Bundled Skill Resources (under `$SKILL_DIR`):**
  - `$SKILL_DIR/scripts/ingest_corpus.py` — Source-isolated corpus indexer, XML formula reader, multi-backend PDF fallback (`fitz` → `pypdf` → `pdfplumber` → `pdftotext`), and duplicate-format detector.
  - `$SKILL_DIR/scripts/kg_engine.py` — Graph builder, conservative aligner, incremental updater, query engine, and Harbor packager.
  - `$SKILL_DIR/scripts/kg_validator.py` — Automated provenance, verbatim-quote, metadata-isolation, schema, and `output_contract` auditor.
  - `$SKILL_DIR/schemas/kg_schema.json` — Canonical JSON Schema (Draft 2020-12).
  - `$SKILL_DIR/docs/field_dictionary.md` — Complete field dictionary, controlled vocabularies, quote normalization, and ID deduplication rules.
  - `$SKILL_DIR/references/normalization_rules.json` — Abbreviation/symbol canonicalization & guarded homonym/non-merge rules.
  - `$SKILL_DIR/templates/query_templates.json` — Reusable scientific KG query templates.
  - `$SKILL_DIR/examples/` — Clearly labeled synthetic illustrative example and self-test runner (not a formal competition case).

---

## 3. Six-Stage Execution Workflow

### Stage 1: Ingest & Isolate Sources
Run `ingest_corpus.py` from `/app/work` using `$SKILL_DIR`:

```bash
SKILL_DIR="${SKILL_DIR:-/skills/weekly-skill}"
python3 "$SKILL_DIR/scripts/ingest_corpus.py" \
  --input-dir /input \
  --output /app/work/corpus_index.json
```

**Mandatory Isolation Rules:**
- Read `corpus-manifest.json` first to enumerate independent `source_id` entries, DOIs, authors, source hashes, and licenses.
- Root-level `DOI`, `title`, and `authors` in `/input/case.json` or `primary-material.json` belong **strictly to the primary paper** and must **never** be copied onto `secondary-material.json`.
- Anchor locations to organizer **JATS `paragraph_id`** values (`location_type: "jats_paragraph_id"`). **Never** fabricate PDF page numbers (e.g., never label `page 1` when `has_pdf_pagination` is `false`).
- If `secondary-publisher.xml` is present, verify linearized inline formulas, subscripts, and superscripts against its XML snippets.
- If `duplicate_source_flags` flags two files as duplicate serializations of the same paper (identical DOI or ≥0.90 Jaccard lexical overlap), deduplicate them—never count them as cross-paper evidence.

### Stage 2: Extract Paper-Scoped Entities & Relations
Read `/input/task.md`, `/input/case.json`, and `/app/work/corpus_index.json`. Produce separate extraction files per independent paper (`/app/work/extract_primary.json`, `/app/work/extract_secondary.json`) strictly following `$SKILL_DIR/docs/field_dictionary.md` and `$SKILL_DIR/schemas/kg_schema.json`:

- **Entity Types:** `Researcher`, `Material`, `Method`, `Task`, `Metric`, `Conclusion`, `Dataset`, `Condition`.
- **Relation Types:** `USES`, `COMPARES`, `OUTPERFORMS`, `MEASURES`, `SUPPORTS`, `CONTRADICTS`, `DERIVES_FROM`, `APPLIES_TO`.
- **Mandatory Provenance on Every Substantive Node & Edge:**
  ```json
  {
    "source_id": "primary",
    "paragraph_id": "p-004",
    "location_type": "jats_paragraph_id",
    "quote": "exact short verbatim substring from paragraph p-004",
    "evidence_strength": "direct_experimental"
  }
  ```
- **Claim Origin on Every Edge:** `author_primary` | `cited_or_paraphrased` | `speculative`.
- **Scope Boundaries:** List unprovided image-pixel values, supplementary tables, or missing experimental parameters explicitly under `unreported_items`.

### Stage 3: Build Base Graph & Run Incremental Cross-Paper Update
```bash
python3 "$SKILL_DIR/scripts/kg_engine.py" build \
  --extraction /app/work/extract_primary.json \
  --rules "$SKILL_DIR/references/normalization_rules.json" \
  --output /app/work/kg_primary.json

python3 "$SKILL_DIR/scripts/kg_engine.py" update \
  --base-graph /app/work/kg_primary.json \
  --extraction /app/work/extract_secondary.json \
  --rules "$SKILL_DIR/references/normalization_rules.json" \
  --output /app/work/kg_merged.json
```

**Conservative Alignment Policy:**
- **Merge (`merged`)** only when two `concept_class` entities share a compatible type and canonical key (or safe synonym in `normalization_rules.json`) with no homonym collision; always preserve the existing node ID and log a `merge_justification`.
- **Keep Separate (`kept_separate`)** whenever entities are guarded homonyms (`DFT`, `PCA`, `ML`, `SEM`, etc.) with distinct or unresolved senses, or represent paper-specific physical samples, model checkpoints, datasets, conditions, or numeric results (`paper_specific_instance`, `experimental_sample`, `metric_observation`).

### Stage 4: Execute ≥3 Traceable Graph Queries
Build `/app/work/queries.json` incorporating any questions from `/input/task.md` plus at least 3 templates from `$SKILL_DIR/templates/query_templates.json` (including a cross-paper comparison, a conflict/evidence audit, and an undeterminable-relation boundary check):

```bash
python3 "$SKILL_DIR/scripts/kg_engine.py" query \
  --graph /app/work/kg_merged.json \
  --queries /app/work/queries.json \
  --output /app/work/query_results.json
```

### Stage 5: Export Harbor Artifacts & Initial `/app/output/result.json`
```bash
python3 "$SKILL_DIR/scripts/kg_engine.py" export \
  --graph /app/work/kg_merged.json \
  --query-results /app/work/query_results.json \
  --case-json /input/case.json \
  --corpus-index /app/work/corpus_index.json \
  --output-dir /app/output
```

### Stage 6: Mandatory Automated Audit & Self-Repair
Run `kg_validator.py` with `--case-json`, `--schema`, and `--audit-out` (which also embeds the `quality_audit` summary into `/app/output/result.json` when `--embed-audit` is passed):

```bash
python3 "$SKILL_DIR/scripts/kg_validator.py" \
  --result /app/output/result.json \
  --graph /app/output/knowledge_graph.json \
  --corpus-index /app/work/corpus_index.json \
  --case-json /input/case.json \
  --schema "$SKILL_DIR/schemas/kg_schema.json" \
  --audit-out /app/output/quality_audit.json \
  --embed-audit
```

If exit code ≠ `0`, inspect the structured error codes in `/app/output/quality_audit.json`, fix the root cause, log any substantive adjustment in `change_records`, re-export, and re-run Stage 6 until `status == "PASS"` with `0` errors.

---

## 4. Exception & Edge-Case Handling

| Condition | Required Action | Result `status` |
| :--- | :--- | :--- |
| Missing secondary paper or partial corpus | Build KG from available source(s), log missing files in `warnings` and `unreported_items`, skip cross-paper merge cleanly | `partial` |
| Duplicate serialization of same paper | Flag via DOI/Jaccard overlap in `ingest_corpus.py`; deduplicate to one `source_id`; never claim cross-paper evidence | `partial` or `success` (with warning) |
| Unparseable / scanned PDF without text layer | Fallback chain `fitz` → `pypdf` → `pdfplumber` → `pdftotext`; if all yield blank text, set `needs_ocr_review: true` and do not hallucinate | `refused` or `undeterminable` |
| Homonym / ambiguous abbreviation | Keep nodes separate (`kept_separate`), log senses and quotes in `alignment_log` and `conflict_log` | `success` |
| Conflicting numeric metrics or directional claims | Preserve both edges/values with conditions and provenance; record entry in `conflict_log` | `success` |
| Empty query result / missing relation | Return `status: "undeterminable"` for that query with explicit `undeterminable_reason`; never invent a bridge edge | `success` |
| Unprovided figure pixels or supplementary tables | List explicitly in `unreported_items` as out-of-scope; never extrapolate values | `success` |
