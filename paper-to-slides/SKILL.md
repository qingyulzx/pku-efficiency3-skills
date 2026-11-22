---
name: paper-to-academic-ppt
description: Turn a research paper (PDF) into a structured, evidence-traceable, template-compliant academic slide deck. Extracts the narrative spine (problem/method/results/limitations) with verbatim quotes, designs page-level claims each backed by paper locators, assembles an editable deck inside the provided template via real master/layout placeholders, renders a PDF preview, and returns a contract-complete result.json. Use when a task asks to convert a paper or research material into academic slides with evidence mapping and template compliance.
---

# 论文转学术 PPT（evidence-traceable）

目标：把一篇论文转换成**证据可追溯、模板合规**的学术演示——每页一个主张，
主张背后挂着论文里的图表/段落定位与逐字引文。
判断（主线取舍、页级主张、图表引用）由 Agent 解析后亲自完成；脚本只做解析、装配、校验。
全程在 `/app/work` 工作，最终产物进 `/app/output`。先读 `/input/case.json` 与 task.md，
**以真实文件为准，不要按记忆或标签假设材料内容**。

进度自检清单（走一步勾一步）：
```
- [ ] Step 1 读输入 + 亲笔保底 result.json
- [ ] Step 2 解析论文（脚本）
- [ ] Step 3 提炼主线四要素（Agent）
- [ ] Step 4 页级大纲 + 证据映射（Agent）
- [ ] Step 5 模板内装配 PPTX（脚本）
- [ ] Step 6 渲染预览 + 质量自检
- [ ] Step 7 契约输出 + 复核
```

## Step 1 — 读输入，先落保底产出

1. 读 `/input/case.json` 与 task.md。确认：`case_id`、论文与模板路径、约束
   （受众/时长/页数）、`output_contract`（**dict 或 list；可能不存在**）。
2. **立刻亲笔写** `/app/output/result.json` 保底版：`case_id` + 契约全部字段
   （有契约逐字段镜像——dict 用其键、list 用每项的 `name`；无契约用
   /skills/weekly-skill/references/output-schema.md §3 默认契约）+ 每字段 `null` +
   `null_reasons: {"字段": "Step N 产出"}` + `status: "running"`。
   之后每个 Step 只增强、不删除已填字段。
3. 脚本一律绝对路径调用（`/skills/weekly-skill/scripts/...`）。

**异常处置**：case.json 读不了 → result.json 写 `status: "failed_input"` + 原因；
论文/模板路径不存在 → 记入 `uncertainty`，按存在的材料继续（保底优先于完美）。

## Step 2 — 解析论文（脚本）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <论文.pdf> \
  --out /app/work/materials_index.json
```

读回 `materials_index.json`：各文件 sha256 与状态、章节/页文本、
`figures_tables`（图表清单与页码）、公式行。若是扫描件（文字极少）→ 记
`uncertainty`，可用容器 ocr-tool 就走 OCR 后重跑。

## Step 3 — 提炼主线四要素（Agent 亲自）

从解析结果（abstract/intro/结果表/conclusion）亲自提炼，写入大纲文件的
`narrative` 节：

- **problem**：论文攻击什么问题，附逐字引文；
- **method**：核心思想一句话，附图表/章节指针；
- **results**：头条数字带单位和出处表；
- **limitations**：优先论文自己的 limitations 节；缺失就明说，
  presenter 推断的 caveat 显式标注。

引文规则：从解析文本**逐字复制**（只修 PDF 换行）；保留页码；
`quote` 字段内绝不改写。

## Step 4 — 页级大纲与证据映射（Agent 亲自）

按 /skills/weekly-skill/references/output-schema.md §2 的 schema 写
`/app/work/outline.json`：

- 每页一条 `claim`（完整句子主张，不是话题标签）+ `role`
  （problem/method/result/limitation/...）+ 讲稿 `notes`；
- 每页 ≥1 条 `evidence`（定位 + 页码 + 逐字引文）；
- 图表页：引用论文原图（解析产物里的图片文件）+ 原文 caption；
- `decisions` 日志：保留/砍掉/合并的每个决定带理由（页数预算约束下的取舍）。

## Step 5 — 模板内装配 PPTX（脚本）

```bash
python /skills/weekly-skill/scripts/build_deck.py --outline /app/work/outline.json \
  --template <模板.pptx> --out /app/output/<case_id>.pptx \
  --max-slides <页数上限> --report /app/work/assembly_report.json
```

读回 `assembly_report.json`。报溢出风险/版式回退/超页数时**改大纲不改产物**
再重跑（产物与 decisions 日志必须一致）。脚本保证：内容落 slide 层占位符
（写 layout 层占位符不渲染）、图片保纵横比、备注附页。

## Step 6 — 渲染预览与质量自检

```bash
python /skills/weekly-skill/scripts/render_preview.py \
  --pptx /app/output/<case_id>.pptx --outdir /app/output/render
```

核对：PDF 页数与 pptx 一致、无字体替换告警、图片完整。
偏差记入 result.json 的渲染记录。

## Step 7 — 完成契约输出与复核

用 /skills/weekly-skill/references/output-schema.md §4 的字段映射，把
outline/装配报告/渲染检查/decisions 填进 result.json 对应契约字段；
未产出的字段保持 `null` + 原因，`status` 按实际情况
（complete / partial + 残留项说明）。

**完成前自查**：每页都有 claim + evidence + notes？数字与论文逐字一致？
未答字段全部 null+原因？渲染 PDF 可打开？
