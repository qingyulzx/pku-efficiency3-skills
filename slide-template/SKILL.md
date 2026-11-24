---
name: academic-ppt-template-adaptation
description: Adapt a paper or research material into a GIVEN PowerPoint template and produce a template-compliant, evidence-traceable academic deck. Analyzes the template's real capabilities (layouts, placeholders, theme fonts/colors, text-size ladders, anomalies) into a manifest, maps each page's content role to a layout, assembles slides via real master/layout placeholders with a capacity ladder (trim bullets, then shrink sizes never below readability floors, then split), renders a PDF preview, runs a whole-deck consistency scan (overflow, font-size floors, image distortion, theme-inheritance violations) in a fix loop, and returns a contract-complete result.json with page-level evidence mapping. Use when a task provides a template pptx plus paper/material and audience/duration/slide constraints and asks for academic slides that truly inherit the template, or asks to adapt fixed content into a specified deck format.
---

# 学术 PPT 模板与格式适配 Skill

目标：把研究材料适配进**指定模板**——产出真正继承其母版/版式/主题的可编辑
演示：版式选择有 manifest 依据、每页文字数字与源材料对得上、整册一致性
可扫描、导出件可复核。
判断（内容→版式映射、取舍、修复决策）由 Agent 解析后亲自完成；脚本只做
解析、装配、扫描。全程在 `/app/work` 工作，最终产物进 `/app/output`。
先读 `/input/case.json` 与 task.md，**以真实文件为准，不要按记忆或标签
假设材料内容**。

进度自检清单（走一步勾一步）：
```
- [ ] Step 1 读输入 + 亲笔保底 result.json
- [ ] Step 2 解析源材料 + 模板能力分析（脚本）
- [ ] Step 3 内容→版式映射决策（Agent 亲自）
- [ ] Step 4 页级大纲 + 版式指定（Agent 亲自）
- [ ] Step 5 模板内装配 PPTX（脚本）
- [ ] Step 6 渲染预览 + 整册一致性扫描（脚本）
- [ ] Step 7 契约输出 + 复核
```

## Step 1 — 读输入，先落保底产出

1. 读 `/input/case.json` 与 task.md。确认：`case_id`、`template.pptx` 路径
   （**必需**——母版/版式/主题的来源）、源材料路径、固定约束
   （受众/时长/页数）、`output_contract`（**dict 或 list；可能不存在**）。
2. **立刻亲笔写** `/app/output/result.json` 保底版：`case_id` + 契约全部字段
   （有契约逐字段镜像——dict 用其键、list 用每项的 `name`；无契约用
   /skills/weekly-skill/references/output-schema.md §3 默认契约）+ 每字段
   `null` + `null_reasons: {"字段": "Step N 产出"}` + `status: "running"`。
   之后每个 Step 只增强、不删除已填字段。
3. 脚本一律绝对路径调用（`/skills/weekly-skill/scripts/...`）。

**异常处置**：case.json 读不了 → result.json 写 `status: "failed_input"` +
原因，停止并如实报告；模板路径不存在/不可读 → 记入 `uncertainty`，
build_deck 会自动回退默认模板并记录（保底优先于完美）。

## Step 2 — 解析源材料 + 模板能力分析（脚本）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <材料文件或目录> \
  --out /app/work/materials_index.json
python /skills/weekly-skill/scripts/analyze_template.py <template.pptx> \
  --out /app/work/manifest.json
```

读回两个 JSON：
- `materials_index.json`：各文件 sha256 与状态、章节/页文本、
  `figures_tables`（图表清单与页码）、公式行；
- `manifest.json` 四块（**模板能力清单是本 Skill 的核心差异化**）：
  - `suggested_role_mapping`：六个角色（title/section/content/two_content/
    picture/closing）→ 版式候选及评分；
  - `themes`：主题色板与主题字体——后面一切视觉继承的来源；
  - `text_style_ladders_pt` + `readability_floors_pt`：字号阶梯与下限；
  - `anomalies`：无标题版式、超小正文占位符、无图片版式等——Step 3/4
    映射时绕开或补偿。

**异常处置**：PDF 提示文字极少（扫描件）→ 记 `uncertainty`，可用容器
ocr-tool 就 OCR 后重跑解析；某文件 `status: "error"` → 不编造其内容；
manifest 打不开（UNREADABLE_PPTX）→ 换案例其他 pptx 或在 result.json
标注并走默认模板回退。

## Step 3 — 内容→版式映射决策（Agent 亲自，判据在此用前速查）

先按受众定叙事骨架（组会讲方法与进度 / 答辩讲创新与边界 / 评审结论先行，
判据与页配比见 /skills/weekly-skill/references/scenario-playbooks.md），
再**亲自**逐页决定内容角色与版式——这一步不交给脚本。角色→版式判据：

| 角色 | 最佳版式特征 | manifest 里的证据 |
|-|-|-|
| title | center_title + subtitle | suggested_role_mapping.title 最高分 |
| section | center_title | 同上（section 键） |
| content | title + 1 个正文占位符 | body_count==1 的版式 |
| two_content | title + ≥2 正文占位符 | body_count≥2 |
| picture | title + 图片占位符 + 正文 | picture_count≥1；模板无图片版式→图片走自由区域 |
| closing | center_title + subtitle | title 候选复用 |

配套硬判据（Step 4/5/6 都要用）：
- **每页一句主张**：标题写成可讲出口的判断句，不写名词标签；
- **时长预算**：约 60–75 秒/页；案例给了 `slide_count` 以案例为准，
  冲突时保页数上限；
- **砍页优先级**：P0 主张+核心证据 → P1 背景/方法主干 → P2 扩展结果
  → P3 礼节/延伸；从 P3 开始砍，砍掉的都进 `cut_log`；
- **容量阶梯**：装不下时**裁剪→缩字号（有地板）→拆页**，绝不压到
  不可读（阶梯由 build_deck 自动执行，拆页决策归你）；
- **anomalies 内化**：无标题版式只用于 backup；超小正文占位符（<0.8in）
  的版式装不下多少字，选它就得砍内容；无图片版式的模板，图片页照样做，
  图片自动走自由区域。

产出 `/app/work/audience_plan.json`：`goal`、`scenario`、页配比决策、
每页角色与版式候选（对照 manifest 的 anomaly 处置）、依据。

## Step 4 — 页级大纲与版式指定（Agent 亲自）

按 /skills/weekly-skill/references/output-schema.md §2 的 schema 写
`/app/work/outline.json`。每页：
- `type`（角色）+ `layout`（可选：**显式版式名或索引，必须从 manifest
  抄写**，优先于角色映射；不凭记忆造名字）+ `priority`（P0–P3）；
- 唯一主张（title）+ ≤5 条要点（bullets，level 0-4）+ figures（图路径
  + caption + status）；
- `evidence`（locator 文件+页/节、逐字引文 ≤40 词、strength 四档：
  direct/indirect/inferred/gap——gap 打 `[证据缺口]`，**绝不编造**）；
- `notes`（口语化讲稿：过渡句、数字读法、指图动作；不复读 bullets）+
  `qa`（预期追问与口径一致的回答）。

**异常处置**：材料撑不起某关键页 → evidence 用 `gap` + 明确缺口描述；
无逐字引文支撑的数字 → 不上页或标 `inferred`；取舍全部进 `cut_log`。

## Step 5 — 模板内装配 PPTX（脚本）

```bash
python /skills/weekly-skill/scripts/build_deck.py --outline /app/work/outline.json \
  --template <模板.pptx> --out /app/output/<case_id>_deck.pptx \
  --max-slides <案例页数约束> --report /app/work/build_report.json
```

读回 `build_report.json`：
- 每页 `fit`（est_h/avail_h/ratio、size_overrides_pt、needs_split、
  trimmed_count）与 `trims`（被阶梯裁掉的 bullet 明细）；
- `layout_usage`（每页实际版式与选择方式——模板继承对账依据）、
  `demotions`（超预算降级为 backup 的页）、`figure_status`、
  `adaptations`、`warnings`。

**needs_split 的页由你拆成两页**（裁剪和缩字号已自动做过仍不够），改
outline 重跑——不要指望脚本硬塞。demotions 非空且你不同意脚本的选择 →
回 Step 4 调整 outline 再跑。迭代 ≤2 轮，变更记入 `change_records`。

## Step 6 — 渲染预览 + 整册一致性扫描（脚本 → 你决策）

```bash
python /skills/weekly-skill/scripts/render_preview.py \
  --pptx /app/output/<case_id>_deck.pptx --outdir /app/output/previews
python /skills/weekly-skill/scripts/check_deck.py \
  /app/output/<case_id>_deck.pptx --out /app/work/check_report.json \
  --pdf /app/output/previews/<case_id>_deck.pdf
```

1. render_report 审计：`slides_without_notes` 必须为 0（讲稿是交付物）；
   `gap_marker_count` 与 outline 里的 missing 图数量一致；无 LibreOffice →
   `render_gap` **如实**写进 result.json（status: "unavailable" + 原因）。
2. check_deck findings 逐条读（**整册字体/字号/溢出/变形检查是本 Skill
   的核心资产**，每条 finding 带 `fix` 指引），error 级必须处理：
   - `OVERFLOW_EST` → 你改 outline（删 bullet/降层级/拆页/换版式），回
     Step 5 重跑；
   - `FONT_SIZE_FLOOR` / `IMAGE_DISTORTION` → 按 fix 处置（提回地板、
     重放图片保纵横比）；
   - `PDF_PAGE_MISMATCH` → 重导出 PDF；
   - `FONT_OVERRIDE` / `COLOR_OVERRIDE`（warn）→ 说明或修正；本包装配
     本应零硬编码，出现即回查 outline/装配路径。

修复循环最多 2 轮；仍剩 error 就在 result.json 里如实标注 `partial` +
残留项，绝不静默吞掉。

## Step 7 — 完成契约输出与复核

1. 把 `/app/output/result.json` 补成终稿：契约字段全部填充；
   `presentation`（deck/pdf 路径+页数）、`page_evidence_map`（逐页
   claim/locator/quote/strength）、`template_inheritance`（layouts_used
   从 build_report 读回、主题字体/色板摘要、size_overrides 审计——
   本包 `hardcoded_visual_overrides` 恒为 0）、`consistency_scan`
   （check_report 摘要 + fix_rounds）、`render_preview`、`sources`
   （含 sha256）、`cut_log`、`qa_prep`、`uncertainty`、`change_records`；
   status 置 `complete`（或 `partial` + 原因）。
2. 另写人类可读的 `/app/output/outline.md`：大纲 + 版式映射决策表 +
   取舍决策表 + 问答清单（可编辑产物）。
3. 校验直到退出码为 0：

```bash
python /skills/weekly-skill/scripts/check_result.py \
  --result /app/output/result.json --case /input/case.json
```

4. 自查三问：每页版式真的来自模板（layout_usage 可对账）？每页文字
   数字与源材料逐字一致（evidence 可复核）？整册一致性（字号地板/
   图片不变形/零硬编码）扫描通过或如实标注？任何一问答"否"→ 回对应
   Step 修复。

## 硬规则（违反即产物不合格）

1. **新页只用 `safe_add_slide(layout)`**（脚本已内置）：真实克隆版式，
   绝不复制现有页，杜绝 partname 碰撞；
2. **零硬编码视觉**：不写字体名、不写 RGB 颜色；唯一例外是字号阶梯且
   全部记录在 build_report（check_deck 的 FONT_OVERRIDE/COLOR_OVERRIDE
   为证）；
3. **字号有下限**（默认 title≥20 / body≥14 / caption≥10pt）：装不下就
   走裁剪→缩字号→needs_split，绝不压到不可读；
4. **图片不变形**：占位符插入用 center-crop，自由区域用原纵横比 fit；
   caption 挂图片下方（重叠时回退页底）；缺图标 `[图缺失]`，不造假图；
5. **主题色/字体全部继承模板**——换一个模板，产出自动跟随；
6. **每页有 evidence**：source/locator + 逐字 quote，未改写事实。

## 异常处理

所有失败路径带机器可读原因码，处置见
/skills/weekly-skill/references/exceptions.md（TEMPLATE_MISSING /
LAYOUT_NOT_FOUND / NO_BODY_PLACEHOLDER / IMAGE_FILE_MISSING /
NEEDS_SPLIT / FONT_SIZE_FLOOR / IMAGE_DISTORTION / PDF_PAGE_MISMATCH 等）：
能自动补偿的自动补偿并记入报告，不能的显式落进 result.json 的
uncertainty/limitations，绝不静默吞掉。

## 适用边界

适用：给定模板 + 论文/材料 + 受众/时长/页数约束的学术汇报适配；
换模板重跑产出自动跟随主题。
不适用：无模板的通用 PPT 生成、论文精读本身、科研绘图素材生产
（相邻课题职责）；不代答"材料里不存在的数据"——缺口如实标注是特性，
不是失败。

## 文件

- `scripts/parse_sources.py` — 源材料解析（只读，带 sha256 与定位）
- `scripts/analyze_template.py` — 模板能力清单（只读；w08 核心差异化）
- `scripts/build_deck.py` — 模板内装配（outline→版式克隆 + 容量阶梯）
- `scripts/render_preview.py` — PDF 渲染 + 往返校验
- `scripts/check_deck.py` — 整册一致性审计（fix 循环的输入；w08 核心资产）
- `scripts/check_result.py` — result.json 契约校验
- `scripts/tmpl_common.py` — 共享库（几何/主题/容量估算/角色映射）
- `references/output-schema.md` — outline.json / result.json 数据模式
- `references/scenario-playbooks.md` — 三场景判据展开
- `references/adaptation-rules.md` — 映射/阶梯/图片/颜色规则细节
- `references/exceptions.md` — 异常码字典与处置路径
- `examples/` — 最小调用示例（源自 arXiv:1706.03762 真实材料，含溯源）

依赖：python-pptx >= 1.0（1.0.2 实测）、Pillow、lxml；PDF 渲染用环境
LibreOffice（render_preview.py 自动发现，缺失时如实记录 render_gap）。
