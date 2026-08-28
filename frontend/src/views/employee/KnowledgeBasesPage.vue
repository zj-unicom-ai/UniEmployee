<!-- 员工详情 · 知识库选择页（差异化展示）：RAGFlow 数据集卡片（文档数 / dataset id /
     描述），点卡片切换选中，独立保存。 -->
<template>
  <div class="kb-page">
    <div class="page-head">
      <div>
        <div class="page-title">知识库 RAGFlow Datasets<span class="count">已选 {{ selectedSet.size }} / {{ items.length }}</span></div>
        <div class="page-hint">勾选后该员工的 kb_search 只检索所选数据集；不勾选时按 RAGFLOW_DATASET_IDS（或全部数据集）检索。数据集在 RAGFlow 侧维护。</div>
      </div>
      <n-input v-model:value="keyword" size="small" clearable placeholder="搜索…" style="width: 180px" />
    </div>

    <div v-if="loading" class="page-empty">加载中…</div>
    <div v-else-if="!filtered.length" class="page-empty">{{ keyword ? '无匹配项' : '暂无可选数据集（检查 RAGFlow 连接）' }}</div>
    <div v-else class="kb-cards">
      <div
        v-for="it in filtered" :key="it.id"
        class="kb-card" :class="{ on: selectedSet.has(it.id) }"
        @click="toggle(it.id)"
      >
        <div class="kb-check">{{ selectedSet.has(it.id) ? '✓' : '' }}</div>
        <div class="kb-body">
          <div class="kb-name">{{ it.name }}</div>
          <div class="kb-desc">{{ it.description || '无描述' }}</div>
          <div class="kb-meta">
            <span class="doc-count">{{ it.document_count != null ? it.document_count + ' 文档' : '文档数未知' }}</span>
            <span class="dataset-id">{{ it.ragflow_dataset_id || it.id }}</span>
          </div>
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

defineOptions({ name: 'KnowledgeBasesPage' })

const props = defineProps({ employee: Object })
const emit = defineEmits(['changed'])

const message = useMessage()
const keyword = ref('')
const loading = ref(false)
const saving = ref(false)
const items = ref([])
const selectedSet = ref(new Set())

const initialIds = computed(() => new Set(props.employee?.kbs || []))
const dirty = computed(() =>
  selectedSet.value.size !== initialIds.value.size ||
  [...selectedSet.value].some(id => !initialIds.value.has(id)))

watch(() => props.employee, () => reset(), { immediate: true })
function reset() { selectedSet.value = new Set(props.employee?.kbs || []) }

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return items.value
  return items.value.filter(it =>
    (it.name || '').toLowerCase().includes(kw) ||
    (it.description || '').toLowerCase().includes(kw) ||
    (it.ragflow_dataset_id || '').includes(kw))
})

function toggle(id) {
  const s = new Set(selectedSet.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedSet.value = s
}

async function load() {
  loading.value = true
  try {
    const [rfRes, catRes] = await Promise.all([
      api.get('/admin/ragflow/datasets').catch(() => ({ data: { datasets: [] } })),
      api.get('/admin/catalog'),
    ])
    const datasets = rfRes.data?.datasets || []
    if (datasets.length) {
      items.value = datasets.map(d => ({
        id: d.id, name: d.name || d.id, description: d.description || '',
        ragflow_dataset_id: d.id, document_count: d.document_count,
      }))
    } else {
      // RAGFlow 不可达时回退到 catalog 已登记的知识库
      items.value = (catRes.data?.knowledge_bases || [])
        .filter(kb => kb.ragflow_dataset_id)
        .map(kb => ({ ...kb, document_count: null }))
    }
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const { data } = await api.put(`/admin/employees/${props.employee.id}`, {
      kbs: [...selectedSet.value],
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
.kb-page { max-width: 900px; }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.page-title { font-size: 14px; font-weight: 600; color: #334155; }
.count { font-size: 12px; font-weight: 400; color: #94a3b8; margin-left: 10px; }
.page-hint { font-size: 12px; color: #94a3b8; margin-top: 4px; line-height: 1.6; max-width: 560px; }
.page-empty { font-size: 13px; color: #94a3b8; padding: 32px 0; text-align: center; background: #fafbfc; border-radius: 8px; }
.kb-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.kb-card { position: relative; display: flex; gap: 10px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; cursor: pointer; transition: all 0.15s; }
.kb-card:hover { border-color: #93c5fd; }
.kb-card.on { border-color: #3b82f6; background: #eff6ff; }
.kb-check { width: 18px; height: 18px; border-radius: 50%; border: 1px solid #cbd5e1; color: #fff; font-size: 11px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }
.kb-card.on .kb-check { background: #3b82f6; border-color: #3b82f6; }
.kb-body { flex: 1; min-width: 0; }
.kb-name { font-size: 13px; font-weight: 600; color: #0f172a; }
.kb-desc { font-size: 12px; color: #64748b; margin-top: 4px; line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 36px; }
.kb-meta { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.doc-count { font-size: 11px; color: #0e7490; background: #ecfeff; border-radius: 8px; padding: 1px 8px; }
.dataset-id { font-size: 10px; color: #94a3b8; font-family: ui-monospace, monospace; }
.page-foot { margin-top: 14px; display: flex; gap: 8px; }
</style>
