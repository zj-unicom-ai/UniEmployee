<!-- 安全护栏 · 工具调用护栏：统一配置工具级 allow/deny。 -->
<template>
  <div class="tools-page">
    <div class="intro-card">
      <div class="intro-title">工具能力策略</div>
      <div class="intro-sub">
        普通用户的员工只有在员工配置和本页策略同时允许时才能执行工具；deny 优先于 allow。
        管理员不受此策略限制，所有拒绝都会记录审计护栏日志。
      </div>
    </div>

    <div class="editor-card">
      <div class="editor-title">普通用户全局 allow/deny</div>
      <n-input
        v-model:value="toolAllowlist" type="textarea" :rows="3"
        placeholder="允许列表（可选，逗号分隔；支持 *，留空表示不额外限制）"
      />
      <n-input
        v-model:value="toolDenylist" type="textarea" :rows="3"
        placeholder="拒绝列表（逗号分隔；deny 优先，支持 *）"
        style="margin-top: 10px"
      />
      <div class="editor-hint">闭包工具（如 kb_search、ontology_*）也遵循此策略。</div>
    </div>

    <div class="editor-card">
      <div class="editor-title">MCP 工具策略</div>
      <n-space align="center">
        <n-switch
          :value="mcpDefaultDeny === '1'"
          @update:value="(v) => { mcpDefaultDeny = v ? '1' : '0' }"
        />
        <span>未绑定连接器来源的 MCP 工具默认拒绝；已绑定连接器自动放行</span>
      </n-space>
      <n-input
        v-model:value="mcpAllowlist" type="textarea" :rows="3"
        placeholder="直接注入 MCP 的允许列表（逗号分隔；已绑定连接器无需填写）"
        style="margin-top: 10px"
      />
    </div>

    <div class="editor-card">
      <div class="editor-title">仅管理员可调用的工具（兼容旧策略）</div>
      <n-input
        v-model:value="adminOnlyTools" type="textarea" :rows="5"
        placeholder="逗号分隔的工具名，如：ontology_save_entity, ontology_link_entities"
      />
      <div class="editor-hint">从下表点击工具名可快速加入；这里的 deny 规则优先于普通用户 allow。</div>
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
const toolAllowlist = ref('')
const savedToolAllowlist = ref('')
const toolDenylist = ref('')
const savedToolDenylist = ref('')
const mcpDefaultDeny = ref('1')
const savedMcpDefaultDeny = ref('1')
const mcpAllowlist = ref('')
const savedMcpAllowlist = ref('')
const tools = ref([])
const toolLogs = ref([])
const saving = ref(false)

const dirty = computed(() =>
  adminOnlyTools.value.trim() !== savedValue.value.trim() ||
  toolAllowlist.value.trim() !== savedToolAllowlist.value.trim() ||
  toolDenylist.value.trim() !== savedToolDenylist.value.trim() ||
  mcpDefaultDeny.value !== savedMcpDefaultDeny.value ||
  mcpAllowlist.value.trim() !== savedMcpAllowlist.value.trim())

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
  savedToolAllowlist.value = s.data.tool_allowlist || ''
  toolAllowlist.value = savedToolAllowlist.value
  savedToolDenylist.value = s.data.tool_denylist || ''
  toolDenylist.value = savedToolDenylist.value
  savedMcpDefaultDeny.value = s.data.mcp_default_deny ?? '1'
  mcpDefaultDeny.value = savedMcpDefaultDeny.value
  savedMcpAllowlist.value = s.data.mcp_allowlist || ''
  mcpAllowlist.value = savedMcpAllowlist.value
  tools.value = c.data.tools || []
  toolLogs.value = l.data.logs || []
}

async function save() {
  saving.value = true
  try {
    const { data } = await api.put('/admin/guard/settings', {
      admin_only_tools: adminOnlyTools.value.trim(),
      tool_allowlist: toolAllowlist.value.trim(),
      tool_denylist: toolDenylist.value.trim(),
      mcp_default_deny: mcpDefaultDeny.value,
      mcp_allowlist: mcpAllowlist.value.trim(),
    })
    if (data.error) { message.error(data.error); return }
    savedValue.value = data.settings.admin_only_tools || ''
    adminOnlyTools.value = savedValue.value
    savedToolAllowlist.value = data.settings.tool_allowlist || ''
    toolAllowlist.value = savedToolAllowlist.value
    savedToolDenylist.value = data.settings.tool_denylist || ''
    toolDenylist.value = savedToolDenylist.value
    savedMcpDefaultDeny.value = data.settings.mcp_default_deny ?? '1'
    mcpDefaultDeny.value = savedMcpDefaultDeny.value
    savedMcpAllowlist.value = data.settings.mcp_allowlist || ''
    mcpAllowlist.value = savedMcpAllowlist.value
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
