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
          v-if="!props.employeeId"
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
        <span v-if="isMarketIntelWorkspace" class="emp-meta market-intel-meta">行业深研 · 来源可追溯</span>
        <span v-else class="emp-meta">{{ empMeta }}</span>
        <n-button quaternary class="execution-button" :aria-expanded="executionOpen" @click="toggleDrawer('execution')">执行详情</n-button>
        <n-button size="small" class="trace-button" @click="openTrace">完整 Trace</n-button>
        <n-button v-if="currentEmp === 'net-ops'" size="small" :loading="exportingSecurity"
                  :disabled="!persistedConvId || stream.sending.value" @click="exportSecurityRecords">
          导出实操记录
        </n-button>
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
        <section v-if="!messages.length && isMarketIntelWorkspace && routeReady && !currentEmployee" class="market-research-unavailable" aria-live="polite">
          <h1>当前账号未分配小察</h1>
          <p>请联系管理员在用户管理中分配行业研究员工后再开始对话。</p>
        </section>

        <section v-else-if="!messages.length && isMarketIntelWorkspace" class="market-research-welcome" aria-label="行业研究入口">
          <div class="research-heading">
            <div class="research-identity">
              <span class="research-mark" aria-hidden="true">察</span>
              <span>小察 · 行业深度研究</span>
            </div>
            <h1>把行业变化，放回产业链里看</h1>
            <p>围绕智能硬件及关联产业，从市场、价值链、技术与政策中建立证据，再形成判断。</p>
          </div>

          <div class="research-framework" aria-label="默认研究视角">
            <span>市场需求</span><i></i><span>产业链</span><i></i><span>竞争格局</span><i></i><span>技术与政策</span>
          </div>

          <div class="research-entry-grid">
            <div class="research-prompts">
              <div class="research-section-title">从一个研究问题开始</div>
              <button
                v-for="(item, index) in marketResearchPrompts"
                :key="`${index}-${item.title}`"
                type="button"
                class="research-prompt"
                :disabled="stream.sending.value || uploading"
                @click="askQuickPrompt(item.prompt)"
              >
                <span class="research-prompt-index">{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="research-prompt-copy">
                  <strong>{{ item.title }}</strong>
                  <span>{{ item.detail }}</span>
                </span>
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" /></svg>
              </button>
            </div>

            <aside class="research-method" aria-label="研究方法">
              <div class="method-title">研究如何展开</div>
              <ol>
                <li><span>界定</span><p>明确行业口径、区域、时间和要回答的决策问题</p></li>
                <li><span>取证</span><p>优先检索公告、政策、标准、财报和行业原始资料</p></li>
                <li><span>核验</span><p>标注来源与日期，解释口径差异和证据缺口</p></li>
                <li><span>判断</span><p>把事实、推断和情景分开，给出影响与观察信号</p></li>
              </ol>
            </aside>
          </div>
          <p class="research-footnote">默认关注智能硬件及上下游；也可以直接指定行业、地区和研究周期。</p>
        </section>

        <section v-else-if="!messages.length" class="chat-welcome" aria-label="新对话快捷问题">
          <div class="welcome-avatar">{{ (currentEmployee?.name || 'AI').slice(0, 1) }}</div>
          <h1>你好，我是{{ currentEmployee?.name || '数字员工' }}</h1>
          <p class="welcome-role">{{ currentEmployee?.role || '你的数字员工助手' }}</p>
          <p class="welcome-instruction">选择一个问题开始对话</p>
          <div class="quick-prompt-list">
            <button
              v-for="(prompt, index) in quickPrompts"
              :key="`${index}-${prompt}`"
              type="button"
              class="quick-prompt"
              :disabled="stream.sending.value || uploading"
              @click="askQuickPrompt(prompt)"
            >
              <span class="prompt-mark" aria-hidden="true">✦</span>
              <span class="prompt-text">{{ prompt }}</span>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" /></svg>
            </button>
          </div>
        </section>
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
        ref="inputBarRef"
        :disabled="stream.sending.value"
        :sending="stream.sending.value"
        :uploading="uploading"
        :full-width="fullWidthMode"
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
import { DEFAULT_QUICK_PROMPTS } from '../utils/quickPrompts.js'
import { useChatStream } from '../composables/useChatStream.js'
import ConversationSidebar from '../components/chat/ConversationSidebar.vue'
import PipelineSidebar from '../components/chat/PipelineSidebar.vue'
import ChatMessage from '../components/chat/ChatMessage.vue'
import InputBar from '../components/chat/InputBar.vue'
import { isCustomEmployee, routeNameForEmployee } from '../utils/employeeRoutes.js'

defineOptions({ name: 'ChatView' })
const props = defineProps({
  employeeId: { type: String, default: '' },
})
const router = useRouter()
const route = useRoute()
const message = useMessage()
const exportingSecurity = ref(false)
const isMarketIntelWorkspace = computed(() => props.employeeId === 'market-intel')
const marketResearchPrompts = computed(() => {
  const configured = Array.isArray(currentEmployee.value?.quick_prompts)
    ? currentEmployee.value.quick_prompts.filter(x => typeof x === 'string' && x.trim()).slice(0, 3)
    : []
  if (configured.length) {
    return configured.map((prompt, index) => ({
      title: `自定义研究问题 ${index + 1}`,
      detail: '使用团队配置的快捷问法',
      prompt,
    }))
  }
  return [
    {
      title: '画出行业全景',
      detail: '口径、规模、增长驱动与关键变量',
      prompt: '请对中国智能硬件行业做一次深入研究。先界定行业口径与上下游范围，再分析市场规模与增速、主要赛道、需求驱动和关键不确定性。核心事实请标注来源链接、发布日期、统计口径和单位。',
    },
    {
      title: '拆解产业链',
      detail: '关键环节、价值分布、依赖与瓶颈',
      prompt: '请以智能硬件为主题拆解上游核心部件、中游方案与制造、下游渠道和应用场景，识别各环节的价值分布、议价能力、依赖关系和瓶颈，并为关键判断提供来源链接与日期。',
    },
    {
      title: '追踪技术路线',
      detail: '成熟度、成本约束与商业化信号',
      prompt: '请研究智能硬件中的端侧 AI 与 AIoT 技术演进和商业化进展，比较主要路线的成熟度、成本约束、代表企业布局及未来 12–24 个月的验证信号。区分已证实事实、分析判断和情景假设。',
    },
    {
      title: '评估机会与风险',
      detail: '从市场、政策、技术和竞争综合判断',
      prompt: '请围绕智能硬件及关联产业，评估未来 1–3 年的行业机会与风险。从市场需求、产业链、技术、政策和竞争格局分析，说明证据、判断限制和建议跟踪的指标。',
    },
  ]
})

async function exportSecurityRecords() {
  exportingSecurity.value = true
  try {
    const { data } = await api.get(`/conversations/${persistedConvId.value}/security-export`, { responseType: 'blob' })
    const url = URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = `security-${persistedConvId.value}.zip`
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) {
    let detail = error.response?.data?.detail
    if (error.response?.data instanceof Blob) {
      try { detail = JSON.parse(await error.response.data.text()).detail } catch {}
    }
    message.error(detail || '实操记录导出失败，请稍后重试')
  } finally {
    exportingSecurity.value = false
  }
}

/* ---------- 基础状态 ---------- */
const employees = ref([])
const empNames = reactive({})
const currentEmp = ref(null)
const inputBarRef = ref(null)
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

// 编排型对话页只展示 kind==='composed' 的员工；定制型员工有专属对话页，
// 不应在本页可被选择（否则会丢失定制上下文如数据源/SQL 工具注入）。
const empOptions = computed(() => employees.value
  .filter(e => props.employeeId ? e.id === props.employeeId : !isCustomEmployee(e))
  .map(e => ({ label: e.role || e.name, value: e.id })))
const currentEmployee = computed(() => employees.value.find(e => e.id === currentEmp.value) || null)
const quickPrompts = computed(() => {
  const configured = Array.isArray(currentEmployee.value?.quick_prompts)
    ? currentEmployee.value.quick_prompts.filter(x => typeof x === 'string' && x.trim()).slice(0, 3)
    : []
  return configured.length ? configured : DEFAULT_QUICK_PROMPTS
})

function askQuickPrompt(prompt) {
  inputBarRef.value?.sendText(prompt)
}

function scrollToBottom() {
  nextTick(() => {
    if (msgsRef.value) msgsRef.value.scrollTop = msgsRef.value.scrollHeight
  })
}

/* ---------- SSE 流 ---------- */
const stream = useChatStream({ stageStates, stageDetail, messages, scrollToBottom })

async function setChatUrl(query, replace = false) {
  const target = { name: route.name || 'chat', query }
  if (router.resolve(target).fullPath !== route.fullPath) {
    await router[replace ? 'replace' : 'push'](target)
  }
}

function markConversationPersisted(cid) {
  if (convId.value !== cid || route.name !== (props.employeeId ? routeNameForEmployee(props.employeeId) : 'chat')) return
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
    pinnedSkills: request.pinnedSkills || [],
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
  const precedingUser = [...messages.value.slice(0, idx)].reverse().find(item => item.role === 'user')
  try {
    await api.post('/me/evaluations', {
      run_id: msg.run_id || '',
      message_id: msg.message_id || '',
      employee_id: msg.employee_id || currentEmp.value || '',
      conversation_id: msg.conversation_id || convId.value || '',
      rating,
      reason,
      question_preview: precedingUser?.content || '',
      answer_preview: msg._md || msg.content || '',
    })
  } catch (e) {
    msg._evaluated = null
    messages.value = [...messages.value]
    message.error(e.response?.data?.detail || '评价未保存，请重试')
  }
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
    await stream.detachActiveStream()
  }
  try {
    const { data } = await api.get(`/conversations/${cid}`)
    if (!syncUrl && route.query.conv !== cid) return false
    if (data.error) { message.error(data.error); return false }
    // 会话属于定制型员工时，重定向到该员工的专属对话路由，避免丢失定制上下文
    const targetRoute = routeNameForEmployee(data.employee_id)
    if (targetRoute !== route.name) {
      await router.replace({ name: targetRoute, query: { conv: cid } })
      return true
    }
    convId.value = cid
    persistedConvId.value = cid
    currentEmp.value = data.employee_id
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
    await stream.resumeActiveRun(cid)
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
  if (props.employeeId && empId !== props.employeeId) return false
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
    } else if (empOptions.value.length) {
      // 专属工作台固定使用路由绑定员工；通用对话页支持 ?emp= 选择编排型员工。
      const target = props.employeeId
        ? empOptions.value.find(e => e.value === props.employeeId)
        : empOptions.value.find(e => e.value === route.query.emp)
      await selectEmployee(target?.value || empOptions.value[0].value, { replaceUrl: true })
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
  const targetEmp = props.employeeId || (typeof emp === 'string' && empOptions.value.some(e => e.value === emp)
    ? emp : (empOptions.value[0]?.value || null))
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
.skill-picker { display: flex; align-items: center; gap: 12px; padding: 8px 24px; font-size: 13px; color: var(--text-secondary, #666); }
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
.message-lane { width: min(100%, 1080px); min-height: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 10px; }
.chat-layout.full-width-mode .message-lane { width: 100%; max-width: none; }
.market-intel-meta { color: #147b78; font-weight: 600; }
.market-research-unavailable { width: min(100%, 620px); margin: auto; padding: 48px 20px; text-align: center; }
.market-research-unavailable h1 { margin: 0 0 9px; color: #203a46; font-size: 20px; }
.market-research-unavailable p { margin: 0; color: #687d85; font-size: 13px; line-height: 1.7; }
.market-research-welcome {
  width: min(100%, 980px);
  margin: auto;
  padding: clamp(24px, 4vh, 48px) 0;
  color: #172b3a;
}
.research-heading { max-width: 760px; }
.research-identity { display: flex; align-items: center; gap: 10px; color: #147b78; font-size: 13px; font-weight: 650; }
.research-mark { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid #a7ceca; border-radius: 50%; color: #116e70; font-size: 15px; }
.research-heading h1 { margin: 17px 0 9px; color: #172b3a; font-size: clamp(27px, 3.3vw, 38px); line-height: 1.2; font-weight: 650; letter-spacing: -.035em; }
.research-heading p { max-width: 680px; margin: 0; color: #5c6f7a; font-size: 14px; line-height: 1.8; }
.research-framework { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 27px 0 30px; color: #526a74; font-size: 12px; }
.research-framework i { width: 25px; height: 1px; background: #b8cac8; }
.research-entry-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(250px, .8fr); gap: clamp(22px, 4vw, 48px); align-items: start; }
.research-section-title, .method-title { margin: 0 0 11px; color: #263e4a; font-size: 14px; font-weight: 650; }
.research-prompts { min-width: 0; }
.research-prompt { display: flex; width: 100%; min-height: 68px; align-items: center; gap: 15px; padding: 12px 6px; border: 0; border-top: 1px solid #e0e8e5; background: transparent; color: inherit; text-align: left; cursor: pointer; }
.research-prompt:last-child { border-bottom: 1px solid #e0e8e5; }
.research-prompt:hover { background: #f1f7f5; }
.research-prompt:focus-visible { outline: 2px solid #147b78; outline-offset: 2px; }
.research-prompt:disabled { cursor: wait; opacity: .55; }
.research-prompt-index { width: 25px; flex: 0 0 25px; color: #b97829; font-size: 12px; font-variant-numeric: tabular-nums; }
.research-prompt-copy { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 4px; }
.research-prompt-copy strong { color: #1e3744; font-size: 14px; font-weight: 620; }
.research-prompt-copy span { color: #71828a; font-size: 12px; line-height: 1.5; }
.research-prompt svg { width: 17px; height: 17px; flex: 0 0 17px; fill: none; stroke: #147b78; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.research-method { padding: 18px 18px 17px; border-left: 3px solid #2f918b; background: #f1f6f4; }
.research-method ol { display: grid; gap: 13px; margin: 0; padding: 0; list-style: none; }
.research-method li { display: grid; grid-template-columns: 43px 1fr; gap: 10px; align-items: start; }
.research-method li > span { padding-top: 1px; color: #147b78; font-size: 12px; font-weight: 650; }
.research-method li p { margin: 0; color: #5c6f7a; font-size: 12px; line-height: 1.65; }
.research-footnote { margin: 19px 0 0; color: #809097; font-size: 11px; line-height: 1.6; }
.chat-welcome { width: min(100%, 540px); margin: auto; padding: 18px 0 10vh; text-align: center; transform: translateY(-3vh); }
.welcome-avatar { display: grid; width: 58px; height: 58px; margin: 0 auto 16px; place-items: center; border-radius: 19px 19px 19px 6px; background: linear-gradient(145deg, #eef2ff, #dbeafe); color: #3157c8; font-size: 24px; font-weight: 700; box-shadow: inset 0 0 0 1px rgba(49, 87, 200, .08); }
.chat-welcome h1 { margin: 0; color: #172033; font-size: 21px; font-weight: 650; letter-spacing: -.02em; }
.welcome-role { margin: 7px 0 0; color: #64748b; font-size: 13px; }
.welcome-instruction { margin: 20px 0 12px; color: #94a3b8; font-size: 12px; }
.quick-prompt-list { display: flex; flex-direction: column; gap: 8px; text-align: left; }
.quick-prompt { display: flex; width: 100%; min-height: 48px; align-items: center; gap: 12px; padding: 11px 14px; border: 1px solid #edf0f5; border-radius: 11px; background: #fafbfc; color: #334155; cursor: pointer; text-align: left; transition: border-color .15s, background .15s, transform .15s; }
.quick-prompt:hover:not(:disabled) { border-color: #c7d2fe; background: #f6f8ff; transform: translateY(-1px); }
.quick-prompt:focus-visible { outline: 2px solid #3157c8; outline-offset: 2px; }
.quick-prompt:disabled { cursor: wait; opacity: .55; }
.prompt-mark { color: #635bdb; font-size: 17px; line-height: 1; }
.prompt-text { min-width: 0; flex: 1; font-size: 13px; line-height: 1.5; }
.quick-prompt svg { width: 16px; height: 16px; fill: none; stroke: #64748b; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
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
  .chat-welcome { width: min(100%, 480px); padding: 12px 4px 8vh; }
  .chat-welcome h1 { font-size: 19px; }
  .market-research-welcome { padding: 16px 0 24px; }
  .research-entry-grid { grid-template-columns: 1fr; gap: 22px; }
  .research-framework { gap: 8px; margin: 20px 0 24px; }
  .research-framework i { width: 13px; }
  .research-method { padding: 15px; }
}
</style>
