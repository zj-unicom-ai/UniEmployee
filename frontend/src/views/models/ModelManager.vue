<!-- 系统设置 · 模型管理：独立的卡片式 CRUD 页面（非 tab）。
     参照 Aix-DB llm-config.vue 适配为 UniEmployee JS 风格。 -->
<template>
  <div class="model-manager">
    <div class="header">
      <h2>模型管理</h2>
      <div class="actions">
        <n-input v-model:value="keyword" placeholder="搜索模型名称" style="width: 220px" clearable
                 @keyup.enter="fetchData" @clear="fetchData">
          <template #prefix>
            <span class="search-icon">⌕</span>
          </template>
        </n-input>
        <n-button secondary @click="fetchData">刷新</n-button>
        <n-button type="primary" @click="handleAdd">+ 添加模型</n-button>
      </div>
    </div>

    <n-spin :show="loading">
      <div v-if="modelList.length > 0" class="grid">
        <div v-for="item in modelList" :key="item.id" class="model-card">
          <div class="card-body">
            <div class="card-top">
              <div class="icon-wrapper">AI</div>
              <div class="info">
                <div class="name-row">
                  <span class="name" :title="item.name">{{ item.name }}</span>
                  <n-tag v-if="item.default_model" type="success" size="small" round>默认</n-tag>
                </div>
                <span class="supplier">{{ supplierName(item.supplier) }}</span>
              </div>
            </div>
            <div class="card-meta">
              <div class="meta-item">
                <span class="label">类型</span>
                <span class="value">{{ modelTypeName(item.model_type) }}</span>
              </div>
              <div class="meta-item">
                <span class="label">模型</span>
                <span class="value" :title="item.base_model">{{ item.base_model }}</span>
              </div>
              <div class="meta-item">
                <span class="label">域名</span>
                <span class="value" :title="item.api_domain">{{ item.api_domain }}</span>
              </div>
            </div>
          </div>
          <div class="card-actions">
            <div class="left-actions">
              <n-button v-if="!item.default_model && item.model_type === 1" text size="small" type="primary"
                        @click="handleSetDefault(item)">设为默认</n-button>
            </div>
            <div class="right-actions">
              <n-button text size="small" @click="handleEdit(item)">编辑</n-button>
              <n-button text size="small" type="error" @click="handleDelete(item)">删除</n-button>
            </div>
          </div>
        </div>
      </div>
      <div v-else class="empty">
        <n-empty description="暂无模型配置">
          <template #extra>
            <n-button type="primary" @click="handleAdd">添加模型</n-button>
          </template>
        </n-empty>
      </div>
    </n-spin>

    <ModelForm v-model:show="showForm" :model-id="currentModelId" @success="fetchData" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useDialog, useMessage } from 'naive-ui'
import api from '../../api.js'
import ModelForm from '../../components/models/ModelForm.vue'

defineOptions({ name: 'ModelManager' })

const dialog = useDialog()
const message = useMessage()

const loading = ref(false)
const modelList = ref([])
const keyword = ref('')
const showForm = ref(false)
const currentModelId = ref(null)

const supplierMap = {
  1: 'OpenAI', 2: 'Azure', 3: 'Ollama', 4: 'vLLM',
  5: 'DeepSeek', 6: 'Qwen', 7: 'Moonshot', 8: 'ZhipuAI',
  9: 'Other', 10: 'MiniMax',
}
const supplierName = (s) => supplierMap[s] || 'Unknown'
const modelTypeName = (t) => ({ 1: '大语言模型', 2: 'Embedding', 3: 'Rerank' }[t] || 'Unknown')

async function fetchData() {
  loading.value = true
  try {
    const { data } = await api.get('/admin/ai-models', { params: { keyword: keyword.value } })
    modelList.value = Array.isArray(data) ? data : []
  } catch (e) {
    message.error('获取模型列表失败')
  } finally {
    loading.value = false
  }
}

function handleAdd() {
  currentModelId.value = null
  showForm.value = true
}

function handleEdit(item) {
  currentModelId.value = item.id
  showForm.value = true
}

function handleDelete(item) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除模型「${item.name}」吗？`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      try {
        await api.delete(`/admin/ai-models/${item.id}`)
        message.success('删除成功')
        fetchData()
      } catch (e) {
        message.error('删除失败')
      }
    },
  })
}

async function handleSetDefault(item) {
  try {
    await api.put(`/admin/ai-models/default/${item.id}`)
    message.success('设置成功')
    fetchData()
  } catch (e) {
    message.error('设置失败')
  }
}

onMounted(fetchData)
</script>

<style scoped>
.model-manager { padding: 18px 28px 24px; height: 100%; display: flex; flex-direction: column; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
.header h2 { margin: 0; font-size: 18px; font-weight: 600; color: #0f172a; }
.actions { display: flex; gap: 8px; align-items: center; }
.search-icon { color: #94a3b8; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.model-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; transition: all 0.2s; }
.model-card:hover { transform: translateY(-2px); box-shadow: 0 8px 20px -6px rgba(0,0,0,0.1); border-color: #cbd5e1; }
.card-body { padding: 16px; }
.card-top { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
.icon-wrapper { width: 40px; height: 40px; border-radius: 10px; background: #e0e7ff; color: #4f46e5; display: flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; flex-shrink: 0; }
.info { flex: 1; min-width: 0; }
.name-row { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.name { font-size: 15px; font-weight: 600; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.supplier { font-size: 12px; color: #64748b; background: #f1f5f9; padding: 1px 8px; border-radius: 999px; }
.card-meta { display: flex; flex-direction: column; gap: 6px; }
.meta-item { display: flex; align-items: center; font-size: 13px; color: #475569; overflow: hidden; }
.label { color: #94a3b8; width: 40px; flex-shrink: 0; }
.value { font-family: monospace; background: #f8fafc; padding: 1px 6px; border-radius: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-actions { display: flex; justify-content: space-between; align-items: center; padding: 8px 16px; background: #f8fafc; border-top: 1px solid #f1f5f9; }
.right-actions { display: flex; gap: 4px; }
.empty { display: flex; justify-content: center; align-items: center; min-height: 300px; }
</style>
