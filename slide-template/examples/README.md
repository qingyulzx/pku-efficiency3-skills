# 最小调用示例

> 本目录是**使用示例**，不是正式案例结果。内容衍生自真实论文
> arXiv:1706.03762v7（Vaswani et al., *Attention Is All You Need*），
> 所有引文均为逐字摘录并标注页码/章节，可对照原文核对。

## 一次完整调用（材料 + 模板 → 可编辑 pptx + 渲染 PDF + result.json）

```bash
# 0) 材料：源论文 PDF、模板 pptx；outline 由 Agent 读材料后按
#    references/output-schema.md §2 撰写（此处以这份现成的为例）

# 1) 源材料解析 —— 章节文本 / 图表清单 / 公式行，带定位与 sha256
python scripts/parse_sources.py --input paper.pdf --out materials_index.json

# 2) 模板能力分析 —— w08 核心差异化：版式/占位符/主题/字号阶梯清单
python scripts/analyze_template.py template.pptx --out manifest.json

# 3) Agent 读回 manifest（角色→版式候选、主题、anomalies）后写 outline.json，
#    每页带 type（角色）或 layout（显式版式名，从 manifest 抄）

# 4) 模板内装配（容量阶梯自动执行：裁剪→缩字号有地板→needs_split）
python scripts/build_deck.py --outline examples/outline.example.json \
    --template template.pptx --out deck.pptx --report build_report.json

# 5) 渲染预览 + 往返校验（无 LibreOffice 时 render_gap 如实记录）
python scripts/render_preview.py --pptx deck.pptx --outdir previews

# 6) 整册一致性扫描（fix 循环输入；带 PDF 交叉核对页数）
python scripts/check_deck.py deck.pptx --out check_report.json \
    --pdf previews/deck.pdf

# 7) 契约校验（退出码 0 才算通过）
python scripts/check_result.py --result result.json --case case.json
```

## 示意输出（节选，标明为示例）

`analyze_template.py` 的 manifest.json（示意，字段见 SKILL.md Step 2）：

```json
{
  "suggested_role_mapping": {
    "title":   [{"index": 0, "name": "Title Slide", "score": 3}],
    "content": [{"index": 1, "name": "Title and Content", "score": 3}],
    "picture": [{"index": 8, "name": "Picture with Caption", "score": 4}]
  },
  "themes": [{"colors": {"accent1": "#1F6FB2"}, "fonts": {"major_latin": "Georgia"}}],
  "readability_floors_pt": {"title": 20.0, "body": 14.0, "caption": 10.0},
  "anomalies": ["LAYOUT_WITHOUT_TITLE:Slide Master/Blank"]
}
```

`build_deck.py` 的 build_report.json（示意）：

```json
{
  "status": "partial",
  "mode": "new",
  "slide_count": 4,
  "needs_split_slides": [],
  "slides": [
    {"page": 2, "role": "content", "layout": "Title and Content",
     "layout_source": "role match",
     "fit": {"ratio": 0.62, "size_overrides_pt": {}, "needs_split": false},
     "trims": []}
  ]
}
```

`check_deck.py`（示意，findings 均带 fix 指引）：

```json
{"status": "pass", "summary": {"errors": 0, "warnings": 0, "by_code": {}}}
```

## 材料溯源

| 项 | 值 |
|-|-|
| 论文 | Attention Is All You Need, Vaswani et al., NeurIPS 2017 |
| 标识 | arXiv:1706.03762v7, DOI 10.48550/arXiv.1706.03762 |
| 本地源文件 | arXiv v7 PDF（15 页）及其 arXiv 摘要页 HTML |
| PDF SHA-256 | BDFAA68D8984F0DC02BEACA527B76F207D99B666D31D1DA728EE0728182DF697 |
| 摘要页 SHA-256 | 29E42A996471DB9C019F1122825CDAC0E6D64C96767D9EE5C0B8891DE6204BEE |
| 引文核对 | outline.example.json 中每条 quote 均逐字存在于上述 PDF（章节/页码见 locator 字段） |

示例内容中的数字（如 BLEU 28.4/41.8、450 万句对）均出自论文原文，
未做任何改写或外推。
