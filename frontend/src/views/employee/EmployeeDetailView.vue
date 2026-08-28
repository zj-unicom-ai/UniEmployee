<!-- 员工详情页：头部信息条 + 配置导航（各配置类型为独立子路由页，可直达/收藏）。
     子页通过 router-view 渲染，保存后 emit changed 触发本页刷新。 -->
<template>
  <div class="emp-detail">
    <div v-if="loading" class="detail-empty">加载中…</div>
    <div v-else-if="!emp" class="detail-empty">员工不存在，<a @click="$router.push('/app/admin')">返回列表</a></div>
    <template v-else>
      <div class="detail-head">
        <n-button text size="small" @click="$router.push('/app/admin')">← 返回列表</n-button>
        <div class="head-main">
          <div class="avatar">{{ (emp.name || '?').slice(0, 1) }}</div>
          <div class="head-info">
            <div class="name">
              {{ emp.name }}
              <span class="emp-id">{{ emp.id }}</span>
            </div>
            <div class="meta">{{ emp.role || '未设置角色' }} · {{ emp.model || '未设置模型' }} · {{ emp.backend || 'state' }}</div>
          </div>
        </div>
      </div>
      <n-tabs :value="activeTab" type="line" size="small" @update:value="goTab">
        <n-tab v-for="t in tabs" :key="t.key" :name="t.key" :tab="tabLabel(t)" />
      </n-tabs>
      <div class="tab-body">
        <router-view :employee="emp" @changed="reload" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'EmployeeDetailView' })

const route = useRoute()
const router = useRouter()
const message = useMessage()

const emp = ref(null)
const loading = ref(false)

const tabs = [
  { key: '', label: '基础信息', countKey: null },
  { key: 'skills', label: '技能', countKey: 'skills' },
  { key: 'tools', label: '工具', countKey: 'tools' },
  { key: 'knowledge-bases', label: '知识库', countKey: 'kbs' },
  { key: 'sops', label: 'SOP', countKey: 'sops' },
  { key: 'connectors', label: '连接器', countKey: 'connectors' },
]

const activeTab = computed(() => {
  // 子路径 '' → ''，'skills' → 'skills'，'knowledge-bases' → 'knowledge-bases'
  const rest = route.path.split('/app/admin/employee/')[1] || ''
  const idLen = (route.params.id || '').length
  const sub = rest.slice(idLen + 1)
  return sub
})

function tabLabel(t) {
  if (!t.countKey) return t.label
  const n = (emp.value?.[t.countKey] || []).length
  return `${t.label} ${n}`
}

function goTab(key) {
  const base = `/app/admin/employee/${route.params.id}`
  router.push(key ? `${base}/${key}` : base)
}

async function reload() {
  loading.value = true
  try {
    const { data } = await api.get(`/admin/employees/${route.params.id}`)
    emp.value = data?.error ? null : data
  } catch (e) {
    message.error('加载员工失败：' + e.message)
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, reload, { immediate: true })
</script>

<style scoped>
.emp-detail { height: 100%; display: flex; flex-direction: column; padding: 18px 28px 0; }
.detail-empty { color: #94a3b8; font-size: 13px; padding: 60px 0; text-align: center; }
.detail-empty a { color: #3b82f6; cursor: pointer; }
.detail-head { margin-bottom: 12px; }
.head-main { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.avatar { width: 46px; height: 46px; border-radius: 50%; background: #eff6ff; color: #2563eb; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 600; flex-shrink: 0; }
.head-info { min-width: 0; }
.name { font-size: 17px; font-weight: 600; color: #0f172a; display: flex; align-items: center; gap: 8px; }
.emp-id { font-size: 11px; color: #94a3b8; font-family: ui-monospace, monospace; font-weight: 400; }
.meta { font-size: 12px; color: #64748b; margin-top: 3px; }
.tab-body { flex: 1; overflow-y: auto; padding: 16px 2px 24px; }
</style>
