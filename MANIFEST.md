# Submission Manifest（提交清单）

本目录即参赛 Skill 本体。平台可将本目录内容安装到 `/app/submission/` 或 `/skills/weekly-skill`；
`SKILL.md` 是唯一入口，其余文件均为其依赖资源。

## 1. Package Metadata（包元数据）

| 项 | 值 |
| :--- | :--- |
| Skill 名称 | `academic-language-polishing` |
| 版本 | 2.2.0 |
| 运行环境 | Python 3.9+，仅标准库（无 pip 依赖，离线可运行） |
| 入口 | `SKILL.md`（YAML frontmatter：`name` / `description`） |
| 运行入口脚本 | `scripts/harbor_case.py`（读入与打包）、`scripts/verify_polish.py`（校验） |
| 依赖数据 | `references/*.json`（规则词典）、`templates/glossary_template.json`（术语表模板） |
| 文件数 | 13 |
| 总字节 | 114110（上限 2 MB） |
| 软链接 | 无 |

## 2. File Inventory（文件清单）

| 路径 | 字节 | SHA-256 |
| :--- | ---: | :--- |
| `examples/minimal_example.md` | 4017 | `7d5e441ba42381cff2904dad75bc2cb61c1ff189ea76da7d9a0c8858d581766e` |
| `examples/sample_case_input.json` | 695 | `98506fcd5cfcad92fb055879551356362c555268a9ed1a69bd0101b8479079cb` |
| `README.md` | 7113 | `d341377a00344907e411d023005060dfba764164caabcc12493ef76087130b0a` |
| `references/edit_taxonomy.json` | 3233 | `8a53a40bfaea5c58cfc996dd24d6080b78be8aec58bccb84c4b4b7c08df6ce8e` |
| `references/hedging_lexicon.json` | 5523 | `a136b963777e0e6b86528eb555072e52a4783c6f00011921fe36d6ff55fbacde` |
| `references/register_profiles.json` | 4810 | `c7daa0ae3de08afe1a3aa0480d1360b56fbf168fecdf6589de8869d56c0b045b` |
| `scripts/extract_anchors.py` | 7855 | `b13a2f58d9e4044e6f3f9ae187cf843b6c8c35aac00713637dd4275921854fcd` |
| `scripts/harbor_case.py` | 14533 | `c6df8ac3454741028d4b89a548d8e62449044e979c565582620baa5d4ca3d42e` |
| `scripts/package_result.py` | 8480 | `5a85cd10e7c6ff852109079ae4e4a57dbb906b5e5989327d0bcaf4f7a8ceee47` |
| `scripts/run_self_test.py` | 14492 | `c4066e8ade031305f60e37b2d75356b06fd3bc7d91657cb483cb510145cf04b2` |
| `scripts/verify_polish.py` | 26013 | `d024b9b45af1aa3d15777b7c8c191cf27b7bf748c1f5e5880784ad0bdf3604b8` |
| `SKILL.md` | 16220 | `fdc8c1bd40b800750cd781df8d4235d1bdb908f4c0c5208ad37015982ff1b24a` |
| `templates/glossary_template.json` | 1126 | `04ce1a8e2f30021a573993c5fb16a24e22c4a1973f91e80a834035524e365913` |

## 3. Install & Invocation（安装与调用）

```bash
# 1) 安装：整目录复制到 Skill 根目录（无需构建、无需联网）
cp -r . /app/submission/

# 2) 自检（9 项，含正/负样本与嵌套 case schema 读入）
cd /app/submission && python3 scripts/run_self_test.py

# 3) 处理案例
python3 scripts/harbor_case.py init --case /input/case.json --work /app/work
python3 scripts/harbor_case.py finalize --case /input/case.json --work /app/work --output /app/output
```

## 4. Provenance & Conditions（来源与使用条件）

- 规则词典（`hedging_lexicon.json`、`edit_taxonomy.json`、`register_profiles.json`）由本项目按学术写作惯例人工整理，未直接引用第三方受版权保护的词表；可按目标期刊或学科增删条目，schema 不变即可继续使用。
- 脚本仅使用 Python 标准库，不执行网络请求，不写入自身目录以外的位置（输出路径由命令行参数给定）。
- 使用条件：需提供 UTF-8 文本或 `case.json`；PDF 需先由平台提供的 PDF 工具转为文本，本 Skill 不内置 OCR。
