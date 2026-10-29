<template>
  <main class="collection-page">
    <header class="page-head">
      <button class="back" type="button" @click="router.push({ name: 'market-intel-sources' })">← 数据源配置</button>
      <div class="head-row"><div><span class="eyebrow">COLLECTION PIPELINE</span><h1>{{ batchId ? '采集批次进度' : '采集批次' }}</h1><p>{{ batchId ? (batch?.mode === 'fetch_only' ? '本批只获取并保存文章原文，不启动模型分析。' : '来源抓取和资料研究分别统计，页面关闭后任务仍会继续。') : '历史批次与当前运行状态；来源完成不代表后续研究已经完成。' }}</p></div><button v-if="batchId" class="secondary" @click="load">刷新进度</button></div>
    </header>
    <div v-if="error" class="notice error" role="alert">{{ error }}</div>
    <section v-if="!batchId" class="panel">
      <div class="section-head"><h2>历史批次</h2><button class="small" @click="load">刷新</button></div>
      <div v-if="loading" class="empty">正在读取批次…</div>
      <div v-else-if="!batches.length" class="empty">还没有采集批次。可以从工作台或数据源配置启动。</div>
      <div v-else class="batch-list"><button v-for="item in batches" :key="item.id" type="button" class="batch-card" @click="router.push({ name: 'market-intel-collection-detail', params: { batchId: item.id } })"><div><strong>{{ batchTitle(item) }}</strong><small>{{ item.source_total }} 个来源 · {{ formatTime(item.created_at) }}</small></div><span class="state" :class="item.status">{{ statusText(item.status) }}</span><span class="counts">来源 {{ item.counts?.source_terminal || 0 }}/{{ item.source_total }} · 发现 {{ item.counts?.source?.found || 0 }} · 观察 {{ item.counts?.observations || 0 }}</span><span class="arrow">↗</span></button></div>
    </section>

    <template v-else-if="batch">
      <section class="panel overview">
        <div class="batch-title"><div><span class="state" :class="batch.status">{{ statusText(batch.status) }}</span><h2>{{ batchTitle(batch) }}</h2><p>启动时间 {{ formatTime(batch.created_at) }} · 触发人 {{ batch.user_id }} · 处理模式 {{ batch.mode === 'fetch_only' ? '只抓取原文' : '抓取并分析' }} · 候选上限 {{ batch.budget?.max_items || '—' }} · 最近心跳 {{ formatTime(batch.updated_at) }}</p></div><div v-if="auth.isAdmin" class="actions"><button v-if="['running','waiting','queued'].includes(batch.status)" class="small" @click="act('pause')">暂停</button><button v-if="batch.status === 'paused'" class="small" @click="act('resume')">继续</button><button v-if="['running','waiting','queued','paused'].includes(batch.status)" class="small danger" @click="act('stop')">停止投递</button><button v-if="['completed_with_issues','failed','cancelled'].includes(batch.status)" class="small" @click="act('retry-failed')">仅重试失败来源</button></div></div>
        <div class="phase-grid">
          <article><div class="phase-label"><span>来源抓取</span><b>{{ sourcePercent }}%</b></div><div class="meter"><i :style="{ width: `${sourcePercent}%` }"></i></div><p>{{ batch.counts?.source_terminal || 0 }} / {{ batch.source_total }} 个来源已终结；{{ batch.counts?.source?.failed || 0 }} 个失败，{{ batch.counts?.source?.cancelled || 0 }} 个取消。</p></article>
          <article><div class="phase-label"><span>{{ batch.mode === 'fetch_only' ? '模型分析' : '资料研究' }}</span><b>{{ pipelineLabel }}</b></div><div class="meter pipeline-meter"><i :style="{ width: `${pipelinePercent}%` }"></i></div><p v-if="batch.mode === 'fetch_only'">本批已设置为只抓原文；模型分析未请求。</p><p v-else>排队 {{ batch.counts?.pipeline?.queued || 0 }} · 处理中 {{ batch.counts?.pipeline?.running || 0 }} · 等待重试 {{ batch.counts?.pipeline?.waiting_retry || 0 }} · 成功 {{ batch.counts?.pipeline?.succeeded || 0 }} · 失败 {{ batch.counts?.pipeline?.failed || 0 }}</p></article>
        </div>
        <div class="result-metrics"><div><b>{{ batch.counts?.source?.found || 0 }}</b><span>发现条目</span></div><div><b>{{ batch.counts?.unique_documents || 0 }}</b><span>唯一文档</span></div><div><b>{{ batch.counts?.source?.duplicate || 0 }}</b><span>重复发现</span></div><div><b>{{ batch.counts?.observations || 0 }}</b><span>研究观察</span></div></div>
        <p class="as-of">统计截至 {{ formatTime(batch.counts?.as_of || batch.as_of) }} · 统计版本 {{ batch.counts?.version || 0 }}</p>
      </section>
      <section class="panel"><div class="section-head"><h2>来源进度 <small>{{ tasks.length }} 个来源</small></h2><span>终结进度不代表全部成功</span></div>
        <div v-if="!tasks.length" class="empty">批次暂无来源任务。</div>
        <div v-else class="task-list"><article v-for="task in tasks" :key="task.source_id"><div class="task-main"><strong>{{ task.source_name }}</strong><small>{{ task.run_id || '尚未创建来源运行' }}<span v-if="task.error"> · {{ task.error }}</span></small></div><span class="state" :class="task.status">{{ statusText(task.status) }}</span><span class="task-counts">发现 {{ task.counts?.found || 0 }} · 新增 {{ task.counts?.new || 0 }} · 修订 {{ task.counts?.revised || 0 }} · 重复 {{ task.counts?.duplicate || 0 }} · 失败 {{ task.counts?.failed || 0 }}</span></article></div>
      </section>
      <section class="panel"><div class="section-head"><h2>批次事件</h2><span>断线后可从持久记录继续读取</span></div><div class="event-list"><article v-for="event in events" :key="event.sequence"><span>#{{ event.sequence }}</span><strong>{{ eventName(event.event_type) }}</strong><small>{{ formatTime(event.created_at) }}</small><code v-if="event.payload?.to">{{ statusText(event.payload.to) }}</code></article><div v-if="!events.length" class="empty">暂无状态变化。</div></div></section>
    </template>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'
import { useAuthStore } from '../../../stores/auth.js'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const batchId = computed(() => route.params.batchId ? String(route.params.batchId) : '')
const batch = ref(null)
const batches = ref([])
const tasks = ref([])
const events = ref([])
const loading = ref(true)
const error = ref('')
let pollTimer = null
const sourcePercent = computed(() => batch.value?.source_total ? Math.round((batch.value.counts?.source_terminal || 0) / batch.value.source_total * 100) : 0)
const pipelinePercent = computed(() => {
  if (batch.value?.mode === 'fetch_only') return batch.value?.counts?.source_fetch_finished ? 100 : 0
  const counts = batch.value?.counts?.pipeline || {}
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0)
  return total ? Math.round(Number(counts.succeeded || 0) / total * 100) : (batch.value?.counts?.source_fetch_finished ? 100 : 0)
})
const pipelineLabel = computed(() => batch.value?.mode === 'fetch_only' ? '未请求' : batch.value?.pipeline_finished_at ? '已终结' : batch.value?.counts?.source_fetch_finished ? '处理中' : '等待来源完成')

function statusText(status) { return ({ queued: '排队中', running: '运行中', waiting: '研究处理中', paused: '已暂停', completed: '已完成', completed_with_issues: '完成但有问题', failed: '失败', cancelled: '已停止', succeeded: '抓取完成', skipped: '已跳过' })[status] || status || '未知' }
function batchTitle(item) { const kind = item.mode === 'fetch_only' ? '原文获取' : '采集'; return item.topic_id ? `${topicName(item.topic_id)} · ${kind}` : `全量来源增量${kind}` }
function topicName(id) { return ({ 'ai-frontier': 'AI 前沿观察', 'embodied-intelligence': '具身智能', 'policy-analysis': '政策分析' })[id] || id }
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未记录' }
function eventName(value) { return ({ batch_created: '已建立采集批次', sources_excluded: '有来源未能纳入', batch_status_changed: '批次状态变化', batch_pause: '暂停批次', batch_resume: '继续批次', batch_stop: '停止投递', batch_retry_failed: '重试失败来源' })[value] || value }

async function load() {
  error.value = ''
  try {
    if (!batchId.value) {
      const { data } = await api.get('/market-research/collection-batches')
      batches.value = data.items || []
    } else {
      const [batchResult, taskResult, eventResult] = await Promise.all([
        api.get(`/market-research/collection-batches/${batchId.value}`),
        api.get(`/market-research/collection-batches/${batchId.value}/tasks`),
        api.get(`/market-research/collection-batches/${batchId.value}/events`, { params: { after_sequence: 0, limit: 200 } }),
      ])
      batch.value = batchResult.data
      tasks.value = taskResult.data.items || []
      events.value = eventResult.data.items || []
      if (['queued','running','waiting'].includes(batch.value.status)) startPolling(); else stopPolling()
    }
  } catch (err) { error.value = err.response?.data?.detail || '采集批次暂时无法加载。' }
  finally { loading.value = false }
}

async function act(action) {
  try { const { data } = await api.post(`/market-research/collection-batches/${batchId.value}/${action}`); batch.value = data; await load() }
  catch (err) { error.value = err.response?.data?.detail || '批次操作失败。' }
}
function startPolling() { if (!pollTimer) pollTimer = setInterval(load, 3000) }
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null }
onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<style scoped>
.collection-page { max-width:1180px; margin:0 auto; padding:34px 28px 60px; color:#263b50; font-family:'Noto Sans SC',sans-serif; }.page-head,.panel { padding:23px 27px; border:1px solid #e0e6eb; border-radius:13px; background:#fff; box-shadow:0 5px 20px #30465a08; }.page-head { background:linear-gradient(120deg,#f7fafb,#fff 62%,#f8f3eb); }.back { padding:0; border:0; color:#718398; background:none; cursor:pointer; font:inherit; font-size:13px; }.head-row,.section-head { display:flex; align-items:center; justify-content:space-between; gap:18px; }.head-row { margin-top:22px; }.eyebrow { color:#a47742; font:600 10px 'DM Mono',monospace; letter-spacing:.18em; }h1 { margin:8px 0 6px; color:#273d53; font-size:28px; }.head-row p,.batch-title p { margin:0; color:#7c8b99; font-size:13px; }.secondary,.small { padding:8px 12px; border:1px solid #d8e0e6; border-radius:7px; color:#52677a; background:white; cursor:pointer; font:600 12px 'Noto Sans SC',sans-serif; }.small.danger { color:#a65c53; }.panel { margin-top:18px; }.section-head { margin-bottom:13px; }.section-head h2,.panel h2 { margin:0; color:#324a60; font-size:16px; }.section-head h2 small { color:#8794a0; font-size:11px; font-weight:400; }.section-head > span { color:#8794a0; font-size:11px; }.empty { padding:27px 0; color:#8795a2; font-size:13px; text-align:center; }.batch-list,.task-list,.event-list { border-top:1px solid #edf0f2; }.batch-card { display:grid; grid-template-columns:minmax(0,1fr) auto 270px 15px; align-items:center; gap:14px; width:100%; padding:14px 4px; border:0; border-bottom:1px solid #edf0f2; color:inherit; background:white; text-align:left; cursor:pointer; }.batch-card:hover { background:#fafbfc; }.batch-card strong,.batch-card small { display:block; }.batch-card strong { color:#384f63; font-size:13px; }.batch-card small { margin-top:4px; color:#84929f; font-size:11px; }.counts { color:#82909c; font-size:11px; }.arrow { color:#a5b0b9; }.state { display:inline-block; padding:4px 8px; border-radius:4px; color:#8a714f; background:#f7f2e9; font-size:10px; white-space:nowrap; }.state.completed,.state.succeeded { color:#4d7e62; background:#edf5ef; }.state.running,.state.queued,.state.waiting { color:#a77942; background:#faf3e9; }.state.failed,.state.completed_with_issues { color:#a75e56; background:#fbefed; }.state.paused,.state.cancelled,.state.skipped { color:#7a8792; background:#f1f3f5; }.batch-title { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; }.batch-title h2 { display:inline-block; margin:10px 9px 6px 0; font-size:19px; }.batch-title p { font-size:11px; }.actions { display:flex; gap:7px; }.phase-grid { display:grid; grid-template-columns:1fr 1fr; gap:15px; margin-top:22px; }.phase-grid article { padding:15px; border:1px solid #e8ecef; border-radius:8px; background:#fbfcfc; }.phase-label { display:flex; justify-content:space-between; color:#4e6275; font-size:12px; }.phase-label b { color:#60788d; font:600 14px 'DM Mono',monospace; }.meter { height:6px; overflow:hidden; margin:10px 0; border-radius:5px; background:#e9eef1; }.meter i { display:block; height:100%; border-radius:5px; background:#79a78a; transition:width .2s; }.pipeline-meter i { background:#b89665; }.phase-grid p { margin:0; color:#84929f; font-size:11px; line-height:1.6; }.result-metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:9px; margin-top:13px; }.result-metrics div { display:flex; align-items:baseline; gap:9px; padding:11px 13px; border-radius:7px; background:#f6f8f8; }.result-metrics b { color:#3c5267; font:600 18px 'DM Mono',monospace; }.result-metrics span,.as-of { color:#8795a1; font-size:11px; }.as-of { margin:12px 0 0; text-align:right; }.task-list article { display:grid; grid-template-columns:minmax(210px,1fr) 90px minmax(360px,auto); align-items:center; gap:12px; padding:13px 2px; border-bottom:1px solid #edf0f2; }.task-main strong,.task-main small { display:block; }.task-main strong { color:#445b70; font-size:12px; }.task-main small { margin-top:3px; color:#8996a1; font-size:10px; }.task-counts { color:#7f8e9a; font-size:11px; }.event-list article { display:grid; grid-template-columns:55px minmax(0,1fr) 180px 110px; align-items:center; gap:10px; padding:10px 2px; border-bottom:1px solid #edf0f2; color:#748594; font-size:11px; }.event-list article > span { font-family:'DM Mono',monospace; }.event-list article strong { color:#50677a; font-weight:500; }.event-list code { color:#a17946; font-family:inherit; }.notice.error { margin-top:15px; padding:12px; border-radius:6px; color:#995a54; background:#fbefed; font-size:13px; }
@media(max-width:760px) { .collection-page { padding:18px 13px 42px; }.page-head,.panel { padding:18px 16px; }.head-row,.batch-title { align-items:flex-start; flex-direction:column; }.batch-card { grid-template-columns:minmax(0,1fr) auto; }.counts,.arrow { grid-column:1/-1; }.phase-grid { grid-template-columns:1fr; }.result-metrics { grid-template-columns:repeat(2,1fr); }.task-list article { grid-template-columns:minmax(0,1fr) auto; }.task-counts { grid-column:1/-1; }.event-list article { grid-template-columns:45px minmax(0,1fr); }.event-list article small,.event-list article code { grid-column:2; } }
</style>
