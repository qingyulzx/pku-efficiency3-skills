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

**显式版式优先**：outline 页的 `layout` 字段（版式名或索引，取自
manifest.json）总是优先于角色映射；找不到则回退并记 `LAYOUT_NOT_FOUND`
警告——所以 layout 值必须从 manifest 抄，不凭记忆写。

w07 骨架的角色名 `two_column` 在装配时等价 `two_content`；`backup` 页按
content 角色选版式并给标题加「备用 |」前缀。

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
段间距 0.40）：它快但有误差，**导出 PDF 才是溢出的最终裁判**
（check_deck 用占位符真实高度复核，比装配期估算更严——两处不一致时
以 check_deck 与 PDF 为准）。

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

## 5. 保底回退（诚实契约）

- 模板缺失/不可读 → build_deck 回退默认 python-pptx 模板，记
  `TEMPLATE_MISSING`/`TEMPLATE_UNREADABLE` 警告，result.json 如实说明；
- 版式无标题占位符 → 标题写入文本框（不跟随版式样式），记
  `NO_TITLE_PLACEHOLDER` 适配；
- 版式无正文占位符 → 要点写入文本框（内容绝不静默丢弃），记
  `NO_BODY_PLACEHOLDER` 适配；
- 页数超预算 → 按 P3→P2 把整页降级为 backup 附录（标题加「备用 |」前缀），
  绝不静默删除。

（v4 的 starting-deck 逐页保源编辑模式已随旧版封存于 scripts-v4-backup/，
重建版流程统一走「从模板新建」。）

## 6. add_slide 的 partname 陷阱（已内置防护）

python-pptx 1.0.2 的 `Slides.add_slide` 用 `len(sldIdLst)+1` 推导新
partname：删除中间页后追加，会与尾部现存页撞名（zip 内重复
`ppt/slides/slideN.xml` → PowerPoint 修复提示/丢页）。本包的
`safe_add_slide` 改用包内真实 partname 集合分配，杜绝碰撞。
