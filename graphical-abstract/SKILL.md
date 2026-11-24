---
name: graphical-abstract-builder
description: Turn a research paper or study material into a single-page graphical abstract (question, method, results, conclusion) as a traceable, editable SVG with PNG/PDF exports. Extracts entities, relations, data and conclusions with verbatim quotes and locators, renders every element from one deterministic figure model with an independent quote-verification pass, and returns a contract-complete result.json. Use when a task asks to create a graphical abstract, science summary figure, mechanism or flow diagram, or data chart from papers, study notes or experimental records, especially when editable sources and element-to-source traceability are required.
---

# 图形摘要构建（evidence-traceable graphical abstract）

目标：把研究材料压缩成**单页、可编辑、证据可追溯**的图形摘要（问题→方法→结果→结论
四段式一页讲完），画面上每个元素都挂着材料里的逐字引文与定位。
判断（面板取舍、视觉编码、什么上画面什么进图注）由 Agent 解析后亲自完成；脚本只做
解析、渲染、校验。全程在 `/app/work` 工作，最终产物进 `/app/output`。先读
`/input/case.json` 与 task.md，**以真实文件为准，不要按记忆或标签假设材料内容**。

进度自检清单（走一步勾一步）：
```
- [ ] Step 1 读输入 + 亲笔保底 result.json
- [ ] Step 2 解析材料（脚本）
- [ ] Step 3 科学内容提取（Agent 亲自）
- [ ] Step 4 figure_model.json（Agent 亲自）
- [ ] Step 5 渲染 SVG/PNG/PDF（脚本）+ 渲染复核
- [ ] Step 6 独立校验 + 肉眼复核
- [ ] Step 7 契约输出 + check_result 校验
```

## Step 1 — 读输入，先落保底产出

1. 读 `/input/case.json` 与 task.md。确认：`case_id`、材料文件路径、约束
   （语言/画布/输出格式）、`output_contract`（**dict 或 list；可能不存在**）。
2. **立刻亲笔写** `/app/output/result.json` 保底版：`case_id` + 契约全部字段
   （有契约逐字段镜像——dict 用其键、list 用每项的 `name`；无契约用
   /skills/weekly-skill/references/output-schema.md §3 默认契约）+ 每字段 `null` +
   `null_reasons: {"字段": "Step N 产出"}` + `status: "running"`。
   之后每个 Step 只增强、不删除已填字段。
3. 建工作目录 `/app/work`。脚本一律绝对路径调用
   （`python /skills/weekly-skill/scripts/<x>.py`）。

**异常处置**：case.json 读不了 → result.json 写 `status: "failed_input"` + 原因，
停止并如实报告；材料路径不存在 → 记入 `uncertainty`，按存在的材料继续（保底优先于完美）。

## Step 2 — 解析材料（脚本）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <材料文件或目录> \
  --out /app/work/materials_index.json
```

读回 `materials_index.json`，重点看：各文件的 sha256 与状态、章节/页文本、
`figures_tables`（图表清单与页码）、公式行。然后基于解析文本生成
`/app/work/sources.json`（`{"材料路径": "<全文>"}`）——Step 5/6 的引文逐字核对
靠它。

**异常处置**：PDF 文字极少（扫描件）→ 记 `uncertainty`，可用容器 ocr-tool 的走
OCR 后重跑，没有工具就只按可读部分设计并声明；某文件 `status: "error"` →
不编造其内容，缺口进 `uncertainty`。

## Step 3 — 科学内容提取（Agent 亲自）

这是 agent-in-the-loop 的核心步骤——**不要交给脚本**。按
/skills/weekly-skill/templates/agent_worksheet.md 的表格逐栏填写
`/app/work/worksheet.md`，全部内容取自 Step 2 的解析文本：

1. **question**：材料攻击什么问题？逐字引文 + 定位；材料自己的重要性陈述。
2. **entities**：必须上画面的实体（分子/细胞/器件/方法/队列…）。每项：
   短标签、层级（谁包含谁、谁在上游）、逐字引文、locator（文件+页/节/句）。
   发现的歧义与消解方式要记录。
3. **relations**：材料**明确陈述**的方向性关系（A 激活 B、剂量引出问题…）。
   记录方向 + 陈述它的原句。只是关联性（非因果）的关系用虚线或不画。
4. **data**：每个可能画的数字——值、单位、条件/系列、来源句（引文里必须含
   该数字）。**材料里没有的数字绝不画**，列进 `uncertainty`；推导数字
   （差值/均值/换算）写明推导过程。
5. **conclusions**：材料自己下的结论，逐字引文 + 定位。

引文规则：从解析文本**逐字复制**（只修 PDF 换行）；保留页码；
`quote` 字段内绝不改写；locator 精确到人几秒内能找到。

产出面板-要点映射草案：每面板 role（question/method/results/conclusion）、
layout（flow/chart/stats/text）、内容、编码决策；并明确哪些内容只进图注
（notes/caption）不上画面。

## Step 4 — 写 figure_model.json（Agent 亲自）

按 /skills/weekly-skill/references/model_schema.md 的 schema 写
`/app/work/figure_model.json`（模板：/skills/weekly-skill/templates/figure_model.template.json；
完整真实示例：/skills/weekly-skill/examples/transformer-1706.03762/）。关键决策：

- **面板计划**：4–6 面板，阅读顺序 question → method → results（1–2 个）→
  conclusion，一面板一个发现。
- **每面板 layout**：`flow`（实体/关系：盒子+箭头）、`chart`（bar/hbar/
  grouped_bar/line 画数据）、`stats`（大数字卡，2–4 个头条值）、`text`
  （结论要点）。
- **视觉通道**：同单位同基线的量级用长度；时序用位置；分类系列才用色
  （内置 Okabe–Ito 色板，绝不纯红对纯绿）；焦点实体用形状/强调。
  一通道一义，一义一通道。
- **画布**：默认 1800×1000 px（约 A4 横向 150 dpi）；字号 ≥12 px（校验强制）。
- **证据链**：把 worksheet 的引文/定位复制进每个元素的 `source`
  （element → quote → locator 三层证据链，model_schema 钉死
  `graphical-abstract/1` 版本）。

## Step 5 — 渲染：单 Scene 三端（脚本）

```bash
python /skills/weekly-skill/scripts/build_figure.py --model /app/work/figure_model.json \
  --outdir /app/work/out --sources /app/work/sources.json
```

产物（同模型输入 → 确定性同图）：`graphical_abstract.svg`（可编辑真源：命名 id、
`layer-*` 组、每元素 provenance `<desc>`）、`.png`（默认 300 dpi；无 matplotlib
自动降级 Pillow，如实记录）、`.pdf`、`element_map.json`、`export_report.json`。
退出码 2 = 模型无效（改 JSON）、3 = SVG 失败（按 playbook 修）；PNG/PDF 导出失败
**不中断**，进 `export_report.json.failures`。

**迭代规则**：有错误改 figure_model.json（**绝不手改 SVG**）再重建，直到
export_report 的 error 清零。

渲染复核（紧随其后）：

```bash
python /skills/weekly-skill/scripts/render_preview.py \
  --svg /app/work/out/graphical_abstract.svg --outdir /app/work/out
```

独立光栅化 SVG 复核可渲染性并审计产物包（SVG 良构、text/layer/id 计数、PNG/PDF
完整性），写 `render_report.json`；环境没有可用光栅化器时如实记 `render_gap`
（复用构建器自身 PNG 时标 `fallback`，不冒充独立渲染）。

## Step 6 — 独立校验（脚本 + 肉眼）

```bash
python /skills/weekly-skill/scripts/check_figure.py --outdir /app/work/out \
  --sources /app/work/sources.json
```

独立校验器重跑全部检查：SVG 良构性、字号下限、画布越界、element_map 完整性、
**引文-材料逐字核对（抓编造数字与改写引文）**、灰度/对比度、导出完整性 →
`issues.json`。退出码 0 才通过。然后**亲自打开 PNG 看**：

- 阅读顺序是否一目了然（面板衔接箭头方向）？
- 实体/箭头方向与材料陈述一致？
- 图例与实际编码一致？每个坐标轴有单位？
- 消除不了的 warning 如实记录进 result.json，**不隐藏**。

## Step 7 — 完成契约输出与复核

1. 写 `/app/work/values.json`：契约字段值（`scientific_summary`、各产物路径、
   `uncertainty` 等）；`element_source_map` / `export_checks` 由脚本自动注入。
2. 装配终稿：

```bash
python /skills/weekly-skill/scripts/make_result.py --stage final \
  --case /input/case.json --out /app/output/result.json \
  --values /app/work/values.json \
  --map /app/work/out/element_map.json \
  --export /app/work/out/export_report.json \
  --issues /app/work/out/issues.json \
  --status complete --uncertainty "<一句诚实说明>"
```

匹配规则：字段名精确 → 包含 → 描述关键词；未匹配字段保持显式 `null` + 原因，
绝不编造。有 error 级 issue 时 status 自动降级 `partial`——**绝不在失败检查上
标 complete**。

3. 校验直到退出码为 0：

```bash
python /skills/weekly-skill/scripts/check_result.py \
  --result /app/output/result.json --case /input/case.json
```

4. 拷贝交付物到 `/app/output`：`graphical_abstract.svg` + `figure_model.json`
   （可编辑源）、`graphical_abstract.png`（预览）+ `graphical_abstract.pdf`
   （导出）、`result.json`。

**完成前自查**：画面上每个数字都出现在 element_map 的一条引文里？图例与
编码一致？未答字段全部 null+原因？SVG 打开是良构 XML、文字是真 `<text>`？
`uncertainty` 提到每个降级/无源项？

## 异常与红线

所有失败模式（材料缺关键数字、实体歧义、文字溢出、字体替换、画布越界、导出失败、
无 matplotlib…）的签名与处置见
/skills/weekly-skill/references/exception_playbook.md。
一条压倒一切的规则：**如实记录，绝不编造**。带 documented limits 的 `partial`
结果好过带虚构证据的漂亮图。

## 参考文件

- /skills/weekly-skill/references/model_schema.md — figure_model.json 逐字段规范
- /skills/weekly-skill/references/output-schema.md — 契约形状 / 默认契约 / result.json 模式
- /skills/weekly-skill/references/exception_playbook.md — 失败签名 → 处置
- /skills/weekly-skill/references/design_notes.md — 编码/色盲安全/排版约定
- /skills/weekly-skill/templates/agent_worksheet.md — Step 3 提取工作表
- /skills/weekly-skill/templates/figure_model.template.json — 最小起步模型
- /skills/weekly-skill/examples/transformer-1706.03762/ — 真实论文完整示例
  （arXiv:1706.03762，逐字引文 + sha256）
