# result.json 输出契约

在 /app/output/result.json 交付，含 case_id 与 output_contract 的**全部**字段；
未完成的字段显式 `null` 并在同层或 `reasons` 里写明原因。字段值形状不得改变。

```jsonc
{
  "case_id": "<来自 /input/case.json>",

  // ---- 主结果：可编辑演示文件 ----
  "pptx_path": "output/deck.pptx",          // 相对 /app 或绝对路径
  "pdf_path": "output/deck.pdf",            // 渲染预览，与 pptx 同源导出
  "slide_count": 8,
  "deck_meta": {                             // 来自案例固定约束，原样回显
    "audience": "…", "duration_minutes": 12, "slide_budget": "8-10 页"
  },
  "outline": [                               // 页级结构：每页一行
    {"slide": 1, "role": "title", "claim": "本文主张……"}
  ],

  // ---- 页级证据映射（每页）----
  "evidence_map": [
    {
      "slide": 3,
      "claim": "顺序计算无法并行是算力瓶颈",
      "source": "arXiv:1706.03762v7",
      "location": "Abstract; Introduction para.1",
      "quote": "Recurrent neural networks … firmly established as state of the art…"
    }
  ],

  // ---- 模板继承（真实性可查）----
  "template": {
    "file": "template.pptx",
    "masters": 1,
    "layouts_used": ["Title Slide", "Title and Content", "Picture with Caption", "…"],
    "theme_fonts": {"major_latin": "…", "minor_latin": "…"},
    "theme_colors": {"accent1": "#…", "…": "…"},
    "hardcoded_visual_overrides": 0,          // 本包恒为 0：无字体名/RGB 写入
    "size_overrides_by_slide": {"5": {"0": 14.0}}   // 字号阶梯审计
  },

  // ---- 渲染与版本记录 ----
  "render_check": {
    "pdf_pages": 8, "pptx_slides": 8, "match": true,
    "font_substitutions": [],                 // 导出端观察到的替换，无则空
    "notes": "文本高度为估算，PDF 为最终裁判"
  },
  "run_record": {
    "mode": "new | edit",
    "steps": ["analyze_template", "build_deck", "check_deck x2", "export_pdf"],
    "fix_rounds": 1,
    "build_report": "output/build_report.json",
    "check_report": "output/check_report.json",
    "change_log": []                          // 编辑模式：before/after 对照
  },

  // ---- 状态、不确定性与限制 ----
  "status": "ok | partial | failed",
  "uncertainty": [
    "第 5 页文本高度为 CJK 估算模型，±10%；已用 PDF 目检确认无溢出"
  ],
  "limitations": [
    "第 7 页图片源文件缺失，占位框保留为空（IMAGE_FILE_MISSING）"
  ],
  "reasons": { "slides": null }               // 仅未完成字段需要
}
```

## 纪律

- 步骤 1 落盘的就是这份骨架（全字段、未答置 null + 原因）；
- 每个字段必须与实际产物一致：layouts_used 从成品 deck 读回，不凭记忆写；
- partial 是合法状态：残留 error、被裁剪内容、缺失资源都如实列出；
- 修复循环每轮的 diff（哪页改了什么）进 run_record，支撑他人复跑核对。
