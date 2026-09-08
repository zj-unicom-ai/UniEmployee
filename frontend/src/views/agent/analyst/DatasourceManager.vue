<!--
数据分析 · 库表配置页
功能：数据源 CRUD + 表结构树 + 表/字段中文标注 + 可查询开关
-->
<template>
  <div class="ds-manager">
    <!-- 顶部配置导航 -->
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

    <div class="ds-body">
      <!-- 左：数据源列表 -->
      <div class="ds-list-panel">
        <div class="panel-header">
          <span>数据源</span>
          <n-button size="tiny" type="primary" @click="openCreate">+ 新增</n-button>
        </div>
        <div class="ds-items">
          <div
            v-for="ds in datasources" :key="ds.id"
            class="ds-item"
            :class="{ active: selectedId === ds.id }"
            @click="selectDs(ds.id)"
          >
            <div class="ds-item-row">
              <span class="ds-name">{{ ds.name }}</span>
              <div class="ds-actions" @click.stop>
                <n-button size="tiny" text @click="openEdit(ds)">编辑</n-button>
                <n-popconfirm @positive-click="deleteDs(ds)">
                  <template #trigger>
                    <n-button size="tiny" text type="error">删除</n-button>
                  </template>
                  确认删除数据源「{{ ds.name }}」？
                </n-popconfirm>
              </div>
            </div>
            <div class="ds-item-row">
              <n-tag size="tiny" :type="ds.enabled ? 'success' : 'default'">
                {{ ds.enabled ? '启用' : '禁用' }}
              </n-tag>
              <span class="ds-item-meta">{{ ds.db_type }}</span>
            </div>
            <div v-if="ds.description" class="ds-item-meta">{{ ds.description }}</div>
          </div>
          <n-empty v-if="!datasources.length" description="暂无数据源" size="small" />
        </div>
      </div>

      <!-- 右：表结构 + 标注 -->
      <div class="ds-detail-panel">
        <template v-if="selectedDs">
          <div class="panel-header">
            <span>{{ selectedDs.name }} · 表结构</span>
            <n-button size="tiny" @click="refreshTables">刷新</n-button>
          </div>
          <div class="tables-area">
            <div
              v-for="t in tables" :key="t.name"
              class="table-card"
              :class="{ active: selectedTable === t.name }"
              @click="selectTable(t.name)"
            >
              <div class="table-card-header">
                <span class="table-name">{{ t.name }}</span>
                <span class="table-meta-inline">{{ t.column_count }} 列 · {{ t.foreign_key_count }} 外键</span>
              </div>
              <div v-if="t.comment" class="table-comment" :title="t.comment">{{ t.comment }}</div>
            </div>
            <n-empty v-if="!tables.length" description="点击刷新发现表" size="small" />
          </div>

          <!-- 表标注编辑 -->
          <div v-if="selectedTableSchema" class="annotation-area">
            <n-tabs type="line" size="small" v-model:value="detailTab" @update:value="onTabChange" style="height: 100%">
              <n-tab-pane name="annotation" tab="字段标注">
                <div class="panel-header">
                  <span>{{ selectedTable }} · 标注</span>
                  <n-button size="tiny" type="primary" @click="saveAnnotation">保存标注</n-button>
                </div>
                <div class="ann-form">
                  <div class="ann-row">
                    <label>表中文名</label>
                    <n-input v-model:value="annotation.table_comment" size="small" placeholder="如：客户表" />
                  </div>
                  <div class="ann-row">
                    <label>可查询</label>
                    <n-switch v-model:value="annotation.queryable" :checked-value="1" :unchecked-value="0" />
                  </div>
                  <div class="ann-columns">
                    <div
                      class="ann-row"
                      v-for="(col, colName) in selectedTableSchema.columns"
                      :key="colName"
                    >
                      <label>{{ colName }} <span class="col-type">{{ col.type }}</span></label>
                      <n-input
                        v-model:value="annotation.column_annotations[colName].comment"
                        size="small"
                        placeholder="字段中文标注"
                      />
                    </div>
                  </div>
                </div>
              </n-tab-pane>

              <n-tab-pane name="preview" tab="数据预览">
                <div class="panel-header">
                  <span>{{ selectedTable }} · 数据预览（前 {{ previewLimit }} 行）</span>
                  <n-button size="tiny" @click="loadPreview" :loading="previewing">刷新</n-button>
                </div>
                <div v-if="previewData.length" class="preview-table">
                  <n-data-table
                    size="small"
                    :columns="previewColumns"
                    :data="previewData"
                    :bordered="true"
                    :single-line="false"
                    :max-height="360"
                    :scroll-x="previewColumns.length * 140"
                  />
                </div>
                <n-empty v-else description="正在加载..." size="small" style="padding: 30px 0" />
              </n-tab-pane>
            </n-tabs>
          </div>
        </template>
        <n-empty v-else description="选择左侧数据源" style="padding: 60px 0" />
      </div>
    </div>

    <!-- 数据源编辑弹窗 -->
    <n-modal v-model:show="showEditor" preset="card" style="width: 560px" :title="editorMode === 'create' ? '新增数据源' : '编辑数据源'">
      <n-form :model="editorForm" label-placement="left" label-width="100" size="small">
        <n-form-item label="名称"><n-input v-model:value="editorForm.name" placeholder="如：业务库" /></n-form-item>
        <n-form-item label="描述"><n-input v-model:value="editorForm.description" /></n-form-item>
        <n-form-item label="类型">
          <n-select v-model:value="editorForm.db_type" :options="dbTypeOptions" />
        </n-form-item>
        <n-form-item label="主机"><n-input v-model:value="editorForm.config.host" /></n-form-item>
        <n-form-item label="端口"><n-input v-model:value="editorForm.config.port" /></n-form-item>
        <n-form-item label="数据库"><n-input v-model:value="editorForm.config.database" /></n-form-item>
        <n-form-item label="用户名"><n-input v-model:value="editorForm.config.username" /></n-form-item>
        <n-form-item label="密码"><n-input v-model:value="editorForm.config.password" type="password" show-password-on="click" /></n-form-item>
        <n-form-item label="Schema">
          <n-input v-model:value="editorForm.config.dbSchema" placeholder="PG schema 可选" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button size="small" @click="testCurrentConnection" :loading="testing">
            测试连接
          </n-button>
          <n-button size="small" @click="showEditor = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveDs">保存</n-button>
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

const router = useRouter()
const message = useMessage()

const currentTab = 'datasources'
function switchTab(name) {
  if (name === 'terminologies') router.push({ name: 'analyst-terminologies' })
  else if (name === 'sql-examples') router.push({ name: 'analyst-sql-examples' })
  else if (name === 'knowledge-bases') router.push({ name: 'analyst-kbs' })
  else if (name === 'connectors') router.push({ name: 'analyst-connectors' })
}

const datasources = ref([])
const selectedId = ref(null)
const selectedDs = computed(() => datasources.value.find(d => d.id === selectedId.value))

const tables = ref([])
const selectedTable = ref(null)
const selectedTableSchema = ref(null)
const annotation = reactive({
  table_comment: '',
  queryable: 1,
  column_annotations: {},
})

const showEditor = ref(false)
const editorMode = ref('create')
const editorForm = reactive({
  id: null, name: '', description: '', db_type: 'mysql', config: {},
})
const testing = ref(false)

// 数据预览
const detailTab = ref('annotation')
const previewing = ref(false)
const previewData = ref([])
const previewLimit = 10
const previewColumns = computed(() => {
  if (!previewData.value.length) return []
  return Object.keys(previewData.value[0]).map(key => ({
    title: key,
    key,
    width: 140,
    ellipsis: { tooltip: true },
  }))
})

async function loadPreview() {
  if (!selectedId.value || !selectedTable.value) return
  previewing.value = true
  try {
    const res = await analystApi.previewTableData(selectedId.value, selectedTable.value, previewLimit)
    previewData.value = res.data || []
  } catch (e) {
    message.error('预览失败：' + (e.response?.data?.detail || e.message))
    previewData.value = []
  } finally {
    previewing.value = false
  }
}

// 切换 Tab 时：切到 preview 自动加载一次
function onTabChange(name) {
  if (name === 'preview' && !previewData.value.length) {
    loadPreview()
  }
}

const dbTypeOptions = [
  { label: 'MySQL', value: 'mysql' },
  { label: 'PostgreSQL', value: 'pg' },
  { label: 'Oracle', value: 'oracle' },
  { label: 'SQL Server', value: 'sqlServer' },
  { label: 'ClickHouse', value: 'ck' },
]

async function loadDatasources() {
  try {
    datasources.value = await analystApi.listDatasources()
    if (datasources.value.length && !selectedId.value) {
      await selectDs(datasources.value[0].id)
    }
  } catch (e) {
    message.error('加载数据源失败：' + (e.response?.data?.detail || e.message))
  }
}

async function selectDs(id) {
  selectedId.value = id
  selectedTable.value = null
  selectedTableSchema.value = null
  await refreshTables()
}

async function refreshTables() {
  if (!selectedId.value) return
  try {
    const data = await analystApi.discoverTables(selectedId.value)
    tables.value = data.tables || []
    if (tables.value.length && !selectedTable.value) {
      await selectTable(tables.value[0].name)
    }
  } catch (e) {
    message.error('表结构发现失败：' + (e.response?.data?.detail || e.message))
  }
}

async function selectTable(tableName) {
  selectedTable.value = tableName
  // 切换表时重置预览
  previewData.value = []
  detailTab.value = 'annotation'
  try {
    const schema = await analystApi.getTableSchema(selectedId.value, tableName)
    selectedTableSchema.value = schema
    // 加载标注（优先用 schema.annotation，没有则初始化空标注）
    const ann = schema.annotation || {}
    annotation.table_comment = ann.table_comment || schema.table_comment || ''
    annotation.queryable = ann.queryable !== undefined ? ann.queryable : 1
    const colAnn = ann.column_annotations || {}
    annotation.column_annotations = {}
    for (const colName of Object.keys(schema.columns || {})) {
      annotation.column_annotations[colName] = {
        comment: colAnn[colName]?.comment || schema.columns[colName].comment || '',
      }
    }
  } catch (e) {
    message.error('获取表结构失败：' + (e.response?.data?.detail || e.message))
  }
}

async function saveAnnotation() {
  try {
    await analystApi.upsertAnnotation(selectedId.value, selectedTable.value, {
      table_comment: annotation.table_comment,
      queryable: annotation.queryable,
      column_annotations: annotation.column_annotations,
    })
    message.success('标注已保存')
    await refreshTables()
    await selectTable(selectedTable.value)
  } catch (e) {
    message.error('保存失败：' + (e.response?.data?.detail || e.message))
  }
}

function openCreate() {
  editorMode.value = 'create'
  Object.assign(editorForm, {
    id: null, name: '', description: '', db_type: 'mysql',
    config: { host: '', port: '3306', database: '', username: '', password: '', dbSchema: '' },
  })
  showEditor.value = true
}

function openEdit(ds) {
  editorMode.value = 'edit'
  editorForm.id = ds.id
  editorForm.name = ds.name
  editorForm.description = ds.description
  editorForm.db_type = ds.db_type
  // 注意：list 接口不返回 config，需要单独获取
  analystApi.getDatasource(ds.id).then(d => {
    editorForm.config = {
      host: d.config?.host || '', port: String(d.config?.port || ''),
      database: d.config?.database || '',
      username: d.config?.username || '',
      password: d.config?.password || '',
      dbSchema: d.config?.dbSchema || '',
    }
  })
  showEditor.value = true
}

async function testCurrentConnection() {
  testing.value = true
  try {
    const res = await analystApi.testDatasourceConnection({
      db_type: editorForm.db_type,
      config: editorForm.config,
      datasource_id: editorMode.value === 'edit' ? editorForm.id : null,
    })
    if (res.success) message.success(res.message || '连接成功')
    else message.error(res.message || '连接失败')
  } catch (e) {
    message.error('测试失败：' + (e.response?.data?.detail || e.message))
  } finally {
    testing.value = false
  }
}

async function saveDs() {
  if (!editorForm.name) { message.warning('请填写名称'); return }
  try {
    if (editorMode.value === 'create') {
      await analystApi.createDatasource({
        name: editorForm.name,
        description: editorForm.description,
        db_type: editorForm.db_type,
        config: editorForm.config,
        enabled: 1,
      })
      message.success('已创建')
    } else {
      await analystApi.updateDatasource(editorForm.id, {
        name: editorForm.name,
        description: editorForm.description,
        db_type: editorForm.db_type,
        config: editorForm.config,
      })
      message.success('已更新')
    }
    showEditor.value = false
    await loadDatasources()
  } catch (e) {
    message.error('保存失败：' + (e.response?.data?.detail || e.message))
  }
}

async function deleteDs(ds) {
  try {
    await analystApi.deleteDatasource(ds.id)
    message.success('已删除')
    await loadDatasources()
  } catch (e) {
    message.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

onMounted(loadDatasources)
</script>

<style scoped>
.ds-manager {
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
.ds-body {
  flex: 1;
  display: flex;
  overflow: hidden;
  min-height: 0;
}
.ds-list-panel {
  width: 280px;
  border-right: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
}
.panel-header {
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  border-bottom: 1px solid #f3f4f6;
}
.ds-items { flex: 1; overflow-y: auto; padding: 6px; }
.ds-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
}
.ds-item:hover { background: #f9fafb; }
.ds-item.active { background: #eff6ff; border: 1px solid #bfdbfe; }
.ds-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.ds-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.ds-name { font-size: 13px; font-weight: 500; color: #1f2937; }
.ds-item-meta { font-size: 11px; color: #6b7280; margin-top: 2px; }

.ds-detail-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.tables-area {
  padding: 10px 12px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
  overflow-y: auto;
}
.table-card {
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  cursor: pointer;
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.table-card:hover { background: #f9fafb; }
.table-card.active { border-color: #3b82f6; background: #eff6ff; }
.table-card-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 8px;
}
.table-name {
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  white-space: nowrap;
}
.table-meta-inline {
  font-size: 11px;
  color: #9ca3af;
  white-space: nowrap;
  flex-shrink: 0;
}
.table-comment {
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.annotation-area {
  margin-top: 10px;
  padding: 10px 12px;
  border-top: 1px solid #f3f4f6;
  overflow-y: auto;
}
.ann-form { display: flex; flex-direction: column; gap: 10px; }
.ann-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ann-row label {
  width: 140px;
  font-size: 12px;
  color: #4b5563;
  flex-shrink: 0;
}
.ann-row .n-input { flex: 1; }
.col-type { color: #9ca3af; font-size: 11px; font-weight: 400; }
.ann-columns {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}
</style>
