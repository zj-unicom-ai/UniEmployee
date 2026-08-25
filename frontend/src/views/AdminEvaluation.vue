<!-- 运行评估：被动统计 + 用户反馈明细，管理员专属 -->
<template>
  <div class="eval-page">
    <h2 style="margin:0 0 16px;font-size:18px;color:#0f172a">运行评估</h2>

    <!-- 筛选条 -->
    <div class="filter-bar">
      <n-select v-model:value="filterEmp" :options="empOptions" clearable placeholder="全部员工"
                size="small" style="width:180px" @update:value="loadStats" />
      <n-select v-model:value="filterPeriod" :options="periodOptions" size="small"
                style="width:120px" @update:value="loadStats" />
    </div>

    <!-- 指标卡片 -->
    <div class="stat-cards">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_runs }}</div>
        <div class="stat-label">总运行次数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ fmtMs(stats.avg_duration_ms) }}</div>
        <div class="stat-label">平均响应时间</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ fmtNum(stats.avg_tokens) }}</div>
        <div class="stat-label">平均 Token</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" :class="{ 'err': stats.error_rate > 0.05 }">
          {{ (stats.error_rate * 100).toFixed(1) }}%
        </div>
        <div class="stat-label">错误率</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ (stats.tool_success_rate * 100).toFixed(1) }}%</div>
        <div class="stat-label">工具成功率</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ satisfactionText }}</div>
        <div class="stat-label">满意度</div>
      </div>
    </div>

    <!-- 日趋势 + Top 工具 -->
    <div class="two-col">
      <div class="col-card">
        <div class="col-title">日趋势（近 30 天）</div>
        <div v-if="!stats.daily_trend.length" class="empty-text">暂无数据</div>
        <div v-else class="trend-bars">
          <div v-for="(d, i) in stats.daily_trend" :key="i" class="trend-row">
            <span class="trend-date">{{ d.date.slice(5) }}</span>
            <span class="trend-emp">{{ empNames[d.employee_id] || d.employee_id }}</span>
            <div class="trend-bar-wrap">
              <div class="trend-bar" :style="{ width: barWidth(d.runs) }">
                <span class="bar-label">{{ d.runs }}</span>
              </div>
              <div v-if="d.errors" class="trend-bar errors" :style="{ width: barWidth(d.errors) }">
                <span class="bar-label">{{ d.errors }}</span>
              </div>
            </div>
            <span class="trend-ms">{{ fmtMs(d.avg_ms) }}</span>
          </div>
        </div>
      </div>
      <div class="col-card">
        <div class="col-title">Top 工具</div>
        <div v-if="!stats.top_tools.length" class="empty-text">暂无数据</div>
        <div v-else class="tool-list">
          <div v-for="(t, i) in stats.top_tools" :key="t.name" class="tool-row">
            <span class="tool-rank">{{ i + 1 }}</span>
            <span class="tool-name">{{ t.name }}</span>
            <span class="tool-cnt">{{ t.count }} 次</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 反馈明细 -->
    <div class="feedback-section">
      <div class="feedback-header">
        <span class="col-title">用户反馈明细</span>
        <div style="display:flex;gap:8px">
          <n-select v-model:value="fbFilterRating" :options="fbRatingOptions" clearable
                    placeholder="全部评分" size="small" style="width:120px" @update:value="loadFeedback" />
        </div>
      </div>
      <div v-if="!feedback.length" class="empty-text">暂无反馈数据</div>
      <div v-else class="fb-list">
        <div v-for="f in feedback" :key="f.id" class="fb-row">
          <span class="fb-rating" :class="f.rating === 1 ? 'up' : 'down'">
            {{ f.rating === 1 ? '👍' : '👎' }}
          </span>
          <span class="fb-emp">{{ empNames[f.employee_id] || f.employee_id }}</span>
          <span v-if="f.reason" class="fb-reason">{{ reasonLabel(f.reason) }}</span>
          <span class="fb-time">{{ fmtTime(f.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import api from '../api.js'

defineOptions({ name: 'AdminEvaluation' })

const filterEmp = ref(null)
const filterPeriod = ref('30d')
const fbFilterRating = ref(null)
const stats = reactive({
  total_runs: 0, avg_duration_ms: 0, avg_tokens: 0,
  error_rate: 0, tool_success_rate: 0,
  satisfaction: { total: 0, thumbs_up: 0, thumbs_down: 0, score: 0 },
  top_tools: [], daily_trend: [],
})
const feedback = ref([])
const employees = ref([])
const empNames = reactive({})

const empOptions = computed(() =>
  employees.value.map(e => ({ label: `${e.name || e.id}`, value: e.id }))
)
const periodOptions = [
  { label: '近 7 天', value: '7d' },
  { label: '近 30 天', value: '30d' },
  { label: '近 90 天', value: '90d' },
]
const fbRatingOptions = [
  { label: '👍 有用', value: 1 },
  { label: '👎 没用', value: -1 },
]
const REASON_MAP = {
  irrelevant: '答非所问', factual_error: '事实错误',
  wrong_process: '流程不对', too_slow: '太慢', other: '其他',
}
const satisfactionText = computed(() => {
  const s = stats.satisfaction
  if (!s.total) return 'N/A'
  return `${(s.score * 100).toFixed(0)}%（${s.thumbs_up}👍 / ${s.thumbs_down}👎）`
})

function fmtMs(ms) { return ms ? `${(ms / 1000).toFixed(1)}s` : 'N/A' }
function fmtNum(n) { return n ? Math.round(n).toLocaleString() : '0' }
function fmtTime(s) { return (s || '').replace('T', ' ').slice(0, 16) }
function reasonLabel(r) { return REASON_MAP[r] || r }
function barWidth(cnt) {
  const max = Math.max(...stats.daily_trend.map(d => d.runs), 1)
  return `${Math.max((cnt / max) * 100, 4)}%`
}

async function loadStats() {
  try {
    const params = { period: filterPeriod.value }
    if (filterEmp.value) params.employee_id = filterEmp.value
    const { data } = await api.get('/admin/evaluation/stats', { params })
    Object.assign(stats, data)
  } catch {}
}

async function loadFeedback() {
  try {
    const params = { limit: 50 }
    if (filterEmp.value) params.employee_id = filterEmp.value
    if (fbFilterRating.value !== null) params.rating = fbFilterRating.value
    const { data } = await api.get('/admin/evaluation/feedback', { params })
    feedback.value = data
  } catch {}
}

onMounted(async () => {
  try {
    const { data } = await api.get('/admin/employees')
    employees.value = data
    data.forEach(e => { empNames[e.id] = e.name || e.id })
  } catch {}
  await Promise.all([loadStats(), loadFeedback()])
})
</script>

<style scoped>
.eval-page { padding: 24px; width: 100%; box-sizing: border-box; }

.filter-bar { display: flex; gap: 10px; margin-bottom: 18px; }

.stat-cards { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 20px; }
.stat-card {
  background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
  padding: 16px; text-align: center;
}
.stat-value { font-size: 22px; font-weight: 700; color: #0f172a; }
.stat-value.err { color: #ef4444; }
.stat-label { font-size: 12px; color: #94a3b8; margin-top: 4px; }

.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.col-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; }
.col-title { font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 12px; }
.empty-text { font-size: 13px; color: #94a3b8; text-align: center; padding: 20px; }

/* 日趋势条形图 */
.trend-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.trend-date { font-size: 11px; color: #94a3b8; width: 40px; text-align: right; flex-shrink: 0; }
.trend-emp { font-size: 11px; color: #334155; width: 80px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.trend-bar-wrap { flex: 1; display: flex; gap: 2px; height: 18px; }
.trend-bar {
  background: #3b82f6; border-radius: 3px; min-width: 4px;
  display: flex; align-items: center; justify-content: flex-end; padding: 0 4px;
}
.trend-bar.errors { background: #ef4444; }
.bar-label { font-size: 10px; color: #fff; font-weight: 500; }
.trend-ms { font-size: 11px; color: #64748b; width: 40px; text-align: right; flex-shrink: 0; }

/* Top 工具 */
.tool-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f1f5f9; }
.tool-rank { font-size: 12px; color: #94a3b8; width: 20px; text-align: center; flex-shrink: 0; }
.tool-name { font-size: 13px; color: #0f172a; flex: 1; font-family: monospace; }
.tool-cnt { font-size: 12px; color: #64748b; flex-shrink: 0; }

/* 反馈明细 */
.feedback-section { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px; }
.feedback-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.fb-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
.fb-rating { font-size: 16px; flex-shrink: 0; }
.fb-emp { font-size: 13px; color: #0f172a; min-width: 80px; }
.fb-reason { font-size: 12px; color: #ef4444; background: #fef2f2; padding: 1px 8px; border-radius: 8px; }
.fb-time { font-size: 12px; color: #94a3b8; margin-left: auto; }

@media (max-width: 768px) {
  .two-col { grid-template-columns: 1fr; }
}
</style>
