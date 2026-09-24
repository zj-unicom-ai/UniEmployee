<!--
数据分析 · 对话问数主页面
布局与通用对话工作台保持一致，保留数据源、模型和表格问答能力
复用 useChatStream SSE 流及通用历史侧栏、执行详情面板
-->
<template>
  <div class="analyst-layout" :class="{ 'full-width-mode': fullWidthMode }">
    <button
      v-if="historyOpen || executionOpen"
      class="drawer-backdrop"
      type="button"
      aria-label="关闭侧栏"
      @click="closeDrawers"
    ></button>
    <ConversationSidebar
      :list="convList"
      :active-id="convId"
      :emp-names="employeeNames"
      :open="historyOpen"
      :query="historyQuery"
      :archived-only="historyArchived"
      :loading="historyLoading"
      :has-more="historyHasMore"
      :error="historyError"
      @select="openConversation"
      @close="historyOpen = false"
      @search="onHistorySearch"
      @archive-filter="onArchiveFilter"
      @load-more="loadMoreHistory"
      @retry-load="loadHistory()"
      @rename="(id, title) => updateConversationMeta(id, { title })"
      @pin="(id, pinned) => updateConversationMeta(id, { pinned })"
      @archive="(id, archived) => updateConversationMeta(id, { archived })"
    />
    <PipelineSidebar
      :states="stageStates"
      :detail="stageDetail"
      :open="executionOpen"
      @close="executionOpen = false"
    />

    <main class="center-panel">
      <header class="chat-header">
        <n-button
          quaternary circle
          aria-label="打开历史会话"
          title="历史会话"
          :aria-expanded="historyOpen"
          @click="toggleDrawer('history')"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16M4 12h16M4 19h10" /></svg>
        </n-button>
        <n-button
          size="small"
          class="new-conversation-button"
          :disabled="stream.sending.value || uploading"
          aria-label="新对话"
          title="新对话"
          @click="newConv"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
          <span>新对话</span>
        </n-button>
        <n-select
          v-model:value="datasourceId"
          :options="dsOptions"
          size="small"
          class="datasource-select"
          placeholder="选择数据源"
          aria-label="分析数据源"
        />
        <n-select
          v-if="aiModels.length"
          :value="currentModel"
          :options="modelOptions"
          size="small"
          class="model-select"
          placeholder="选择模型"
          aria-label="选择模型"
          @update:value="(v) => currentModel = v"
        />
        <span v-if="datasourceName" class="datasource-context" :title="datasourceName">
          数据源 · {{ datasourceName }}
        </span>
        <div class="header-actions">
          <n-button quaternary class="execution-button" :aria-expanded="executionOpen" @click="toggleDrawer('execution')">
            执行详情
          </n-button>
          <n-button size="small" class="trace-button" @click="openTrace">完整 Trace</n-button>
          <n-button
            quaternary circle
            class="layout-mode-button"
            :aria-pressed="fullWidthMode"
            :aria-label="fullWidthMode ? '切换到标准宽度模式' : '切换到全屏宽度模式'"
            :title="fullWidthMode ? '切换到标准宽度' : '切换到全屏宽度'"
            @click="toggleWidthMode"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path v-if="!fullWidthMode" d="M4 9V4h5M4 4l6 6M20 15v5h-5M20 20l-6-6M15 4h5v5M20 4l-6 6M9 20H4v-5M4 20l6-6" />
              <path v-else d="M9 3v6H3M3 9l7-7M15 21v-6h6M21 15l-7 7M21 9h-6V3M15 3l7 7M3 15h6v6M9 21l-7-7" />
            </svg>
          </n-button>
          <n-button size="small" text class="data-config-button" @click="$router.push({ name: 'analyst-datasources' })">
            数据配置
          </n-button>
        </div>
      </header>

      <section class="msgs" ref="msgsRef" aria-label="数据分析对话">
        <div class="message-lane">
          <section v-if="!messages.length" class="welcome-box" aria-label="小数快捷问题">
            <div class="welcome-hero">
              <div class="hero-avatar">数</div>
              <div class="hero-text">
                <div class="hero-eyebrow">DATA ANALYST · 小数</div>
                <h1 class="hero-title">从数据开始，找到下一步</h1>
                <p class="hero-sub">
                  {{ datasourceName ? `当前数据源「${datasourceName}」，选择一个问题开始分析` : '选择一个问题开始分析，也可以先选数据源或上传表格' }}
                </p>
              </div>
            </div>
            <div v-if="quickPrompts.length" class="prompt-grid">
              <button
                v-for="(ex, i) in quickPrompts"
                :key="ex.id || i"
                type="button"
                class="prompt-card"
                :disabled="stream.sending.value || uploading"
                @click="usePrompt(ex)"
              >
                <span class="prompt-index">{{ String(i + 1).padStart(2, '0') }}</span>
                <span class="prompt-body">
                  <span class="prompt-q">{{ ex.question }}</span>
                  <span v-if="ex.description" class="prompt-desc">{{ ex.description }}</span>
                </span>
                <span class="prompt-cta" aria-hidden="true">↗</span>
              </button>
            </div>
          </section>

          <template v-for="(msg, idx) in messages" :key="idx">
            <ChatMessage :msg="msg" :idx="idx" />
            <SqlViewer v-if="msg.sql" :sql="msg.sql" class="sql-viewer" />
          </template>
        </div>
      </section>

      <footer class="input-bar" :class="{ 'drop-active': dropActive }"
              @dragover.prevent="dropActive = true" @dragenter.prevent="dropActive = true"
              @dragleave="onDragLeave" @drop.prevent="onDrop" @paste="onPaste">
        <div v-if="dropActive" class="drop-hint">松开即可添加表格</div>
        <div v-if="pendingFiles.length" class="att-chips">
          <span v-for="(f, i) in pendingFiles" :key="`${f.name}-${f.lastModified}`" class="att-chip" :title="f.name">
            <span aria-hidden="true">▤</span>
            <span class="chip-name">{{ f.name }}</span>
            <span class="chip-size">{{ fmtSize(f.size) }}</span>
            <button type="button" class="chip-remove" :disabled="uploading || stream.sending.value"
                    :aria-label="`移除附件 ${f.name}`" @click="pendingFiles.splice(i, 1)">×</button>
          </span>
        </div>
        <div class="input-row">
          <button
            class="attach-button"
            type="button"
            :disabled="uploading || stream.sending.value"
            title="上传 CSV / Excel 表格"
            aria-label="上传 CSV 或 Excel 表格"
            @click="fileInputRef?.click()"
          >
            <svg v-if="!uploading" viewBox="0 0 24 24" aria-hidden="true"><path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l8.6-8.6a4 4 0 0 1 5.7 5.7l-8.6 8.6a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg>
            <span v-else class="btn-spinner"></span>
          </button>
          <input ref="fileInputRef" type="file" hidden multiple accept=".csv,.xlsx,.xls" @change="onFilePick" />
          <n-input
            v-model:value="inputText"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 6 }"
            size="small"
            placeholder="向小数提问；支持粘贴或拖入 CSV / Excel 表格"
            :disabled="stream.sending.value || uploading"
            :input-props="{ 'aria-label': '输入数据分析问题' }"
            @keydown.enter="onEnter"
          />
          <n-button
            v-if="stream.sending.value"
            type="error"
            class="send-button stop-button"
            aria-label="停止生成"
            @click="stream.stopActiveStream"
          >停止</n-button>
          <n-button
            v-else
            type="primary"
            class="send-button"
            :disabled="(!inputText.trim() && !pendingFiles.length) || (!datasourceId && !pendingFiles.length) || uploading"
            :loading="uploading"
            @click="onSend"
          >{{ uploading ? '上传中' : '发送' }}</n-button>
        </div>
        <div class="input-footer">Enter 发送 · Shift+Enter 换行 · 支持拖入或粘贴表格</div>
      </footer>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../../../api.js'
import { DEFAULT_QUICK_PROMPTS } from '../../../utils/quickPrompts.js'
import * as analystApi from '../../../api/analyst.js'
import { useChatStream, renderMd, extractReport } from '../../../composables/useChatStream.js'
import ChatMessage from '../../../components/chat/ChatMessage.vue'
import SqlViewer from '../../../components/agent/analyst/SqlViewer.vue'
import ConversationSidebar from '../../../components/chat/ConversationSidebar.vue'
import PipelineSidebar from '../../../components/chat/PipelineSidebar.vue'

defineOptions({ name: 'AnalystView' })
const message = useMessage()
const route = useRoute()
const router = useRouter()

const datasourceId = ref(null)
const datasources = ref([])
const employeeNames = { xiaoshu: '小数' }
const historyQuery = ref('')
const historyArchived = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const historyPage = ref(0)
const historyTotal = ref(0)
const HISTORY_PAGE_SIZE = 20
const historyHasMore = computed(() => historyPage.value * HISTORY_PAGE_SIZE < historyTotal.value)
const historyOpen = ref(false)
const executionOpen = ref(false)
const fullWidthMode = ref(false)
try { fullWidthMode.value = localStorage.getItem('uniemployee-chat-width-mode') === 'full' } catch {}
let historyRequestSeq = 0
let historySearchTimer = null
// 模型选择
const aiModels = ref([])
const currentModel = ref('')
const modelOptions = computed(() =>
  aiModels.value.map(m => ({ label: m.name, value: m.base_model }))
)
function defaultModelBase() {
  const d = aiModels.value.find(m => m.default_model)
  return d ? d.base_model : (aiModels.value[0]?.base_model || '')
}
async function loadAiModels() {
  try {
    const { data } = await api.get('/ai-models')
    aiModels.value = Array.isArray(data) ? data : []
  } catch {}
}
const dsOptions = computed(() =>
  datasources.value.map(d => ({
    label: `[${d.kind === 'database' ? '库' : d.kind === 'knowledge_base' ? '知' : '连'}] ${d.name}${d.kind === 'database' && d.is_public ? ' · 公共' : ''}`,
    value: d.id,
  }))
)
const datasourceName = computed(() =>
  datasources.value.find(d => d.id === datasourceId.value)?.name || ''
)
// 当前选中的数据源对象（{kind, id}），传给 useChatStream.sendTo
const currentDataSource = computed(() => {
  const ds = datasources.value.find(d => d.id === datasourceId.value)
  if (!ds) return null
  return { kind: ds.kind, id: ds.id }
})

// 优先展示员工专属配置；未配置时显示平台默认的两条欢迎话术。
const quickPrompts = ref(DEFAULT_QUICK_PROMPTS.map((question, id) => ({ id: `default-${id}`, question })))
const employeeQuickPrompts = ref([])
let employeePromptsLoaded = false

async function loadEmployeeQuickPrompts() {
  if (employeePromptsLoaded) return
  employeePromptsLoaded = true
  try {
    const { data } = await api.get('/employees')
    const employee = (Array.isArray(data) ? data : []).find(e => e.id === 'xiaoshu')
    employeeQuickPrompts.value = (employee?.quick_prompts || [])
      .filter(x => typeof x === 'string' && x.trim()).slice(0, 3)
  } catch {
    employeeQuickPrompts.value = []
  }
}

async function loadQuickPrompts() {
  await loadEmployeeQuickPrompts()
  if (employeeQuickPrompts.value.length) {
    quickPrompts.value = employeeQuickPrompts.value.map((question, id) => ({ id: `employee-${id}`, question }))
  } else {
    quickPrompts.value = DEFAULT_QUICK_PROMPTS.map((question, id) => ({ id: `default-${id}`, question }))
  }
}

// 点击快捷话术后直接开始分析。
function usePrompt(ex) {
  inputText.value = ex.question
  // 自动发送：直接调用 onSend
  onSend()
}

const convId = ref(null)
const persistedConvId = ref(null)
const routeReady = ref(false)
const convList = ref([])
const messages = ref([])
const inputText = ref('')
const msgsRef = ref(null)
const stageStates = reactive({})
const stageDetail = reactive({})
const dropActive = ref(false)

// 表格问答附件：选中的待上传文件（发送时先上传再随消息发出）
const pendingFiles = ref([])
const uploading = ref(false)
const fileInputRef = ref(null)

function toggleWidthMode() {
  fullWidthMode.value = !fullWidthMode.value
  try { localStorage.setItem('uniemployee-chat-width-mode', fullWidthMode.value ? 'full' : 'standard') } catch {}
}

function closeDrawers() {
  historyOpen.value = false
  executionOpen.value = false
}

function toggleDrawer(which) {
  const isOpen = which === 'history' ? historyOpen.value : executionOpen.value
  closeDrawers()
  if (!isOpen && which === 'history') historyOpen.value = true
  if (!isOpen && which === 'execution') executionOpen.value = true
}

function openTrace() {
  if (!convId.value) return
  const href = router.resolve({ name: 'trace', query: { conv: convId.value } }).href
  window.open(href, '_blank')
}

function onFilePick(e) {
  addFiles(Array.from(e.target.files || []))
  e.target.value = ''
}

function addFiles(files) {
  if (uploading.value || stream.sending.value) return
  for (const f of files) {
    if (!/\.(csv|xlsx|xls)$/i.test(f.name)) {
      message.warning('仅支持 csv/xlsx/xls 表格文件：' + f.name)
      continue
    }
    if (pendingFiles.value.length >= 5) {
      message.warning('单条消息最多 5 个附件')
      break
    }
    const duplicate = pendingFiles.value.some(x => x.name === f.name && x.size === f.size && x.lastModified === f.lastModified)
    if (!duplicate) pendingFiles.value.push(f)
  }
}

function onDrop(e) {
  dropActive.value = false
  addFiles(Array.from(e.dataTransfer?.files || []))
}

function onDragLeave(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) dropActive.value = false
}

function onPaste(e) {
  if (uploading.value || stream.sending.value) return
  const files = Array.from(e.clipboardData?.items || [])
    .filter(item => item.kind === 'file')
    .map(item => item.getAsFile())
    .filter(Boolean)
  if (files.length) {
    e.preventDefault()
    addFiles(files)
  }
}

function onEnter(e) {
  if (e.isComposing || e.keyCode === 229 || e.shiftKey) return
  e.preventDefault()
  onSend()
}

function fmtSize(n) {
  if (!n) return ''
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB'
  if (n >= 1024) return Math.round(n / 1024) + 'KB'
  return n + 'B'
}

const stream = useChatStream({ stageStates, stageDetail, messages, scrollToBottom })

async function setAnalystUrl(query, replace = false) {
  const target = { name: 'analyst', query }
  if (router.resolve(target).fullPath !== route.fullPath) {
    await router[replace ? 'replace' : 'push'](target)
  }
}

function markConversationPersisted(cid) {
  if (convId.value !== cid || route.name !== 'analyst') return
  persistedConvId.value = cid
  // 首条消息被服务端接收后，会话才可从地址栏恢复。
  void setAnalystUrl({ conv: cid }, true)
}

function scrollToBottom() {
  nextTick(() => {
    if (msgsRef.value) msgsRef.value.scrollTop = msgsRef.value.scrollHeight
  })
}

function formatTime(t) {
  if (!t) return ''
  return t.replace('T', ' ').slice(0, 16)
}

async function loadDatasources() {
  try {
    // 聚合加载三类数据源：数据库 / 知识库 / 连接器
    datasources.value = await analystApi.listAllDataSources()
    if (datasources.value.length && !datasourceId.value) {
      datasourceId.value = datasources.value[0].id
    }
  } catch (e) {
    message.error('加载数据源失败：' + (e.response?.data?.detail || e.message))
  }
}

async function loadHistory(append = false) {
  if (append && historyLoading.value) return
  const requestSeq = ++historyRequestSeq
  const page = append ? historyPage.value + 1 : 1
  if (!append) {
    convList.value = []
    historyTotal.value = 0
  }
  historyLoading.value = true
  historyError.value = ''
  try {
    const { data } = await api.get('/conversations', {
      params: {
        employee_id: 'xiaoshu', page, page_size: HISTORY_PAGE_SIZE,
        q: historyQuery.value.trim(), archived: historyArchived.value,
        exclude_auto: true,
      },
    })
    if (requestSeq !== historyRequestSeq) return
    const items = data.items || []
    if (append) {
      const known = new Set(convList.value.map(item => item.conv_id))
      convList.value = [...convList.value, ...items.filter(item => !known.has(item.conv_id))]
    } else {
      convList.value = items
    }
    historyPage.value = page
    historyTotal.value = data.total || 0
  } catch (e) {
    if (requestSeq === historyRequestSeq) historyError.value = e.response?.data?.detail || '会话加载失败'
  } finally {
    if (requestSeq === historyRequestSeq) historyLoading.value = false
  }
}

function onHistorySearch(value) {
  historyQuery.value = value || ''
  historyRequestSeq++
  clearTimeout(historySearchTimer)
  historyLoading.value = true
  historySearchTimer = setTimeout(() => loadHistory(), 300)
}

function onArchiveFilter(value) {
  if (historyArchived.value === value) return
  historyArchived.value = value
  clearTimeout(historySearchTimer)
  loadHistory()
}

function loadMoreHistory() {
  if (historyHasMore.value) loadHistory(true)
}

async function updateConversationMeta(cid, changes) {
  try {
    await api.patch(`/conversations/${cid}`, changes)
    if (changes.archived === true && cid === convId.value) {
      await newConv()
    } else {
      await loadHistory()
    }
    message.success(changes.title ? '会话已重命名' : changes.archived === true ? '会话已归档' : changes.archived === false ? '会话已移出归档' : changes.pinned ? '会话已置顶' : '已取消置顶')
  } catch (e) {
    message.error(e.response?.data?.detail || '会话操作失败，请稍后重试')
  }
}

async function newConv({ syncUrl = true, replaceUrl = false } = {}) {
  if (stream.sending.value) {
    message.warning('请先停止当前生成，再切换会话')
    return false
  }
  const requestedRoute = route.fullPath
  try {
    const data = await analystApi.createAnalystConversation()
    if (!syncUrl && route.fullPath !== requestedRoute) return false
    convId.value = data.conversation_id
    persistedConvId.value = null
    currentModel.value = defaultModelBase()
    messages.value = []
    inputText.value = ''
    pendingFiles.value = []
    stream.resetPipeline()
    closeDrawers()
    await loadHistory()
    if (syncUrl) await setAnalystUrl({}, replaceUrl)
    return true
  } catch (e) {
    message.error('创建会话失败：' + (e.response?.data?.detail || e.message))
    return false
  }
}

async function openConversation(cid, { syncUrl = true, replaceUrl = false } = {}) {
  if (stream.sending.value) {
    message.warning('请先停止当前生成，再切换会话')
    return false
  }
  try {
    const data = await analystApi.getAnalystConversation(cid)
    if (!syncUrl && route.query.conv !== cid) return false
    if (data.error) { message.error(data.error); return false }
    if (data.employee_id !== 'xiaoshu') {
      await router.replace({ name: 'chat', query: { conv: cid } })
      return true
    }
    convId.value = cid
    persistedConvId.value = cid
    currentModel.value = data.model || defaultModelBase()
    messages.value = []
    inputText.value = ''
    pendingFiles.value = []
    stream.resetPipeline()
    let userTurn = 0
    const turnLastBot = {}
    let lastBot = null
    for (const t of (data.turns || [])) {
      if (t.role === 'user') {
        userTurn++
        messages.value.push({ role: 'user', content: t.content, time: formatTime(t.created_at) })
      } else {
        // 历史回放：同样从文本中抽出报告 HTML 段（若有）
        const { reportHtml, cleanedMd } = extractReport(t.content || '')
        const msg = {
          role: 'bot', content: '', html: renderMd(cleanedMd),
          _md: t.content || '', trace: [], time: formatTime(t.created_at),
        }
        if (reportHtml) msg.reportHtml = reportHtml
        if (t.tool_calls && t.tool_calls.length) {
          msg.trace = t.tool_calls.map(tc => ({
            type: 'tool', name: tc.name || '',
            args: tc.args && Object.keys(tc.args).length ? JSON.stringify(tc.args) : '',
            status: 'done', preview: tc.result || '',
          }))
        }
        messages.value.push(msg)
        lastBot = msg
        turnLastBot[userTurn] = msg
      }
    }
    for (const file of (data.files || [])) {
      const target = turnLastBot[file.turn_no] || lastBot
      if (target) {
        if (!target.files) target.files = []
        if (!target.files.some(item => item.path === file.path)) target.files.push(file)
      }
    }
    scrollToBottom()
    closeDrawers()
    await loadHistory()
    if (syncUrl) await setAnalystUrl({ conv: cid }, replaceUrl)
    return true
  } catch (e) {
    message.error('会话加载失败：' + (e.response?.data?.detail || e.message))
    return false
  }
}

async function onSend() {
  const text = inputText.value.trim()
  if (!text && !pendingFiles.value.length) return
  // 纯表格问答（只带附件）不强制选数据源；数据库问数仍需数据源
  if (!datasourceId.value && !pendingFiles.value.length) {
    message.warning('请先选择数据源')
    return
  }
  if (!convId.value) {
    await newConv()
    if (!convId.value) return
  }
  const targetConvId = convId.value
  // 先上传表格附件（.csv/.xlsx/.xls），后端发送消息时自动注册为 DuckDB 表
  let attachments = []
  if (pendingFiles.value.length) {
    uploading.value = true
    try {
      for (const f of pendingFiles.value) {
        const form = new FormData()
        form.append('file', f)
        const { data } = await api.post(`/conversations/${targetConvId}/attachments`, form)
        if (data.error) {
          message.error('附件「' + f.name + '」上传失败：' + data.error)
        } else {
          attachments.push(data)
        }
      }
    } catch (e) {
      message.error('附件上传失败：' + (e.response?.data?.detail || e.message))
    }
    uploading.value = false
    pendingFiles.value = []
    if (!attachments.length) return
  }
  // 把 data_source={kind,id} 作为 query param 传到后端，由 streaming.py
  // 按 kind 注入到对应工具的 contextvar（database→sql_db_* / knowledge_base→kb_search / connector→MCP）。
  await stream.sendTo(
    `/api/conversations/${targetConvId}/messages`,
    text,
    attachments,
    currentDataSource.value,
    currentModel.value,
    { onAccepted: () => markConversationPersisted(targetConvId) },
  )
  inputText.value = ''
  await loadHistory()
}

onMounted(async () => {
  try {
    await loadAiModels()
    await loadDatasources()
    await loadHistory()
    // 优先从 URL ?conv=xxx 恢复指定会话（从会话历史页跳转过来时）
    const qconv = route.query.conv
    if (typeof qconv === 'string' && qconv) {
      const opened = await openConversation(qconv, { syncUrl: false })
      if (!opened && convList.value.length) await openConversation(convList.value[0].conv_id, { replaceUrl: true })
      else if (!opened) await newConv({ replaceUrl: true })
    } else if (convList.value.length) {
      await openConversation(convList.value[0].conv_id, { replaceUrl: true })
    } else {
      await newConv({ replaceUrl: true })
    }
    // 进入页面后加载员工专属快捷问法，未配置时保留默认欢迎话术
    await loadQuickPrompts()
  } finally {
    routeReady.value = true
  }
})

watch(() => route.query.conv, async (cid) => {
  if (!routeReady.value) return
  if (typeof cid === 'string' && cid) {
    if (cid !== persistedConvId.value) {
      const opened = await openConversation(cid, { syncUrl: false })
      if (!opened && route.query.conv === cid) {
        await setAnalystUrl(persistedConvId.value ? { conv: persistedConvId.value } : {}, true)
      }
    }
  } else if (persistedConvId.value) {
    const requestedRoute = route.fullPath
    const created = await newConv({ syncUrl: false })
    if (!created && route.fullPath === requestedRoute) {
      await setAnalystUrl({ conv: persistedConvId.value }, true)
    }
  }
})

onBeforeUnmount(() => {
  clearTimeout(historySearchTimer)
  historyRequestSeq++
  stream.abortActiveStream()
})
</script>

<style scoped>
.analyst-layout {
  position: relative;
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  color: #1c2540;
  background: #f7f8fc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.center-panel { display: flex; flex: 1; flex-direction: column; min-width: 0; min-height: 0; background: #fff; }
.chat-header {
  z-index: 2;
  display: flex;
  min-height: 58px;
  align-items: center;
  gap: 9px;
  padding: 8px 18px;
  border-bottom: 1px solid #e6e8f0;
  background: rgba(255, 255, 255, .96);
}
.chat-header :deep(svg) { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.new-conversation-button, .model-select, .datasource-select { flex: 0 0 auto; }
.datasource-select { width: 242px; }
.model-select { width: 160px; }
.datasource-context {
  min-width: 0;
  overflow: hidden;
  color: #74809b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.header-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 4px; margin-left: auto; }
.msgs { flex: 1; min-height: 0; overflow-y: auto; padding: 26px clamp(20px, 4vw, 68px) 18px; scroll-behavior: smooth; }
.message-lane { display: flex; width: min(100%, 1080px); min-height: 100%; flex-direction: column; gap: 10px; margin: 0 auto; }
.analyst-layout.full-width-mode .message-lane { width: 100%; max-width: none; }
.welcome-box { width: min(100%, 760px); margin: auto; padding: 18px 0 8vh; }
.welcome-hero { display: flex; align-items: center; gap: 16px; margin-bottom: 22px; }
.hero-avatar {
  display: grid;
  width: 54px;
  height: 54px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #e2ddff;
  border-radius: 18px 18px 18px 6px;
  background: linear-gradient(145deg, #f2efff, #e5ebff);
  color: #5c4dc4;
  font-size: 22px;
  font-weight: 700;
  box-shadow: inset 0 0 0 1px rgba(92, 77, 196, .04);
}
.hero-text { min-width: 0; }
.hero-eyebrow { margin-bottom: 6px; color: #776bbd; font-size: 10px; font-weight: 700; letter-spacing: .12em; }
.hero-title { margin: 0; color: #17213a; font-size: 21px; font-weight: 650; letter-spacing: -.025em; }
.hero-sub { margin: 7px 0 0; color: #79839a; font-size: 13px; line-height: 1.55; }
.prompt-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 10px; }
.prompt-card {
  position: relative;
  display: flex;
  min-height: 88px;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 15px;
  border: 1px solid #e8e9f1;
  border-radius: 12px;
  background: #fff;
  color: #34405b;
  cursor: pointer;
  text-align: left;
  transition: border-color .16s ease, background .16s ease, transform .16s ease, box-shadow .16s ease;
}
.prompt-card:hover:not(:disabled) { transform: translateY(-1px); border-color: #c9c2f2; background: #fdfcff; box-shadow: 0 8px 22px rgba(63, 55, 135, .07); }
.prompt-card:focus-visible, .attach-button:focus-visible, .chip-remove:focus-visible { outline: 2px solid #6758cc; outline-offset: 2px; }
.prompt-card:disabled { cursor: wait; opacity: .55; }
.prompt-index { display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center; border-radius: 8px; background: #f2f0ff; color: #6e61c9; font: 600 10px/1 ui-monospace, SFMono-Regular, Menlo, monospace; }
.prompt-body { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 5px; }
.prompt-q { display: -webkit-box; overflow: hidden; color: #2c3752; font-size: 13px; font-weight: 550; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.prompt-desc { display: -webkit-box; overflow: hidden; color: #8992a6; font-size: 11px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 1; }
.prompt-cta { align-self: center; color: #7a6fca; font-size: 18px; line-height: 1; }
.sql-viewer { margin: 2px 0 12px; }
.input-bar {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 12px max(24px, calc((100% - 1080px) / 2)) 9px;
  border-top: 1px solid #e6e8f0;
  background: #fff;
}
.analyst-layout.full-width-mode .input-bar { padding-right: clamp(24px, 4vw, 72px); padding-left: clamp(24px, 4vw, 72px); }
.input-bar.drop-active { outline: 2px dashed #9187df; outline-offset: -6px; background: #faf9ff; }
.drop-hint { position: absolute; z-index: 2; inset: 0; display: grid; place-items: center; background: rgba(248, 247, 255, .95); color: #6255be; font-size: 14px; font-weight: 600; pointer-events: none; }
.att-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.att-chip { display: inline-flex; max-width: 320px; align-items: center; gap: 7px; padding: 5px 8px; border: 1px solid #e5e5f0; border-radius: 8px; background: #fafaff; color: #59627a; font-size: 11px; }
.chip-name { overflow: hidden; max-width: 200px; text-overflow: ellipsis; white-space: nowrap; }
.chip-size { flex: 0 0 auto; color: #969cb0; font-size: 10px; }
.chip-remove { width: 19px; height: 19px; flex: 0 0 auto; border: 0; border-radius: 50%; background: transparent; color: #8b91a3; cursor: pointer; font-size: 16px; line-height: 1; }
.chip-remove:hover:not(:disabled) { background: #efedf9; color: #5d51b7; }
.input-row { display: flex; align-items: flex-end; gap: 9px; padding: 9px 10px; border: 1px solid #e2e4ec; border-radius: 14px; background: #fff; transition: border-color .16s ease, box-shadow .16s ease; }
.input-row:focus-within { border-color: #a49cde; box-shadow: 0 0 0 3px rgba(112, 99, 201, .09); }
.input-row :deep(.n-input) { flex: 1; min-width: 0; border: 0; background: transparent; box-shadow: none !important; }
.input-row :deep(.n-input__textarea-el) { padding: 4px 2px; color: #25304a; line-height: 1.6; }
.input-row :deep(.n-input__textarea-el::placeholder) { color: #a0a6b6; }
.attach-button { display: grid; width: 36px; height: 36px; flex: 0 0 auto; place-items: center; border: 0; border-radius: 9px; background: transparent; color: #7b8295; cursor: pointer; }
.attach-button:hover:not(:disabled) { background: #f4f2fc; color: #6558bf; }
.attach-button:disabled { cursor: wait; opacity: .55; }
.attach-button svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.send-button { min-width: 64px; height: 36px; flex: 0 0 auto; border-radius: 9px; }
.stop-button { min-width: 58px; }
.input-footer { padding: 0 4px; color: #9aa0af; font-size: 10px; text-align: center; }
.btn-spinner { width: 16px; height: 16px; border: 2px solid rgba(101, 88, 191, .22); border-top-color: #6558bf; border-radius: 50%; animation: analyst-spin .6s linear infinite; }
@keyframes analyst-spin { to { transform: rotate(360deg); } }
.drawer-backdrop { position: absolute; z-index: 30; inset: 0; border: 0; background: rgba(17, 24, 39, .22); cursor: default; }

@media (max-width: 1250px) {
  .chat-header { gap: 7px; padding-right: 12px; padding-left: 12px; }
  .datasource-context { display: none; }
  .datasource-select { width: 215px; }
  .model-select { width: 142px; }
}
@media (max-width: 900px) {
  .datasource-select { width: min(230px, 32vw); }
  .model-select { width: 128px; }
  .trace-button { display: none; }
  .msgs { padding: 20px 18px 14px; }
  .input-bar { padding-right: 20px; padding-left: 20px; }
}
@media (max-width: 640px) {
  .chat-header { min-height: 54px; gap: 6px; padding: 7px 9px; }
  .new-conversation-button { width: 34px; padding: 0; }
  .new-conversation-button span { display: none; }
  .datasource-select { width: auto; min-width: 0; flex: 1 1 auto; }
  .model-select, .execution-button, .trace-button, .layout-mode-button, .data-config-button { display: none; }
  .chat-header > :deep(.n-button) { flex-shrink: 0; }
  .msgs { padding: 15px 12px 10px; }
  .message-lane { gap: 8px; }
  .welcome-box { padding: 12px 2px 7vh; }
  .welcome-hero { gap: 12px; margin-bottom: 16px; }
  .hero-avatar { width: 46px; height: 46px; border-radius: 15px 15px 15px 5px; font-size: 19px; }
  .hero-title { font-size: 18px; }
  .hero-sub { font-size: 12px; }
  .prompt-grid { grid-template-columns: 1fr; gap: 8px; }
  .prompt-card { min-height: 70px; padding: 12px; }
  .input-bar, .analyst-layout.full-width-mode .input-bar { padding: 9px 10px 7px; }
  .input-row { gap: 5px; padding: 7px; }
  .send-button { min-width: 54px; }
  .input-footer { font-size: 9px; }
}
@media (prefers-reduced-motion: reduce) {
  .prompt-card, .input-row, .attach-button { transition: none; }
  .btn-spinner { animation-duration: 1.2s; }
}
</style>
