<!-- 我的连接器：管理当前用户针对已分配员工的远程 MCP OAuth 授权。 -->
<template>
  <div class="connector-page">
    <div class="page-heading">
      <div>
        <h2>我的连接器</h2>
        <p>授权后，已分配给你的数字员工可以使用对应 MCP 服务。授权凭据只属于当前账号。</p>
      </div>
      <n-button secondary :loading="loading" @click="load">刷新</n-button>
    </div>

    <n-alert v-if="notice" :type="notice.type" :title="notice.title" class="notice">
      {{ notice.message }}
    </n-alert>

    <n-spin :show="loading">
      <div v-if="items.length" class="connector-grid">
        <n-card v-for="item in items" :key="item.id" class="connector-card" bordered>
          <div class="card-heading">
            <div>
              <div class="connector-name">{{ item.name }}</div>
              <div class="connector-id">{{ item.id }}</div>
            </div>
            <n-tag :type="statusType(item.status)" size="small" round>
              {{ statusLabel(item) }}
            </n-tag>
          </div>
          <p class="description">{{ item.description || '远程 MCP 连接器' }}</p>
          <div class="employee-line">
            可用于：{{ item.employees?.join('、') || '已分配员工' }}
          </div>
          <div v-if="item.scopes" class="scope-line">授权范围：{{ item.scopes }}</div>
          <div class="card-actions">
            <n-button type="primary" size="small" :loading="busyId === item.id" @click="connect(item)">
              {{ item.status === 'disconnected' ? '连接账号' : '重新授权' }}
            </n-button>
            <n-button
              v-if="item.status !== 'disconnected'"
              size="small"
              quaternary
              type="error"
              :loading="busyId === item.id + ':disconnect'"
              @click="disconnect(item)"
            >
              移除本地授权
            </n-button>
          </div>
        </n-card>
      </div>
      <n-empty v-else-if="!loading" description="当前没有可授权的 OAuth 连接器">
        <template #extra>
          <span class="empty-help">管理员需要先在资源中心配置 OAuth MCP 连接器，并将它指派给员工。</span>
        </template>
      </n-empty>
    </n-spin>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api.js'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const loading = ref(false)
const items = ref([])
const busyId = ref('')
const callbackResult = ref('')

const notice = computed(() => {
  const result = callbackResult.value || route.query.oauth
  if (result === 'connected') return { type: 'success', title: '授权完成', message: '连接器已绑定到当前账号。' }
  if (result === 'denied') return { type: 'warning', title: '授权未完成', message: '你取消了服务端的授权请求。' }
  if (result === 'failed') return { type: 'error', title: '授权失败', message: '授权链接已失效或服务端未完成令牌交换，请重新发起授权。' }
  return null
})

function statusLabel(item) {
  if (item.status === 'connected') return '已授权'
  if (item.status === 'refresh_required') return '令牌待刷新'
  if (item.status === 'reauthorization_required') return '需要重新授权'
  return '未连接'
}

function statusType(status) {
  if (status === 'connected') return 'success'
  if (status === 'reauthorization_required') return 'error'
  if (status === 'refresh_required') return 'warning'
  return 'default'
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/connectors')
    items.value = data.items || []
  } catch (error) {
    message.error(error.response?.data?.detail || '连接器列表读取失败')
  } finally {
    loading.value = false
  }
}

async function connect(item) {
  busyId.value = item.id
  try {
    const { data } = await api.post(`/connectors/${encodeURIComponent(item.id)}/oauth/start`)
    window.location.assign(data.authorization_url)
  } catch (error) {
    message.error(error.response?.data?.detail || '无法启动 OAuth 授权')
  } finally {
    busyId.value = ''
  }
}

async function disconnect(item) {
  if (!window.confirm(`移除“${item.name}”在 UniEmployee 中保存的授权？这不会撤销 OAuth 服务商上的授权；对应员工将无法再调用该连接器。`)) return
  busyId.value = `${item.id}:disconnect`
  try {
    await api.delete(`/connectors/${encodeURIComponent(item.id)}/oauth`)
    message.success('本地授权已移除')
    await load()
  } catch (error) {
    message.error(error.response?.data?.detail || '移除本地授权失败')
  } finally {
    busyId.value = ''
  }
}

onMounted(async () => {
  callbackResult.value = String(route.query.oauth || '')
  await load()
  if (route.query.oauth) {
    const query = { ...route.query }
    delete query.oauth
    delete query.reason
    router.replace({ query })
  }
})
</script>

<style scoped>
.connector-page { max-width: 1080px; margin: 0 auto; padding: 8px 4px 32px; }
.page-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 22px; }
.page-heading h2 { margin: 0; color: #172033; font-size: 21px; font-weight: 650; }
.page-heading p { margin: 7px 0 0; color: #64748b; font-size: 13px; line-height: 1.7; }
.notice { margin: 0 0 18px; }
.connector-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }
.connector-card { border-radius: 12px; }
.card-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.connector-name { color: #172033; font-weight: 650; font-size: 15px; }
.connector-id { margin-top: 3px; color: #94a3b8; font: 11px ui-monospace, monospace; }
.description { min-height: 38px; margin: 14px 0 10px; color: #64748b; font-size: 13px; line-height: 1.6; }
.employee-line, .scope-line { margin-top: 7px; color: #64748b; font-size: 12px; line-height: 1.5; word-break: break-word; }
.card-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
.empty-help { color: #94a3b8; font-size: 12px; }
@media (max-width: 640px) { .connector-page { padding: 0 0 24px; } .page-heading { align-items: center; } }
</style>
