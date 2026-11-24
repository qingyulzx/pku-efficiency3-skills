# 异常码字典与处置路径

原则：**能自动补偿的补偿并记录，不能的显式标注，绝不静默吞掉。**
所有码出现在 build_report.json / check_report.json / render_report.json 的
warnings/findings 里，最终汇入 result.json 的 limitations 与 uncertainty。

## 解析/分析期（parse_sources.py / analyze_template.py）

| 码 | 含义 | 自动处置 | Agent 后续动作 |
|-|-|-|-|
| status:"error"（parse_sources） | 单文件解析失败（缺后端/损坏） | 跳过该文件并计数 | 不编造其内容，缺口进 uncertainty |
| status:"warning"（parse_sources） | PDF 文字极少（疑似扫描件） | 标记 | 记 uncertainty；有 OCR 工具就 OCR 后重跑 |
| UNREADABLE_PPTX:<path>:<Exc> | analyze_template 打不开模板 | 终止，exit 2 | 换别的 pptx 或在 result.json 标注 failed + 原因 |

## 构建期（build_deck.py）

| 码 | 含义 | 自动处置 | Agent 后续动作 |
|-|-|-|-|
| OUTLINE_NOT_FOUND:<path> | outline.json 路径不存在 | 终止，exit 2 | 核对路径 |
| OUTLINE_UNREADABLE:<path>:<Exc> | outline.json 解析失败 | 终止，exit 2 | 修 JSON 重跑 |
| TEMPLATE_MISSING:<path> | 模板路径不存在 | 回退默认模板并记录 | 修路径重跑，或在 result.json 如实说明 |
| TEMPLATE_UNREADABLE:<path>:<Exc> | 模板打不开（损坏/非 pptx） | 回退默认模板并记录 | 同上；如案例还给了别的 pptx 尝试之 |
| LAYOUT_NOT_FOUND:<name> | 显式指定的版式名/索引不存在 | 回退角色映射 | 核对 manifest.json 的版式名后修正 outline |
| NO_LAYOUT_FOR_ROLE:<role> | 模板没有任何版式适配该角色 | 回退第一个带标题版式，再回退版式 0 | 接受回退或换角色 |
| NO_TITLE_PLACEHOLDER | 版式无标题占位符 | 标题写入文本框（不跟随版式样式） | 优先换有标题的版式 |
| NO_BODY_PLACEHOLDER | 版式无正文占位符 | 要点写入文本框（内容不丢弃） | 换 content 类版式可更贴模板 |
| NO_SUBTITLE_PLACEHOLDER | 无副标题占位符 | subtitle 跳过 | 接受或换 title 版式 |
| IMAGE_FILE_MISSING:<path> | 图片文件不存在 | 画 [图缺失] 标记框，构建继续 | 修路径或从 PDF 重新抽取图片 |
| IMAGE_UNREADABLE:<path>:<Exc> | 图片文件损坏 | 同上 | 同上 |
| NEEDS_SPLIT | 地板字号仍装不下 | 保留内容 + 标记 | 把该页拆成两页，改 outline 重跑 |
| TITLE_TOO_LONG | 标题估算超 2 行 | 已缩字号仍超则警告 | 改写更短标题 |
| SAVE_FAILED:<Exc> | 保存失败（磁盘/权限） | 终止，exit 2 | 换输出路径重试 |

## 扫描期（check_deck.py）

| 码 | 级别 | 含义 | fix 指引 |
|-|-|-|-|
| OVERFLOW_EST | error | 估算文本高超占位符 10% 以上（用占位符真实高度） | 删 bullet/降层级/拆页/换版式后重建 |
| FONT_SIZE_FLOOR | error | 某运行字号低于地板 | 提回地板或砍内容 |
| IMAGE_DISTORTION | error | 显示纵横比偏离源 >3% | 重放图片（占位符 center-crop 或原比例 fit） |
| PDF_PAGE_MISMATCH | error | PDF 页数 ≠ 幻灯片数 | 重导出 PDF |
| FONT_OVERRIDE | warn | run 级字体名覆盖主题字体 | 移除覆盖（或经 font-discovery 确认后保留并记录） |
| COLOR_OVERRIDE | warn | run 级硬编码色不在主题色板 | 改用主题色 |
| MISSING_TITLE | warn | 版式有标题占位符但页上无标题文字 | 补标题 |
| TITLE_TOO_LONG | warn | 标题估算超 2 行 | 缩短 |
| MISSING_NOTES | info | 无讲稿/证据块 | 补 notes + [evidence] |

严重级语义：error → 必须处理（修复循环目标）；warn → 应处理或说明；
info → 提示。扫描器单页崩溃不中断整册扫描（崩溃页记入 findings）。

## 渲染期（render_preview.py）

- 环境无 LibreOffice/soffice → render_gap，status "unavailable"：**如实**写进
  result.json 的 render_preview，audit 部分仍可交付；
- 转换超时/失败 → 重试一次；仍失败则同上处置（render_gap + 原因）；
- 导出成功但 check_deck --pdf 报页数不一致 → 重导出；仍不一致则逐页核对
  并把偏差写进渲染记录。
