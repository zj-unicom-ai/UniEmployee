<template>
  <main class="eval-page">
    <header class="page-head">
      <div>
        <div class="eyebrow">DIGITAL EMPLOYEE QUALITY</div>
        <h1>运行评估</h1>
        <p>从运行状态、真实反馈和可重复用例中发现问题，验证改进。</p>
      </div>
      <div class="head-actions">
        <button class="quiet-button" :disabled="loading" @click="refreshAll">{{ loading ? '刷新中…' : '刷新数据' }}</button>
      </div>
    </header>

    <nav class="tabs" aria-label="评估视图">
      <button v-for="item in tabs" :key="item.id" :class="{ active: tab === item.id }" @click="tab = item.id">
        {{ item.label }} <span v-if="item.id === 'feedback' && feedbackTotal" class="tab-count">{{ feedbackTotal }}</span>
      </button>
    </nav>

    <section v-if="tab === 'overview'" class="view-stack">
      <div class="filter-bar">
        <label>数字员工
          <select v-model="filterEmp" @change="refreshAll"><option value="">全部员工</option><option v-for="e in employees" :key="e.id" :value="e.id">{{ e.name || e.id }}</option></select>
        </label>
        <label>统计周期
          <select v-model="filterPeriod" @change="refreshAll"><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option></select>
        </label>
        <span class="scope-note">运行指标与反馈列表使用相同筛选范围</span>
      </div>

      <div v-if="loadError" class="error-banner">{{ loadError }} <button @click="refreshAll">重试</button></div>
      <div class="stat-grid">
        <article class="stat-card stat-primary"><div class="stat-kicker">运行量</div><strong>{{ fmtInt(stats.total_runs) }}</strong><span>次运行 · {{ filterPeriodLabel }}</span></article>
        <article class="stat-card"><div class="stat-kicker">用户正向反馈</div><strong>{{ pct(stats.satisfaction.score) }}</strong><span>{{ stats.satisfaction.thumbs_up || 0 }} 赞 / {{ stats.satisfaction.thumbs_down || 0 }} 踩</span></article>
        <article class="stat-card"><div class="stat-kicker">评价覆盖率</div><strong>{{ pct(stats.satisfaction.coverage) }}</strong><span>{{ stats.satisfaction.rated_runs || 0 }} / {{ fmtInt(stats.total_runs) }} 次运行有评价</span></article>
        <article class="stat-card"><div class="stat-kicker">运行错误率</div><strong :class="{ danger: stats.error_rate > 0.05 }">{{ pct(stats.error_rate) }}</strong><span>失败运行 / 全部运行</span></article>
        <article class="stat-card"><div class="stat-kicker">工具成功率</div><strong>{{ stats.tool_total ? pct(stats.tool_success_rate) : '—' }}</strong><span>{{ fmtInt(stats.tool_total) }} 次工具调用</span></article>
        <article class="stat-card"><div class="stat-kicker">平均响应耗时</div><strong>{{ fmtMs(stats.avg_duration_ms) }}</strong><span>平均每次运行</span></article>
        <article class="stat-card"><div class="stat-kicker">平均 Token</div><strong>{{ fmtInt(stats.avg_tokens) }}</strong><span>用于观察单次调用成本</span></article>
      </div>

      <div class="overview-grid">
        <section class="panel trend-panel">
          <div class="panel-head"><div><h2>运行与错误趋势</h2><p>{{ filterPeriodLabel }} · 按日汇总</p></div><span class="legend"><i></i>运行 <i class="red-dot"></i>错误</span></div>
          <div v-if="!dailyRows.length" class="empty-state">当前周期暂无运行记录</div>
          <div v-else class="trend-list">
            <div v-for="d in dailyRows" :key="d.date" class="trend-row">
              <time>{{ d.date.slice(5) }}</time>
              <div class="bar-track"><div class="bar-runs" :style="{ width: `${Math.max(3, d.runs / maxDailyRuns * 100)}%` }"></div><div class="bar-errors" :style="{ width: `${d.errors / maxDailyRuns * 100}%` }"></div></div>
              <b>{{ d.runs }}</b><span class="trend-error">{{ d.errors ? `${d.errors} 错误` : '—' }}</span>
            </div>
          </div>
        </section>
        <section class="panel reason-panel">
          <div class="panel-head"><div><h2>差评原因</h2><p>{{ fmtInt(stats.satisfaction.thumbs_down) }} 条点踩反馈</p></div><button class="text-button" @click="openFeedbackForNegative">查看差评 →</button></div>
          <div v-if="!stats.reason_breakdown.length" class="empty-state">还没有反馈原因</div>
          <button v-for="r in stats.reason_breakdown" :key="r.reason" class="reason-row" @click="openFeedbackForReason(r.reason)">
            <span>{{ reasonLabel(r.reason) }}</span><div class="reason-track"><i :style="{ width: `${Math.max(5, r.count / maxReasonCount * 100)}%` }"></i></div><b>{{ r.count }}</b>
          </button>
        </section>
        <section class="panel tools-panel">
          <div class="panel-head"><div><h2>工具调用表现</h2><p>按调用次数排列，失败率帮助定位风险</p></div></div>
          <div v-if="!stats.top_tools.length" class="empty-state">当前周期没有工具调用</div>
          <div v-for="tool in stats.top_tools" :key="tool.name" class="tool-row"><code>{{ tool.name }}</code><span>{{ fmtInt(tool.count) }} 次</span><b :class="{ danger: tool.failures }">{{ tool.failures ? `${tool.failures} 次失败` : `${pct(tool.success_rate)} 成功` }}</b></div>
        </section>
      </div>
    </section>

    <section v-else-if="tab === 'feedback'" class="view-stack">
      <div class="filter-bar feedback-filters">
        <label>员工<select v-model="feedbackFilters.employee_id" @change="syncFeedbackScope"><option value="">全部员工</option><option v-for="e in employees" :key="e.id" :value="e.id">{{ e.name || e.id }}</option></select></label>
        <label>周期<select v-model="feedbackFilters.period" @change="syncFeedbackScope"><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option></select></label>
        <label>评分<select v-model="feedbackFilters.rating" @change="loadFeedback(true)"><option value="">全部评分</option><option value="-1">点踩</option><option value="1">点赞</option></select></label>
        <label>原因<select v-model="feedbackFilters.reason" @change="loadFeedback(true)"><option value="">全部原因</option><option v-for="r in reasonOptions" :key="r.value" :value="r.value">{{ r.label }}</option></select></label>
        <label>处理状态<select v-model="feedbackFilters.status" @change="loadFeedback(true)"><option value="">全部状态</option><option value="open">待处理</option><option value="investigating">处理中</option><option value="resolved">已解决</option></select></label>
      </div>
      <div class="panel feedback-panel">
        <div class="panel-head"><div><h2>用户反馈</h2><p>按时间倒序 · 共 {{ feedbackTotal }} 条</p></div><span class="feedback-rate">本周期评价覆盖 {{ pct(stats.satisfaction.coverage) }}</span></div>
        <div v-if="feedbackLoading" class="empty-state">正在读取反馈…</div>
        <div v-else-if="!feedback.length" class="empty-state">这个筛选范围内没有反馈</div>
        <article v-for="f in feedback" :key="f.id" class="feedback-card">
          <div class="feedback-top">
            <div class="feedback-ident"><span class="rating-mark" :class="f.rating === 1 ? 'up' : 'down'">{{ f.rating === 1 ? '＋' : '−' }}</span><b>{{ empNames[f.employee_id] || f.employee_id }}</b><span v-if="f.reason" class="reason-chip">{{ reasonLabel(f.reason) }}</span><span class="status-chip" :class="`status-${f.status || 'open'}`">{{ statusLabel(f.status) }}</span></div>
            <time>{{ fmtTime(f.created_at) }}</time>
          </div>
          <div class="qa-grid"><div><span>用户问题</span><p>{{ f.question_preview || '历史评价未保存问题内容' }}</p></div><div><span>员工回答</span><p>{{ f.answer_preview || '历史评价未保存回答内容' }}</p></div></div>
          <div class="feedback-bottom">
            <div class="feedback-links"><button class="text-button" :disabled="!f.conversation_id" @click="openConversation(f)">打开会话 ↗</button><button class="text-button" :disabled="!f.conversation_id" @click="openTrace(f)">查看 Trace ↗</button></div>
            <div class="resolution-controls"><select v-model="feedbackEdits[f.id].status"><option value="open">待处理</option><option value="investigating">处理中</option><option value="resolved">已解决</option></select><input v-model="feedbackEdits[f.id].resolution_note" maxlength="1000" placeholder="处理记录（可选）"/><button class="small-primary" :disabled="savingFeedback === f.id" @click="saveFeedback(f)">{{ savingFeedback === f.id ? '保存中…' : '保存处理' }}</button></div>
          </div>
        </article>
        <div v-if="feedbackTotal > feedbackPageSize" class="pager"><button :disabled="feedbackOffset === 0" @click="changeFeedbackPage(-1)">上一页</button><span>{{ feedbackOffset + 1 }}–{{ Math.min(feedbackOffset + feedback.length, feedbackTotal) }} / {{ feedbackTotal }}</span><button :disabled="feedbackOffset + feedbackPageSize >= feedbackTotal" @click="changeFeedbackPage(1)">下一页</button></div>
      </div>
    </section>

    <section v-else class="view-stack benchmark-view">
      <div class="benchmark-intro"><div><h2>基准评测</h2><p>把典型问题变成固定用例，重复运行并人工判定结果，比较配置改动前后的表现。</p></div><button class="primary-button" @click="openSuiteEditor()">＋ 新建用例集</button></div>
      <div class="benchmark-layout">
        <section class="panel suite-list-panel">
          <div class="panel-head"><div><h2>用例集</h2><p>{{ suites.length }} 个评测集</p></div></div>
          <div v-if="suiteLoading" class="empty-state">正在读取用例集…</div>
          <div v-else-if="!suites.length" class="empty-state">先按一个员工和一个业务场景创建用例集。</div>
          <button v-for="s in suites" :key="s.id" class="suite-card" :class="{ selected: selectedSuite?.id === s.id }" @click="selectSuite(s)">
            <b>{{ s.name }}</b><span>{{ empNames[s.employee_id] || s.employee_id }} · {{ s.case_count }} 个用例</span><small>{{ s.description || '暂无说明' }}</small>
          </button>
        </section>
        <section class="panel suite-detail-panel">
          <div v-if="!selectedSuite" class="empty-state large-empty">选择一个用例集开始管理用例和评测记录</div>
          <template v-else>
            <div class="panel-head suite-detail-head"><div><h2>{{ selectedSuite.name }}</h2><p>{{ empNames[selectedSuite.employee_id] || selectedSuite.employee_id }} · {{ selectedSuite.description || '暂无说明' }}</p></div><div class="suite-actions"><button class="quiet-button" @click="openSuiteEditor(selectedSuite)">编辑</button><button class="quiet-button" @click="openCaseEditor()">＋ 添加用例</button><button class="primary-button" :disabled="runningSuite" @click="runSuite">{{ runningSuite ? '已提交评测…' : '运行评测' }}</button></div></div>
            <div class="safety-note">运行会调用员工当前配置的模型和工具。请先确认用例不会产生非预期的外部业务操作。</div>
            <div class="case-list"><article v-for="c in selectedSuite.cases" :key="c.id" class="case-card"><div><b>{{ c.enabled ? '启用' : '停用' }}</b><button class="text-button" @click="openCaseEditor(c)">编辑</button><button class="text-button danger-text" @click="removeCase(c)">删除</button></div><p class="case-prompt">{{ c.prompt }}</p><small>判定标准：{{ c.criteria }}</small><div v-if="c.tags?.length" class="tag-list"><span v-for="tag in c.tags" :key="tag">{{ tag }}</span></div></article><div v-if="!selectedSuite.cases.length" class="empty-state">用例集还没有用例</div></div>
            <div class="runs-head"><h3>运行历史</h3><span>配置摘要用于识别不同员工配置</span></div>
            <div v-if="!benchmarkRuns.length" class="empty-state compact-empty">暂无评测运行记录</div>
            <button v-for="r in benchmarkRuns" :key="r.id" class="benchmark-run-row" @click="openBenchmarkRun(r.id)"><span><b>{{ fmtTime(r.started_at) }}</b><small>{{ r.config_hash }}</small></span><span>{{ runStatusLabel(r.status) }}</span><span>{{ r.completed_cases }}/{{ r.total_cases }} 完成</span><strong>{{ r.passed_cases }} 通过</strong></button>
          </template>
        </section>
      </div>
    </section>

    <n-modal v-model:show="suiteEditorOpen" preset="card" :title="editingSuite ? '编辑用例集' : '新建用例集'" style="width:min(520px, calc(100vw - 32px))">
      <div class="editor-fields"><label>数字员工<select v-model="suiteForm.employee_id" :disabled="!!editingSuite"><option value="">选择员工</option><option v-for="e in employees" :key="e.id" :value="e.id">{{ e.name || e.id }}</option></select></label><label>用例集名称<input v-model="suiteForm.name" maxlength="100" placeholder="例如：售前产品问答"/></label><label>业务场景说明<textarea v-model="suiteForm.description" maxlength="1000" rows="3" placeholder="这组用例用于检查什么能力？"/></label></div>
      <template #footer><div class="modal-actions"><button class="quiet-button" @click="suiteEditorOpen = false">取消</button><button class="primary-button" :disabled="!suiteForm.name.trim() || !suiteForm.employee_id" @click="saveSuite">保存</button></div></template>
    </n-modal>

    <n-modal v-model:show="caseEditorOpen" preset="card" :title="editingCase ? '编辑评测用例' : '添加评测用例'" style="width:min(640px, calc(100vw - 32px))">
      <div class="editor-fields"><label>用户输入<textarea v-model="caseForm.prompt" maxlength="4000" rows="4" placeholder="输入要重复测试的问题或任务"/></label><label>人工判定标准<textarea v-model="caseForm.criteria" maxlength="2000" rows="3" placeholder="描述通过条件，例如：数值正确、有数据来源、给出行动建议"/></label><label>标签<input v-model="caseForm.tagsText" placeholder="用逗号分隔，例如：事实准确,知识库"/></label><label class="check-label"><input v-model="caseForm.enabled" type="checkbox"/>启用此用例</label></div>
      <template #footer><div class="modal-actions"><button class="quiet-button" @click="caseEditorOpen = false">取消</button><button class="primary-button" :disabled="!caseForm.prompt.trim() || !caseForm.criteria.trim()" @click="saveCase">保存用例</button></div></template>
    </n-modal>

    <n-modal v-model:show="runDetailOpen" preset="card" title="基准评测结果" style="width:min(900px, calc(100vw - 32px))">
      <div v-if="runDetail" class="run-detail"><div class="run-summary"><span>{{ runStatusLabel(runDetail.status) }}</span><span>{{ runDetail.config_hash }}</span><span>{{ runDetail.completed_cases }}/{{ runDetail.total_cases }} 已完成</span><span>{{ runDetail.passed_cases }} 项通过</span></div><article v-for="result in runDetail.results" :key="result.id" class="result-card"><div class="result-head"><b>{{ result.prompt }}</b><span>{{ resultStatusLabel(result.run_status) }}</span><span v-if="result.grade" class="grade-badge" :class="`grade-${result.grade}`">{{ gradeLabel(result.grade) }}</span></div><div class="criteria-box"><b>判定标准</b><p>{{ result.criteria }}</p></div><div class="answer-box"><b>员工回答</b><pre>{{ result.answer || '没有捕获到文本回答' }}</pre></div><div v-if="result.conversation_id" class="feedback-links"><button class="text-button" @click="openBenchmarkTrace(result)">查看执行 Trace ↗</button></div><div class="grade-controls"><select v-model="gradeEdits[result.id].grade"><option value="">待判定</option><option value="pass">通过</option><option value="fail">未通过</option><option value="needs_review">需复核</option></select><input v-model="gradeEdits[result.id].review_note" maxlength="1000" placeholder="判定备注"/><button class="small-primary" @click="saveGrade(runDetail.id,result)">保存判定</button></div></article><div v-if="!runDetail.results.length" class="empty-state">评测已排队，正在等待执行结果…</div></div>
    </n-modal>
  </main>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useDialog, useMessage } from 'naive-ui'
import api from '../api.js'
import { routeNameForEmployee } from '../utils/employeeRoutes.js'

defineOptions({ name: 'AdminEvaluation' })
const router = useRouter()
const dialog = useDialog()
const message = useMessage()
const tabs = [{ id: 'overview', label: '运行概览' }, { id: 'feedback', label: '反馈处理' }, { id: 'benchmarks', label: '基准评测' }]
const tab = ref('overview')
const employees = ref([])
const empNames = reactive({})
const filterEmp = ref('')
const filterPeriod = ref('30d')
const stats = reactive({ total_runs: 0, avg_duration_ms: 0, avg_tokens: 0, error_rate: 0, tool_success_rate: 0, tool_total: 0, satisfaction: { total: 0, thumbs_up: 0, thumbs_down: 0, score: 0, rated_runs: 0, coverage: 0 }, top_tools: [], reason_breakdown: [], daily_trend: [] })
const loadError = ref('')
const loading = ref(false)
const feedback = ref([])
const feedbackTotal = ref(0)
const feedbackLoading = ref(false)
const feedbackOffset = ref(0)
const feedbackPageSize = 10
const feedbackFilters = reactive({ employee_id: '', period: '30d', rating: '', reason: '', status: '' })
const feedbackEdits = reactive({})
const savingFeedback = ref(null)
const suites = ref([])
const suiteLoading = ref(false)
const selectedSuite = ref(null)
const benchmarkRuns = ref([])
const runningSuite = ref(false)
const suiteEditorOpen = ref(false)
const editingSuite = ref(null)
const suiteForm = reactive({ employee_id: '', name: '', description: '' })
const caseEditorOpen = ref(false)
const editingCase = ref(null)
const caseForm = reactive({ prompt: '', criteria: '', tagsText: '', enabled: true })
const runDetailOpen = ref(false)
const runDetail = ref(null)
const gradeEdits = reactive({})
let pollTimer = null

const filterPeriodLabel = computed(() => ({ '7d': '近 7 天', '30d': '近 30 天', '90d': '近 90 天' })[filterPeriod.value])
const dailyRows = computed(() => {
  const grouped = new Map()
  for (const d of stats.daily_trend || []) {
    const row = grouped.get(d.date) || { date: d.date, runs: 0, errors: 0 }
    row.runs += Number(d.runs || 0); row.errors += Number(d.errors || 0); grouped.set(d.date, row)
  }
  return [...grouped.values()].slice(-30)
})
const maxDailyRuns = computed(() => Math.max(1, ...dailyRows.value.map(d => d.runs)))
const maxReasonCount = computed(() => Math.max(1, ...(stats.reason_breakdown || []).map(r => r.count)))
const reasonOptions = [{ value: 'irrelevant', label: '答非所问' }, { value: 'factual_error', label: '事实错误' }, { value: 'wrong_process', label: '流程不对' }, { value: 'too_slow', label: '太慢' }, { value: 'other', label: '其他' }, { value: 'unspecified', label: '未分类' }]

function fmtInt(n) { return Number(n || 0).toLocaleString() }
function pct(n) { return `${(Number(n || 0) * 100).toFixed(1)}%` }
function fmtMs(n) { return n == null ? '—' : n >= 1000 ? `${(n / 1000).toFixed(1)}s` : `${Math.round(n)}ms` }
function fmtTime(value) { return (value || '').replace('T', ' ').slice(0, 16) || '—' }
function reasonLabel(code) { return reasonOptions.find(r => r.value === code)?.label || (code === 'unspecified' ? '未分类' : code) }
function statusLabel(status) { return ({ open: '待处理', investigating: '处理中', resolved: '已解决' })[status] || '待处理' }
function runStatusLabel(status) { return ({ queued: '排队中', running: '运行中', completed: '已完成', completed_with_errors: '部分失败', failed: '运行失败' })[status] || status }
function resultStatusLabel(status) { return status === 'completed' ? '运行成功' : '运行失败' }
function gradeLabel(grade) { return ({ pass: '通过', fail: '未通过', needs_review: '需复核' })[grade] || '' }
function paramsFromFeedback() {
  const p = { limit: feedbackPageSize, offset: feedbackOffset.value, period: feedbackFilters.period }
  if (feedbackFilters.employee_id) p.employee_id = feedbackFilters.employee_id
  if (feedbackFilters.rating !== '') p.rating = Number(feedbackFilters.rating)
  if (feedbackFilters.reason) p.reason = feedbackFilters.reason
  if (feedbackFilters.status) p.status = feedbackFilters.status
  return p
}
async function loadStats() {
  const params = { period: filterPeriod.value }
  if (filterEmp.value) params.employee_id = filterEmp.value
  const { data } = await api.get('/admin/evaluation/stats', { params })
  Object.assign(stats, data)
}
async function loadFeedback(reset = false) {
  if (reset) feedbackOffset.value = 0
  feedbackLoading.value = true
  try {
    const { data } = await api.get('/admin/evaluation/feedback', { params: paramsFromFeedback() })
    feedbackTotal.value = data.total || 0
    if (feedbackOffset.value >= feedbackTotal.value && feedbackOffset.value > 0) {
      feedbackOffset.value = feedbackTotal.value ? Math.floor((feedbackTotal.value - 1) / feedbackPageSize) * feedbackPageSize : 0
      return await loadFeedback()
    }
    feedback.value = data.items || []
    feedback.value.forEach(f => { feedbackEdits[f.id] = { status: f.status || 'open', resolution_note: f.resolution_note || '' } })
  } catch (e) { message.error(e.response?.data?.detail || '读取反馈失败') }
  finally { feedbackLoading.value = false }
}
async function refreshAll() {
  loading.value = true; loadError.value = ''
  feedbackFilters.employee_id = filterEmp.value
  feedbackFilters.period = filterPeriod.value
  try { await Promise.all([loadStats(), loadFeedback(true)]) }
  catch (e) { loadError.value = e.response?.data?.detail || '评估数据读取失败，请重试' }
  finally { loading.value = false }
}
async function syncFeedbackScope() {
  filterEmp.value = feedbackFilters.employee_id
  filterPeriod.value = feedbackFilters.period
  loading.value = true
  try { await Promise.all([loadStats(), loadFeedback(true)]) }
  catch (e) { message.error(e.response?.data?.detail || '统计数据读取失败') }
  finally { loading.value = false }
}
function changeFeedbackPage(delta) { feedbackOffset.value = Math.max(0, feedbackOffset.value + delta * feedbackPageSize); loadFeedback() }
async function saveFeedback(row) {
  savingFeedback.value = row.id
  try {
    await api.patch(`/admin/evaluation/feedback/${row.id}`, feedbackEdits[row.id])
    message.success('处理记录已保存'); await loadFeedback()
  } catch (e) { message.error(e.response?.data?.detail || '保存失败') }
  finally { savingFeedback.value = null }
}
function openFeedbackForNegative() { feedbackFilters.employee_id = filterEmp.value; feedbackFilters.period = filterPeriod.value; feedbackFilters.rating = '-1'; tab.value = 'feedback'; loadFeedback(true) }
function openFeedbackForReason(reason) { feedbackFilters.employee_id = filterEmp.value; feedbackFilters.period = filterPeriod.value; feedbackFilters.reason = reason; feedbackFilters.rating = '-1'; tab.value = 'feedback'; loadFeedback(true) }
function openConversation(row) { router.push({ name: routeNameForEmployee(row.employee_id), query: { conv: row.conversation_id } }) }
function openTrace(row) { router.push({ name: 'trace', query: { conv: row.conversation_id, run: row.run_id } }) }

async function loadSuites() {
  suiteLoading.value = true
  try { const { data } = await api.get('/admin/evaluation/suites'); suites.value = data }
  catch (e) { message.error(e.response?.data?.detail || '读取评测集失败') }
  finally { suiteLoading.value = false }
}
async function selectSuite(suite) {
  const { data } = await api.get(`/admin/evaluation/suites/${suite.id}`)
  selectedSuite.value = data; await loadBenchmarkRuns()
}
async function loadBenchmarkRuns() {
  if (!selectedSuite.value) return
  const { data } = await api.get(`/admin/evaluation/suites/${selectedSuite.value.id}/runs`)
  benchmarkRuns.value = data
  if (data.some(r => ['queued', 'running'].includes(r.status))) {
    if (!pollTimer) pollTimer = setInterval(async () => { await loadBenchmarkRuns(); if (!benchmarkRuns.value.some(r => ['queued', 'running'].includes(r.status))) { clearInterval(pollTimer); pollTimer = null; if (runDetailOpen.value && runDetail.value) openBenchmarkRun(runDetail.value.id) } }, 2500)
  }
}
function openSuiteEditor(suite = null) {
  editingSuite.value = suite
  suiteForm.employee_id = suite?.employee_id || employees.value[0]?.id || ''
  suiteForm.name = suite?.name || ''; suiteForm.description = suite?.description || ''
  suiteEditorOpen.value = true
}
async function saveSuite() {
  try {
    if (editingSuite.value) await api.put(`/admin/evaluation/suites/${editingSuite.value.id}`, { name: suiteForm.name, description: suiteForm.description })
    else {
      const { data } = await api.post('/admin/evaluation/suites', suiteForm)
      suiteEditorOpen.value = false; await loadSuites(); await selectSuite(data); message.success('用例集已创建'); return
    }
    suiteEditorOpen.value = false; await loadSuites();
    if (selectedSuite.value) await selectSuite(suites.value.find(s => s.id === selectedSuite.value.id) || selectedSuite.value)
    message.success('用例集已保存')
  } catch (e) { message.error(e.response?.data?.detail || '保存失败') }
}
function openCaseEditor(item = null) {
  editingCase.value = item
  caseForm.prompt = item?.prompt || ''; caseForm.criteria = item?.criteria || ''
  caseForm.tagsText = (item?.tags || []).join(', '); caseForm.enabled = item?.enabled ?? true
  caseEditorOpen.value = true
}
async function saveCase() {
  try {
    await api.post(`/admin/evaluation/suites/${selectedSuite.value.id}/cases`, {
      id: editingCase.value?.id, prompt: caseForm.prompt, criteria: caseForm.criteria,
      tags: caseForm.tagsText.split(',').map(s => s.trim()).filter(Boolean), enabled: caseForm.enabled,
    })
    caseEditorOpen.value = false; await selectSuite(selectedSuite.value); message.success('评测用例已保存')
  } catch (e) { message.error(e.response?.data?.detail || '保存失败') }
}
function removeCase(item) {
  dialog.warning({ title: '停用评测用例', content: '停用后不会加入新一轮评测，历史结果仍保留。', positiveText: '停用', negativeText: '取消', onPositiveClick: async () => {
    try { await api.delete(`/admin/evaluation/cases/${item.id}`); await selectSuite(selectedSuite.value); message.success('用例已停用') }
    catch (e) { message.error(e.response?.data?.detail || '操作失败') }
  } })
}
function runSuite() {
  if (!selectedSuite.value?.cases.some(c => c.enabled)) { message.warning('请先添加并启用至少一个用例'); return }
  dialog.warning({ title: '运行基准评测', content: '系统会调用员工当前配置的模型和工具。请确认这些用例不会产生非预期的外部业务操作。', positiveText: '开始运行', negativeText: '取消', onPositiveClick: async () => {
    runningSuite.value = true
    try {
      const { data } = await api.post(`/admin/evaluation/suites/${selectedSuite.value.id}/runs`, {}, { timeout: 60000 })
      message.success(`评测已提交，共 ${data.total_cases} 个用例`); await loadBenchmarkRuns()
    } catch (e) { message.error(e.response?.data?.detail || '启动评测失败') }
    finally { runningSuite.value = false }
  } })
}
async function openBenchmarkRun(id) {
  try {
    const { data } = await api.get(`/admin/evaluation/runs/${id}`)
    runDetail.value = data; runDetailOpen.value = true
    data.results.forEach(r => { gradeEdits[r.id] = { grade: r.grade || '', review_note: r.review_note || '' } })
  } catch (e) { message.error(e.response?.data?.detail || '读取评测结果失败') }
}
async function saveGrade(runId, result) {
  try {
    await api.patch(`/admin/evaluation/runs/${runId}/results/${result.id}`, gradeEdits[result.id])
    message.success('判定已保存'); await openBenchmarkRun(runId); await loadBenchmarkRuns()
  } catch (e) { message.error(e.response?.data?.detail || '判定保存失败') }
}
function openBenchmarkTrace(result) { router.push({ name: 'trace', query: { conv: result.conversation_id, run: result.trace_run_id } }); runDetailOpen.value = false }

onMounted(async () => {
  try {
    const { data } = await api.get('/admin/employees')
    employees.value = data; data.forEach(e => { empNames[e.id] = e.name || e.id })
  } catch (e) { loadError.value = e.response?.data?.detail || '员工列表读取失败' }
  await Promise.all([refreshAll(), loadSuites()])
})
onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer) })
</script>

<style scoped>
.eval-page { --ink:#142c3b; --muted:#617986; --line:#dce6e9; --paper:#f4f8f7; --teal:#087f78; --teal-soft:#e2f3ef; --red:#bd5349; color:var(--ink); padding:26px clamp(18px,3vw,40px) 48px; width:100%; box-sizing:border-box; background:var(--paper); min-height:100%; }
.page-head { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin-bottom:23px; }
.eval-page button:focus-visible,.eval-page select:focus-visible,.eval-page input:focus-visible,.eval-page textarea:focus-visible { outline:2px solid #087f78; outline-offset:2px; }
.eyebrow { color:var(--teal); font:700 10px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing:.16em; }
h1 { font-size:28px; letter-spacing:-.04em; line-height:1.1; margin:6px 0 8px; color:var(--ink); }
.page-head p,.panel-head p,.benchmark-intro p { color:var(--muted); font-size:13px; margin:0; }
.head-actions { display:flex; gap:8px; }
.tabs { display:flex; gap:24px; border-bottom:1px solid var(--line); margin-bottom:20px; }
.tabs button { position:relative; padding:0 2px 13px; border:0; background:none; color:#718590; font-size:13px; cursor:pointer; }
.tabs button.active { color:var(--teal); font-weight:700; }
.tabs button.active::after { position:absolute; bottom:-1px; left:0; right:0; height:2px; background:var(--teal); content:''; }
.tab-count { background:#e5eeed; border-radius:10px; padding:1px 6px; margin-left:5px; font-size:10px; }
.view-stack { display:flex; flex-direction:column; gap:16px; }
.filter-bar { display:flex; align-items:flex-end; flex-wrap:wrap; gap:12px; }
.filter-bar label,.editor-fields label { display:flex; flex-direction:column; gap:6px; color:#617986; font-size:11px; font-weight:600; }
select,input,textarea { font:inherit; }
.filter-bar select,.resolution-controls select,.grade-controls select,.editor-fields input,.editor-fields select,.editor-fields textarea,.resolution-controls input,.grade-controls input { border:1px solid var(--line); border-radius:6px; background:#fff; color:var(--ink); padding:8px 10px; min-width:130px; outline-color:var(--teal); font-size:12px; }
.scope-note { color:#80939b; font-size:11px; padding:0 0 9px; }
.stat-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:10px; }
.stat-card,.panel { background:#fff; border:1px solid var(--line); border-radius:9px; }
.stat-card { min-height:112px; padding:15px 16px; display:flex; flex-direction:column; gap:5px; }
.stat-card.stat-primary { background:#e4f2ef; border-color:#c5e1dc; }
.stat-kicker { color:#718590; font-size:11px; }
.stat-card strong { font-size:25px; letter-spacing:-.04em; color:var(--ink); }
.stat-card span { color:#80939b; font-size:10px; }
.danger { color:var(--red)!important; }
.overview-grid { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(280px,.75fr); gap:14px; }
.panel { padding:17px 18px; min-width:0; }
.panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; }
.panel-head h2,.benchmark-intro h2 { margin:0 0 4px; font-size:15px; letter-spacing:-.02em; }
.panel-head p { font-size:11px; }
.trend-panel { min-height:310px; }
.legend { color:var(--muted); font-size:10px; display:flex; align-items:center; gap:5px; }
.legend i,.red-dot { width:7px; height:7px; display:inline-block; border-radius:50%; background:var(--teal); }
.legend .red-dot { background:#d97568; margin-left:5px; }
.trend-list { max-height:246px; overflow:auto; padding-right:4px; }
.trend-row { display:grid; grid-template-columns:42px 1fr 30px 48px; gap:8px; align-items:center; min-height:22px; font-size:10px; }
.trend-row time { color:#899aa1; font-variant-numeric:tabular-nums; }
.bar-track { height:9px; background:#eef3f2; border-radius:5px; overflow:hidden; position:relative; }
.bar-runs { height:100%; background:#76b9ae; border-radius:5px; }
.bar-errors { height:100%; position:absolute; left:0; top:0; background:#d97568; border-radius:5px; opacity:.9; }
.trend-row b { text-align:right; font-size:10px; }
.trend-error { color:#9c7772; text-align:right; font-size:9px; }
.reason-panel { min-height:190px; }
.reason-row { display:grid; grid-template-columns:72px 1fr 20px; width:100%; align-items:center; gap:9px; border:0; padding:7px 0; background:transparent; color:var(--ink); font-size:11px; text-align:left; cursor:pointer; }
.reason-row:hover span { color:var(--teal); }
.reason-track { height:5px; background:#edf2f1; border-radius:4px; overflow:hidden; }
.reason-track i { display:block; height:100%; background:#d68b7f; border-radius:4px; }
.reason-row b { text-align:right; font-size:10px; }
.tools-panel { grid-column:1/-1; }
.tool-row { display:grid; grid-template-columns:1fr 80px 100px; gap:12px; align-items:center; padding:10px 0; border-top:1px solid #edf1f1; font-size:11px; }
.tool-row code { color:#305b63; font-size:11px; }.tool-row span { color:var(--muted); text-align:right; }.tool-row b { text-align:right; font-size:10px; }
.empty-state { color:#8a9ca2; text-align:center; padding:27px 12px; font-size:12px; }
.large-empty { padding:90px 20px; }.compact-empty { padding:14px; }
.error-banner { display:flex; justify-content:space-between; align-items:center; border:1px solid #e5b5ae; background:#fff1ef; color:#963c33; border-radius:7px; padding:10px 13px; font-size:12px; }
.error-banner button,.text-button { border:0; background:none; color:var(--teal); cursor:pointer; font-size:11px; }.text-button:disabled { color:#b5c0c3; cursor:not-allowed; }.text-button:hover:not(:disabled) { text-decoration:underline; }
.feedback-filters { align-items:center; padding:12px 14px; border:1px solid var(--line); border-radius:8px; background:#fff; }
.feedback-filters label { flex-direction:row; align-items:center; gap:7px; }.feedback-filters select { min-width:105px; padding:7px; }
.feedback-panel { padding:18px; }.feedback-rate { color:var(--muted); font-size:11px; }
.feedback-card { border-top:1px solid #e9efef; padding:15px 0 13px; }
.feedback-top,.feedback-ident,.feedback-bottom,.feedback-links,.resolution-controls,.grade-controls { display:flex; align-items:center; gap:9px; }
.feedback-top { justify-content:space-between; margin-bottom:11px; }.feedback-top time { color:#8b9ba1; font-size:10px; }
.feedback-ident b { font-size:12px; }.rating-mark { width:22px; height:22px; display:grid; place-items:center; border-radius:50%; font-weight:700; }.rating-mark.up { color:#087f78; background:#e1f3ef; }.rating-mark.down { color:#b44c43; background:#fff0ed; }
.reason-chip,.status-chip { border-radius:10px; padding:3px 8px; color:#8e594e; background:#fbefeb; font-size:10px; }.status-chip { color:#6f7f85; background:#edf1f1; }.status-investigating { color:#826525; background:#faf1d9; }.status-resolved { color:#176f66; background:#e5f2ed; }
.qa-grid { display:grid; grid-template-columns:1fr 1.4fr; gap:12px; }
.qa-grid>div { background:#f5f8f7; border-radius:6px; padding:10px 12px; min-width:0; }.qa-grid span,.criteria-box>b,.answer-box>b { display:block; color:#809198; font-size:9px; letter-spacing:.03em; margin-bottom:5px; }.qa-grid p { margin:0; font-size:11px; line-height:1.55; white-space:pre-wrap; overflow-wrap:anywhere; max-height:105px; overflow:auto; }
.feedback-bottom { justify-content:space-between; margin-top:10px; flex-wrap:wrap; }.feedback-links { gap:13px; }.resolution-controls { flex:1; justify-content:flex-end; flex-wrap:wrap; }.resolution-controls select { min-width:92px; padding:7px; }.resolution-controls input { min-width:180px; padding:7px 9px; flex:1; max-width:300px; }
.small-primary,.primary-button { border:1px solid var(--teal); border-radius:6px; padding:8px 12px; background:var(--teal); color:white; font-size:11px; cursor:pointer; }.small-primary { padding:7px 10px; }.primary-button:disabled,.small-primary:disabled { opacity:.55; cursor:not-allowed; }.quiet-button { border:1px solid var(--line); border-radius:6px; padding:8px 11px; background:#fff; color:#526c77; font-size:11px; cursor:pointer; }
.pager { display:flex; justify-content:center; align-items:center; gap:17px; padding-top:12px; color:var(--muted); font-size:11px; }.pager button { border:1px solid var(--line); border-radius:5px; background:#fff; padding:6px 10px; color:var(--ink); cursor:pointer; }.pager button:disabled { opacity:.4; cursor:not-allowed; }
.benchmark-intro { display:flex; justify-content:space-between; align-items:center; gap:15px; }.benchmark-intro p { max-width:680px; line-height:1.6; }.benchmark-layout { display:grid; grid-template-columns:minmax(220px,.7fr) minmax(0,1.7fr); gap:14px; align-items:start; }.suite-list-panel,.suite-detail-panel { min-height:390px; }
.suite-card { display:block; width:100%; border:1px solid transparent; border-top-color:#e9efef; background:#fff; text-align:left; padding:12px 9px; cursor:pointer; color:var(--ink); }.suite-card.selected { background:#edf6f3; border-color:#d1e7e2; border-radius:6px; }.suite-card b,.suite-card span,.suite-card small { display:block; }.suite-card b { font-size:12px; }.suite-card span { color:var(--muted); font-size:10px; margin:5px 0; }.suite-card small { color:#8b9ba1; font-size:10px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.suite-detail-head { align-items:flex-start; }.suite-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }.safety-note { padding:9px 11px; background:#fff7e5; color:#876c2d; border-radius:6px; font-size:10px; line-height:1.5; margin-bottom:12px; }.case-card { border-top:1px solid #e9efef; padding:12px 3px; }.case-card>div:first-child { display:flex; align-items:center; gap:10px; }.case-card b { color:#6f858b; font-size:9px; }.case-card .text-button { padding:0; }.case-prompt { font-size:12px; margin:8px 0 4px; line-height:1.5; white-space:pre-wrap; }.case-card small { color:#7c8d94; font-size:10px; line-height:1.5; }.danger-text { color:#b44c43; }.tag-list { display:flex; gap:5px; margin-top:7px; }.tag-list span { color:#547c78; background:#e9f3f0; border-radius:8px; padding:2px 7px; font-size:9px; }
.runs-head { display:flex; align-items:baseline; gap:10px; border-top:1px solid var(--line); margin-top:12px; padding-top:14px; }.runs-head h3 { font-size:13px; margin:0; }.runs-head span { color:#88999f; font-size:10px; }.benchmark-run-row { display:grid; grid-template-columns:1fr 80px 100px 75px; gap:10px; width:100%; align-items:center; border:0; border-top:1px solid #edf1f1; background:#fff; padding:10px 4px; text-align:left; color:var(--ink); cursor:pointer; font-size:10px; }.benchmark-run-row span:first-child b,.benchmark-run-row small { display:block; }.benchmark-run-row small { color:#8b9ba1; margin-top:3px; }.benchmark-run-row strong { text-align:right; color:var(--teal); }
.editor-fields { display:flex; flex-direction:column; gap:13px; }.editor-fields input,.editor-fields select,.editor-fields textarea { box-sizing:border-box; width:100%; resize:vertical; }.check-label { flex-direction:row!important; align-items:center; }.check-label input { width:auto; }.modal-actions { display:flex; justify-content:flex-end; gap:8px; }
.run-summary { display:flex; gap:14px; flex-wrap:wrap; color:#68808a; font-size:10px; margin-bottom:12px; }.result-card { border:1px solid var(--line); border-radius:7px; padding:13px; margin:10px 0; }.result-head { display:flex; align-items:center; gap:9px; font-size:11px; }.result-head b { flex:1; }.result-head>span { color:#74878e; }.grade-badge { padding:3px 7px; border-radius:10px; background:#eef1f1; }.grade-pass { color:#16756d!important; background:#e4f3ef; }.grade-fail { color:#b34d43!important; background:#fff0ed; }.grade-needs_review { color:#856b2c!important; background:#faf2da; }.criteria-box,.answer-box { margin-top:10px; border-radius:6px; padding:10px; background:#f5f8f7; }.criteria-box p { font-size:11px; margin:0; white-space:pre-wrap; }.answer-box pre { max-height:210px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font:11px/1.55 ui-monospace,Menlo,monospace; margin:0; }.grade-controls { margin-top:10px; }.grade-controls select { min-width:95px; }.grade-controls input { flex:1; }
@media(max-width:1100px) { .stat-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
@media(max-width:780px) { .eval-page { padding:18px 14px 32px; }.page-head { align-items:flex-start; }.page-head h1 { font-size:24px; }.overview-grid,.benchmark-layout { grid-template-columns:1fr; }.tools-panel { grid-column:auto; }.stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.feedback-filters label { width:calc(50% - 8px); justify-content:space-between; }.feedback-filters select { flex:1; }.qa-grid { grid-template-columns:1fr; }.feedback-bottom { align-items:flex-start; }.resolution-controls { justify-content:flex-start; }.suite-detail-head { flex-direction:column; }.suite-actions { justify-content:flex-start; }.benchmark-run-row { grid-template-columns:1fr 75px; }.benchmark-run-row span:nth-child(3),.benchmark-run-row strong { text-align:left; }.grade-controls { flex-wrap:wrap; }.grade-controls input { min-width:100%; } }
@media(max-width:460px) { .stat-grid { grid-template-columns:1fr 1fr; gap:7px; }.stat-card { padding:12px; min-height:100px; }.stat-card strong { font-size:20px; }.scope-note { width:100%; }.feedback-top { align-items:flex-start; }.feedback-ident { flex-wrap:wrap; }.resolution-controls input { max-width:none; min-width:100%; }.trend-row { grid-template-columns:36px 1fr 25px 40px; gap:5px; } }
</style>
