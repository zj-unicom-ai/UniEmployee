<template>
  <main class="sources-page">
    <header class="page-head">
      <button class="back" type="button" @click="router.push({ name: 'market-intel' })">← 小察工作台</button>
      <div class="title-row">
        <div><span class="eyebrow">SOURCE OPERATIONS</span><h1>数据源配置</h1><p>管理 RSS 信源、主题路由和单源采集状态。新导入的信源默认停用。</p></div>
        <div class="head-actions" v-if="auth.isAdmin">
          <select v-model="collectionMode" class="batch-mode-select" aria-label="批次处理模式"><option value="fetch_only">只抓取原文（不调用模型）</option><option value="incremental">抓取并分析（调用模型）</option></select>
          <button class="secondary" :disabled="busy" @click="startBatch()">{{ topicFilter ? '获取当前主题来源' : '一键获取已启用来源' }}</button>
          <button class="secondary" @click="router.push({ name: 'market-intel-collection' })">采集进度</button>
          <button class="secondary" @click="router.push({ name: 'market-intel-unverified', query: topicFilter ? { topic: topicFilter } : {} })">待核验资料</button>
          <button class="secondary" :disabled="busy" @click="openCreate = !openCreate">{{ openCreate ? '取消新增' : '＋ 新增来源' }}</button>
          <button class="primary" :disabled="busy" @click="previewImport">导入首批信源</button>
        </div>
      </div>
      <div class="summary-grid">
        <div><b>{{ summary.source_count || 0 }}</b><span>已配置</span></div>
        <div><b>{{ summary.enabled_source_count || 0 }}</b><span>已启用</span></div>
        <div><b>{{ summary.intake_pending || 0 }}</b><span>待处理文章</span></div>
        <div><b>{{ qualityPending }}</b><span>待核验 / 待复核</span></div>
      </div>
      <p v-if="auth.isAdmin && !topicFilter" class="form-note batch-note">若启用来源关联多个主题，请先在信源列表选择一个主题，再启动本轮采集。</p>
    </header>

    <div v-if="notice" class="notice" :class="noticeType" role="status">{{ notice }}</div>
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>

    <section v-if="openCreate && auth.isAdmin" class="panel create-panel">
      <h2>新增 RSS 来源</h2>
      <div class="form-grid">
        <label>来源名称<input v-model.trim="draft.name" maxlength="200" placeholder="例如：OpenAI News"></label>
        <label>Feed URL<input v-model.trim="draft.feed_url" type="url" placeholder="https://example.com/feed.xml"></label>
        <label>候选主题<select v-model="draft.topic_id"><option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option></select></label>
        <label>采集间隔（分钟）<input v-model.number="draft.interval_minutes" type="number" min="5" max="10080"></label>
      </div>
      <p class="form-note">仅 RSS/Atom 可用。保存后为草稿，需先试抓，通过后再启用。</p>
      <button class="primary" :disabled="busy || !draft.name || !draft.feed_url" @click="createSource">保存来源</button>
    </section>

    <section class="panel source-panel">
      <div class="section-head"><div><h2>信源列表</h2><span>{{ filteredSources.length }} 项</span></div>
        <div class="filters"><select v-model="topicFilter"><option value="">全部主题</option><option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option></select><select v-model="statusFilter"><option value="all">全部状态</option><option value="enabled">已启用</option><option value="disabled">已停用</option></select></div>
      </div>
      <div v-if="loading" class="empty">正在读取信源…</div>
      <div v-else-if="!filteredSources.length" class="empty">还没有匹配的来源。可以新增来源或导入首批信源清单。</div>
      <div v-else class="source-list">
        <article v-for="source in filteredSources" :key="source.id" class="source-row">
          <div class="source-main">
            <div class="source-title"><span class="health-dot" :class="source.health"></span><strong>{{ source.name }}</strong><span class="tier">{{ source.tier }}</span><span class="status" :class="{ enabled: source.enabled }">{{ source.enabled ? '已启用' : '草稿 / 停用' }}</span></div>
            <a :href="source.config.feed_url" target="_blank" rel="noopener noreferrer">{{ source.config.feed_url }}</a>
            <div class="meta"><span>{{ topicNames(source.candidate_topic_ids) }}</span><span>{{ source.interval_minutes }} 分钟</span><span>{{ source.first_party ? '一手来源' : '非一手' }}</span><span>版本 {{ source.config_version }}</span></div>
          </div>
          <div class="source-actions" v-if="auth.isAdmin">
            <button class="small" :disabled="busy" @click="beginEdit(source)">编辑</button>
            <button class="small" :disabled="busy" @click="preview(source)">试抓</button>
            <button class="small" :disabled="busy || !source.enabled" @click="collect(source)">立即采集</button>
            <button class="small" :disabled="busy" @click="toggle(source)">{{ source.enabled ? '停用' : '启用' }}</button>
          </div>
          <div v-if="source.last_run" class="run-line">最近运行：{{ source.last_run }}</div>
          <form v-if="editingId === source.id" class="edit-form" @submit.prevent="saveEdit(source)">
            <label>来源名称<input v-model.trim="editDraft.name" maxlength="200"></label>
            <label>Feed URL<input v-model.trim="editDraft.feed_url" type="url"></label>
            <label>候选主题<select v-model="editDraft.topics" multiple><option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option></select></label>
            <label>采集间隔<input v-model.number="editDraft.interval_minutes" type="number" min="5" max="10080"></label>
            <div class="edit-actions"><button class="small" type="button" @click="editingId = ''">取消</button><button class="primary" type="submit" :disabled="busy">保存配置</button></div>
          </form>
        </article>
      </div>
    </section>

    <section v-if="previewResult" class="panel result-panel">
      <div class="section-head"><div><h2>试抓结果</h2><span>{{ previewResult.diagnostic }}</span></div><button class="small" @click="previewResult = null">关闭</button></div>
      <div v-if="previewResult.items?.length" class="candidate-list"><article v-for="(item, index) in previewResult.items" :key="item.url"><span class="candidate-no">{{ String(index + 1).padStart(2, '0') }}</span><div><strong>{{ item.title }}</strong><a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.url }}</a><small>{{ item.published_at || '发布时间未提供' }} · {{ item.has_fulltext ? 'Feed 含正文' : '仅摘要，需读取原文' }}</small><p v-if="item.summary">{{ item.summary }}</p></div></article></div>
      <div v-else class="empty">Feed 暂无候选内容。</div>
    </section>

    <section v-if="runs.length" class="panel run-panel">
      <div class="section-head"><div><h2>最近采集运行</h2><span>抓取完成与研究处理状态分开显示</span></div><button class="small" @click="loadSources">刷新</button></div>
      <div class="run-list"><article v-for="run in runs" :key="run.id"><div><strong>{{ sourceName(run.source_id) }}</strong><small>{{ run.topic_id ? topicNames([run.topic_id]) : '试抓' }} · {{ formatTime(run.created_at) }}</small></div><span class="run-status" :class="run.status">{{ statusText(run.status) }}</span><span class="run-counts">发现 {{ run.counts?.found || 0 }} · 新增 {{ run.counts?.new || 0 }} · 重复 {{ run.counts?.duplicate || 0 }} · 失败 {{ run.counts?.failed || 0 }}</span><span v-if="run.error" class="run-error">{{ run.error }}</span></article></div>
    </section>

    <div v-if="importPreview" class="modal-backdrop" @click.self="importPreview = null">
      <section class="import-dialog" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <button class="close" aria-label="关闭" @click="importPreview = null">×</button>
        <span class="eyebrow">DRY RUN</span><h2 id="import-title">导入首批信源</h2>
        <p>预览清单中的 {{ importPreview.items.length }} 个 RSS 信源。首次导入全部为草稿，不会抓取文章或调用模型。</p>
        <div class="import-summary"><span>新增 <b>{{ importPreview.summary.new }}</b></span><span>复用 <b>{{ importPreview.summary.reused }}</b></span><span>冲突 <b>{{ importPreview.summary.conflict }}</b></span><span>不支持 <b>{{ importPreview.summary.unsupported }}</b></span><span>原计划启用 <b>{{ importPreview.summary.desired_enabled }}</b></span><span>原计划停用 <b>{{ importPreview.summary.desired_disabled }}</b></span></div>
        <div class="import-list"><div v-for="item in importPreview.items" :key="item.legacy_source_id"><strong>{{ item.name }}</strong><span>{{ item.actionLabel || actionName(item.action) }}</span><small>{{ item.reason }}</small></div></div>
        <div class="dialog-actions"><button class="secondary" @click="importPreview = null">返回</button><button class="primary" :disabled="busy || importPreview.summary.new === 0" @click="runImport">导入 {{ importPreview.summary.new }} 个草稿</button></div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'
import { useAuthStore } from '../../../stores/auth.js'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const sources = ref([])
const topics = ref([])
const summary = ref({})
const runs = ref([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const noticeType = ref('success')
const openCreate = ref(false)
const importPreview = ref(null)
const previewResult = ref(null)
const topicFilter = ref('')
const statusFilter = ref('all')
const collectionMode = ref('fetch_only')
const draft = ref({ name: '', feed_url: '', topic_id: 'ai-frontier', interval_minutes: 120 })
const editingId = ref('')
const editDraft = ref({ name: '', feed_url: '', topics: [], interval_minutes: 120 })
let pollTimer = null

topicFilter.value = typeof route.query.topic === 'string' ? route.query.topic : ''

const filteredSources = computed(() => sources.value.filter(source =>
  (!topicFilter.value || source.candidate_topic_ids.includes(topicFilter.value)) &&
  (statusFilter.value === 'all' || source.enabled === (statusFilter.value === 'enabled'))))
const activeRuns = computed(() => runs.value.filter(run => ['queued', 'running'].includes(run.status)).length)
const qualityPending = computed(() => Number(summary.value.quality?.unverified || 0) + Number(summary.value.quality?.needs_review || 0))

function topicNames(ids = []) { return ids.map(id => topics.value.find(topic => topic.id === id)?.name || id).join('、') }
function sourceName(id) { return sources.value.find(source => source.id === id)?.name || '已删除来源' }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '时间未知' }
function statusText(status) { return ({ queued: '排队中', running: '运行中', succeeded: '抓取完成', completed_with_issues: '部分失败', failed: '失败' })[status] || status }
function actionName(action) { return ({ new: '新增草稿', reused: '已存在', conflict: '配置冲突', unsupported: '暂不支持' })[action] || action }
function setNotice(message, type = 'success') { notice.value = message; noticeType.value = type; setTimeout(() => { if (notice.value === message) notice.value = '' }, 4500) }

async function loadSources() {
  try {
    const [{ data: sourceData }, { data: workbench }, { data: runData }] = await Promise.all([
      api.get('/market-research/sources'), api.get('/market-research/workbench', { params: { limit: 1 } }),
      api.get('/market-research/sources/runs', { params: { limit: 100 } }),
    ])
    sources.value = sourceData.items || []
    summary.value = sourceData.summary || {}
    topics.value = workbench.topics || []
    runs.value = runData.items || []
    if (activeRuns.value) startPolling(); else stopPolling()
  } catch (err) {
    error.value = err.response?.data?.detail || '信源配置暂时无法加载。'
  } finally { loading.value = false }
}

function startPolling() { if (!pollTimer) pollTimer = setInterval(loadSources, 3000) }
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null }

async function previewImport() {
  busy.value = true; error.value = ''
  try { const { data } = await api.post('/market-research/sources/import/preview'); importPreview.value = data }
  catch (err) { error.value = err.response?.data?.detail || '信源清单预览失败。' }
  finally { busy.value = false }
}
async function runImport() {
  if (!importPreview.value) return
  busy.value = true
  try {
    const { data } = await api.post('/market-research/sources/import', { manifest_hash: importPreview.value.manifest_hash })
    importPreview.value = null
    setNotice(`已导入 ${data.created} 个停用草稿；复用 ${data.reused}，冲突 ${data.conflict}，不支持 ${data.unsupported}。`)
    await loadSources()
  } catch (err) { error.value = err.response?.data?.detail || '导入信源失败。' }
  finally { busy.value = false }
}
async function createSource() {
  busy.value = true
  try {
    await api.post('/market-research/sources', { name: draft.value.name, kind: 'rss', config: { feed_url: draft.value.feed_url, sort_by_published_at: true, initial_backfill_limit: 5, initial_backfill_months: 6 }, candidate_topic_ids: [draft.value.topic_id], tier: 'T3', first_party: false, desired_enabled: false, interval_minutes: draft.value.interval_minutes })
    draft.value = { name: '', feed_url: '', topic_id: 'ai-frontier', interval_minutes: 120 }
    openCreate.value = false; setNotice('来源已保存为草稿，请先试抓并确认配置。'); await loadSources()
  } catch (err) { error.value = err.response?.data?.detail || '新增来源失败。' }
  finally { busy.value = false }
}
async function toggle(source) {
  busy.value = true
  try { await api.patch(`/market-research/sources/${source.id}/enabled`, { enabled: !source.enabled, config_version: source.config_version }); setNotice(source.enabled ? '来源已停用。' : '来源已启用。'); await loadSources() }
  catch (err) { error.value = err.response?.data?.detail || '更新来源状态失败。' }
  finally { busy.value = false }
}
function beginEdit(source) {
  editingId.value = source.id
  editDraft.value = { name: source.name, feed_url: source.config.feed_url, topics: [...source.candidate_topic_ids], interval_minutes: source.interval_minutes }
}
async function saveEdit(source) {
  busy.value = true
  try {
    await api.patch(`/market-research/sources/${source.id}`, {
      config_version: source.config_version,
      name: editDraft.value.name,
      kind: source.kind,
      config: { ...source.config, feed_url: editDraft.value.feed_url },
      candidate_topic_ids: editDraft.value.topics,
      tags: source.tags,
      tier: source.tier,
      first_party: source.first_party,
      participation_mode: source.participation_mode,
      desired_enabled: source.desired_enabled,
      interval_minutes: editDraft.value.interval_minutes,
    })
    editingId.value = ''; setNotice('信源配置已更新，后续运行会使用新版本。'); await loadSources()
  } catch (err) { error.value = err.response?.data?.detail || '保存信源配置失败。' }
  finally { busy.value = false }
}
async function preview(source) {
  busy.value = true; previewResult.value = null
  try { const { data } = await api.post(`/market-research/sources/${source.id}/preview`, null, { params: { limit: 5 } }); previewResult.value = data }
  catch (err) { error.value = err.response?.data?.detail || 'RSS 试抓失败。' }
  finally { busy.value = false; await loadSources() }
}
async function collect(source) {
  busy.value = true
  try {
    const topicId = source.candidate_topic_ids.length === 1 ? source.candidate_topic_ids[0] : window.prompt(`请选择主题：${topicNames(source.candidate_topic_ids)}\n输入主题 ID：`, source.candidate_topic_ids[0])
    if (!topicId) return
    await api.post(`/market-research/sources/${source.id}/collect`, { topic_id: topicId })
    setNotice(`已排入「${source.name}」采集队列，后台会继续处理。`); await loadSources()
  } catch (err) { error.value = err.response?.data?.detail || '启动采集失败。' }
  finally { busy.value = false }
}

async function startBatch(sourceIds = []) {
  busy.value = true
  try {
    const requestId = globalThis.crypto?.randomUUID?.() || `mcb-${Date.now()}-${Math.random().toString(16).slice(2)}`
    const { data } = await api.post('/market-research/collection-batches', {
      request_id: requestId,
      topic_id: topicFilter.value,
      source_ids: sourceIds,
      mode: collectionMode.value,
      max_items: 500,
    })
    await router.push({ name: 'market-intel-collection-detail', params: { batchId: data.id } })
  } catch (err) { error.value = err.response?.data?.detail || '启动采集批次失败。' }
  finally { busy.value = false }
}

onMounted(loadSources)
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.sources-page { max-width:1180px; margin:0 auto; padding:34px 28px 64px; color:#213348; font-family:'Noto Sans SC',sans-serif; }
.page-head { padding:26px 30px 22px; border:1px solid #e0e6eb; border-radius:16px; background:linear-gradient(120deg,#f7fafb,#fff 58%,#f9f4eb); box-shadow:0 8px 28px #30465a0a; }
.back { padding:0; border:0; background:none; color:#718398; cursor:pointer; font:500 13px inherit; }
.title-row,.section-head { display:flex; align-items:center; justify-content:space-between; gap:20px; }
.title-row { margin-top:23px; }
.eyebrow { color:#a47742; font:600 10px 'DM Mono',monospace; letter-spacing:.18em; }
h1 { margin:8px 0 7px; color:#24394e; font-size:29px; font-weight:620; letter-spacing:-.04em; }
.title-row p { margin:0; color:#738395; font-size:14px; }
.head-actions,.dialog-actions,.filters { display:flex; align-items:center; gap:9px; }
.batch-mode-select { min-width:120px; padding:9px 10px; border:1px solid #d8e1e7; border-radius:7px; color:#52677c; background:#fff; font:12px 'Noto Sans SC',sans-serif; }
button { cursor:pointer; font:600 13px 'Noto Sans SC',sans-serif; }
button:disabled { opacity:.5; cursor:wait; }
.primary,.secondary,.small { padding:9px 13px; border-radius:7px; }
.primary { border:1px solid #8f6335; color:#fff; background:#956c40; }
.secondary,.small { border:1px solid #d7e0e6; color:#52677c; background:#fff; }
.small { padding:7px 10px; font-size:12px; white-space:nowrap; }
.summary-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:11px; margin-top:24px; }
.summary-grid > div { display:flex; align-items:baseline; gap:9px; padding:13px 15px; border:1px solid #e7ecef; border-radius:9px; background:#ffffffb8; }
.summary-grid b { color:#30475e; font:600 21px 'DM Mono',monospace; }.summary-grid span { color:#7e8c98; font-size:12px; }
.panel { margin-top:20px; padding:22px 24px; border:1px solid #e0e6eb; border-radius:13px; background:#fff; box-shadow:0 5px 20px #30465a08; }
.section-head { margin-bottom:15px; }.section-head > div { display:flex; align-items:baseline; gap:12px; }.section-head h2,.panel h2 { margin:0; color:#2d4257; font-size:17px; font-weight:620; }.section-head span,.form-note { color:#8995a1; font-size:12px; }
.filters select,.form-grid select,.form-grid input { padding:8px 10px; border:1px solid #d8e1e7; border-radius:6px; color:#33495d; background:white; font:13px inherit; }
.source-list { border-top:1px solid #edf0f2; }.source-row { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px 18px; padding:17px 2px; border-bottom:1px solid #edf0f2; }.source-main { min-width:0; }.source-title { display:flex; align-items:center; gap:9px; }.source-title strong { color:#334a5e; font-size:14px; }.source-main > a { display:block; overflow:hidden; margin-top:7px; color:#798c9b; font:12px 'DM Mono',monospace; text-overflow:ellipsis; white-space:nowrap; }.tier,.status { padding:3px 7px; border-radius:4px; color:#8d6a3e; background:#f7f2e9; font-size:10px; }.status { color:#8995a1; background:#f2f4f6; }.status.enabled { color:#4e7d65; background:#edf5ef; }.health-dot { width:7px; height:7px; border-radius:50%; background:#aeb8c1; }.health-dot.healthy { background:#52a17b; }.health-dot.degraded { background:#cf9551; }.health-dot.blocked { background:#c16a64; }.meta { display:flex; flex-wrap:wrap; gap:13px; margin-top:9px; color:#8794a0; font-size:11px; }.source-actions { display:flex; align-items:center; gap:7px; }.run-line { grid-column:1 / -1; color:#8b98a4; font-size:11px; }
.empty { padding:27px 10px; color:#8996a2; text-align:center; font-size:13px; }.notice { margin-top:15px; padding:11px 14px; border-radius:7px; color:#477657; background:#eef6ef; font-size:13px; }.notice.error { color:#955951; background:#fbefed; }
.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:13px; margin:17px 0 10px; }.form-grid label { display:flex; flex-direction:column; gap:6px; color:#607284; font-size:12px; }.form-note { margin:7px 0 13px; }
.edit-form { grid-column:1/-1; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; padding:14px; border:1px solid #e8ecef; border-radius:8px; background:#fafcfc; }.edit-form label { display:flex; flex-direction:column; gap:5px; color:#718292; font-size:11px; }.edit-form input,.edit-form select { min-width:0; padding:8px; border:1px solid #d9e1e7; border-radius:5px; color:#34495d; background:white; font:12px 'Noto Sans SC',sans-serif; }.edit-form select[multiple] { min-height:70px; }.edit-actions { grid-column:1/-1; display:flex; justify-content:flex-end; gap:8px; }
.result-panel,.run-panel { margin-bottom:20px; }.candidate-list,.run-list { border-top:1px solid #edf0f2; }.candidate-list article { display:grid; grid-template-columns:36px minmax(0,1fr); gap:12px; padding:13px 2px; border-bottom:1px solid #edf0f2; }.candidate-no { color:#ae987b; font:12px 'DM Mono',monospace; }.candidate-list strong,.candidate-list a,.candidate-list small { display:block; }.candidate-list strong { color:#344b60; font-size:13px; }.candidate-list a { overflow:hidden; margin-top:5px; color:#8091a0; font:11px 'DM Mono',monospace; text-overflow:ellipsis; white-space:nowrap; }.candidate-list small,.candidate-list p { display:block; margin:5px 0 0; color:#82909c; font-size:11px; }.candidate-list p { color:#627487; line-height:1.55; }
.run-list article { display:grid; grid-template-columns:minmax(160px,1fr) 90px minmax(260px,auto); align-items:center; gap:12px; padding:12px 2px; border-bottom:1px solid #edf0f2; }.run-list article > div strong,.run-list article small { display:block; }.run-list article strong { color:#3a5064; font-size:12px; }.run-list article small,.run-counts { color:#8794a0; font-size:11px; }.run-status { color:#788998; font-size:12px; }.run-status.running,.run-status.queued { color:#af7b3b; }.run-status.succeeded { color:#538264; }.run-status.failed,.run-status.completed_with_issues { color:#b55d55; }.run-error { grid-column:1/-1; color:#b65b53; font-size:11px; }
.modal-backdrop { position:fixed; z-index:1000; inset:0; display:grid; place-items:center; padding:20px; background:#17243266; }.import-dialog { position:relative; display:flex; flex-direction:column; width:min(700px,100%); max-height:min(82vh,760px); padding:26px; border-radius:14px; background:white; box-shadow:0 22px 70px #14253630; }.close { position:absolute; top:17px; right:18px; border:0; background:none; color:#8996a1; font-size:22px; }.import-dialog h2 { margin:8px 0 6px; color:#2a4157; font-size:21px; }.import-dialog > p { color:#788998; font-size:13px; }.import-summary { display:grid; grid-template-columns:repeat(3,1fr); gap:7px; margin:12px 0; }.import-summary span { padding:9px; border-radius:6px; color:#778696; background:#f5f7f8; font-size:11px; }.import-summary b { margin-left:4px; color:#334a5f; }.import-list { overflow:auto; max-height:310px; border-top:1px solid #e9edf0; }.import-list > div { display:grid; grid-template-columns:minmax(0,1fr) 80px; gap:3px 12px; padding:9px 2px; border-bottom:1px solid #edf0f2; }.import-list strong { overflow:hidden; color:#40566a; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }.import-list span { color:#8f714e; font-size:11px; }.import-list small { grid-column:1/-1; color:#8996a0; font-size:10px; }.dialog-actions { justify-content:flex-end; padding-top:16px; }
@media(max-width:760px) { .sources-page { padding:18px 13px 45px; }.page-head { padding:20px 17px; }.title-row { align-items:flex-start; flex-direction:column; }.summary-grid { grid-template-columns:repeat(2,1fr); }.section-head { align-items:flex-start; flex-direction:column; }.source-row { grid-template-columns:1fr; }.source-actions { justify-content:flex-start; }.run-list article { grid-template-columns:1fr 90px; }.run-counts { grid-column:1/-1; }.form-grid,.edit-form { grid-template-columns:1fr; }.import-summary { grid-template-columns:repeat(2,1fr); } }
</style>
