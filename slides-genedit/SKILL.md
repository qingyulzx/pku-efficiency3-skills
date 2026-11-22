---
name: slides-genedit
description: Generate and edit academic presentation decks from research material. Two routes - (1) generate a new deck from a paper/notes under fixed audience, duration and slide-count constraints, with per-slide claims, verbatim-number evidence mapping, speaker notes, and a rendered PDF preview; (2) source-preserving edits of an existing starting deck - inventory it, apply only the requested local changes, and prove untouched slides stayed byte-identical. Use when asked to turn research material into slides, or to modify/compress/re-audience an existing deck without breaking it.
---

# 学术 PPT 生成与编辑（dual-route）

目标：把研究材料「翻译」成可讲、可追溯、可编辑的演示文件；或对已有 deck
做**保源编辑**——只改要求的部分，未动的页字节级不变。
难点在取舍与重排（哪些结果单占一页、方法压几条、图 3 图 4 谁先、超页数砍什么），
这些判断由 Agent 亲自完成；脚本只做解析、装配、校验、渲染。
全程 `/app/work` 工作，产物进 `/app/output`。先读 `/input/case.json` 与 task.md，
**以真实文件为准**。

## 路线分流（先定夺，绝不混用）

读 `/input/case.json` + task.md 后判断（依据实际文件与任务措辞）：

- **GENERATE（生成）**：输入没有现成 deck（材料 + 受众/时长/页数约束 + 模板）→ 走 Step 2-7 主线。
- **EDIT（编辑）**：给了 starting deck 且指令是局部修改（改标题/换内容/加删页/压缩/换受众）→ 走 Step 2'-4'。
- deck 存在但指令是整体重写/重排叙事 → 实为生成（starting deck 留作 N-1 版）。
路线决定与其证据记录进 result.json。

预算纪律：~7 个工具步是甜点区，64 请求 / 900 秒总量。

## Step 1 — 读输入，先落保底产出（两条路线共通）

1. 读 `/input/case.json` 与 task.md。确认：`case_id`、材料/现成 deck 路径、约束
   （受众/时长/页数）、`output_contract`（**dict 或 list；可能不存在**）。
   读实际存在的每个输入文件（`material*.md/pdf/tex`、图）；PDF 用容器
   pdf-text-tool / pdf-render-tool / ocr-tool。绝不按文件名猜内容。
2. **立刻亲笔写** `/app/output/result.json` 保底版：`case_id` + `route` +
   契约全部字段（dict 用其键、list 用每项 `name`；无契约用
   /skills/weekly-skill/reference/schemas.md 默认契约或 output-schema.md §3）+
   每字段 `null` + `unanswered: [{field, reason}]` + `status: "partial"`。
   之后每步只增强、不删除。
3. 脚本一律绝对路径（`/skills/weekly-skill/scripts/...`）。

## Step 2 — 解析材料（生成路线）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <材料文件或目录> \
  --out /app/work/materials_index.json
```

读回索引：文件 sha256/状态、章节页文本、图表清单、（若有）模板 layouts。

## Step 3 — 页级大纲：你的判断，留痕（生成路线）

按 /skills/weekly-skill/reference/schemas.md（或 references/output-schema.md §2）
写 `/app/work/outline.json`：

- 一页一主张（标题陈述信息，不是话题标签）；每页 `role` + 讲稿 `notes`；
- **数字逐字**：28.4 不写成 ~28；每个数字的出处进该页 `evidence`；
  找不到出处的数字不上页；
- 按受众/时长取舍：组会重方法、评审重进度、答辩重贡献与证据；
- `decisions` 日志：保留/砍/并/重排每条带理由（页数预算下的取舍）。

## Step 4 — 装配（生成路线）

```bash
python /skills/weekly-skill/scripts/build_deck.py --outline /app/work/outline.json \
  --template <模板.pptx（若有）> --out /app/output/deck_v1.pptx \
  --max-slides <上限> --report /app/work/assembly_report.json
```

读回报告；报溢出/回退/超页数时改 outline 再跑。脚本保证：slide 层占位符
（layout 层不渲染）、图片保纵横比、备注附页。

## Step 2' — 盘点 starting deck（编辑路线）

读入 deck（python-pptx 或清单工具），定位指令点名的目标
（页索引 + 占位符 idx / 形状名）。目标不存在 → 大声失败、改目标或新增，
绝不静默跳过。

## Step 3' — 外科手术式修改（编辑路线）

只覆盖指令要求的部分：改写既有条目（保留原格式）、追加条目、写备注、
插图（保纵横比）、加页/删页/移页/复制页。全 deck 重写走 ops 是误用——换路线。
`/app/work/ops.json` 按序应用到 1 基页索引。

## Step 4' — 保真核验（编辑路线）

对未动的页做字节级对比（raw sha256）+ 母版/版式摘要对比；不一致即失败回滚。
保真矩阵进 result.json 的 `edit_preservation`。

## Step 5 — 渲染预览与质量自检

```bash
python /skills/weekly-skill/scripts/render_preview.py \
  --pptx /app/output/deck_v1.pptx --outdir /app/output/render
```

PDF 页数一致、无字体替换告警、图片完整。编辑路线对 deck_v2 同样渲染核对。

## Step 6 — 契约输出与复核

把 outline/装配报告/渲染检查/decisions（或 ops/保真矩阵）填进 result.json
对应契约字段；未产出字段保持 `null` + 原因；`status` 按实际（complete/partial）。

**完成前自查**：每页 claim+evidence+notes？数字逐字？未答字段全 null+原因？
编辑路线未动页字节级不变？渲染 PDF 可打开？
