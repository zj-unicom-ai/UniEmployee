<!-- 员工详情 · 连接器选择页（差异化展示）：MCP 连接器卡片（transport 类型 / 命令或 URL /
     参数预览），点卡片切换选中，独立保存。连接器的增删改在「资源中心」进行。 -->
<template>
  <div class="conn-page">
    <div class="page-head">
      <div>
        <div class="page-title">连接器 Connectors（MCP）<span class="count">已选 {{ selectedSet.size }} / {{ items.length }}</span></div>
        <div class="page-hint">勾选后该员工编译时接入对应 MCP server 的工具；连接器的创建与配置在「资源中心」进行。</div>
      </div>
      <n-input v-model:value="keyword" size="small" clearable placeholder="搜索…" style="width: 180px" />
    </div>

    <div v-if="loading" class="page-empty">加载中…</div>
    <div v-else-if="!filtered.length" class="page-empty">{{ keyword ? '无匹配项' : '暂无可选连接器' }}</div>
    <div v-else class="conn-cards">
      <div
        v-for="it in filtered" :key="it.id"
        class="conn-card" :class="{ on: selectedSet.has(it.id) }"
        @click="toggle(it.id)"
      >
        <div class="conn-check">{{ selectedSet.has(it.id) ? '✓' : '' }}</div>
        <div class="conn-body">
          <div class="conn-name">
            {{ it.name }}
            <span class="transport-tag" :class="it.transport">{{ transportLabel(it) }}</span>
          </div>
          <div class="conn-desc">{{ it.description || '无描述' }}</div>
          <div v-if="it.endpoint" class="conn-endpoint" :title="it.endpoint">{{ it.endpoint }}</div>
          <div v-if="it.toolCount != null" class="conn-tools">提供 {{ it.toolCount }} 个工具</div>
        </div>
      </div>
    </div>

    <div class="page-foot">
      <n-button type="primary" size="small" :loading="saving" :disabled="!dirty" @click="save">
        保存{{ dirty ? '（有未保存修改）' : '' }}
      </n-button>
      <n-button v-if="dirty" size="small" quaternary @click="reset">还原</n-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'ConnectorsPage' })

const props = defineProps({ employee: Object })
const emit = defineEmits(['changed'])

const message = useMessage()
const keyword = ref('')
const loading = ref(false)
const saving = ref(false)
const items = ref([])
const selectedSet = ref(new Set())

const initialIds = computed(() => new Set(props.employee?.connectors || []))
const dirty = computed(() =>
  selectedSet.value.size !== initialIds.value.size ||
  [...selectedSet.value].some(id => !initialIds.value.has(id)))

watch(() => props.employee, () => reset(), { immediate: true })
function reset() { selectedSet.value = new Set(props.employee?.connectors || []) }

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(it =>
    (it.name || '').toLowerCase().includes(kw) ||
    (it.description || '').toLowerCase().includes(kw) ||
    (it.endpoint || '').toLowerCase().includes(kw))
})

function toggle(id) {
  const s = new Set(selectedSet.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedSet.value = s
}

function transportLabel(it) {
  return { stdio: 'stdio', http: 'HTTP', streamable: 'HTTP' }[it.transport] || it.transport
}

// 从连接器 config JSON 解析 transport 与可读的接入端信息
function parseConfig(c) {
  const cfg = c.config || {}
  if (cfg.url) {
    return { transport: cfg.transport || 'http', endpoint: cfg.url }
  }
  if (cfg.command) {
    const args = (cfg.args || []).join(' ')
    const cwd = cfg.cwd ? ` (cwd: ${cfg.cwd})` : ''
    return { transport: 'stdio', endpoint: `${cfg.command} ${args}${cwd}`.trim() }
  }
  return { transport: 'unknown', endpoint: '' }
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/catalog')
    const cons = data.connectors || []
    // 并发拉取各连接器详情（连接器数量少）；失败的单个降级为仅名称描述
    const detailed = await Promise.all(cons.map(async (c) => {
      try {
        const r = await api.get(`/admin/connectors/${c.id}`)
        if (r.data?.error) return { ...c, transport: 'unknown', endpoint: '' }
        return { ...c, ...parseConfig(r.data) }
      } catch {
        return { ...c, transport: 'unknown', endpoint: '' }
      }
    }))
    items.value = detailed
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const { data } = await api.put(`/admin/employees/${props.employee.id}`, {
      connectors: [...selectedSet.value],
    })
    if (data.error) { message.error('保存失败：' + data.error); return }
    message.success('已保存')
    emit('changed')
  } catch (e) {
    message.error('保存出错：' + e.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.conn-page { max-width: 900px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.page-title { font-size: 14px; font-weight: 600; color: #334155; }
.count { font-size: 12px; font-weight: 400; color: #94a3b8; margin-left: 10px; }
.page-hint { font-size: 12px; color: #94a3b8; margin-top: 4px; line-height: 1.6; max-width: 560px; }
.page-empty { font-size: 13px; color: #94a3b8; padding: 32px 0; text-align: center; background: #fafbfc; border-radius: 8px; }
.conn-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
.conn-card { display: flex; gap: 10px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; cursor: pointer; transition: all 0.15s; }
.conn-card:hover { border-color: #93c5fd; }
.conn-card.on { border-color: #3b82f6; background: #eff6ff; }
.conn-check { width: 18px; height: 18px; border-radius: 50%; border: 1px solid #cbd5e1; color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }
.conn-card.on .conn-check { background: #3b82f6; border-color: #3b82f6; }
.conn-body { flex: 1; min-width: 0; }
.conn-name { font-size: 13px; font-weight: 600; color: #0f172a; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.transport-tag { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: #f5f3ff; color: #7c3aed; font-weight: 400; }
.transport-tag.stdio { background: #f1f5f9; color: #475569; }
.conn-desc { font-size: 12px; color: #64748b; margin-top: 4px; line-height: 1.5; }
.conn-endpoint { font-size: 11px; color: #94a3b8; font-family: ui-monospace, monospace; margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conn-tools { font-size: 11px; color: #0e7490; margin-top: 4px; }
.page-foot { margin-top: 14px; display: flex; gap: 8px; }
</style>
