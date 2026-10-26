<template>
  <div class="collection-backdrop" @click.self="requestClose">
    <section class="collection-dialog" role="dialog" aria-modal="true" aria-labelledby="collection-title">
      <header class="collection-header">
        <div class="collection-brand"><span class="collection-seal">察</span><div><span class="section-kicker">RESEARCH INTAKE</span><h2 id="collection-title">让小察去研究</h2></div></div>
        <button class="close-button" type="button" aria-label="关闭采集对话" :disabled="busy" @click="requestClose">×</button>
      </header>

      <div class="collection-context">
        <label for="collection-topic">写入主题</label>
        <select id="collection-topic" v-model="topicId" :disabled="busy || messages.length > 0">
          <option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option>
        </select>
        <label for="collection-category">所属领域</label>
        <select id="collection-category" v-model="categoryId" :disabled="busy || messages.length > 0">
          <option value="">由小察判断</option>
          <option v-for="category in selectedTopic?.categories || []" :key="category.id" :value="category.id">{{ category.name }}</option>
        </select>
        <span>小察会检索、核对来源，再自动整理标题、摘要和正文。</span>
      </div>

      <div ref="messageList" class="collection-messages" aria-live="polite" aria-label="与小察的研究对话">
        <div v-if="!messages.length" class="collection-welcome">
          <span class="welcome-glyph" aria-hidden="true">⌁</span>
          <h3>从一个信号开始</h3>
          <p>输入行业话题、事件或原文链接。小察会查找相关资料，优先核验一手来源，并把适合持续跟踪的观察写入工作台。</p>
          <div class="prompt-examples">
            <button type="button" :disabled="busy" @click="useExample('研究最近人形机器人进入工厂试点的进展，重点核对真实部署和商业化信号')">人形机器人落地进展</button>
            <button type="button" :disabled="busy" @click="useExample('分析这个链接的主要信息、发布背景与产业影响：')">分析一个网页链接</button>
          </div>
        </div>

        <template v-else>
          <div v-for="(message, index) in messages" :key="`${index}-${message.time}`" class="conversation-line" :class="message.role === 'user' ? 'user-line' : 'assistant-line'">
            <span v-if="message.role !== 'user'" class="assistant-avatar" aria-hidden="true">察</span>
            <div class="conversation-bubble" :class="message.role === 'user' ? 'user-bubble' : 'assistant-bubble'">
              <div v-if="message.role === 'user'" class="user-copy">{{ message.content }}</div>
              <template v-else>
                <div v-if="message.html" class="assistant-copy md" v-html="message.html"></div>
                <div v-else-if="message.content" class="assistant-copy md">{{ message.content }}</div>
                <div v-if="message.error" class="message-error" role="alert">{{ message.error }}</div>
                <div v-if="message.notice" class="message-notice">{{ message.notice }}</div>
                <div v-if="message.trace?.length" class="research-activity">
                  <span>研究过程</span>
                  <span v-for="(trace, traceIndex) in message.trace.filter(item => item.type === 'tool')" :key="trace.id || `${trace.name}-${traceIndex}`" class="activity-chip" :class="{ failed: trace.status === 'error' }">{{ toolLabel(trace.name) }}{{ trace.status === 'start' ? '中…' : trace.status === 'error' ? '失败' : '完成' }}</span>
                </div>
                <div v-if="!message.html && !message.content && !message.error" class="typing-indicator" aria-label="小察正在处理"><i></i><i></i><i></i></div>
              </template>
              <time>{{ message.time }}</time>
            </div>
          </div>
        </template>

        <div v-if="busy" class="collection-progress"><span class="progress-pulse"></span>{{ startingConversation ? '正在建立研究会话…' : '小察正在检索与核实信息，随后整理结构化观察…' }}</div>
        <div v-if="requestError" class="request-error" role="alert">{{ requestError }}</div>
        <div v-if="saveState === 'saved' && savedObservation" class="saved-card" role="status">
          <span class="saved-mark" aria-hidden="true">✓</span>
          <div><strong>研究观察已写入工作台</strong><span>{{ savedObservation.title }}</span></div>
          <button type="button" @click="$emit('open', savedObservation)">查看详情</button>
        </div>
        <div v-else-if="saveState === 'not-saved'" class="not-saved-note" role="status">本轮研究已结束，但没有检测到新入库的观察。你可以继续告诉小察补充核验，或明确要求“保存到工作台”。</div>
      </div>

      <form class="collection-composer" @submit.prevent="sendMessage">
        <textarea ref="inputElement" v-model="input" rows="2" maxlength="6000" :disabled="busy" placeholder="输入一个行业话题、事件，或粘贴原文链接…" @keydown.enter.exact.prevent="sendMessage"></textarea>
        <div class="composer-bottom"><span>尽量提供对象、时间范围或你关注的问题；也可以直接粘贴链接。</span><button class="send-button" type="submit" :disabled="busy || !input.trim()"><span v-if="!busy" aria-hidden="true">↗</span>{{ busy ? '研究中…' : '发送给小察' }}</button></div>
      </form>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import api from '../../../api.js'
import { renderMd, useChatStream } from '../../../composables/useChatStream.js'

const props = defineProps({
  topics: { type: Array, default: () => [] },
  initialTopic: { type: String, default: 'embodied-intelligence' },
  initialCategory: { type: String, default: '' },
})
const emit = defineEmits(['close', 'saved', 'open'])
const messages = ref([])
const input = ref('')
const topicId = ref(props.initialTopic)
const categoryId = ref(props.initialCategory)
const conversationId = ref('')
const startingConversation = ref(false)
const requestError = ref('')
const saveState = ref('')
const savedObservation = ref(null)
const savedIds = new Set()
const inputElement = ref(null)
const messageList = ref(null)
const stageStates = reactive({})
const stageDetail = reactive({})
const stream = useChatStream({
  stageStates,
  stageDetail,
  messages,
  scrollToBottom: () => nextTick(() => {
    if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
  }),
})
const busy = computed(() => startingConversation.value || stream.sending.value)
const selectedTopic = computed(() => props.topics.find(item => item.id === topicId.value))

watch(topicId, nextTopicId => {
  const validCategory = props.topics.find(item => item.id === nextTopicId)
    ?.categories?.some(category => category.id === categoryId.value)
  if (!validCategory) categoryId.value = ''
})

function nowTime() {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())
}

function toolLabel(name) {
  if (name === 'bocha_search' || name === 'newsnow') return '搜索来源'
  if (name === 'save_market_observation') return '保存观察'
  if (name === 'read_file') return '读取研究规程'
  if (/playwright|browser_(navigate|snapshot|click|type|fill)/i.test(name || '')) return '读取原文'
  return name || '研究工具'
}

function requestClose() {
  if (!busy.value) emit('close')
}

function useExample(value) {
  input.value = value
  nextTick(() => inputElement.value?.focus())
}

async function ensureConversation() {
  if (conversationId.value) return conversationId.value
  startingConversation.value = true
  requestError.value = ''
  try {
    const { data } = await api.post('/employees/market-intel/conversations')
    conversationId.value = data.conversation_id
    return conversationId.value
  } finally {
    startingConversation.value = false
  }
}

function collectionPrompt(query) {
  const topic = selectedTopic.value
  const categories = topic?.categories || []
  const categoryList = categories.map(category => `${category.id}（${category.name}）`).join('、')
  const categoryConstraint = categoryId.value
    ? `用户已指定所属细分领域：${categoryId.value}（${categories.find(category => category.id === categoryId.value)?.name || ''}）。`
    : `请从以下领域中判断唯一归属：${categoryList}。`
  return `这是小察行业研究工作台中的“采集并入库”任务。请使用行业深度研究规程，对用户提供的话题或链接进行检索、核验和整理；不要只给一段泛泛回答。

目标工作台主题：${topic?.name || topicId.value}（topic_id=${topicId.value}）
分类要求：${categoryConstraint}每条资讯只能保存一个 category_id；不得多选、不得留空。如果证据不足以明确归类，先继续核验，仍无法判断时解释原因并不要入库。
用户本轮输入：
${query}

执行要求：
1. 如果输入是 URL，优先读取原始页面；如果是话题，围绕它检索近期进展并优先使用官方公告、论文、监管/行业组织等一手来源，补充可信的独立来源交叉核对。
2. 依据来源提炼一条最值得持续观察的行业信号。记录中要包括清晰标题、列表摘要、结构化正文、来源链接、来源发布机构与日期；正文区分可核验事实、分析判断、待验证信息和后续观察信号。
3. 只写来源能够支持的内容，标出检索基准日期和证据限制。打不开或无法核实的内容要明确说，不要编造信息或链接。
4. 如果找到了足够可靠且适合持续跟踪的信息，必须调用 save_market_observation，将结构化字段保存到指定主题和唯一细分领域；category_id 必须使用上面的合法 ID，sources_json 必须是合法 JSON 数组并包含真实 URL。完成后在回复中给出记录标题、所属领域、主要结论、来源和保存结果。
5. 如果没有足够可靠的信息，不要为了入库而编造记录；说明查到了什么、缺少什么证据以及下一步可以怎么查。
6. 后续对话如果用户要求补充或更正，应继续核实，并把新的研究观察单独保存；不得声称更新了旧记录，除非实际执行了对应操作。`
}

async function refreshSavedObservation(convId) {
  const { data } = await api.get('/market-research/workbench', {
    params: { topic_id: topicId.value, limit: 100 },
  })
  const matches = (data.items || []).filter(item => item.conv_id === convId)
  const created = matches.find(item => !savedIds.has(item.id))
  if (created) {
    savedIds.add(created.id)
    savedObservation.value = created
    saveState.value = 'saved'
    emit('saved', created)
  } else if (!matches.length) {
    saveState.value = 'not-saved'
  }
}

async function sendMessage() {
  if (busy.value) return
  if (/^https?:\/\/\S+$/.test(input.value.trim())) {
    startingConversation.value = true; requestError.value = ''
    try {
      await api.post('/market-research/intake', { url: input.value.trim(), topic_id: topicId.value, category_id: categoryId.value })
      input.value = ''; emit('close')
    } catch (err) { requestError.value = err.response?.data?.detail || '链接提交失败，请重试' }
    finally { startingConversation.value = false }
    return
  }
  const query = input.value.trim()
  if (!query || busy.value) return
  requestError.value = ''
  saveState.value = ''
  let convId
  try {
    convId = await ensureConversation()
  } catch (error) {
    requestError.value = error.response?.data?.detail || '研究会话创建失败，请检查连接后重试。'
    return
  }
  input.value = ''
  messages.value.push({ role: 'user', content: query, time: nowTime() })
  const prompt = collectionPrompt(query)
  await stream.sendTo(`/api/conversations/${encodeURIComponent(convId)}/messages`, prompt, [], null, '', {
    appendUser: false,
    pinnedSkills: ['industry-deep-research'],
    pinnedSkillLabels: ['行业深度研究'],
  })
  const lastMessage = messages.value.at(-1)
  if (lastMessage?._streamTerminal && !lastMessage.error && lastMessage.status !== 'running') {
    try {
      await refreshSavedObservation(convId)
    } catch (error) {
      requestError.value = error.response?.data?.detail || '研究已完成，但工作台状态暂时无法刷新。'
    }
  }
}

function onKeydown(event) {
  if (event.key === 'Escape') requestClose()
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  nextTick(() => inputElement.value?.focus())
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  stream.abortActiveStream()
})
</script>

<style scoped>
.collection-backdrop { position: fixed; z-index: 30; inset: 56px 0 0; display: grid; place-items: center; padding: 18px; background: rgba(15,23,42,.52); backdrop-filter: blur(4px); }
.collection-dialog { display: grid; grid-template-rows: auto auto minmax(250px,1fr) auto; width: min(940px,100%); height: min(850px,calc(100vh - 96px)); overflow: hidden; border: 1px solid #dbe3ee; border-radius: 13px; background: #f8fafc; box-shadow: 0 26px 90px rgba(15,23,42,.24); }
.collection-header { display: flex; align-items: center; justify-content: space-between; padding: 17px 23px; border-bottom: 1px solid #e2e8f0; background: #fff; }
.collection-brand { display: flex; align-items: center; gap: 12px; }
.collection-seal { display: grid; width: 39px; height: 39px; place-items: center; border: 2px solid #eff6ff; border-radius: 50%; color: #fff; background: #3b82f6; font: 700 17px 'Noto Serif SC',serif; }
.section-kicker { color: #64748b; font: 600 10px 'DM Mono',monospace; letter-spacing: .11em; }
.collection-header h2 { margin: 3px 0 0; color: #0f172a; font: 650 20px 'Noto Serif SC','Noto Sans SC',serif; }
.close-button { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid transparent; border-radius: 50%; color: #64748b; background: transparent; cursor: pointer; font-size: 24px; line-height: 1; }
.close-button:hover:not(:disabled) { color: #1d4ed8; border-color: #dbeafe; background: #eff6ff; }
.close-button:disabled { opacity: .4; cursor: wait; }
.collection-context { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 13px; padding: 12px 23px; border-bottom: 1px solid #e2e8f0; background: #fff; }
.collection-context label { color: #475569; font-size: 13px; font-weight: 600; }
.collection-context select { min-width: 145px; padding: 7px 28px 7px 10px; border: 1px solid #cbd5e1; border-radius: 6px; color: #1e3a8a; background: #f8fbff; font: 600 13px 'Noto Sans SC',sans-serif; }
.collection-context select:focus { outline: 3px solid #dbeafe; border-color: #60a5fa; }
.collection-context select:disabled { opacity: .6; }
.collection-context > span { color: #94a3b8; font-size: 12px; }
.collection-messages { min-height: 0; overflow-y: auto; padding: 22px clamp(14px,4vw,38px); scroll-behavior: smooth; }
.collection-welcome { display: flex; min-height: 100%; flex-direction: column; align-items: center; justify-content: center; padding: 26px 10px; text-align: center; }
.welcome-glyph { display: grid; width: 55px; height: 55px; place-items: center; border: 1px solid #bfdbfe; border-radius: 15px; color: #2563eb; background: #fff; font-size: 34px; }
.collection-welcome h3 { margin: 17px 0 6px; color: #1e293b; font-size: 21px; font-weight: 650; }
.collection-welcome p { max-width: 540px; margin: 0; color: #64748b; font-size: 15px; line-height: 1.8; }
.prompt-examples { display: flex; flex-wrap: wrap; justify-content: center; gap: 9px; margin-top: 21px; }
.prompt-examples button { padding: 8px 12px; border: 1px solid #dbe3ee; border-radius: 99px; color: #475569; background: #fff; cursor: pointer; font: 13px 'Noto Sans SC',sans-serif; }
.prompt-examples button:hover:not(:disabled) { color: #1d4ed8; border-color: #bfdbfe; background: #eff6ff; }
.prompt-examples button:disabled { opacity: .5; cursor: wait; }
.conversation-line { display: flex; gap: 10px; margin: 0 auto 17px; max-width: 780px; }
.user-line { justify-content: flex-end; }
.assistant-line { align-items: flex-start; }
.assistant-avatar { display: grid; width: 29px; height: 29px; flex: 0 0 auto; place-items: center; border: 1px solid #dbeafe; border-radius: 50%; color: #2563eb; background: #fff; font: 600 13px 'Noto Serif SC',serif; }
.conversation-bubble { max-width: min(88%,700px); padding: 12px 15px 8px; border-radius: 11px; box-shadow: 0 2px 7px rgba(15,23,42,.035); }
.user-bubble { border: 1px solid #bfdbfe; border-top-right-radius: 4px; color: #1e3a8a; background: #eff6ff; }
.assistant-bubble { border: 1px solid #e2e8f0; border-top-left-radius: 4px; color: #334155; background: #fff; }
.user-copy { white-space: pre-wrap; font-size: 15px; line-height: 1.8; }
.assistant-copy { font-size: 15px; line-height: 1.85; overflow-wrap: anywhere; }
.assistant-copy :deep(p) { margin: 0 0 10px; }
.assistant-copy :deep(p:last-child) { margin-bottom: 5px; }
.assistant-copy :deep(h1),.assistant-copy :deep(h2),.assistant-copy :deep(h3) { margin: 13px 0 7px; color: #0f172a; font-size: 16px; line-height: 1.55; }
.assistant-copy :deep(ul),.assistant-copy :deep(ol) { margin: 7px 0 10px; padding-left: 23px; }
.assistant-copy :deep(li) { margin: 4px 0; }
.assistant-copy :deep(a) { color: #2563eb; text-decoration: underline; text-underline-offset: 2px; }
.conversation-bubble time { display: block; margin-top: 4px; color: #a0a9b8; font-size: 10px; text-align: right; }
.message-error { margin-top: 7px; color: #b91c1c; font-size: 13px; line-height: 1.7; }
.message-notice { margin-top: 7px; color: #1d4ed8; font-size: 12px; }
.research-activity { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 10px; padding-top: 8px; border-top: 1px solid #f1f5f9; color: #94a3b8; font-size: 11px; }
.activity-chip { padding: 3px 7px; border-radius: 99px; color: #2563eb; background: #eff6ff; }
.activity-chip.failed { color: #b91c1c; background: #fef2f2; }
.typing-indicator { display: flex; gap: 4px; padding: 5px 0 9px; }
.typing-indicator i { width: 6px; height: 6px; border-radius: 50%; background: #60a5fa; animation: type-bounce 1s infinite ease-in-out; }
.typing-indicator i:nth-child(2) { animation-delay: .12s; }
.typing-indicator i:nth-child(3) { animation-delay: .24s; }
@keyframes type-bounce { 0%,60%,100% { transform: translateY(0); opacity: .55; } 30% { transform: translateY(-4px); opacity: 1; } }
.collection-progress { display: flex; align-items: center; gap: 9px; max-width: 780px; margin: 6px auto; padding: 8px 11px; color: #2563eb; font-size: 12px; }
.progress-pulse { width: 7px; height: 7px; border-radius: 50%; background: #3b82f6; box-shadow: 0 0 0 4px #dbeafe; animation: pulse 1.5s infinite; }
@keyframes pulse { 50% { box-shadow: 0 0 0 7px rgba(219,234,254,0); } }
.request-error,.not-saved-note { max-width: 780px; margin: 9px auto; padding: 10px 12px; border: 1px solid #fecaca; border-radius: 7px; color: #b91c1c; background: #fff7f7; font-size: 13px; line-height: 1.7; }
.not-saved-note { border-color: #fde68a; color: #92400e; background: #fffbeb; }
.saved-card { display: flex; max-width: 780px; align-items: center; gap: 11px; margin: 12px auto 2px; padding: 11px 13px; border: 1px solid #bbf7d0; border-radius: 8px; color: #166534; background: #f0fdf4; }
.saved-mark { display: grid; width: 24px; height: 24px; flex: 0 0 auto; place-items: center; border-radius: 50%; color: #15803d; background: #dcfce7; font-weight: 700; }
.saved-card div { display: grid; min-width: 0; flex: 1; gap: 3px; }
.saved-card strong { font-size: 13px; }
.saved-card div span { overflow: hidden; color: #4b7c5b; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.saved-card button { padding: 6px 9px; border: 1px solid #86efac; border-radius: 6px; color: #166534; background: #fff; cursor: pointer; font: 600 12px 'Noto Sans SC',sans-serif; white-space: nowrap; }
.collection-composer { padding: 13px 20px 15px; border-top: 1px solid #dbe3ee; background: #fff; }
.collection-composer textarea { display: block; width: min(780px,100%); min-height: 58px; margin: 0 auto; padding: 11px 13px; resize: vertical; border: 1px solid #cbd5e1; border-radius: 8px; outline: none; color: #0f172a; background: #fff; font: 15px/1.7 'DM Sans','Noto Sans SC',sans-serif; }
.collection-composer textarea:focus { border-color: #60a5fa; box-shadow: 0 0 0 3px #dbeafe; }
.collection-composer textarea::placeholder { color: #94a3b8; }
.collection-composer textarea:disabled { color: #64748b; background: #f8fafc; }
.composer-bottom { display: flex; width: min(780px,100%); align-items: center; justify-content: space-between; gap: 12px; margin: 8px auto 0; }
.composer-bottom > span { color: #94a3b8; font-size: 11px; line-height: 1.5; }
.send-button { display: inline-flex; min-width: 112px; align-items: center; justify-content: center; gap: 7px; padding: 9px 12px; border: 1px solid #2563eb; border-radius: 7px; color: #fff; background: #3b82f6; cursor: pointer; font: 600 13px 'Noto Sans SC',sans-serif; white-space: nowrap; }
.send-button:hover:not(:disabled) { background: #2563eb; }
.send-button:disabled { opacity: .48; cursor: not-allowed; }
@media (prefers-reduced-motion: reduce) { .collection-dialog *, .collection-dialog *::before, .collection-dialog *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
@media (max-width: 620px) {
  .collection-backdrop { inset: 0; padding: 8px; }
  .collection-dialog { width: 100%; height: 100%; max-height: 100%; border-radius: 10px; }
  .collection-header { padding: 13px 15px; }
  .collection-context { padding: 10px 15px; }
  .collection-context > span { width: 100%; }
  .collection-messages { padding: 16px 11px; }
  .collection-composer { padding: 11px 12px max(12px,env(safe-area-inset-bottom)); }
  .composer-bottom { align-items: flex-end; }
  .composer-bottom > span { max-width: 62%; }
  .conversation-bubble { max-width: 91%; padding: 11px 12px 7px; }
  .collection-welcome h3 { font-size: 19px; }
  .collection-welcome p { font-size: 14px; }
  .saved-card { align-items: flex-start; flex-wrap: wrap; }
  .saved-card button { margin-left: 35px; }
}
</style>
