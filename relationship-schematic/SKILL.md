---
name: relationship-schematic
description: Generate or edit scientific entity-relationship schematics (mechanism diagrams, pathway chains, experimental workflows, structural containment) as traceable, editable SVG with verified relation semantics. Parses source materials into a locator-indexed inventory, extracts an evidence-quoted entity/relation table by agent judgment, renders a layered SVG from the relation model, reads the drawing back to verify every relation type and the geometric direction of each arrow, then exports 300-dpi PNG and vector PDF with compliance checks. Use for any "draw a mechanism/workflow/relationship figure from this paper or case material" task where scientific correctness of entities, arrow directions and hierarchy matters.
---

# 科研示意图：实体关系抽取 → 建模 → 渲染 → 回读核对 → 导出

目标：画**科学正确性可被审稿人核验**的示意图——实体、箭头方向、层级、数值单位
逐项可溯源到来源材料，同时交付可编辑 SVG 主源与合规导出件（300dpi PNG + 矢量 PDF）。
判断（实体识别、关系类型、方向、取舍）由 Agent 解析后亲自完成；脚本只做解析、
校验、渲染、回读。全程在 `/app/work` 工作，最终产物进 `/app/output`。先读
`/input/case.json` 与 task.md，**以真实文件为准，不要按记忆或标签假设材料内容**。

## 红线（脚本强制，非自律）

1. **关系表先行**：无逐字引文的关系拒画（`model_check` error `relation_no_evidence`）。
   引不出来 = 画不出来，这是特性不是失败。
2. **`from`/`to` 编码语句语义而非布局**："A inhibits B" ⇒ `from: A, to: B, type:
   inhibits`；几何由渲染器决定，回读核对检查箭头尖端真的落在语义目标一侧。
3. **方向未明画成未明**：`direction: "unknown"`（虚线 + `?`），绝不靠合理性猜。
4. **包含 = 嵌套组框**，不是边、不是并列；时序 = `precedes` 带步骤标。
5. **图上不得出现 model.json 之外的实体/数值**：回读核对逐项覆盖；手改 SVG 骗
   不过几何方向检查（篡改必被抓）。

进度自检清单（走一步勾一步）：
```
- [ ] Step 1 读输入 + 亲笔保底 result.json
- [ ] Step 2 解析材料（脚本）
- [ ] Step 3 实体关系表（Agent 亲自）
- [ ] Step 4 model.json + 画前校验
- [ ] Step 5 渲染分层 SVG
- [ ] Step 6 回读核对 + 导出
- [ ] Step 7 契约输出 + 校验
```

## Step 1 — 读输入，亲笔保底

1. 读 `/input/case.json` 与 task.md。确认：`case_id`、材料路径（PDF/文本/已有
   SVG）、图面约束（格式/尺寸/风格）、`output_contract`（**dict、list（字符串或
   `{name}` 对象）、可能不存在**）。
2. **立刻亲笔写** `/app/output/result.json` 保底版：`case_id` + 契约全部字段
   （有契约逐字段镜像——dict 用其键、list 用每项的字符串或 `name`；无契约用
   /skills/weekly-skill/references/output-schema.md §3 默认契约）+ 每字段 `null` +
   `null_reasons: {"字段": "Step N 产出"}` + `status: "running"`。之后每个 Step
   只增强、不删除已填字段。（`scripts/init_result.py --case /input/case.json
   --work /app/work --output /app/output` 可一键生成同款脚手架；跑不了就亲笔写，
   保底不等脚本。）
3. 脚本一律绝对路径调用（`/skills/weekly-skill/scripts/...`）。

**异常处置**：case.json 读不了 → result.json 写 `status: "failed_input"` + 原因；
材料路径不存在 → 记入 `uncertainty`，按存在的材料继续（保底优先于完美）。

## Step 2 — 解析材料（脚本）

```bash
python /skills/weekly-skill/scripts/parse_sources.py --input <材料文件或目录> \
  --out /app/work/materials_index.json
```

读回 `materials_index.json`：各文件 sha256 与状态、章节/页文本、`figures_tables`
（图表清单与页码）、公式行。**引文从解析文本逐字复制**（只修 PDF 换行），定位
（文件 + 页/节/行）随之确定——没有定位的引文不算证据。

**异常处置**：PDF 文字极少（扫描件）→ 记 `uncertainty`，容器有 ocr-tool 就
OCR 后重跑解析；某文件 `status: "error"` → 不编造其内容，缺口进 `uncertainty`。

## Step 3 — 实体关系表（Agent 亲自）

这是 agent-in-the-loop 的核心步骤——**不要交给脚本**。基于 Step 2 索引逐句过
材料，写 `/app/work/relation_table.json`（两表 + 组，形状见
/skills/weekly-skill/references/output-schema.md §2）：

- **实体表**：每个科学角色一条——`label`（源文印刷名）+ `type`（功能角色副标）+
  逐字引文 + 定位 + source id（DOI/文件名）。
- **关系表**：每条陈述的相互作用一条——`from`/`to`（语义主体/客体）+ `type`
  （9 种：activates/inhibits/binds/modifies/transports/indirect/precedes/contains/
  parallels）+ `direction`（`A_to_B`/`B_to_A`/`bidirectional`/`unknown`）+ 逐字
  引文 + 定位 + source id。

硬 case 规则（照做）：

- **同义词/缩写**（"β-catenin" vs "CTNNB1"）：一个实体，label 用源文印法，等价
  关系记 `uncertainty`；源文明确区分的两个名字保持两个实体。
- **方向未明**：`direction: "unknown"`；不靠合理性消歧。
- **间接证据**（"X leads to Y via Z"）：优先拆链 X→Z→Y（每跳都要有引文）；拆
  不了才用 `indirect` 虚线。
- **数值/单位/浓度**：进 label 逐字保真（如 "3.3–10.4%"），不四舍五入、不编造。
- **包含句**（"X complex consists of A, B, C"）→ 组 + 成员 + `contains` 关系。
- **时序**（"first … then …"）→ `precedes` 带步骤标。
- **无引文的关系** → 不进表（画时会被拒）。
- 案例要**统计图表**（数值轴/误差棒）→ 超出本技能核心：交付能用的部分（实体
  表、数据→图例映射纪律）并标 partial + 原因。

深挖抽取判据与场景（生成/编辑/混合材料）时读
/skills/weekly-skill/references/scenario-playbooks.md。

## Step 4 — model.json（关系语义层）

把两表装进 `/app/work/model.json`（结构按
/skills/weekly-skill/references/model-schema.md——实体/关系/组 + evidence）：

- 关系的 `evidence.quote` **必填**（无引文 = error）；实体的 quote 强烈建议（缺
  了是 warn，如实上报）。
- 组可嵌套；`contains` 的目标必须在组里（否则回读核对 fail）。

画前校验：

```bash
python /skills/weekly-skill/scripts/model_check.py /app/work/model.json
```

exit 0 = 干净（警告允许）。错误必须修（渲染器反正拒收）；警告
（`entity_no_evidence`、`direction_uncertain`、`cycle_in_rank_graph`、…）是合法的
科学状态：保留并带进 result.json，不许靠编造"修复"。

## Step 5 — 渲染分层 SVG（脚本）

```bash
python /skills/weekly-skill/scripts/make_schematic.py /app/work/model.json \
  -o /app/work/figure.svg --report /app/work/layout.json
```

产物：`node-*` / `edge-*` / `group-*` / `legend` 分组，每个元素带
`data-evidence-quote/-locator/-source`。布局自动（最长路径分层，`A_to_B` 边向下）；
内容超宽时画布自动加宽 + `canvas_expanded` 警告，**绝不裁剪**。符号语义（实线=
直接/虚线=间接、三角箭头=激活、钝端杠线=抑制、嵌套框=包含）统一从
/skills/weekly-skill/symbols/symbols.json 读取，约定见
references/symbol-conventions.md。

## Step 6 — 回读核对 + 导出

```bash
python /skills/weekly-skill/scripts/verify_svg.py /app/work/model.json \
  /app/work/figure.svg --out /app/work/verify.json
```

核心防失效门，逐项产出 pass/fail/warn 行：

| 检查 | 抓什么 |
|-|-|
| entity / relation_coverage | 模型的实体/关系都画了且属性一致；图上没有模型外元素（篡改检测） |
| marker_semantics | 钝端杠=抑制、三角=激活、虚线=间接/未明，按符号库核对 |
| marker_geometry | **箭头尖端几何上必须落在语义目标一侧**——手改方向、渲染反向都 fail |
| containment | 组框真包住成员；非成员不被误包；`contains` 必有组 |
| text_fit / legend_coverage | 标签不溢出；每个画出的关系类型都在图例里 |

失败处置：修**模型或编辑** → 重渲染 → 重核对（两轮迭代正常）；**绝不手补 SVG
骗过检查**。材料自相矛盾 → 保引文更强/更具体的那版图，双方引文进 `uncertainty`。

核对通过后导出：

```bash
python /skills/weekly-skill/scripts/export_svg.py /app/work/figure.svg \
  -o /app/output --pdf
```

写 `<name>_300dpi.png` + `<name>.pdf`，后端降级链 cairosvg → Edge headless →
Chrome headless → PIL 兜底光栅化，**每次后端失败都记入报告**（含 PNG 分辨率/白底
检查、PDF 头/页面宽高比/文字嵌入检查）。把 figure.svg 和 model.json 拷进
/app/output 作为可编辑主源；导出的 PNG 即渲染预览。

## Step 7 — 契约输出与复核

1. 把 `/app/output/result.json` 补成终稿：契约字段按
   /skills/weekly-skill/references/output-schema.md §3 的映射填充——`editable_source`
   （SVG + model 路径与说明）、`exported_artifacts`（导出报告逐件：格式/dpi/后端/
   检查）、`rendered_preview`（PNG 路径）、`entity_relation_table`（两表内容或
   model.json 路径 + 计数）、`verification_report`（verify 摘要：pass/fail/warn
   计数 + verify.json 路径）、`sources`（来源文档/DOI + sha256）；未产出的字段保持
   `null` + 原因；`status` 只有 verify 通过且导出全成才 `complete`，否则 `partial`
   + 残留项说明。`uncertainty` 列实体歧义、unknown 方向、材料冲突；`change_records`
   讲清生成/编辑轨迹。
2. 校验直到退出码为 0：

```bash
python /skills/weekly-skill/scripts/check_result.py \
  --result /app/output/result.json --case /input/case.json
```

3. 完成前三问：每条画出的关系都能在材料里找到逐字引文吗（抽查 3 条
   `data-evidence-quote`）？箭头方向语义与几何都对吗？未答字段全部 null + 原因
   了吗？任何一问答"否"→ 回对应 Step 修复。

## 编辑已有 SVG（source-preserving）

案例给的是改图而不是画图时：

1. 读 SVG，定位 `node-*` / `edge-*` / `group-*` 分组和 `data-*` 属性（本技能产出
   的图完全自描述）。
2. **局部改动**（改标签/颜色/边类型/标题、删无依赖元素）→ 写 edits JSON 跑
   `python /skills/weekly-skill/scripts/edit_svg.py figure.svg edits.json -o
   figure_edited.svg`。每个 op 带 `reason`；报告证明未动元素逐属性不变
   （`preserved.ok`）。然后重导出（Step 6 导出段）。
3. **结构改动**（加删实体/关系、翻转方向）→ edit_svg **设计上拒绝**（翻转属性
   不重路由 = 画一条撒谎的箭头）。从 SVG 的 data 属性重建/扩展 model.json，改
   模型重渲染重核对。
4. 外来 SVG（无 data 属性）→ 从源材料重建模型重渲染，不手改；记 `change_records`。

## 失败处置速查

| 情况 | 检测 | 动作 |
|-|-|-|
| 材料/案例读不了 | Step 1 或 Step 2 | 保底已落，`partial_reasons` 点名文件与问题 |
| 关系引不出引文 | model_check `relation_no_evidence` | 砍掉或找到引文；绝不无引文画 |
| 方向未明 | 抽取判断 | `unknown`（虚线 + `?`）+ `uncertainty` |
| 同义词/缩写实体 | 抽取判断 | 单实体 + 等价说明进 `uncertainty` |
| 引文冲突 | 两条引文打架 | 画更具体引文支撑的版本，双方进 `uncertainty` |
| 标签溢出 | verify `text_fit` warn | 缩短标签或加换行重渲染；警告如实带出 |
| 画布不够 | `canvas_expanded` warn | 已自动加宽；或调大 `canvas_width` |
| 导出后端失败 | export 报告逐项记录 | 自动降级（cairosvg→Edge→Chrome→PIL）；全挂则 PIL 兜底 PNG，PDF null + 原因，status `partial` |
| verify 过不了 | verify exit 1 | 修模型循环；材料矛盾就保引文子集，`verification_report` 如实报 fails |

## 适用边界

适用：材料 → 机制图/通路链/实验流程/结构包含的**生成**；已有 SVG 的
**source-preserving 编辑**。不适用：统计图表的数值计算与方法选择、海报/封面
版式设计、艺术插画美化；**不代画材料里不存在的关系**——无引文拒画是特性不是
失败。

## 最小调用示例

见 /skills/weekly-skill/examples/README.md 与两个真实论文（Wang et al. 2021,
CC BY 4.0）衍生的例子（wnt-canonical、tankyrase-axin），每条关系带逐字引文 +
定位 + sha256，明确标注为示例、非正式案例结果。
