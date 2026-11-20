# IR 模式（intermediate representation）

IR 是本 Skill 的可编辑「真源」：所有判断（部件识别、连接方向、阶段划分）由 Agent 写进 IR，
渲染与校验脚本只消费 IR。改图 = 改 IR 后重渲重校（见 scripts/edit_ir.py），
绝不在导出的 SVG 上直接改。

IR 是一个 JSON 对象，`figure_type` 取 `apparatus`（装置图）或 `route`（技术路线/流程图）。

## 公共字段

| 字段 | 类型 | 必填 | 说明 |
|-|-|-|-|
| figure_type | "apparatus" \| "route" | ✓ | 图类型 |
| title | string | 建议 | 图标题（渲染在画布顶部） |
| subtitle | string | 可选 | 副标题 |
| canvas | {width, height} | 可选 | 画布**最小**尺寸（px）。渲染器只会放大不会裁剪：内容超出时画布自动扩展 |
| source_document | {id, title, version?} | 建议 | 材料标识（arXiv 号 / DOI / 文件名 + 版本），写入图内 provenance 行 |
| extraction_index | [item] | ✓ | 覆盖索引：材料中提到的**每个**部件/步骤一条（见下），是双向校验「覆盖检查」的数据源 |
| change_log | [record] | 编辑时自动 | edit_ir.py 追加的修改记录 |

### source 对象（每个部件/连接/节点/边必带）

```json
{"location": "§2.1 第2段 / Materials and methods p.3",
 "quote": "从材料逐字复制的原句（校验时做空白归一化后必须能在材料文本中找到）"}
```

- `quote` 必须逐字来自材料；改写、翻译、概括一律不允许（校验会硬失败）。
- `location` 写人能定位的形式：章节+段落，或页码+行号。

### certainty 枚举

| 值 | 含义 | 图面表现 |
|-|-|-|
| quoted（默认） | 材料明示 | 正常实线 |
| inferred | 连接为合理推断（材料未逐字写出 A→B，但明确写了上下游顺序） | 灰虚线 + 「(连接为推断)」标注 |
| unspecified_spec | 部件存在但规格未给 | 虚线框 + 「△ 规格未提供·示意」 |
| uncertain | 内容未完全确定 | 同上 |

## apparatus（装置图）

```json
{
  "figure_type": "apparatus",
  "components": [
    {"id": "C1",
     "label": "质量流量计 MFC-1",
     "type": "mfc",                     // 见 symbol_library.md 的类型表
     "specs": [{"key": "量程", "value": "0–100 mL/min"}],
     "certainty": "quoted",
     "source": {"location": "...", "quote": "..."}}
  ],
  "connections": [
    {"id": "L1",
     "from": "C1", "to": "C2",          // 箭头方向 = 物料/信号流向
     "medium": "N2",                    // 介质：决定线颜色（图例自动生成）
     "kind": "material",                // material|signal|energy，决定线型
     "conditions": [{"key": "流速", "value": "50 mL/min"}],
     "certainty": "quoted",
     "route": "below",                  // 可选：强制走下方回流廊道
     "source": {"location": "...", "quote": "..."}}
  ],
  "extraction_index": [ ... ]
}
```

- 连接拓扑决定布局：从左到右按「最长路径分层」排布；指向更早层（回流）或
  `route:"below"` 的连接走画布下方廊道，避免箭头反向穿过部件。
- 提到了部件但材料**没写它和谁连接**：仍放进 components，渲染时进入
  「材料未给出连接关系（未连线）」虚线区——不许编造连接。

## route（技术路线图 / 流程图）

```json
{
  "figure_type": "route",
  "nodes": [
    {"id": "S1",
     "kind": "start|end|stage|step|decision|milestone",
     "label": "样品制备",
     "step_no": "1.",                   // 与正文编号逐条对照
     "objective": "获得均匀前驱体",       // stage/step 附加行
     "methods": ["水热合成"], "inputs": ["TEOS"], "outputs": ["前驱体凝胶"],
     "milestone": "批次重复性 CV<5%",     // 画金色里程碑标记
     "certainty": "quoted",
     "source": {"location": "...", "quote": "..."}}
  ],
  "edges": [
    {"id": "E1", "from": "S1", "to": "S2",
     "kind": "main|loop",               // loop 用灰色（回流/迭代）
     "label": "是", "condition": "活性≥90%",   // 决策分支条件
     "route": "below",                  // 回流边强制走下方
     "source": {"location": "...", "quote": "..."}}
  ],
  "extraction_index": [ ... ]
}
```

## extraction_index（覆盖索引 —— 正确性的抓手）

材料里提到的每个部件 / 每个步骤，一条记录：

```json
{"mention": "质量流量计", "quote": "two mass flow controllers (MFC)",
 "mapped_id": "C3"}                     // 画到图上 → 填元素 id
```

```json
{"mention": "备用冷阱", "quote": "a spare cold trap was available",
 "status": "omitted", "reason": "材料说明其为备用件，未接入当前流程，图上不画"}
```

规则：
1. 不允许出现既无 `mapped_id` 又非 `status:"omitted"+`reason` 的条目（校验硬失败）。
2. `quote` 同样必须逐字可回溯（校验硬失败）。
3. 宁多勿漏：拿不准是否该画的实体，先进索引，再决定 map 或 omit + reason。

## 校验关系

- `validate_ir.py`：结构（id 唯一、端点存在、source 必带、枚举合法）。
- `check_consistency.py`：双向（材料→图 覆盖；图→材料 引文逐字回溯）、
  SVG↔IR id 一致、箭头落点几何。
