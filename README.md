# PKU 学术效率第三期 · 科研绘图与学术PPT Skill 集

北大接招·学术效率赛道第三期参赛作品集合。9 个可被 Agent 调用的 Skill，覆盖科研绘图（figures）与学术演示（slides）两大场景。

> 平台：The Playground (play.bohrium.com) · 赛期 2026-11-20 → 2026-11-27
> 每个 Skill 在组织方固定的 3 个科研案例上由评测 Agent 实际运行评分。

## 作品目录

| 目录 | 题目 | 一句话说明 |
|---|---|---|
| [graphical-abstract](./graphical-abstract/) | Graphical Abstract（图形摘要） | 把研究问题→方法→结果→结论压缩成单页可编辑图形摘要 |
| [relationship-schematic](./relationship-schematic/) | 科研示意图生成与编辑 | 实体-关系语义层驱动的示意图生成，抑制/激活方向不画错 |
| [data-chart](./data-chart/) | 科研数据图表生成与编辑 | 源数据→图元显式映射 + 数值回读校验的图表管线 |
| [bio-pathway](./bio-pathway/) | 生物机制图与通路图 | 实体/相互作用/分区三层建模的生物通路图 |
| [apparatus-roadmap](./apparatus-roadmap/) | 实验装置与技术路线图 | 部件-管路-条件标注一致的装置图与技术路线图 |
| [paper-to-slides](./paper-to-slides/) | 论文转学术 PPT | 主线四要素提取→页级主张→模板装配的全流程 |
| [presentation-content](./presentation-content/) | 学术汇报内容组织 | 受众×场景驱动的汇报内容取舍决策框架 |
| [slide-template](./slide-template/) | 学术 PPT 模板与格式适配 | 模板结构分析 + 版式映射 + 批量一致性检查 |
| [slides-genedit](./slides-genedit/) | 学术 PPT 生成与编辑 | 从研究材料生成演示文件并支持源保留编辑 |

（各目录内容随比赛进度填充，完成后每个目录含 SKILL.md、脚本资源、使用说明与真实案例演示。）

## 通用设计原则

1. **可编辑源文件优先**：绘图以 SVG 为主源（元素可命名、可逐个溯源、可 diff），导出 PNG/PDF；演示以 python-pptx 生成真 .pptx。
2. **证据映射**：图中每个实体/关系/数值、每页每条主张都保留到来源材料的定位与引文，可独立复核。
3. **agent-in-the-loop**：科学判断（实体识别、关系方向、内容取舍）由 Agent 亲自做，脚本只承担确定性支撑（解析/渲染/校验）。
4. **异常处置**：材料缺数值、实体歧义、模板不匹配、字体缺失等均有真实处置路径，部分结果如实标注限制。

## 使用方式

每个子目录是一个独立的 Playground Skill（SKILL.md 入口）。详见各目录内 README 与 SKILL.md frontmatter 的适用条件。

## 许可

待定（建议 MIT，随最终提交确认）。
