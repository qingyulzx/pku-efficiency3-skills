# 输出模式（relation_table.json / model.json / result.json / case 输入期望）

本文件是 SKILL.md 各步骤产出的数据模式说明。Agent 负责判断与填充，脚本负责
解析、校验与装配；任何一方都不得改变字段名或值的形状。

## 1. case 输入期望（/input/case.json，实际形状以运行时读到的为准）

常见形状（**先读真实文件，不要按这里的描述假设**）：

```json
{
  "case_id": "…",
  "materials": ["…pdf / 文本 / 已有 svg…"],
  "constraints": {
    "figure_format": "svg + png + pdf",
    "canvas": "…",
    "style": "…"
  },
  "output_contract": { "字段名": "要求描述", "…": "…" }
}
```

- `output_contract` 可能是 dict、list（字符串或 `{name: …}` 对象），也可能不存在。
  存在时：result.json 必须逐字段镜像；答不了的字段保留键名、显式 `null`，并在
  `null_reasons` 里写一句原因。
- 不存在时：使用本文件 §3 的默认契约。

## 2. relation_table.json（Step 3 产出，Agent 亲自抽取；Step 4 装进 model.json）

```json
{
  "case_id": "与 case.json 一致",
  "entities": [
    {
      "id": "APC",
      "label": "APC",
      "type": "protein",
      "evidence": {
        "quote": "the degradation complexes consisting of adenomatous polyposis coli (APC)…",
        "locator": "paper.pdf p.2 Background ¶1",
        "source": "doi:10.1186/s40364-021-00323-7"
      }
    }
  ],
  "relations": [
    {
      "from": "Wnt",
      "to": "Frizzled",
      "type": "binds",
      "direction": "A_to_B",
      "label": "",
      "evidence": {
        "quote": "Wnt … The ligands of the frizzled family",
        "locator": "paper.pdf p.3 Table 1",
        "source": "doi:10.1186/s40364-021-00323-7"
      }
    }
  ],
  "groups": [
    {"id": "destruction_complex", "label": "β-catenin destruction complex",
     "members": ["APC", "GSK3B", "Axin"], "evidence": {"quote": "…", "locator": "…", "source": "…"}}
  ],
  "uncertainty": ["β-catenin 与 CTNNB1 系同义，已合并为一实体", "…"]
}
```

字段约束（model_check.py 硬校验，发现代码表见 references/model-schema.md）：

- `type` 限 9 种：`activates` `inhibits` `binds` `modifies` `transports` `indirect`
  `precedes` `contains` `parallels`；`direction` 限 `A_to_B` / `B_to_A` /
  `bidirectional` / `unknown`。
- `quote` 必须是材料文本的**逐字子串**（只修 PDF 换行），绝不改写；`locator`
  = 文件 + 页/节/行。**关系缺 quote = error（拒绝出图）**；实体缺 quote = warn。
- `from`/`to` 编码语句语义（"A inhibits B" ⇒ from=A, to=B），不是布局提示。
- 包含 → `groups` + `contains` 关系（不画成边或并列）；时序 → `precedes`。

Step 4 把两表 + groups 原样装进 model.json（完整模型结构、校验发现代码表见
references/model-schema.md）。

## 3. result.json（Step 7 终稿；Step 1 先写全 null 保底版）

```json
{
  "case_id": "…",
  "status": "running | complete | partial | failed_input | failed_render",
  "output_contract 镜像字段": "……（存在契约时逐字段镜像；答不了 = null + null_reasons）",
  "editable_source": {"svg": "/app/output/figure.svg", "model": "/app/output/model.json",
                      "note": "分层 SVG；每个元素带 data-evidence-quote/-locator/-source"},
  "exported_artifacts": [{"path": "/app/output/figure_300dpi.png", "format": "png",
                          "dpi": 300, "backend": "edge-headless", "checks": ["白底", "分辨率"]}],
  "rendered_preview": "/app/output/figure_300dpi.png",
  "entity_relation_table": "两表全文，或 model.json 路径 + 实体/关系/组计数",
  "verification_report": {"pass": 18, "fail": 0, "warn": 2, "detail": "/app/work/verify.json"},
  "sources": [{"path": "…", "sha256": "…", "role": "material", "quote_provenance": "…"}],
  "uncertainty": ["如实列出：实体歧义、unknown 方向、引文冲突、OCR 未做、导出后端降级等"],
  "null_reasons": {"字段名": "未答原因（一句）"},
  "change_records": [{"step": "…", "change": "…", "why": "…"}]
}
```

- 默认契约（case 无 `output_contract` 时）：`editable_source`、`exported_artifacts`、
  `rendered_preview`、`entity_relation_table`、`verification_report`、`sources`。
- `status` 置 `complete` 的条件：verify_svg 通过（fail=0）且导出合规检查全过；
  否则 `partial` + 残留项说明。**部分结果必须写明自己的边界**。

校验：`python /skills/weekly-skill/scripts/check_result.py --result
/app/output/result.json --case /input/case.json`。退出码 0 才算通过；错误信息
逐条修复后重跑。

## 4. 目录约定

- 工作区：`/app/work/`（materials_index.json、relation_table.json、model.json、
  figure.svg、layout.json、verify.json）
- 产物：`/app/output/`（result.json、figure.svg、model.json、`<name>_300dpi.png`、
  `<name>.pdf`）
- Skill 根：`/skills/weekly-skill/`（脚本用 `python /skills/weekly-skill/scripts/<x>.py`）
