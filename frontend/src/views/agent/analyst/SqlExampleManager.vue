<!--
数据分析 · SQL 示例页
功能：示例列表 + SQL 语法高亮编辑器（简易版：等宽 + 保留字着色）
-->
<template>
  <div class="ex-manager">
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

    <div class="ex-body">
      <div class="panel-header">
        <n-input v-model:value="searchKeyword" size="small" placeholder="搜索问题" style="width: 240px" clearable />
        <n-space size="small">
          <n-select
            v-model:value="filterDsId"
            :options="dsOptions"
            size="small"
            placeholder="按数据源"
            clearable
            style="width: 160px"
          />
          <n-switch v-model:value="showDisabled" size="small">
            <template #checked>含禁用</template>
            <template #unchecked>仅启用</template>
          </n-switch>
          <n-button size="small" type="primary" @click="openCreate">+ 新增示例</n-button>
        </n-space>
      </div>

      <div class="ex-list">
        <div
          v-for="ex in filteredExamples"
          :key="ex.id"
          class="ex-card"
          :class="{ disabled: !ex.enabled }"
        >
          <div class="ex-card-header">
            <span class="ex-question">{{ ex.question }}</span>
            <n-space size="small">
              <n-tag v-if="ex.chart_type" size="tiny" type="info">{{ ex.chart_type }}</n-tag>
              <n-tag v-if="!ex.enabled" size="tiny" type="default">禁用</n-tag>
            </n-space>
          </div>
          <pre class="ex-sql" v-html="highlightSql(ex.sql_text)"></pre>
          <div v-if="ex.description" class="ex-desc">{{ ex.description }}</div>
          <div class="ex-actions">
            <n-button size="tiny" text @click="toggleEnabled(ex)">
              {{ ex.enabled ? '禁用' : '启用' }}
            </n-button>
            <n-button size="tiny" text @click="openEdit(ex)">编辑</n-button>
            <n-popconfirm @positive-click="deleteExample(ex)">
              <template #trigger>
                <n-button size="tiny" text type="error">删除</n-button>
              </template>
              确认删除示例「{{ ex.question }}」？
            </n-popconfirm>
          </div>
        </div>
        <n-empty v-if="!filteredExamples.length" description="暂无 SQL 示例" size="small" />
      </div>
    </div>

    <!-- 示例编辑弹窗 -->
    <n-modal v-model:show="showEditor" preset="card" style="width: 640px" :title="editorMode === 'create' ? '新增 SQL 示例' : '编辑 SQL 示例'">
      <n-form :model="editorForm" label-placement="left" label-width="100" size="small">
        <n-form-item label="问题">
          <n-input v-model:value="editorForm.question" placeholder="如：本月销售额 TOP10 客户" />
        </n-form-item>
        <n-form-item label="SQL">
          <n-input
            v-model:value="editorForm.sql_text"
            type="textarea"
            :rows="6"
            placeholder="SELECT ... FROM ... LIMIT 10"
            style="font-family: 'SF Mono', Consolas, monospace;"
          />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="editorForm.description" type="textarea" :rows="2" />
        </n-form-item>
        <n-form-item label="关联数据源">
          <n-select
            v-model:value="editorForm.datasource_id"
            :options="dsOptions"
            placeholder="空表示适用所有数据源"
            clearable
          />
        </n-form-item>
        <n-form-item label="图表类型">
          <n-select v-model:value="editorForm.chart_type" :options="chartTypeOptions" />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="editorForm.enabled" :checked-value="1" :unchecked-value="0" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button size="small" @click="showEditor = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveExample">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import * as analystApi from '../../../api/analyst.js'
import { highlightSql } from '../../../utils/sqlFormat.js'

const router = useRouter()
const message = useMessage()

const currentTab = 'sql-examples'
function switchTab(name) {
  if (name === 'datasources') router.push({ name: 'analyst-datasources' })
  else if (name === 'terminologies') router.push({ name: 'analyst-terminologies' })
  else if (name === 'knowledge-bases') router.push({ name: 'analyst-kbs' })
  else if (name === 'connectors') router.push({ name: 'analyst-connectors' })
}

const examples = ref([])
const searchKeyword = ref('')
const filterDsId = ref(null)
const showDisabled = ref(false)
const dsOptions = ref([])

const chartTypeOptions = [
  { label: '默认（表格）', value: '' },
  { label: '表格', value: 'table' },
  { label: '饼图', value: 'pie' },
  { label: '柱状图', value: 'bar' },
  { label: '折线图', value: 'line' },
]

const filteredExamples = computed(() => {
  let r = examples.value
  if (!showDisabled.value) r = r.filter(e => e.enabled)
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    r = r.filter(e =>
      e.question.toLowerCase().includes(kw) ||
      e.sql_text.toLowerCase().includes(kw) ||
      (e.description || '').toLowerCase().includes(kw)
    )
  }
  return r
})

// SQL 关键字高亮（简易版，避免引入外部库）
const SQL_KEYWORDS_REMOVED = true // 已抽到 utils/sqlFormat.js

async function loadExamples() {
  try {
    examples.value = await analystApi.listSqlExamples({
      include_disabled: showDisabled.value ? 1 : 0,
    })
  } catch (e) {
    message.error('加载示例失败：' + (e.response?.data?.detail || e.message))
  }
}

async function loadDatasources() {
  try {
    const list = await analystApi.listDatasources()
    dsOptions.value = list.map(d => ({ label: d.name, value: d.id }))
  } catch {}
}

function openCreate() {
  editorMode.value = 'create'
  Object.assign(editorForm, {
    id: null, question: '', sql_text: '', description: '',
    datasource_id: null, chart_type: '', enabled: 1,
  })
  showEditor.value = true
}

function openEdit(ex) {
  editorMode.value = 'edit'
  editorForm.id = ex.id
  editorForm.question = ex.question
  editorForm.sql_text = ex.sql_text
  editorForm.description = ex.description
  editorForm.datasource_id = ex.datasource_id || null
  editorForm.chart_type = ex.chart_type
  editorForm.enabled = ex.enabled
  showEditor.value = true
}

async function saveExample() {
  if (!editorForm.question) { message.warning('请填写问题'); return }
  if (!editorForm.sql_text) { message.warning('请填写 SQL'); return }
  try {
    if (editorMode.value === 'create') {
      await analystApi.createSqlExample({
        question: editorForm.question,
        sql_text: editorForm.sql_text,
        description: editorForm.description,
        datasource_id: editorForm.datasource_id,
        chart_type: editorForm.chart_type,
        enabled: editorForm.enabled,
      })
      message.success('已创建')
    } else {
      await analystApi.updateSqlExample(editorForm.id, {
        question: editorForm.question,
        sql_text: editorForm.sql_text,
        description: editorForm.description,
        datasource_id: editorForm.datasource_id,
        chart_type: editorForm.chart_type,
        enabled: editorForm.enabled,
      })
      message.success('已更新')
    }
    showEditor.value = false
    await loadExamples()
  } catch (e) {
    message.error('保存失败：' + (e.response?.data?.detail || e.message))
  }
}

async function deleteExample(ex) {
  try {
    await analystApi.deleteSqlExample(ex.id)
    message.success('已删除')
    await loadExamples()
  } catch (e) {
    message.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

async function toggleEnabled(ex) {
  try {
    await analystApi.toggleSqlExample(ex.id, ex.enabled ? 0 : 1)
    await loadExamples()
  } catch (e) {
    message.error('操作失败：' + (e.response?.data?.detail || e.message))
  }
}

const showEditor = ref(false)
const editorMode = ref('create')
const editorForm = reactive({
  id: null, question: '', sql_text: '', description: '',
  datasource_id: null, chart_type: '', enabled: 1,
})

onMounted(async () => {
  await Promise.all([loadExamples(), loadDatasources()])
})
</script>

<style scoped>
.ex-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: #fff;
}
.config-nav {
  padding: 8px 16px 0;
  border-bottom: 1px solid #e5e7eb;
}
.config-nav :deep(.n-button) { margin-bottom: 4px; }
.ex-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 16px;
}
.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.ex-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 12px;
}
.ex-card {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}
.ex-card.disabled { opacity: 0.6; }
.ex-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.ex-question { font-size: 14px; font-weight: 600; color: #1f2937; }
.ex-sql {
  background: #1e293b;
  color: #e2e8f0;
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  font-family: 'SF Mono', Consolas, monospace;
  overflow-x: auto;
  margin-bottom: 8px;
  white-space: pre-wrap;
  word-break: break-all;
}
.ex-sql :deep(.sql-kw) { color: #93c5fd; font-weight: 600; }
.ex-sql :deep(.sql-str) { color: #fcd34d; }
.ex-desc {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 8px;
}
.ex-actions {
  display: flex;
  gap: 12px;
  border-top: 1px solid #f3f4f6;
  padding-top: 6px;
}
</style>
