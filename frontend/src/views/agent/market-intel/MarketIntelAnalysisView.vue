<template>
  <main class="analysis-page">
    <div class="analysis-wrap">
      <div class="page-toolbar">
        <button class="back-link" type="button" @click="goBack"><span aria-hidden="true">←</span> 返回研究详情</button>
        <span class="breadcrumb">小察 <i>／</i> {{ topicName }} <i>／</i> AI 研判</span>
      </div>

      <div v-if="loading" class="state-panel" role="status"><span class="loader-ring"></span>正在读取观察与研判记录…</div>
      <div v-else-if="pageError" class="state-panel error-panel" role="alert">
        <div><h1>研判页面无法打开</h1><p>{{ pageError }}</p></div>
        <button class="primary-button" type="button" @click="loadPage">重新加载</button>
      </div>

      <template v-else-if="observation">
        <header class="analysis-header">
          <div class="header-copy">
            <span class="section-kicker">INDUSTRY JUDGEMENT</span>
            <h1>AI 研判</h1>
            <p>基于这条观察中的事实与来源，分析行业影响，并把判断和不确定性分开呈现。</p>
          </div>
          <div class="source-record">
            <span class="record-label">当前研究观察</span>
            <h2>{{ observation.title }}</h2>
            <p>{{ observation.summary || '这条观察暂无摘要。研判将同时参考正文与可追溯来源。' }}</p>
            <div class="record-facts"><span>{{ topicName }}</span><span>{{ observation.category_name || '待分类' }}</span><span>{{ observation.sources?.length || 0 }} 个来源</span><span>记录于 {{ formatDate(observation.captured_at) }}</span></div>
          </div>
        </header>

        <section class="analysis-controls" aria-label="发起 AI 研判">
          <label for="focus-question">希望重点判断什么？<span>可选</span></label>
          <div class="control-row">
            <textarea id="focus-question" v-model="focusQuestion" rows="2" maxlength="2000" :disabled="starting || isRunning" placeholder="例如：这项进展对产业链供应商的影响有多大？"></textarea>
            <button class="start-button" type="button" :disabled="starting || isRunning" @click="startAnalysis">
              <span class="button-symbol" aria-hidden="true">✳</span>
              {{ starting ? '正在启动…' : isRunning ? '研判进行中' : currentAnalysis ? '重新研判' : '开始 AI 研判' }}
            </button>
          </div>
          <p v-if="startError" class="inline-error" role="alert">{{ startError }}</p>
          <p v-else class="control-note">每次研判都会作为独立运行记录保存，可回看先前结果。</p>
        </section>

        <div class="analysis-grid">
          <section class="result-panel" aria-labelledby="result-title">
            <header class="result-heading">
              <div><span class="section-kicker">ANALYSIS RESULT</span><h2 id="result-title">研判结果</h2></div>
              <span class="status-pill" :class="`status-${currentStatus}`"><i></i>{{ statusLabel }}</span>
            </header>

            <div v-if="connectionNotice" class="connection-notice" role="status">
              <span>{{ connectionNotice }}</span>
              <button v-if="isRunning" type="button" @click="resumeStream">继续接收</button>
            </div>

            <div v-if="!currentAnalysis" class="result-empty">
              <div class="empty-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
              <h3>让这条信息形成判断</h3>
              <p>开始研判后，小察会梳理核心结论、行业影响、机会与风险，并列出下一步值得验证的信号。</p>
            </div>
            <div v-else-if="analysisText" class="analysis-content" v-html="renderMd(analysisText)"></div>
            <div v-else-if="isRunning" class="thinking-state" role="status">
              <span class="thinking-orbit"><i></i></span>
              <div><strong>{{ currentStage || (currentStatus === 'queued' ? '任务已排队' : '正在分析证据') }}</strong><p>结果会在这里逐步呈现。离开页面不会中止后台研判。</p></div>
            </div>
            <div v-else-if="currentAnalysis" class="result-empty compact-empty">
              <h3>{{ currentStatus === 'error' || currentStatus === 'abandoned' ? '这次研判没有完成' : '尚无可展示的研判正文' }}</h3>
              <p>{{ currentAnalysis.error || '可以重新发起一次研判；已有运行记录仍保留在右侧历史中。' }}</p>
              <button v-if="currentStatus === 'error' || currentStatus === 'abandoned'" class="text-button" type="button" @click="startAnalysis">重新研判</button>
            </div>
            <footer v-if="currentAnalysis" class="result-footer">
              <span v-if="currentAnalysis.created_at">发起于 {{ formatDateTime(currentAnalysis.created_at) }}</span>
              <span v-if="currentAnalysis.focus_question">关注点：{{ currentAnalysis.focus_question }}</span>
              <span v-if="isRunning" class="stream-indicator"><i></i> 正在接收结果</span>
            </footer>
          </section>

          <aside class="evidence-column">
            <section class="evidence-panel">
              <header><div><span class="section-kicker">EVIDENCE</span><h2>研判依据</h2></div><span class="evidence-count">{{ observation.sources?.length || 0 }}</span></header>
              <p class="evidence-summary">{{ observation.summary || '暂无摘要，研判将以研究正文和来源信息作为依据。' }}</p>
              <a v-for="(source, index) in observation.sources || []" :key="`${source.url}-${index}`" class="evidence-link" :href="source.url || undefined" target="_blank" rel="noopener noreferrer" :class="{ disabled: !source.url }">
                <span class="source-index">{{ String(index + 1).padStart(2, '0') }}</span><span><strong>{{ source.title || source.organization || source.url || '未命名来源' }}</strong><small>{{ source.organization || source.published_at || '打开原始资料' }}</small></span><span v-if="source.url" class="external-arrow" aria-hidden="true">↗</span>
              </a>
              <p v-if="!observation.sources?.length" class="no-evidence">目前没有登记引用链接。请把研判结论视为待核验判断。</p>
              <button class="detail-link" type="button" @click="goDetail">查看完整研究记录 <span aria-hidden="true">↗</span></button>
            </section>

            <section class="history-panel">
              <header><div><span class="section-kicker">RUN HISTORY</span><h2>研判历史</h2></div><span class="history-count">{{ history.length }}</span></header>
              <div v-if="!history.length" class="history-empty">完成第一次研判后，运行记录会保存在这里。</div>
              <button v-for="entry in history" :key="entry.id" type="button" class="history-item" :class="{ selected: currentAnalysis?.id === entry.id }" @click="selectAnalysis(entry)">
                <span class="history-status" :class="`status-${entry.status || 'abandoned'}`"><i></i></span>
                <span class="history-copy"><strong>{{ entry.focus_question || '行业影响与趋势研判' }}</strong><small>{{ formatDateTime(entry.created_at) }}</small></span>
                <span class="history-chevron" aria-hidden="true">›</span>
              </button>
              <button v-if="history.length" class="refresh-history" type="button" @click="loadHistory">刷新历史</button>
            </section>
          </aside>
        </div>
      </template>
    </div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'
import { renderMd } from '../../../composables/useChatStream.js'

const route = useRoute()
const router = useRouter()
const observation = ref(null)
const history = ref([])
const currentAnalysis = ref(null)
const analysisText = ref('')
const focusQuestion = ref('')
const currentStage = ref('')
const connectionNotice = ref('')
const startError = ref('')
const pageError = ref('')
const loading = ref(true)
const starting = ref(false)
let streamController = null
let lastEventSeq = 0

const topicName = computed(() => ({
  'embodied-intelligence': '具身智能',
  'ai-frontier': 'AI 前沿观察',
  'policy-analysis': '政策分析',
}[observation.value?.topic_id || route.query.topic] || '行业观察'))
const currentStatus = computed(() => currentAnalysis.value?.status || 'idle')
const isRunning = computed(() => ['queued', 'running'].includes(currentStatus.value))
const statusLabel = computed(() => ({
  idle: '待开始', queued: '等待运行', running: '正在研判', done: '已完成',
  error: '运行失败', interrupted: '等待处理', cancelled: '已取消', abandoned: '已中断',
}[currentStatus.value] || '待开始'))

function formatDate(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
function formatDateTime(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

function stopStream() {
  if (streamController) streamController.abort()
  streamController = null
}

async function loadPage() {
  stopStream()
  loading.value = true
  pageError.value = ''
  observation.value = null
  history.value = []
  currentAnalysis.value = null
  analysisText.value = ''
  try {
    const { data } = await api.get(`/market-research/observations/${encodeURIComponent(route.params.id)}`)
    observation.value = data
    await loadHistory()
    if (currentAnalysis.value) await restoreSelectedAnalysis()
  } catch (err) {
    pageError.value = err.response?.data?.detail || '研究记录暂时无法加载，请检查连接后重试。'
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  if (!observation.value) return
  try {
    const { data } = await api.get(`/market-research/observations/${encodeURIComponent(route.params.id)}/analyses`)
    history.value = data.items || []
    if (!currentAnalysis.value && history.value.length) {
      currentAnalysis.value = history.value[0]
      focusQuestion.value = isRunning.value ? '' : currentAnalysis.value.focus_question || ''
    }
  } catch (err) {
    startError.value = err.response?.data?.detail || '研判历史暂时无法加载。'
  }
}

async function restoreSelectedAnalysis() {
  if (!currentAnalysis.value) return
  analysisText.value = ''
  currentStage.value = ''
  connectionNotice.value = ''
  lastEventSeq = 0
  if (['done', 'interrupted'].includes(currentAnalysis.value.status)) {
    await loadFinalConversation(currentAnalysis.value)
  } else if (isRunning.value) {
    resumeStream()
  }
}

async function loadFinalConversation(entry) {
  try {
    const { data } = await api.get(`/conversations/${encodeURIComponent(entry.conversation_id)}`)
    const lastAssistant = [...(data.turns || [])].reverse().find(turn => turn.role === 'assistant' && turn.content?.trim())
    if (lastAssistant) analysisText.value = lastAssistant.content
  } catch (err) {
    connectionNotice.value = '运行已结束，但最终结果暂时无法读取；请稍后刷新。'
  }
}

async function startAnalysis() {
  if (!observation.value || starting.value || isRunning.value) return
  stopStream()
  starting.value = true
  startError.value = ''
  connectionNotice.value = ''
  analysisText.value = ''
  currentStage.value = ''
  try {
    const focusQuestionToSubmit = focusQuestion.value.trim()
    const { data } = await api.post(`/market-research/observations/${encodeURIComponent(route.params.id)}/analyses`, {
      focus_question: focusQuestionToSubmit,
    })
    focusQuestion.value = ''
    currentAnalysis.value = { ...data.analysis, ...data.run, status: data.run.status, error: '' }
    history.value = [currentAnalysis.value, ...history.value.filter(item => item.id !== currentAnalysis.value.id)]
    lastEventSeq = 0
    resumeStream()
  } catch (err) {
    startError.value = err.response?.data?.detail || 'AI 研判任务启动失败，请稍后重试。'
  } finally {
    starting.value = false
  }
}

function handleEvent(event) {
  if (event._event_seq) lastEventSeq = Math.max(lastEventSeq, Number(event._event_seq))
  if (['run_started', 'token', 'stage', 'tool'].includes(event.type)) {
    updateCurrentAnalysis({ status: 'running' })
  }
  if (event.type === 'token') analysisText.value += event.content || ''
  else if (event.type === 'stage') currentStage.value = event.detail_text || event.stage || '正在分析证据'
  else if (event.type === 'tool') currentStage.value = event.name ? `正在使用 ${event.name}` : '正在整理研究材料'
  else if (event.type === 'error') {
    if (event.error_code === 'run_events_expired') connectionNotice.value = '实时事件已过保留期，正在尝试读取最终结果。'
    else {
      updateCurrentAnalysis({ status: 'error', error: event.message || '研判运行失败' })
    }
  } else if (event.type === 'approval_required') {
    updateCurrentAnalysis({ status: 'interrupted' })
    connectionNotice.value = '研判运行暂停，等待人工处理。'
  } else if (event.type === 'message_end') {
    updateCurrentAnalysis({ status: 'done' })
  }
}

function updateCurrentAnalysis(patch) {
  if (!currentAnalysis.value) return
  currentAnalysis.value = { ...currentAnalysis.value, ...patch }
  history.value = history.value.map(item => item.id === currentAnalysis.value.id ? currentAnalysis.value : item)
}

async function resumeStream() {
  if (!currentAnalysis.value?.run_id || streamController) return
  streamController = new AbortController()
  const controller = streamController
  connectionNotice.value = ''
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(currentAnalysis.value.run_id)}/events?after=${lastEventSeq}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      signal: controller.signal,
    })
    if (!response.ok) throw new Error(`服务返回 HTTP ${response.status}`)
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() || ''
      for (const frame of frames) {
        const line = frame.split('\n').find(row => row.startsWith('data:'))
        if (!line) continue
        try { handleEvent(JSON.parse(line.slice(5).trim())) } catch { /* 忽略不完整事件 */ }
      }
    }
    if (controller.signal.aborted) return
    const { data: run } = await api.get(`/runs/${encodeURIComponent(currentAnalysis.value.run_id)}`)
    updateCurrentAnalysis({ status: run.status, error: run.error || '' })
    if (!analysisText.value || run.status === 'done') await loadFinalConversation(currentAnalysis.value)
    if (['error', 'abandoned', 'cancelled'].includes(run.status) && !analysisText.value) {
      updateCurrentAnalysis({ error: run.error || '研判运行未能完成' })
    }
    if (run.status === 'interrupted') connectionNotice.value = '研判运行暂停，等待人工处理。'
    if (run.status === 'done' || run.status === 'error') await loadHistory()
  } catch (err) {
    if (err.name !== 'AbortError') {
      connectionNotice.value = '连接中断，研判仍在后台运行。你可以继续接收，或稍后重新打开此页。'
    }
  } finally {
    if (streamController === controller) streamController = null
  }
}

async function selectAnalysis(entry) {
  if (currentAnalysis.value?.id === entry.id) return
  stopStream()
  currentAnalysis.value = entry
  focusQuestion.value = ['queued', 'running'].includes(entry.status) ? '' : entry.focus_question || ''
  await restoreSelectedAnalysis()
}

function goBack() {
  goDetail()
}
function goDetail() {
  router.push({ name: 'market-intel-observation', params: { id: route.params.id }, query: {
    topic: observation.value?.topic_id || route.query.topic,
    category: route.query.category,
  } })
}

watch(() => route.params.id, loadPage, { immediate: true })
onBeforeUnmount(stopStream)
</script>

<style scoped>
.analysis-page {
  min-height: 100%;
  padding: 22px 34px 42px;
  color: #0f172a;
  background: #f1f5f9;
  font-family: var(--font-sans, 'Noto Sans SC', sans-serif);
}
.analysis-wrap { width: min(100%, 1450px); margin: 0 auto; }
.page-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 34px; margin-bottom: 22px; }
.back-link { display: inline-flex; align-items: center; gap: 8px; padding: 7px 10px; border: 1px solid #e2e8f0; border-radius: 7px; color: #475569; background: #fff; cursor: pointer; font: 500 14px var(--font-sans, sans-serif); }
.back-link:hover { color: #2563eb; border-color: #bfdbfe; background: #eff6ff; }
.back-link span { font-size: 17px; line-height: 1; }
.breadcrumb { color: #94a3b8; font-size: 13px; }
.breadcrumb i { margin: 0 5px; color: #cbd5e1; font-style: normal; }
.analysis-header { display: grid; grid-template-columns: minmax(230px, .55fr) minmax(0, 1.45fr); gap: 18px; align-items: stretch; }
.header-copy { display: flex; flex-direction: column; justify-content: center; padding: 22px 13px 22px 4px; }
.section-kicker { color: #64748b; font: 600 11px var(--font-mono, ui-monospace, monospace); letter-spacing: .11em; }
.header-copy h1 { margin: 8px 0 5px; color: #0f172a; font-size: clamp(29px, 3.2vw, 40px); font-weight: 700; letter-spacing: -.035em; }
.header-copy p { max-width: 410px; margin: 0; color: #64748b; font-size: 15px; line-height: 1.8; }
.source-record { padding: 22px 24px; border: 1px solid #dbeafe; border-left: 4px solid #3b82f6; border-radius: 10px; background: #fff; box-shadow: 0 4px 18px rgba(15,23,42,.035); }
.record-label { color: #2563eb; font-size: 13px; font-weight: 650; }
.source-record h2 { margin: 9px 0 7px; color: #0f172a; font-size: 19px; font-weight: 650; line-height: 1.55; }
.source-record p { margin: 0; color: #475569; font-size: 15px; line-height: 1.75; }
.record-facts { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 13px; color: #64748b; font-size: 13px; }
.record-facts span:first-child { color: #1d4ed8; font-weight: 600; }
.analysis-controls { margin-top: 16px; padding: 17px 20px; border: 1px solid #dbe3ee; border-radius: 10px; background: #fff; }
.analysis-controls > label { display: flex; align-items: baseline; gap: 9px; margin-bottom: 9px; color: #1e293b; font-size: 15px; font-weight: 650; }
.analysis-controls > label span { color: #94a3b8; font-size: 12px; font-weight: 400; }
.control-row { display: flex; align-items: stretch; gap: 12px; }
.control-row textarea { flex: 1; min-width: 0; min-height: 58px; resize: vertical; padding: 11px 13px; border: 1px solid #cbd5e1; border-radius: 7px; color: #0f172a; background: #fff; font: 14px/1.7 var(--font-sans, sans-serif); }
.control-row textarea:focus { outline: 3px solid #dbeafe; border-color: #60a5fa; }
.control-row textarea::placeholder { color: #94a3b8; }
.start-button { display: inline-flex; min-width: 154px; align-items: center; justify-content: center; gap: 8px; padding: 10px 15px; border: 1px solid #2563eb; border-radius: 7px; color: #fff; background: #3b82f6; cursor: pointer; font: 650 14px var(--font-sans, sans-serif); transition: .16s ease; }
.start-button:hover { background: #2563eb; }
.start-button:disabled { opacity: .6; cursor: wait; }
.button-symbol { font-size: 18px; }
.control-note,.inline-error { margin: 8px 0 0; color: #94a3b8; font-size: 13px; }
.inline-error { color: #b91c1c; }
.analysis-grid { display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 16px; align-items: start; margin-top: 16px; }
.result-panel,.evidence-panel,.history-panel,.state-panel { border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; box-shadow: 0 4px 18px rgba(15,23,42,.035); }
.result-panel { min-height: 520px; overflow: hidden; }
.result-heading,.evidence-panel > header,.history-panel > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 19px 22px; border-bottom: 1px solid #e8edf3; }
.result-heading h2,.evidence-panel h2,.history-panel h2 { margin: 4px 0 0; color: #0f172a; font-size: 19px; font-weight: 650; }
.status-pill { display: inline-flex; align-items: center; gap: 7px; padding: 6px 10px; border: 1px solid #e2e8f0; border-radius: 99px; color: #64748b; background: #f8fafc; font-size: 12px; white-space: nowrap; }
.status-pill i,.history-status i,.stream-indicator i { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.status-running,.status-queued { color: #1d4ed8; border-color: #bfdbfe; background: #eff6ff; }
.status-done { color: #15803d; border-color: #bbf7d0; background: #f0fdf4; }
.status-error,.status-abandoned,.status-cancelled { color: #b91c1c; border-color: #fecaca; background: #fef2f2; }
.status-interrupted { color: #b45309; border-color: #fde68a; background: #fffbeb; }
.connection-notice { display: flex; justify-content: space-between; gap: 12px; padding: 10px 20px; color: #1d4ed8; background: #eff6ff; font-size: 13px; line-height: 1.6; }
.connection-notice button,.text-button { padding: 0; border: 0; color: #1d4ed8; background: none; cursor: pointer; font: 650 13px var(--font-sans, sans-serif); text-decoration: underline; text-underline-offset: 3px; white-space: nowrap; }
.analysis-content { padding: 23px 29px 27px; color: #334155; font-size: 16px; line-height: 1.9; overflow-wrap: anywhere; }
.analysis-content :deep(h1),.analysis-content :deep(h2) { margin: 26px 0 11px; color: #0f172a; font-size: 20px; font-weight: 700; line-height: 1.5; }
.analysis-content :deep(h1:first-child),.analysis-content :deep(h2:first-child) { margin-top: 0; }
.analysis-content :deep(h3) { margin: 21px 0 8px; color: #1e293b; font-size: 17px; font-weight: 650; }
.analysis-content :deep(p) { margin: 0 0 15px; }
.analysis-content :deep(ul),.analysis-content :deep(ol) { margin: 0 0 16px; padding-left: 25px; }
.analysis-content :deep(li) { margin: 5px 0; padding-left: 3px; }
.analysis-content :deep(strong) { color: #1e293b; font-weight: 700; }
.analysis-content :deep(a) { color: #2563eb; text-decoration: underline; text-underline-offset: 3px; }
.analysis-content :deep(blockquote) { margin: 18px 0; padding: 10px 16px; border-left: 3px solid #93c5fd; color: #475569; background: #f8fbff; }
.analysis-content :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
.analysis-content :deep(th),.analysis-content :deep(td) { padding: 8px 11px; border: 1px solid #e2e8f0; text-align: left; }
.analysis-content :deep(th) { background: #f8fafc; }
.result-empty { display: flex; min-height: 365px; flex-direction: column; align-items: center; justify-content: center; padding: 32px; text-align: center; }
.result-empty h3 { margin: 16px 0 7px; color: #1e293b; font-size: 18px; }
.result-empty p { max-width: 470px; margin: 0; color: #64748b; font-size: 15px; line-height: 1.8; }
.empty-wave { display: flex; height: 34px; align-items: center; gap: 5px; }
.empty-wave i { display: block; width: 4px; height: 14px; border-radius: 5px; background: #93c5fd; }
.empty-wave i:nth-child(2),.empty-wave i:nth-child(4) { height: 25px; background: #60a5fa; }
.empty-wave i:nth-child(3) { height: 33px; background: #3b82f6; }
.compact-empty { min-height: 310px; }
.thinking-state { display: flex; min-height: 365px; align-items: center; justify-content: center; gap: 17px; padding: 32px; }
.thinking-state strong { color: #1e3a8a; font-size: 17px; }
.thinking-state p { margin: 5px 0 0; color: #64748b; font-size: 14px; line-height: 1.7; }
.thinking-orbit { position: relative; display: grid; width: 42px; height: 42px; place-items: center; border: 1px solid #bfdbfe; border-radius: 50%; }
.thinking-orbit::before { position: absolute; width: 28px; height: 28px; border: 2px solid #dbeafe; border-top-color: #3b82f6; border-radius: 50%; content: ''; animation: orbit .9s linear infinite; }
.thinking-orbit i { width: 7px; height: 7px; border-radius: 50%; background: #3b82f6; }
@keyframes orbit { to { transform: rotate(360deg); } }
.result-footer { display: flex; flex-wrap: wrap; gap: 8px 15px; padding: 13px 21px; border-top: 1px solid #e8edf3; color: #94a3b8; font-size: 12px; }
.stream-indicator { display: inline-flex; align-items: center; gap: 6px; color: #2563eb; }
.evidence-column { display: grid; gap: 14px; }
.evidence-panel,.history-panel { overflow: hidden; }
.evidence-panel > header,.history-panel > header { padding: 16px 18px; }
.evidence-panel h2,.history-panel h2 { font-size: 17px; }
.evidence-count,.history-count { display: grid; min-width: 27px; height: 27px; place-items: center; padding: 0 7px; border-radius: 8px; color: #2563eb; background: #eff6ff; font: 600 12px var(--font-mono, monospace); }
.evidence-summary { margin: 0; padding: 15px 17px 4px; color: #475569; font-size: 14px; line-height: 1.75; }
.evidence-link { display: flex; align-items: flex-start; gap: 10px; margin: 9px 13px 0; padding: 11px 9px; border: 1px solid #e2e8f0; border-radius: 7px; color: inherit; text-decoration: none; }
.evidence-link:hover { border-color: #bfdbfe; background: #f8fbff; }
.evidence-link.disabled { cursor: default; }
.source-index { padding-top: 1px; color: #94a3b8; font: 600 11px var(--font-mono, monospace); }
.evidence-link > span:nth-child(2) { display: grid; min-width: 0; flex: 1; gap: 4px; }
.evidence-link strong { color: #334155; font-size: 13px; line-height: 1.5; }
.evidence-link small { color: #94a3b8; font-size: 11px; }
.external-arrow { color: #2563eb; }
.no-evidence { margin: 14px 17px; color: #b45309; font-size: 13px; line-height: 1.7; }
.detail-link { display: flex; width: calc(100% - 26px); justify-content: space-between; margin: 14px 13px 13px; padding: 11px 10px; border: 0; border-top: 1px solid #e8edf3; color: #2563eb; background: #fff; cursor: pointer; text-align: left; font: 600 13px var(--font-sans, sans-serif); }
.history-empty { padding: 17px; color: #94a3b8; font-size: 13px; line-height: 1.7; }
.history-item { display: flex; width: 100%; align-items: flex-start; gap: 9px; padding: 12px 15px; border: 0; border-bottom: 1px solid #f1f5f9; color: inherit; background: #fff; cursor: pointer; text-align: left; }
.history-item:hover,.history-item.selected { background: #f8fbff; }
.history-item.selected { box-shadow: inset 3px 0 #3b82f6; }
.history-status { display: grid; width: 18px; height: 18px; flex: 0 0 auto; place-items: center; margin-top: 2px; color: #94a3b8; }
.history-status.status-done { color: #16a34a; }
.history-status.status-running,.history-status.status-queued { color: #2563eb; }
.history-status.status-error,.history-status.status-abandoned { color: #dc2626; }
.history-status.status-interrupted { color: #d97706; }
.history-copy { display: grid; min-width: 0; flex: 1; gap: 4px; }
.history-copy strong { overflow: hidden; color: #334155; font-size: 13px; font-weight: 550; text-overflow: ellipsis; white-space: nowrap; }
.history-copy small { color: #94a3b8; font-size: 11px; }
.history-chevron { color: #94a3b8; font-size: 20px; line-height: 17px; }
.refresh-history { width: 100%; padding: 11px; border: 0; color: #2563eb; background: #fff; cursor: pointer; font: 600 12px var(--font-sans, sans-serif); }
.state-panel { display: flex; min-height: 180px; align-items: center; justify-content: space-between; gap: 22px; padding: 26px; color: #64748b; font-size: 15px; }
.error-panel h1 { margin: 0 0 6px; color: #0f172a; font-size: 21px; }
.error-panel p { margin: 0; line-height: 1.7; }
.loader-ring { display: inline-block; width: 18px; height: 18px; margin-right: 10px; border: 2px solid #dbeafe; border-top-color: #3b82f6; border-radius: 50%; vertical-align: -4px; animation: orbit .8s linear infinite; }
.primary-button { padding: 9px 13px; border: 1px solid #2563eb; border-radius: 7px; color: #fff; background: #3b82f6; cursor: pointer; font: 600 13px var(--font-sans, sans-serif); }
@media (prefers-reduced-motion: reduce) { *,*::before,*::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
@media (max-width: 1000px) { .analysis-grid { grid-template-columns: minmax(0, 1fr) 285px; } }
@media (max-width: 760px) {
  .analysis-page { padding: 16px 16px 30px; }
  .analysis-header { grid-template-columns: 1fr; gap: 5px; }
  .header-copy { padding: 15px 2px; }
  .analysis-grid { grid-template-columns: 1fr; }
  .evidence-column { grid-template-columns: 1fr; }
  .control-row { flex-direction: column; }
  .start-button { min-height: 44px; }
  .result-panel { min-height: 420px; }
}
@media (max-width: 520px) {
  .analysis-page { padding: 12px 10px 24px; }
  .page-toolbar { align-items: flex-start; flex-direction: column; gap: 8px; margin-bottom: 15px; }
  .breadcrumb { padding-left: 3px; font-size: 12px; }
  .source-record { padding: 17px; }
  .analysis-controls { padding: 14px; }
  .result-heading { align-items: flex-start; padding: 16px; }
  .analysis-content { padding: 19px 17px; font-size: 15px; }
  .thinking-state { align-items: flex-start; justify-content: flex-start; min-height: 260px; padding: 25px 18px; }
  .state-panel { align-items: flex-start; flex-direction: column; }
}
</style>
