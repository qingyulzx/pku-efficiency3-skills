# 适配规则细节

## 1. 内容→版式映射

分析器对每个版式计算能力向量（has_title / has_center_title / has_subtitle /
body_count / picture_count），六个内容角色按下表选版式（高分优先）：

| role | 最佳特征 | 典型命中 |
|-|-|-|
| title | center_title + subtitle | Title Slide |
| section | center_title | Section Header / Title Slide |
| content | title + 1 个正文占位符 | Title and Content |
| two_content | title + ≥2 正文占位符 | Two Content / Comparison |
| picture | title + 图片占位符 + 正文 | Picture with Caption |
| closing | center_title + subtitle | Title Slide / Section Header |

注意：OOXML 模板的正文占位符既有 `<p:ph type="body">` 也有 `type="obj"`，
两者都算正文（python-pptx 里分别是 BODY 和 OBJECT 枚举）。映射失败时回退
到第一个带标题的版式，再回退版式 0，并记 `NO_LAYOUT_FOR_ROLE` 警告。

## 2. 容量阶梯（字号与溢出）

正文超出占位符时的处理顺序，每一步都写进 build_report 的 `trims`/`fit`：

1. **裁剪**：先删最深层（level≥2）bullet，再删尾部 level-0 bullet，
   保底 4 条；
2. **缩字号**：各级字号按 `avail/est` 比例缩小，**永不低于地板**
   （默认 title 20pt / body 14pt / caption 10pt，命令行可调）；
3. **needs_split**：仍装不下 → 报告里标记，由 Agent 把内容拆成两页。

标题超 2 行时按 0.85 缩一次（不低于 title 地板），仍超则记
`TITLE_TOO_LONG` 警告，由 Agent 改写标题。

估算模型是 CJK 感知的（中文字宽 ~0.98em，拉丁 ~0.52em，行高 1.18，
段间距 0.40）：它快但有误差，**导出 PDF 才是溢出的最终裁判**。

## 3. 图片与 caption

- 有图片占位符的版式：`placeholder.insert_picture(path)` —— 按占位符
  center-crop 填充，纵横比保持；返回 `PlaceholderPicture`。
  注意：插入后原占位符对象即失效（元素被替换），其 idx 等属性要在
  插入前捕获。
- 无图片占位符：正文右侧或页面下部自由区域，按原纵横比 fit（多图横向
  均分槽位）。
- **caption 挂在返回的 PlaceholderPicture 正下方**（左对齐、同宽、间距
  0.06in）；若该位置与任何占位符重叠（如 Picture with Caption 版式的
  标题/正文紧贴图片下方），回退到页面底部条带，保证永不重叠。

## 4. 字体与颜色

- **从不**写 run 级字体名或 srgbClr —— 主题字体/颜色经
  master→layout→placeholder 链继承。换模板，产出自动跟随。
- 字号阶梯是唯一显式排版属性，全部记录在 build_report 供审计。
- 字体缺失场景：交给导出端的 font-discovery 工具核对渲染结果；
  检查器只报告「谁覆盖了主题字体」（FONT_OVERRIDE），不擅自替换。

## 5. 编辑模式（保源）

- 打开 starting deck（不是模板），只动 spec 指定的占位符，其余原样；
- `delete_slides` 按 starting deck 原始页序；
- 追加页走与新建模式相同的版式映射与 add_slide 安全路径；
- 每次改动进 change_log（before/after），支撑"逐页偏差记录"。

## 6. add_slide 的 partname 陷阱（已内置防护）

python-pptx 1.0.2 的 `Slides.add_slide` 用 `len(sldIdLst)+1` 推导新
partname：删除中间页后追加，会与尾部现存页撞名（zip 内重复
`ppt/slides/slideN.xml` → PowerPoint 修复提示/丢页）。本包的
`safe_add_slide` 改用包内真实 partname 集合分配，杜绝碰撞。
