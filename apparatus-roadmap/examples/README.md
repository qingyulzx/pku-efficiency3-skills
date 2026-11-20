# 示例（真实材料衍生，标注为示例输出）

以下两组示例演示 Skill 的完整调用流程：材料 → IR（Agent 判断）→ 校验 → 渲染 → 双向一致性检查。
**两组输出均为示例**，用于说明接口，不冒充正式案例结果。

## 示例 1：装置图（apparatus）

- 真实来源：arXiv:2609.17220v1 (cond-mat.mtrl-sci), Schneider et al.,
  "A transfer-rod-mounted rotatable sample holder enabling a compact modular
  vacuum system for ion-beam milling, oblique magnetron sputtering, and
  co-sputtering", 15 Sep 2026.
  https://doi.org/10.48550/arXiv.2609.17220
- 材料摘录：`material.txt`（§II System Design 全部五段 + Figure 8 图注，
  逐字转录自 arXiv HTML 版；行内公式线性化，其余措辞未改）
  sha256: `F748FD3AA7076CCAD9D931FB7E2B77A757F616E8D2AFE3493905A0B4CDFADF00`
- IR：`intermediate.json`（19 部件 / 14 连接 / 23 条覆盖索引；
  每个元素带 source.location + 逐字 quote；3 条 inferred 连接如实标注）
- 示例输出：`example_output.svg`（**示例**）——四层可编辑 SVG；
  同一 IR 重跑 `render.py --also-png --also-pdf` 可得 PNG/PDF 导出件

## 示例 2：技术路线图（route）

- 真实来源：arXiv:2504.19020v1 (cond-mat.mtrl-sci), Mulcahy, Conroy et al.,
  "A Workflow for Correlative in-situ Nano-chip Liquid Cell Transmission
  Electron Microscopy and Atom Probe Tomography Enabled by Cryogenic Plasma
  Focused Ion Beam", 26 Apr 2025.
  https://doi.org/10.48550/arXiv.2504.19020
- 材料摘录：`material.txt`（论文摘要，逐字转录）
  sha256: `79DC97248243F17C02B0E367C1C8EF803F7427896ADFE6DA13830C57EA25EC1F`
- IR：`intermediate.json`（8 节点 / 7 边；LCTEM→冷冻→传输→PFIB→APT 全链）
- 示例输出：`example_output.svg`（**示例**）

## 复现命令

```bash
python scripts/validate_ir.py examples/vacuum-system-apparatus/intermediate.json
python scripts/render.py examples/vacuum-system-apparatus/intermediate.json \
       --outdir /tmp/out --name vacuum --also-png --also-pdf
python scripts/check_consistency.py \
       examples/vacuum-system-apparatus/intermediate.json \
       examples/vacuum-system-apparatus/material.txt \
       /tmp/out/vacuum.svg /tmp/out/vacuum.geometry.json
```

两个示例的 consistency 检查（引文逐字回溯 / 覆盖 / SVG↔IR / 箭头落点 / 图层）
均应 exit 0。编辑场景示例见 `tests/case3_edit/`（包外，见仓库 tests/ 目录）。
