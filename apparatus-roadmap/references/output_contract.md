# 输出契约（result.json）

## 目录布局（评测运行时）

```
/app/output/
  result.json            结构化结果（本文件约束的对象）
  <name>.svg             可编辑主源（分层：frame/structure/annotation/source）
  <name>.png             渲染预览（位图）
  <name>.pdf             导出件（cairosvg 可用时矢量，否则位图 PDF）
  <name>.geometry.json   几何报告（盒子/锚点/溢出警告/字体）
  consistency_report.json 双向校验报告
  intermediate.json      当前 IR（改图的真源，随交付保存）
```

## result.json 字段

`case_id` 必填；`status`、`sources`、`uncertainty` 是校验基线字段
（`check_result.py` 始终检查，无论有无契约）。其余字段名：**案例的
output_contract 给了什么字段就用什么字段名**（不发明、不改名、不改值形状）；
案例没给时用下列模板：

| 字段 | 内容 | 填法 |
|-|-|-|
| status | `"complete" / "partial" / "failed_input" / "failed_render"` | 如实 |
| sources | `[{"path", "sha256", "role": "material"}]` | 从 materials_index.json 搬运 |
| run_status | `{"steps": [已完成步骤]}` partial 时列残留步骤与影响 | 如实 |
| figure | `{"figure_type", "title", "editable_source": {"path", "format": "svg", "layers": [...]}, "exports": [{"path", "format", "check"}], "preview": {"path"}} | exports[].check 写实测检查（如 "PDF 打开有效/位图 96dpi/字体已栅格化"） |
| element_sources | `[{"id", "label", "source_location", "quote"}]` 每个部件/连接/节点/边一条 | 从 IR 的 source 对象搬运 |
| data_mapping | 线型/介质颜色/不确定标记 → 含义 | 从图例搬运（material 实线/signal 虚线/…/△ 规格未提供） |
| provenance | `{"source_document": {...}, "tool", "generated_at", "change_records": [...]}` | change_records 来自 IR.change_log |
| uncertainty | `[{"item", "handling"}]` 每个未定项 | 与图上 △/灰虚线一一对应 |

## 硬规则

1. **未答字段显式 null + 原因**：字段值 `null`，同时在顶层
   `"null_reasons": {"字段": "一句原因"}` 里登记（check_result.py 认这种写法）。
   没有原因的 null 在终验中算不完整。
2. 第一步**亲笔**写 result.json 骨架（全字段 null + null_reasons +
   status "running"）；最后用 `python scripts/check_result.py --result
   result.json --case /input/case.json` 终验（exit 1 = 契约字段缺失或
   null 无原因或基线缺失，必须补后重跑）。
3. 部分结果必须写明边界：partial 时在 run_status.steps 列出未完成步骤，
   在 uncertainty 里说明影响范围。
4. 不虚构软件状态（字体没找到就写 font_notes 的原话；PDF 走了位图就写 raster）。
