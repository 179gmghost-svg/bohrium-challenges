# Scientific Literature Knowledge Graph Builder (`scientific-literature-kg-builder`)

A reusable, zero-external-dependency Python 3 Agent Skill built for **阅读15｜文献知识图谱构建** (`ARMI:2611.000032v5`) and Harbor / Bohrium Playground CLI evaluation.

## 1. Key Capabilities
- **Strict Source Isolation:** Parses `corpus-manifest.json`, `primary-material.json`, `secondary-material.json`, `material.json`, `secondary-publisher.xml`, and optional raw PDFs while guaranteeing primary-paper root metadata (`DOI`, `title`, `authors`) never leaks onto secondary papers, and duplicate serializations of the same paper are never counted as cross-paper evidence.
- **Multi-Backend PDF Extraction Fallback:** Automatically cascades `PyMuPDF (fitz)` → `pypdf` → `pdfplumber` → Poppler `pdftotext` (skipping blank-output backends and writing temp files strictly in the output directory rather than `%TEMP%`).
- **JATS Paragraph Provenance & Verbatim Quote Audit:** Binds every substantive node and edge to `(source_id, paragraph_id, quote, evidence_strength)`, rejects fabricated PDF page numbers in JATS-only corpora, and checks `page` vs. `para_id` consistency in PDF corpora.
- **Conservative Cross-Paper Alignment:** Normalizes safe aliases/abbreviations while blocking erroneous merges across guarded homonyms (`DFT`, `PCA`, `ML`, `SEM`, etc.), physical samples, datasets, experimental conditions, and numeric results—recording both `merged` and `kept_separate` decisions in `alignment_log`.
- **Incremental Updates with ID Preservation:** Integrates new papers without mutating existing node IDs, logging `update_history`, `change_records`, and `conflict_log`.
- **Harbor Contract Compliance:** Dynamically adapts to `output_contract` (list or dict with `required_fields` / `fields` / `required` / `keys` / `output_fields`), writes `/app/output/quality_audit.json`, and embeds `quality_audit` into `/app/output/result.json`.

## 2. Dependencies & Environment
- **Python:** 3.9+ standard library only (`json`, `re`, `hashlib`, `pathlib`, `argparse`, `subprocess`, `xml.etree.ElementTree`, `collections`).
- **Optional PDF backends:** `fitz` (PyMuPDF), `pypdf`, `pdfplumber`, or Poppler `pdftotext` CLI. Degrades gracefully and sets `needs_ocr_review: true` if no text layer is extractable.

## 3. Directory Structure (Root-Ready for Harbor & Playground CLI)
```text
.
├── SKILL.md                            # Core Agent Skill prompt, SKILL_DIR workflow & exception rules
├── README.md                           # Architecture, usage, methods, self-check & changelog
├── docs/
│   └── field_dictionary.md             # Field definitions, controlled vocabularies & ID rules
├── schemas/
│   └── kg_schema.json                  # Canonical JSON Schema (Draft 2020-12, v1.1.0)
├── references/
│   └── normalization_rules.json        # Entity normalization & homonym/non-merge guardrails
├── templates/
│   └── query_templates.json            # Parameterized scientific KG query templates
├── scripts/
│   ├── ingest_corpus.py                # Source-isolated corpus indexer, PDF fallback & dedup detector
│   ├── kg_engine.py                    # KG build, incremental update, query & Harbor export CLI
│   └── kg_validator.py                 # Automated provenance, quote, schema & contract auditor
└── examples/
    ├── run_minimal_example.py          # End-to-end runnable synthetic self-test (NOT a formal case)
    └── sample_output_result.json       # Illustrative synthetic output (NOT a formal case)
```

## 4. Quick Self-Check
Run the bundled illustrative self-test from the skill root directory:

```bash
python3 examples/run_minimal_example.py
```

Expected result: builds primary KG, incrementally merges secondary paper (merging canonical concepts, keeping a guarded `DFT` homonym separate, logging a 240 mV vs. 295 mV condition-scoped discrepancy), executes 4 queries (including 1 `undeterminable` path check), exports GraphML/JSON/Markdown + `result.json` + `quality_audit.json`, and exits `0` with `status == "PASS"`.

## 5. Limitations & Failure Handling
- Does not perform OCR on scanned image-only PDFs (flags `needs_ocr_review: true` and returns `undeterminable`/`refused` rather than guessing).
- Does not infer values from unprovided figure pixels or supplementary tables (logs them explicitly under `unreported_items`).
- Cross-paper alignment is intentionally conservative: ambiguous acronyms without full-form context remain separate and are logged in `alignment_log` and `conflict_log`.

## 6. Changelog (v1.1.0 — Harbor & Playground CLI Hardening)
- Removed placeholder `GITHUB_URL.txt` so the archive contains zero unreplaced placeholders and is ready for direct `--outputs` / `--skill` submission.
- Flattened zip root so `SKILL.md` sits directly at archive root after `Expand-Archive`.
- Updated `SKILL.md` to invoke all scripts/resources via `$SKILL_DIR` (`/skills/weekly-skill`), matching Harbor's `/app/work` working directory and exact `64` requests / `900s` budget.
- Added `docs/field_dictionary.md`, `change_records`, and `quality_audit` (`schemas/kg_schema.json` v1.1.0 + `/app/output/quality_audit.json`).
- Upgraded `scripts/ingest_corpus.py` with 4-tier PDF fallback (`fitz` → `pypdf` → `pdfplumber` → `pdftotext` with local temp file cleanup).
- Upgraded `scripts/kg_validator.py` and `scripts/kg_engine.py` with multi-shape `output_contract` compatibility (`list` or dict `required_fields`/`fields`/`required`/`keys`/`output_fields`), structured error codes, `PAGE_PARA_MISMATCH` checks, clean null omission, and `--audit-out` / `--embed-audit`.
