# 最小调用示例

> 本目录是**使用示例**，不是正式案例结果。内容衍生自真实论文
> arXiv:1706.03762v7（Vaswani et al., *Attention Is All You Need*），
> 所有引文均为逐字摘录并标注页码/章节，可对照原文核对。

## 一次完整调用（论文 + 模板 → pptx + PDF）

```bash
# 0) 材料：源论文 PDF、模板 pptx，以及本目录的 content.example.json
#    （content 由 Agent 读论文后按 references/content-schema.md 撰写；
#     此处以这份现成的为例）

# 1) 模板能力分析 —— 决定每页用哪个版式
python scripts/analyze_template.py template.pptx --out manifest.json

# 2) 装配（新建模式）
python scripts/build_deck.py --template template.pptx \
    --content examples/content.example.json \
    --out deck.pptx --report build_report.json

# 3) 一致性扫描（fix 循环输入）
python scripts/check_deck.py deck.pptx --out check_report.json

# 4) 导出 PDF 后交叉核对页数
python scripts/check_deck.py deck.pptx --pdf deck.pdf

# 5) 编辑模式（当案例提供了 starting deck）
python scripts/build_deck.py --template template.pptx --start-deck starting.pptx \
    --content content.json --out adapted.pptx --report build_report.json
```

## 示意输出（节选，标明为示例）

`analyze_template.py` 的 manifest.json（示意，字段见 SKILL.md 步骤 3）：

```json
{
  "suggested_role_mapping": {
    "title":   [{"index": 0, "name": "Title Slide", "score": 3}],
    "content": [{"index": 1, "name": "Title and Content", "score": 3}],
    "picture": [{"index": 8, "name": "Picture with Caption", "score": 4}]
  },
  "themes": [{"colors": {"accent1": "#1F6FB2"}, "fonts": {"major_latin": "Georgia"}}],
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
    {"role": "content", "layout": "Title and Content",
     "fit": {"ratio": 0.62, "size_overrides_pt": {}}, "trims": []}
  ]
}
```

`check_deck.py`（示意）：

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
| 引文核对 | content.example.json 中每条 quote 均逐字存在于上述 PDF（章节/页码见 location 字段） |

示例内容中的数字（如 BLEU 28.4/41.8、450 万句对）均出自论文原文，
未做任何改写或外推。
