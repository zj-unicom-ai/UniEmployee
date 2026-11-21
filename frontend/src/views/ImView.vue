<template>
  <div class="im-page">
    <div class="page-head">
      <div>
        <div class="page-title">原生 IM 多平台接入</div>
        <div class="page-subtitle">
          复用 Octop 的协议适配器，把飞书、钉钉、企业微信、微信、QQ、元宝及海外平台消息接入 UniEmployee 数字员工。
        </div>
      </div>
      <n-button v-if="isAdmin" type="primary" @click="openCreate()">新增平台通道</n-button>
    </div>

    <n-alert class="setup-alert" type="info" :show-icon="false">
      原生通道需要配置平台机器人凭据，并为通道绑定一个数字员工。凭据在数据库中加密保存；首次配置前请在服务端设置
      <code>CONNECTOR_OAUTH_ENCRYPTION_KEY</code>。旧版通用 Webhook 通道仍可继续使用。
    </n-alert>

    <div v-if="loading" class="loading-state">正在读取通道配置…</div>
    <div v-else-if="!items.length" class="empty-state">
      <div class="empty-title">还没有 IM 通道</div>
      <div class="empty-desc">创建平台机器人通道后，用户就能在对应的 IM 应用中与数字员工对话。</div>
      <n-button v-if="isAdmin" type="primary" @click="openCreate()">配置第一个通道</n-button>
    </div>
    <div v-else class="channel-grid">
      <n-card v-for="row in items" :key="row.id" class="channel-card" size="small" :bordered="true">
        <div class="card-head">
          <div>
            <div class="card-title">{{ row.name }}</div>
            <div class="card-platform">{{ providerName(row.provider || row.kind) }}</div>
          </div>
          <n-tag :type="statusType(row)" size="small" round>
            {{ statusText(row) }}
          </n-tag>
        </div>
        <div v-if="row.description" class="card-description">{{ row.description }}</div>
        <div class="card-meta">
          <span>数字员工</span>
          <span>{{ employeeNames(row) || '尚未绑定' }}</span>
        </div>
        <div v-if="row.runtime?.error" class="runtime-error">{{ row.runtime.error }}</div>
        <div v-if="row.inbound_url" class="webhook-line">
          入站地址 <code>{{ absoluteApiUrl(row.inbound_url) }}</code>
        </div>
        <div class="card-actions">
          <n-button v-if="isAdmin && isNative(row)" size="tiny" @click="probe(row)" :loading="probingId === row.id">
            测试连接
          </n-button>
          <n-button v-if="isAdmin && row.provider !== 'web'" size="tiny" @click="openEdit(row)">编辑</n-button>
          <n-button v-if="isAdmin && row.provider !== 'web'" size="tiny" type="error" quaternary @click="remove(row)">删除</n-button>
          <n-tag v-if="!row.enabled" type="warning" size="tiny">已停用</n-tag>
        </div>
      </n-card>
    </div>

    <n-modal v-model:show="showForm" preset="card" :title="editing ? '编辑 IM 通道' : '新增 IM 通道'"
             class="channel-modal" :mask-closable="false">
      <n-form label-placement="top" size="small">
        <div class="form-intro" v-if="selectedProvider">
          <div>{{ selectedProvider.description }}</div>
          <a v-if="selectedProvider.intro_url" :href="selectedProvider.intro_url" target="_blank" rel="noreferrer">
            打开平台机器人后台
          </a>
        </div>
        <n-form-item v-if="!editing" label="接入平台" required>
          <n-select v-model:value="form.provider" :options="providerOptions" @update:value="onProviderChange" />
        </n-form-item>
        <n-form-item v-if="supportsNativeMode" label="接入方式" required>
          <n-select v-model:value="form.mode" :options="modeOptions" @update:value="onModeChange" />
        </n-form-item>
        <n-form-item label="通道名称" required>
          <n-input v-model:value="form.name" placeholder="例如：浙江联通飞书机器人" />
        </n-form-item>
        <n-form-item label="说明">
          <n-input v-model:value="form.description" placeholder="可选，描述通道用途" />
        </n-form-item>
        <n-form-item label="绑定数字员工" required>
          <n-select v-model:value="form.employee_id" :options="employeeOptions" filterable placeholder="选择收到消息后运行的员工" />
        </n-form-item>
        <template v-for="field in (selectedProvider?.fields || [])" :key="field.name">
          <n-form-item :label="field.label" :required="field.required && !secretAlreadySet(field.name)">
            <n-switch v-if="field.type === 'switch'" v-model:value="form.config[field.name]" />
            <n-input-number v-else-if="field.type === 'number'" v-model:value="form.config[field.name]" :min="1" style="width:100%" />
            <n-input v-else-if="field.type === 'json' || field.type === 'textarea'"
                     v-model:value="form.config[field.name]" type="textarea" :rows="field.type === 'json' ? 5 : 3"
                     :placeholder="field.placeholder || (secretAlreadySet(field.name) ? '已保存；留空保持原值' : '')" />
            <n-input v-else v-model:value="form.config[field.name]"
                     :type="field.type === 'password' ? 'password' : 'text'"
                     :show-password-on="field.type === 'password' ? 'click' : undefined"
                     :placeholder="field.placeholder || (secretAlreadySet(field.name) ? '已保存；留空保持原值' : '')" />
            <template #feedback v-if="secretAlreadySet(field.name)">已保存凭据；留空可保留当前值。</template>
          </n-form-item>
        </template>
        <n-form-item label="启用通道">
          <n-switch v-model:value="form.enabled" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div class="modal-actions">
          <span class="required-note">带 * 的字段必填</span>
          <div>
            <n-button @click="showForm = false">取消</n-button>
            <n-button type="primary" :loading="saving" @click="save">{{ editing ? '保存修改' : '创建并连接' }}</n-button>
          </div>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'

defineOptions({ name: 'ImView' })

const auth = useAuthStore()
const message = useMessage()
const dialog = useDialog()
const isAdmin = computed(() => auth.isAdmin)
const loading = ref(false)
const saving = ref(false)
const showForm = ref(false)
const items = ref([])
const providers = ref([])
const employees = ref([])
const editing = ref(null)
const probingId = ref('')
const secretFields = ref([])
const form = reactive({
  name: '', description: '', provider: '', mode: 'native', employee_id: null, config: {}, enabled: true,
})

const providerOptions = computed(() => providers.value.map(p => ({ label: p.name, value: p.kind })))
const modeOptions = [
  { label: '原生长连接 / 轮询', value: 'native' },
  { label: '通用 Webhook', value: 'webhook' },
]
const employeeOptions = computed(() => employees.value.map(e => ({ label: `${e.name}（${e.id}）`, value: e.id })))
const supportsNativeMode = computed(() => providers.value.some(p => p.kind === form.provider && p.kind !== 'generic'))
const selectedProvider = computed(() => {
  const kind = form.mode === 'webhook' && form.provider !== 'generic' ? 'generic' : form.provider
  return providers.value.find(p => p.kind === kind) || null
})

function providerName(kind) {
  if (kind === 'web') return '平台内 Web 聊天'
  return providers.value.find(p => p.kind === kind)?.name || kind
}

function isNative(row) {
  return row.mode === 'native'
}

function statusText(row) {
  if (!row.enabled) return '已停用'
  if ((row.provider || row.kind) === 'web') return '可用'
  if (row.mode !== 'native') return 'Webhook'
  if (row.runtime?.connected === true) return '已连接'
  if (row.runtime?.connected === false && row.runtime?.running) return '运行中，未连通'
  if (row.runtime?.running) return '已启动，状态待确认'
  return row.runtime?.error ? '连接异常' : '未连接'
}

function statusType(row) {
  if (!row.enabled) return 'warning'
  if ((row.provider || row.kind) === 'web') return 'success'
  if (row.mode !== 'native') return 'info'
  if (row.runtime?.connected === true) return 'success'
  if (row.runtime?.error) return 'error'
  return row.runtime?.running ? 'info' : 'default'
}

function employeeNames(row) {
  return (row.employees || []).map(e => e.name).join('、')
}

function absoluteApiUrl(path) {
  return `${location.origin}/api${path}`
}

async function load() {
  loading.value = true
  try {
    const calls = [api.get('/im/channels'), api.get('/im/providers')]
    if (isAdmin.value) calls.push(api.get('/admin/employees'))
    const [channelRes, providerRes, employeeRes] = await Promise.all(calls)
    items.value = channelRes.data.items || []
    providers.value = providerRes.data.items || []
    employees.value = employeeRes?.data || []
  } catch (err) {
    message.error(err.response?.data?.detail || '读取 IM 通道失败')
  } finally {
    loading.value = false
  }
}

function resetForm(provider = providers.value[0]?.kind || '') {
  const mode = provider === 'generic' ? 'webhook' : 'native'
  const configProvider = mode === 'webhook' && provider !== 'generic' ? 'generic' : provider
  Object.assign(form, {
    name: '', description: '', provider, mode, employee_id: employees.value[0]?.id || null,
    config: initialConfig(configProvider), enabled: true,
  })
}

function initialConfig(provider) {
  const defaults = {
    discord: { allow_all_channels: true },
    mqtt: { port: 8883, transport: 'tcp', tls_enabled: true, subscribe_topic: 'devices/+/in', publish_topic: 'devices/{client_id}/out' },
    yuanbao: { api_domain: 'https://bot.yuanbao.tencent.com', ws_url: 'wss://bot-wss.yuanbao.tencent.com/wss/connection' },
  }
  const config = { ...(defaults[provider] || {}) }
  for (const field of providers.value.find(p => p.kind === provider)?.fields || []) {
    if (field.type === 'textarea' || field.type === 'json') config[field.name] = ''
  }
  return config
}

function onProviderChange(kind) {
  form.mode = kind === 'generic' ? 'webhook' : 'native'
  form.config = initialConfig(form.mode === 'webhook' && kind !== 'generic' ? 'generic' : kind)
}

function onModeChange(mode) {
  const configProvider = mode === 'webhook' && form.provider !== 'generic' ? 'generic' : form.provider
  form.config = { ...initialConfig(configProvider), ...form.config }
}

function openCreate(provider) {
  editing.value = null
  secretFields.value = []
  resetForm(provider)
  showForm.value = true
}

function openEdit(row) {
  if (row.provider === 'web') return
  editing.value = row
  secretFields.value = row.secret_fields || []
  const config = { ...(row.config || {}) }
  const mode = row.mode || 'webhook'
  const configProvider = mode === 'webhook' && row.provider !== 'generic' ? 'generic' : row.provider
  for (const field of providers.value.find(p => p.kind === configProvider)?.fields || []) {
    if (Array.isArray(config[field.name]) && field.type === 'textarea') {
      config[field.name] = config[field.name].join(', ')
    } else if (field.type === 'json' && config[field.name] !== undefined) {
      config[field.name] = JSON.stringify(config[field.name], null, 2)
    }
  }
  Object.assign(form, {
    name: row.name,
    description: row.description || '',
    provider: row.provider,
    mode,
    employee_id: row.employees?.[0]?.id || null,
    config,
    enabled: Boolean(row.enabled),
  })
  showForm.value = true
}

function secretAlreadySet(name) {
  return secretFields.value.some(value => value === name || value.startsWith(`${name}.`))
}

function prepareConfig() {
  const config = { ...form.config }
  for (const field of selectedProvider.value?.fields || []) {
    if (field.type === 'json' && typeof config[field.name] === 'string') {
      const raw = config[field.name].trim()
      if (!raw && editing.value && secretAlreadySet(field.name)) {
        config[field.name] = editing.value.config?.[field.name] || []
      } else if (raw) {
        config[field.name] = JSON.parse(raw)
      } else {
        config[field.name] = []
      }
    }
    if (field.type === 'textarea' && ['allowed_user_ids', 'allowed_chat_ids', 'allowed_channel_ids'].includes(field.name)) {
      const value = config[field.name]
      config[field.name] = Array.isArray(value)
        ? value
        : String(value || '').split(/[\s,]+/).filter(Boolean)
    }
  }
  return config
}

function validateConfig(config) {
  for (const field of selectedProvider.value?.fields || []) {
    if (!field.required) continue
    const value = config[field.name]
    if (value && (!Array.isArray(value) || value.length)) continue
    if (editing.value && secretAlreadySet(field.name)) continue
    if (field.name === 'accounts' && editing.value && secretAlreadySet('accounts')) continue
    message.warning(`请填写${field.label}`)
    return false
  }
  if (!form.name.trim()) {
    message.warning('请填写通道名称')
    return false
  }
  if (!form.employee_id) {
    message.warning('请选择绑定的数字员工')
    return false
  }
  if (form.mode === 'native' && form.provider === 'weixin' && Array.isArray(config.accounts)) {
    const invalid = config.accounts.some(account => !account?.account_id || (!account?.token && !secretAlreadySet('accounts')))
    if (invalid) {
      message.warning('每个微信账号都要填写 account_id 和 token')
      return false
    }
  }
  return true
}

async function save() {
  let config
  try {
    config = prepareConfig()
  } catch {
    message.error('配置 JSON 格式无效，请检查后重试')
    return
  }
  if (!validateConfig(config)) return
  saving.value = true
  try {
    const body = {
      name: form.name.trim(),
      description: form.description.trim(),
      provider: form.provider,
      mode: form.mode,
      config,
      enabled: form.enabled,
      employee_ids: [form.employee_id],
    }
    if (editing.value) {
      await api.put(`/im/channels/${editing.value.id}`, body)
      message.success('IM 通道配置已更新')
    } else {
      await api.post('/im/channels', body)
      message.success('IM 通道已创建')
    }
    showForm.value = false
    await load()
  } catch (err) {
    message.error(err.response?.data?.detail || '保存通道失败')
  } finally {
    saving.value = false
  }
}

async function probe(row) {
  probingId.value = row.id
  try {
    const { data } = await api.post(`/im/channels/${row.id}/probe`)
    if (data.ok) message.success('通道启动检查通过；持续状态请查看通道卡片')
    else message.error(data.error || '连接校验失败')
    await load()
  } catch (err) {
    message.error(err.response?.data?.detail || '连接校验失败')
  } finally {
    probingId.value = ''
  }
}

function remove(row) {
  dialog.warning({
    title: '删除 IM 通道',
    content: `确认删除“${row.name}”？现有会话记录会保留，平台连接将停止。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.delete(`/im/channels/${row.id}`)
        message.success('通道已删除')
        await load()
      } catch (err) {
        message.error(err.response?.data?.detail || '删除通道失败')
      }
    },
  })
}

onMounted(load)
</script>

<style scoped>
.im-page { min-height: 100%; padding: 24px 28px 40px; color: #1e293b; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.page-title { font-size: 22px; font-weight: 700; letter-spacing: -.02em; }
.page-subtitle { color: #64748b; font-size: 13px; margin-top: 7px; max-width: 900px; line-height: 1.65; }
.setup-alert { margin-bottom: 20px; line-height: 1.7; }
.setup-alert code, .webhook-line code { padding: 2px 5px; border-radius: 4px; background: #f1f5f9; color: #334155; overflow-wrap: anywhere; }
.loading-state, .empty-state { padding: 64px 20px; text-align: center; color: #64748b; }
.empty-title { color: #334155; font-size: 16px; font-weight: 650; margin-bottom: 8px; }
.empty-desc { margin: 0 auto 20px; max-width: 560px; font-size: 13px; }
.channel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.channel-card { border-radius: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.card-title { font-weight: 650; font-size: 15px; color: #0f172a; }
.card-platform { margin-top: 4px; color: #64748b; font-size: 12px; }
.card-description { margin-top: 14px; color: #64748b; font-size: 12px; min-height: 34px; line-height: 1.55; }
.card-meta { margin-top: 14px; padding-top: 11px; border-top: 1px solid #f1f5f9; display: flex; justify-content: space-between; gap: 10px; color: #64748b; font-size: 12px; }
.card-meta span:last-child { color: #334155; text-align: right; }
.runtime-error { margin-top: 10px; color: #d03050; font-size: 12px; line-height: 1.5; }
.webhook-line { margin-top: 10px; font-size: 11px; color: #64748b; overflow-wrap: anywhere; }
.card-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; margin-top: 15px; }
.channel-modal { width: min(700px, 94vw); }
.form-intro { padding: 10px 12px; background: #f8fafc; border-radius: 8px; color: #64748b; font-size: 12px; line-height: 1.65; margin-bottom: 14px; }
.form-intro a { display: inline-block; margin-top: 6px; color: #2563eb; text-decoration: none; }
.modal-actions { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.modal-actions > div { display: flex; gap: 8px; }
.required-note { color: #94a3b8; font-size: 12px; }
@media (max-width: 680px) {
  .im-page { padding: 18px 14px 30px; }
  .page-head { flex-direction: column; }
  .page-head > :deep(.n-button) { align-self: flex-start; }
  .channel-grid { grid-template-columns: 1fr; }
}
</style>
