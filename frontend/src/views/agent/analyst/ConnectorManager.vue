<!--
数据分析 · 连接器绑定页
功能：列出 xiaoshu 已绑定的连接器 + 从资源中心选连接器绑定/解绑
-->
<template>
  <div class="conn-manager">
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

    <div class="conn-body">
      <div class="panel-header">
        <span>已绑定连接器（{{ boundConnectors.length }}）</span>
        <n-button size="small" type="primary" @click="openBindDialog">+ 绑定连接器</n-button>
      </div>

      <div class="conn-list">
        <div v-for="c in boundConnectors" :key="c.id" class="conn-card">
          <div class="card-main">
            <div class="card-name">{{ c.name }}</div>
            <div class="card-desc">{{ c.description || '无描述' }}</div>
            <div class="card-meta">
              <n-tag size="tiny" type="warning">MCP</n-tag>
              <span class="meta-text">{{ c.config?.command || '未配置命令' }}</span>
            </div>
          </div>
          <div class="card-actions">
            <n-popconfirm @positive-click="doUnbind(c)">
              <template #trigger>
                <n-button size="tiny" type="error" text>解绑</n-button>
              </template>
              确认解绑连接器「{{ c.name }}」？
            </n-popconfirm>
          </div>
        </div>
        <n-empty v-if="!boundConnectors.length" description="暂未绑定连接器" size="small" />
      </div>
    </div>

    <!-- 绑定选择弹窗 -->
    <n-modal v-model:show="showBindDialog" preset="card" style="width: 560px" title="选择连接器绑定">
      <n-input v-model:value="bindSearch" size="small" placeholder="搜索连接器名称" clearable style="margin-bottom: 12px" />
      <div class="bind-list">
        <div
          v-for="c in availableConnectors"
          :key="c.id"
          class="bind-item"
          :class="{ bound: isBound(c.id) }"
        >
          <div class="bind-main">
            <div class="bind-name">{{ c.name }}</div>
            <div class="bind-desc">{{ c.description || '无描述' }}</div>
          </div>
          <n-button
            v-if="!isBound(c.id)"
            size="tiny"
            type="primary"
            @click="doBind(c)"
          >绑定</n-button>
          <n-tag v-else size="tiny" type="success">已绑定</n-tag>
        </div>
        <n-empty v-if="!availableConnectors.length" description="没有可选连接器" size="small" />
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

const currentTab = 'connectors'
function switchTab(name) {
  if (name === 'datasources') router.push({ name: 'analyst-datasources' })
  else if (name === 'terminologies') router.push({ name: 'analyst-terminologies' })
  else if (name === 'sql-examples') router.push({ name: 'analyst-sql-examples' })
  else if (name === 'knowledge-bases') router.push({ name: 'analyst-kbs' })
}

const boundConnectors = ref([])
const allConnectors = ref([])
const showBindDialog = ref(false)
const bindSearch = ref('')

const availableConnectors = computed(() => {
  if (!bindSearch.value) return allConnectors.value
  const kw = bindSearch.value.toLowerCase()
  return allConnectors.value.filter(c =>
    c.name.toLowerCase().includes(kw) || (c.description || '').toLowerCase().includes(kw))
})

function isBound(connId) {
  return boundConnectors.value.some(c => c.id === connId)
}

async function loadBound() {
  try {
    boundConnectors.value = await analystApi.listBoundConnectors()
  } catch (e) {
    message.error('加载已绑定连接器失败：' + (e.response?.data?.detail || e.message))
  }
}

async function loadAll() {
  try {
    allConnectors.value = await analystApi.listAllConnectors()
  } catch (e) {
    message.error('加载连接器列表失败：' + (e.response?.data?.detail || e.message))
  }
}

function openBindDialog() {
  bindSearch.value = ''
  showBindDialog.value = true
}

async function doBind(c) {
  try {
    await analystApi.bindConnector(c.id)
    message.success('已绑定：' + c.name)
    await loadBound()
  } catch (e) {
    message.error('绑定失败：' + (e.response?.data?.detail || e.message))
  }
}

async function doUnbind(c) {
  try {
    await analystApi.unbindConnector(c.id)
    message.success('已解绑：' + c.name)
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
.conn-manager {
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
.conn-body {
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
.conn-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.conn-card {
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
