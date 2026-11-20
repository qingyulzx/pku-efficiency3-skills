# 部件图元库（P&ID 风格约定）

渲染器（scripts/render.py 的 `draw_component_glyph`）按 `type` 画图元。
画法参考化工 P&ID（管道仪表流程图）通行惯例，做了一致性简化：**一个类型一个图元，
含义固定，读者不需要看说明书也能猜个八九不离十**。

| type（大小写不敏感） | 图元 | 常见同义词（抽取时映射到左列） |
|-|-|-|
| gas_source / gas_tank / cylinder | 气瓶：矩形+圆顶+阀门管线 | 钢瓶、气源、gas cylinder |
| valve | 两三角对顶（蝶阀惯例） | 阀、截止阀、针阀 |
| pump / vacuum_pump / scroll_pump / turbomolecular_pump | 圆+内三角（泵惯例） | 泵、机械泵、分子泵 |
| mfc / mass_flow_controller | 矩形+孔板符号（两三角相对） | 质量流量计、MFC、flow controller |
| filter | 矩形+平行线+虚线竖纹 | 过滤器、滤芯 |
| adsorber / column / reactor / trap | 竖矩形+内填充线（填充床惯例） | 反应器、吸附柱、色谱柱 |
| chamber / vessel / load_lock / process_chamber / detector | 圆角矩形+内十字圆 | 腔体、反应腔、真空腔、检测器 |
| sensor / gauge / pressure_gauge / temperature_sensor | 圆表盘+引线，内标 P/T | 压力计、真空规、热电偶 |
| heater / furnace | 矩形+锯齿（电阻加热惯例） | 加热炉、加热带、马弗炉 |
| cooler / dewar / cryostat | 矩形+外虚线框（冷屏） | 冷阱、杜瓦、冷凝器 |
| electronics / power / controller / readout | 矩形+地线符号 | 电源、控制器、读出电路 |
| source / sputter_source / ion_beam_source / sample_source | 圆+散点（发射/源） | 靶源、离子源、样品源 |
| 其他/未知 | 圆角矩形（通用框） | 一切没有惯例图元的部件 |

规则：
1. **映射靠功能不靠词面**：中文「真空泵」→ pump；「质量流量控制器」→ mfc；
   材料自造的名称（如「进气单元」）按描述的功能归入最接近的类型，归不进就用 other，
   不要硬凑。
2. 同类多台：id 区分（C1/C2…），label 保留材料原名（「MFC-1」「MFC-2」）。
3. **规格未提供的部件**：certainty = "unspecified_spec"，图元自动虚线+「△ 规格未提供·示意」，
   部件照样画（它确实存在），但不编造数值。
4. 图元是示意约定，不承担工程制图精度（不按比例、不表达真实尺寸）。

## 线型 / 颜色语义（自动图例）

| kind | 线型 | 含义 |
|-|-|-|
| material | 实线 | 物料/气体流动 |
| signal | 长虚线 6,4 | 信号/电连接 |
| energy | 点线 2,3 | 能量/热量传递 |
| （certainty=inferred） | 灰虚线 5,4 | 材料未明示、由上下游顺序推断的连接 |

- 颜色按 `medium`（介质）自动分配（N2 蓝、CO2 红……固定色板），图例自动生成，
  不需要手工维护。
- 箭头方向 = 流向。`from` 是上游，`to` 是下游，写反了校验虽查不出语义，
  但评审会——抽取时务必对着材料的方向动词（「流入」「泵入」「排出」）确认。
