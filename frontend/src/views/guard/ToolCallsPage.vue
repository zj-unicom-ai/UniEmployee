<!-- 安全护栏 · 工具调用护栏：仅管理员可调用的工具白名单（逗号分隔），
     普通用户的员工调用白名单内工具会被运行时拒绝并记录。 -->
<template>
  <div class="tools-page">
    <div class="intro-card">
      <div class="intro-title">工具白名单机制</div>
      <div class="intro-sub">
        列在下方白名单中的工具，只有管理员账号的数字员工可以真实执行；
        普通用户的员工即使声明了这些工具，运行时调用也会被安全护栏拒绝（返回权限错误并记录日志），真实逻辑不执行。
      </div>
    </div>

    <div class="editor-card">
      <div class="editor-title">仅管理员可调用的工具</div>
      <n-input
        v-model:value="adminOnlyTools" type="textarea" :rows="5"
        placeholder="逗号分隔的工具名，如：ontology_save_entity, ontology_link_entities"
      />
      <div class="editor-hint">从下表点击工具名可快速加入白名单；留空表示不限制任何工具。</div>
      <div class="editor-actions">
        <n-button type="primary" size="small" :loading="saving" :disabled="!dirty" @click="save">
          保存{{ dirty ? '（有未保存修改）' : '' }}
        </n-button>
        <n-button v-if="dirty" size="small" quaternary @click="load">还原</n-button>
      </div>
    </div>

    <div class="catalog-card">
      <div class="editor-title">平台全部工具</div>
      <n-empty v-if="!tools.length" description="加载中或无工具" style="padding: 24px 0" />
      <div v-else class="tool-grid">
        <div v-for="t in tools" :key="t.name" class="tool-item" :class="{ on: inList(t.name) }" @click="toggleTool(t.name)">
          <div class="tool-name">
            {{ t.name }}
            <span v-if="inList(t.name)" class="on-tag">白名单内</span>
            <span v-if="t.needs_approval" class="appr-tag">需审批</span>
          </div>
          <div class="tool-desc">{{ t.description || '无描述' }}</div>
        </div>
      </div>
    </div>

    <div class="logs-section">
      <div class="editor-title">最近越权调用记录</div>
      <n-empty v-if="!toolLogs.length" description="暂无记录" style="padding: 24px 0" />
      <div v-else class="log-list">
        <div v-for="l in toolLogs" :key="l.id" class="log-item">
          <span class="log-type denied">越权拦截</span>
          <span class="log-detail">{{ l.detail }}</span>
          <span class="log-time">{{ l.created_at }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'ToolCallsPage' })

const message = useMessage()
const adminOnlyTools = ref('')
const savedValue = ref('')
const tools = ref([])
const toolLogs = ref([])
const saving = ref(false)

const dirty = computed(() => adminOnlyTools.value.trim() !== savedValue.value.trim())

function listSet() {
  return new Set(adminOnlyTools.value.split(',').map(x => x.trim()).filter(Boolean))
}
function inList(name) { return listSet().has(name) }

function toggleTool(name) {
  const s = listSet()
  if (s.has(name)) s.delete(name)
  else s.add(name)
  adminOnlyTools.value = [...s].join(', ')
}

async function load() {
  const [s, c, l] = await Promise.all([
    api.get('/admin/guard/settings'),
    api.get('/admin/catalog'),
    api.get('/admin/guard/logs', { params: { limit: 50, event_type: 'tool_denied' } }),
  ])
  savedValue.value = s.data.admin_only_tools || ''
  adminOnlyTools.value = savedValue.value
  tools.value = c.data.tools || []
  toolLogs.value = l.data.logs || []
}

async function save() {
  saving.value = true
  try {
    const { data } = await api.put('/admin/guard/settings', {
      admin_only_tools: adminOnlyTools.value.trim(),
    })
    if (data.error) { message.error(data.error); return }
    savedValue.value = data.settings.admin_only_tools || ''
    adminOnlyTools.value = savedValue.value
    message.success('已保存，各用户下次对话生效')
  } catch (e) {
    message.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.tools-page { width: 100%; display: flex; flex-direction: column; gap: 16px; }
.intro-card, .editor-card, .catalog-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 16px 18px; }
.intro-title, .editor-title { font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 6px; }
.intro-sub { font-size: 12px; color: #64748b; line-height: 1.7; }
.editor-card :deep(textarea) { font-family: ui-monospace, monospace; font-size: 13px; }
.editor-hint { font-size: 12px; color: #94a3b8; margin-top: 6px; }
.editor-actions { margin-top: 12px; display: flex; gap: 8px; }
.tool-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; margin-top: 10px; }
.tool-item { border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; cursor: pointer; transition: all 0.15s; }
.tool-item:hover { border-color: #93c5fd; }
.tool-item.on { background: #fef2f2; border-color: #fca5a5; }
.tool-name { font-size: 13px; font-weight: 500; color: #0f172a; font-family: ui-monospace, monospace; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.on-tag { font-size: 10px; background: #fef2f2; color: #b91c1c; border-radius: 8px; padding: 1px 7px; font-family: inherit; }
.appr-tag { font-size: 10px; background: #fffbeb; color: #b45309; border-radius: 8px; padding: 1px 7px; font-family: inherit; }
.tool-desc { font-size: 12px; color: #64748b; margin-top: 4px; line-height: 1.5; }
.logs-section { }
.log-list { display: flex; flex-direction: column; gap: 6px; }
.log-item { display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 14px; font-size: 12px; }
.log-type.denied { background: #fef2f2; color: #b91c1c; border-radius: 8px; padding: 1px 8px; font-size: 11px; flex-shrink: 0; }
.log-detail { color: #475569; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-time { color: #cbd5e1; flex-shrink: 0; }
</style>
