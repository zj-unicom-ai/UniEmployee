<!-- 系统设置 · 审计日志：管理员后台变更操作记录（员工/资源/用户/组织/护栏），
     支持按对象类型/动作筛选与分页，可展开查看变更前后快照。 -->
<template>
  <div class="audit-page">
    <div class="toolbar">
      <n-select v-model:value="objType" size="small" :options="objOptions" style="width: 160px"
                placeholder="对象类型（全部）" clearable @update:value="reload" />
      <n-select v-model:value="action" size="small" :options="actionOptions" style="width: 130px"
                placeholder="动作（全部）" clearable @update:value="reload" />
      <div class="flex-sp"></div>
      <span class="total">共 {{ total }} 条</span>
      <n-button size="small" @click="load">刷新</n-button>
    </div>

    <n-empty v-if="!loading && !logs.length" description="暂无审计记录" style="padding: 40px 0" />
    <n-spin v-else :show="loading">
      <div class="log-list">
        <div v-for="l in logs" :key="l.id" class="log-item">
          <div class="log-head" @click="toggle(l.id)">
            <span class="act" :class="l.action">{{ actionLabel[l.action] || l.action }}</span>
            <span class="obj">{{ objLabel(l) }}</span>
            <span class="actor">{{ l.actor_name || l.actor_id || '-' }}</span>
            <span class="time">{{ l.created_at }}</span>
            <span class="ip">{{ l.ip }}</span>
            <span class="chevron">{{ opened === l.id ? '▾' : '▸' }}</span>
          </div>
          <div v-if="opened === l.id" class="diff">
            <div v-if="beforeOf(l)" class="diff-block">
              <div class="diff-title">变更前</div>
              <pre>{{ beforeOf(l) }}</pre>
            </div>
            <div v-if="afterOf(l)" class="diff-block">
              <div class="diff-title">变更后</div>
              <pre>{{ afterOf(l) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </n-spin>

    <div class="pager">
      <n-pagination v-model:page="page" :page-size="pageSize" :item-count="total"
                    @update:page="load" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../../api.js'

defineOptions({ name: 'AuditLogsPage' })

const logs = ref([])
const total = ref(0)
const loading = ref(false)
const page = ref(1)
const pageSize = 50
const opened = ref(0)
const objType = ref(null)
const action = ref(null)

const objOptions = [
  { label: '员工', value: 'employee' },
  { label: '技能', value: 'skill' },
  { label: '工具', value: 'tool' },
  { label: '知识库', value: 'kb' },
  { label: 'SOP', value: 'sop' },
  { label: '连接器', value: 'connector' },
  { label: '部门', value: 'org' },
  { label: '用户', value: 'user' },
  { label: '用户密码', value: 'user_password' },
  { label: '员工分配', value: 'assignment' },
  { label: '护栏配置', value: 'guard_settings' },
  { label: '敏感词', value: 'sensitive_word' },
  { label: '登录/认证', value: 'auth' },
]
const actionOptions = [
  { label: '新增', value: 'create' },
  { label: '修改', value: 'update' },
  { label: '删除', value: 'delete' },
  { label: '登录成功', value: 'login' },
  { label: '登录失败', value: 'login_failed' },
]
const actionLabel = { create: '新增', update: '修改', delete: '删除',
                      login: '登录成功', login_failed: '登录失败' }
const objNameMap = Object.fromEntries(objOptions.map(o => [o.value, o.label]))

function objLabel(l) {
  return `${objNameMap[l.obj_type] || l.obj_type}${l.obj_id ? ' · ' + l.obj_id : ''}`
}
function pretty(s) {
  if (!s) return ''
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}
const beforeOf = l => pretty(l.before)
const afterOf = l => pretty(l.after)

function toggle(id) { opened.value = opened.value === id ? 0 : id }

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/audit/logs', {
      params: {
        limit: pageSize, offset: (page.value - 1) * pageSize,
        obj_type: objType.value || '', action: action.value || '',
      },
    })
    logs.value = data.logs || []
    total.value = data.total || 0
    opened.value = 0
  } finally {
    loading.value = false
  }
}
function reload() { page.value = 1; load() }

onMounted(load)
</script>

<style scoped>
.audit-page { width: 100%; }
.toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.flex-sp { flex: 1; }
.total { font-size: 12px; color: #94a3b8; }
.log-list { display: flex; flex-direction: column; gap: 6px; }
.log-item { background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 0 14px; }
.log-head { display: flex; align-items: center; gap: 12px; font-size: 13px; padding: 9px 0; cursor: pointer; }
.act { font-size: 11px; border-radius: 8px; padding: 1px 8px; flex-shrink: 0; }
.act.create { background: #ecfdf5; color: #047857; }
.act.update { background: #eff6ff; color: #1d4ed8; }
.act.delete { background: #fef2f2; color: #b91c1c; }
.obj { color: #0f172a; font-weight: 500; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.actor { color: #475569; flex-shrink: 0; }
.time { color: #94a3b8; font-size: 12px; flex-shrink: 0; }
.ip { color: #cbd5e1; font-size: 11px; flex-shrink: 0; }
.chevron { color: #cbd5e1; flex-shrink: 0; }
.diff { border-top: 1px dashed #e2e8f0; padding: 10px 0 14px; display: flex; gap: 16px; flex-wrap: wrap; }
.diff-block { flex: 1; min-width: 280px; }
.diff-title { font-size: 12px; font-weight: 600; color: #64748b; margin-bottom: 6px; }
.diff-block pre { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; font-size: 12px; max-height: 320px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }
</style>
