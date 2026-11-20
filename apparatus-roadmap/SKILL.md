---
name: setup-roadmap
description: 实验装置图与技术路线图生成/编辑。从论文方法段、装置清单或研究计划中抽取部件、连接、步骤与阶段，生成分层可编辑 SVG（含 PNG/PDF 导出），并对图-材料一致性做双向校验（材料提到的每样东西都在图上、图上每样东西都能逐字回溯到材料）。当任务涉及：装置示意图、实验流程图、P&ID、技术路线图、物料流向图，或对已有装置图改部件/加管路时使用。
---

# 实验装置与技术路线图 Skill

把「装置怎么搭、步骤怎么走、物料从哪来到哪去」画成一张**对得起材料**的图。
判断（部件是什么类型、箭头朝哪、阶段怎么分）由你做；解析、渲染、校验交给脚本。
核心承诺：**图上的每个元素都能逐字回溯到输入材料，材料提到的每个实体要么画了、
要么有书面的省略理由**——这是由 `check_consistency.py` 机器强制的，不是自评。

## 输入约定

- `/input/case.json`：任务说明（含 output_contract 字段名，如有）。
- 材料文件（按 case 指定）：PDF 用容器 pdf-text-tool 取文字层，扫描页用
  ocr-tool；两者都失败的页记入 uncertainty，**不猜**。
- 参考 `references/`：ir_schema.md（IR 格式）、symbol_library.md（图元/线型约定）、
  extraction_playbook.md（判断规则）、output_contract.md（result.json 字段）。

## 工作流程（7 步，按序执行）

### Step 1 读取与盘点
读 case.json 和全部材料。PDF 只信真解析结果。列出材料清单（文件、页数、
可解析性）——这份清单后面写进 provenance。

### Step 2 保底产出
立即初始化 result.json（所有契约字段 null + 原因）：

```
python scripts/finalize_result.py --init --case /input/case.json --out /app/output/result.json
```

此后每完成一步，回头把对应字段从 null 换成实值。中途崩溃也留下完整骨架。

### Step 3 抽取与判断（agent-in-the-loop）
按 extraction_playbook.md 规则，**亲自**完成：
1. 部件识别：每个部件 → id/label/type（映射见 symbol_library.md）/specs；
2. 连接拓扑：from/to（方向对材料里的动词确认）、medium、kind、conditions；
3. route 类图：节点 kind（stage/step/decision/start/end）、step_no 与正文对照、
   回环边标 kind=loop + route=below；
4. 每个元素挂 source {location, quote}（quote 逐字复制）；规格未给 →
   certainty=unspecified_spec；连接靠推断 → inferred；
5. extraction_index 登记**所有**提到的实体/步骤（mapped_id 或 omitted+reason）。

产出一个 IR JSON（格式照 ir_schema.md），存 `/app/output/intermediate.json`。

### Step 4 IR 校验
```
python scripts/validate_ir.py /app/output/intermediate.json
```
exit 0 才继续。常见错误：id 重复、连接端点不存在、元素缺 source.location、
extraction_index 有 omitted 无 reason。改 IR 再跑。

### Step 5 渲染
```
python scripts/render.py /app/output/intermediate.json --outdir /app/output \
       --name figure --also-png --also-pdf --png-scale 2 \
       [--font <font-discovery 找到的 CJK 字体路径>]
```
产出 figure.svg（四层可编辑）+ figure.png + figure.pdf + figure.geometry.json。
检查 stdout：overflow_warnings 应为空；font_notes 里有「no CJK font」就用
font-discovery 工具找字体重跑；PNG 因字体缺中文时 SVG 仍是真文字（保真源），
同时在 result.json 的 uncertainty 里如实记录。

### Step 6 双向一致性校验（不过不算完成）
```
python scripts/check_consistency.py /app/output/intermediate.json \
       <材料文本文件> /app/output/figure.svg /app/output/figure.geometry.json \
       --out /app/output/consistency_report.json
```
五项检查：引文逐字回溯（防无中生有）、覆盖索引完备（防漏画）、SVG↔IR id 双向
一致、箭头落点无悬空、图层齐全。**exit 1 必须回到 Step 3 修 IR 再重跑 5–6**，
不许带病交付。材料文本 = 解析出的全文（多文件可先合并）。

### Step 7 终化
把实值填进 result.json（字段与填法见 output_contract.md：图路径、元素来源表、
数据映射、provenance、uncertainty 与图上标记一一对应），然后：

```
python scripts/finalize_result.py --finalize --result /app/output/result.json \
       --case /input/case.json --artifact-dir /app/output \
       --consistency /app/output/consistency_report.json
```
exit 0 才算交付。partial 结果必须在 run_status 里列明未完成步骤与影响。

## 编辑场景（已有图改部件/加管路）

改 IR，不改 SVG：
1. 用户给的新材料存成文本文件；
2. 写 edits 文件（操作格式见 `scripts/edit_ir.py` 文档头）：
   add_component / add_connection / update_component / remove_component …；
3. `python scripts/edit_ir.py intermediate.json edits.json --material 新材料.txt
   --out intermediate_v2.json`——新增元素的 quote 会被逐字核验，核验不过整批拒绝；
4. 对 v2 重跑 Step 4→6，result.json 的 provenance.change_records 自动带出。

## 异常处置路径

| 异常 | 处置 |
|-|-|
| 部件规格未给 | 照画 + certainty=unspecified_spec（图上自动「△ 规格未提供·示意」），不编数值 |
| 连接关系材料未写 | inferred 灰虚线标注，或不连线进未连线区；uncertainty 里说明 |
| 流程顺序歧义 | 选一种读法，uncertainty 记录歧义原文与理由 |
| 文字溢出 | 画布自动扩展；geometry.json 的 overflow_warnings 非空时缩小标签文本重渲 |
| 字体缺失（中文变框） | font-discovery 找字体传 --font；仍无 → SVG 保真文字 + uncertainty 记录 |
| 导出失败 | SVG 是保底交付件；PNG/PDF 失败写进 font_notes/uncertainty，不谎报 |
| 材料 PDF 不可解析 | 该部分字段 null + 原因（页码），不猜 |
| 校验硬失败 | 修 IR 重跑，绝不跳过或降级检查 |

## 自查清单（交付前）

- [ ] result.json 全字段非 null 或 null+原因（finalize exit 0）
- [ ] consistency_report.json pass=true
- [ ] SVG 打开可见四层（frame/structure/annotation/source），元素带 data-id
- [ ] PNG/PDF 存在且非空；字体问题（如有）已记录
- [ ] 图上每个 △/灰虚线在 uncertainty 里有一一对应条目
- [ ] intermediate.json 已随交付保存（改图真源）

## 限制

- 示意图元不表达工程比例与真实尺寸；不判断实验方案科学合理性。
- 中文 PDF 的 OCR 质量受原件影响，引文以文字层优先。
- PDF 矢量导出依赖 cairosvg（可选）；缺失时退化为位图 PDF 并如实标注。
- 依赖：Python 3 标准库（SVG）；Pillow（PNG/位图 PDF，可选）。
