<!-- 原生技术雷达：所有视图共用当前租户的平台有效观察记录。 -->
<template>
  <section class="technology-radar" aria-labelledby="theme-dashboard-title">
    <header class="radar-head">
      <div><h1 id="theme-dashboard-title">具身智能技术雷达</h1><p>从技术进展到产业信号，持续追踪每一条研究依据。</p></div>
      <div class="sync"><span>{{ loading ? '正在同步平台数据…' : `同步于 ${syncedAt || '—'}` }}</span><button type="button" :disabled="loading" @click="load">刷新数据</button></div>
    </header>
    <nav class="radar-tabs" aria-label="看板视图">
      <button v-for="tab in tabs" :key="tab.id" type="button" :aria-current="activeTab === tab.id ? 'page' : undefined" @click="activeTab = tab.id">{{ tab.name }}</button>
    </nav>
    <div v-if="error" class="radar-error" role="alert">{{ error }} <button type="button" @click="load">重试</button></div>
    <template v-else-if="ready">
      <MarketIntelAssessment v-if="activeTab === 'judgement'" :overview="assessment" :records="records" @refresh="load" />
      <template v-else>
      <div class="radar-filters">
        <div class="filter-row"><span class="filter-label">时间</span><div class="segments"><button v-for="win in windows" :key="win.value" type="button" :aria-pressed="filters.months === win.value" @click="filters.months = win.value; filters.month = ''">{{ win.name }}</button></div><label>来源机构 <select v-model="filters.organization"><option value="">全部机构</option><option value="__unknown">未标注</option><option v-for="org in organizations" :key="org" :value="org">{{ org }}</option></select></label><label class="search">搜索 <input v-model="filters.query" type="search" placeholder="标题、机构、正文" /></label></div>
        <div class="filter-row categories"><span class="filter-label">领域</span><button v-for="category in categories" :key="category.id" type="button" class="chip" :aria-pressed="filters.categories.includes(category.id)" @click="toggleCategory(category.id)"><i :style="{ background: color(category.id) }"></i>{{ category.name }}</button></div>
        <div class="filter-row"><label v-for="dimension in dimensions" :key="dimension.key">{{ dimension.name }} <select v-model="filters[dimension.key]"><option value="">全部</option><option v-for="label in dimension.labels" :key="label" :value="label">{{ label }}</option></select></label></div>
        <div class="filter-foot"><span>当前 <b>{{ filtered.length }}</b> / {{ records.length }} 条<span v-if="filters.month"> · 月份 {{ filters.month }} <button type="button" class="text-button" @click="filters.month = ''">清除</button></span></span><button type="button" class="text-button" @click="reset">重置筛选</button></div>
      </div>
      <div v-if="!records.length" class="radar-empty">平台还没有具身智能研究记录。点击「让小察研究」开始收集，研究结果保存后会出现在这里。</div>
      <div v-else-if="!filtered.length" class="radar-empty">没有符合条件的研究记录。<button type="button" @click="reset">重置筛选</button></div>
      <template v-else>
        <template v-if="activeTab === 'overview'">
          <div class="radar-kpis"><article v-for="kpi in kpis" :key="kpi.label"><span>{{ kpi.label }}</span><strong>{{ kpi.value }}<small>{{ kpi.unit }}</small></strong><p>{{ kpi.note }}</p></article></div>
          <section class="radar-panel"><div class="panel-head"><div><h2>月度进展</h2><p>按发布日期统计；未记录发布日期时使用采集日期。点击月份联动筛选。</p></div></div>
            <div class="legend"><span v-for="cat in activeCategories" :key="cat.id"><i :style="{ background: color(cat.id) }"></i>{{ cat.name }}</span></div>
            <div class="trend-scroll"><div class="trend" :style="{ minWidth: `${Math.max(600, trend.length * 42)}px` }"><button v-for="bar in trend" :key="bar.month" type="button" class="trend-column" :aria-label="`${bar.month}，${bar.total} 条，点击筛选`" @click="filters.month = bar.month"><span class="bar-value">{{ bar.total || '' }}</span><span class="bar-stack" :style="{ height: `${bar.total / trendMax * 175}px` }"><span v-for="part in bar.parts" :key="part.id" :title="`${bar.month} · ${part.name}：${part.count} 条`" :style="{ height: `${part.count / bar.total * 100}%`, background: color(part.id) }"></span></span><span class="bar-label">{{ bar.month }}</span></button></div></div>
          </section>
          <section class="radar-panel"><div class="panel-head"><div><h2>研究领域记分板</h2><p>计数表示研究覆盖，不代表技术水平或商业成熟度。</p></div></div><div class="table-scroll"><table><thead><tr><th>研究领域</th><th>记录数</th><th>占当前筛选</th><th>有来源记录</th><th>最近观察</th></tr></thead><tbody><tr v-for="row in categoryStats" :key="row.id"><td><button class="text-button" type="button" @click="filters.categories = [row.id]"><i class="dot" :style="{ background: color(row.id) }"></i>{{ row.name }}</button></td><td><b>{{ row.count }}</b></td><td><span class="meter"><i :style="{ width: `${percent(row.count, filtered.length)}%`, background: color(row.id) }"></i></span>{{ percent(row.count, filtered.length) }}%</td><td>{{ row.sourced }}</td><td>{{ row.latest || '—' }}</td></tr></tbody></table></div></section>
          <div class="radar-two-columns"><section class="radar-panel"><h2>覆盖与观察</h2><ul class="insights"><li>当前筛选共 {{ filtered.length }} 条记录，覆盖 {{ activeCategories.length }} 个领域。</li><li>{{ sourcedCount }} 条记录附有来源链接，{{ filtered.length - sourcedCount }} 条尚未提供来源链接。</li><li>{{ unknownOrgs }} 条未标注来源机构；机构分布反映资料覆盖，不能直接视为企业竞争排名。</li><li>{{ markedCount }} 条记录带有阶段标注，{{ filtered.length - markedCount }} 条未标注；价值判断与 A 类优先级均不代表商业化验证。</li></ul></section><section class="radar-panel"><div class="panel-head"><h2>近期进展</h2><button type="button" class="text-button" @click="activeTab = 'data'">全部明细 ↗</button></div><button v-for="item in recent" :key="item.id" type="button" class="feed-item" @click="openObservation(item)"><span>{{ item.date || '日期未记录' }} · {{ categoryName(item.category) }}</span><strong>{{ item.title }}</strong></button></section></div>
        </template>
        <template v-else-if="activeTab === 'maturity'">
          <div class="radar-two-columns"><section v-for="dimension in dimensions.filter(d => ['stage', 'tier'].includes(d.key))" :key="dimension.key" class="radar-panel"><h2>领域 × {{ dimension.name }}</h2><p class="muted">点击单元格联动领域与{{ dimension.name }}筛选；空缺标注单独统计。</p><div class="table-scroll"><table><thead><tr><th>研究领域</th><th v-for="label in dimension.labels" :key="label">{{ label }}</th></tr></thead><tbody><tr v-for="cat in categoryStats.filter(c => c.count)" :key="cat.id"><td>{{ cat.name }}</td><td v-for="label in dimension.labels" :key="label"><button class="heat-button" :style="{ background: `rgba(42,120,214,${.04 + dimensionCount(dimension.key, label, cat.id) / Math.max(1,cat.count) * .6})` }" type="button" @click="filters.categories = [cat.id]; filters[dimension.key] = label">{{ dimensionCount(dimension.key, label, cat.id) }}</button></td></tr></tbody></table></div></section></div>
          <section class="radar-panel"><h2>价值判断分布</h2><p class="muted">沿用记录原有的分析判断，不表示商业验证。含“潜力”的措辞保留在完整研究记录中。</p><button v-for="label in dimensions.find(d => d.key === 'tier').labels" :key="label" type="button" class="org-row" @click="filters.tier = label"><span>{{ label }}</span><span class="org-meter"><i :style="{ width: `${percent(dimensionCount('tier', label), filtered.length)}%` }"></i></span><b>{{ dimensionCount('tier', label) }}</b></button></section>
          <section class="radar-panel"><h2>来源完整度</h2><div class="coverage-grid"><article><strong>{{ sourcedCount }} / {{ filtered.length }}</strong><span>附有可追溯来源链接</span></article><article><strong>{{ publishedCount }} / {{ filtered.length }}</strong><span>记录了发布日期</span></article><article><strong>{{ filtered.length - unknownOrgs }} / {{ filtered.length }}</strong><span>标注了来源机构</span></article></div><p class="muted">以上仅衡量资料字段完整度，不表示来源已完成核验或研究结论可靠。</p></section>
        </template>
        <template v-else-if="activeTab === 'orgs'">
          <div class="radar-two-columns"><section class="radar-panel"><h2>来源机构分布</h2><p class="muted">取观察记录的来源机构；一条记录涉及多个机构时分别计数。</p><button v-for="org in orgStats" :key="org.name" type="button" class="org-row" @click="filters.organization = org.name"><span>{{ org.name }}</span><span class="org-meter"><i :style="{ width: `${org.count / orgMax * 100}%` }"></i></span><b>{{ org.count }}</b></button><p v-if="!orgStats.length" class="radar-empty">当前记录未标注来源机构。</p></section><section class="radar-panel"><h2>领域 × 采集方式</h2><p class="muted">使用平台实际存储的采集方式，查看各领域证据的积累路径。</p><div class="table-scroll"><table><thead><tr><th>领域</th><th v-for="method in methods" :key="method.id">{{ method.name }}</th></tr></thead><tbody><tr v-for="cat in categoryStats" :key="cat.id"><td>{{ cat.name }}</td><td v-for="method in methods" :key="method.id"><span class="heat-cell" :style="{ background: `rgba(42,120,214,${Math.min(.7, .04 + methodCount(cat.id, method.id) / Math.max(1, cat.count) * .6)})` }">{{ methodCount(cat.id, method.id) }}</span></td></tr></tbody></table></div></section></div>
          <div class="radar-two-columns"><section v-for="dimension in dimensions.filter(d => ['openness', 'evidenceType'].includes(d.key))" :key="dimension.key" class="radar-panel"><h2>{{ dimension.name }}分布</h2><button v-for="label in dimension.labels" :key="label" type="button" class="org-row" @click="filters[dimension.key] = label"><span>{{ label }}</span><span class="org-meter"><i :style="{ width: `${percent(dimensionCount(dimension.key, label), filtered.length)}%` }"></i></span><b>{{ dimensionCount(dimension.key, label) }}</b></button></section></div>
        </template>
        <section v-else class="radar-panel"><div class="panel-head"><div><h2>研究明细库</h2><p>与平台共用观察记录；点击标题打开完整研究内容和来源。</p></div><label>排序 <select v-model="sort"><option value="date">日期倒序</option><option value="captured">最近采集</option><option value="title">标题</option></select></label></div><div class="table-scroll"><table class="detail-table"><thead><tr><th>日期</th><th>研究成果与领域</th><th>来源机构</th><th>交付阶段</th><th>价值 / 优先级</th><th>采集方式</th><th>来源数</th></tr></thead><tbody><tr v-for="item in pageItems" :key="item.id"><td>{{ item.date || '—' }}<small>{{ item.dateLabel }}</small></td><td><button type="button" class="record-title" @click="openObservation(item)">{{ item.title }} ↗</button><small>{{ categoryName(item.category) }}</small><p>{{ item.summary }}</p></td><td>{{ item.organizations.join('、') || '未标注' }}</td><td :title="item.stageRaw">{{ item.stage }}</td><td :title="item.valueRaw">{{ item.tier }} / {{ item.priority }}</td><td>{{ methodName(item.ingest_method) }}</td><td>{{ item.sources.length }}</td></tr></tbody></table></div><div class="pagination"><span>共 {{ filtered.length }} 条 · 第 {{ page }} / {{ pageCount }} 页</span><button type="button" :disabled="page <= 1" @click="page--">上一页</button><button type="button" :disabled="page >= pageCount" @click="page++">下一页</button></div></section>
      </template>
      <details class="radar-method"><summary>统计口径与数据来源</summary><p>数据来自当前租户平台数据库中「具身智能」主题下的全部有效研究观察，排除回收站记录。各视图共享同一组筛选条件；月份为自然月范围，最近 3 个月包含当前月。页面打开、返回窗口及每 60 秒自动刷新，也可手动刷新。来源机构仅取来源的机构字段，不由标题推断；新采集记录优先使用数据库结构化标注；历史阶段、开放程度、证据类型依照原方案规则从正文同名标题归并，无法归并时列为“未标注”，明细与完整记录保留原文。A 类表示优先跟踪，不表示技术成熟。区域未标注时不推断国别。</p></details>
      </template>
    </template>
    <p v-else class="radar-empty" role="status">正在读取全部平台研究记录…</p>
  </section>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import api from '../../../api.js'
import { filterObservations, loadRadarObservations } from './marketIntelRadar.js'
import MarketIntelAssessment from './MarketIntelAssessment.vue'
import { taxonomy } from './radarTaxonomy.js'
const assessment = ref({})
const emit = defineEmits(['synced'])
const router = useRouter()
const records = ref([]), topicCategories = ref([]), loading = ref(false), ready = ref(false), error = ref(''), syncedAt = ref('')
const activeTab = ref('judgement'), sort = ref('date'), page = ref(1)
const filters = reactive({ months: '', categories: [], organization: '', query: '', month: '', stage: '', tier: '', priority: '', openness: '', evidenceType: '' })
const tabs = [{ id: 'judgement', name: '行业研判' }, { id: 'overview', name: '技术总览' }, { id: 'maturity', name: '成熟度与价值' }, { id: 'orgs', name: '机构与生态' }, { id: 'data', name: '研究明细库' }]
const windows = [{ value: '', name: '全部' }, { value: '12', name: '近12个月' }, { value: '6', name: '近6个月' }, { value: '3', name: '近3个月' }]
const methods = [{ id: 'agent', name: 'Agent研究' }, { id: 'manual', name: '手动录入' }, { id: 'source_task', name: '来源任务' }, { id: 'file_import', name: '文件导入' }]
const dimensions = [
  { key: 'stage', name: '交付阶段', labels: [...taxonomy.stage.labels, '未标注'] },
  { key: 'tier', name: '商业价值', labels: [...taxonomy.tier.labels, '未标注'] },
  { key: 'priority', name: '优先级', labels: ['A', 'B', 'C', '未标注'] },
  { key: 'openness', name: '开放程度', labels: [...taxonomy.openness.labels, '未标注'] },
  { key: 'evidenceType', name: '证据类型', labels: [...taxonomy.evidenceType.labels, '未标注'] },
]
const dimensionCount = (key, label, category) => filtered.value.filter(i => i[key] === label && (category === undefined || i.category === category)).length
const markedCount = computed(() => filtered.value.filter(i => i.stage !== '未标注').length)
const palette = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#ce6d99', '#598b40', '#7969c4', '#268b95', '#a17d52', '#b75d5d', '#70849e', '#4f6083', '#9299a1']
const categories = computed(() => [...topicCategories.value, { id: '', name: '待分类' }])
const color = id => palette[Math.max(0, categories.value.findIndex(c => c.id === id)) % palette.length]
const categoryName = id => categories.value.find(c => c.id === id)?.name || '其他领域'
const methodName = id => methods.find(m => m.id === id)?.name || '未标注'
const percent = (a, b) => b ? Math.round(a / b * 100) : 0
const organizations = computed(() => [...new Set(records.value.flatMap(i => i.organizations))].sort((a, b) => a.localeCompare(b, 'zh')))
const filtered = computed(() => filterObservations(records.value, filters))
const sourcedCount = computed(() => filtered.value.filter(i => i.sources.some(s => /^https?:\/\//.test(s.url))).length)
const unknownOrgs = computed(() => filtered.value.filter(i => !i.organizations.length).length)
const publishedCount = computed(() => filtered.value.filter(i => i.dateLabel === '发布日期').length)
const categoryStats = computed(() => categories.value.map(c => {
  const items = filtered.value.filter(i => i.category === c.id)
  return { ...c, count: items.length, sourced: items.filter(i => i.sources.some(s => /^https?:\/\//.test(s.url))).length, latest: items.map(i => i.date).sort().at(-1) }
}))
const activeCategories = computed(() => categoryStats.value.filter(c => c.count))
const orgStats = computed(() => {
  const counts = new Map()
  filtered.value.forEach(i => i.organizations.forEach(org => counts.set(org, (counts.get(org) || 0) + 1)))
  return [...counts].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, 'zh'))
})
const orgMax = computed(() => Math.max(1, ...orgStats.value.map(o => o.count)))
const kpis = computed(() => [
  { label: '研究记录', value: filtered.value.length, unit: '条', note: `平台有效记录共 ${records.value.length} 条` },
  { label: 'A类重点', value: filtered.value.filter(i => i.priority === 'A').length, unit: '条', note: '原记录标注 · 建议优先跟踪' },
  { label: '近3个月进展', value: filterObservations(filtered.value, { months: '3' }).length, unit: '条', note: '当前筛选内，按自然月统计' },
  { label: '来源机构', value: orgStats.value.length, unit: '家', note: '按来源机构字段去重' },
  { label: '价值极高 / 很高', value: filtered.value.filter(i => ['极高', '很高'].includes(i.tier)).length, unit: '条', note: '记录原有分析判断' },
  { label: '产品 / API阶段', value: filtered.value.filter(i => i.stage === '产品/API阶段').length, unit: '条', note: `${markedCount.value} 条有阶段标注` },
])
const trend = computed(() => {
  const dated = filtered.value.filter(i => i.date)
  const months = [...new Set(dated.map(i => i.date.slice(0, 7)))].sort()
  if (!months.length) return []
  const result = [], last = months.at(-1)
  let [y, m] = months[0].split('-').map(Number)
  while (`${y}-${String(m).padStart(2, '0')}` <= last) {
    const month = `${y}-${String(m).padStart(2, '0')}`
    const items = dated.filter(i => i.date.startsWith(month))
    result.push({ month, total: items.length, parts: activeCategories.value.map(c => ({ ...c, count: items.filter(i => i.category === c.id).length })).filter(c => c.count) })
    if (++m > 12) { m = 1; y++ }
  }
  return result
})
const trendMax = computed(() => Math.max(1, ...trend.value.map(b => b.total)))
const recent = computed(() => [...filtered.value].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 6))
const sorted = computed(() => [...filtered.value].sort((a, b) => sort.value === 'title' ? a.title.localeCompare(b.title, 'zh') : sort.value === 'captured' ? b.captured_at.localeCompare(a.captured_at) : b.date.localeCompare(a.date)))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / 20)))
const pageItems = computed(() => sorted.value.slice((page.value - 1) * 20, page.value * 20))
const methodCount = (id, method) => filtered.value.filter(i => i.category === id && i.ingest_method === method).length
function toggleCategory(id) { filters.categories = filters.categories.includes(id) ? filters.categories.filter(c => c !== id) : [...filters.categories, id] }
function reset() { Object.assign(filters, { months: '', categories: [], organization: '', query: '', month: '', stage: '', tier: '', priority: '', openness: '', evidenceType: '' }) }
function openObservation(item) { router.push({ name: 'market-intel-observation', params: { id: item.id }, query: { topic: 'embodied-intelligence' } }) }
watch([filtered, sort], () => { page.value = 1 })
let timer, controller, disposed = false
async function load() {
  if (loading.value || disposed) return
  loading.value = true
  controller = new AbortController()
  try {
    const [result, judgementResult] = await Promise.all([loadRadarObservations(api, controller.signal), api.get('/market-research/judgements/embodied-intelligence', { signal: controller.signal })])
    if (disposed) return
    assessment.value = judgementResult.data
    records.value = result.items
    topicCategories.value = result.topics.find(t => t.id === 'embodied-intelligence')?.categories || []
    syncedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    error.value = ''; ready.value = true
    emit('synced', result.topics)
  } catch (err) { if (!disposed) error.value = err.response?.data?.detail || '平台数据同步失败，请重试。' }
  finally { loading.value = false }
}
function refreshVisible() { if (!document.hidden) load() }
onMounted(() => { load(); timer = setInterval(refreshVisible, 60000); window.addEventListener('focus', refreshVisible); document.addEventListener('visibilitychange', refreshVisible) })
onBeforeUnmount(() => { disposed = true; controller?.abort(); clearInterval(timer); window.removeEventListener('focus', refreshVisible); document.removeEventListener('visibilitychange', refreshVisible) })
</script>

<style scoped>
.technology-radar { --blue:#2a78d6; --ink:#18202a; --muted:#68727d; --line:#e1e4e7; color:var(--ink); font:14px/1.55 system-ui,-apple-system,'PingFang SC',sans-serif; min-width:0; }
button,input,select { font:inherit; } button { cursor:pointer; } button:disabled { opacity:.45; cursor:default; } button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible { outline:2px solid var(--blue); outline-offset:3px; }
.radar-head { display:flex; justify-content:space-between; gap:20px; align-items:center; margin:8px 0 18px; } h1 { margin:0; font-size:26px; letter-spacing:-.5px; } .radar-head p,.panel-head p,.muted { color:var(--muted); font-size:12px; margin:5px 0 12px; } .sync { display:flex; gap:12px; align-items:center; color:var(--muted); font-size:12px; } .sync button,.pagination button { background:white; border:1px solid var(--line); border-radius:5px; padding:5px 10px; }
.radar-tabs { display:flex; flex-wrap:wrap; gap:4px; margin-bottom:16px; border-bottom:1px solid var(--line); padding-bottom:10px; } .radar-tabs button { border:0; background:transparent; color:var(--muted); border-radius:5px; padding:8px 16px; font-weight:600; } .radar-tabs button[aria-current] { background:#18202a; color:white; }
.radar-filters { background:#fcfcfb; border:1px solid var(--line); border-radius:8px; padding:12px 14px; margin-bottom:16px; } .filter-row { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px; } .filter-label { color:var(--muted); font-size:12px; min-width:28px; } .segments { display:flex; border:1px solid #ccd2d8; border-radius:5px; overflow:hidden; margin-right:12px; } .segments button { border:0; border-right:1px solid var(--line); background:none; font-size:12px; padding:5px 9px; } .segments button[aria-pressed=true] { background:#e9f1fb; color:#205eaa; box-shadow:inset 0 -2px var(--blue); } label { color:var(--muted); font-size:12px; display:flex; gap:7px; align-items:center; } input,select { border:1px solid #ccd2d8; background:white; color:var(--ink); border-radius:5px; min-height:29px; padding:3px 7px; max-width:210px; } .search { margin-left:auto; } .categories { gap:7px; } .chip { border:1px solid #d7dce0; background:none; border-radius:20px; font-size:12px; padding:3px 9px; } .chip[aria-pressed=true] { background:#eaf2fb; border-color:var(--blue); } .chip i,.legend i,.dot { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:6px; } .filter-foot { display:flex; justify-content:space-between; font-size:12px; color:var(--muted); } .text-button { border:0; background:none; color:var(--blue); padding:0; text-align:left; }
.radar-kpis { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:12px; margin-bottom:16px; } .radar-kpis article { background:#fcfcfb; border:1px solid var(--line); border-radius:7px; padding:14px 12px; } .radar-kpis article>span { color:var(--muted); font-size:12px; } .radar-kpis strong { display:block; font-size:29px; font-weight:650; margin:7px 0; font-variant-numeric:tabular-nums; } .radar-kpis small { font-size:12px; font-weight:400; margin-left:5px; } .radar-kpis p { font-size:11px; color:var(--muted); margin:0; }
.radar-panel { background:#fcfcfb; border:1px solid var(--line); border-radius:8px; padding:18px; margin-bottom:16px; min-width:0; } h2 { margin:0 0 9px; font-size:16px; font-weight:650; } .panel-head { display:flex; justify-content:space-between; gap:15px; align-items:baseline; } .legend { display:flex; flex-wrap:wrap; gap:5px 16px; color:var(--muted); font-size:11px; margin:4px 0 12px; } .trend-scroll,.table-scroll { overflow-x:auto; } .trend { height:240px; display:flex; gap:4px; align-items:end; border-bottom:1px solid var(--line); padding:0 6px 12px; } .trend-column { height:220px; flex:1; min-width:32px; background:none; border:0; display:flex; flex-direction:column; align-items:center; justify-content:end; padding:0 1px; } .trend-column:hover { background:#edf3fa; } .bar-stack { display:flex; flex-direction:column-reverse; width:23px; overflow:hidden; border-radius:3px 3px 0 0; } .bar-stack>span { display:block; width:100%; min-height:1px; } .bar-value { font-size:11px; color:var(--muted); height:18px; } .bar-label { font-size:10px; color:var(--muted); margin-top:7px; }
.table-scroll table { width:100%; border-collapse:collapse; text-align:left; white-space:nowrap; font-size:12px; } th { color:var(--muted); font-weight:500; } td,th { border-bottom:1px solid #e9ebee; padding:10px 12px; } td:first-child,th:first-child { padding-left:0; } tbody tr:hover { background:#f3f6f9; } .meter { display:inline-block; width:72px; height:5px; background:#eceff2; border-radius:3px; margin-right:10px; vertical-align:middle; } .meter i { display:block; height:100%; } .radar-two-columns { display:grid; grid-template-columns:1fr 1fr; gap:16px; align-items:start; } .insights { padding-left:19px; color:#525e6a; line-height:1.9; font-size:13px; } .insights li { margin-bottom:13px; } .feed-item { display:block; background:none; border:0; border-bottom:1px solid var(--line); text-align:left; padding:10px 0; width:100%; } .feed-item span { display:block; color:var(--muted); font-size:11px; } .feed-item strong { font-size:13px; font-weight:550; } .feed-item:hover strong { color:var(--blue); }
.dimension-note { color:var(--muted); max-width:800px; line-height:1.9; } .dimension-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; margin-top:22px; } .dimension-grid article { border:1px dashed #cbd2da; padding:20px; border-radius:5px; } .dimension-grid span,.dimension-grid small { display:block; font-size:12px; color:var(--muted); } .dimension-grid strong { display:block; font-size:22px; margin:7px 0; color:#8d969f; font-weight:450; } .coverage-grid { display:grid; grid-template-columns:repeat(3,1fr); margin:22px 0; gap:15px; } .coverage-grid strong { display:block; font-size:27px; font-weight:500; } .coverage-grid span { font-size:12px; color:var(--muted); }
.org-row { display:flex; align-items:center; gap:12px; background:none; border:0; width:100%; padding:8px 0; text-align:left; font-size:12px; } .org-row>span:first-child { width:42%; overflow-wrap:anywhere; } .org-meter { flex:1; background:#edf0f3; height:9px; border-radius:3px; } .org-meter i { display:block; height:100%; background:var(--blue); border-radius:3px; } .org-row b { width:24px; text-align:right; } .heat-button { border:0; border-radius:3px; width:100%; min-width:35px; padding:6px; } .heat-cell { display:block; text-align:center; padding:4px; border-radius:3px; }
.detail-table { table-layout:fixed; min-width:1100px; } .detail-table th:first-child { width:108px; } .detail-table th:nth-child(2) { width:35%; } .detail-table td { white-space:normal; vertical-align:top; } .detail-table small { display:block; color:var(--muted); font-size:11px; margin-top:4px; } .detail-table p { font-size:12px; color:var(--muted); margin:7px 0; line-height:1.7; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; } .record-title { border:0; background:none; color:var(--ink); padding:0; text-align:left; font-weight:600; } .record-title:hover { color:var(--blue); } .pagination { display:flex; justify-content:flex-end; align-items:center; gap:12px; margin-top:16px; font-size:12px; color:var(--muted); } .radar-method { font-size:12px; color:var(--muted); margin:6px 0 22px; } .radar-method summary { cursor:pointer; color:#465567; } .radar-method p { line-height:1.8; max-width:960px; } .radar-empty { padding:40px 18px; text-align:center; color:var(--muted); border:1px dashed var(--line); border-radius:7px; margin-bottom:16px; } .radar-error { background:#fff1f0; color:#a33832; padding:18px; margin-bottom:18px; }
@media (max-width:1100px) { .radar-kpis { grid-template-columns:repeat(3,1fr); } .radar-two-columns { grid-template-columns:1fr; } }
@media (max-width:640px) { .radar-head { align-items:start; flex-direction:column; gap:10px; } h1 { font-size:23px; } .radar-tabs button { padding:7px 9px; font-size:12px; } .search { margin-left:0; } .radar-kpis { grid-template-columns:repeat(2,1fr); gap:8px; } .radar-panel { padding:13px; } .dimension-grid { grid-template-columns:repeat(2,1fr); } .coverage-grid { grid-template-columns:1fr; } .panel-head { flex-wrap:wrap; } }
</style>
