# 最小调用示例（基于真实论文，输出为示意样本）

> 本文件是 Skill 的最小调用演示：输入真实、脚本命令真实、输出片段真实截取自
> 本地验证运行；**输出标明为示例，不冒充正式案例结果**。

## 输入

材料：arXiv:1706.03762v7《Attention Is All You Need》（Vaswani et al., 2017）
- PDF sha256: `bdafaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697`
- 摘要逐字引文（arXiv abs 页）：
  "We propose a new simple network architecture, the Transformer, based solely
  on attention mechanisms, dispensing with recurrence and convolutions entirely."
- 正文逐字引文（PDF p.5, §3.2.2）：
  "Multi-head attention allows the model to jointly attend to information from
  different representation subspaces at different positions."
- 正文逐字引文（PDF p.9, §5.4）：
  "single-head attention is 0.9 BLEU worse than the best setting, quality also
  drops off with too many heads."

约束（示例）：组会 / 10 分钟 / ≤8 页 / lab 模板（layout 名为中文）

## 调用（SKILL.md 七步中的关键三步）

```bash
# Step 2 解析源材料
python /skills/weekly-skill/scripts/parse_sources.py \
  --input /input/materials --out /app/work/materials_index.json

# Step 5 装配（Agent 已在 Step 3/4 完成场景判据与页级大纲 outline.json）
python /skills/weekly-skill/scripts/build_deck.py \
  --outline /app/work/outline.json --out /app/output/case_deck.pptx \
  --template /input/template_lab.pptx --max-slides 8 \
  --report /app/work/build_report.json

# Step 6 渲染预览 + 往返校验
python /skills/weekly-skill/scripts/render_preview.py \
  --pptx /app/output/case_deck.pptx --outdir /app/output/previews
```

## 示意输出（截取自本地验证运行，标注：示例）

outline.json 单页片段（Agent 判断的页级主张 + 证据指针）：

```json
{
  "page_no": 4,
  "type": "content",
  "priority": "P0",
  "title": "方法主干：多头注意力让模型同时在多个表示子空间里对齐信息",
  "evidence": [
    {"locator": "1706.03762.pdf p.5 §3.2.2",
     "quote": "Multi-head attention allows the model to jointly attend to information from different representation subspaces at different positions.",
     "strength": "direct"}
  ],
  "figures": [{"path": "materials/fig1_architecture.png",
               "caption": "Figure 1: The Transformer - model architecture",
               "status": "available", "locator": "1706.03762.pdf p.3 Figure 1"}],
  "notes": "指着右边的架构图讲：……这里停 90 秒，是全场最重要的一页。"
}
```

build_deck.py 汇报行（真实运行输出）：

```
{"status": "ok", "deck": ".../case_deck.pptx", "content_pages": 8,
 "backup_pages": 2, "total_slides": 10, "warnings": []}
```

build_report.json 中的模板适配记录（示例：模板 layout 名为中文，名称匹配失败
后走占位符签名回退，正文页正确落到带 body 占位符的版式）：

```json
{"page": 2, "type": "content", "layout": "正文版式A",
 "selection": "signature match (正文版式A)"}
```

check_result.py 终检（真实运行输出，示例）：

```
{"status": "pass", "contract_fields": 8, "filled": 8,
 "nulled_with_reason": 0, "coverage": 1.0, "errors": [], "warnings": []}
```

## 一个诚实的缺口处理示例

Table 1（p.6）图片未从 PDF 提取。处置：该页 `figures.status = "missing"`，
装配脚本在页面上打出 `[图缺失] Table 1（源：1706.03762.pdf p.6 Table 1）`
标注框（不造假图），讲稿改为口述原表数字，`uncertainty` 里记录该缺口。
