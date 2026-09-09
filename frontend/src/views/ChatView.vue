<!--
对话工作台：左侧历史对话侧栏 + 中栏执行流水线 + 右栏 SSE 流式对话
重构后：布局编排 + 员工/会话管理，渲染委托给子组件
-->
<template>
  <div class="chat-layout">
    <ConversationSidebar
      :list="convList"
      :active-id="convId"
      :emp-names="empNames"
      @select="openConversation"
      @new="newConv"
    />

    <PipelineSidebar
      :states="stageStates"
      :detail="stageDetail"
    />

    <div class="chat-main">
      <div class="chat-header">
        <n-select
          :value="currentEmp"
          :options="empOptions"
          size="small"
          style="width:200px"
          @update:value="selectEmployee"
        />
        <n-select
          v-if="aiModels.length"
          :value="currentModel"
          :options="modelOptions"
          size="small"
          placeholder="选择模型"
          style="width:160px"
          @update:value="(v) => currentModel = v"
        />
        <span class="emp-meta">{{ empMeta }}</span>
        <n-button size="small" @click="openTrace">🔎 执行过程</n-button>
      </div>

      <div class="msgs" ref="msgsRef">
        <ChatMessage
          v-for="(msg, idx) in messages" :key="idx"
          :msg="msg"
          :idx="idx"
          @rate="submitRating"
          @approve="(id, midx) => decide(id, 'approve', midx)"
          @reject="(id, midx) => decide(id, 'reject', midx)"
        />
      </div>

      <InputBar
        :disabled="stream.sending.value"
        :uploading="uploading"
        :hint="hint"
        @send="onSend"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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

/* ---------- 基础状态 ---------- */
const employees = ref([])
const empNames = reactive({})
const currentEmp = ref(null)
const convId = ref(null)
const convList = ref([])
const messages = ref([])
const empMeta = ref('')
const hint = ref('向数字员工提问吧。')
const msgsRef = ref(null)
const stageStates = reactive({})
const stageDetail = reactive({})

/* ---------- 模型选择 ---------- */
const aiModels = ref([])
const currentModel = ref('')  // base_model 名
const modelOptions = computed(() =>
  aiModels.value.map(m => ({ label: m.name, value: m.base_model }))
)

const HINTS = {
  xiaosu: '试试：\n① X1音箱续航多久？买一个多少钱？\n② 查一下订单O12345\n③ 音箱坏了不出声了，我要投诉！\n④ O12345我想退款\n⑤ 记住我姓张，回复要通俗一点\n⑥ 查一下张总的会员等级\n⑦ S2台灯和S2 Pro有什么区别？',
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

/* ---------- 发送 / 审批 ---------- */
const uploading = ref(false)

async function onSend(text, files = []) {
  if (!convId.value) return
  let attachments = []
  if (files.length) {
    uploading.value = true
    try {
      for (const f of files) {
        const form = new FormData()
        form.append('file', f)
        const { data } = await api.post(`/conversations/${convId.value}/attachments`, form)
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
  await stream.sendTo(`/api/conversations/${convId.value}/messages`, text, attachments, null, currentModel.value)
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
async function loadHistory(empId) {
  try {
    const { data } = await api.get('/conversations', { params: { employee_id: empId, limit: 15 } })
    convList.value = data || []
  } catch {}
}

async function openConversation(cid) {
  try {
    const { data } = await api.get(`/conversations/${cid}`)
    if (data.error) return
    // 会话属于定制型员工时，重定向到该员工的专属对话路由，避免丢失定制上下文
    const targetRoute = routeNameForEmployee(data.employee_id)
    if (targetRoute !== 'chat') {
      router.replace({ name: targetRoute, query: { conv: cid } })
      return
    }
    convId.value = cid
    currentEmp.value = data.employee_id
    hint.value = HINTS[data.employee_id] || '向数字员工提问吧。'
    // 恢复会话绑定的模型；未绑定时用列表中的默认模型
    currentModel.value = data.model || defaultModelBase()
    messages.value = []
    stream.resetPipeline()
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
  // 切换员工时重置为默认模型
  currentModel.value = defaultModelBase()
  try {
    const { data } = await api.post(`/employees/${empId}/conversations`)
    convId.value = data.conversation_id
  } catch { return }
  messages.value = []
  stream.resetPipeline()
  empMeta.value = '已切换到该员工（记忆跨会话保留）'
  await loadHistory(empId)
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

import { renderMd } from '../composables/useChatStream.js'

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
      await openConversation(qconv)
      // 会话存在且属编排型才加载该员工历史；否则回退选第一个员工
      if (!convId.value && data.length) await selectEmployee(data[0].id)
    } else if (data.length) {
      await selectEmployee(data[0].id)
    }
  } catch (e) {
    empMeta.value = '员工列表加载失败：' + e.message
  }
})

onBeforeUnmount(() => {
  stream.abortActiveStream()
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100%;
}
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
</style>
