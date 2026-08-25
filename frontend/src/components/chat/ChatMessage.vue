<!--
单条消息组件：用户消息 / bot 消息（含 trace、子代理、审批、评价）
emit: rated(msg, rating, reason)
-->
<template>
  <div>
    <!-- 用户消息 -->
    <div v-if="msg.role === 'user'" class="msg-wrapper user-wrapper">
      <div class="msg user">
        <div v-if="msg.content" class="msg-text">{{ msg.content }}</div>
        <div v-if="msg.attachments && msg.attachments.length" class="user-atts">
          <span v-for="(a, ai) in msg.attachments" :key="ai" class="user-att" :title="a.path">
            📎 {{ a.name }}<span v-if="a.size" class="user-att-size">（{{ fmtSize(a.size) }}）</span>
          </span>
        </div>
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

        <!-- 评价按钮 -->
        <template v-if="msg.run_id && !msg._evaluated">
          <span class="eval-btn" @click="$emit('rate', msg, 1, idx)" title="有用">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
          </span>
          <span class="eval-btn" @click="showReason = !showReason" title="没用">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h3a2 2 0 012 2v7a2 2 0 01-2 2h-3"/></svg>
          </span>
        </template>
        <span v-else-if="msg._evaluated === 1" class="eval-btn evaluated-up" title="已评价有用">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3"/></svg>
        </span>
        <span v-else-if="msg._evaluated === -1" class="eval-btn evaluated-down" title="已评价没用">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h3a2 2 0 012 2v7a2 2 0 01-2 2h-3"/></svg>
        </span>
      </div>

      <!-- 点踩原因 -->
      <ReasonPopover
        :show="showReason"
        :selected="reasonSelected"
        @select="reasonSelected = $event"
        @cancel="closeReason"
        @confirm="(val) => { $emit('rate', msg, -1, idx, val); closeReason() }"
      />

      <!-- Trace -->
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

      <!-- 子代理 -->
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
          <n-button size="small" type="success" @click="$emit('approve', msg.approval.id, idx)">批准</n-button>
          <n-button size="small" type="error" @click="$emit('reject', msg.approval.id, idx)">拒绝</n-button>
        </div>
        <div v-else class="approval-resolved">{{ msg.approval.resolved }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ReasonPopover from './ReasonPopover.vue'

const props = defineProps({
  msg: { type: Object, required: true },
  idx: { type: Number, required: true },
})
defineEmits(['rate', 'approve', 'reject'])

const showReason = ref(false)
const reasonSelected = ref(null)

function closeReason() {
  showReason.value = false
  reasonSelected.value = null
}

function copyText(text) {
  if (!text) return
  navigator.clipboard.writeText(typeof text === 'string' ? text.replace(/<[^>]+>/g, '') : '').catch(() => {})
}

function fmtSize(n) {
  if (!n) return ''
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB'
  if (n >= 1024) return Math.round(n / 1024) + 'KB'
  return n + 'B'
}

function subagentStatusText(status) {
  const map = { started: '运行中', completed: '已完成', failed: '失败', interrupted: '已中断' }
  return map[status] || status
}
</script>

<style scoped>
.msg-wrapper { display: flex; flex-direction: column; gap: 2px; }
/* 用户消息：wrapper 撑满整行（时间/按钮贴真正的右边缘），宽度限制放在气泡上保持聊天气泡感；
   bot 回复（长文/表格/代码）放宽到接近全宽，避免右侧大片空白 */
.user-wrapper { align-self: stretch; align-items: flex-end; }
.bot-wrapper { max-width: 92%; align-self: flex-start; align-items: flex-start; position: relative; }
.msg { padding: 12px 16px; border-radius: 16px; font-size: 14px; line-height: 1.7; word-break: break-word; animation: msg-in 0.25s ease-out; }
@keyframes msg-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.msg.user { align-self: flex-end; max-width: 76%; background: linear-gradient(135deg, #3b82f6, #2563eb); color: #fff; border-bottom-right-radius: 4px; }
.user-atts { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
.user-att {
  background: rgba(255,255,255,0.18); border: 1px solid rgba(255,255,255,0.35);
  border-radius: 6px; padding: 3px 8px; font-size: 12px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.user-att-size { opacity: 0.75; }
.msg.bot { align-self: flex-start; background: #ffffff; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,0.02); }
.msg-meta { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #94a3b8; }
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

/* 评价按钮 */
.eval-btn {
  cursor: pointer; display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px; border-radius: 8px;
  color: #94a3b8; transition: all 0.2s ease;
}
.eval-btn:hover { background: #f1f5f9; color: #475569; transform: scale(1.1); }
.eval-btn.evaluated-up { color: #10b981; background: #ecfdf5; }
.eval-btn.evaluated-down { color: #ef4444; background: #fef2f2; }
</style>
