<!-- 执行过程追踪：按会话展示运行记录，展开查看 LLM/工具调用时间线 -->
<template>
  <div class="trace-layout">
    <!-- 左侧：run 列表 -->
    <div class="runs-panel">
      <div v-if="!convId" class="trace-empty">
        <p style="font-size:15px;margin-bottom:8px">🔎 执行过程</p>
        <p>请从对话页或历史页点击「执行过程」链接进入</p>
        <n-button style="margin-top:16px" type="primary" ghost @click="$router.push({name:'history'})">前往历史对话</n-button>
      </div>
      <div v-else-if="loading" class="trace-empty">加载中…</div>
      <div v-else-if="!runs.length" class="trace-empty">该会话暂无执行记录</div>
      <div
        v-for="r in runs" :key="r.run_id"
        class="run-card tech-card"
        :class="{ active: r.run_id === selectedRunId }"
        @click="loadDetail(r.run_id)"
      >
        <div class="run-q">{{ r.input_preview || (r.kind === 'resume' ? '（审批恢复执行）' : '（无输入预览）') }}</div>
        <div class="run-meta">
          <n-tag :type="statusType(r.status)" size="tiny" round bordered>{{ statusText(r.status) }}</n-tag>
          <span>🧠 {{ r.llm_calls || 0 }}</span>
          <span>🔧 {{ r.tool_calls || 0 }}</span>
          <span>⏱ {{ ms(r.duration_ms) }}</span>
          <span>{{ fmtTime(r.started_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 右侧：详情 -->
    <div class="detail-panel">
      <div v-if="!selectedRun" class="trace-empty">选择左侧一次运行，查看执行时间线</div>
      <template v-else>
        <!-- 摘要 -->
        <div class="summary-card tech-card">
          <div class="kv"><b>{{ statusText(selectedRun.status) }}</b><span>状态</span></div>
          <div class="kv"><b>{{ ms(selectedRun.duration_ms) }}</b><span>总耗时</span></div>
          <div class="kv"><b>{{ selectedRun.llm_calls || 0 }}</b><span>模型调用</span></div>
          <div class="kv"><b>{{ selectedRun.tool_calls || 0 }}</b><span>工具调用</span></div>
          <div class="kv"><b>{{ selectedRun.total_tokens || 0 }}</b><span>tokens</span></div>
          <div v-if="selectedRun.error" class="err-line">❌ {{ selectedRun.error }}</div>
        </div>

        <!-- 事件时间线 -->
        <n-collapse v-if="selectedRun.events && selectedRun.events.length" accordion>
          <n-collapse-item v-for="(e, i) in selectedRun.events" :key="i" :name="String(i)">
            <template #header>
              <span class="ev-icon">{{ e.etype === 'llm' ? '🧠' : '🔧' }}</span>
              <span class="ev-name">{{ e.name }}</span>
              <n-tag :type="e.status === 'ok' ? 'success' : (e.status === 'error' ? 'error' : 'info')" size="tiny" round bordered>
                {{ e.status === 'ok' ? '成功' : (e.status === 'error' ? '失败' : '未完成') }}
              </n-tag>
              <span v-if="e.tokens" class="ev-tokens">{{ e.tokens }} tok</span>
              <span class="ev-time">{{ ms(e.duration_ms) }} · {{ fmtClock(e.started_at) }}</span>
            </template>
            <div class="ev-body">
              <div class="ev-section">输入</div>
              <pre>{{ e.input || '（空）' }}</pre>
              <div class="ev-section">输出</div>
              <pre>{{ e.output || '（空）' }}</pre>
            </div>
          </n-collapse-item>
        </n-collapse>
        <div v-else class="trace-empty">本次运行没有捕获到事件</div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import api from '../api.js'

defineOptions({ name: 'TraceView' })

const route = useRoute()
const convId = route.query.conv || ''
const convTitle = ref('')
const runs = ref([])
const selectedRun = ref(null)
const selectedRunId = ref(null)
const loading = ref(true)

const STATUS_MAP = { done: { type: 'success', text: '完成' }, error: { type: 'error', text: '出错' }, interrupted: { type: 'warning', text: '等待审批' }, running: { type: 'info', text: '运行中' } }
function statusType(s) { return (STATUS_MAP[s] || { type: 'default' }).type }
function statusText(s) { return (STATUS_MAP[s] || { text: s }).text }
function ms(v) { if (v == null) return '-'; return v >= 1000 ? (v / 1000).toFixed(1) + 's' : v + 'ms' }
function fmtTime(s) { return (s || '').replace('T', ' ').slice(5, 16) }
function fmtClock(s) { return (s || '').slice(11) }

async function loadRuns() {
  if (!convId) { loading.value = false; return }
  try {
    const { data } = await api.get(`/conversations/${convId}/traces`)
    if (data.error) { loading.value = false; return }
    convTitle.value = data.title || convId
    runs.value = data.runs || []
    if (runs.value.length) await loadDetail(runs.value[0].run_id)
  } catch {} finally {
    loading.value = false
  }
}

async function loadDetail(runId) {
  selectedRunId.value = runId
  try {
    const { data } = await api.get(`/traces/${runId}`)
    if (!data.error) selectedRun.value = data
  } catch {}
}

onMounted(loadRuns)
</script>

<style scoped>
.trace-layout { display: flex; gap: 16px; height: 100%; padding: 16px; }

.runs-panel { width: 340px; flex-shrink: 0; overflow-y: auto; }
.run-card { padding: 12px 14px; margin-bottom: 10px; cursor: pointer; }
.run-card.active { border-color: #3b82f6; box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.12); }
.run-q { font-size: 13px; font-weight: 500; color: #0f172a; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-meta { margin-top: 6px; font-size: 11px; color: #64748b; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }

.detail-panel { flex: 1; min-width: 0; overflow-y: auto; }
.summary-card { padding: 16px 20px; margin-bottom: 16px; display: flex; gap: 32px; flex-wrap: wrap; }
.kv b { font-size: 18px; display: block; color: #0f172a; }
.kv span { font-size: 11px; color: #64748b; }
.err-line { color: #ef4444; font-size: 12px; margin-top: 6px; width: 100%; }

.ev-icon { margin-right: 6px; }
.ev-name { font-weight: 500; margin-right: 8px; color: #0f172a; }
.ev-tokens { font-size: 11px; color: #94a3b8; margin-left: 8px; }
.ev-time { margin-left: auto; font-size: 11px; color: #94a3b8; white-space: nowrap; }
.ev-body { padding: 8px 0; }
.ev-section { font-size: 11px; color: #64748b; font-weight: 600; margin: 8px 0 4px; }
.ev-body pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 7px; padding: 10px; font-size: 12px; white-space: pre-wrap; word-break: break-all; max-height: 260px; overflow: auto; }

.trace-empty { padding: 50px; text-align: center; color: #94a3b8; font-size: 13px; }
</style>
