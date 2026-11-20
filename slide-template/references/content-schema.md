# content.json 契约（build_deck.py 输入）

```jsonc
{
  "deck": {                       // 元信息，进 build_report 与 result.json
    "title": "...",               // 汇报标题
    "audience": "...",            // 固定受众（来自案例约束）
    "duration_minutes": 12,       // 固定时长
    "slide_budget": "8-10 页",     // 固定页数预算
    "language": "中文为主，术语保留英文"
  },
  "delete_slides": [3],           // 仅编辑模式：删除 starting deck 的第 n 页（原始页序）
  "slides": [
    {
      // ---- 定位（二选一）----
      "slide_index": 2,           // 编辑模式：改这一页（原始页序）；缺省=追加新页
      "role": "content",          // 新页角色：title|section|content|two_content|picture|closing
      "layout": "Title Only",     // 可选：显式版式名或索引，覆盖 role 映射

      // ---- 内容 ----
      "title": "…",
      "subtitle": "…",            // title/section 页
      "bullets": [                // 正文，level 0-4
        {"level": 0, "text": "…", "bold": false},
        {"level": 1, "text": "…"}
      ],
      "image":  {"path": "fig.png", "caption": "图 1：…"},
      "images": [ {"path": "…", "caption": "…"}, {"path": "…"} ],  // 多图并排

      // ---- 讲稿与证据 ----
      "notes": "讲解要点……",
      "evidence": {
        "source": "arXiv:1706.03762v7",
        "location": "Section 3.2, Figure 1",
        "quote": "An attention function can be described as mapping a query…"  // 逐字
      }
    }
  ]
}
```

## 字段语义

- `role` 由 analyze_template 的 suggested_role_mapping 解析为版式；`layout` 显式指定总是优先，找不到则回退 role 匹配并记 `LAYOUT_NOT_FOUND` 警告。
- 编辑模式下，spec 里**只出现要改的字段**（有 `title` 才改标题，有 `bullets` 才换正文）——这就是保源编辑。
- `evidence.quote` 必须是源材料逐字引文；`location` 用章节/图表号，可被第三方核对。
- 图片路径不存在时：记 `IMAGE_FILE_MISSING` 警告，占位框保留为空，构建继续。

## build_report.json 关键字段（决策输入）

- `slides[i].fit.ratio`：估算文本高 / 可用高；>1.05 即危险。
- `slides[i].fit.size_overrides_pt`：该页写下去的字号覆盖（审计线索）。
- `slides[i].fit.needs_split`：true = 即使地板字号也装不下，必须由 Agent 拆页重跑。
- `slides[i].trims`：被容量阶梯裁掉的 bullet 明细（不是静默截断）。
- `change_log`（编辑模式）：每次 replace_title/replace_body/replace_notes/delete_slide 的前后对照。
