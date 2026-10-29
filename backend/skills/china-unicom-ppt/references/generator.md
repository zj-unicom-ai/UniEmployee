# 生成接口

先通过 `load_workspace_dependencies` 获得 Node、Python 与 node_modules 路径，不安装或修改打包运行时。PPTX 创建前按 Presentations 的实现指南运行一次 operation marker。

```sh
RUNTIME_NODE_MODULES="<bundled-node_modules>" "<bundled-node>" \
  "<this-skill>/scripts/build-deck.mjs" \
  "/absolute/content.json" "/absolute/new-project"
```

输入为 JSON：

```json
{
  "title": "项目汇报",
  "font": "Microsoft YaHei",
  "slides": [
    {"kind":"cover","title":"项目汇报","subtitle":"数智产品中心","date":"2026年10月"},
    {"title":"项目概况","sourceLabel":"来源：用户提供的项目材料","sources":[],"elements":[
      {"type":"text","text":"本阶段工作进展","bounds":[60,145,1160,60],"size":40,"bold":true},
      {"type":"text","text":"按真实材料填写内容","bounds":[60,270,1160,100],"size":28}
    ]},
    {"kind":"end","title":"守正创新  行稳致远"}
  ]
}
```

自动页眉适用于普通页；`cover` 和 `end` 使用专用版式。`elements` 坐标为 `[x,y,width,height]`，CSS px 画布固定 1280×720。字体大小为 CSS px，PPT 点为其 0.75 倍。

元素类型：

- `text`：`text,bounds,size,bold,color,align,valign`。默认 24px、黑色、左上对齐。手动换行可用 `\n`。
- `rect`：`bounds,fill`。用于已有品牌色条，不用来堆叠卡片。
- `image`：`bounds,src,alt,fit`。路径必须位于工程内部，如 `media/case.jpg`；先将原图复制进去。默认 contain，保留比例。
- `chart`：`bounds,categories,values,seriesName`。单系列红色柱状图，量程默认零起点并根据数据自动计算上限。可用 `axisMax`、`majorUnit` 指定上限和刻度间隔；拒绝负数、非数值、类别数量不匹配或会截断数据的上限。其他图表类型需按主题扩展。
- `table`：`bounds,rows,widths,size`。`rows` 为二维字符串矩阵，首行红底白字，后续灰白交替；`widths` 为各列 px 宽度，其和与 bounds 宽一致。

输出：`.build/draft.pptx`、`previews/*.png`、`deck.pptd`、`pages/*.page`、`media/`。JSON 是 YAML 1.2 的合法子集，PPTD 与 page 文件使用 JSON 编码。PPTD 坐标与字号乘 0.75，因此输出物理尺寸与原 PPT 一致。

所有文本框关闭自动缩字。新增内容必须逐页渲染检查，坐标校验不代表文字适配。表格和图表保持原生对象。

将草稿通过 Presentations 的 `finalizePresentation` 导出为新文件；不要把未经校验的草稿命名为最终文件。如需要淡入淡出，可用 open-kimi-ppt 的 `patch_transitions`，随后再次验证根级 transition 顺序。PPTD 通过 open-kimi-ppt 的图片检查与本地导出脚本验证；保持工程自包含。

交付前可使用 PowerPoint/LibreOffice 对最终 PPTX 再次渲染，确认实际阅读结果与预览接近。未实际打开 PowerPoint 时不要声称已在 PowerPoint 验证。未嵌入字体时不要承诺跨平台完全一致。
