<!-- 自动任务：定时(cron) / 事件触发的自动化执行管理页（admin）。
     任务执行复用对话链路（护栏/记忆/Trace），结果落会话，可选经频道 outbound_webhook 推送。 -->
<template>
  <div class="auto-page">
    <div class="toolbar">
      <div class="intro">
        <div class="intro-title">自动化任务</div>
        <div class="intro-sub">定时（cron）或事件触发数字员工自动执行任务；结果落会话历史，配置推送频道后可推送到外部 IM</div>
      </div>
      <n-button type="primary" size="small" @click="openCreate">新建任务</n-button>
    </div>

    <n-data-table :columns="columns" :data="items" :loading="loading" :bordered="false"
                  size="small" :row-key="r => r.id" :pagination="false" />
    <n-empty v-if="!loading && !items.length" description="还没有自动化任务，点击右上角新建" style="padding: 48px 0" />

    <!-- 新建 / 编辑 -->
    <n-modal v-model:show="showForm" preset="card" :title="editingId ? '编辑任务' : '新建任务'"
             style="width: 640px" :mask-closable="false">
      <n-form label-placement="left" label-width="92" size="small">
        <n-form-item label="任务名称" required>
          <n-input v-model:value="form.name" placeholder="如：每日经营简报" />
        </n-form-item>
        <n-form-item label="触发方式" required>
          <n-radio-group v-model:value="form.trigger_type">
            <n-radio value="cron">定时（cron）</n-radio>
            <n-radio value="event">事件触发</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item v-if="form.trigger_type === 'cron'" label="cron 表达式" required>
          <n-input v-model:value="form.cron_expr" placeholder="分 时 日 月 周（服务器本地时间），如 0 9 * * 1-5" />
          <div class="field-hint">
            快捷：
            <n-button text type="primary" size="tiny" @click="form.cron_expr = '0 9 * * *'">每天 9 点</n-button> ·
            <n-button text type="primary" size="tiny" @click="form.cron_expr = '0 9 * * 1-5'">工作日 9 点</n-button> ·
            <n-button text type="primary" size="tiny" @click="form.cron_expr = '0 * * * *'">每小时</n-button> ·
            <n-button text type="primary" size="tiny" @click="form.cron_expr = '*/15 * * * *'">每 15 分钟</n-button>
          </div>
        </n-form-item>
        <template v-if="form.trigger_type === 'event'">
          <n-form-item label="事件标识" required>
            <n-input v-model:value="form.event_key" placeholder="如 order.refunded" />
          </n-form-item>
          <n-form-item label="secret">
            <n-input v-model:value="form.secret" placeholder="可选；配置后调用方需携带相同 secret" />
          </n-form-item>
          <n-form-item v-if="form.event_key" label="调用地址">
            <code class="event-url">{{ eventUrlPreview }}</code>
          </n-form-item>
        </template>
        <n-form-item label="执行员工" required>
          <n-select v-model:value="form.employee_id" :options="employeeOptions"
                    placeholder="选择数字员工" filterable />
        </n-form-item>
        <n-form-item label="任务指令" required>
          <n-input v-model:value="form.prompt" type="textarea" :rows="4"
                   placeholder="要执行的工作描述。可用占位符：{{now}} 当前时间；{{payload}} 事件数据（事件触发时）" />
        </n-form-item>
        <n-form-item label="运行身份">
          <n-input v-model:value="form.run_as" placeholder="以哪个用户身份运行（影响记忆与会话归属），默认创建者" />
        </n-form-item>
        <n-form-item label="推送频道">
          <n-select v-model:value="form.channel_id" :options="channelOptions"
                    placeholder="不推送：结果仅落会话历史" clearable />
          <div class="field-hint">选择配置了 outbound_webhook 的频道，任务结果会推送到外部 IM</div>
        </n-form-item>
      </n-form>
      <template #footer>
        <div class="modal-footer">
          <n-button size="small" @click="showForm = false">取消</n-button>
          <n-button size="small" type="primary" :loading="saving" @click="save">保存</n-button>
        </div>
      </template>
    </n-modal>

    <!-- 运行结果 -->
    <n-modal v-model:show="showResult" preset="card" title="任务执行结果" style="width: 640px">
      <div v-if="runResult" class="run-result">
        <div class="run-meta">
          <n-tag :type="runResult.status === 'ok' ? 'success' : 'error'" size="small">
            {{ runResult.status === 'ok' ? '成功' : '失败' }}
          </n-tag>
          <span class="run-conv">会话：{{ runResult.conversation_id }}</span>
        </div>
        <div v-if="runResult.error" class="run-error">{{ runResult.error }}</div>
        <pre class="run-reply">{{ runResult.reply || '（无输出）' }}</pre>
      </div>
      <template #footer>
        <div class="modal-footer">
          <n-button size="small" @click="showResult = false">关闭</n-button>
          <n-button size="small" type="primary" @click="gotoConv">前往会话</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { h, ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, NSwitch, NTooltip, useMessage } from 'naive-ui'
import api from '../api.js'

defineOptions({ name: 'AutomationView' })

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const saving = ref(false)
const items = ref([])
const employees = ref([])
const channels = ref([])
const showForm = ref(false)
const showResult = ref(false)
const editingId = ref(null)
const runResult = ref(null)
const runningIds = ref(new Set())

const form = ref({
  name: '', trigger_type: 'cron', cron_expr: '', event_key: '', secret: '',
  employee_id: null, prompt: '', run_as: '', channel_id: null, enabled: true,
})

const employeeOptions = computed(() =>
  employees.value.map(e => ({ label: `${e.name}（${e.id}）`, value: e.id })))
const channelOptions = computed(() =>
  channels.value.map(c => ({ label: c.name, value: c.id })))
const eventUrlPreview = computed(() =>
  `${location.origin}/api/automations/events/${form.value.event_key || '<事件标识>'}`)

function triggerText(row) {
  if (row.trigger_type === 'cron') return row.cron_expr
  return `${row.event_key}`
}

async function load() {
  loading.value = true
  try {
    const [a, e, c] = await Promise.all([
      api.get('/automations'),
      api.get('/admin/employees'),
      api.get('/im/channels'),
    ])
    items.value = a.data.items || []
    employees.value = e.data || []
    channels.value = c.data.items || []
  } catch (err) {
    message.error('加载失败：' + (err.response?.data?.detail || err.message))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = { name: '', trigger_type: 'cron', cron_expr: '0 9 * * *', event_key: '',
                 secret: '', employee_id: null, prompt: '', run_as: '', channel_id: null,
                 enabled: true }
  showForm.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.value = {
    name: row.name, trigger_type: row.trigger_type, cron_expr: row.cron_expr,
    event_key: row.event_key, secret: row.secret, employee_id: row.employee_id,
    prompt: row.prompt, run_as: row.run_as, channel_id: row.channel_id || null,
    enabled: row.enabled,
  }
  showForm.value = true
}

async function save() {
  const f = form.value
  if (!f.name.trim() || !f.prompt.trim() || !f.employee_id) {
    message.warning('请填写任务名称、执行员工和任务指令')
    return
  }
  if (f.trigger_type === 'cron' && !f.cron_expr.trim()) {
    message.warning('请填写 cron 表达式')
    return
  }
  if (f.trigger_type === 'event' && !f.event_key.trim()) {
    message.warning('请填写事件标识')
    return
  }
  saving.value = true
  try {
    const body = { ...f, channel_id: f.channel_id || '' }
    if (editingId.value) await api.put(`/automations/${editingId.value}`, body)
    else await api.post('/automations', body)
    message.success('已保存')
    showForm.value = false
    await load()
  } catch (err) {
    message.error('保存失败：' + (err.response?.data?.detail || err.message))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row, v) {
  try {
    await api.put(`/automations/${row.id}`, { enabled: v })
    row.enabled = v
  } catch (err) {
    row.enabled = !v
    message.error('操作失败：' + (err.response?.data?.detail || err.message))
  }
}

async function runNow(row) {
  runningIds.value = new Set([...runningIds.value, row.id])
  message.info(`正在运行「${row.name}」，请稍候…`)
  try {
    const { data } = await api.post(`/automations/${row.id}/run`)
    runResult.value = data
    showResult.value = true
    await load()
  } catch (err) {
    message.error('运行失败：' + (err.response?.data?.detail || err.message))
  } finally {
    const s = new Set(runningIds.value)
    s.delete(row.id)
    runningIds.value = s
  }
}

async function del(row) {
  try {
    await api.delete(`/automations/${row.id}`)
    message.success('已删除')
    await load()
  } catch (err) {
    message.error('删除失败：' + (err.response?.data?.detail || err.message))
  }
}

function gotoConv() {
  showResult.value = false
  if (runResult.value?.conversation_id) {
    router.push({ name: 'history' })
  }
}

const columns = [
  { title: '任务', key: 'name', width: 170,
    render: r => h('div', { class: 'cell-name' }, [
      h('div', { class: 'name' }, r.name),
      r.last_status === 'error'
        ? h('div', { class: 'err-hint', title: r.last_error }, '上次运行失败') : null,
    ]) },
  { title: '触发', key: 'trigger', width: 150,
    render: r => h('div', { class: 'cell-trigger' }, [
      h(NTag, { size: 'tiny', type: r.trigger_type === 'cron' ? 'info' : 'warning',
                bordered: false }, { default: () => (r.trigger_type === 'cron' ? '定时' : '事件') }),
      h('span', { class: 'expr', title: r.trigger_type === 'cron'
        ? 'cron：分 时 日 月 周' : r.event_url || '' }, triggerText(r)),
    ]) },
  { title: '员工', key: 'employee_id', width: 120,
    render: r => r.employee_id },
  { title: '指令', key: 'prompt', ellipsis: { tooltip: true },
    render: r => h('span', { class: 'prompt' }, r.prompt) },
  { title: '上次运行', key: 'last_run_at', width: 190,
    render: r => h('div', { class: 'cell-run' }, [
      h('span', {}, r.last_run_at
        ? `${r.last_run_at}（${runCountLabel(r)}）` : '未运行过'),
      r.last_conv_id ? h(NButton, { text: true, type: 'primary', size: 'tiny',
        onClick: () => router.push({ name: 'history' }) }, { default: () => '查看' }) : null,
    ]) },
  { title: '启用', key: 'enabled', width: 70,
    render: r => h(NSwitch, { value: r.enabled, size: 'small',
      onUpdateValue: v => toggleEnabled(r, v) }) },
  { title: '操作', key: 'actions', width: 180,
    render: r => h('div', { class: 'cell-actions' }, [
      h(NTooltip, null, { trigger: () => h(NButton, {
        size: 'tiny', secondary: true, loading: runningIds.value.has(r.id),
        onClick: () => runNow(r) }, { default: () => '运行' }),
        default: () => '立即运行一次（不影响定时计划）' }),
      h(NButton, { size: 'tiny', secondary: true, onClick: () => openEdit(r) },
        { default: () => '编辑' }),
      h(NButton, { size: 'tiny', secondary: true, type: 'error', onClick: () => del(r) },
        { default: () => '删除' }),
    ]) },
]

function runCountLabel(r) {
  const st = r.last_status === 'ok' ? '成功' : r.last_status === 'error' ? '失败' : r.last_status
  return `${st}，共 ${r.run_count} 次`
}

onMounted(load)
</script>

<style scoped>
.auto-page { padding: 24px; height: 100%; overflow-y: auto; }
.toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.intro-title { font-size: 14px; font-weight: 600; color: #334155; }
.intro-sub { font-size: 12px; color: #94a3b8; margin-top: 3px; }
.field-hint { font-size: 11px; color: #94a3b8; margin-top: 4px; }
.event-url { font-size: 11px; background: #f1f5f9; border-radius: 6px; padding: 3px 8px; color: #475569; }
.modal-footer { display: flex; justify-content: flex-end; gap: 8px; }
.cell-name .name { font-weight: 500; color: #0f172a; }
.cell-name .err-hint { font-size: 11px; color: #b91c1c; margin-top: 2px; }
.cell-trigger { display: flex; align-items: center; gap: 6px; }
.cell-trigger .expr { font-size: 12px; color: #475569; font-family: ui-monospace, monospace; }
.prompt { font-size: 12px; color: #64748b; }
.cell-run { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #64748b; }
.cell-actions { display: flex; gap: 4px; }
.run-result .run-meta { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.run-conv { font-size: 12px; color: #64748b; font-family: ui-monospace, monospace; }
.run-error { font-size: 12px; color: #b91c1c; background: #fef2f2; border-radius: 6px; padding: 8px 12px; margin-bottom: 10px; }
.run-reply { font-size: 12px; color: #334155; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px; white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; margin: 0; }
</style>
