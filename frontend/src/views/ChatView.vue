<!-- 对话工作台：左侧历史对话侧栏 + 中栏执行流水线 + 右栏 SSE 流式对话 -->
<template>
  <div class="chat-layout">
    <!-- 左栏：历史会话 -->
    <div class="conv-sidebar">
      <div class="conv-head">
        <span class="conv-title">历史对话</span>
        <n-button size="tiny" @click="newConv">+ 新会话</n-button>
      </div>
      <div class="conv-list">
        <div v-if="!convList.length" class="conv-empty">暂无历史对话<br>发条消息开始吧</div>
        <div
          v-for="c in convList" :key="c.conv_id"
          class="conv-item"
          :class="{ active: c.conv_id === convId }"
          @click="openConversation(c.conv_id)"
        >
          <div class="conv-name">{{ c.title || c.preview || '新对话' }}</div>
          <div class="conv-meta">
            <span class="emp-tag">{{ empNames[c.employee_id] || c.employee_id }}</span>
            <span>{{ fmtTime(c.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 中栏：执行流水线 -->
    <div class="pipeline-sidebar">
      <div class="pipeline-title">执行流水线</div>
      <div class="pipeline-body">
        <template v-for="(s, i) in STAGES" :key="s[0]">
          <div v-if="i" class="connector" :class="{ done: stageStates[s[0]] === 'done' }"></div>
          <div class="stage" :class="stageStates[s[0]] || 'pending'">
            <div class="dot"></div>
            <div>
              <div class="stage-name">{{ i + 1 }}. {{ s[1] }}</div>
              <div v-if="stageDetail[s[0]]" class="stage-detail">{{ stageDetail[s[0]] }}</div>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 右栏：对话区 -->
    <div class="chat-main">
      <!-- 员工选择条 -->
      <div class="chat-header">
        <n-select
          :value="currentEmp"
          :options="empOptions"
          size="small"
          style="width:240px"
          @update:value="selectEmployee"
        />
        <span class="emp-meta">{{ empMeta }}</span>
        <n-button size="small" @click="openTrace">🔎 执行过程</n-button>
      </div>

      <!-- 消息列表 -->
      <div class="msgs" ref="msgsRef">
        <template v-for="(msg, idx) in messages" :key="idx">
          <!-- 用户消息 -->
          <div v-if="msg.role === 'user'" class="msg-wrapper user-wrapper">
            <div class="msg user">
              <div class="msg-text">{{ msg.content }}</div>
            </div>
            <div class="msg-meta">
              <span class="msg-time">{{ msg.time }}</span>
              <span class="msg-copy" @click="copyText(msg.content)" title="复制">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
              </span>
            </div>
          </div>
          <!-- Bot 消息 -->
          <div v-else class="msg-wrapper bot-wrapper">
            <div class="msg bot">
              <div v-if="msg.html" class="md" v-html="msg.html"></div>
              <div v-else-if="msg.content" class="md">{{ msg.content }}</div>
              <div v-else class="msg-loading">
                <span class="loading-dot">.</span>
                <span class="loading-dot">.</span>
                <span class="loading-dot">.</span>
              </div>
            </div>
            <div class="msg-meta">
              <span class="msg-time">{{ msg.time }}</span>
              <span class="msg-copy" @click="copyText(msg.html || msg.content)" title="复制">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
              </span>
              <template v-if="msg.run_id && !msg._evaluated">
                <span class="eval-btn" @click="submitRating(msg, 1, idx)" title="有用">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
                </span>
                <span class="eval-btn" @click="showReasonPopover(msg, idx)" title="没用">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h3a2 2 0 012 2v7a2 2 0 01-2 2h-3"/></svg>
                </span>
              </template>
              <template v-else-if="msg._evaluated === 1">
                <span class="eval-btn evaluated-up" title="已评价有用">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
                </span>
              </template>
              <template v-else-if="msg._evaluated === -1">
                <span class="eval-btn evaluated-down" title="已评价没用">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h3a2 2 0 012 2v7a2 2 0 01-2 2h-3"/></svg>
                </span>
              </template>
            </div>
            <div v-if="reasonPopover.show && reasonPopover.msgIdx === idx" class="reason-popover">
              <div class="reason-title">请告诉我们哪里不好：</div>
              <div class="reason-options">
                <span v-for="r in REASONS" :key="r.value" class="reason-chip"
                      :class="{ active: reasonPopover.selected === r.value }"
                      @click="reasonPopover.selected = r.value">{{ r.label }}</span>
              </div>
              <div class="reason-actions">
                <n-button size="tiny" @click="reasonPopover.show = false">取消</n-button>
                <n-button size="tiny" type="error" :disabled="!reasonPopover.selected"
                          @click="confirmNegative">提交</n-button>
              </div>
            </div>
          </div>
          <!-- Trace（思考/工具） -->
          <n-collapse v-if="msg.trace && msg.trace.length" :default-expanded-names="msg.traceExpanded ? ['t'] : []" class="trace-collapse">
            <n-collapse-item name="t">
              <template #header>
                <span class="trace-badge">思考 / 工具</span>
                <span class="trace-count">（{{ msg.trace.length }} 项）</span>
              </template>
              <div v-for="(t, ti) in msg.trace" :key="ti" class="trace-item" :class="t.type">
                <template v-if="t.type === 'think'">
                  <div class="think-box">
                    <span class="think-label">模型思考</span>
                    <span class="think-text">{{ t.content }}</span>
                  </div>
                </template>
                <template v-else-if="t.type === 'tool'">
                  <div class="tool-box">
                    <b>🔧 {{ t.name }}</b>
                    <span v-if="t.args">({{ t.args }})</span>
                    <span v-if="t.status === 'start'"> 调用中…</span>
                    <span v-else> ✓</span>
                    <pre v-if="t.preview">{{ t.preview }}</pre>
                  </div>
                </template>
              </div>
            </n-collapse-item>
          </n-collapse>
          <!-- 子代理面板 -->
          <div v-if="msg.subagents && msg.subagents.length" class="subagent-panel">
            <div class="subagent-title">子代理</div>
            <div v-for="sa in msg.subagents" :key="sa.name" class="subagent-item">
              <span class="subagent-name">🧩 {{ sa.name }}</span>
              <span class="subagent-status" :class="sa.status">{{ subagentStatusText(sa.status) }}</span>
              <pre v-if="sa.output" class="subagent-output">{{ sa.output }}</pre>
            </div>
          </div>
          <!-- 审批卡片 -->
          <div v-if="msg.approval" class="approval-card">
            <div class="approval-head">
              <b>⚠ 人工审批</b>　员工请求执行 <b>{{ msg.approval.tool }}</b>
              <span v-if="msg.approval.args">，参数：<code>{{ msg.approval.args }}</code></span>
            </div>
            <div v-if="!msg.approval.resolved" class="approval-btns">
              <n-button size="small" type="success" @click="decide(msg.approval.id, 'approve', idx)">批准</n-button>
              <n-button size="small" type="error" @click="decide(msg.approval.id, 'reject', idx)">拒绝</n-button>
            </div>
            <div v-else class="approval-resolved">{{ msg.approval.resolved }}</div>
          </div>
        </template>
      </div>

      <!-- 输入栏 + 问号提示 -->
      <div class="input-bar">
        <n-input
          v-model:value="input"
          placeholder="输入消息，回车发送"
          @keyup.enter="send"
          :disabled="sending"
        />
        <n-button type="primary" :loading="sending" @click="send">发送</n-button>
        <n-popover trigger="hover" placement="top-start" :width="340">
          <template #trigger>
            <span class="hint-icon">?</span>
          </template>
          <div style="white-space:pre-line;font-size:13px;line-height:1.7;max-height:300px;overflow-y:auto">{{ hint }}</div>
        </n-popover>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import api from '../api.js'

defineOptions({ name: 'ChatView' })
const router = useRouter()
const route = useRoute()

const STAGES = [
  ['input', '用户输入'], ['employee', 'Employee 加载'], ['sop', '加载 SOP'],
  ['skills', '加载 Skills'], ['planning', '智能体规划'], ['skill', '调用 Skill'],
  ['report', '输出回复'],
]
const HINTS = {
  xiaosu: '试试：\n① X1音箱续航多久？买一个多少钱？\n② 查一下订单O12345\n③ 音箱坏了不出声了，我要投诉！\n④ O12345我想退款\n⑤ 记住我姓张，回复要通俗一点\n⑥ 查一下张总的会员等级\n⑦ S2台灯和S2 Pro有什么区别？',
  xiaoshu: '试试：\n① 哪个地区销售额最高？\n② 按月统计各产品线的销售趋势\n③ 华东和华北谁的单均金额更高？\n④ 投影仪这个产品线在Q1表现怎么样\n⑤ 做个按产品和地区的交叉分析\n⑥ 你觉得哪个产品最值得加大投入？',
}

const employees = ref([])
const empNames = reactive({})
const currentEmp = ref(null)
const convId = ref(null)
const convList = ref([])
const messages = ref([])
let activeController = null

function abortActiveStream() {
  if (activeController) {
    activeController.abort()
    activeController = null
  }
}
const input = ref('')
const sending = ref(false)
const empMeta = ref('')
const hint = ref('向数字员工提问吧。')
const stageStates = reactive({})
const stageDetail = reactive({})
const msgsRef = ref(null)
const reasonPopover = reactive({ show: false, msgIdx: null, selected: null })
const REASONS = [
  { value: 'irrelevant', label: '答非所问' },
  { value: 'factual_error', label: '事实错误' },
  { value: 'wrong_process', label: '流程不对' },
  { value: 'too_slow', label: '太慢' },
  { value: 'other', label: '其他' },
]

const empOptions = computed(() =>
  employees.value.map(e => ({ label: e.role || e.name, value: e.id }))
)

function fmtTime(s) { return (s || '').replace('T', ' ').slice(5, 16) }

function scrollToBottom() {
  nextTick(() => {
    if (msgsRef.value) msgsRef.value.scrollTop = msgsRef.value.scrollHeight
  })
}

/* ---------- XSS 消毒 ---------- */
const BAD_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE', 'FORM'])
// URL 协议白名单：仅允许 http/https/mailto/tel 与相对地址；data:、javascript: 等一律拒绝
const SAFE_PROTOCOLS = ['http:', 'https:', 'mailto:', 'tel:']
const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'formaction', 'action', 'poster', 'background'])
function isSafeUrl(v) {
  const t = v.trim()
  // 锚点 / 相对路径 / query-only：视为安全
  if (!t || t.startsWith('#') || t.startsWith('/') || t.startsWith('./') ||
      t.startsWith('../') || t.startsWith('?')) return true
  const idx = t.indexOf(':')
  if (idx <= 0) return true // 无协议前缀 → 视为相对路径
  const proto = t.slice(0, idx).toLowerCase()
  return SAFE_PROTOCOLS.includes(proto)
}
function sanitizeHtml(html) {
  const tpl = document.createElement('template')
  tpl.innerHTML = html
  for (const el of Array.from(tpl.content.querySelectorAll('*'))) {
    if (BAD_TAGS.has(el.tagName)) { el.remove(); continue }
    for (const attr of Array.from(el.attributes)) {
      const n = attr.name.toLowerCase()
      const v = (attr.value || '').trim()
      if (n.startsWith('on')) el.removeAttribute(attr.name)       // 事件处理器
      else if (n === 'style') el.removeAttribute(attr.name)       // 内联样式（CSS 注入面）
      else if (URL_ATTRS.has(n) && !isSafeUrl(v)) el.removeAttribute(attr.name)
    }
  }
  return tpl.innerHTML
}
function renderMd(md) {
  try { return sanitizeHtml(marked.parse(md || '')) }
  catch { return `<pre>${String(md || '').replace(/</g, '&lt;')}</pre>` }
}

/* ---------- 流水线 ---------- */
function resetPipeline() {
  Object.keys(stageStates).forEach(k => delete stageStates[k])
  Object.keys(stageDetail).forEach(k => delete stageDetail[k])
  stageStates.input = 'done'
  stageDetail.input = new Date().toLocaleTimeString()
}
function setStage(id, status, detail) {
  stageStates[id] = status
  if (detail !== undefined) stageDetail[id] = detail
}

/* ---------- SSE 流式解析 ---------- */
async function readStream(resp, msgIdx) {
  const reader = resp.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop()
    for (const p of parts) {
      if (!p.startsWith('data:')) continue
      try { handleEvent(JSON.parse(p.slice(5)), msgIdx) } catch {}
    }
  }
  // 空 trace 移除
  const msg = messages.value[msgIdx]
  if (msg && msg.trace && !msg.trace.length) delete msg.trace
  scrollToBottom()
}

function handleEvent(ev, msgIdx) {
  const msg = messages.value[msgIdx]
  if (ev.type === 'stage') {
    if (ev.stage === 'report' && ev.status === 'done') {
      setStage('planning', 'done'); setStage('skill', 'done'); setStage('report', 'done', '')
    } else {
      setStage(ev.stage, ev.status, ev.detail_text)
      if (ev.stage === 'employee') empMeta.value = ev.detail_text
    }
  } else if (ev.type === 'thinking') {
    if (!msg.trace) msg.trace = []
    let box = msg.trace.find(t => t.type === 'think' && !t._closed)
    if (!box) { box = { type: 'think', content: '' }; msg.trace.push(box) }
    box.content += ev.content
    msg.trace = [...msg.trace]
    scrollToBottom()
  } else if (ev.type === 'token') {
    if (!msg._md) msg._md = ''
    msg._md += ev.content
    msg.html = renderMd(msg._md)
    msg.content = ''
    messages.value = [...messages.value]
    scrollToBottom()
  } else if (ev.type === 'tool') {
    if (!msg.trace) msg.trace = []
    const args = ev.args && Object.keys(ev.args).length ? JSON.stringify(ev.args) : ''
    if (ev.status === 'start') {
      msg.trace.push({ type: 'tool', name: ev.name, args, status: 'start' })
    } else {
      const pending = msg.trace.find(t => t.type === 'tool' && t.status === 'start' && t.name === ev.name)
      if (pending) { pending.status = 'done'; pending.preview = ev.preview || '' }
      else msg.trace.push({ type: 'tool', name: ev.name, args, status: 'done', preview: ev.preview || '' })
    }
    msg.trace = [...msg.trace]
    scrollToBottom()
  } else if (ev.type === 'subagent') {
    if (!msg.subagents) msg.subagents = []
    let sa = msg.subagents.find(s => s.name === ev.name)
    if (!sa) {
      sa = { name: ev.name, status: ev.status, output: '' }
      msg.subagents.push(sa)
    }
    sa.status = ev.status
    if (ev.output) sa.output = ev.output
    msg.subagents = [...msg.subagents]
    messages.value = [...messages.value]
    scrollToBottom()
  } else if (ev.type === 'todos') {
    setStage('planning', 'active', ev.items.map(t => `${t.status === 'completed' ? '☑' : '☐'} ${t.content}`).join('\n'))
  } else if (ev.type === 'approval_required') {
    msg.approval = {
      id: ev.approval_id,
      tool: ev.tool,
      args: ev.args ? JSON.stringify(ev.args) : '',
      resolved: null,
    }
    setStage('skill', 'active', `审批中：${ev.tool}`)
    messages.value = [...messages.value]
    scrollToBottom()
  } else if (ev.type === 'error') {
    if (!msg.trace) msg.trace = []
    msg.trace.push({ type: 'tool', name: '⚠ ' + ev.message, args: '', status: 'done' })
    msg.trace = [...msg.trace]
    scrollToBottom()
  } else if (ev.type === 'message_end') {
    msg.run_id = ev.run_id
    msg.message_id = ev.message_id
    msg.employee_id = ev.employee_id
    msg.conversation_id = ev.conversation_id
  }
}

/* ---------- 发送 / 审批 ---------- */
async function send() {
  if (!convId.value || sending.value) return
  const text = input.value.trim()
  if (!text) return
  input.value = ''
  sending.value = true
  resetPipeline()
  const ts = fmtNow()
  messages.value.push({ role: 'user', content: text, time: ts })
  const botIdx = messages.value.length
  messages.value.push({ role: 'bot', content: '', html: '', _md: '', trace: [], traceExpanded: false, time: ts })
  const controller = new AbortController()
  abortActiveStream()
  activeController = controller
  try {
    const resp = await fetch(`/api/conversations/${convId.value}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
      body: JSON.stringify({ message: text }),
      signal: controller.signal,
    })
    await readStream(resp, botIdx)
    if (activeController === controller) activeController = null
  } catch (e) {
    if (e.name !== 'AbortError') {
      messages.value[botIdx].content = '⚠ 连接失败：' + e.message
    }
    if (activeController === controller) activeController = null
  }
  sending.value = false
  await loadHistory(currentEmp.value)
}

async function decide(approvalId, decision, msgIdx) {
  const msg = messages.value[msgIdx]
  msg.approval.resolved = decision === 'approve' ? '✓ 已批准' : '✗ 已拒绝'
  const traceIdx = messages.value.length
  messages.value.push({ role: 'bot', content: '', html: '', _md: '', trace: [], traceExpanded: false, time: fmtNow() })
  const controller = new AbortController()
  abortActiveStream()
  activeController = controller
  try {
    const resp = await fetch(`/api/approvals/${approvalId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
      body: JSON.stringify({ decision }),
      signal: controller.signal,
    })
    await readStream(resp, traceIdx)
    if (activeController === controller) activeController = null
  } catch (e) {
    if (e.name !== 'AbortError') {
      messages.value[traceIdx].content = '⚠ ' + e.message
    }
    if (activeController === controller) activeController = null
  }
}

/* ---------- 历史会话 ---------- */
async function loadHistory(empId) {
  try {
    const { data } = await api.get(`/conversations`, { params: { employee_id: empId, limit: 15 } })
    convList.value = data || []
  } catch {}
}

async function openConversation(cid) {
  try {
    const { data } = await api.get(`/conversations/${cid}`)
    if (data.error) return
    convId.value = cid
    currentEmp.value = data.employee_id
    hint.value = HINTS[data.employee_id] || '向数字员工提问吧。'
    messages.value = []
    resetPipeline()
    for (const t of (data.turns || [])) {
      if (t.role === 'user') {
        messages.value.push({ role: 'user', content: t.content, time: fmtNow() })
      } else {
        const msg = { role: 'bot', content: '', html: renderMd(t.content || ''), _md: t.content || '', trace: [], time: fmtNow() }
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
      }
    }
    scrollToBottom()
  } catch {}
}

/* ---------- 员工切换 ---------- */
async function selectEmployee(empId) {
  currentEmp.value = empId
  hint.value = HINTS[empId] || '向数字员工提问吧。'
  try {
    const { data } = await api.post(`/employees/${empId}/conversations`)
    convId.value = data.conversation_id
  } catch { return }
  messages.value = []
  resetPipeline()
  empMeta.value = '已切换到该员工（记忆跨会话保留）'
  await loadHistory(empId)
}

function newConv() {
  if (currentEmp.value) selectEmployee(currentEmp.value)
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

function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(typeof text === 'string' ? text.replace(/<[^>]+>/g, '') : '').catch(() => {})
}

function showReasonPopover(msg, idx) {
  reasonPopover.show = true
  reasonPopover.msgIdx = idx
  reasonPopover.selected = null
}

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

async function confirmNegative() {
  const idx = reasonPopover.msgIdx
  const msg = messages.value[idx]
  const reason = reasonPopover.selected
  reasonPopover.show = false
  if (msg && reason) await submitRating(msg, -1, idx, reason)
}

function subagentStatusText(status) {
  const map = { started: '运行中', completed: '已完成', failed: '失败', interrupted: '已中断' }
  return map[status] || status
}

/* ---------- 初始化 ---------- */
onMounted(async () => {
  try {
    const { data } = await api.get('/employees')
    employees.value = data
    data.forEach(e => { empNames[e.id] = e.name })
    const qconv = route.query.conv
    if (qconv) {
      if (data.length) await selectEmployee(data[0].id)
      await openConversation(qconv)
    } else if (data.length) {
      await selectEmployee(data[0].id)
    }
  } catch (e) {
    empMeta.value = '员工列表加载失败：' + e.message
  }
})

onBeforeUnmount(() => {
  abortActiveStream()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
}

/* 左栏：历史会话 */
.conv-sidebar {
  width: 240px;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
}
.conv-head {
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
}
.conv-title { font-size: 13px; font-weight: 600; color: #334155; }
.conv-list { flex: 1; overflow-y: auto; padding: 8px; }
.conv-empty { font-size: 12px; color: #94a3b8; text-align: center; padding: 24px 8px; line-height: 1.8; }
.conv-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.15s;
}
.conv-item:hover { background: #f1f5f9; }
.conv-item.active { background: #eff6ff; border: 1px solid #3b82f6; }
.conv-name { font-size: 13px; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: #94a3b8; margin-top: 3px; display: flex; gap: 8px; }
.emp-tag { color: #3b82f6; }

/* 中栏：流水线 */
.pipeline-sidebar {
  width: 240px;
  border-right: 1px solid #e2e8f0;
  padding: 16px;
  overflow-y: auto;
  background: #ffffff;
}
.pipeline-title { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 12px; }
.pipeline-body { display: flex; flex-direction: column; }
.stage { display: flex; gap: 10px; padding: 6px 0; opacity: 0.4; }
.stage.active, .stage.done { opacity: 1; }
.dot {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid #cbd5e1; flex-shrink: 0; margin-top: 1px; position: relative;
}
.stage.active .dot { border-color: #3b82f6; background: #eff6ff; }
.stage.done .dot { border-color: #10b981; background: #10b981; }
.stage.done .dot::after {
  content: ""; position: absolute; left: 5px; top: 2px;
  width: 4px; height: 8px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg);
}
.stage-name { font-size: 13px; font-weight: 500; color: #0f172a; }
.stage-detail { font-size: 11px; color: #64748b; margin-top: 2px; line-height: 1.5; white-space: pre-wrap; }
.connector { width: 2px; height: 14px; background: #e2e8f0; margin-left: 8px; }
.connector.done { background: #10b981; }

/* 右栏：对话区 */
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.chat-header {
  padding: 10px 16px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  gap: 12px;
  background: #ffffff;
}
.emp-meta { font-size: 12px; color: #64748b; flex: 1; }

.msgs { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 6px; min-height: 0; }
.msg-wrapper { display: flex; flex-direction: column; max-width: 76%; gap: 2px; }
.user-wrapper { align-self: flex-end; align-items: flex-end; }
.bot-wrapper { align-self: flex-start; align-items: flex-start; position: relative; }
.msg { padding: 12px 16px; border-radius: 16px; font-size: 14px; line-height: 1.7; word-break: break-word; animation: msg-in 0.25s ease-out; }
@keyframes msg-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.msg.user { align-self: flex-end; background: linear-gradient(135deg, #3b82f6, #2563eb); color: #fff; border-bottom-right-radius: 4px; }
.msg.bot { align-self: flex-start; background: #ffffff; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.02); }
.msg-text { }
.msg-meta { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #94a3b8; }
.bot-meta { }
.user-meta { }
.msg-copy { cursor: pointer; opacity: 0.4; transition: opacity 0.15s; font-size: 12px; line-height: 1; position: relative; }
.msg-copy:hover { opacity: 1; }
.msg-copy:hover::after { content: '复制'; position: absolute; left: 50%; transform: translateX(-50%); bottom: calc(100% + 4px); background: #334155; color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px; white-space: nowrap; }
.msg-loading { font-size: 24px; line-height: 1; letter-spacing: 2px; color: #3b82f6; }
.loading-dot { animation: loading-pulse 1.4s infinite; opacity: 0; }
.loading-dot:nth-child(1) { animation-delay: 0s; }
.loading-dot:nth-child(2) { animation-delay: 0.2s; }
.loading-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes loading-pulse { 0%, 100% { opacity: 0; } 50% { opacity: 1; } }

/* markdown 排版 */
.md :deep(h1), .md :deep(h2), .md :deep(h3) { line-height: 1.3; margin: 14px 0 8px; font-weight: 600; }
.md :deep(h1) { font-size: 19px; } .md :deep(h2) { font-size: 17px; } .md :deep(h3) { font-size: 15px; }
.md :deep(p) { margin: 8px 0; }
.md :deep(ul), .md :deep(ol) { margin: 8px 0; padding-left: 22px; }
.md :deep(li) { margin: 4px 0; }
.md :deep(a) { color: #3b82f6; }
.md :deep(code) { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 12.5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.md :deep(pre) { background: #1e293b; color: #e2e8f0; padding: 12px 14px; border-radius: 8px; overflow-x: auto; margin: 10px 0; }
.md :deep(pre code) { background: none; padding: 0; color: inherit; }
.md :deep(blockquote) { border-left: 3px solid #cbd5e1; margin: 8px 0; padding: 2px 12px; color: #64748b; }
.md :deep(table) { border-collapse: collapse; margin: 10px 0; font-size: 13px; }
.md :deep(th), .md :deep(td) { border: 1px solid #e2e8f0; padding: 5px 10px; text-align: left; }
.md :deep(th) { background: #f8fafc; }
.md :deep(strong) { font-weight: 600; }

/* trace 折叠 */
.trace-collapse { align-self: stretch; }
.trace-badge { background: #f1f5f9; border-radius: 10px; padding: 1px 8px; font-size: 11px; color: #64748b; }
.trace-count { font-size: 11px; color: #94a3b8; margin-left: 6px; }
.trace-item { margin-bottom: 6px; }
.think-box {
  font-size: 12.5px; color: #64748b; background: #f8fafc;
  border-left: 3px solid #cbd5e1; border-radius: 0 6px 6px 0; padding: 8px 12px; line-height: 1.65; white-space: pre-wrap;
}
.think-label { display: block; font-size: 11px; color: #94a3b8; margin-bottom: 3px; font-weight: 600; }
.tool-box {
  font-size: 12.5px; color: #334155; background: #f0f9ff; border: 1px solid #bae6fd;
  padding: 7px 12px; border-radius: 8px; line-height: 1.55;
}
.tool-box b { color: #0369a1; }
.tool-box pre { margin: 5px 0 0; background: #f0f9ff; border-radius: 6px; padding: 6px 9px; font-size: 11.5px; color: #334155; white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; }

/* 子代理面板 */
.subagent-panel {
  align-self: stretch; background: #f5f3ff; border: 1px solid #ddd6fe;
  border-radius: 12px; padding: 10px 14px; font-size: 12.5px; color: #5b21b6;
}
.subagent-title { font-size: 11px; font-weight: 700; color: #7c3aed; margin-bottom: 6px; }
.subagent-item { padding: 4px 0; border-top: 1px solid rgba(124,58,237,0.12); }
.subagent-item:first-of-type { border-top: 0; }
.subagent-name { font-weight: 600; color: #5b21b6; }
.subagent-status { margin-left: 8px; font-size: 11px; color: #94a3b8; }
.subagent-status.started { color: #d97706; }
.subagent-status.completed { color: #059669; }
.subagent-status.failed, .subagent-status.interrupted { color: #dc2626; }
.subagent-output { margin: 5px 0 0; background: #ffffff; border-radius: 6px; padding: 6px 9px; font-size: 11.5px; color: #4c1d95; white-space: pre-wrap; word-break: break-word; max-height: 220px; overflow: auto; }

/* 审批 */
.approval-card {
  align-self: stretch; background: #fffbeb; border: 1px solid #fcd34d;
  border-radius: 12px; padding: 14px 16px; font-size: 13px; color: #92400e;
  animation: msg-in 0.25s ease-out;
}
.approval-btns { margin-top: 8px; display: flex; gap: 8px; }
.approval-resolved { margin-top: 8px; font-weight: 500; }

.hint-icon { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; border-radius: 50%; background: #e2e8f0; color: #64748b; font-size: 14px; font-weight: 700; cursor: pointer; transition: all 0.15s; margin-left: 6px; flex-shrink: 0; }
.hint-icon:hover { background: #3b82f6; color: #fff; }

/* 反馈按钮 */
.eval-btn {
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 8px;
  color: #94a3b8; transition: all 0.2s ease;
}
.eval-btn:hover { background: #f1f5f9; color: #475569; transform: scale(1.1); }
.eval-btn.evaluated-up { color: #10b981; background: #ecfdf5; }
.eval-btn.evaluated-down { color: #ef4444; background: #fef2f2; }

/* 点踩原因浮层 */
.reason-popover {
  position: absolute; bottom: calc(100% + 8px); left: 0; z-index: 10;
  background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 12px 14px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 260px;
}
.reason-title { font-size: 12px; color: #64748b; margin-bottom: 10px; font-weight: 500; }
.reason-options { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.reason-chip {
  font-size: 12px; padding: 4px 12px; border-radius: 16px;
  border: 1px solid #e2e8f0; cursor: pointer; transition: all 0.15s; color: #475569;
  background: #f8fafc;
}
.reason-chip:hover { border-color: #3b82f6; color: #3b82f6; background: #eff6ff; }
.reason-chip.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }
.reason-actions { display: flex; gap: 8px; justify-content: flex-end; }

.input-bar {
  padding: 12px 20px; background: #ffffff; border-top: 1px solid #e2e8f0;
  display: flex; gap: 10px;
}
</style>
