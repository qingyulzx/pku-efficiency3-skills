# 输出模式（figure_model.json / result.json / case 输入期望）

本文件是 SKILL.md 各步骤产出的数据模式说明。Agent 负责判断与填充，脚本负责解析与校验；
任何一方都不得改变字段名或值的形状。

## 1. case 输入期望（/input/case.json，实际形状以运行时读到的为准）

常见形状（**先读真实文件，不要按这里的描述假设**）：

```json
{
  "case_id": "…",
  "materials": ["…pdf/路径…"],
  "constraints": {
    "language": "…（若给出）",
    "canvas": "…（若给出）",
    "format": "svg + png + pdf（默认三端）"
  },
  "output_contract": { "字段名": "要求描述", "…": "…" }
}
```

- `output_contract` 可能是 dict、list，也可能不存在。存在时：result.json 必须逐字段镜像；
  答不了的字段保留键名、显式 `null`，并在 `null_reasons` 里写一句原因。
- 不存在时：使用本文件 §3 的默认契约。

## 2. 中间产物（Step 3 / Step 4 产出）

### worksheet（Agent 亲笔，模板见 templates/agent_worksheet.md）

五张表：question / entities / relations / data / conclusions。每行必须带
**逐字引文**（材料文本的原样子串，只修 PDF 换行）与 **locator**（文件 + 页/节/句，
精确到人几秒内能定位）。材料里不存在的数字不画，记入 `uncertainty`。

### figure_model.json（Step 4 产出，Step 5 渲染输入；完整字段见 references/model_schema.md）

```json
{
  "schema": "graphical-abstract/1",
  "case_id": "与 case.json 一致",
  "canvas": {"width": 1800, "height": 1000},
  "panels": [
    {
      "id": "p-question",
      "role": "question | method | results | conclusion | custom",
      "heading": "面板标题",
      "layout": "flow | chart | stats | text",
      "…": "（各 layout 的元素清单见 model_schema.md）",
      "elements_or_nodes": [
        {"id": "ent-1", "label": "…",
         "source": {"file": "materials/paper.pdf",
                    "locator": "p.2 §Results sentence 3",
                    "quote": "逐字引文（含要画的数字）"}}
      ]
    }
  ],
  "caption_note": "不上画面的限定语写进 notes/caption，不进画布"
}
```

字段约束（build_figure.py / ga_lib 加载与校验时硬执行）：

- 顶层必须有 `schema`（钉死 `graphical-abstract/1`）、`case_id`、`panels`（1–6 个）。
- 每个上画面的数据元素必须带 `source.quote`；quote 必须是材料文本的**逐字子串**
  （check_figure.py 用 sources.json 复核，抓编造数字与改写）。
- 画布坐标为像素、y 向下；字号下限默认 12px（`checks.min_font_px`），越界即报错。

### sources.json（供引文核对）

```json
{ "materials/paper.pdf": "<完整提取文本>" }
```

由 Agent 从真实材料生成；build_figure.py / check_figure.py 的 `--sources` 参数用它
做引文逐字核对。

## 3. result.json（Step 7 终稿；Step 1 先写全 null 保底版）

案例没给 `output_contract` 时，用下面的**默认契约**（逐字段镜像）：

| 字段 | 含义 |
|---|---|
| `graphical_abstract_svg` | 可编辑 SVG 产物路径（真源：命名 id、layer-* 组、逐元素 provenance `<desc>`） |
| `graphical_abstract_png` | 光栅预览路径（300 dpi；无 matplotlib 时为 Pillow 降级，如实声明） |
| `graphical_abstract_pdf` | 矢量导出路径 |
| `figure_model` | 模型文件路径（可编辑中间表示） |
| `scientific_summary` | 与单页图形对应的文字总结（问题→方法→结果→结论） |
| `element_source_map` | 三层证据链：element → quote → locator（来自 element_map.json） |
| `export_checks` | 渲染/导出检查摘要（来自 export_report.json：layout、各端产物、failures、checks） |
| `uncertainty` | 如实列出的缺口与降级（无源数字、扫描件未 OCR、导出失败等） |
| `sources` | 材料文件清单（含 sha256） |

```json
{
  "case_id": "…",
  "status": "running | complete | partial | failed_input | failed_render",
  "output_contract 镜像字段": "……（存在契约时逐字段镜像；答不了 = null + null_reasons）",
  "element_source_map": [ {"id": "p-results.bar-1", "panel": "…",
                            "quote": "…", "locator": "…", "encoding": "…"} ],
  "export_checks": {"layout": "…", "svg": {"…": "…"}, "png": {"…": "…"},
                    "pdf": {"…": "…"}, "failures": [], "checks": {"…": "…"}},
  "render_preview": {"png": "…", "status": "ok | fallback | unavailable",
                     "render_gap": "…"},
  "scientific_summary": "…",
  "uncertainty": ["如实列出：材料没有的数字、导出降级、扫描件等"],
  "null_reasons": {"字段名": "未答原因（一句）"},
  "sources": [{"path": "…", "sha256": "…", "role": "material"}]
}
```

校验：`python /skills/weekly-skill/scripts/check_result.py --result result.json --case case.json`。
退出码 0 才算通过；错误信息逐条修复后重跑。

## 4. 目录约定

- 工作区：`/app/work/`（materials_index.json、sources.json、worksheet、figure_model.json、out/）
- 产物：`/app/output/`（result.json、graphical_abstract.svg/.png/.pdf、figure_model.json）
- Skill 根：`/skills/weekly-skill/`（脚本用 `python /skills/weekly-skill/scripts/<x>.py`）
