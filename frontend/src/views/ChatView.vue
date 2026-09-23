<!--
对话工作台：左侧历史对话侧栏 + 中栏执行流水线 + 右栏 SSE 流式对话
重构后：布局编排 + 员工/会话管理，渲染委托给子组件
-->
<template>
  <div class="chat-layout" :class="{ 'full-width-mode': fullWidthMode }">
    <button
      v-if="historyOpen || executionOpen"
      class="drawer-backdrop"
      aria-label="关闭侧栏"
      @click="closeDrawers"
    ></button>
    <ConversationSidebar
      :list="convList"
      :active-id="convId"
      :emp-names="empNames"
      :open="historyOpen"
      :query="historyQuery"
      :archived-only="historyArchived"
      :loading="historyLoading"
      :has-more="historyHasMore"
      :error="historyError"
      @select="openConversation"
      @new="newConv"
      @close="historyOpen = false"
      @search="onHistorySearch"
      @archive-filter="onArchiveFilter"
      @load-more="loadMoreHistory"
      @retry-load="() => loadHistory(currentEmp)"
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

    <div class="chat-main">
      <div class="chat-header">
        <n-button
          quaternary
          circle
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
          :value="currentEmp"
          :options="empOptions"
          size="small"
          class="employee-select"
          @update:value="selectEmployee"
        />
        <n-select
          v-if="aiModels.length"
          :value="currentModel"
          :options="modelOptions"
          size="small"
          placeholder="选择模型"
          class="model-select"
          @update:value="(v) => currentModel = v"
        />
        <span class="emp-meta">{{ empMeta }}</span>
        <n-button quaternary class="execution-button" :aria-expanded="executionOpen" @click="toggleDrawer('execution')">执行详情</n-button>
        <n-button size="small" class="trace-button" @click="openTrace">完整 Trace</n-button>
        <n-button
          quaternary
          circle
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
      </div>

      <div class="msgs" ref="msgsRef">
        <div class="message-lane">
        <ChatMessage
          v-for="(msg, idx) in messages" :key="idx"
          :msg="msg"
          :idx="idx"
          @rate="submitRating"
          @approve="(id, midx) => decide(id, 'approve', midx)"
          @reject="(id, midx) => decide(id, 'reject', midx)"
          @retry="retryMessage"
        />
        </div>
      </div>

      <InputBar
        :disabled="stream.sending.value"
        :sending="stream.sending.value"
        :uploading="uploading"
        :full-width="fullWidthMode"
        :hint="hint"
        @send="onSend"
        @stop="stream.stopActiveStream"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api.js'
import { useChatStream } from '../composables/useChatStream.js'
import ConversationSidebar from '../components/chat/ConversationSidebar.vue'
import PipelineSidebar from '../components/chat/PipelineSidebar.vue'
import ChatMessage from '../components/chat/ChatMessage.vue'
import InputBar from '../components/chat/InputBar.vue'
import { isCustomEmployee, routeNameForEmployee } from '../utils/employeeRoutes.js'

defineOptions({ name: 'ChatView' })
const router = useRouter()
const route = useRoute()
const message = useMessage()

/* ---------- 基础状态 ---------- */
const employees = ref([])
const empNames = reactive({})
const currentEmp = ref(null)
const convId = ref(null)
const persistedConvId = ref(null)
const routeReady = ref(false)
const convList = ref([])
const historyQuery = ref('')
const historyArchived = ref(false)
const historyLoading = ref(false)
const historyError = ref('')
const historyPage = ref(0)
const historyTotal = ref(0)
const HISTORY_PAGE_SIZE = 20
const historyHasMore = computed(() => historyPage.value * HISTORY_PAGE_SIZE < historyTotal.value)
let historyRequestSeq = 0
let historySearchTimer = null
const messages = ref([])
const empMeta = ref('')
const hint = ref('向数字员工提问吧。')
const msgsRef = ref(null)
const stageStates = reactive({})
const stageDetail = reactive({})
const historyOpen = ref(false)
const executionOpen = ref(false)
const fullWidthMode = ref(false)
try {
  fullWidthMode.value = localStorage.getItem('uniemployee-chat-width-mode') === 'full'
} catch {}

function toggleWidthMode() {
  fullWidthMode.value = !fullWidthMode.value
  try {
    localStorage.setItem('uniemployee-chat-width-mode', fullWidthMode.value ? 'full' : 'standard')
  } catch {}
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

/* ---------- 模型选择 ---------- */
const aiModels = ref([])
const currentModel = ref('')  // base_model 名
const modelOptions = computed(() =>
  aiModels.value.map(m => ({ label: m.name, value: m.base_model }))
)

const HINTS = {
  xiaosu: '试试：\n① X1音箱续航多久？买一个多少钱？\n② 查一下订单O12345\n③ 音箱坏了不出声了，我要投诉！\n④ O12345我想退款\n⑤ 记住我姓张，回复要通俗一点\n⑥ 查一下张总的会员等级\n⑦ S2台灯和S2 Pro有什么区别？',
  'market-intel': '试试：\n① 最近有什么值得关注的行业动态？出一份今日简报\n② 声湃科技把 Mini3 降到 299 了，出个对标分析\n③ 刷到消息说光屿智能融资了 3 个亿，要不要紧？\n④ 简报好了，归档发布（走人工审批）',
}

// 编排型对话页只展示 kind==='composed' 的员工；定制型员工有专属对话页，
// 不应在本页可被选择（否则会丢失定制上下文如数据源/SQL 工具注入）。
const empOptions = computed(() =>
  employees.value
    .filter(e => !isCustomEmployee(e))
    .map(e => ({ label: e.role || e.name, value: e.id }))
)

function scrollToBottom() {
  nextTick(() => {
    if (msgsRef.value) msgsRef.value.scrollTop = msgsRef.value.scrollHeight
  })
}

/* ---------- SSE 流 ---------- */
const stream = useChatStream({ stageStates, stageDetail, messages, scrollToBottom })

async function setChatUrl(query, replace = false) {
  const target = { name: 'chat', query }
  if (router.resolve(target).fullPath !== route.fullPath) {
    await router[replace ? 'replace' : 'push'](target)
  }
}

function markConversationPersisted(cid) {
  if (convId.value !== cid || route.name !== 'chat') return
  persistedConvId.value = cid
  // 新会话在第一条消息被服务端接收后才落库，此时地址才可以用于刷新恢复。
  void setChatUrl({ conv: cid }, true)
}

/* ---------- 发送 / 审批 ---------- */
const uploading = ref(false)

async function onSend(text, files = [], onAccepted = () => {}) {
  if (!convId.value) return
  const targetConvId = convId.value
  let attachments = []
  if (files.length) {
    uploading.value = true
    try {
      for (const f of files) {
        const form = new FormData()
        form.append('file', f)
        const { data } = await api.post(`/conversations/${targetConvId}/attachments`, form)
        if (data.error) {
          messages.value.push({ role: 'bot', content: '⚠ 附件「' + f.name + '」上传失败：' + data.error, html: '', time: fmtNow() })
        } else {
          attachments.push(data)
        }
      }
    } catch (e) {
      messages.value.push({ role: 'bot', content: '⚠ 附件上传失败：' + (e.response?.data?.detail || e.message), html: '', time: fmtNow() })
    }
    uploading.value = false
    if (!attachments.length) return
  }
  await stream.sendTo(`/api/conversations/${targetConvId}/messages`, text, attachments, null, currentModel.value, {
    onAccepted: () => {
      onAccepted()
      markConversationPersisted(targetConvId)
    },
  })
  await loadHistory(currentEmp.value)
}

async function retryMessage(msg) {
  const request = msg?._retryPayload
  if (!request || stream.sending.value) return
  const failedIndex = messages.value.indexOf(msg)
  if (failedIndex >= 0) messages.value.splice(failedIndex, 1)
  const targetConvId = convId.value
  await stream.sendTo(request.endpoint, request.text, request.attachments, request.dataSource, request.model, {
    appendUser: false,
    onAccepted: () => markConversationPersisted(targetConvId),
  })
  await loadHistory(currentEmp.value)
}

async function decide(approvalId, decision, msgIdx) {
  await stream.decide(approvalId, decision, msgIdx)
  await loadHistory(currentEmp.value)
}

/* ---------- 评价 ---------- */
async function submitRating(msg, rating, idx, reason = '') {
  if (msg._evaluated) return
  msg._evaluated = rating
  messages.value = [...messages.value]
  try {
    await api.post('/me/evaluations', {
      run_id: msg.run_id || '',
      message_id: msg.message_id || '',
      employee_id: msg.employee_id || currentEmp.value || '',
      conversation_id: msg.conversation_id || convId.value || '',
      rating,
      reason,
    })
  } catch {}
}

/* ---------- 历史会话 ---------- */
async function loadHistory(empId = currentEmp.value, append = false) {
  if (!empId || (append && historyLoading.value)) return
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
        employee_id: empId, page, page_size: HISTORY_PAGE_SIZE,
        q: historyQuery.value.trim(), archived: historyArchived.value,
      },
    })
    if (requestSeq !== historyRequestSeq) return
    const items = data.items || []
    if (append) {
      const knownIds = new Set(convList.value.map(item => item.conv_id))
      convList.value = [...convList.value, ...items.filter(item => !knownIds.has(item.conv_id))]
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
  historySearchTimer = setTimeout(() => loadHistory(currentEmp.value), 300)
}

function onArchiveFilter(value) {
  if (historyArchived.value === value) return
  historyArchived.value = value
  clearTimeout(historySearchTimer)
  loadHistory(currentEmp.value)
}

function loadMoreHistory() {
  if (historyHasMore.value) loadHistory(currentEmp.value, true)
}

async function updateConversationMeta(cid, changes) {
  try {
    await api.patch(`/conversations/${cid}`, changes)
    if (changes.archived === true && cid === convId.value) {
      await selectEmployee(currentEmp.value)
    } else {
      await loadHistory(currentEmp.value)
    }
    message.success(changes.title ? '会话已重命名' : changes.archived === true ? '会话已归档' : changes.archived === false ? '会话已移出归档' : changes.pinned ? '会话已置顶' : '已取消置顶')
  } catch (e) {
    message.error(e.response?.data?.detail || '会话操作失败，请稍后重试')
  }
}

async function openConversation(cid, { syncUrl = true, replaceUrl = false } = {}) {
  if (stream.sending.value) {
    message.warning('请先停止当前生成，再切换会话')
    return false
  }
  try {
    const { data } = await api.get(`/conversations/${cid}`)
    if (!syncUrl && route.query.conv !== cid) return false
    if (data.error) { message.error(data.error); return false }
    // 会话属于定制型员工时，重定向到该员工的专属对话路由，避免丢失定制上下文
    const targetRoute = routeNameForEmployee(data.employee_id)
    if (targetRoute !== 'chat') {
      await router.replace({ name: targetRoute, query: { conv: cid } })
      return true
    }
    convId.value = cid
    persistedConvId.value = cid
    currentEmp.value = data.employee_id
    hint.value = HINTS[data.employee_id] || '向数字员工提问吧。'
    // 恢复会话绑定的模型；未绑定时用列表中的默认模型
    currentModel.value = data.model || defaultModelBase()
    // 产物文件按归属轮次（turn_no）挂到生成它的那条回答消息上；
    // 无轮次信息的旧数据挂到最后一 条回答。实时生成走 file 事件直接进 msg.files。
    const filesByTurn = {}
    for (const f of (data.files || [])) {
      const t = f.turn_no || 0
      ;(filesByTurn[t] = filesByTurn[t] || []).push(f)
    }
    messages.value = []
    stream.resetPipeline()
    let userTurn = 0
    let lastBot = null
    const turnLastBot = {}
    for (const t of (data.turns || [])) {
      if (t.role === 'user') {
        userTurn++
        messages.value.push({ role: 'user', content: t.content, time: fmtNow() })
      } else {
        // 历史消息同样抽取 REPORT_HTML 包裹的看板/报告（与流式 useChatStream 行为一致），
        // markdown 渲染的是去掉报告段后的剩余文本
        const { reportHtml, cleanedMd } = extractReport(t.content || '')
        const msg = { role: 'bot', content: '', html: renderMd(cleanedMd), _md: t.content || '', trace: [], time: fmtNow() }
        if (reportHtml) msg.reportHtml = reportHtml
        if (t.tool_calls && t.tool_calls.length) {
          msg.trace = t.tool_calls.map(tc => ({
            type: 'tool',
            name: tc.name || '',
            args: tc.args && Object.keys(tc.args).length ? JSON.stringify(tc.args) : '',
            status: 'done',
            preview: tc.result || '',
          }))
        }
        messages.value.push(msg)
        lastBot = msg
        turnLastBot[userTurn] = msg
      }
    }
    for (const group of Object.values(filesByTurn)) {
      for (const f of group) {
        const target = turnLastBot[f.turn_no] || lastBot
        if (target) {
          if (!target.files) target.files = []
          if (!target.files.some(x => x.path === f.path)) target.files.push(f)
        }
      }
    }
    await loadHistory(data.employee_id)
    scrollToBottom()
    closeDrawers()
    if (syncUrl) await setChatUrl({ conv: cid }, replaceUrl)
    return true
  } catch (e) {
    message.error(e.response?.data?.detail || '会话加载失败')
    return false
  }
}

/* ---------- 员工切换 ---------- */
async function selectEmployee(empId, { syncUrl = true, replaceUrl = false } = {}) {
  if (stream.sending.value) {
    message.warning('请先停止当前生成，再切换员工')
    return false
  }
  historyQuery.value = ''
  historyArchived.value = false
  clearTimeout(historySearchTimer)
  const requestedRoute = route.fullPath
  let newId
  try {
    const { data } = await api.post(`/employees/${empId}/conversations`)
    newId = data.conversation_id
  } catch (e) {
    message.error(e.response?.data?.detail || '新建会话失败')
    return false
  }
  if (!syncUrl && route.fullPath !== requestedRoute) return false
  currentEmp.value = empId
  hint.value = HINTS[empId] || '向数字员工提问吧。'
  // 切换员工时重置为默认模型
  currentModel.value = defaultModelBase()
  convId.value = newId
  persistedConvId.value = null
  messages.value = []
  stream.resetPipeline()
  empMeta.value = '已切换到该员工（记忆跨会话保留）'
  await loadHistory(empId)
  if (syncUrl) await setChatUrl({ emp: empId }, replaceUrl)
  return true
}

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

async function newConv() {
  if (currentEmp.value) {
    await selectEmployee(currentEmp.value)
    closeDrawers()
  }
}

function openTrace() {
  if (convId.value) {
    const url = router.resolve({ name: 'trace', query: { conv: convId.value } }).href
    window.open(url, '_blank')
  }
}

function fmtNow() {
  const d = new Date()
  return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`
}

import { renderMd, extractReport } from '../composables/useChatStream.js'

/* ---------- 初始化 ---------- */
onMounted(async () => {
  try {
    await loadAiModels()
    const { data } = await api.get('/employees')
    employees.value = data
    data.forEach(e => { empNames[e.id] = e.name })
    const qconv = route.query.conv
    if (qconv) {
      // 先尝试打开指定会话；若该会话属于定制型员工，openConversation 会重定向到对应路由
      const opened = await openConversation(qconv, { syncUrl: false })
      // 会话存在且属编排型才加载该员工历史；否则回退选第一个员工
      if (!opened && empOptions.value.length) await selectEmployee(empOptions.value[0].value, { replaceUrl: true })
    } else if (data.length) {
      // ?emp= 指定要打开的编排型员工（首页员工卡片入口）；无效或定制型时回退第一个
      const target = route.query.emp && data.find(e => e.id === route.query.emp && !isCustomEmployee(e))
      await selectEmployee(target ? target.id : (empOptions.value[0]?.value || data[0].id), { replaceUrl: true })
    }
  } catch (e) {
    empMeta.value = '员工列表加载失败：' + e.message
  } finally {
    routeReady.value = true
  }
})

watch(() => [route.query.conv, route.query.emp], async ([cid, emp]) => {
  if (!routeReady.value) return
  if (typeof cid === 'string' && cid) {
    if (cid !== persistedConvId.value) {
      const opened = await openConversation(cid, { syncUrl: false })
      if (!opened && route.query.conv === cid) {
        await setChatUrl(persistedConvId.value ? { conv: persistedConvId.value } : { emp: currentEmp.value }, true)
      }
    }
    return
  }
  const targetEmp = typeof emp === 'string' && empOptions.value.some(e => e.value === emp)
    ? emp : (empOptions.value[0]?.value || null)
  if (targetEmp && (persistedConvId.value || currentEmp.value !== targetEmp)) {
    const requestedRoute = route.fullPath
    const created = await selectEmployee(targetEmp, { syncUrl: false })
    if (!created && route.fullPath === requestedRoute) {
      await setChatUrl(persistedConvId.value ? { conv: persistedConvId.value } : { emp: currentEmp.value }, true)
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
.chat-layout {
  position: relative;
  display: flex;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.chat-header {
  min-height: 58px;
  padding: 8px 20px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #ffffff;
}
.chat-header :deep(svg) { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; }
.employee-select { width: 220px; flex: 0 0 auto; }
.new-conversation-button { flex: 0 0 auto; }
.model-select { width: 170px; flex: 0 0 auto; }
.emp-meta { font-size: 12px; color: #64748b; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msgs { flex: 1; overflow-y: auto; padding: 28px clamp(24px, 4vw, 72px) 18px; min-height: 0; }
.message-lane { width: min(100%, 1080px); margin: 0 auto; display: flex; flex-direction: column; gap: 10px; }
.chat-layout.full-width-mode .message-lane { width: 100%; max-width: none; }
.drawer-backdrop { position: absolute; inset: 0; z-index: 30; border: 0; background: rgba(15, 23, 42, 0.2); cursor: default; }

@media (max-width: 900px) {
  .chat-header { padding: 8px 12px; gap: 8px; }
  .employee-select { width: 190px; }
  .model-select { width: 140px; }
  .msgs { padding: 20px 18px 14px; }
  .emp-meta { display: none; }
}

@media (max-width: 640px) {
  .chat-header { min-height: 54px; }
  .new-conversation-button { width: 34px; padding: 0; }
  .new-conversation-button span { display: none; }
  .employee-select { flex: 1 1 auto; width: auto; min-width: 0; }
  .model-select, .execution-button, .trace-button, .layout-mode-button { display: none; }
  .chat-header > :deep(.n-button) { flex-shrink: 0; }
  .msgs { padding: 16px 12px 10px; }
  .message-lane { gap: 8px; }
}
</style>
