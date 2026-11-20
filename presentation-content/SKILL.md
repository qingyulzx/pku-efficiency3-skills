---
name: weekly-skill
description: Organize a paper or research material into an audience-aware academic presentation. Turns source materials plus audience/duration/slide constraints into a page-level outline (one claim per page with evidence locators and quotes), an editable template-based PPTX with speaker notes, rendered previews, and a verifiable result.json with cut decisions. Use when preparing group-meeting / defense / review talks from papers or research materials, or when a task asks to organize academic reporting content into slides with evidence mapping.
---

# 学术汇报内容组织（audience-aware slide content organization）

目标：把研究材料组织成**服务于指定听众与时长**的可讲页面——不是把论文压缩一遍。
判断（取舍、主张、顺序）由 Agent 做解析后亲自完成；脚本只做解析、装配、校验。
全程在 `/app/work` 工作，最终产物进 `/app/output`。先读 `/input/case.json` 与 task.md，
**以真实文件为准，不要按记忆或标签假设材料内容**。

进度自检清单（走一步勾一步）：
```
- [ ] Step 1 读输入 + 保底 result.json
- [ ] Step 2 解析源材料
- [ ] Step 3 场景判据 + 受众计划
- [ ] Step 4 页级大纲 + 取舍留痕
- [ ] Step 5 装配 PPTX
- [ ] Step 6 渲染预览 + 自检
- [ ] Step 7 契约输出 + 校验
```

## Step 1 — 读输入，先落保底产出

1. 读 `/input/case.json` 与 task.md。确认：`case_id`、材料文件路径、约束
   （受众/时长/页数/模板）、`output_contract`（dict 或 list；可能不存在）。
2. **立刻**写 `/app/output/result.json` 保底版：`case_id` + 契约全部字段（有契约逐字段
   镜像，无契约用 /skills/weekly-skill/references/output-schema.md §3 默认契约）+ 每字段 `null` +
   `null_reasons: {"字段": "Step N 产出"}` + `status: "running"`。
   之后每个 Step 只增强、不删除已填字段。
3. 建工作目录 `/app/work`。

**异常处置**：case.json 读不了 → result.json 写 `status: "failed_input"` + 原因，停止并如实报告；
材料路径不存在 → 记入 `uncertainty`，继续处理存在的材料（保底优先于完美）。

## Step 2 — 解析源材料（脚本）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <材料文件或目录> \
  --out /app/work/materials_index.json
```

读回 `materials_index.json`，重点看：各文件的 sha256 与状态、章节/页文本、
`figures_tables`（图/表清单与页码）、公式行、模板 pptx 的 layouts 清单。

**异常处置**：PDF 提示文字极少（扫描件）→ 记 `uncertainty`，可用容器 ocr-tool 的就走
OCR 后重跑解析，没有工具就只按可读部分设计并在 result.json 声明；某文件 `status:
"error"` → 不编造其内容，缺口进 `uncertainty`。

## Step 3 — 定场景与听众计划（判据在此，用前速查）

按下表把案例的受众/时长转成**页配比与讲述策略**（这是本题核心决策，先做再往下走）：

| 场景 | 听众要什么 | 页配比重点 | 叙事顺序 | 问答压力 |
|------|-----------|-----------|----------|----------|
| **组会** | 方法细节、进度、下一步 | 方法+进度+下一步 ≥60% | 上次→这次解决/卡在哪→证据→下一步 | 中：替代方案、结果稳定性 |
| **答辩** | 创新点、边界、对比 | 创新+对比+边界 ≥50% | 缺口→创新点声明（早）→证据链→正面对比→主动边界 | 高：特例质疑、泛化、检验 |
| **评审** | 结论、证据强度、风险 | 结论先行，背景 ≤1 页 | 结论+最硬证据（第 1 页）→逐页加固/限定 | 书面追问：数据补充 |

配套硬规则（三场景通用，Step 4/5 都要用）：
- **每页一句主张**：标题写成可讲出口的判断句，不写名词标签。
- **时长预算**：约 60–75 秒/页；案例给了 `slide_count` 以案例为准，冲突时保页数上限。
- **证据强度四档**：`direct`（逐字对应）/ `indirect`（多处合并）/ `inferred`（外推，
  需说明假设）/ `gap`（材料无支撑——页面保留主张但打 `[证据缺口]`，**绝不编造**）。
- **砍页优先级**：P0 主张+核心证据 → P1 背景/方法主干 → P2 扩展结果 → P3 礼节/延伸；
  从 P3 开始砍，砍掉的都进 `cut_log`（内容、原因、去向）。

产出 `/app/work/audience_plan.json`：`goal`（这次汇报要达成什么，一句话可检查）、
`scenario`、`audience_prior`（听众先验/关注点）、页配比决策、依据（对照上表）。
深挖某场景时再读 /skills/weekly-skill/references/scenario-playbooks.md（展开版判据+问答模式+完成标准）。

## Step 4 — 设计页级大纲与取舍（Agent 亲自判断）

这是 agent-in-the-loop 的核心步骤——**不要交给脚本**。基于 Step 2 的材料索引与
Step 3 的受众计划，逐页决定：

1. **页序**：服务于 Step 3 的叙事顺序，不按论文章节搬运。
2. **每页**：唯一主张（title）+ ≤5 条要点（bullets）+ evidence（locator 文件+页/节、
   逐字引文 ≤40 词、strength 四档）+ figures（有图绑定图路径，无图标 missing）+
   notes（口语化讲稿：过渡句、数字读法、指图动作；**不复读 bullets**）+ qa（预期追问
   与口径一致的回答）+ priority（P0–P3）。
3. **取舍**：被砍内容全部进 `cut_log`（内容、对照判据的原因、去向：backup 页或仅留材料）。
4. **问答预演**：每页过一遍"机制/数据/边界/价值"四问；关键追问配 backup 页。

按 /skills/weekly-skill/references/output-schema.md §2 的 schema 写 `/app/work/outline.json`。
**异常处置**：材料撑不起某场景关键页 → 该页 evidence 用 `gap` + 明确缺口描述；
时长/页数冲突 → 按优先级砍并留痕；无逐字引文支撑的数字 → 不上页或标 `inferred`。

## Step 5 — 装配可编辑演示文件（脚本）

```bash
python /skills/weekly-skill/scripts/build_deck.py --outline /app/work/outline.json \
  --out /app/output/<case_id>_deck.pptx \
  --template <案例模板.pptx 或省略> --max-slides <案例页数约束> \
  --report /app/work/build_report.json
```

读回 `build_report.json`：layout_usage（模板适配）、adaptations（无占位符时的文本框
回退）、demotions（超预算降级到 backup 的页）、figure_status。若 demotions 非空且
你不同意脚本的选择 → 回 Step 4 调整 outline 再跑（≤2 轮迭代，把变更记入
`change_records`）。

**异常处置**：模板缺失/不可读 → 脚本自动回退默认模板并在 report 记录（result.json
里如实说明）；图缺失 → 脚本打 `[图缺失]` 标注框，不造假图——如果你能从材料数字重排
一个表格页替代，回 Step 4 加 backup 页。

## Step 6 — 渲染预览与质量自检

```bash
python /skills/weekly-skill/scripts/render_preview.py \
  --pptx /app/output/<case_id>_deck.pptx --outdir /app/output/previews
```

1. 看 render_report.json + 打开渲染出的 PDF/PNG 逐页检查：文字不溢出、母版被尊重、
   `[图缺失]` 只出现在真实缺图处、页脚 locator 可读。
2. audit 部分：`slides_without_notes` 必须为 0（讲稿是交付物）；
   `gap_marker_count` 与 outline 里的 missing 图数量一致。
3. 发现问题 → 修 outline 或约束，回 Step 5 重跑（记 `change_records`）。

**异常处置**：环境无 LibreOffice → 报告里会有 `render_gap`，**如实**写进
result.json 的 `render_preview`（status: "unavailable" + 原因），audit 部分仍可交付；
转换超时/失败 → 重试一次，仍失败则同上处置。

## Step 7 — 完成契约输出与复核

1. 把 `/app/output/result.json` 补成终稿：所有契约字段填充；`page_evidence_map`
   （逐页 claim/locator/quote/strength）、`presentation`（deck 路径+页数+模板信息）、
   `speaker_notes`、`render_preview`、`sources`（含 sha256）、`cut_log`、`qa_prep`、
   `uncertainty`、`change_records`；status 置 `complete`（或 `partial` + 原因）。
2. 另写人类可读的 `/app/output/outline.md`：大纲 + 取舍决策表 + 问答清单（可编辑产物）。
3. 校验直到退出码为 0：

```bash
python /skills/weekly-skill/scripts/check_result.py \
  --result /app/output/result.json --case /input/case.json
```

4. 自查三问（task.md 的验收标准）：页面每个论断在源材料里有定位吗？叙事顺序服务
   于指定听众与时长吗？取舍过程他人可复核吗？任何一问答"否"→ 回对应 Step 修复。

## 适用边界

适用：已有研究材料（论文/数据/草稿）→ 指定听众与时长的汇报页面组织。
不适用：论文精读本身、成稿学术写作、科研绘图素材生产（相邻课题职责）；
不代答"材料里不存在的数据"——缺口如实标注是特性，不是失败。

## 最小调用示例

见 /skills/weekly-skill/examples/example-transformer.md（基于真实 arXiv 论文的示意输入/输出片段，
标注为示例，非正式案例结果）。
