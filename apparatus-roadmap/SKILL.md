---
name: setup-roadmap
description: Turn papers, equipment lists, or research plans into layered, editable SVG diagrams of experimental setups (apparatus, P&ID-style) and technical roadmaps (flow/route charts), with verbatim-quote evidence for every component, connection, and stage, machine-checked bidirectional consistency between the figure and the source material, honest uncertainty marking (unspecified specs, inferred links), and PNG/PDF export. Use when a task asks to draw an apparatus diagram, experiment flowchart, technical route map, or material-flow diagram, or to edit an existing one.
---

# 实验装置与技术路线图（evidence-traceable SVG）

目标：把「装置怎么搭、步骤怎么走、物料从哪来到哪去」画成一张**对得起材料**的
分层可编辑 SVG——图上每个元素都能逐字回溯到输入材料，材料提到的每个实体
要么画了、要么有书面的省略理由，这由 `check_consistency.py` 机器强制，不是自评。
判断（部件是什么类型、箭头朝哪、阶段怎么分）由 Agent 解析材料后亲自完成；
脚本只做解析、渲染、校验。全程在 `/app/work` 工作，最终产物进 `/app/output`。
先读 `/input/case.json`，**以真实文件为准，不要按记忆或标签假设材料内容**。

进度自检清单（走一步勾一步）：
```
- [ ] Step 1 读输入 + 亲笔保底 result.json
- [ ] Step 2 解析材料（脚本）
- [ ] Step 3 装置/路线要素提取（Agent）
- [ ] Step 4 写 IR 图级大纲 + 结构校验
- [ ] Step 5 IR 渲染装配 SVG（脚本）
- [ ] Step 6 导出预览 + 双向一致性校验
- [ ] Step 7 契约输出 + 复核
```

## Step 1 — 读输入，先落保底产出

1. 读 `/input/case.json`（与 task.md，如有）。确认：`case_id`、材料路径、
   图类型期望（装置图 / 技术路线图）、`output_contract`（**dict 或 list；
   可能不存在**，形状细则见 references/output-schema.md §1）。
2. **立刻亲笔写** `/app/output/result.json` 保底版：`case_id` + 契约全部字段
   （有契约逐字段镜像——dict 用其键、list 用每项的 `name`；无契约用
   /skills/weekly-skill/references/output_contract.md 的默认字段模板，
   含 status/sources/uncertainty 基线）+ 每字段 `null` +
   `null_reasons: {"字段": "Step N 产出"}` + `status: "running"`。
   之后每个 Step 只增强、不删除已填字段。
3. 脚本一律绝对路径调用（`/skills/weekly-skill/scripts/...`）。

**异常处置**：case.json 读不了 → result.json 写 `status: "failed_input"` + 原因；
材料路径不存在 → 记入 `uncertainty`，按存在的材料继续（保底优先于完美）。

## Step 2 — 解析材料（脚本）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <材料文件或目录> \
  --out /app/work/materials_index.json
```

读回 `materials_index.json`：各文件 sha256 与状态、章节/页文本、图表清单。
扫描件（文字极少）→ 记 `uncertainty`，容器有 ocr-tool 就 OCR 后重跑；
解析失败的页记 `uncertainty`（含页码），**不猜**。同时把可回溯的全文文本
合并存 `/app/work/materials_fulltext.txt`（Step 6 双向校验的比对基准）。

## Step 3 — 装置/路线要素提取（Agent 亲自）

本 Skill 的科学核心，判断规则见
/skills/weekly-skill/references/extraction_playbook.md，**亲自**完成：

- **apparatus（装置图）**：
  1. 部件清单：每个部件 → id/label/type（图元映射见 symbol_library.md）/
     specs；同类多台分开建；只出现在背景/展望、不参与流程的进
     extraction_index 标 omitted+reason，不画；
  2. 连接拓扑：from/to（**方向对着材料里的动词确认**：「流入」"directed to"）、
     medium、kind（material/signal/energy）、conditions（温度/流速逐字取值）；
  3. 条件标注：规格未给 → `certainty: unspecified_spec`（图上自动
     「△ 规格未提供·示意」）；连接靠上下游顺序推断 → `inferred`（灰虚线）；
     两者皆无 → 不建连接，部件进未连线区，不编造。
- **route（技术路线图）**：阶段模型——节点 kind（start/end/stage/step/
  decision/milestone）、`step_no` 与材料编号逐条对照（没编号就不编造）、
  决策分支出边带 condition、回环边 `kind: loop` + `route: below`。
- **每个元素挂 source** `{location, quote}`：引文从解析文本**逐字复制**
  （只修 PDF 换行），保留页码/章节定位，`quote` 内绝不改写。
- **extraction_index 登记**材料提到的所有实体/步骤（mapped_id 或
  omitted+reason）——覆盖检查的上限就是索引的完整度，宁多勿漏。

## Step 4 — 写 IR（图级大纲）并做结构校验

按 /skills/weekly-skill/references/ir_schema.md 把 Step 3 结果写成 IR JSON，
存 `/app/output/intermediate.json`（`figure_type: apparatus | route`）。
IR 是可编辑真源：改图 = 改 IR 后重渲重校，**绝不在导出的 SVG 上直接改**。

```bash
python /skills/weekly-skill/scripts/validate_ir.py /app/output/intermediate.json
```

exit 0 才继续。常见错误：id 重复、连接端点不存在、元素缺 source.location、
extraction_index 有 omitted 无 reason。改 IR 再跑。

## Step 5 — IR 渲染装配 SVG（脚本）

```bash
python /skills/weekly-skill/scripts/render.py /app/output/intermediate.json \
  --outdir /app/output --name figure --also-png --also-pdf --png-scale 2 \
  [--font <font-discovery 找到的 CJK 字体路径>]
```

产出 `figure.svg`（四层可编辑：frame/structure/annotation/source，元素带
data-id + 逐字引文 `<desc>`）、`figure.geometry.json`、`figure.png`、`figure.pdf`。
读回 geometry.json：`overflow_warnings` 应为空（非空 → 缩小标签文本重渲）；
`font_notes` 有「no CJK font」→ 用 font-discovery 找字体重跑；PNG 因缺字体
变框时 SVG 仍是真文字（保真源），并在 uncertainty 如实记录。

## Step 6 — 导出预览与双向一致性校验（不过不算完成）

核对导出件：PNG/PDF 存在且非空；PDF 走 cairosvg 矢量、缺失时位图——
如实写进 result.json 的渲染记录，不谎报。然后跑双向校验：

```bash
python /skills/weekly-skill/scripts/check_consistency.py /app/output/intermediate.json \
  /app/work/materials_fulltext.txt /app/output/figure.svg /app/output/figure.geometry.json \
  --out /app/output/consistency_report.json
```

五项检查：引文逐字回溯（防无中生有）、覆盖索引完备（防漏画）、SVG↔IR id
双向一致、箭头落点无悬空、图层齐全。**exit 1 必须回到 Step 3 修 IR 再重跑
Step 5–6**，不许带病交付。

## Step 7 — 完成契约输出与复核

用 /skills/weekly-skill/references/output_contract.md 的字段模板把实值填进
result.json：图路径（svg/png/pdf + 四层说明）、element_sources（每元素一条
定位+引文）、data_mapping（线型/颜色/△/灰虚线语义）、provenance、
uncertainty（与图上 △/灰虚线一一对应）；未产出的字段保持 `null` + 原因，
`status` 按实际情况（complete / partial + 残留项说明）。然后：

```bash
python /skills/weekly-skill/scripts/check_result.py --result /app/output/result.json \
  --case /input/case.json
```

exit 0 才算交付。

**完成前自查**：图上每个元素都能逐字回溯？材料提到的实体要么在图上、要么有
omitted 理由？每个 △/灰虚线在 uncertainty 有一一对应条目？SVG 四层齐全、
元素带 data-id？PNG/PDF 非空且字体问题已记录？intermediate.json 已随交付
保存（改图真源）？

## 编辑场景（已有图改部件/加管路）

改 IR，不改 SVG：新材料存成文本文件 → 按 `scripts/edit_ir.py` 文档头写
edits（add_component/add_connection/update/remove）→
`python /skills/weekly-skill/scripts/edit_ir.py /app/output/intermediate.json
edits.json --material 新材料.txt --out /app/work/intermediate_v2.json`
（新增元素的 quote 会被逐字核验，不过整批拒绝）→ 对 v2 重跑 Step 4→6。

## 限制

- 示意图元不表达工程比例与真实尺寸；不判断实验方案科学合理性。
- PNG/PDF 依赖 Pillow（PNG/位图 PDF，可选）与 cairosvg（矢量 PDF，可选）；
  缺失时 SVG 是保底交付件，如实标注。
- 中文 OCR 质量受原件影响，引文以 PDF 文字层优先。
