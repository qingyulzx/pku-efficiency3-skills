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

`case_id` 必填。其余字段名：**案例的 output_contract 给了什么字段就用什么字段名**
（不发明、不改名、不改值形状）；案例没给时用下列模板：

| 字段 | 内容 | 填法 |
|-|-|-|
| run_status | `{"status": "completed"/"partial"/"failed", "steps": [已完成步骤]}` | 如实 |
| figure | `{"figure_type", "title", "editable_source": {"path", "format": "svg", "layers": [...]}, "exports": [{"path", "format", "check"}], "preview": {"path"}} | exports[].check 写实测检查（如 "PDF 打开有效/位图 96dpi/字体已栅格化"） |
| element_sources | `[{"id", "label", "source_location", "quote"}]` 每个部件/连接/节点/边一条 | 从 IR 的 source 对象搬运 |
| data_mapping | 线型/介质颜色/不确定标记 → 含义 | 从图例搬运（material 实线/signal 虚线/…/△ 规格未提供） |
| provenance | `{"source_document": {...}, "tool", "generated_at", "change_records": [...]}` | change_records 来自 IR.change_log |
| uncertainty | `[{"item", "handling"}]` 每个未定项 | 与图上 △/灰虚线一一对应 |

## 硬规则

1. **未答字段显式 null + 原因**，两种等价写法：
   - 直接 `"figure": null` + 同级 `"figure_null_reason": "..."`；或
   - `"figure": {"value": null, "null_reason": "..."}`。
   没有原因的 null 在 finalize 校验中算不完整。
2. 第一步先 `finalize_result.py --init` 生成骨架（保底产出），最后
   `--finalize` 校验完整性（exit 1 = 有字段缺 null_reason，必须补）。
3. 部分结果必须写明边界：partial 时在 run_status.steps 列出未完成步骤，
   在 uncertainty 里说明影响范围。
4. 不虚构软件状态（字体没找到就写 font_notes 的原话；PDF 走了位图就写 raster）。
