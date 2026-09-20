<template>
  <div class="im-page">
    <div class="toolbar">
      <div>
        <h2>IM 频道</h2>
        <p>管理 Web、飞书等消息频道及其运行状态。</p>
      </div>
      <n-button v-if="isAdmin" type="primary" @click="openCreate">新建频道</n-button>
    </div>

    <n-alert v-if="error" type="error" closable @close="error = ''">
      {{ error }}
    </n-alert>

    <n-spin :show="loading">
      <n-empty v-if="!loading && !items.length" description="暂无 IM 频道" />
      <n-grid v-else cols="1 m:2" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in items" :key="item.id">
          <n-card size="small" :title="item.name">
            <template #header-extra>
              <n-space>
                <n-tag size="small" :type="item.enabled ? 'success' : 'default'">
                  {{ item.enabled ? '已启用' : '已停用' }}
                </n-tag>
                <n-tag
                  v-if="item.provider === 'feishu'"
                  size="small"
                  :type="runtimeTag(item.runtime?.status)"
                >
                  {{ runtimeLabel(item.runtime?.status) }}
                </n-tag>
              </n-space>
            </template>

            <p>{{ item.description || '暂无描述' }}</p>
            <div class="meta">类型：{{ providerLabel(item.provider) }}</div>
            <div class="meta">默认员工：{{ item.employees?.[0]?.name || '未配置' }}</div>
            <template v-if="item.provider === 'feishu'">
              <div class="meta">凭证：{{ item.config?.configured ? '已配置' : '未配置' }}</div>
              <div class="meta">最近连接：{{ formatTime(item.runtime?.last_connected_at) }}</div>
              <div class="meta">最近入站：{{ formatTime(item.runtime?.last_inbound_at) }}</div>
              <div class="meta">最近出站：{{ formatTime(item.runtime?.last_outbound_at) }}</div>
              <n-alert
                v-if="item.runtime?.last_error"
                class="runtime-error"
                type="warning"
                :show-icon="false"
              >
                {{ item.runtime.last_error }}
              </n-alert>
            </template>

            <template #footer>
              <n-space>
                <n-button size="small" @click="edit(item)">编辑</n-button>
                <n-button size="small" @click="toggle(item)">
                  {{ item.enabled ? '停用' : '启用' }}
                </n-button>
                <n-button
                  v-if="item.provider === 'feishu'"
                  size="small"
                  :disabled="!item.enabled"
                  @click="reconnect(item)"
                >
                  重新连接
                </n-button>
                <n-button
                  v-if="item.provider === 'feishu'"
                  size="small"
                  @click="openDeadLetters(item)"
                >
                  失败投递
                </n-button>
              </n-space>
            </template>
          </n-card>
        </n-gi>
      </n-grid>
    </n-spin>

    <n-modal
      v-model:show="showForm"
      preset="card"
      :title="editing ? '编辑频道' : '新建频道'"
      style="width: 560px"
    >
      <n-form label-placement="left" label-width="90">
        <n-form-item label="名称">
          <n-input v-model:value="form.name" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="form.description" />
        </n-form-item>
        <n-form-item label="类型">
          <n-select
            v-model:value="form.provider"
            :options="providerOptions"
            :disabled="!!editing"
          />
        </n-form-item>
        <n-form-item label="默认员工">
          <n-select
            v-model:value="form.employee_id"
            :options="employeeOptions"
            placeholder="飞书频道必须选择一个员工"
            filterable
          />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="form.enabled" />
        </n-form-item>

        <template v-if="form.provider === 'feishu'">
          <n-divider>飞书凭证</n-divider>
          <n-form-item label="App ID">
            <n-input v-model:value="form.app_id" />
          </n-form-item>
          <n-form-item label="App Secret">
            <n-input
              v-model:value="form.app_secret"
              type="password"
              show-password-on="click"
              :placeholder="editing && editing.config?.configured ? '留空表示不更换' : ''"
            />
          </n-form-item>
          <p class="hint">
            飞书外部租户标识会从事件中自动识别；不会映射为平台租户或继承平台权限。
          </p>
        </template>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showForm = false">取消</n-button>
          <n-button type="primary" :loading="saving" @click="save">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal
      v-model:show="showDeadLetters"
      preset="card"
      :title="`${deadChannel?.name || ''} · 失败投递`"
      style="width: 760px"
    >
      <n-spin :show="deadLoading">
        <n-empty v-if="!deadItems.length" description="暂无 Dead Letter" />
        <n-list v-else bordered>
          <n-list-item v-for="job in deadItems" :key="job.id">
            <div class="dead-job">
              <div>
                <strong>{{ job.id }}</strong>
                <div class="meta">尝试次数：{{ job.attempts }} · {{ formatTime(job.updated_at) }}</div>
                <div class="dead-error">{{ job.error || '未知错误' }}</div>
              </div>
              <n-button size="small" type="primary" @click="replay(job)">重新投递</n-button>
            </div>
          </n-list-item>
        </n-list>
      </n-spin>
    </n-modal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import api from '../api.js'

const items = ref([])
const employees = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const showForm = ref(false)
const editing = ref(null)
const showDeadLetters = ref(false)
const deadLoading = ref(false)
const deadItems = ref([])
const deadChannel = ref(null)
let pollTimer = null

const form = reactive({
  name: '',
  description: '',
  provider: 'feishu',
  enabled: true,
  employee_id: null,
  app_id: '',
  app_secret: '',
})

const providerOptions = [
  { label: 'Web', value: 'web' },
  { label: '飞书', value: 'feishu' },
  { label: '钉钉（后续开发）', value: 'dingtalk', disabled: true },
  { label: '企业微信（后续开发）', value: 'wecom', disabled: true },
]

const isAdmin = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('user') || '{}').role === 'admin'
  } catch {
    return false
  }
})

const employeeOptions = computed(() =>
  employees.value.map((item) => ({ label: item.name || item.id, value: item.id })),
)

function runtimeLabel(status) {
  return {
    disabled: '未运行',
    unconfigured: '未配置',
    connecting: '连接中',
    connected: '已连接',
    reconnecting: '重连中',
    failed: '连接失败',
  }[status] || '未知状态'
}

function runtimeTag(status) {
  return {
    connected: 'success',
    connecting: 'info',
    reconnecting: 'warning',
    failed: 'error',
    unconfigured: 'warning',
  }[status] || 'default'
}

function providerLabel(provider) {
  return { web: 'Web', feishu: '飞书', dingtalk: '钉钉', wecom: '企业微信' }[provider] || provider
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function load(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [channelsResult, employeesResult] = await Promise.all([
      api.get('/im/channels'),
      employees.value.length ? Promise.resolve(null) : api.get('/employees'),
    ])
    items.value = channelsResult.data.items || []
    if (employeesResult) employees.value = employeesResult.data || []
  } catch (e) {
    error.value = e.response?.data?.detail || '频道加载失败'
  } finally {
    if (showLoading) loading.value = false
  }
}

function resetForm() {
  Object.assign(form, {
    name: '',
    description: '',
    provider: 'feishu',
    enabled: true,
    employee_id: null,
    app_id: '',
    app_secret: '',
  })
}

function openCreate() {
  editing.value = null
  resetForm()
  showForm.value = true
}

function edit(item) {
  editing.value = item
  Object.assign(form, {
    name: item.name,
    description: item.description || '',
    provider: item.provider,
    enabled: item.enabled,
    employee_id: item.employees?.[0]?.id || null,
    app_id: item.config?.app_id || '',
    app_secret: '',
  })
  showForm.value = true
}

async function save() {
  if (!form.name.trim()) {
    error.value = '请输入频道名称'
    return
  }
  if (form.provider === 'feishu' && !form.employee_id) {
    error.value = '飞书频道必须选择一个默认员工'
    return
  }
  if (form.provider === 'feishu' && !editing.value && (!form.app_id || !form.app_secret)) {
    error.value = '新建飞书频道必须填写 App ID 和 App Secret'
    return
  }

  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      description: form.description,
      provider: form.provider,
      enabled: form.enabled,
      employee_ids: form.employee_id ? [form.employee_id] : [],
    }
    const url = editing.value
      ? `/im/channels/${editing.value.id}`
      : '/im/channels'
    const saved = await api[editing.value ? 'put' : 'post'](url, payload)
    const channelId = editing.value?.id || saved.data.id
    if (form.provider === 'feishu' && form.app_id && form.app_secret) {
      await api.put(`/im/channels/${channelId}/credentials`, {
        app_id: form.app_id.trim(),
        app_secret: form.app_secret,
      })
    }
    showForm.value = false
    await load()
  } catch (e) {
    error.value = e.response?.data?.detail || '保存失败'
  } finally {
    saving.value = false
  }
}

async function toggle(item) {
  try {
    await api.put(`/im/channels/${item.id}`, { enabled: !item.enabled })
    await load(false)
  } catch (e) {
    error.value = e.response?.data?.detail || '更新失败'
  }
}

async function reconnect(item) {
  try {
    await api.post(`/im/channels/${item.id}/reconnect`)
    await load(false)
  } catch (e) {
    error.value = e.response?.data?.detail || '重连失败'
  }
}

async function openDeadLetters(item) {
  deadChannel.value = item
  showDeadLetters.value = true
  deadLoading.value = true
  try {
    const { data } = await api.get(`/im/channels/${item.id}/outbox`, {
      params: { status: 'dead', limit: 50 },
    })
    deadItems.value = data.items || []
  } catch (e) {
    error.value = e.response?.data?.detail || '失败投递加载失败'
  } finally {
    deadLoading.value = false
  }
}

async function replay(job) {
  try {
    await api.post(`/im/outbox/${job.id}/replay`)
    deadItems.value = deadItems.value.filter((item) => item.id !== job.id)
  } catch (e) {
    error.value = e.response?.data?.detail || '重新投递失败'
  }
}

onMounted(async () => {
  await load()
  pollTimer = window.setInterval(() => load(false), 5000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.im-page { padding: 24px; height: 100%; overflow: auto; }
.toolbar { display: flex; justify-content: space-between; margin-bottom: 20px; }
h2 { margin: 0 0 6px; }
.toolbar p, .im-page p, .meta { color: #64748b; }
.toolbar p { margin: 0; }
.meta { margin-top: 6px; font-size: 13px; }
.runtime-error { margin-top: 12px; }
.hint { margin: -4px 0 0 90px; font-size: 12px; }
.dead-job { display: flex; justify-content: space-between; gap: 16px; width: 100%; }
.dead-error { margin-top: 6px; color: #b45309; word-break: break-word; }
</style>
