<!--
数据分析 · 术语配置页
功能：术语列表 + 新增/编辑表单（术语名/同义词/描述/数据源）
-->
<template>
  <div class="term-manager">
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

    <div class="term-body">
      <div class="panel-header">
        <n-input v-model:value="searchKeyword" size="small" placeholder="搜索术语" style="width: 200px" clearable />
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
          <n-button size="small" type="primary" @click="openCreate">+ 新增术语</n-button>
        </n-space>
      </div>

      <div class="term-list">
        <div
          v-for="term in filteredTerms"
          :key="term.id"
          class="term-card"
          :class="{ disabled: !term.enabled }"
        >
          <div class="term-card-header">
            <span class="term-word">{{ term.word }}</span>
            <n-tag v-if="!term.enabled" size="tiny" type="default">禁用</n-tag>
            <n-tag v-else size="tiny" type="success">启用</n-tag>
          </div>
          <div v-if="term.synonyms.length" class="term-synonyms">
            <n-tag v-for="syn in term.synonyms" :key="syn" size="tiny" style="margin: 2px">
              {{ syn }}
            </n-tag>
          </div>
          <div v-if="term.description" class="term-desc">{{ term.description }}</div>
          <div class="term-actions">
            <n-button size="tiny" text @click="toggleEnabled(term)">
              {{ term.enabled ? '禁用' : '启用' }}
            </n-button>
            <n-button size="tiny" text @click="openEdit(term)">编辑</n-button>
            <n-popconfirm @positive-click="deleteTerm(term)">
              <template #trigger>
                <n-button size="tiny" text type="error">删除</n-button>
              </template>
              确认删除术语「{{ term.word }}」？
            </n-popconfirm>
          </div>
        </div>
        <n-empty v-if="!filteredTerms.length" description="暂无术语" size="small" />
      </div>
    </div>

    <!-- 术语编辑弹窗 -->
    <n-modal v-model:show="showEditor" preset="card" style="width: 520px" :title="editorMode === 'create' ? '新增术语' : '编辑术语'">
      <n-form :model="editorForm" label-placement="left" label-width="100" size="small">
        <n-form-item label="术语词">
          <n-input v-model:value="editorForm.word" placeholder="如：客户" />
        </n-form-item>
        <n-form-item label="描述">
          <n-input v-model:value="editorForm.description" type="textarea" :rows="2" />
        </n-form-item>
        <n-form-item label="同义词">
          <div style="display: flex; gap: 8px; width: 100%;">
            <n-select
              v-model:value="editorForm.synonyms"
              filterable
              multiple
              tag
              placeholder="回车添加同义词"
              style="flex: 1"
            />
            <n-button size="small" :loading="generating" @click="onGenerateSynonyms">
              AI 生成
            </n-button>
          </div>
        </n-form-item>

        <!-- AI 生成同义词候选项弹窗 -->
        <n-modal
          v-model:show="showSynonymPicker"
          preset="card"
          style="width: 420px"
          title="AI 生成的候选同义词"
        >
          <div style="margin-bottom: 8px; color: #6b7280; font-size: 12px;">
            勾选要加入的同义词，取消勾选的不加入。
          </div>
          <n-checkbox-group v-model:value="pickedSynonyms">
            <n-space vertical>
              <n-checkbox
                v-for="s in generatedSynonyms"
                :key="s"
                :value="s"
                :label="s"
              />
            </n-space>
          </n-checkbox-group>
          <template #footer>
            <n-space>
              <n-button size="small" @click="showSynonymPicker = false">取消</n-button>
              <n-button size="small" type="primary" @click="confirmPickSynonyms">
                加入到同义词
              </n-button>
            </n-space>
          </template>
        </n-modal>
        <n-form-item label="关联数据源">
          <n-select
            v-model:value="editorForm.datasource_ids"
            :options="dsOptions"
            multiple
            placeholder="空表示适用所有数据源"
          />
        </n-form-item>
        <n-form-item label="启用">
          <n-switch v-model:value="editorForm.enabled" :checked-value="1" :unchecked-value="0" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button size="small" @click="showEditor = false">取消</n-button>
          <n-button size="small" type="primary" @click="saveTerm">保存</n-button>
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

const currentTab = 'terminologies'
function switchTab(name) {
  if (name === 'datasources') router.push({ name: 'analyst-datasources' })
  else if (name === 'sql-examples') router.push({ name: 'analyst-sql-examples' })
  else if (name === 'knowledge-bases') router.push({ name: 'analyst-kbs' })
  else if (name === 'connectors') router.push({ name: 'analyst-connectors' })
}

const terms = ref([])
const searchKeyword = ref('')
const filterDsId = ref(null)
const showDisabled = ref(false)
const dsOptions = ref([])

const filteredTerms = computed(() => {
  let r = terms.value
  if (!showDisabled.value) r = r.filter(t => t.enabled)
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    r = r.filter(t =>
      t.word.toLowerCase().includes(kw) ||
      t.synonyms.some(s => s.toLowerCase().includes(kw)) ||
      (t.description || '').toLowerCase().includes(kw)
    )
  }
  return r
})

async function loadTerms() {
  try {
    terms.value = await analystApi.listTerminologies({
      include_disabled: showDisabled.value ? 1 : 0,
    })
  } catch (e) {
    message.error('加载术语失败：' + (e.response?.data?.detail || e.message))
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
    id: null, word: '', description: '', synonyms: [], datasource_ids: [], enabled: 1,
  })
  showEditor.value = true
}

function openEdit(term) {
  editorMode.value = 'edit'
  editorForm.id = term.id
  editorForm.word = term.word
  editorForm.description = term.description
  editorForm.synonyms = [...term.synonyms]
  editorForm.datasource_ids = [...term.datasource_ids]
  editorForm.enabled = term.enabled
  showEditor.value = true
}

async function saveTerm() {
  if (!editorForm.word) { message.warning('请填写术语词'); return }
  try {
    if (editorMode.value === 'create') {
      await analystApi.createTerminology({
        word: editorForm.word,
        description: editorForm.description,
        synonyms: editorForm.synonyms,
        datasource_ids: editorForm.datasource_ids,
        enabled: editorForm.enabled,
      })
      message.success('已创建')
    } else {
      await analystApi.updateTerminology(editorForm.id, {
        word: editorForm.word,
        description: editorForm.description,
        synonyms: editorForm.synonyms,
        datasource_ids: editorForm.datasource_ids,
        enabled: editorForm.enabled,
      })
      message.success('已更新')
    }
    showEditor.value = false
    await loadTerms()
  } catch (e) {
    message.error('保存失败：' + (e.response?.data?.detail || e.message))
  }
}

async function deleteTerm(term) {
  try {
    await analystApi.deleteTerminology(term.id)
    message.success('已删除')
    await loadTerms()
  } catch (e) {
    message.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

async function toggleEnabled(term) {
  try {
    await analystApi.toggleTerminology(term.id, term.enabled ? 0 : 1)
    await loadTerms()
  } catch (e) {
    message.error('操作失败：' + (e.response?.data?.detail || e.message))
  }
}

const showEditor = ref(false)
const editorMode = ref('create')
const editorForm = reactive({
  id: null, word: '', description: '', synonyms: [], datasource_ids: [], enabled: 1,
})

// AI 生成同义词
const generating = ref(false)
const showSynonymPicker = ref(false)
const generatedSynonyms = ref([])
const pickedSynonyms = ref([])

async function onGenerateSynonyms() {
  if (!editorForm.word) {
    message.warning('请先填写术语词')
    return
  }
  generating.value = true
  try {
    const res = await analystApi.generateSynonyms(editorForm.word)
    generatedSynonyms.value = res.synonyms || []
    // 默认勾选所有候选
    pickedSynonyms.value = [...generatedSynonyms.value]
    if (!generatedSynonyms.value.length) {
      message.info('LLM 未返回候选同义词')
      return
    }
    showSynonymPicker.value = true
  } catch (e) {
    message.error('生成失败：' + (e.response?.data?.detail || e.message))
  } finally {
    generating.value = false
  }
}

function confirmPickSynonyms() {
  // 把勾选的同义词合并到 editorForm.synonyms，去重
  const existing = new Set(editorForm.synonyms)
  for (const s of pickedSynonyms.value) {
    if (!existing.has(s)) {
      editorForm.synonyms.push(s)
      existing.add(s)
    }
  }
  showSynonymPicker.value = false
}

onMounted(async () => {
  await Promise.all([loadTerms(), loadDatasources()])
})
</script>

<style scoped>
.term-manager {
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
.term-body {
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
.term-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.term-card {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}
.term-card.disabled { opacity: 0.6; }
.term-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.term-word { font-size: 14px; font-weight: 600; color: #1f2937; }
.term-synonyms { margin-bottom: 6px; }
.term-desc {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 8px;
}
.term-actions {
  display: flex;
  gap: 12px;
  border-top: 1px solid #f3f4f6;
  padding-top: 6px;
}
</style>
