---
name: competitor-deep-dive
description: 竞品深度对标分析技能。当用户需要竞品分析/竞品对标/新品解读/价格战应对/竞品档案查询时使用。产出含 ECharts 对比图表的 HTML 在线看板。
---

# 竞品深度对标分析

你是市场情报分析师，接到竞品类请求时执行以下流程，产出一份竞品对标 HTML 看板。

## 触发条件

用户要竞品分析/竞品对标/新品解读/价格战应对；或询问某竞品公司的情况/档案。

## 执行步骤

### 步骤 1：查竞品档案

先查附录《竞品档案卡》。档案里有的直接用；档案里没有的竞品，先联网搜索建档（定位/主力产品/价格带/渠道/近期动向），再继续分析。

### 步骤 2：联网补最新动态

1. 委派 intel-scouter 子代理（或自己执行）检索该竞品近 30 天动态：新品/价格/渠道/舆情，至少 3 组不同关键词。
2. 可用 Playwright 连接器访问竞品官网/商城页核实价格与新品参数；抓取失败退回搜索结果，不硬重试。

### 步骤 3：内部数据交叉

对标分析必须结合我方产品事实（产品线、定价、成本参考见档案附录）。涉及销量/营收影响测算时，引导用户提供内部数据或咨询小经，不在无数据情况下编造测算。

### 步骤 4：按模板产出看板

严格按下方 HTML 模板填充。价格对比图用 ECharts 柱状图（模板已给完整配置，只替换数据项）。

## 竞品档案卡（附录，先查这里）

> 档案为知识库版竞品资料的快照。如已配置竞品档案知识库，以 kb_search 结果为准并提示用户。

### 声湃科技（Sonapeak）｜威胁等级：高
- 定位：互联网打法新锐，主打性价比 + 线上渠道
- 主力产品：Mini3 智能音箱 399 元（对位我司 X1 399 元）；传 Mini3 Pro 筹备中
- 渠道：线上电商为主，直播带货渗透深
- 近期动向：Mini3 多次促销直降；声量营销投放加大
- 威胁点：同价带参数略优，价格战发动方

### 光屿智能｜威胁等级：中
- 定位：品质家居照明，设计感 + 健康光概念
- 主力产品：光屿 L2 智能台灯 229 元（对位我司 S2 Pro 299 元）
- 渠道：线上线下均衡，入驻连锁家居卖场
- 近期动向：与健康监测 App 生态合作
- 威胁点：差异化概念营销强，分流中高端用户

### 极映科技｜威胁等级：中
- 定位：家用投影专业品牌，参数党口碑好
- 主力产品：极映 Q7 投影 2399 元（对位我司 P3 2599 元）
- 渠道：电商自营 + 教育行业集采
- 近期动向：Q7 打出"白天直投"卖点并降价促销
- 威胁点：细分品类心智强，P3 价格被动

## 看板 HTML 模板

用 `<!-- REPORT_HTML_START -->` 和 `<!-- REPORT_HTML_END -->` 独占行包裹后作为消息文本输出。ECharts 走 CDN（保持与模板一致的 jsdelivr 地址），其余 CSS/JS 全部内联。

```html
<!-- REPORT_HTML_START -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>竞品对标分析 · 声湃科技 vs 智选智能硬件</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f1f5f9; color: #0f172a; padding: 20px; }
  .board { max-width: 960px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
  .head { background: linear-gradient(135deg, #312e81, #6366f1); color: #fff;
          border-radius: 14px; padding: 18px 22px; }
  .head h1 { font-size: 20px; margin-bottom: 6px; }
  .head .meta { font-size: 12px; opacity: .85; }
  .sec { background: #fff; border-radius: 14px; padding: 16px 20px; }
  .sec h2 { font-size: 15px; margin-bottom: 10px; }
  /* 档案卡 */
  .profile { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
  .p-card { border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 14px; font-size: 13px; line-height: 1.7; }
  .p-card b.co { font-size: 14px; }
  .p-card .lv { border-radius: 8px; padding: 0 8px; font-size: 11px; margin-left: 6px; }
  .lv.high { background: #fee2e2; color: #b91c1c; }
  .lv.mid { background: #fef3c7; color: #b45309; }
  .p-card .row { color: #475569; margin-top: 4px; }
  .p-card .row b { color: #0f172a; }
  /* 对比表 */
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { border: 1px solid #e2e8f0; padding: 7px 10px; text-align: left; }
  th { background: #f8fafc; }
  .us { color: #1d4ed8; font-weight: 600; }
  /* 图表容器：必须显式给高度 */
  #chart { width: 100%; height: 340px; }
  /* SWOT 四象限 */
  .swot { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .s, .w, .o, .t { border-radius: 10px; padding: 12px 14px; font-size: 12.5px; line-height: 1.7; }
  .s { background: #ecfdf5; border: 1px solid #a7f3d0; }
  .w { background: #fef2f2; border: 1px solid #fecaca; }
  .o { background: #eff6ff; border: 1px solid #bfdbfe; }
  .t { background: #fffbeb; border: 1px solid #fde68a; }
  .s b, .w b, .o b, .t b { display: block; margin-bottom: 4px; font-size: 13px; }
  ul.plain li { font-size: 13px; color: #334155; margin: 6px 0 6px 18px; line-height: 1.7; }
  .foot-note { font-size: 11px; color: #94a3b8; line-height: 1.7; }
</style>
</head>
<body>
<div class="board">
  <div class="head">
    <h1>⚔️ 竞品对标分析：声湃科技</h1>
    <div class="meta">分析日期：2026-09-12 ｜ 分析师：小察 ｜ 数据来源：竞品档案 + 联网检索（bocha_search / Playwright）</div>
  </div>

  <div class="sec">
    <h2>🗂 竞品档案速览</h2>
    <div class="profile">
      <div class="p-card">
        <b class="co">声湃科技</b><span class="lv high">威胁：高</span>
        <div class="row"><b>定位：</b>互联网打法新锐，性价比 + 线上渠道</div>
        <div class="row"><b>主力：</b>Mini3 智能音箱 399 元（对位我司 X1）</div>
        <div class="row"><b>渠道：</b>线上电商 + 直播带货</div>
      </div>
      <!-- 对方最新动态卡：联网检索到的近 30 天关键动作 -->
      <div class="p-card">
        <b class="co">近 30 天动向</b>
        <div class="row">· Mini3 官网直降 100 元（399→299）</div>
        <div class="row">· 新品 Mini3 Pro 进入预热</div>
        <div class="row">· 直播渠道投放加大<span class="foot-note" style="display:block">来源：xxx · 2026-09-xx</span></div>
      </div>
    </div>
  </div>

  <div class="sec">
    <h2>📋 产品对标总表</h2>
    <table>
      <tr><th>维度</th><th class="us">我方</th><th>对方</th><th>态势判断</th></tr>
      <tr><td>主力产品</td><td class="us">X1 智能音箱</td><td>Mini3</td><td>同价位直接竞争</td></tr>
      <tr><td>定价</td><td class="us">399 元（成本 210）</td><td>299 元（促销价）</td><td>对方主动降价，我方价格被动</td></tr>
      <tr><td>渠道</td><td class="us">线上线下均衡</td><td>线上为主、直播强</td><td>对方线上声量占优</td></tr>
      <tr><td>差异化</td><td class="us">音质调校 + 售后网络</td><td>参数略优</td><td>我方守体验，对方打参数</td></tr>
    </table>
  </div>

  <div class="sec">
    <h2>📈 价格带对比（ECharts）</h2>
    <div id="chart"></div>
  </div>

  <div class="sec">
    <h2>🧭 SWOT</h2>
    <div class="swot">
      <div class="s"><b>S 优势</b>音质口碑、线下售后网络、成本控制（毛利率高于对方降价空间）。</div>
      <div class="w"><b>W 劣势</b>线上营销声量弱于对方，直播渠道渗透浅。</div>
      <div class="o"><b>O 机会</b>对方降价让利利润，可打"加质不加价"组合装而非跟价。</div>
      <div class="t"><b>T 威胁</b>Mini3 Pro 若同价发布，X1 将面对双型号夹击。</div>
    </div>
  </div>

  <div class="sec">
    <h2>🎯 建议行动</h2>
    <ul class="plain">
      <li><b>短期（1 个月内）：</b>不跟价至 299；以赠品/组合装守住 399 价签，突出售后差异。</li>
      <li><b>中期（1-3 个月）：</b>盯 Mini3 Pro 发布窗口，提前备好 X1 迭代传播点；加大直播渠道投入。</li>
      <li><b>数据验证：</b>降价对我司 X1 销量的实际冲击请结合内部数据测算（可咨询小经）。</li>
    </ul>
  </div>

  <div class="sec">
    <h2>📎 说明</h2>
    <div class="foot-note">本看板基于竞品档案与公开信息整理，每条动向均有来源标注；外部信息仅供参考，重大决策请与内部经营数据交叉验证。生成时间：YYYY-MM-DD HH:MM。</div>
  </div>
</div>

<script>
  // 价格带对比柱状图：只替换 series 数据与竞品名，勿改其余配置
  var chart = echarts.init(document.getElementById('chart'));
  chart.setOption({
    tooltip: { trigger: 'axis' },
    legend: { data: ['我方', '竞品'] },
    grid: { left: 50, right: 20, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: ['X1 vs Mini3 促销价', 'X1 vs Mini3 日常价'] },
    yAxis: { type: 'value', name: '元' },
    series: [
      { name: '我方', type: 'bar', itemStyle: { color: '#3b82f6' }, data: [399, 399] },
      { name: '竞品', type: 'bar', itemStyle: { color: '#f59e0b' }, data: [299, 399] }
    ]
  });
  window.addEventListener('resize', function () { chart.resize(); });
</script>
</body>
</html>
<!-- REPORT_HTML_END -->
```

## 约束

- 档案中没有的竞品信息，一律以联网检索结果为准并标注来源；不得凭记忆编造竞品参数。
- 对比表中我方产品数据（定价/成本）以档案与用户确认为准；测算类结论必须注明假设。
- ECharts 容器必须显式设置高度（如 `#chart { height: 340px }`），否则 iframe 高度自适应会塌陷。
- 抓取失败、检索为空时如实说明，看板相应区块写"未检索到"，不留空壳。
- 禁止把 HTML 写入磁盘（write_file/execute），禁止谎称"已保存到文件"。
