// IM / 对话工作台共用的 SSE 流式聊天逻辑：流式 Markdown、工具 trace、子代理、审批、错误提示。
import { nextTick, ref } from 'vue'
import { marked } from 'marked'

const BAD_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'LINK', 'META', 'BASE', 'FORM'])
const SAFE_PROTOCOLS = ['http:', 'https:', 'mailto:', 'tel:']
const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'formaction', 'action', 'poster', 'background'])

function isSafeUrl(v) {
  const t = (v || '').trim()
  if (!t || t.startsWith('#') || t.startsWith('/') || t.startsWith('./') ||
      t.startsWith('../') || t.startsWith('?')) return true
  const idx = t.indexOf(':')
  if (idx <= 0) return true
  return SAFE_PROTOCOLS.includes(t.slice(0, idx).toLowerCase())
}

function sanitizeHtml(html) {
  const tpl = document.createElement('template')
  tpl.innerHTML = html
  for (const el of Array.from(tpl.content.querySelectorAll('*'))) {
    if (BAD_TAGS.has(el.tagName)) { el.remove(); continue }
    for (const attr of Array.from(el.attributes)) {
      const n = attr.name.toLowerCase()
      const v = (attr.value || '').trim()
      if (n.startsWith('on')) el.removeAttribute(attr.name)
      else if (n === 'style') el.removeAttribute(attr.name)
      else if (URL_ATTRS.has(n) && !isSafeUrl(v)) el.removeAttribute(attr.name)
    }
  }
  return tpl.innerHTML
}

export function renderMd(md) {
  try { return sanitizeHtml(marked.parse(md || '')) }
  catch { return `<pre>${String(md || '').replace(/</g, '&lt;')}</pre>` }
}

export function useChatStream({ stageStates, stageDetail, messages, scrollToBottom }) {
  const sending = ref(false)
  let activeController = null

  function abortActiveStream() {
    if (activeController) {
      activeController.abort()
      activeController = null
    }
  }

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

  function touch() {
    messages.value = [...messages.value]
    scrollToBottom?.()
  }

  function handleEvent(ev, msgIdx) {
    const msg = messages.value[msgIdx]
    if (!msg) return
    if (ev.type === 'stage') {
      if (ev.stage === 'report' && ev.status === 'done') {
        setStage('planning', 'done'); setStage('skill', 'done'); setStage('report', 'done', '')
      } else {
        setStage(ev.stage, ev.status, ev.detail_text)
      }
    } else if (ev.type === 'thinking') {
      if (!msg.trace) msg.trace = []
      let box = msg.trace.find(t => t.type === 'think' && !t._closed)
      if (!box) { box = { type: 'think', content: '' }; msg.trace.push(box) }
      box.content += ev.content
      touch()
    } else if (ev.type === 'token') {
      if (!msg._md) msg._md = ''
      msg._md += ev.content
      msg.html = renderMd(msg._md)
      msg.content = ''
      touch()
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
      touch()
    } else if (ev.type === 'subagent') {
      if (!msg.subagents) msg.subagents = []
      let sa = msg.subagents.find(s => s.name === ev.name)
      if (!sa) {
        sa = { name: ev.name, status: ev.status, output: '' }
        msg.subagents.push(sa)
      }
      sa.status = ev.status
      if (ev.output) sa.output = ev.output
      touch()
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
      touch()
    } else if (ev.type === 'error') {
      if (!msg.trace) msg.trace = []
      msg.trace.push({ type: 'tool', name: '⚠ ' + ev.message, args: '', status: 'done' })
      touch()
    }
  }

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
    const msg = messages.value[msgIdx]
    if (msg && msg.trace && !msg.trace.length) delete msg.trace
    scrollToBottom?.()
  }

  async function sendTo(endpoint, text) {
    if (!endpoint || sending.value) return
    const trimmed = String(text || '').trim()
    if (!trimmed) return
    const now = new Date()
    const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    messages.value.push({ role: 'user', content: trimmed, time })
    const botIdx = messages.value.length
    messages.value.push({ role: 'bot', content: '', html: '', _md: '', trace: [], time })
    sending.value = true
    resetPipeline()
    const controller = new AbortController()
    abortActiveStream()
    activeController = controller
    try {
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({ message: trimmed }),
        signal: controller.signal,
      })
      await readStream(resp, botIdx)
      if (activeController === controller) activeController = null
    } catch (e) {
      if (e.name !== 'AbortError') messages.value[botIdx].content = '⚠ 连接失败：' + e.message
      if (activeController === controller) activeController = null
    }
    sending.value = false
    scrollToBottom?.()
  }

  async function decide(approvalId, decision, msgIdx) {
    const msg = messages.value[msgIdx]
    if (!msg) return
    msg.approval.resolved = decision === 'approve' ? '✓ 已批准' : '✗ 已拒绝'
    const now = new Date()
    const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    const botIdx = messages.value.length
    messages.value.push({ role: 'bot', content: '', html: '', _md: '', trace: [], time })
    sending.value = true
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
      await readStream(resp, botIdx)
      if (activeController === controller) activeController = null
    } catch (e) {
      if (e.name !== 'AbortError') messages.value[botIdx].content = '⚠ ' + e.message
      if (activeController === controller) activeController = null
    }
    sending.value = false
  }

  return {
    sending,
    sendTo,
    decide,
    setStage,
    resetPipeline,
    abortActiveStream,
  }
}
