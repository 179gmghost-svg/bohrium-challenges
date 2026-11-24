---
name: academic-language-polishing
description: Dual-channel academic language polishing skill for peer-reviewed manuscripts, theses, grant proposals, peer-review rebuttals, and bilingual abstracts. Fixes grammar, syntax, collocation, Chinglish, and terminology drift via sentence-level minimal edits while deterministically locking numerical/citation/LaTeX anchors, conserving epistemic hedging/negation/conditional/quantifier boundaries at edit-span and whole-document level, sweeping glossary consistency, catching unlogged edits, and producing auditable edit logs and Harbor-compliant outputs.
---

# Academic Language Polishing（学术语言润色）

## 1. Purpose & Trigger Boundaries（用途与触发边界）

### When to Trigger（适用场景）
Use this skill whenever the task requests **academic language polishing, proofreading, copy-editing, register alignment, Chinglish elimination, bilingual abstract alignment, or cross-section terminology/abbreviation unification** on:
- Journal manuscripts (plain text, Markdown, LaTeX `.tex`, DOCX, or PDF-extracted drafts)
- Theses / dissertations (Chinese or English)
- Grant proposals (NSFC, NIH, ERC, etc.)
- Peer-review responses / rebuttals
- Bilingual academic abstracts (ZH/EN)

### When NOT to Trigger（禁止擅自触发）
Do **NOT** invoke this skill or silently rewrite user text when the request is:
- Pure factual Q&A, literature explanation, or concept clarification
- Asking for high-level structural feedback or peer-review critique without requesting text edits
- Creative writing, marketing copy, or casual correspondence

If the user's intent is ambiguous (e.g., pasted a paragraph without specifying whether to explain or polish), ask or keep edits strictly bounded rather than rewriting unprompted.

---

## 2. Core Principles（四大质量铁律）

Every polishing run must satisfy all four evaluation pillars:
1. **改得对（Correctness）**：真正修正语法（主谓一致、时态语态、冠词介词、单复数）、句法（悬垂修饰、长句断句、平行结构）、学术搭配与标点硬错误，而不是换一种同样别扭的说法掩盖问题。
2. **说得像（Register & Consistency）**：严格匹配目标文体与语域（见 `references/register_profiles.json`），消除口语缩写、中英文宣传化形容词/口语套话与中式英语直译腔；全篇统一术语表及缩写首次出现规范 `Full Name (ABBR)`。
3. **没改坏（Semantic & Anchor Fidelity）**：零丢失、零篡改数值、单位、统计检验值（`p`、`R^2`、`n`、`SD`、`CI`）、引用编号/键值（`[1]`、`\cite{}`）、图表公式指向（`Fig. 1`、`Table 2`、`\ref{}`）及 LaTeX 数学块；严格守恒 4 级限定强度（Tentative / Moderate / Strong / Absolute）、相关性与因果性边界、否定极性、条件从句与量词范围，绝不擅自拔高或削弱作者结论。
4. **讲得清（Auditability）**：交付**完整可编辑润色稿 + 逐句修改说明表**；每处修改均标注 `edit_id`、位置、原文、改文、标准修改类型（`references/edit_taxonomy.json`）、三级复核标签（A 机械修正 / B 语域优化 / C 需人工确认）与清晰理由，并通过反向漏记检测确保零隐蔽改动。

---

## 3. Execution Workflow（双通道润色与校验流程）

Resolve paths relative to this skill directory (e.g. `/skills/weekly-skill` in Harbor runtime). All bundled scripts use **Python 3 standard library only** (zero external dependencies) and set `sys.dont_write_bytecode = True` to avoid generating binary `__pycache__` artifacts.

### Phase 0: Input Inspection & Triage（输入读取与边界检查）
0. **Fast path（推荐）**：`python3 scripts/harbor_case.py init --case /input/case.json --work /app/work` 会自动定位正文、术语表与文体，写出 `original.txt`、`glossary.json`、`genre.txt` 和 `case_brief.json`（含字段来源路径、缺失项与不确定性）。若该命令报错或 `material_gaps` 非空，再手工按下述步骤检查；`case_brief.json` 的结论必须在最终 `boundaries_and_uncertainty` 中如实转述。
1. In Harbor runtime, read `/input/case.json` and `task.md` (if present); store intermediate files in `/app/work` and final deliverables in `/app/output`. If input includes real PDF files, parse them directly with available PDF tools without inventing text.
2. Identify and record:
   - **Target scope**: specific sections or full manuscript
   - **Target genre/register**: map to `references/register_profiles.json` (`journal_article`, `thesis_dissertation`, `grant_proposal`, `peer_review_rebuttal`, `bilingual_abstract`). If unspecified, default to `journal_article` and log this assumption in `boundaries_and_uncertainty`.
   - **Glossary & style rules**: load user/case glossary if provided; normalize against `templates/glossary_template.json`.
   - **Material gaps & conflicts**: note missing sections, unreadable pages, missing units, or conflicting glossary definitions before editing.

### Phase 1: Immutable Anchor Lock（不可变锚点锁定）
Run the deterministic anchor extractor on the raw input manuscript before editing:
```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/extract_anchors.py \
  --input /app/work/original.txt \
  --output /app/work/anchors_original.json
```
Review `encoding_anomalies`, `anchors`, and `abbreviations`:
- Treat all extracted `latex_math_display`, `latex_math_inline`, `latex_labels`, `latex_citations`, `numeric_citations`, `author_year_citations`, `cross_refs`, `stat_values`, and `numbers_and_units` as **read-only immutable tokens** (SI spacing normalization such as `25°C` → `25 °C` is allowed).
- If `encoding_anomalies` is non-empty (e.g., `U+FFFD` or mojibake), record it in `human_review_flags` and do **not** guess corrupted numbers or proper nouns.

### Phase 2: Sentence-Level Minimal-Edit Polishing（分句级最小编辑润色）
Edit the manuscript **sentence by sentence** (not free-form paragraph rewriting), following:
1. **Minimal-Edit Rule**：优先做精准最小改动；除非原句存在严重中式英语直译腔或语法崩溃，否则保留作者原有句群结构与信息组织。
2. **Genre & Register Alignment**：依据 `references/register_profiles.json` 调整时态、人称、语态与客观措辞；清除英文口语缩写、中英文宣传化/口语词（如 `groundbreaking`, `very good`, `众所周知`, `特别好`）及中式英语套话（如 `with the rapid development of`, `more and more`）。
3. **Glossary & Abbreviation Enforcement**：
   - 将全文所有 `forbidden_variants` 统一替换为 `preferred_en` / `preferred_zh`。
   - 对需要首次展开的缩写，在首次出现处规范为 `Full Name (ABBR)` 或 `中文全称（ABBR）`，后续统一使用 `ABBR`。
   - 若术语表自身存在冲突（同一缩写或概念映射多个首选译法），**不得擅自裁决**，保留原文并在 `edit_log` 中用 `HUMAN_FLAG_ONLY` 标注待作者确认。
4. **Epistemic, Causal, Negation, Conditional & Quantifier Conservation**：
   - 对照 `references/hedging_lexicon.json` 的 4 级限定强度（Tentative → Moderate → Strong → Absolute）、相关性/因果性区分、否定极性、条件从句（`if/unless/若`）与量词（`some/all/部分/所有`），确保改写前后语义边界严格守恒。
5. **Structured Edit Log Construction**：
   - 将每一处修改写入 `/app/work/edit_log.json`（JSON 数组），每条记录必须包含：
     `edit_id`, `location`, `original`, `revised`, `edit_type`, `review_tier`, `rationale`, `requires_human_confirmation`。
   - `original` 必须是原文中可精确匹配的片段，`revised` 必须是润色稿中可精确匹配的片段，且所有被改动的句子均须被 `edit_log` 覆盖。
   - 一处修改对应一个 `edit_id`；若一句同时存在语法与语域问题，拆成两条（各写主类型），不要用一次整句重写把多个问题合并。

**逐句六项检查清单（每句依次过一遍，命中即改并记录）**

| # | 检查项 | 典型缺陷 | 允许的最小改法 | 禁止 |
| :- | :--- | :--- | :--- | :--- |
| 1 | 语法骨架 | 主谓不一致、时态漂移、单复数、冠词/介词缺失、悬垂修饰 | 只改出错成分（`play`→`plays`，`don't`→`do not`） | 借修语法整句重排 |
| 2 | 搭配与冗余 | 动名搭配生硬、名词化堆叠、`It is worth noting that` 类冗赘引导 | 换搭配或删引导语，保留主干（`show hysteresis`→`exhibit hysteresis`） | 删掉承载信息的成分 |
| 3 | 语域与人称 | 口语词、宣传化形容词、绝对化措辞、第一人称误用 | 换等强度客观词（`very good`→`favorable`）；作者原有的绝对化表述**不改**，标 `C_HUMAN_CONFIRM` | 把作者的强论断悄悄改弱，或把弱论断改强 |
| 4 | 术语与缩写 | 同义词漂移、禁用变体、缩写未首次展开 | 按术语表统一；首次出现写 `Full Name (ABBR)` | 自创新译名或缩写 |
| 5 | 不可变锚点 | 数值、单位、`±`、`p` 值、`n`、引用编号、图表/公式指向、LaTeX | 原样保留；仅允许 SI 空格规范化 | 四舍五入、换算、补全缺失单位、改引用编号 |
| 6 | 逻辑边界 | 限定强度、相关/因果、否定范围、条件从句、量词 | 原样保留；必要时用同档措辞 | 增删 `may/可能`、把 `associated with` 改成 `causes`、把 `部分` 改成 `所有` |

改完一句后回读：把改文单独读一遍，确认主语、信息重心与论断强度都与原句一致；不一致就退回上一版重改。

### Phase 3: Deterministic Dual-Channel Audit（改后自动化五模块回扫）
Run `scripts/verify_polish.py` on the polished draft and edit log:
```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_polish.py \
  --original /app/work/original.txt \
  --polished /app/work/polished.txt \
  --edit-log /app/work/edit_log.json \
  --glossary /app/work/glossary.json \
  --genre journal_article \
  --output /app/work/verification_audit.json
```
Inspect all 5 modules in `verification_audit.json`:
1. `1_anchor_preservation`: Must have `mismatch_count == 0` (any mismatch in numbers, units, stats, citations, cross-refs, or LaTeX math is a **hard blocker** — fix immediately).
2. `2_hedging_conservation`: Must have `warning_count == 0`. Two channels are reported: per-span warnings (`HEDGING_WEAKENED/STRENGTHENED`, `ABSOLUTE_CLAIM_INTRODUCED`, `NEGATION_SCOPE_SHIFT`, `CONDITIONAL_BOUNDARY_DROPPED`, `QUANTIFIER_OVERGENERALIZED`, `CORRELATION_UPGRADED_TO_CAUSATION`) and `document_level` `DOC_HEDGING_WEAKENED`, which catches hedging lost anywhere in the text that no edit entry accounts for. `advisory[]` entries (same-tier marker substitution, whole-text strengthening) must be judged and, if intentional, marked `C_HUMAN_CONFIRM` rather than silently kept.
3. `3_glossary_and_abbreviations`: Resolve all `forbidden_variant_hits` and `abbreviation_issues`; surface any `glossary_conflicts` to `human_review_flags`.
4. `4_register_and_chinglish`: Resolve all EN contractions, EN/ZH promotional hype or oral fillers, and Chinglish hits.
5. `5_edit_log_completeness`: Fix any missing schema fields, unmatched spans, or `unlogged_changed_sentences`; if `minimal_edit_warning` triggers (`text_similarity_ratio < 0.45`), check whether over-rewriting occurred.

Iterate Phase 2 → Phase 3 until `overall_passed == true` (or only unavoidable source-side conflicts/gaps remain, explicitly documented). Note that a *correct* fix can still be flagged: when the original sentence itself carries an overstated claim (e.g. 说明…可以完全抑制 without supporting statistics), keep the author's wording, log it as `HUMAN_FLAG_ONLY` with identical `original`/`revised`, and list it under `human_review_flags`.

### Phase 4: Harbor Output Packaging（结构化产物封装）
Fast path（Phase 3 + 4 一条命令，等价于下面两步）：
```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/harbor_case.py finalize \
  --case /input/case.json --work /app/work --output /app/output
```
退出码 `0` 表示 `overall_passed == true`，`2` 表示校验仍有阻塞项（产物已写出，需回到 Phase 2 修正），`1` 表示输入缺失或文件非法。手工分步执行时使用 `scripts/package_result.py`：
```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/package_result.py \
  --case-json /input/case.json \
  --polished /app/work/polished.txt \
  --edit-log /app/work/edit_log.json \
  --audit /app/work/verification_audit.json \
  --output-dir /app/output \
  --status completed
```
Verify `/app/output` contains:
- `result.json` (preserves all original `output_contract` fields and `case_id`, plus `status`, `polished_text`, `edit_log`, `verification_audit`, `boundaries_and_uncertainty`, `artifacts`)
- `polished_manuscript.md` (clean ready-to-use manuscript)
- `edit_log.md` and `edit_log.csv` (sentence-level auditable change table)
- `human_review_flags.md` (author sign-off items, material gaps, and conflicts)
- `verification_audit.json` (machine-verifiable audit trace)

---

## 4. Exception & Boundary Handling Matrix（异常处理规范）

| Exception Scenario | Detection Signal | Required Action |
| :--- | :--- | :--- |
| **超长文本（Long Manuscript）** | `char_count > 12000` or multi-chapter draft | Split by section/paragraph boundaries (never mid-sentence or mid-LaTeX environment); maintain a single shared glossary & abbreviation registry; run `verify_polish.py` on the **reassembled full document** to guarantee cross-section consistency. |
| **编码混乱 / 乱码（Encoding / Mojibake）** | `encoding_anomalies` non-empty in `extract_anchors.py` | Do not fabricate corrupted characters or digits. Preserve raw span, flag in `human_review_flags.md` and `boundaries_and_uncertainty`. |
| **公式 / 引用 / LaTeX 混杂** | `has_latex == true` | Keep `$...$`, `$$...$$`, `\cite{}`, `\ref{}`, `\label{}`, and environment tags verbatim; polish prose outside commands only; confirm zero anchor diff in Module 1. |
| **中英日混排（Mixed CJK / EN / JA）** | `has_cjk` + `has_japanese_kana` or bilingual text | Preserve intentional foreign proper nouns/citations; normalize fullwidth/halfwidth punctuation per primary target language; flag unclear code-switching for human review. |
| **术语表冲突（Glossary Conflict）** | `glossary_conflicts` non-empty in Module 3 | Do **not** silently pick one variant; preserve source text at conflicting spans, add `HUMAN_FLAG_ONLY` entry, and list conflicting targets in `conflicts`. |
| **目标文体不明（Unspecified Genre）** | Genre absent from `task.md` / `case.json` | Default to `journal_article` (neutral formal academic register) and record the default choice in `uncertainties`. |
| **材料缺失或无法判断（Material Gap）** | Missing referenced table/figure, truncated sentence, missing unit | Never invent missing data. Set `status: "partial_material_gap"` if core text is missing, or `"completed"` with explicit `material_gaps` entries if localized. |
| **工具/运行失败（Runtime Failure）** | Unreadable binary or script error | Report exact error stage and cause in `result.json` with `status: "failed"`, never fabricate outputs. |
| **沙箱/temp 目录不可写（Sandbox）** | `PermissionError` when a script writes a scratch file | Scripts are stdlib-only and write only to the paths passed on the command line; the self-test probes the temp dir and falls back to the current directory. Pass `--work`/`--output` under writable paths. |

---

## 5. Self-Check & Verification（自查验证方法）

Run the bundled self-test suite (requires Python 3.9+ stdlib only):
```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_self_test.py
```
All positive cases (EN journal LaTeX, ZH thesis, SI spacing & ZH scientific word non-false-positive, contraction-negation parity) and negative stress tests (anchor corruption, span- and document-level hedging/causal/negation/conditional/quantifier drift, glossary conflict, EN/ZH register violation, unlogged edit, nested case-schema intake) must pass before packaging. Current suite: 9/9.
