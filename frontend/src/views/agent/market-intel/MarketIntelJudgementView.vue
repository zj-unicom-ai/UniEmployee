<template>
  <main class="judgement-page">
    <div class="judgement-shell">
      <header class="page-topbar">
        <button class="back-link" type="button" @click="backToWorkbench">← 返回研究主题</button>
        <span class="desk-mark"><i>察</i> 小察 · 行业深度研究</span>
      </header>

      <div v-if="loading" class="state-message"><span class="loader"></span>正在整理研判与证据…</div>
      <div v-else-if="error" class="state-message error-message" role="alert">
        <span>{{ error }}</span><button type="button" @click="loadPage">重试</button>
      </div>

      <template v-else>
        <nav class="breadcrumbs" aria-label="面包屑">
          <button type="button" @click="backToWorkbench">研究主题</button><span>／</span>
          <button type="button" @click="backToTopic">{{ scope.topic?.name || '行业观察' }}</button>
          <template v-if="!isTopic"><span>／</span><span>{{ scope.category?.name || '细分领域' }}</span></template>
        </nav>

        <section class="report-hero" :class="`accent-${scope.topic?.accent || 'blue'}`">
          <div class="hero-copy">
            <span class="eyebrow">{{ isTopic ? 'TOPIC SYNTHESIS' : 'CATEGORY JUDGEMENT' }} <i>／</i> {{ scope.topic?.eyebrow }}</span>
            <h1>{{ isTopic ? `${scope.topic?.name} · 主题综合研判` : `${scope.category?.name} · 趋势研判` }}</h1>
            <p>{{ report
              ? `本版综合引用 ${citedEvidenceCount} 条观察、${report.sources?.length || 0} 个来源。下方按关键变化、趋势驱动和后续信号展开。`
              : (isTopic
                ? '汇总各细分领域的研判，观察主题级趋势、交叉影响与证据缺口。'
                : '根据持续积累的行业证据，形成可追溯、可更新的细分领域判断。') }}</p>
            <div class="hero-meta">
              <span v-if="report">第 {{ report.version }} 版</span>
              <span v-if="report">置信度：{{ confidenceLabel(report.confidence) }}</span>
              <span v-if="report">资料截止 {{ formatDate(report.data_cutoff) }}</span>
              <span v-if="report">更新于 {{ formatDate(report.created_at) }}</span>
              <span v-if="!report">研判尚未形成</span>
            </div>
          </div>
          <div class="hero-actions">
            <span class="freshness" :class="`freshness-${freshness}`">{{ freshnessLabel }}</span>
            <button class="primary-action" type="button" :disabled="isTopic && !overview?.reported_category_count" @click="generateReport">
              <span aria-hidden="true">✳</span>{{ report ? '更新研判' : '生成研判' }}
            </button>
            <button v-if="isTopic" class="secondary-action" type="button" @click="loadPage">刷新数据库分析</button>
            <button v-if="!isTopic" class="secondary-action" type="button" @click="collectionOpen = true">＋ 获取新依据</button>
          </div>
        </section>

        <section v-if="freshness === 'stale'" class="stale-banner" role="status">
          <span class="stale-icon">↗</span>
          <div><strong>{{ staleMessage }}</strong><p>{{ isTopic ? '请先完成相关细分研判，再更新主题综合判断。' : '这些记录已经进入该细分领域，可更新研判后纳入分析。' }}</p></div>
          <button v-if="!isTopic" type="button" @click="generateReport">吸收新证据</button>
        </section>

        <MarketIntelJudgementDashboard
          v-if="report"
          :report="report"
          :evidence="evidence"
          :total-evidence="evidenceCount"
          :cited-evidence="citedEvidenceCount"
          :new-evidence="newEvidenceCount"
          :is-topic="isTopic"
          :categories="isTopic ? (overview?.categories || []) : []"
          :theme-accent="scope.topic?.accent || 'blue'"
          :reported-category-count="overview?.reported_category_count || 0"
          :category-count="overview?.category_count || 0"
          @open-observation="openObservation"
          @open-category="openCategory"
        >
          <template v-if="isTopic" #topic-insights>
            <MarketIntelTopicInsights :observations="evidence" :categories="overview?.categories || []" :report="report" @open-observation="openObservation" @open-category="openCategory" @collect="collectForCategory" />
          </template>
        </MarketIntelJudgementDashboard>

        <section v-else class="empty-report">
          <span class="empty-sigil" aria-hidden="true">⌁</span>
          <div>
            <span class="section-kicker">JUDGEMENT NOT CREATED</span>
            <h2>{{ isTopic ? '主题综合研判还没有形成' : `“${scope.category?.name || '该领域'}”还没有分类研判` }}</h2>
            <p v-if="isTopic">目前有 {{ overview?.reported_category_count || 0 }} 个细分领域形成了研判。主题判断将从这些分类研判汇总，不直接从文章列表生成。</p>
            <p v-else>当前积累 {{ evidenceCount }} 条研究依据。生成时会引用工作台中的证据和一手来源，并保存为可追溯的第一个版本。</p>
            <div class="empty-actions">
              <button class="primary-action" type="button" :disabled="(isTopic && !overview?.reported_category_count) || (!isTopic && !evidenceCount)" @click="generateReport">{{ isTopic ? '形成主题综合研判' : '基于现有证据生成研判' }}</button>
              <button v-if="!isTopic" class="secondary-action" type="button" @click="collectionOpen = true">＋ 先获取研究依据</button>
            </div>
            <p v-if="isTopic && !overview?.reported_category_count" class="disabled-hint">先打开一个细分领域，积累证据并形成分类研判。</p>
            <p v-else-if="!isTopic && !evidenceCount" class="disabled-hint">细分研判需要至少一条已经入库的研究观察。</p>
          </div>
        </section>

        <MarketIntelTopicInsights v-if="isTopic && !report" :observations="evidence" :categories="overview?.categories || []" @open-observation="openObservation" @open-category="openCategory" @collect="collectForCategory" />

        <section v-if="isTopic && !evidence.length" class="category-judgements">
          <div class="section-heading"><div><span class="section-kicker">SUBCATEGORY JUDGEMENTS</span><h2>细分领域进展</h2></div><span class="source-badge">{{ overview?.reported_category_count || 0 }} / {{ overview?.category_count || 0 }} 已形成研判</span></div>
          <div class="subjudgement-grid">
            <button v-for="item in overview?.categories || []" :key="item.id" type="button" class="subjudgement-card" @click="openCategory(item.id)">
              <span class="sub-card-heading"><strong>{{ item.name }}</strong><b>{{ item.evidence_count || 0 }} 条依据</b></span>
              <p>{{ item.report?.conclusion || item.description }}</p>
              <span class="sub-card-foot"><i :class="`dot-${item.freshness || 'missing'}`"></i>{{ item.report ? `第 ${item.report.version} 版 · ` : '' }}{{ judgementStatus(item) }}<b aria-hidden="true">↗</b></span>
            </button>
          </div>
        </section>

        <details v-else class="evidence-section evidence-disclosure">
          <summary class="section-heading"><div><span class="section-kicker">EVIDENCE FOR THIS JUDGEMENT</span><h2 id="evidence-title">支撑观察</h2></div><span class="source-badge">{{ evidenceCount }} 条累计 · 本版引用 {{ citedEvidenceCount }} 条</span></summary>
          <div v-if="evidence.length" class="evidence-list">
            <article v-for="item in evidence" :key="item.id" class="evidence-item">
              <button class="evidence-open" type="button" @click="openObservation(item)">
                <span class="evidence-date">{{ formatDate(item.published_at || item.captured_at) }}</span>
                <span class="evidence-copy"><strong>{{ item.title }}</strong><small>{{ item.summary || '打开记录查看完整研究正文与来源。' }}</small></span>
                <span class="evidence-arrow" aria-hidden="true">↗</span>
              </button>
              <div class="evidence-meta"><span>{{ item.source_name || methodLabel(item.ingest_method) }}</span><span>{{ item.sources?.length || 0 }} 个来源</span><span v-if="report?.evidence_ids?.includes(item.id)" class="cited-tag">本版已引用</span><span v-else-if="item.captured_at > (report?.data_cutoff || '')" class="new-tag">新证据</span></div>
            </article>
          </div>
          <p v-else class="muted-copy">还没有已入库的研究观察。</p>
        </details>

        <details v-if="history.length" class="revision-history history-disclosure">
          <summary class="section-heading"><div><span class="section-kicker">JUDGEMENT HISTORY</span><h2 id="history-title">版本演进</h2></div><span class="source-badge">保留 {{ history.length }} 个版本</span></summary>
          <div class="history-list">
            <article v-for="(version, index) in history" :key="version.id" class="history-item" :class="{ 'history-current': index === 0 }">
              <span class="history-marker"></span>
              <div class="history-copy"><div class="history-topline"><strong>第 {{ version.version }} 版</strong><span v-if="index === 0" class="current-version">当前版本</span><span>{{ formatDate(version.created_at) }}</span><span>置信度 {{ confidenceLabel(version.confidence) }}</span></div><p>{{ version.conclusion }}</p><small>截止 {{ formatDate(version.data_cutoff) }} · 引用 {{ version.evidence_count }} 条观察 · {{ version.source_count }} 个来源</small></div>
            </article>
          </div>
        </details>
      </template>
    </div>

    <MarketIntelTopicChatDialog
      v-if="chatOpen"
      :topic="scope.topic"
      :category="isTopic ? null : scope.category"
      :observations="isTopic ? [] : evidence"
      :observation-count="isTopic ? topicEvidenceCount : evidenceCount"
      :current-judgement="report"
      :category-judgements="isTopic ? (overview?.categories || []) : []"
      :initial-prompt="initialPrompt"
      @close="closeChat"
    />
    <MarketIntelCollectionDialog
      v-if="collectionOpen"
      :topics="collectionTopics"
      :initial-topic="topicId"
      :initial-category="collectionCategory || categoryId"
      @close="collectionOpen = false"
      @saved="handleCollected"
      @open="openObservation"
    />
  </main>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'
import MarketIntelTopicInsights from './MarketIntelTopicInsights.vue'
import { loadRadarObservations } from './marketIntelRadar.js'
import MarketIntelJudgementDashboard from './MarketIntelJudgementDashboard.vue'
import MarketIntelCollectionDialog from './MarketIntelCollectionDialog.vue'
import MarketIntelTopicChatDialog from './MarketIntelTopicChatDialog.vue'

const route = useRoute()
const router = useRouter()
const topicId = computed(() => String(route.params.topicId || ''))
const categoryId = computed(() => String(route.params.categoryId || ''))
const isTopic = computed(() => !categoryId.value)
const loading = ref(true)
const error = ref('')
const overview = ref(null)
const detail = ref(null)
const evidence = ref([])
const history = ref([])
const collectionTopics = ref([])
const chatOpen = ref(false)
const collectionOpen = ref(false)
const initialPrompt = ref('')
const collectionCategory = ref('')
function collectForCategory(id) { collectionCategory.value = id; collectionOpen.value = true }

const scope = computed(() => isTopic.value
  ? { topic: overview.value?.topic, category: null }
  : { topic: detail.value?.topic, category: detail.value?.category })
const judgement = computed(() => isTopic.value ? overview.value?.topic_report : detail.value)
const report = computed(() => judgement.value?.report || null)
const freshness = computed(() => judgement.value?.freshness || 'missing')
const freshnessLabel = computed(() => {
  if (freshness.value === 'stale') return isTopic.value ? '细分判断有更新' : `${newEvidenceCount.value} 条新证据待吸收`
  if (freshness.value === 'current') return '当前无待同步变更'
  return '等待形成研判'
})
const staleMessage = computed(() => isTopic.value
  ? `有 ${judgement.value?.updated_category_count || 0} 个细分研判版本更新，${judgement.value?.new_evidence_count || 0} 条观察新增或发生变化，需重新综合。`
  : `有 ${newEvidenceCount.value} 条新增观察晚于当前研判资料截止时间。`)
const evidenceCount = computed(() => Number(judgement.value?.evidence_count || 0))
const newEvidenceCount = computed(() => Number(judgement.value?.new_evidence_count || 0))
const citedEvidenceCount = computed(() => report.value?.evidence_ids?.length || 0)
const topicEvidenceCount = computed(() => (overview.value?.categories || []).reduce((sum, item) => sum + Number(item.evidence_count || 0), 0))

function confidenceLabel(value) { return ({ high: '较高', medium: '中等', low: '有限' })[value] || '中等' }
function judgementStatus(item) {
  if (!item?.report) return '尚未形成研判'
  if (item.freshness === 'stale') return `${item.new_evidence_count || 0} 条新依据待吸收`
  return '判断已更新'
}
function methodLabel(method) { return ({ agent: 'Agent 研究', manual: '手动录入', source_task: '来源任务', file_import: '文件导入' })[method] || '研究记录' }
function formatDate(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}

let loadVersion = 0
async function loadPage() {
  const version = ++loadVersion
  loading.value = true
  error.value = ''
  try {
    if (isTopic.value) {
      const [overviewResult, historyResult, allEvidence] = await Promise.all([
        api.get(`/market-research/judgements/${encodeURIComponent(topicId.value)}`),
        api.get(`/market-research/judgements/${encodeURIComponent(topicId.value)}/history`),
        loadRadarObservations(api, undefined, topicId.value),
      ])
      if (version !== loadVersion) return
      overview.value = overviewResult.data
      history.value = historyResult.data || []
      detail.value = null
      evidence.value = allEvidence.items
      collectionTopics.value = allEvidence.topics
    } else {
      const [judgementResult, workbenchResult, historyResult] = await Promise.all([
        api.get(`/market-research/judgements/${encodeURIComponent(topicId.value)}/${encodeURIComponent(categoryId.value)}`),
        api.get('/market-research/workbench', { params: { topic_id: topicId.value, category_id: categoryId.value, limit: 1 } }),
        api.get(`/market-research/judgements/${encodeURIComponent(topicId.value)}/history`, { params: { category_id: categoryId.value } }),
      ])
      if (version !== loadVersion) return
      detail.value = judgementResult.data
      evidence.value = judgementResult.data.evidence || []
      collectionTopics.value = workbenchResult.data.topics || []
      history.value = historyResult.data || []
    }
  } catch (err) {
    if (version !== loadVersion) return
    error.value = err.response?.data?.detail || '研判暂时无法加载，请检查连接后重试。'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

function backToWorkbench() {
  router.push({ name: 'market-intel-topic', params: { topicId: topicId.value } })
}
function backToTopic() { router.push({ name: 'market-intel-judgement', params: { topicId: topicId.value } }) }
function openCategory(id) {
  router.push({ name: 'market-intel-judgement', params: { topicId: topicId.value, categoryId: id } })
}
function openObservation(item) {
  collectionOpen.value = false
  router.push({ name: 'market-intel-observation', params: { id: item.id }, query: { topic: item.topic_id, category: item.category_id || undefined } })
}
function generateReport() {
  initialPrompt.value = isTopic.value
    ? '请基于本页提供的各细分领域最新研判，生成或更新主题综合研判。综合共同趋势、交叉影响、分化信号、机会风险和证据缺口，不要绕过分类直接从资讯列表总结。引用细分研判中的来源与证据，并调用 save_market_judgement 保存新的主题版本。'
    : `请基于工作台中“${scope.value.category?.name || '当前细分领域'}”的已入库观察，生成或更新一份有证据链的趋势研判。正文应包含研究口径、关键判断、证据、驱动因素、机会与风险、后续跟踪指标和不确定性。只引用本领域证据，带上实际引用 observation IDs、来源和最新证据截止时间，并调用 save_market_judgement 保存分类版本。`
  chatOpen.value = true
}
async function closeChat() {
  chatOpen.value = false
  await loadPage()
}
async function handleCollected(item) {
  collectionOpen.value = false
  evidence.value = [item, ...evidence.value.filter(record => record.id !== item.id)]
  await loadPage()
}

watch(() => `${topicId.value}/${categoryId.value}`, loadPage, { immediate: true })
</script>

<style scoped>
.judgement-page { min-height: 100%; padding: 0 34px 44px; color: #16263d; background: radial-gradient(ellipse at 82% 0%, rgba(59,130,246,.07), transparent 32%), #f6f8fb; font: 15px/1.7 'DM Sans','Noto Sans SC',sans-serif; }
.judgement-shell { width: min(1360px,100%); margin: 0 auto; }
.page-topbar { display:flex; align-items:center; justify-content:space-between; min-height:62px; border-bottom:1px solid #e3eaf2; }
.back-link,.breadcrumbs button { padding:0; border:0; color:#54708e; background:transparent; cursor:pointer; font:inherit; }
.back-link:hover,.breadcrumbs button:hover { color:#1d4ed8; }
.desk-mark { display:flex; align-items:center; gap:9px; color:#64748b; font-size:13px; }
.desk-mark i { display:grid; width:27px; height:27px; place-items:center; border-radius:50%; color:#fff; background:#3b82f6; font-style:normal; font-weight:700; }
.breadcrumbs { display:flex; align-items:center; gap:10px; padding:20px 0 14px; color:#94a3b8; font-size:13px; }
.report-hero { display:flex; align-items:center; justify-content:space-between; gap:32px; padding:30px 34px; border:1px solid #dce6f2; border-radius:14px; background:linear-gradient(110deg,#fff,#f2f7ff); box-shadow:0 8px 25px rgba(31,64,110,.04); }
.report-hero.accent-copper { background:linear-gradient(110deg,#fff,#fcf5ef); border-color:#eadfd3; }
.report-hero.accent-green { background:linear-gradient(110deg,#fff,#f1f8f4); border-color:#dce9df; }
.hero-copy { max-width:900px; min-width:0; }
.eyebrow,.section-kicker { color:#71839b; font:600 11px 'DM Mono','Noto Sans SC',sans-serif; letter-spacing:.09em; }
.eyebrow i { color:#a8b7c9; font-style:normal; padding:0 4px; }
.hero-copy h1 { margin:9px 0 8px; color:#152945; font:600 clamp(25px,3vw,34px)/1.35 'Noto Serif SC','Noto Sans SC',serif; }
.hero-copy p { max-width:880px; margin:0; color:#485d78; font-size:17px; line-height:1.8; }
.hero-meta { display:flex; flex-wrap:wrap; gap:8px 20px; margin-top:18px; color:#8291a4; font-size:12px; }
.hero-actions { display:flex; flex:0 0 auto; flex-direction:column; align-items:stretch; gap:9px; min-width:158px; }
.freshness { display:inline-flex; justify-content:center; padding:5px 10px; border-radius:99px; color:#52657d; background:#eaf0f7; font-size:12px; }
.freshness-current { color:#17654a; background:#e5f5ed; }
.freshness-stale { color:#965b08; background:#fff1d5; }
.freshness-missing { color:#64748b; background:#edf1f6; }
.primary-action,.secondary-action { display:inline-flex; justify-content:center; align-items:center; gap:7px; min-height:41px; padding:8px 13px; border:1px solid #2563eb; border-radius:7px; color:#fff; background:#3478e5; cursor:pointer; font:600 13px 'Noto Sans SC',sans-serif; white-space:nowrap; }
.primary-action:hover:not(:disabled) { background:#2563eb; }
.primary-action:disabled { opacity:.45; cursor:not-allowed; }
.secondary-action { border-color:#cbd7e5; color:#36506f; background:#fff; }
.secondary-action:hover { border-color:#9ab4d2; background:#f8fbff; }
.stale-banner { display:flex; align-items:center; gap:13px; margin-top:15px; padding:14px 17px; border:1px solid #f1d59e; border-radius:9px; color:#80520c; background:#fff9eb; }
.stale-icon { display:grid; width:30px; height:30px; flex:0 0 auto; place-items:center; border-radius:50%; background:#ffefc9; font-size:18px; }
.stale-banner div { flex:1; min-width:0; }
.stale-banner strong { font-size:14px; }
.stale-banner p { margin:2px 0 0; color:#98743b; font-size:13px; }
.stale-banner button { padding:7px 10px; border:1px solid #e5c67f; border-radius:6px; color:#79530f; background:#fff; cursor:pointer; font:600 12px 'Noto Sans SC',sans-serif; }
.category-judgements,.evidence-section { border:1px solid #e2e8f0; border-radius:11px; background:#fff; box-shadow:0 4px 16px rgba(18,44,77,.025); }
.section-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:15px; margin-bottom:17px; }
.evidence-disclosure > summary,.history-disclosure > summary { position:relative; padding-right:38px; cursor:pointer; list-style:none; }
.evidence-disclosure > summary::-webkit-details-marker,.history-disclosure > summary::-webkit-details-marker { display:none; }
.evidence-disclosure > summary::after,.history-disclosure > summary::after { content:'＋'; position:absolute; right:1px; bottom:4px; color:#6482a0; font-size:18px; }
.evidence-disclosure[open] > summary::after,.history-disclosure[open] > summary::after { content:'−'; }
.evidence-disclosure > summary:focus-visible,.history-disclosure > summary:focus-visible { outline:3px solid #94b9dc; outline-offset:3px; border-radius:4px; }
.section-heading h2 { margin:3px 0 0; color:#1d3049; font:600 22px 'Noto Serif SC',serif; }
.source-badge { padding:4px 8px; border:1px solid #e1e8f0; border-radius:99px; color:#7a8ba0; font-size:11px; white-space:nowrap; }
.empty-report { display:flex; gap:18px; align-items:flex-start; margin-top:19px; padding:29px; border:1px dashed #cbd7e5; border-radius:11px; background:#fff; }
.empty-sigil { display:grid; width:48px; height:48px; flex:0 0 auto; place-items:center; border:1px solid #dbe6f2; border-radius:12px; color:#6c91c4; background:#f5f9ff; font-size:30px; }
.empty-report h2 { margin:4px 0 7px; color:#203651; font:600 21px 'Noto Serif SC',serif; }
.empty-report p { max-width:780px; margin:0; color:#697c93; font-size:14px; }
.empty-actions { display:flex; flex-wrap:wrap; gap:9px; margin-top:16px; }
.empty-actions .primary-action { min-width:180px; }
.disabled-hint { margin-top:9px !important; color:#9aa8b8 !important; font-size:12px !important; }
.category-judgements,.evidence-section { padding:23px 25px; margin-top:19px; }
.revision-history { padding:21px 24px; margin-top:19px; border:1px solid #e2e8f0; border-radius:11px; background:#fff; }
.history-disclosure > summary { margin-bottom:0; }
.history-disclosure[open] > summary { margin-bottom:17px; }
.evidence-disclosure > summary { margin-bottom:0; }
.evidence-disclosure[open] > summary { margin-bottom:17px; }
.history-list { display:flex; flex-direction:column; gap:0; border-left:1px solid #e1e8f0; margin-left:7px; }
.history-item { position:relative; display:flex; gap:14px; padding:1px 0 20px 18px; }
.history-item:last-child { padding-bottom:2px; }
.history-marker { position:absolute; top:5px; left:-5px; width:9px; height:9px; border:2px solid #fff; border-radius:50%; background:#aab5c3; box-shadow:0 0 0 1px #cad4e0; }
.history-current .history-marker { background:#3b82f6; box-shadow:0 0 0 1px #90b2e4; }
.history-copy { min-width:0; flex:1; }
.history-topline { display:flex; align-items:center; flex-wrap:wrap; gap:8px 13px; color:#93a0b1; font-size:11px; }
.history-topline strong { color:#405773; font-size:13px; }
.current-version { padding:2px 6px; border-radius:99px; color:#17654a; background:#e5f5ed; }
.history-copy p { display:-webkit-box; max-width:1050px; margin:5px 0; overflow:hidden; color:#61758f; font-size:13px; line-height:1.65; -webkit-box-orient:vertical; -webkit-line-clamp:3; }
.history-copy small { color:#9aa6b4; font-size:10px; }
.subjudgement-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.subjudgement-card { min-width:0; padding:14px; border:1px solid #e3eaf2; border-radius:8px; color:#3b506a; background:#fff; text-align:left; cursor:pointer; transition:.16s ease; }
.subjudgement-card:hover { border-color:#9bb9e1; background:#f9fbff; transform:translateY(-1px); }
.sub-card-heading { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.sub-card-heading strong { color:#263e5a; font-size:14px; }
.sub-card-heading b { color:#91a0b2; font:11px 'DM Mono',monospace; white-space:nowrap; }
.subjudgement-card p { display:-webkit-box; min-height:52px; margin:8px 0 11px; overflow:hidden; color:#667a93; font-size:14px; line-height:1.65; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.sub-card-foot { display:flex; align-items:center; gap:6px; color:#8b98a8; font-size:11px; }
.sub-card-foot b { margin-left:auto; color:#4b83d7; font-size:14px; }
.sub-card-foot i { width:7px; height:7px; border-radius:50%; background:#aab4c2; }
.dot-current { background:#32a276 !important; }.dot-stale { background:#e0a63a !important; }.dot-missing { background:#aab4c2 !important; }
.evidence-list { border-top:1px solid #edf1f5; }
.evidence-item { padding:12px 0 9px; border-bottom:1px solid #edf1f5; }
.evidence-open { display:grid; width:100%; grid-template-columns:92px minmax(0,1fr) 20px; align-items:start; gap:13px; padding:0; border:0; color:inherit; background:transparent; text-align:left; cursor:pointer; }
.evidence-date { padding-top:2px; color:#8d9bad; font:11px 'DM Mono','Noto Sans SC',sans-serif; }
.evidence-copy { display:flex; min-width:0; flex-direction:column; gap:3px; }
.evidence-copy strong { color:#334a65; font-size:14px; font-weight:600; }
.evidence-open:hover .evidence-copy strong { color:#2563eb; }
.evidence-copy small { display:-webkit-box; overflow:hidden; color:#74869b; font-size:14px; line-height:1.7; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.evidence-arrow { color:#6d95ce; }
.evidence-meta { display:flex; align-items:center; gap:13px; margin:7px 0 0 105px; color:#a0aaba; font-size:10px; }
.cited-tag,.new-tag { padding:2px 6px; border-radius:99px; color:#19754d; background:#e9f7ef; }.new-tag { color:#a46205; background:#fff4dc; }
.muted-copy { color:#93a0af; font-size:13px; }
.state-message { display:flex; min-height:240px; align-items:center; justify-content:center; gap:12px; color:#718198; }
.state-message button { padding:6px 10px; border:1px solid #cbd7e5; border-radius:6px; color:#345981; background:#fff; cursor:pointer; }
.error-message { color:#a63c3c; }
.loader { width:18px; height:18px; border:2px solid #dce7f4; border-top-color:#3b82f6; border-radius:50%; animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
@media(max-width:1000px) { .subjudgement-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media(max-width:760px) { .judgement-page { padding:0 16px 30px; }.report-hero { align-items:stretch; flex-direction:column; gap:20px; padding:23px 20px; }.hero-actions { display:grid; grid-template-columns:1fr 1fr; }.freshness { grid-column:1/-1; }.subjudgement-grid { grid-template-columns:1fr 1fr; }.category-judgements,.evidence-section { padding:18px; } }
@media(max-width:520px) { .judgement-page { padding:0 11px 24px; }.desk-mark { font-size:11px; }.breadcrumbs { padding-top:14px; }.hero-copy h1 { font-size:25px; }.hero-copy p { font-size:15px; }.hero-meta { gap:7px 12px; }.hero-actions { grid-template-columns:1fr; }.freshness { grid-column:auto; }.subjudgement-grid { grid-template-columns:1fr; }.section-heading { align-items:flex-start; flex-direction:column; gap:7px; }.source-badge { white-space:normal; }.empty-report { padding:20px; }.evidence-open { grid-template-columns:1fr 18px; gap:4px 8px; }.evidence-date { grid-column:1/-1; }.evidence-meta { margin-left:0; flex-wrap:wrap; } }
</style>
