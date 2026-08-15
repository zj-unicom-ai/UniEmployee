<!-- 员工管理：左侧员工列表 + 右侧编辑表单（名称/模型/后端/人设/技能/工具/SOP/连接器） -->
<template>
  <div class="admin-layout">
    <!-- 左侧：员工列表 -->
    <div class="emp-list-panel">
      <div class="list-head">
        <span class="list-title">员工</span>
        <n-button size="tiny" type="primary" @click="newEmp">+ 新建</n-button>
      </div>
      <div class="list-body">
        <div v-if="!employees.length" class="list-empty">暂无员工，点击「+ 新建」</div>
        <div
          v-for="e in employees" :key="e.id"
          class="emp-item"
          :class="{ active: current?.id === e.id }"
          @click="loadEmp(e.id)"
        >
          <div class="emp-name">{{ e.name }}</div>
          <div class="emp-role">{{ e.role || '' }} · {{ e.backend }}</div>
        </div>
      </div>
    </div>

    <!-- 右侧：表单 -->
    <div class="form-panel">
      <n-form label-placement="left" :label-width="100" size="small">
        <n-form-item label="员工 ID">
          <n-input :value="current?.id || ''" placeholder="保存后自动生成" readonly />
        </n-form-item>
        <n-form-item label="名称 *" required>
          <n-input v-model:value="form.name" placeholder="如：小苏" />
        </n-form-item>
        <n-form-item label="角色">
          <n-input v-model:value="form.role" placeholder="如：售前售后客服" />
        </n-form-item>
        <n-form-item label="模型">
          <n-input v-model:value="form.model" placeholder="openai:deepseek-v4-flash" />
        </n-form-item>
        <n-form-item label="运行后端">
          <n-select v-model:value="form.backend" :options="backendOptions" />
        </n-form-item>
        <n-form-item label="人设">
          <n-input v-model:value="form.persona" type="textarea" :rows="6" placeholder="描述该员工的身份、语气与工作原则…" />
        </n-form-item>
      </n-form>

      <!-- 多选组 -->
      <div class="groups">
        <div v-for="g in groupDefs" :key="g.key" class="group">
          <div class="group-title">{{ g.label }}</div>
          <div class="chips">
            <span v-if="!groupItems(g).length" class="hint-text">（暂无可选项）</span>
            <label
              v-for="it in groupItems(g)" :key="it.id"
              class="chip"
              :class="{ on: selected[g.key].has(it.id) }"
            >
              <input type="checkbox" :checked="selected[g.key].has(it.id)" @change="toggleChip(g.key, it.id, $event)" />
              <span>{{ it.name }}</span>
              <span v-if="it.description || g.key === 'knowledge_bases'" class="chip-desc">
                <template v-if="g.key === 'knowledge_bases'">{{ it.ragflow_dataset_id || it.id }}{{ it.document_count != null ? ' · ' + it.document_count + ' 文档' : '' }}</template>
                <template v-else>{{ it.description }}</template>
              </span>
            </label>
          </div>
        </div>
        <div class="hint-text">提示：勾选「start_refund」工具会自动启用人工审批；知识库直接绑定 RAGFlow 数据集，勾选后该员工的 kb_search 只检索所选数据集，不勾选时按 RAGFLOW_DATASET_IDS（或全部数据集）检索。</div>
      </div>

      <div class="actions">
        <n-button type="primary" @click="saveEmp">保存</n-button>
        <n-button v-if="current" type="error" ghost @click="delEmp">删除该员工</n-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import api from '../api.js'

defineOptions({ name: 'AdminView' })

const dialog = useDialog()
const message = useMessage()

const backendOptions = [
  { label: 'state（默认，标准工具后端）', value: 'state' },
  { label: 'local_shell（数据分析沙箱）', value: 'local_shell' },
]
const groupDefs = [
  { key: 'skills', label: '技能 Skills' },
  { key: 'tools', label: '工具 Tools' },
  { key: 'knowledge_bases', label: '知识库 RAGFlow Datasets' },
  { key: 'sops', label: 'SOP 流程文档' },
  { key: 'connectors', label: '连接器 Connectors（MCP）' },
]

const catalog = ref({})
const ragflowDatasets = ref([])
const employees = ref([])
const current = ref(null)
const form = reactive({ name: '', role: '', model: 'openai:deepseek-v4-flash', backend: 'state', persona: '' })
const selected = reactive({
  skills: new Set(), tools: new Set(), knowledge_bases: new Set(),
  sops: new Set(), connectors: new Set(),
})

function toggleChip(key, id, e) {
  if (e.target.checked) selected[key].add(id)
  else selected[key].delete(id)
}

const kbOptions = computed(() => {
  const datasets = ragflowDatasets.value || []
  if (datasets.length) {
    return datasets.map(d => ({
      id: d.id,
      name: d.name || d.id,
      description: d.description || '',
      ragflow_dataset_id: d.id,
      document_count: d.document_count,
    }))
  }
  return (catalog.value.knowledge_bases || []).filter(kb => kb.ragflow_dataset_id)
})

function groupItems(g) {
  return g.key === 'knowledge_bases' ? kbOptions.value : (catalog.value[g.key] || [])
}

function clearForm() {
  current.value = null
  form.name = ''; form.role = ''; form.model = 'openai:deepseek-v4-flash'; form.backend = 'state'; form.persona = ''
  Object.keys(selected).forEach(k => selected[k].clear())
}

function loadEmp(id) {
  const e = employees.value.find(x => x.id === id)
  if (!e) return
  current.value = e
  form.name = e.name || ''; form.role = e.role || ''; form.model = e.model || ''
  form.backend = e.backend || 'state'; form.persona = e.persona || ''
  selected.skills = new Set(e.skills || [])
  selected.tools = new Set(e.tools || [])
  const kbIds = new Set(kbOptions.value.map(k => k.id))
  selected.knowledge_bases = new Set((e.kbs || []).filter(id => kbIds.has(id)))
  selected.sops = new Set(e.sops || [])
  selected.connectors = new Set(e.connectors || [])
}

function newEmp() { clearForm() }

async function saveEmp() {
  if (!form.name) { message.warning('请填写名称'); return }
  const data = {
    name: form.name.trim(), role: form.role.trim(), model: form.model.trim(),
    backend: form.backend, persona: form.persona,
    skills: [...selected.skills], tools: [...selected.tools], kbs: [...selected.knowledge_bases],
    sops: [...selected.sops], connectors: [...selected.connectors],
  }
  try {
    if (current.value) {
      const { data: d } = await api.put(`/admin/employees/${current.value.id}`, data)
      if (d.error) { message.error('保存失败：' + d.error); return }
      message.success('已更新')
    } else {
      const { data: d } = await api.post('/admin/employees', data)
      if (d.error) { message.error('保存失败：' + d.error); return }
      message.success('已创建：' + d.id)
    }
    await reload()
    if (!current.value && employees.value.length) loadEmp(employees.value[employees.value.length - 1].id)
  } catch (e) { message.error('保存出错：' + e.message) }
}

function delEmp() {
  if (!current.value) return
  dialog.warning({
    title: '删除员工',
    content: `确认删除员工「${current.value.name}」？该操作不可恢复。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.delete(`/admin/employees/${current.value.id}`)
        message.success('已删除')
        await reload()
        clearForm()
      } catch (e) { message.error('删除出错：' + e.message) }
    },
  })
}

async function reload() {
  try {
    const [catRes, empRes, rfRes] = await Promise.all([
      api.get('/admin/catalog'),
      api.get('/admin/employees'),
      api.get('/admin/ragflow/datasets').catch(() => ({ data: { datasets: [] } })),
    ])
    catalog.value = catRes.data
    ragflowDatasets.value = rfRes.data?.datasets || []
    employees.value = (empRes.data || []).filter(x => x && !x.error)
    if (current.value) {
      const found = employees.value.find(x => x.id === current.value.id)
      if (found) loadEmp(found.id)
    }
  } catch {}
}

onMounted(async () => {
  await reload()
  if (!current.value && employees.value.length) loadEmp(employees.value[0].id)
})
</script>

<style scoped>
.admin-layout { display: flex; height: 100%; }
.emp-list-panel { width: 248px; border-right: 1px solid #e2e8f0; display: flex; flex-direction: column; background: #fff; }
.list-head { padding: 12px 14px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #f1f5f9; }
.list-title { font-size: 13px; font-weight: 600; color: #334155; }
.list-body { flex: 1; overflow-y: auto; padding: 8px; }
.list-empty { font-size: 12px; color: #94a3b8; padding: 18px 10px; text-align: center; }
.emp-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px; border: 1px solid transparent; transition: background 0.15s; }
.emp-item:hover { background: #f1f5f9; }
.emp-item.active { background: #eff6ff; border-color: #3b82f6; }
.emp-name { font-size: 14px; font-weight: 500; color: #0f172a; }
.emp-role { font-size: 11px; color: #64748b; margin-top: 2px; }

.form-panel { flex: 1; overflow-y: auto; padding: 24px 28px; }
.groups { margin-top: 20px; border-top: 1px solid #e2e8f0; padding-top: 18px; max-width: 860px; }
.group { margin-bottom: 18px; }
.group-title { font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 10px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; padding: 6px 12px; border: 1px solid #cbd5e1; border-radius: 20px; background: #fff; cursor: pointer; user-select: none; transition: all 0.15s; }
.chip input { display: none; }
.chip.on { background: #eff6ff; border-color: #3b82f6; color: #2563eb; }
.chip-desc { color: #94a3b8; font-size: 11px; }
.hint-text { font-size: 12px; color: #94a3b8; margin-top: 8px; line-height: 1.6; }
.actions { margin-top: 24px; display: flex; gap: 10px; max-width: 860px; }
</style>
