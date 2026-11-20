---
name: academic-ppt-template-adaptation
description: 把固定论文/研究材料适配进指定 PPT 模板，产出可编辑 pptx + 渲染 PDF + 逐页证据映射。分析模板母版/版式/占位符能力，按内容角色映射版式，容量阶梯（裁剪→缩字号有下限→建议拆页），图片纵横比保持（caption 挂 PlaceholderPicture 下方），主题字体颜色零硬编码，整册一致性扫描与修复循环。适用于：给定模板 + 论文/材料 + 受众/时长/页数约束的学术汇报生成，以及 starting deck 的保源编辑。
---

# 学术 PPT 模板与格式适配 Skill

把一篇论文（或研究材料）组织成**真正套用指定模板**的学术汇报：母版/版式/占位符继承可查、页内文字数字与源材料对得上、整册一致性可扫描、导出件可复核。你（Agent）负责所有判断密集型决策（主线提取、内容→版式映射、修复决策）；脚本只做解析、装配、扫描。

## 输入（/input/case.json + task.md）

确认这几样东西，缺哪样就在 result.json 里如实标注：

- `template.pptx`（必需）——母版/版式/主题的来源，**永远从它或它的派生 deck 出发**；
- 源材料：论文 PDF / 文档（事实依据，逐字引用而非改写）；
- `starting_deck.pptx`（可选）——存在时进入**保源编辑模式**（见步骤 4）；
- 固定约束：受众、时长、页数预算（在 case.json 或 task.md 里找）。

## 工作流（7 步，每步先落盘再前进）

### 步骤 1 — 契约先行（保底产出）
立即在 /app/output 写 `result.json` 骨架：case_id + output_contract 全字段，未完成的字段显式 `null` 并写原因（如 `"slides": null, "reason": "extraction not started"`）。此后每完成一步就更新它。**任何时刻中断都有可提交产出。**

### 步骤 2 — 读源材料，提取主线
用 pdf-text-tool（或等价工具）抽取论文文本。自己判断并整理：
- 研究问题 → 方法 → 结果 → 限制 四段主线；
- 每个关键主张的**逐字引文 + 位置**（章节/图表号）——这是后面每页 evidence 的原料；
- 图表清单：哪些图/表值得上页面，编号是什么。
数字、结论、图号必须与源文一致，不得改写事实。

### 步骤 3 — 模板能力分析（脚本）
```
python scripts/analyze_template.py <template.pptx> --out manifest.json
```
读 manifest.json 的四块输出再决策：
- `suggested_role_mapping`：六个角色（title/section/content/two_content/picture/closing）→ 版式候选；
- `themes`：主题色板与主题字体（后面一切视觉继承的来源）；
- `text_style_ladders_pt` + `readability_floors_pt`：字号阶梯与下限；
- `anomalies`：无标题版式、超小正文占位符、无图片版式等——映射时绕开或在 content 里补偿。

**你做映射决策**：每页选 role（或显式 layout 名覆盖）。anomalies 里的坑要内化，例如无图片版式的模板，图片页会走自由区域放置。

### 步骤 4 — 写 content.json 并装配（脚本）
按 `references/content-schema.md` 写 slides 数组：每页 role/layout、title、bullets（level 0-4）、image（path+caption）、notes、evidence（source/location/quote）。然后：

```
# 新建模式（无 starting deck）
python scripts/build_deck.py --template template.pptx --content content.json \
    --out deck.pptx --report build_report.json

# 保源编辑模式（有 starting deck）：只在指定页上动刀，其余页原样保留
python scripts/build_deck.py --template template.pptx --start-deck starting.pptx \
    --content content.json --out deck.pptx --report build_report.json
```
编辑模式用 `slide_index`（以输入 starting deck 的原始页序为基准）+ `delete_slides`；无 `slide_index` 的 spec 追加新页。

读 build_report.json 的每页 `fit`（est_h/avail_h/ratio、size_overrides_pt、needs_split）、`trims`（被裁掉的 bullet）、`warnings`。**needs_split 的页由你拆成两页重跑**，不要指望脚本硬塞。

### 步骤 5 — 一致性扫描 + 修复循环（脚本 → 你决策）
```
python scripts/check_deck.py deck.pptx --out check_report.json [--pdf deck.pdf]
```
逐条读 findings（slide/shape/code/severity/message/fix），error 级必须处理：
- `OVERFLOW_EST` → 你改 content.json（删 bullet/降层级/拆页），重跑步骤 4；
- `FONT_SIZE_FLOOR` / `IMAGE_DISTORTION` / `COLOR_OVERRIDE` / `FONT_OVERRIDE` → 按 fix 提示处置；
- `PDF_PAGE_MISMATCH` → 重导出。
修复循环最多 2 轮；仍剩 error 就在 result.json 里如实标注为 partial 并说明残留项。

### 步骤 6 — 导出与渲染核对
用 office-renderer（LibreOffice）把 deck.pptx 转成 PDF，再跑一次 check_deck 带 `--pdf`。确认：页数一致、无字体替换告警、图片完整。有偏差记录进 result.json 的渲染记录。

### 步骤 7 — 收尾 result.json
按 `references/output-contract.md` 补全所有字段：主结果（pptx/PDF 路径）、逐页证据映射（每页 source/location/quote）、模板继承说明（用的哪个 layout、manifest 摘要）、渲染与版本记录（build_report/check_report 摘要 + 修复轮次）、不确定性（估计器 vs 渲染的差异、被裁剪的内容）。对照骨架确认没有字段漏掉。

## 硬规则（违反即产物不合格）

1. **新页只用 `add_slide(layout)`**（脚本已内置安全版）：真实克隆版式，绝不复制现有页；
2. **零硬编码视觉**：不写字体名、不写 RGB 颜色；唯一例外是字号阶梯且全部记录在 build_report；
3. **字号有下限**（默认 title≥20 / body≥14 / caption≥10pt）：装不下就走裁剪→缩字号→needs_split，绝不压到不可读；
4. **图片不变形**：占位符插入用 center-crop，自由区域用原纵横比 fit；caption 挂在返回的 PlaceholderPicture 下方（重叠时回退页底）；
5. **主题色/字体全部继承模板**——换一个模板，产出自动跟随；
6. **每页有 evidence**：source + location + 逐字 quote，未改写事实。

## 异常处理

所有失败路径带机器可读原因码，处置见 `references/exceptions.md`（UNREADABLE_PPTX / LAYOUT_NOT_FOUND / NO_BODY_PLACEHOLDER / IMAGE_FILE_MISSING / NEEDS_SPLIT / FONT_SIZE_FLOOR / IMAGE_DISTORTION / PDF_PAGE_MISMATCH 等）：能自动补偿的自动补偿并记入报告，不能的显式落进 result.json 的 uncertainty/limitations，绝不静默吞掉。

## 文件

- `scripts/analyze_template.py` — 模板能力清单（只读）
- `scripts/build_deck.py` — 模板内装配（新建/编辑两种模式）
- `scripts/check_deck.py` — 整册一致性审计（fix 循环的输入）
- `scripts/tmpl_common.py` — 共享库（几何/主题/容量估算/角色映射）
- `references/content-schema.md` — content.json 契约
- `references/adaptation-rules.md` — 映射/阶梯/图片/颜色规则细节
- `references/exceptions.md` — 异常码字典与处置路径
- `references/output-contract.md` — result.json 字段契约
- `examples/` — 最小调用示例（源自 arXiv:1706.03762 真实材料，含溯源）

依赖：python-pptx >= 1.0（1.0.2 实测）、Pillow、lxml；PDF 导出用环境提供的 office-renderer。
