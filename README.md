# Academic Language Polishing Skill（写作02｜学术语言润色）

## 1. Overview & Methodology（定位与核心方法）

本 Skill 面向科研论文、学位论文、基金申请书、审稿回复与中英文摘要的**学术语言润色**任务，采用 **“不可变锚点锁定 + 分句级最小编辑 + 五模块自动化回扫校验（Dual-Channel Polish & Audit）”** 架构，重点解决基础 Agent 在学术润色中常见的四大痛点：

1. **改得对**：消除语法、句法、搭配与标点硬错误，而非同义改写掩盖问题。
2. **说得像**：基于 `references/register_profiles.json` 严格匹配 5 类学术文体语域，清除口语缩写、宣传化词与中式英语直译腔。
3. **没改坏**：通过 `scripts/extract_anchors.py` 与 `scripts/verify_polish.py` 确定性锁定数值、单位、统计值、引用、图表指向与 LaTeX 公式，并对 4 级限定强度（Tentative → Moderate → Strong → Absolute）及相关性/因果性边界执行**逐句 + 全篇双通道**守恒校验，专门拦截“整段重写后限定词消失”这一类隐性削弱。
4. **讲得清**：输出完整可编辑润色稿 + 标准化逐句修改说明（`edit_log.md` / `edit_log.csv` / `result.json`），每条修改均含原文、改文、修改类型、三级复核标签（A/B/C）与理由。

---

## 2. Directory Structure & Requirements（目录结构与依赖）

```text
academic-language-polishing/
├── SKILL.md                           # Skill 主规范（含 YAML frontmatter 与 Harbor 运行契约）
├── README.md                          # 使用与方法说明（本文件）
├── references/
│   ├── register_profiles.json         # 5 类学术文体语域规则（期刊/学位/基金/审稿回复/双语摘要）
│   ├── edit_taxonomy.json             # 11 类标准修改标签 + A/B/C 三级人工复核分类
│   └── hedging_lexicon.json           # 中英文 4 级限定强度词典 + 因果/相关 + 中式英语检测库
├── templates/
│   └── glossary_template.json         # 可复用双语术语表 JSON 模板
├── scripts/
│   ├── harbor_case.py                 # Phase 0/3/4：案例读入 + 一条命令完成校验与打包
│   ├── extract_anchors.py             # Phase 1：不可变锚点提取与编码异常检测
│   ├── verify_polish.py               # Phase 3：五模块自动化回扫校验（含全篇限定词漂移）
│   ├── package_result.py              # Phase 4：Harbor result.json 与多格式产物打包
│   └── run_self_test.py               # 自动化功能与边界压力测试套件（9 项）
└── examples/
    ├── sample_case_input.json         # 最小 Harbor case.json 示意输入（非正式案例）
    └── minimal_example.md             # 完整最小调用示例与示意输出（非正式案例）
```

- **运行环境**：Python 3.9+（**纯标准库，零第三方 pip 依赖**，完全离线可运行）。
- **合规性**：全部为 UTF-8 文本文件，无软链接，总大小 < 120 KB（远低于 Harbor 50 文件 / 单文件 500 KB / 总计 2 MB 上限）。

---

## 3. Quick Start & Invocation（调用步骤）

### A. Agent / Harbor 自动调用
将本目录放置于 `/app/submission/`（Harbor 会自动挂载至 `/skills/weekly-skill`）。Agent 读取 `/input/case.json` 与 `task.md` 后，严格按 `SKILL.md` 的 Phase 0–4 执行并输出至 `/app/output/`。

最短运行路径（两条命令）：

```bash
python3 scripts/harbor_case.py init --case /input/case.json --work /app/work
# …… 按 Phase 2 写出 /app/work/polished.txt 与 /app/work/edit_log.json ……
python3 scripts/harbor_case.py finalize --case /input/case.json --work /app/work --output /app/output
```

`init` 只做定位与转写（正文、术语表、文体、`output_contract` 字段名），绝不补造内容；无法定位的字段写入 `case_brief.json` 的 `material_gaps` / `uncertainties`。`finalize` 退出码：`0` 通过，`2` 仍有阻塞项（产物已写出），`1` 输入缺失或非法。

### B. 命令行独立校验与打包
```bash
# 1. 提取原文不可变锚点
python3 scripts/extract_anchors.py --input original.txt --output anchors.json

# 2. 对润色稿与逐句修改表执行五模块回扫校验
python3 scripts/verify_polish.py \
  --original original.txt \
  --polished polished.txt \
  --edit-log edit_log.json \
  --glossary templates/glossary_template.json \
  --genre journal_article \
  --output verification_audit.json

# 3. 封装 Harbor 兼容输出（result.json + edit_log.md/csv + human_review_flags.md）
python3 scripts/package_result.py \
  --case-json examples/sample_case_input.json \
  --polished polished.txt \
  --edit-log edit_log.json \
  --audit verification_audit.json \
  --output-dir ./demo_output

# 4. 运行自测与负样本拦截测试
python3 scripts/run_self_test.py
```

---

## 4. Limitations & Failure Handling（限制与失败处理）

- **事实核查边界**：本 Skill 保证“不篡改原文已有事实与数据”，但不替代领域专家对原始实验数据真实性的外部核查；若原文存在逻辑矛盾或数据缺失，仅在 `human_review_flags.md` 中标注 `HUMAN_FLAG_ONLY`，绝不擅自补数。
- **规则词典覆盖边界**：`hedging_lexicon.json` 与 Chinglish 规则库覆盖高频学术表达；极细微的学科专有语用仍由 Agent 的分句审校与作者 C 级复核共同兜底。
- **失败分级报告**：遇到缺失材料、术语表冲突或文件解析异常时，在 `result.json` 中如实区分 `completed`、`partial_material_gap` 与 `failed` 状态，并记录具体阻塞项。

---

## 5. Maintenance & Reusability（复用与维护）

- 团队可直接替换或扩展 `templates/glossary_template.json` 与 `references/register_profiles.json` 以适配特定目标期刊（如 Nature/Science、IEEE、ACS、GB/T 7714 学位论文）。
- 任何规则扩展后，运行 `python3 scripts/run_self_test.py` 即可验证回归稳定性。
- 词典版本：`hedging_lexicon.json` 2.2.0、`edit_taxonomy.json` 1.0.0。修改词典只需保持 schema 不变，`verify_polish.py` 自动生效。

---

## 6. Changelog（版本记录）

| 版本 | 变更 |
| :--- | :--- |
| 2.2.0 | 新增全篇限定强度漂移通道（`DOC_HEDGING_WEAKENED`），可捕捉任何未被 `edit_log` 覆盖的限定词丢失；报告型动词（show/demonstrate/indicate 等）只在 `that` 从句位置计入限定强度，避免 `show → exhibit` 类动词替换被误判；否定词表补全缩写式（don't / doesn't / cannot 等）并统一弯引号；CJK 图表指向允许 `图2 / 图 2` 空格差异；新增 `scripts/harbor_case.py`（案例读入 + 一条命令校验打包）；`result.json` 的 `human_review_flags` 字段写入实际标记项；自测 5 项扩展至 9 项，含沙箱不可写 temp 目录的回退。 |
| 2.1.0 | 五模块回扫、锚点锁定、术语/缩写治理、异常处理矩阵、Harbor 输出契约打包。 |
