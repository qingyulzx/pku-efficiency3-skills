# 学术汇报内容组织 Skill（w07）

把一篇论文/研究材料组织成**服务于指定听众与时长**的学术汇报：页级大纲、
可编辑 PPTX（含讲稿备注）、渲染预览、证据映射与取舍留痕。

## 它解决什么问题

同一份研究，组会讲方法与进度、答辩讲创新点与边界、评审讲结论与证据强度。
本 Skill 把「受众 × 时长 × 页数 × 模板」转成可执行的页级决策：每页一句主张、
每句主张带源材料定位与逐字引文、每个被砍的内容留痕、每个预期追问有口径
一致的回答。核心判断（取舍/主张/顺序）由 Agent 做；脚本只做解析、装配、校验。

## 依赖

- Python 3.9+，`python-pptx`（装配）、`pypdf`（PDF 解析，`pdfplumber` 可选更优）、
  `Pillow`（图片适配）、`python-docx`（docx 材料，可选）
- 渲染预览：LibreOffice `soffice`（可选；缺失时如实记录 render_gap，不影响其余产物）

## 安装与调用

Skill 目录即本包（SKILL.md 在根）。安装到 Agent 的 skills 目录后，Agent 按
SKILL.md 的 7 步执行；三个脚本的接口都可独立使用：

```bash
# 1) 解析材料 → materials_index.json（含 sha256/章节/图表清单/模板 layouts）
python scripts/parse_sources.py --input <材料文件或目录> --out materials_index.json

# 2) 装配演示文件（outline schema 见 references/output-schema.md §2）
python scripts/build_deck.py --outline outline.json --out deck.pptx \
  [--template tpl.pptx] [--max-slides N] [--report report.json]

# 3) 渲染预览 + 往返校验（页数/备注覆盖/图缺失标记/字体）
python scripts/render_preview.py --pptx deck.pptx --outdir previews

# 4) 契约校验（对照 case.json 的 output_contract）
python scripts/check_result.py --result result.json [--case case.json] [--base <根目录>]
```

## 目录结构

```
SKILL.md                        # 7 步工作流（判据内联在 Step 3 使用点）
README.md                       # 本文件
GITHUB_URL.txt
scripts/
  parse_sources.py              # 材料解析与清单（PDF/MD/TXT/DOCX/PPTX/图片）
  build_deck.py                 # 模板适配装配（占位符签名回退/图缺失标注/预算降级）
  render_preview.py             # soffice 渲染 + python-pptx 往返校验
  check_result.py               # 契约字段/显式 null+原因/产物路径存在性校验
references/
  scenario-playbooks.md         # 组会/答辩/评审三场景深度判据（按需读取）
  output-schema.md              # outline.json / result.json 数据模式
examples/
  example-transformer.md        # 真实论文（arXiv:1706.03762）最小调用示例（输出为示意）
```

## 输入与输出

**输入**：研究材料（论文 PDF/MD/DOCX，可含图与模板 PPTX）+ 受众/时长/页数约束
+ 输出契约（若有）。

**输出**（/app/output）：`result.json`（镜像契约字段 + 页级证据映射 + 取舍留痕 +
不确定性）、可编辑 `deck.pptx`（页脚带源定位、notes 带讲稿与问答预案、备用页）、
`previews/`（PDF 渲染 + render_report.json）、`outline.md`（人类可读大纲）。

## 异常处置一览（真实路径，非口号）

| 情况 | 处置 | 留痕 |
|------|------|------|
| 扫描件 PDF（文字极少） | 提示走 OCR；不可行则按可读部分设计 | uncertainty |
| 某材料解析失败 | 不编造内容，缺口如实标注 | materials_index status |
| 模板缺失/不可读 | 回退默认模板 | build_report warning |
| 模板 layout 名不匹配 | 占位符签名匹配 → 空白版式兜底 | layout_usage |
| 版式无 body 占位符 | 自动加文本框 | adaptations |
| 页数超预算 | 低优先级整页降级为备用页，绝不静默删除 | demotions |
| 图缺失 | `[图缺失]` 标注框，不造假图 | figure_status |
| 材料撑不起关键页 | evidence.strength=gap，页面打缺口标注 | uncertainty |
| 无 LibreOffice | render_gap 如实记录，audit 仍交付 | render_report |
| outline 非法 | 精确报错，不产半成品 | 退出码 2 |

## 适用边界

适用：已有研究材料 → 指定听众/时长的汇报页面组织与交付。
不适用：论文精读、成稿学术写作、科研绘图素材生产（相邻课题职责）；
不代答材料中不存在的数据——缺口如实标注是特性，不是失败。

## 本地验证

开发者本地用真实 arXiv 论文跑了完整 e2e（解析→大纲→装配→渲染→契约校验）
与 5 项异常路径测试；真实报错与修复记录见包外 `tests/` 与 `progress.md`
（测试产物不进包）。示意输出见 `examples/example-transformer.md`。

## 维护

单文件脚本、无第三方私有依赖；改判据只动 `references/scenario-playbooks.md`
与 SKILL.md Step 3 内联表；改输出字段形状须同步 `references/output-schema.md`
与 `scripts/check_result.py`。
