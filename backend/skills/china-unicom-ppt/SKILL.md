---
name: china-unicom-ppt
description: "Create China Unicom branded presentations. Use when the user asks to write, create, revise, or outline a China Unicom PPT, project proposal, company introduction, or work report. 保留联通白底、品牌红、官方 Logo 与统一页眉版式。"
metadata:
  include_tools: generate_china_unicom_ppt
---

# China Unicom PPT（中国联通专属演示文稿）

## 触发条件

用户要求撰写、制作、修改中国联通风格的 PPT，或提出联通公司介绍、项目方案、技术分享、工作汇报等演示文稿需求时使用。用户明确指定其他视觉风格时，以用户要求为准。

## 工作流程

1. 确认演示目标、受众、时长、页数和可用材料。信息不足时先按常规汇报场景组织内容，不为常规版式选择阻塞工作。
2. 先搭建“结论—依据—行动”叙事，再选页型。每页只承担一个主要信息，不把所有内容都写成项目符号或卡片。
3. 事实与数据只来自用户材料或已核实来源。涉及联通公司事实、产品政策、经营数据或当前动态时，优先使用 `bocha_search` 查找中国联通官方来源；标明年份、统计主体、单位和来源。无法核实的内容标注待确认，不补造数字、案例、奖项或预测。
4. 按下方版式规则编排。优先保留原模板的留白、母版、页眉、字体层级、几何关系和 Logo 比例；不得把参考 PPT 栅格化后当成可编辑新稿。
5. 使用 `generate_china_unicom_ppt` 生成可编辑成品；生成后提供 PPTX 文件并支持在会话中在线预览。逐页检查文字换行、来源与页脚位置。只有文件实际生成并通过检查后，才称为已生成 PPT。
6. 若当前环境没有 PPTX 导出工具，交付逐页可制作稿（页标题、核心结论、正文、建议图表/图片、来源），明确说明这是内容稿而非 PPT 文件。不要声称已导出或附上不存在的文件。

## 联通版式规则

- 画布使用 16:9，白底为主，黑色标题，联通红作关键强调。Logo 主红约 `#E60027`；同一份文件保持颜色一致。
- 正文建议 `#161616`，辅助文字 `#666666`，来源 `#707070`。不使用通用科技蓝、渐变背景、圆角卡片或大面积阴影，除非用户明确要求。
- 封面 Logo 放右上，左侧配红色竖线；主标题约 40pt，副标题和日期约 18–20pt。标题过长时拆成两行，不挤压 Logo。
- 正文页标题约 24pt 加粗，Logo 置右上，标题下方用通栏红线分隔。正文 17–22pt，主结论 28–33pt，大数字 39–60pt，来源/页码 10–12pt。
- Logo 保持原始比例，不重绘、不拉伸、不重复叠加；有带 Logo 的母版时不再添加第二个 Logo。
- 封面、目录、章节、概况、数据、业务、结束页按内容选型。目录 3–5 项；数据图表优先使用可编辑对象，柱状图从零起点；内容过多时拆页，先精简文案再调整布局。
- 不把旧预览里的“试用水印”当作品牌元素。旧母版中的 2022 冬奥联合标识只在相关历史主题中使用；一般主题使用通用中国联通 Logo。
- 中文字体首选 Microsoft YaHei；当前环境不可用时使用可用中文字体（如 PingFang SC），并说明替代字体可能带来跨平台差异。
- 普通结束页可使用“守正创新 行稳致远”，也可按用户指定结语。

## 内容与来源

- 区分中国联通集团、中国联合网络通信股份有限公司及香港上市公司口径；不混用各自历史、业务和财务数字。
- 公司介绍只使用来源当前披露的数据，不把旧年度数值写成现状，也不默认扩写成投资建议。
- 官方资料入口：
  - 公司简介：<https://www.chinaunicom.com.hk/sc/about/profile.php>
  - 业务概览：<https://www.chinaunicom.com.hk/sc/business/business_overview.php>
  - 五年财务概要：<https://www.chinaunicom.com.hk/sc/ir/five_year_summary.php>（香港上市公司口径，原表单位为人民币百万元）
  - 公司历史：<https://www.chinaunicom.com.hk/sc/about/history.php>
  - 官方图片库：<https://www.chinaunicom.com.hk/sc/media/photo.php>（图片只用于其真实场景，不冒充客户案例）
- 页面标注简短来源；可用时在演示文稿备注或随附来源清单放完整链接。

## 生成器与参考文件

- `assets/reference.pptx` 是只读的集团模板，包含原生母版和布局；`assets/logo.png` 是提取的官方 Logo。生成时不得改写原文件。
- `scripts/build-deck.mjs` 面向配置了 `@oai/artifact-tool` 与 `RUNTIME_NODE_MODULES` 的执行环境，可从定位内容 JSON 生成可编辑 PPTX 草稿、逐页预览和 PPTD 工程；输入格式与坐标规则见 `references/generator.md`。
- 该脚本依赖独立的 Node.js 运行时和演示文稿生成库。若当前员工运行环境未配置这些依赖或没有执行/导出工具，不要尝试调用不存在的插件或工具，按工作流程第 6 步交付逐页可制作稿。
