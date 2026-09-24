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

// 报告 HTML 提取：从 markdown 文本中抽出 REPORT_HTML_START/END 包裹的整段 HTML
// 让前端用 iframe srcdoc 渲染（renderMd 的 sanitize 会剥掉 script/style，必须独立通道）
function isRenderableReportHtml(html) {
  const s = (html || '').trim()
  if (!s || s.length < 80) return false
  return /<!doctype\s+html/i.test(s) ||
    (/<html[\s>]/i.test(s) && /<\/html>/i.test(s)) ||
    (/<(?:head|body|div|section|main|script|style|canvas|svg)[\s>]/i.test(s) &&
      /<\/(?:div|section|main|script|style|canvas|svg)>/i.test(s))
}

export function extractReport(md) {
  const re = /<!--\s*REPORT_HTML_START\s*-->([\s\S]*?)<!--\s*REPORT_HTML_END\s*-->/
  const m = (md || '').match(re)
  if (!m) return { reportHtml: '', cleanedMd: md || '' }
  let html = m[1].trim()
  // 兼容模型把整段包在 ```html 围栏里的情况
  const fence = html.match(/^```(?:html)?\s*\n([\s\S]*?)\n```$/)
  if (fence) html = fence[1].trim()
  if (!isRenderableReportHtml(html)) {
    return { reportHtml: '', cleanedMd: md || '' }
  }
  // 删掉报告段（含外层围栏），保留前后文本
  const cleanedMd = (md || '').replace(re, '').trim()
  return { reportHtml: html, cleanedMd }
}

export function useChatStream({ stageStates, stageDetail, messages, scrollToBottom }) {
  const sending = ref(false)
  let activeController = null
  let activeMessageIdx = null

  function abortActiveStream() {
    if (activeController) {
      activeController.abort()
      activeController = null
    }
  }

  function stopActiveStream() {
    const msg = activeMessageIdx == null ? null : messages.value[activeMessageIdx]
    if (!activeController || !msg) return
    msg.status = 'stopped'
    msg._streamTerminal = true
    setStage('report', 'stopped', '已由用户停止')
    touch()
    abortActiveStream()
  }

  function resetPipeline() {
    Object.keys(stageStates).forEach(k => delete stageStates[k])
    Object.keys(stageDetail).forEach(k => delete stageDetail[k])
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
      setStage(ev.stage, ev.status, ev.detail_text)
    } else if (ev.type === 'thinking') {
      if (!msg.trace) msg.trace = []
      let box = msg.trace.find(t => t.type === 'think' && !t._closed)
      if (!box) { box = { type: 'think', content: '' }; msg.trace.push(box) }
      box.content += ev.content
      touch()
    } else if (ev.type === 'token') {
      setStage('report', 'active', '正在生成回复')
      if (!msg._md) msg._md = ''
      msg._md += ev.content
      // 报告生成技能输出 HTML 时，抽出整段 HTML 走 iframe srcdoc 渲染，
      // markdown 渲染的是去掉报告段后的剩余文本（如引言/小节说明）
      const { reportHtml, cleanedMd } = extractReport(msg._md)
      if (reportHtml) msg.reportHtml = reportHtml
      msg.html = renderMd(cleanedMd)
      msg.content = ''
      touch()
    } else if (ev.type === 'tool') {
      if (!msg.trace) msg.trace = []
      const args = ev.args && Object.keys(ev.args).length ? JSON.stringify(ev.args) : ''
      if (ev.status === 'start') {
        msg.trace.push({ type: 'tool', id: ev.id || '', name: ev.name, args, status: 'start' })
      } else {
        const st = ev.status === 'error' ? 'error' : 'done'
        const pending = msg.trace.find(t => t.type === 'tool' && t.status === 'start' &&
          (ev.id ? t.id === ev.id : t.name === ev.name))
        if (pending) { pending.status = st; pending.preview = ev.preview || '' }
        else msg.trace.push({ type: 'tool', id: ev.id || '', name: ev.name, args, status: st, preview: ev.preview || '' })
      }
      const tools = msg.trace.filter(t => t.type === 'tool')
      const hasError = tools.some(t => t.status === 'error')
      const hasPending = tools.some(t => t.status === 'start')
      setStage('skill', hasPending ? 'active' : hasError ? 'error' : 'done',
        `${ev.name || '工具'}：${ev.status === 'start' ? '调用中' : ev.status === 'error' ? '调用失败' : '调用完成'}`)
      touch()
    } else if (ev.type === 'sql') {
      // 数据分析专家：sql_db_query 工具执行后回传 SQL 语句，由 SqlViewer 渲染
      // 同一次工具调用可能产生多条结果，用数组承接避免覆盖
      if (!msg.sql) msg.sql = ev.sql || ''
      else if (ev.sql) msg.sql += '\n;\n' + ev.sql
      touch()
    } else if (ev.type === 'file') {
      // 数字员工产物文件（Word 方案/纪要/CSV 等）：渲染成可下载/可预览的文件卡片
      if (!msg.files) msg.files = []
      if (!msg.files.some(f => f.path === ev.path)) {
        msg.files.push({ artifact_id: ev.artifact_id, conv_id: ev.conv_id,
          name: ev.name, path: ev.path, size: ev.size,
          artifact_type: ev.artifact_type || 'file' })
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
      if (ev.items?.length) {
        const allDone = ev.items.every(t => t.status === 'completed')
        setStage('planning', allDone ? 'done' : 'active',
          ev.items.map(t => `${t.status === 'completed' ? '☑' : '☐'} ${t.content}`).join('\n'))
      }
    } else if (ev.type === 'approval_required') {
      msg.approval = {
        id: ev.approval_id,
        tool: ev.tool,
        args: ev.args ? JSON.stringify(ev.args) : '',
        resolved: null,
      }
      msg._streamTerminal = true
      setStage('skill', 'active', `审批中：${ev.tool}`)
      touch()
    } else if (ev.type === 'error') {
      // 运行级错误：气泡内直接显示错误卡（不再藏进折叠 trace），流水线置错
      msg.error = ev.message || '任务执行出错，请稍后重试'
      msg.status = 'error'
      msg._streamTerminal = true
      setStage('report', 'error', msg.error)
      touch()
    } else if (ev.type === 'message_end') {
      // 运行结束元信息：run_id 供评价按钮与 Trace 跳转使用（组件拆分时曾遗漏）
      msg.run_id = ev.run_id
      msg.message_id = ev.message_id
      msg.employee_id = ev.employee_id
      msg.conversation_id = ev.conversation_id
      msg._streamTerminal = true
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
    if (msg && !msg._streamTerminal) {
      msg.error = msg._md || msg.html || msg.content
        ? '连接已中断，当前结果可能不完整，请刷新历史或继续追问。'
        : '连接已中断，未收到最终结果，请重试。'
      msg.status = 'interrupted'
      setStage('report', 'error', msg.error)
      touch()
    }
    if (msg && msg.trace && !msg.trace.length) delete msg.trace
    scrollToBottom?.()
  }

  async function sendTo(endpoint, text, attachments = [], dataSource = null, model = '', options = {}) {
    if (!endpoint || sending.value) return
    const trimmed = String(text || '').trim()
    if (!trimmed && !attachments.length) return
    const now = new Date()
    const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
    const userMsg = { role: 'user', content: trimmed, time }
    if (attachments.length) userMsg.attachments = attachments
    if (options.appendUser !== false) messages.value.push(userMsg)
    const botIdx = messages.value.length
    const botMsg = {
      role: 'bot', content: '', html: '', _md: '', trace: [], time,
      _retryPayload: { endpoint, text: trimmed, attachments, dataSource, model },
    }
    messages.value.push(botMsg)
    sending.value = true
    activeMessageIdx = botIdx
    resetPipeline()
    setStage('input', 'done', new Date().toLocaleTimeString())
    const controller = new AbortController()
    abortActiveStream()
    activeController = controller
    try {
      // 数据问数页前端选了数据源后，把 data_source 作为 query param 传到后端，
      // 后端按 kind（database/knowledge_base/connector）注入到对应工具的 contextvar。
      // dataSource 形如 {kind:'database', id:'ds:xxx'} / {kind:'knowledge_base', id:'kb:yyy'}
      let url = endpoint
      if (dataSource && dataSource.id) {
        const dsJson = JSON.stringify(dataSource)
        url += (url.includes('?') ? '&' : '?') + 'data_source=' + encodeURIComponent(dsJson)
      }
      const resp = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
        },
        body: JSON.stringify({ message: trimmed, attachments, model: model || '' }),
        signal: controller.signal,
      })
      if (!resp.ok) throw new Error(`服务返回 HTTP ${resp.status}`)
      options.onAccepted?.()
      await readStream(resp, botIdx)
      if (activeController === controller) activeController = null
    } catch (e) {
      const msg = messages.value[botIdx]
      if (e.name !== 'AbortError' && msg) {
        msg.error = `请求失败：${e.message || '网络连接不可用'}`
        msg.status = 'error'
        setStage('report', 'error', msg.error)
        touch()
      } else if (e.name === 'AbortError' && msg && !msg._streamTerminal) {
        msg.status = 'interrupted'
        msg.error = '连接已中断，当前结果可能不完整。'
        setStage('report', 'error', msg.error)
        touch()
      }
      if (activeController === controller) activeController = null
    }
    if (activeMessageIdx === botIdx) activeMessageIdx = null
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
    activeMessageIdx = botIdx
    try {
      const resp = await fetch(`/api/approvals/${approvalId}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
        body: JSON.stringify({ decision }),
        signal: controller.signal,
      })
      if (!resp.ok) throw new Error(`服务返回 HTTP ${resp.status}`)
      await readStream(resp, botIdx)
      if (activeController === controller) activeController = null
    } catch (e) {
      const reply = messages.value[botIdx]
      if (e.name !== 'AbortError' && reply) {
        reply.error = `审批恢复失败：${e.message || '网络连接不可用'}`
        reply.status = 'error'
        touch()
      } else if (e.name === 'AbortError' && reply && !reply._streamTerminal) {
        reply.status = 'interrupted'
        reply.error = '审批恢复连接已中断，请刷新会话确认审批状态。'
        touch()
      }
      if (activeController === controller) activeController = null
    }
    if (activeMessageIdx === botIdx) activeMessageIdx = null
    sending.value = false
  }

  return {
    sending,
    sendTo,
    decide,
    setStage,
    resetPipeline,
    abortActiveStream,
    stopActiveStream,
  }
}
