# 输出模式（outline.json / result.json / case 输入期望）

本文件是 SKILL.md 各步骤产出的数据模式说明。Agent 负责判断与填充，脚本负责校验与装配；
任何一方都不得改变字段名或值的形状。

## 1. case 输入期望（/input/case.json，实际形状以运行时读到的为准）

常见形状（**先读真实文件，不要按这里的描述假设**）：

```json
{
  "case_id": "…",
  "materials": ["…pdf/路径…"],
  "constraints": {
    "audience": "组会 | 答辩 | 评审 | 其他（读原文字段）",
    "duration_minutes": 10,
    "slide_count": 8,
    "template": "template.pptx"
  },
  "output_contract": { "字段名": "要求描述", "…": "…" }
}
```

- `output_contract` 可能是 dict、list，也可能不存在。存在时：result.json 必须逐字段镜像；
  答不了的字段保留键名、显式 `null`，并在 `null_reasons` 里写一句原因。
- 不存在时：使用本文件 §3 的默认契约。
- `template.pptx` 是本 Skill 的必需材料：一切版式/主题从它继承；缺失或不可读时
  build_deck.py 自动回退默认模板并记录（见 references/exceptions.md）。

## 2. outline.json（Step 4 产出，Step 5 装配输入）

```json
{
  "case_id": "与 case.json 一致",
  "deck": {
    "title": "汇报标题", "audience": "固定受众", "duration_minutes": 10,
    "slide_budget": "8-10 页", "language": "中文为主，术语保留英文"
  },
  "scenario": "group_meeting | defense | review | <实际受众>",
  "goal": "这次汇报要达成什么（可检查的一句话）",
  "audience_prior": "听众先验与关注点（一句）",
  "time_budget_minutes": 10,
  "pages": [
    {
      "page_no": 1,
      "type": "title | section | content | two_column | picture | closing | backup",
      "layout": "可选：显式版式名或索引（必须来自 manifest.json，不凭记忆造名字）；优先于 type 角色映射",
      "priority": "P0 | P1 | P2 | P3",
      "title": "本页唯一主张（一句话，可讲出口）",
      "subtitle": "副标题（title/section 页可选）",
      "bullets": ["要点（≤5 条，每条 ≤2 行）", "  - 子要点（两空格开头=二级）",
                   {"level": 1, "text": "字典形式（level 0-4）同样接受"}],
      "evidence": [
        {
          "locator": "源定位：文件 + 页/节/行，如 'paper.pdf p.2 Table 1'",
          "quote": "支撑该主张的逐字引文（≤40 词）",
          "strength": "direct | indirect | inferred | gap"
        }
      ],
      "figures": [
        {"path": "图片文件路径", "caption": "图题", "status": "available | missing",
         "locator": "源定位"}
      ],
      "notes": "完整讲稿（口语化，含过渡句与数字读法，不复读 bullets）",
      "qa": [{"q": "预期追问", "a": "回答要点（口径与页面一致）", "page_ref": 5}]
    }
  ],
  "cut_log": [
    {"content": "被砍掉的内容", "reason": "为什么（对照判据/优先级）",
     "where": "去向：backup 第 N 页 / 仅留在材料 §…"}
  ]
}
```

字段约束（build_deck.py 会硬校验）：
- 顶层必须有 `case_id`、`pages`；每个 page 必须有 `title`。
- `type` 是内容角色；w08 六角色映射为版式：`picture` 走图片版式（无图片版式的模板
  自动落自由区域），`two_column` 等价 `two_content`。`layout` 显式指定总是优先，
  找不到则回退角色映射并记 `LAYOUT_NOT_FOUND` 警告。
- `bullets` 两种写法都接受：字符串（前导空格/`- ` = 二级）或 `{"level","text","bold"}`。
- `evidence` 逐字引文与数字不得改写；`strength` 四档，`gap` 绝不编造。
- `priority`：P0=主张+核心证据；P1=背景/方法主干；P2=扩展结果/次要方法；P3=礼节/延伸。
  超页数预算时脚本按 P3→P2 顺序把整页降级为 backup（追加到附录），绝不静默删除。

## 2b. build_report.json 关键字段（Step 5 决策输入）

- `slides[i].fit.ratio`：估算文本高 / 可用高；>1.05 即危险。
- `slides[i].fit.size_overrides_pt`：该页写下去的字号覆盖（审计线索）。
- `slides[i].fit.needs_split`：true = 即使地板字号也装不下，必须由 Agent 拆页重跑。
- `slides[i].trims`：被容量阶梯裁掉的 bullet 明细（不是静默截断）。
- `layout_usage`：每页实际用的版式与选择方式（explicit / role match）——result.json
  的模板继承块从这里对账。
- `demotions` / `figure_status` / `adaptations` / `warnings`：降级、图片、回退与
  异常的全部留痕。

## 3. result.json（Step 7 终稿；Step 1 先写全 null 保底版）

```json
{
  "case_id": "…",
  "status": "running | complete | partial | failed_input | failed_render",
  "output_contract 镜像字段": "……（存在契约时逐字段镜像；答不了= null + null_reasons）",
  "presentation": {"deck_path": "…pptx", "content_pages": 8, "backup_pages": 2,
                    "pdf_path": "…pdf",
                    "template": {"path": "…", "sha256": "…", "adaptations": []}},
  "page_evidence_map": [
    {"page": 1, "claim": "…", "locator": "…", "quote": "…", "strength": "direct"}
  ],
  "speaker_notes": "每页备注已写入 pptx notes；此字段为提取摘要或 'notes/outline.md'",
  "render_preview": {"pdf": "…", "status": "ok | unavailable", "render_gap": "…"},
  "sources": [{"path": "…", "sha256": "…", "role": "paper | template | figure"}],
  "cut_log": "与 outline.json 一致",
  "qa_prep": [{"page": 3, "q": "…", "a": "…"}],
  "template_inheritance": {
    "layouts_used": ["Title Slide", "Title and Content", "…"],
    "theme_fonts": {"major_latin": "…", "minor_latin": "…"},
    "theme_colors": {"accent1": "#…", "…": "…"},
    "hardcoded_visual_overrides": 0,
    "size_overrides_by_slide": {"5": {"0": 14.0}}
  },
  "consistency_scan": {"status": "pass | fail", "errors": 0, "warnings": 0,
                        "report": "…check_report.json", "fix_rounds": 1},
  "run_record": {"steps": ["parse_sources", "analyze_template", "build_deck",
                            "render_preview", "check_deck"],
                 "fix_rounds": 1, "reports": ["…build_report.json"]},
  "uncertainty": ["如实列出：证据缺口、OCR 未做、渲染不可用、页数压缩等"],
  "null_reasons": {"字段名": "未答原因（一句）"},
  "change_records": [{"step": "…", "change": "…", "why": "…"}]
}
```

w08 模板适配字段说明（`template_inheritance` / `consistency_scan` / `run_record`）：
- `layouts_used` 从成品 deck 的 build_report.layout_usage 读回，不凭记忆写；
- `hardcoded_visual_overrides` 本包恒为 0（零硬编码规则）——非 0 即不合格；
- `size_overrides_by_slide` 是唯一允许的显式排版（字号阶梯审计）；
- `consistency_scan` 摘自 check_deck.py 的 check_report（errors 必须处理完或如实
  标注 partial），`fix_rounds` 记录修复循环轮次。

校验：`python scripts/check_result.py --result result.json --case case.json`。
退出码 0 才算通过；错误信息逐条修复后重跑。

## 4. 目录约定

- 工作区：`/app/work/`（materials_index.json、outline.json、build_report.json）
- 产物：`/app/output/`（result.json、deck.pptx、previews/、outline.md）
- Skill 根：`/skills/weekly-skill/`（脚本用 `python /skills/weekly-skill/scripts/<x>.py`）
