<template>
  <div class="im-page">
    <div class="toolbar">
      <div>
        <h2>IM 频道</h2>
        <p>管理 Web、飞书、钉钉等消息频道及其运行状态。</p>
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
                  v-if="isLongConnection(item.provider)"
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
            <template v-if="isLongConnection(item.provider)">
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
                <n-button
                  v-if="supportsScan(item.provider) && isAdmin"
                  size="small"
                  @click="openScan(item)"
                >
                  扫码创建应用
                </n-button>
                <n-button size="small" @click="toggle(item)">
                  {{ item.enabled ? '停用' : '启用' }}
                </n-button>
                <n-button
                  v-if="isLongConnection(item.provider)"
                  size="small"
                  :disabled="!item.enabled"
                  @click="reconnect(item)"
                >
                  重新连接
                </n-button>
                <n-button
                  v-if="isLongConnection(item.provider)"
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
            placeholder="长连接频道必须选择一个员工"
            filterable
          />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="form.enabled" />
        </n-form-item>

        <template v-if="isLongConnection(form.provider)">
          <n-divider>{{ providerLabel(form.provider) }}凭证</n-divider>
          <n-form-item v-if="supportsScan(form.provider)" label="接入方式">
            <n-radio-group v-model:value="form.credential_mode" size="small">
              <n-radio-button value="scan">扫码一键创建</n-radio-button>
              <n-radio-button value="manual">手工填写 {{ credentialFieldLabels.id }}</n-radio-button>
            </n-radio-group>
          </n-form-item>

          <template v-if="supportsScan(form.provider) && form.credential_mode === 'scan'">
            <n-alert class="form-note" type="info" :show-icon="false">
              {{ scanCredentialHint }}
            </n-alert>
            <p class="hint">
              {{ editing ? '保存后请在该频道卡片上点击「扫码创建应用」。' : '保存频道后会自动弹出二维码。' }}
            </p>
          </template>

          <template v-else>
            <n-form-item :label="credentialFieldLabels.id">
              <n-input v-model:value="form.app_id" />
            </n-form-item>
            <n-form-item :label="credentialFieldLabels.secret">
              <n-input
                v-model:value="form.app_secret"
                type="password"
                show-password-on="click"
                :placeholder="editing && editing.config?.configured ? '留空表示不更换' : ''"
              />
            </n-form-item>
            <p class="hint">{{ manualCredentialHint }}</p>
          </template>
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
      :show="showScan"
      preset="card"
      :title="scanModalTitle"
      style="width: 600px"
      :mask-closable="false"
      @update:show="onScanShowChange"
    >
      <n-alert class="scan-note" type="warning" :show-icon="false">
        <template v-if="scanChannel?.provider === 'feishu'">
          扫码创建的应用形态固定为「个人智能体」、预置权限不可裁剪，且<strong>默认仅创建者本人可见</strong>；
          要在群聊里 <code>@</code> 机器人，需先在飞书开发者后台放开可见范围（待办 T-1）。
          生产级企业自建应用请改用「手工填写 App ID / App Secret」。
        </template>
        <template v-else>
          扫码会在你的钉钉企业内新建一个机器人应用，凭据由钉钉直接下发、不经过浏览器。
          应用形态与权限范围由钉钉侧决定，建好后可在钉钉开发者后台按需调整。
          若要复用已有应用，请改用「手工填写 Client ID / Client Secret」。
        </template>
        <template v-if="scanChannel?.config?.configured">
          <br />该频道当前已有凭据，扫码会新建一个应用并覆盖原凭据。
        </template>
      </n-alert>

      <n-spin :show="scanStarting">
        <div v-if="scanStatus === 'pending'" class="scan-pending">
          <div class="qr-box" v-html="scanQrSvg" />
          <div class="scan-side">
            <p class="scan-step">
              用手机{{ scanProviderLabel }}扫描二维码，并在{{ scanProviderLabel }}内确认授权
            </p>
            <p v-if="scanSession?.user_code" class="scan-code">{{ scanSession.user_code }}</p>
            <p class="meta">剩余有效期：{{ remainingText }}</p>
            <p class="meta">授权成功后自动写入凭据并重连，无需再填 App Secret。</p>
            <n-button size="small" @click="cancelScan">取消本次扫码</n-button>
          </div>
        </div>

        <n-result
          v-else-if="scanStatus === 'success'"
          status="success"
          title="应用已创建，凭据已写入"
          :description="scanSuccessDescription"
        >
          <template #footer>
            <n-button size="small" type="primary" @click="onScanShowChange(false)">
              完成
            </n-button>
          </template>
        </n-result>

        <n-result
          v-else
          :status="scanResult.status"
          :title="scanResult.title"
          :description="scanResultDetail"
        >
          <template #footer>
            <n-space justify="center">
              <n-button size="small" @click="onScanShowChange(false)">关闭</n-button>
              <n-button size="small" type="primary" @click="restartScan">
                重新生成二维码
              </n-button>
            </n-space>
          </template>
        </n-result>
      </n-spin>

      <p class="hint scan-hint">
        App Secret 由服务端加密保存，不会回显到页面；关闭本窗口会自动取消未完成的扫码任务。
      </p>
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
import QRCode from 'qrcode'
import api from '../api.js'

// 扫码轮询：服务端 interval（实测 5 秒）是下限之外的参考值，前端不小于 2 秒。
const SCAN_POLL_MIN_MS = 2000
const SCAN_POLL_FALLBACK_SECONDS = 5

// 长连接渠道：由后端 Provider 建立 WebSocket 收发消息，因此有运行状态、重连与失败投递。
// 其余渠道（web）走 Webhook 或平台内置聊天，没有常驻连接。
const LONG_CONNECTION_PROVIDERS = ['feishu', 'dingtalk', 'wecom']
// 扫码一键创建应用：由后端 im/registration.py 的 RegistrationFlow 实现 Device Flow。
// 飞书走单端点 + action，钉钉走三个独立路径，两者共用同一套会话与接口。
const SCAN_PROVIDERS = ['feishu', 'dingtalk']

function isLongConnection(provider) {
  return LONG_CONNECTION_PROVIDERS.includes(provider)
}

function supportsScan(provider) {
  return SCAN_PROVIDERS.includes(provider)
}

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

// ---- 扫码一键创建应用（路径 B，对接 /api/im/channels/{id}/registration/*）----
const showScan = ref(false)
const scanChannel = ref(null)
const scanSession = ref(null)
const scanQrSvg = ref('')
const scanStarting = ref(false)
const scanError = ref('')
const scanCredential = ref(null)
const scanRemaining = ref(0)
let scanTimer = null
let scanIntervalMs = SCAN_POLL_FALLBACK_SECONDS * 1000
let scanLastPollAt = 0

const form = reactive({
  name: '',
  description: '',
  provider: 'feishu',
  enabled: true,
  employee_id: null,
  credential_mode: 'scan',
  app_id: '',
  app_secret: '',
})

const providerOptions = [
  { label: 'Web', value: 'web' },
  { label: '飞书', value: 'feishu' },
  { label: '钉钉', value: 'dingtalk' },
  { label: '企业微信', value: 'wecom' },
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

// 扫码相关文案全部按渠道切换：飞书那套「个人智能体 / 仅创建者可见」的代价在钉钉不存在。
const scanProviderLabel = computed(() => providerLabel(scanChannel.value?.provider) || '')

const scanModalTitle = computed(() => {
  const base = `扫码创建${scanProviderLabel.value}应用`
  return scanChannel.value?.name ? `${base} · ${scanChannel.value.name}` : base
})

const scanCredentialHint = computed(() => {
  const { secret } = credentialFieldLabelsFor(form.provider)
  if (form.provider === 'dingtalk') {
    return `由你的钉钉账号在本企业内自动创建机器人应用，${secret} 不经过浏览器。`
      + '应用形态与权限范围由钉钉侧决定，建好后可在开发者后台按需调整。'
  }
  return `由你的飞书账号在本企业内自动创建应用并预置权限，${secret} 不经过浏览器。`
    + '代价：应用形态固定为「个人智能体」、预置权限不可裁剪、默认仅创建者本人可见。'
})

const scanStatus = computed(() => scanSession.value?.status || 'idle')

const remainingText = computed(() => {
  const total = Math.max(0, Math.floor(scanRemaining.value))
  if (!total) return '已过期'
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return minutes > 0 ? `${minutes} 分 ${String(seconds).padStart(2, '0')} 秒` : `${seconds} 秒`
})

const scanResult = computed(() => {
  const fields = credentialFieldLabelsFor(scanChannel.value?.provider)
  const map = {
    denied: {
      status: 'warning',
      title: scanProviderLabel.value ? `${scanProviderLabel.value}端取消了授权` : '授权已取消',
      detail: '本次未创建任何应用。',
    },
    expired: { status: 'warning', title: '二维码已过期', detail: '二维码超过有效期，请重新生成。' },
    timeout: { status: 'warning', title: '二维码已过期', detail: '二维码超过有效期，请重新生成。' },
    cancelled: { status: 'info', title: '已取消', detail: '后台轮询任务已清理。' },
    error: {
      status: 'error',
      title: '创建失败',
      detail: `可重新发起，或改用手工填写 ${fields.id}。`,
    },
    idle: {
      status: 'error',
      title: '扫码创建暂不可用',
      detail: `请改用手工填写 ${fields.id} / ${fields.secret}。`,
    },
  }
  return map[scanStatus.value] || map.idle
})

const scanResultDetail = computed(
  () => scanError.value || scanSession.value?.error || scanResult.value.detail,
)

const scanSuccessDescription = computed(() => {
  const { id } = credentialFieldLabelsFor(scanChannel.value?.provider)
  const appId = scanSession.value?.app_id || '—'
  const configured = scanCredential.value?.configured === false ? '未配置' : '已配置'
  return `${id}：${appId} · 凭证状态：${configured}`
})

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

// 各渠道凭证字段语义相同（应用标识 + 密钥），只是平台叫法不同：飞书是 App ID/Secret，
// 钉钉是 Client ID/Secret，企微是 Bot ID/Secret。表单直接复用 form.app_id /
// form.app_secret 两个字段。
const CREDENTIAL_FIELD_LABELS = {
  dingtalk: { id: 'Client ID', secret: 'Client Secret' },
  wecom: { id: 'Bot ID', secret: 'Secret' },
}

function credentialFieldLabelsFor(provider) {
  return CREDENTIAL_FIELD_LABELS[provider] || { id: 'App ID', secret: 'App Secret' }
}

const credentialFieldLabels = computed(() => credentialFieldLabelsFor(form.provider))

const manualCredentialHint = computed(() => {
  if (form.provider === 'dingtalk') {
    return '钉钉自建应用：在钉钉开放平台创建「企业内部应用」后，把应用信息里的 Client ID / Client Secret 填到这里。'
      + '机器人收发消息走 Stream 模式长连接，无需公网回调地址，也不用填写加签或 Token；'
      + '企业标识会从消息中自动识别，不会映射为平台租户或继承平台权限。'
  }
  if (form.provider === 'wecom') {
    return '企业微信智能机器人：在工作台「智能机器人 → 手工创建 → API 模式 → 使用长连接」拿到 Bot ID 与 Secret 后填到这里。'
      + '消息收发走长连接，无需公网 IP 或回调地址，也不用填 Token / EncodingAESKey；'
      + '注意「长连接」与「设置接收消息回调地址」是互斥的两种 API 模式，切换会让现有长连接失效。'
  }
  return '企业自建应用：形态、权限、可见范围都能在飞书开发者后台自由配置，生产与群聊机器人推荐这种方式。'
    + '飞书外部租户标识会从事件中自动识别；不会映射为平台租户或继承平台权限。'
})

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
    credential_mode: 'scan',
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
    // 已有凭据时默认停在手工填写，避免误以为要重新扫码。
    credential_mode: item.config?.configured ? 'manual' : 'scan',
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
  if (isLongConnection(form.provider) && !form.employee_id) {
    error.value = `${providerLabel(form.provider)}频道必须选择一个默认员工`
    return
  }
  // 只有手工填写方式才强制两串凭据；扫码方式由后端在建应用后自动写入。
  const manualCredential = isLongConnection(form.provider)
    && !(supportsScan(form.provider) && form.credential_mode === 'scan')
  if (manualCredential && !editing.value && (!form.app_id || !form.app_secret)) {
    error.value = `手工填写方式需要同时提供 ${credentialFieldLabels.value.id} 和 ${credentialFieldLabels.value.secret}`
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
    if (isLongConnection(form.provider) && form.app_id && form.app_secret) {
      await api.put(`/im/channels/${channelId}/credentials`, {
        app_id: form.app_id.trim(),
        app_secret: form.app_secret,
      })
    }
    const createdWithScan =
      supportsScan(form.provider) && form.credential_mode === 'scan' && !editing.value
    showForm.value = false
    await load()
    if (createdWithScan && isAdmin.value) {
      // 新建频道选扫码：直接把二维码推出来，省掉「回卡片找按钮」这一步。
      // provider 必须带上，扫码文案按渠道切换（飞书的代价说明不适用于钉钉）。
      await openScan({ id: channelId, name: form.name.trim(), provider: form.provider })
    }
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

// ---------- 扫码一键创建 ----------

function stopScanTimer() {
  if (scanTimer) {
    window.clearInterval(scanTimer)
    scanTimer = null
  }
}

function resetScanState() {
  stopScanTimer()
  scanSession.value = null
  scanQrSvg.value = ''
  scanError.value = ''
  scanCredential.value = null
  scanRemaining.value = 0
}

async function openScan(channel) {
  scanChannel.value = channel
  resetScanState()
  showScan.value = true
  await startScan()
}

async function renderScanQr(url) {
  if (!url) return
  try {
    scanQrSvg.value = await QRCode.toString(url, {
      type: 'svg',
      margin: 1,
      errorCorrectionLevel: 'M',
    })
  } catch {
    scanError.value = '二维码渲染失败，请重新生成或改用手工填写 App ID'
  }
}

function applyScanSnapshot(snapshot) {
  scanSession.value = snapshot
  scanRemaining.value = Number(snapshot?.remaining_seconds) || 0
  if (snapshot?.status === 'success') {
    scanCredential.value = snapshot.credential || null
    stopScanTimer()
    load(false)
    return
  }
  if (snapshot?.status && snapshot.status !== 'pending') {
    stopScanTimer()
  }
}

function startScanTimer(intervalSeconds) {
  stopScanTimer()
  const seconds = Number(intervalSeconds) || SCAN_POLL_FALLBACK_SECONDS
  scanIntervalMs = Math.max(SCAN_POLL_MIN_MS, Math.round(seconds * 1000))
  scanLastPollAt = Date.now()
  scanTimer = window.setInterval(onScanTick, 1000)
}

async function onScanTick() {
  if (scanStatus.value !== 'pending') return
  if (scanRemaining.value > 0) scanRemaining.value -= 1
  if (Date.now() - scanLastPollAt < scanIntervalMs) return
  scanLastPollAt = Date.now()
  await pollScan()
}

async function pollScan() {
  const channel = scanChannel.value
  const session = scanSession.value
  if (!channel?.id || !session?.session_id) return
  try {
    const { data } = await api.get(
      `/im/channels/${channel.id}/registration/${session.session_id}`,
    )
    applyScanSnapshot(data)
  } catch (e) {
    if (e.response?.status === 404) {
      // 会话只在内存里，服务重启后会丢；此时提示重来，不要静默卡住。
      stopScanTimer()
      scanSession.value = { ...session, status: 'error' }
      scanError.value = '扫码会话已失效（服务可能已重启），请重新生成二维码'
    }
  }
}

async function startScan() {
  const channel = scanChannel.value
  if (!channel?.id) return
  scanStarting.value = true
  scanError.value = ''
  try {
    const { data } = await api.post(`/im/channels/${channel.id}/registration/start`)
    applyScanSnapshot(data)
    await renderScanQr(data?.qr_url)
    startScanTimer(data?.interval)
  } catch (e) {
    // 503 表示环境不支持扫码（例如出网被拦），页面应引导回手工填写。
    scanError.value = e.response?.data?.detail || '扫码创建暂不可用，请改用手工填写 App ID / App Secret'
  } finally {
    scanStarting.value = false
  }
}

async function restartScan() {
  resetScanState()
  await startScan()
}

async function cancelScan() {
  const channel = scanChannel.value
  const session = scanSession.value
  if (!channel?.id || !session?.session_id || session.status !== 'pending') return
  stopScanTimer()
  try {
    const { data } = await api.post(
      `/im/channels/${channel.id}/registration/${session.session_id}/cancel`,
    )
    applyScanSnapshot(data)
  } catch (e) {
    error.value = e.response?.data?.detail || '取消失败'
    scanSession.value = { ...session, status: 'cancelled' }
  }
}

async function cancelPendingOnLeave() {
  const channel = scanChannel.value
  const session = scanSession.value
  if (!channel?.id || !session?.session_id || session.status !== 'pending') return
  try {
    await api.post(`/im/channels/${channel.id}/registration/${session.session_id}/cancel`)
  } catch {
    // 关窗时的取消失败不打扰用户：后端在超时或进程退出时也会清理。
  }
}

function onScanShowChange(value) {
  showScan.value = value
  if (value) return
  // 关闭即放弃：取消未完成的扫码会话，避免留下悬挂轮询与重复建应用。
  void cancelPendingOnLeave()
  resetScanState()
  scanChannel.value = null
  void load(false)
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
  stopScanTimer()
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
.form-note { margin-bottom: 8px; }
.scan-note { margin-bottom: 16px; }
.scan-note code { padding: 0 4px; background: rgba(0, 0, 0, .06); border-radius: 3px; }
.scan-pending { display: flex; gap: 20px; align-items: flex-start; }
.qr-box { width: 196px; height: 196px; flex: none; padding: 8px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; }
.qr-box :deep(svg) { display: block; width: 180px; height: 180px; }
.scan-side { flex: 1; min-width: 0; }
.scan-step { margin: 0 0 8px; color: #0f172a; }
.scan-code { margin: 0 0 8px; color: #0f172a; font-size: 20px; font-weight: 600; letter-spacing: 2px; }
.scan-side .meta { margin-top: 0; margin-bottom: 4px; }
.scan-side :deep(.n-button) { margin-top: 10px; }
.scan-hint { margin: 16px 0 0; }
</style>
