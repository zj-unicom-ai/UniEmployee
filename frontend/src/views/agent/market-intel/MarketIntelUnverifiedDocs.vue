<template>
  <main class="raw-docs-page">
    <header class="page-head">
      <button class="back" type="button" @click="router.push({ name: 'market-intel-sources' })">← 数据源配置</button>
      <div class="head-row">
        <div>
          <span class="eyebrow">SOURCE EVIDENCE</span>
          <h1>待核验资料</h1>
          <p>这里展示已抓取的原始资料和核验状态；“已初筛”表示已整理内容范围与候选领域，仍未核验的资料不会计入有效研究依据。</p>
        </div>
        <div class="head-actions">
          <button class="secondary" type="button" :disabled="loading || triaging" @click="loadDocuments">刷新列表</button>
          <button class="primary" type="button" :disabled="loading || triaging || !(summary.unverified > 0)" @click="runLocalTriage">
            {{ triaging ? '本地初筛中…' : '本地初筛未核验资料' }}
          </button>
        </div>
      </div>
      <div class="summary-grid">
        <div><b>{{ summary.raw_documents || 0 }}</b><span>原始资料</span></div>
        <div><b>{{ summary.unverified || 0 }}</b><span>未核验</span></div>
        <div><b>{{ summary.needs_review || 0 }}</b><span>待复核</span></div>
        <div><b>{{ summary.triaged || 0 }}</b><span>已初筛</span></div>
        <div><b>{{ summary.source_attributed || 0 }}</b><span>已关联观察</span></div>
      </div>
    </header>

    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <div v-if="success" class="notice success" role="status">{{ success }}</div>

    <section class="panel">
      <form class="filters" @submit.prevent="applyFilters">
        <label>核验状态
          <select v-model="status" @change="applyFilters">
            <option value="unverified">未核验</option>
            <option value="needs_review">待复核</option>
            <option value="triaged">已初筛</option>
            <option value="source_attributed">已关联观察</option>
            <option value="all">全部资料</option>
          </select>
        </label>
        <label>数据源
          <select v-model="sourceId" @change="applyFilters">
            <option value="">全部数据源</option>
            <option v-for="source in sources" :key="source.id" :value="source.id">{{ source.name }}</option>
          </select>
        </label>
        <label class="search-field">搜索标题或正文
          <input v-model.trim="search" type="search" maxlength="100" placeholder="输入关键词后回车">
        </label>
        <button class="primary" type="submit">搜索</button>
      </form>

      <div class="list-heading">
        <div><h2>{{ statusLabel }}资料</h2><span>共 {{ total }} 篇去重后的文档</span></div>
        <span v-if="topicId" class="topic-chip">{{ topicName(topicId) }}</span>
      </div>

      <div v-if="loading" class="empty">正在读取原始资料…</div>
      <div v-else-if="!items.length" class="empty">当前条件下没有资料。可切换状态或清除筛选后查看。</div>
      <div v-else class="document-list">
        <article v-for="item in items" :key="item.document_id" class="document-card">
          <div class="document-topline">
            <div class="badges">
              <span class="quality-badge" :class="`quality-${item.quality_status}`">{{ qualityLabel(item.quality_status) }}</span>
              <span class="content-badge">{{ contentLabel(item.content_source) }}</span>
              <span v-if="item.source_count > 1" class="duplicate-badge">{{ item.source_count }} 个来源</span>
            </div>
            <time>{{ formatDate(item.published_at || item.publication_month || item.fetched_at) }}</time>
          </div>
          <h3><a :href="item.canonical_url" target="_blank" rel="noopener noreferrer">{{ item.title || item.document_title || '（无标题）' }}</a></h3>
          <div class="source-list">
            <span v-for="source in item.sources" :key="`${source.source_id}:${source.url}`" class="source-chip">
              {{ source.source_name }} · {{ discoveryLabel(source.discovery_status) }}
            </span>
          </div>
          <p v-if="item.quality_reason" class="quality-reason">核验说明：{{ item.quality_reason }}</p>
          <div v-if="item.triage?.triage_method === 'local_rules'" class="triage-box">
            <div class="triage-heading"><strong>本地预审</strong><span>{{ item.triage.evidence_scope_label }} · {{ item.triage.body_chars }} 字</span></div>
            <div class="triage-topics">
              <span v-for="topic in item.triage.candidate_topics || []" :key="topic" class="topic-chip">{{ topicName(topic) }}</span>
              <span v-for="category in item.triage.suggested_categories || []" :key="`${category.topic_id}:${category.category_id}`" class="category-chip">{{ category.name }}</span>
            </div>
            <p>{{ item.triage.relevance_hint }}；匹配词：{{ (item.triage.matched_keywords || []).join('、') || '无' }}</p>
            <p><b>下一步：</b>{{ item.triage.next_action }}</p>
            <small v-if="item.quality_status === 'source_attributed'">这条资料现已关联研究观察；关键词提示仅供分类参考。</small>
            <small v-else>本地关键词初筛，仍需核查来源原文；未调用平台大模型，不计入有效研究依据。</small>
          </div>
          <p v-if="item.excerpt" class="excerpt">{{ item.excerpt }}</p>
          <div class="document-foot"><span>抓取 {{ formatDate(item.fetched_at) }}</span><span>最近发现 {{ formatDate(item.last_seen_at) }}</span><span v-if="item.observation_id">观察记录 {{ item.observation_id }}</span></div>
        </article>
      </div>

      <footer v-if="total > pageSize" class="pagination">
        <button class="secondary" type="button" :disabled="loading || page === 0" @click="changePage(-1)">上一页</button>
        <span>第 {{ page + 1 }} / {{ pageCount }} 页</span>
        <button class="secondary" type="button" :disabled="loading || page + 1 >= pageCount" @click="changePage(1)">下一页</button>
      </footer>
    </section>
  </main>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'

const route = useRoute()
const router = useRouter()
const items = ref([])
const sources = ref([])
const summary = ref({})
const total = ref(0)
const loading = ref(false)
const triaging = ref(false)
const error = ref('')
const success = ref('')
const status = ref('triaged')
const sourceId = ref('')
const search = ref('')
const page = ref(0)
const pageSize = 30
const topicId = computed(() => typeof route.query.topic === 'string' ? route.query.topic : '')
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))
const statusLabel = computed(() => ({ unverified: '未核验', needs_review: '待复核', triaged: '已初筛', source_attributed: '已关联观察', all: '全部' })[status.value] || '原始')

function topicName(id) { return ({ 'ai-frontier': 'AI 前沿观察', 'embodied-intelligence': '具身智能', 'policy-analysis': '政策分析' })[id] || id }
function qualityLabel(value) { return ({ unverified: '未核验', needs_review: '待复核', triaged: '已初筛', source_attributed: '已关联观察' })[value] || value || '未核验' }
function contentLabel(value) { return ({ article_fetch: '原文已抓取', fulltext: 'Feed 含正文', summary: '仅有摘要', rss: 'Feed 元数据' })[value] || value || '未知内容类型' }
function discoveryLabel(value) { return ({ discovered: '已发现', fetched: '正文可读', fetch_failed: '正文抓取失败', queued: '处理中', observation_saved: '观察已保存' })[value] || value || '状态未知' }
function formatDate(value) {
  if (!value) return '时间未知'
  const date = new Date(value.length === 7 ? `${value}-01T00:00:00` : value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

async function loadSources() {
  try {
    const { data } = await api.get('/market-research/sources')
    sources.value = data.items || []
  } catch (err) {
    error.value = err.response?.data?.detail || '数据源列表暂时无法加载。'
  }
}

async function loadDocuments() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/market-research/source-documents', { params: {
      status: status.value, source_id: sourceId.value, topic_id: topicId.value,
      q: search.value, limit: pageSize, offset: page.value * pageSize,
    } })
    items.value = data.items || []
    total.value = Number(data.total || 0)
    summary.value = data.summary || {}
  } catch (err) {
    error.value = err.response?.data?.detail || '原始资料暂时无法加载。'
  } finally {
    loading.value = false
  }
}

async function runLocalTriage() {
  triaging.value = true
  error.value = ''
  success.value = ''
  try {
    const { data } = await api.post('/market-research/source-documents/local-triage')
    success.value = `已初筛 ${Number(data.processed || 0)} 篇；只整理正文范围与候选领域，未调用平台大模型，也未计入有效研究依据。`
    status.value = 'triaged'
    page.value = 0
    await loadDocuments()
  } catch (err) {
    error.value = err.response?.data?.detail || '本地初筛失败，请稍后重试。'
  } finally {
    triaging.value = false
  }
}

function applyFilters() { page.value = 0; loadDocuments() }
function changePage(direction) { page.value = Math.max(0, page.value + direction); loadDocuments() }

onMounted(async () => {
  await Promise.all([loadSources(), loadDocuments()])
})
</script>

<style scoped>
.raw-docs-page { max-width:1180px; margin:0 auto; padding:34px 28px 64px; color:#263b50; font-family:'Noto Sans SC',sans-serif; }
.page-head,.panel { padding:24px 28px; border:1px solid #e0e6eb; border-radius:14px; background:#fff; box-shadow:0 5px 20px #30465a08; }
.page-head { background:linear-gradient(120deg,#f7fafb,#fff 62%,#f8f3eb); }
.back { padding:0; border:0; color:#718398; background:none; cursor:pointer; font:inherit; font-size:13px; }
.head-row,.list-heading { display:flex; align-items:center; justify-content:space-between; gap:18px; }
.head-row { margin-top:20px; }
.head-actions { display:flex; flex-wrap:wrap; gap:8px; }
.eyebrow { color:#a47742; font:600 10px 'DM Mono',monospace; letter-spacing:.18em; }
h1 { margin:7px 0; color:#273d53; font-size:28px; }
.head-row p { margin:0; color:#7c8b99; font-size:13px; }
.summary-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-top:22px; }
.summary-grid div { display:flex; align-items:baseline; gap:9px; padding:12px 14px; border-radius:8px; background:#f4f7f7; }
.summary-grid b { color:#3b5369; font:600 20px 'DM Mono',monospace; }
.summary-grid span { color:#84929f; font-size:12px; }
.panel { margin-top:18px; }
.filters { display:grid; grid-template-columns:150px 220px minmax(200px,1fr) auto; align-items:end; gap:12px; }
.filters label { display:flex; flex-direction:column; gap:6px; color:#738395; font-size:12px; }
.filters select,.filters input { min-width:0; height:38px; padding:0 10px; border:1px solid #d8e1e7; border-radius:7px; color:#40586d; background:#fff; font:13px 'Noto Sans SC',sans-serif; }
.primary,.secondary { min-height:36px; padding:8px 13px; border:1px solid #bd9b72; border-radius:7px; color:#805d36; background:#fffaf3; cursor:pointer; font:600 12px 'Noto Sans SC',sans-serif; }
.secondary { border-color:#d8e0e6; color:#52677a; background:#fff; }
button:disabled { opacity:.55; cursor:default; }
.list-heading { margin:25px 0 12px; padding-top:18px; border-top:1px solid #edf0f2; }
.list-heading h2 { display:inline; margin:0 10px 0 0; color:#344c62; font-size:16px; }
.list-heading span { color:#8795a1; font-size:12px; }
.topic-chip,.source-chip { display:inline-flex; padding:4px 8px; border-radius:5px; color:#667d8e; background:#f0f4f5; font-size:11px; }
.document-list { border-top:1px solid #edf0f2; }
.document-card { padding:17px 2px 15px; border-bottom:1px solid #edf0f2; }
.document-topline,.badges,.source-list,.document-foot { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.document-topline { justify-content:space-between; }
.document-topline time,.document-foot { color:#8996a2; font-size:11px; }
.quality-badge,.content-badge,.duplicate-badge { display:inline-flex; padding:4px 8px; border-radius:5px; color:#8b714d; background:#f8f2e9; font-size:11px; }
.quality-source_attributed { color:#4d7a60; background:#edf5ef; }
.quality-needs_review { color:#9a6d30; background:#fbf3e3; }
.quality-triaged { color:#536f87; background:#edf3f8; }
.content-badge { color:#62798b; background:#eef3f5; }
.duplicate-badge { color:#6b6989; background:#f1f0f8; }
.document-card h3 { margin:10px 0 8px; font-size:16px; line-height:1.55; }
.document-card h3 a { color:#344c62; text-decoration:none; }
.document-card h3 a:hover { color:#9a7041; text-decoration:underline; }
.source-list { margin:0 0 7px; }
.quality-reason { margin:7px 0; color:#a26151; font-size:12px; line-height:1.6; }
.triage-box { margin:9px 0 11px; padding:11px 13px; border:1px solid #e4eaf0; border-radius:8px; background:#f8fafb; }
.triage-heading,.triage-topics { display:flex; align-items:center; flex-wrap:wrap; gap:7px; }
.triage-heading { justify-content:space-between; color:#516b7f; font-size:12px; }
.triage-heading span,.triage-box small { color:#8694a0; font-size:11px; }
.triage-topics { margin-top:8px; }
.category-chip { display:inline-flex; padding:4px 8px; border-radius:5px; color:#8a663d; background:#f8f1e7; font-size:11px; }
.triage-box p { margin:7px 0 0; color:#62778a; font-size:12px; line-height:1.6; }
.triage-box small { display:block; margin-top:7px; }
.excerpt { display:-webkit-box; overflow:hidden; margin:8px 0 11px; color:#64778a; font-size:13px; line-height:1.7; -webkit-box-orient:vertical; -webkit-line-clamp:3; }
.document-foot { gap:15px; }
.empty { padding:32px 0; color:#8795a2; font-size:13px; text-align:center; }
.pagination { display:flex; align-items:center; justify-content:center; gap:16px; margin-top:18px; }
.pagination span { color:#778898; font-size:12px; }
.notice.error { margin-top:15px; padding:12px; border-radius:6px; color:#995a54; background:#fbefed; font-size:13px; }
.notice.success { margin-top:15px; padding:12px; border-radius:6px; color:#4d7a60; background:#edf5ef; font-size:13px; }
@media(max-width:760px) {
  .raw-docs-page { padding:18px 13px 42px; }
  .page-head,.panel { padding:18px 16px; }
  .head-row { align-items:flex-start; flex-direction:column; }
  .summary-grid { grid-template-columns:repeat(2,1fr); }
  .filters { grid-template-columns:1fr 1fr; }
  .filters .search-field { grid-column:1/-1; }
}
</style>
