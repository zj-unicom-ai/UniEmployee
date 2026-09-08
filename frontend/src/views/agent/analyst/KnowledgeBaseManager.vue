<!--
数据分析 · 知识库绑定页
功能：列出 xiaoshu 已绑定的知识库 + 从资源中心选知识库绑定/解绑
-->
<template>
  <div class="kb-manager">
    <div class="config-nav">
      <n-button text size="small" @click="$router.push({ name: 'analyst' })">
        ← 返回对话
      </n-button>
      <n-tabs type="line" size="small" :value="currentTab" @update:value="switchTab">
        <n-tab name="datasources">库表配置</n-tab>
        <n-tab name="terminologies">术语配置</n-tab>
        <n-tab name="sql-examples">SQL 示例</n-tab>
        <n-tab name="knowledge-bases">知识库</n-tab>
        <n-tab name="connectors">连接器</n-tab>
      </n-tabs>
    </div>

    <div class="kb-body">
      <div class="panel-header">
        <span>已绑定知识库（{{ boundKbs.length }}）</span>
        <n-button size="small" type="primary" @click="openBindDialog">+ 绑定知识库</n-button>
      </div>

      <div class="kb-list">
        <div v-for="kb in boundKbs" :key="kb.id" class="kb-card">
          <div class="card-main">
            <div class="card-name">{{ kb.name }}</div>
            <div class="card-desc">{{ kb.description || '无描述' }}</div>
            <div class="card-meta">
              <n-tag size="tiny" type="info">RAGFlow</n-tag>
              <span v-if="kb.ragflow_dataset_id" class="meta-text">{{ kb.ragflow_dataset_id }}</span>
              <span v-else class="meta-text warn">未配置 dataset_id</span>
            </div>
          </div>
          <div class="card-actions">
            <n-popconfirm @positive-click="doUnbind(kb)">
              <template #trigger>
                <n-button size="tiny" type="error" text>解绑</n-button>
              </template>
              确认解绑知识库「{{ kb.name }}」？
            </n-popconfirm>
          </div>
        </div>
        <n-empty v-if="!boundKbs.length" description="暂未绑定知识库" size="small" />
      </div>
    </div>

    <!-- 绑定选择弹窗 -->
    <n-modal v-model:show="showBindDialog" preset="card" style="width: 560px" title="选择知识库绑定">
      <n-input v-model:value="bindSearch" size="small" placeholder="搜索知识库名称" clearable style="margin-bottom: 12px" />
      <div class="bind-list">
        <div
          v-for="kb in availableKbs"
          :key="kb.id"
          class="bind-item"
          :class="{ bound: isBound(kb.id) }"
        >
          <div class="bind-main">
            <div class="bind-name">{{ kb.name }}</div>
            <div class="bind-desc">{{ kb.description || '无描述' }}</div>
          </div>
          <n-button
            v-if="!isBound(kb.id)"
            size="tiny"
            type="primary"
            @click="doBind(kb)"
          >绑定</n-button>
          <n-tag v-else size="tiny" type="success">已绑定</n-tag>
        </div>
        <n-empty v-if="!availableKbs.length" description="没有可选知识库" size="small" />
      </div>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import * as analystApi from '../../../api/analyst.js'

const router = useRouter()
const message = useMessage()

const currentTab = 'knowledge-bases'
function switchTab(name) {
  if (name === 'datasources') router.push({ name: 'analyst-datasources' })
  else if (name === 'terminologies') router.push({ name: 'analyst-terminologies' })
  else if (name === 'sql-examples') router.push({ name: 'analyst-sql-examples' })
  else if (name === 'connectors') router.push({ name: 'analyst-connectors' })
}

const boundKbs = ref([])
const allKbs = ref([])
const showBindDialog = ref(false)
const bindSearch = ref('')

const availableKbs = computed(() => {
  if (!bindSearch.value) return allKbs.value
  const kw = bindSearch.value.toLowerCase()
  return allKbs.value.filter(kb =>
    kb.name.toLowerCase().includes(kw) || (kb.description || '').toLowerCase().includes(kw))
})

function isBound(kbId) {
  return boundKbs.value.some(kb => kb.id === kbId)
}

async function loadBound() {
  try {
    boundKbs.value = await analystApi.listBoundKbs()
  } catch (e) {
    message.error('加载已绑定知识库失败：' + (e.response?.data?.detail || e.message))
  }
}

async function loadAll() {
  try {
    allKbs.value = await analystApi.listAllKbs()
  } catch (e) {
    message.error('加载知识库列表失败：' + (e.response?.data?.detail || e.message))
  }
}

function openBindDialog() {
  bindSearch.value = ''
  showBindDialog.value = true
}

async function doBind(kb) {
  try {
    await analystApi.bindKb(kb.id)
    message.success('已绑定：' + kb.name)
    await loadBound()
  } catch (e) {
    message.error('绑定失败：' + (e.response?.data?.detail || e.message))
  }
}

async function doUnbind(kb) {
  try {
    await analystApi.unbindKb(kb.id)
    message.success('已解绑：' + kb.name)
    await loadBound()
  } catch (e) {
    message.error('解绑失败：' + (e.response?.data?.detail || e.message))
  }
}

onMounted(async () => {
  await Promise.all([loadBound(), loadAll()])
})
</script>

<style scoped>
.kb-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.config-nav {
  padding: 8px 16px;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  gap: 16px;
}
.kb-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
}
.kb-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.kb-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #f9fafb;
}
.card-main {
  flex: 1;
}
.card-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}
.card-desc {
  font-size: 12px;
  color: #6b7280;
  margin-top: 2px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
}
.meta-text {
  font-size: 11px;
  color: #9ca3af;
}
.meta-text.warn {
  color: #f59e0b;
}
.bind-list {
  max-height: 400px;
  overflow-y: auto;
}
.bind-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px;
  border: 1px solid #f3f4f6;
  border-radius: 4px;
  margin-bottom: 6px;
}
.bind-item.bound {
  background: #f0fdf4;
}
.bind-main {
  flex: 1;
}
.bind-name {
  font-size: 13px;
  font-weight: 600;
}
.bind-desc {
  font-size: 11px;
  color: #6b7280;
  margin-top: 2px;
}
</style>
