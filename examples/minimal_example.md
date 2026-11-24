# Minimal Invocation Example（最小调用示例）

> **声明**：以下输入、调用与输出均为**最小示意示例（Illustrative Example）**，仅用于展示本 Skill 的接口规范与完整处理流程，**不冒充任何正式评测案例结果**。

---

## 1. Illustrative Input（示意输入）

- **目标文体**：`journal_article`（英文期刊论文 Results & Discussion 片段）
- **术语表约束**：`electrochemical impedance spectroscopy (EIS)`；禁用 `AC impedance spectra`。
- **待润色原文（Original）**：

```text
With the rapid development of lithium-ion batteries, the interfacial resistance play a very important role in rate capability [1]. In this work, AC impedance spectra was measured at 25 °C (Fig. 1a), and the charge-transfer resistance decreased from 42.3 ± 1.2 Ω to 18.6 ± 0.8 Ω (p < 0.01). These results may suggest that the coating is associated with improved Li+ transport, which is very good for cycling stability.
```

---

## 2. Invocation Steps（调用方式）

1. 提取锚点：`python3 scripts/extract_anchors.py --input original.txt --output anchors.json`
2. Agent 按 `SKILL.md` Phase 2 执行分句级最小编辑并生成 `polished.txt` 与 `edit_log.json`。
3. 自动五模块回扫：`python3 scripts/verify_polish.py --original original.txt --polished polished.txt --edit-log edit_log.json --glossary glossary.json --genre journal_article --output verification_audit.json`
4. 打包输出：`python3 scripts/package_result.py --case-json examples/sample_case_input.json --polished polished.txt --edit-log edit_log.json --audit verification_audit.json --output-dir ./demo_output`

---

## 3. Illustrative Output（示意输出）

### A. 润色后完整文本（Polished Manuscript）

```text
In lithium-ion batteries, interfacial resistance plays a critical role in determining rate capability [1]. In this work, electrochemical impedance spectroscopy (EIS) was performed at 25 °C (Fig. 1a), and the charge-transfer resistance decreased from 42.3 ± 1.2 Ω to 18.6 ± 0.8 Ω (p < 0.01). These results may suggest that the coating is associated with improved Li+ transport, which is favorable for cycling stability.
```

### B. 逐句修改说明（Sentence-Level Edit Log）

| Edit ID | 位置 | 修改类型 | 复核分级 | 原文（Original） | 改文（Revised） | 修改理由（Rationale） | 需人工确认 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| E001 | S1 | CHINGLISH | B_STYLE_REGISTER | With the rapid development of lithium-ion batteries, the interfacial resistance play a very important role in rate capability [1]. | In lithium-ion batteries, interfacial resistance plays a critical role in determining rate capability [1]. | 消除中式英语套话 “With the rapid development of” 与 “play a very important role”，同时修正主谓一致（resistance plays）并保留引用 [1]。 | 否 |
| E002 | S2 | TERMINOLOGY | A_SAFE_MECHANICAL | AC impedance spectra was measured at 25 °C (Fig. 1a) | electrochemical impedance spectroscopy (EIS) was performed at 25 °C (Fig. 1a) | 按术语表将禁用变体 “AC impedance spectra” 统一为首次展开形式 “electrochemical impedance spectroscopy (EIS)”，修正动宾搭配并完整保留 25 °C 与 Fig. 1a。 | 否 |
| E003 | S3 | REGISTER | B_STYLE_REGISTER | which is very good for cycling stability. | which is favorable for cycling stability. | 将口语化评价词 “very good” 替换为客观学术表达 “favorable”，同时完整保留前文限定词 “may suggest” 与相关性表述 “is associated with”。 | 否 |

### C. 自动化校验摘要（Verification Audit Summary）

- `overall_passed`: `true`
- `anchor_mismatches`: `0`（`[1]`、`25 °C`、`Fig. 1a`、`42.3 ± 1.2`、`18.6 ± 0.8`、`p < 0.01` 全部零漂移）
- `hedging_warnings`: `0`（`may suggest` 与 `associated with` 限定强度与相关性边界完全守恒）
- `forbidden_variant_hits`: `0`；`register_issues`: `0`
