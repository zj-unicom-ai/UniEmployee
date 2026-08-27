<!-- 业务本体：企业实体/关系类型（schema）与业务实例（data）的可视化管理，仅管理员可编辑 -->
<template>
  <div class="onto-page">
    <div class="onto-stats">
      <n-card size="small" class="stat-card">
        <n-statistic label="业务实体" :value="stats.total_entities || 0" />
      </n-card>
      <n-card size="small" class="stat-card">
        <n-statistic label="业务关系" :value="stats.total_relations || 0" />
      </n-card>
      <n-card size="small" class="stat-card grow">
        <div class="type-badges">
          <n-tag v-for="t in (stats.by_type || [])" :key="t.entity_type" size="small" round bordered>
            {{ entityTypeName(t.entity_type) }} × {{ t.c }}
          </n-tag>
        </div>
      </n-card>
    </div>

    <n-tabs v-model:value="activeTab" type="line" animated>
      <!-- 实体实例 -->
      <n-tab-pane name="entities" tab="业务实体">
        <div class="onto-toolbar">
          <n-select v-model:value="filterType" clearable placeholder="全部类型" :options="typeOptions" style="width:180px" />
          <n-input v-model:value="keyword" clearable placeholder="搜索名称/属性" style="width:240px" @keyup.enter="loadEntities" />
          <n-button @click="loadEntities">查询</n-button>
          <div class="spacer" />
          <n-button type="primary" @click="openEntityModal()">+ 新建实体</n-button>
        </div>
        <div v-if="entities.length" class="card-grid">
          <div v-for="e in entities" :key="e.id" class="res-card onto-card" @click="openEntityDetail(e.id)">
            <div class="card-head">
              <span class="card-name">{{ e.name }}</span>
              <n-tag size="tiny" round bordered>{{ entityTypeName(e.entity_type) }}</n-tag>
            </div>
            <div class="onto-props">
              <div v-for="(v, k) in propPreview(e)" :key="k" class="onto-prop">
                <span class="onto-prop-key">{{ attrName(e.entity_type, k) }}</span>
                <span class="onto-prop-val">{{ v }}</span>
              </div>
            </div>
            <div class="card-acts" @click.stop>
              <n-button size="tiny" quaternary @click="openEntityModal(e)">编辑</n-button>
              <n-button size="tiny" quaternary type="error" @click="delEntity(e.id)">删除</n-button>
            </div>
          </div>
        </div>
        <div v-else class="onto-empty">暂无数据，点击「+ 新建实体」录入业务数据</div>
      </n-tab-pane>

      <!-- 关系实例 -->
      <n-tab-pane name="relations" tab="业务关系">
        <div class="onto-toolbar">
          <n-button type="primary" @click="openRelationModal()">+ 新建关系</n-button>
        </div>
        <n-data-table :columns="relColumns" :data="relations" size="small" :pagination="relPagination" :row-key="r => r.id" />
      </n-tab-pane>

      <!-- 关系图谱 -->
      <n-tab-pane name="graph" tab="关系图谱">
        <div class="onto-toolbar">
          <span class="graph-hint">节点按实体类型着色，连线为关系（中文名）；拖拽节点调整布局，滚轮缩放，点击节点查看详情</span>
          <div class="spacer" />
          <n-button size="small" @click="relayoutGraph">重新布局</n-button>
        </div>
        <div v-show="relations.length" ref="graphRef" class="onto-graph"></div>
        <n-empty v-if="!relations.length" description="暂无关系数据，先在「业务关系」中创建" size="large" style="padding:60px 0" />
      </n-tab-pane>

      <!-- 类型定义 -->
      <n-tab-pane name="schema" tab="类型定义">
        <div class="onto-schema">
          <div class="onto-schema-block">
            <div class="onto-toolbar">
              <span class="res-title">实体类型（{{ schema.entity_types?.length || 0 }}）</span>
              <n-button size="small" type="primary" @click="openTypeModal()">+ 新建</n-button>
            </div>
            <n-data-table :columns="etColumns" :data="schema.entity_types || []" size="small" :row-key="t => t.id" />
          </div>
          <div class="onto-schema-block">
            <div class="onto-toolbar">
              <span class="res-title">关系类型（{{ schema.relation_types?.length || 0 }}）</span>
              <n-button size="small" type="primary" @click="openRtModal()">+ 新建</n-button>
            </div>
            <n-data-table :columns="rtColumns" :data="schema.relation_types || []" size="small" :row-key="t => t.id" />
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 实体详情抽屉 -->
    <n-drawer v-model:show="detailShow" :width="480">
      <n-drawer-content :title="detailEntity?.name" closable>
        <n-descriptions v-if="detailEntity" :column="1" label-placement="left" size="small">
          <n-descriptions-item label="类型">{{ entityTypeName(detailEntity.entity_type) }}</n-descriptions-item>
          <n-descriptions-item v-for="(v, k) in detailProps" :key="k" :label="attrName(detailEntity.entity_type, k)">{{ v }}</n-descriptions-item>
        </n-descriptions>
        <div class="onto-detail-rel">
          <div class="res-title">关联关系（{{ detailEntity?.relations?.length || 0 }}）</div>
          <n-empty v-if="!detailEntity?.relations?.length" description="暂无关联" size="small" />
          <div v-for="r in detailEntity?.relations" :key="r.id" class="onto-rel-row">
            <n-tag size="tiny" :type="r.from_id === detailEntity.id ? 'success' : 'warning'" round bordered>
              {{ r.from_id === detailEntity.id ? '发出' : '接收' }}
            </n-tag>
            <span class="onto-rel-text">{{ relTypeName(r.relation_type) }} → {{ relTargetName(r) }}</span>
            <n-button size="tiny" quaternary type="error" @click="delRelation(r.id)">删除</n-button>
          </div>
          <n-button size="small" type="primary" ghost style="margin-top:12px" @click="openRelationModal(detailEntity)">
            + 关联到其他实体
          </n-button>
        </div>
      </n-drawer-content>
    </n-drawer>

    <!-- 实体 新建/编辑 弹窗 -->
    <n-modal v-model:show="entityModal" preset="card" :title="editingEntity?.id ? '编辑实体' : '新建实体'" style="width:560px;max-width:92vw">
      <n-form label-placement="left" :label-width="90" size="small">
        <n-form-item label="类型">
          <n-select v-model:value="entityForm.entity_type" :options="typeOptions" filterable @update:value="onEntityTypeChange" />
        </n-form-item>
        <n-form-item label="名称"><n-input v-model:value="entityForm.name" /></n-form-item>
        <n-form-item v-for="a in attrsOf(entityForm.entity_type)" :key="a.key" :label="a.name">
          <n-input v-model:value="entityProps[a.key]" :type="a.type === 'textarea' ? 'textarea' : 'text'" :rows="a.type === 'textarea' ? 2 : 1" placeholder="选填" />
        </n-form-item>
        <n-form-item label="其他属性">
          <n-input v-model:value="entityPropsJson" type="textarea" :rows="3" placeholder='{"key": "value"} 追加额外属性，选填' />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button @click="entityModal = false">取消</n-button>
          <n-button type="primary" @click="saveEntity">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 关系 新建 弹窗 -->
    <n-modal v-model:show="relationModal" preset="card" title="新建业务关系" style="width:520px;max-width:92vw">
      <n-form label-placement="left" :label-width="90" size="small">
        <n-form-item label="来源实体">
          <n-select v-model:value="relationForm.from_id" :options="entityOptions" filterable placeholder="选择实体" />
        </n-form-item>
        <n-form-item label="关系类型">
          <n-select v-model:value="relationForm.relation_type" :options="relationTypeOptions" filterable placeholder="选择关系类型" />
        </n-form-item>
        <n-form-item label="目标实体">
          <n-select v-model:value="relationForm.to_id" :options="entityOptions" filterable placeholder="选择实体" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button @click="relationModal = false">取消</n-button>
          <n-button type="primary" @click="saveRelation">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 实体类型 新建 弹窗 -->
    <n-modal v-model:show="typeModal" preset="card" :title="editingType ? '编辑实体类型' : '新建实体类型'" style="width:560px;max-width:92vw">
      <n-form label-placement="left" :label-width="90" size="small">
        <n-form-item label="代码"><n-input v-model:value="typeForm.code" :disabled="!!editingType" placeholder="唯一标识，如 customer" /></n-form-item>
        <n-form-item label="名称"><n-input v-model:value="typeForm.name" /></n-form-item>
        <n-form-item label="图标"><n-input v-model:value="typeForm.icon" placeholder="emoji，如 🤝" /></n-form-item>
        <n-form-item label="描述"><n-input v-model:value="typeForm.description" /></n-form-item>
        <n-form-item label="属性定义">
          <n-input v-model:value="typeForm.attrs" type="textarea" :rows="4" placeholder='[{"key":"grade","name":"客户等级","type":"text"}]' />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button @click="typeModal = false">取消</n-button>
          <n-button type="primary" @click="saveType">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 关系类型 新建 弹窗 -->
    <n-modal v-model:show="rtModal" preset="card" :title="editingRt ? '编辑关系类型' : '新建关系类型'" style="width:560px;max-width:92vw">
      <n-form label-placement="left" :label-width="90" size="small">
        <n-form-item label="代码"><n-input v-model:value="rtForm.code" :disabled="!!editingRt" placeholder="唯一标识，如 follow_up" /></n-form-item>
        <n-form-item label="名称"><n-input v-model:value="rtForm.name" /></n-form-item>
        <n-form-item label="来源类型">
          <n-select v-model:value="rtForm.from_type" :options="typeOptions" filterable />
        </n-form-item>
        <n-form-item label="目标类型">
          <n-select v-model:value="rtForm.to_type" :options="typeOptions" filterable />
        </n-form-item>
        <n-form-item label="基数"><n-input v-model:value="rtForm.cardinality" placeholder="如 1:n" /></n-form-item>
        <n-form-item label="描述"><n-input v-model:value="rtForm.description" /></n-form-item>
      </n-form>
      <template #footer>
        <n-space>
          <n-button @click="rtModal = false">取消</n-button>
          <n-button type="primary" @click="saveRt">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, computed, h, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useMessage } from 'naive-ui'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'

echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer])

const msg = useMessage()
const auth = useAuthStore()
const activeTab = ref('entities')

const schema = ref({ entity_types: [], relation_types: [] })
const entities = ref([])
const relations = ref([])
const stats = ref({})
const filterType = ref(null)
const keyword = ref('')

const typeOptions = computed(() => (schema.value.entity_types || []).map(t => ({ label: `${t.icon || ''} ${t.name}（${t.code}）`, value: t.code })))
const relationTypeOptions = computed(() => (schema.value.relation_types || []).map(t => ({ label: `${t.name}（${t.code}）`, value: t.code })))
const entityOptions = computed(() => entities.value.map(e => ({ label: `【${entityTypeName(e.entity_type)}】${e.name}`, value: e.id })))
const isAdmin = computed(() => auth.isAdmin)

const etColumns = [
  { title: '类型', key: 'code' },
  { title: '名称', key: 'name' },
  { title: '来源', key: 'tenant_id', render: r => h('span', {}, r.tenant_id === 'system' ? '预置' : '自定义') },
  { title: '属性', key: 'attrs', render: r => (r.attrs || []).map(a => a.key).join('、') || '—' },
  { title: '操作', key: 'op', width: 130, render: r => h('div', {}, [
      h('n-button', { size: 'tiny', quaternary: true, onClick: () => openTypeModal(r) }, { default: () => '编辑' }),
      h('n-button', { size: 'tiny', quaternary: true, type: 'error', onClick: () => delType(r) }, { default: () => '删除' }),
    ]) },
]
const rtColumns = [
  { title: '代码', key: 'code' },
  { title: '名称', key: 'name' },
  { title: '方向', key: 'from_type', render: r => h('span', {}, `${entityTypeName(r.from_type)} → ${entityTypeName(r.to_type)}`) },
  { title: '基数', key: 'cardinality' },
  { title: '来源', key: 'tenant_id', render: r => h('span', {}, r.tenant_id === 'system' ? '预置' : '自定义') },
  { title: '操作', key: 'op', width: 130, render: r => h('div', {}, [
      h('n-button', { size: 'tiny', quaternary: true, onClick: () => openRtModal(r) }, { default: () => '编辑' }),
      h('n-button', { size: 'tiny', quaternary: true, type: 'error', onClick: () => delRt(r) }, { default: () => '删除' }),
    ]) },
]
const relColumns = [
  { title: '来源', key: 'from', render: r => h('span', {}, `${relName(r.from_id)}` + (relEntityType(r.from_id) ? `（${entityTypeName(relEntityType(r.from_id))}）` : '')) },
  { title: '关系', key: 'relation_type', render: r => h('n-tag', { size: 'tiny', round: true, bordered: true, title: r.relation_type }, { default: () => relTypeName(r.relation_type) }) },
  { title: '目标', key: 'to', render: r => h('span', {}, `${relName(r.to_id)}` + (relEntityType(r.to_id) ? `（${entityTypeName(relEntityType(r.to_id))}）` : '')) },
  { title: '操作', key: 'op', width: 90, render: r => h('n-button', { size: 'tiny', quaternary: true, type: 'error', onClick: () => delRelation(r.id) }, { default: () => '删除' }) },
]
const relPagination = { pageSize: 15 }

const detailShow = ref(false)
const detailEntity = ref(null)
const detailProps = computed(() => {
  const p = detailEntity.value?.props || {}
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== ''))
})

const entityModal = ref(false)
const editingEntity = ref(null)
const entityForm = ref({ entity_type: null, name: '' })
const entityProps = ref({})
const entityPropsJson = ref('')
const relationModal = ref(false)
const relationForm = ref({ from_id: null, to_id: null, relation_type: null })
const typeModal = ref(false)
const typeForm = ref({})
const editingType = ref(null)
const rtModal = ref(false)
const rtForm = ref({})
const editingRt = ref(null)

const entityById = id => entities.value.find(e => e.id === id)
const relName = id => entityById(id)?.name || `#${id}`
const relEntityType = id => entityById(id)?.entity_type || ''
// code → 中文名映射（schema 未加载或自定义类型缺名时回退显示 code）
const entityTypeName = code => (schema.value.entity_types || []).find(t => t.code === code)?.name || code
const relTypeName = code => (schema.value.relation_types || []).find(t => t.code === code)?.name || code
const attrName = (typeCode, key) =>
  (schema.value.entity_types || []).find(t => t.code === typeCode)?.attrs?.find(a => a.key === key)?.name || key
const propPreview = e => {
  const p = e.props || {}
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== undefined && v !== '').slice(0, 3))
}
const attrsOf = code => (schema.value.entity_types || []).find(t => t.code === code)?.attrs || []
const relTargetName = r => {
  const id = r.from_id === detailEntity.value.id ? r.to_id : r.from_id
  return relName(id)
}

async function loadSchema() {
  schema.value = (await api.get('/admin/ontology/schema')).data
}
async function loadEntities() {
  const params = {}
  if (filterType.value) params.entity_type = filterType.value
  if (keyword.value) params.keyword = keyword.value
  entities.value = (await api.get('/admin/ontology/entities', { params })).data.items
}
async function loadRelations() {
  relations.value = (await api.get('/admin/ontology/relations')).data.items
}
async function loadStats() {
  stats.value = (await api.get('/admin/ontology/stats')).data
}
async function reloadAll() {
  await Promise.all([loadSchema(), loadEntities(), loadRelations(), loadStats()])
}

function openEntityDetail(id) {
  api.get(`/admin/ontology/entities/${id}`).then(r => { detailEntity.value = r.data; detailShow.value = true })
}
function openEntityModal(e) {
  editingEntity.value = e || null
  entityForm.value = { entity_type: e?.entity_type || null, name: e?.name || '' }
  entityProps.value = { ...(e?.props || {}) }
  entityPropsJson.value = ''
  entityModal.value = true
}
function onEntityTypeChange() { entityProps.value = {}; entityPropsJson.value = '' }
async function saveEntity() {
  try {
    const extra = entityPropsJson.value.trim() ? JSON.parse(entityPropsJson.value) : {}
    const props = { ...entityProps.value, ...extra }
    if (editingEntity.value) {
      await api.put(`/admin/ontology/entities/${editingEntity.value.id}`, { ...entityForm.value, props })
    } else {
      await api.post('/admin/ontology/entities', { ...entityForm.value, props })
    }
    msg.success('已保存')
    entityModal.value = false
    reloadAll()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  }
}
async function delEntity(id) {
  if (!confirm('确定删除该实体？其关联关系将一并删除。')) return
  await api.delete(`/admin/ontology/entities/${id}`)
  msg.success('已删除')
  reloadAll()
}

function openRelationModal(detail) {
  relationForm.value = { from_id: detail?.id || null, to_id: null, relation_type: null }
  relationModal.value = true
}
async function saveRelation() {
  try {
    await api.post('/admin/ontology/relations', relationForm.value)
    msg.success('已保存')
    relationModal.value = false
    reloadAll()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  }
}
async function delRelation(id) {
  if (!confirm('确定删除该关系？')) return
  await api.delete(`/admin/ontology/relations/${id}`)
  msg.success('已删除')
  reloadAll()
}

function openTypeModal(t) {
  editingType.value = t || null
  typeForm.value = {
    code: t?.code || '', name: t?.name || '', icon: t?.icon || '',
    description: t?.description || '', attrs: JSON.stringify(t?.attrs || [], null, 1) || '[]',
  }
  typeModal.value = true
}
async function saveType() {
  try {
    const body = { ...typeForm.value, attrs: JSON.parse(typeForm.value.attrs || '[]') }
    if (editingType.value) {
      await api.put(`/admin/ontology/entity-types/${editingType.value.id}`, body)
    } else {
      await api.post('/admin/ontology/entity-types', body)
    }
    msg.success('已保存')
    typeModal.value = false
    reloadAll()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  }
}
function openRtModal(t) {
  editingRt.value = t || null
  rtForm.value = {
    code: t?.code || '', name: t?.name || '', from_type: t?.from_type || null,
    to_type: t?.to_type || null, cardinality: t?.cardinality || 'm:n', description: t?.description || '',
  }
  rtModal.value = true
}
async function saveRt() {
  try {
    if (editingRt.value) {
      await api.put(`/admin/ontology/relation-types/${editingRt.value.id}`, rtForm.value)
    } else {
      await api.post('/admin/ontology/relation-types', rtForm.value)
    }
    msg.success('已保存')
    rtModal.value = false
    reloadAll()
  } catch (e) {
    msg.error(e.response?.data?.detail || '保存失败')
  }
}

async function delType(t) {
  const used = entities.value.filter(e => e.entity_type === t.code).length
  const tip = used
    ? `仍有 ${used} 个「${t.name}」实体，删除类型不会删除这些实体（其类型将显示为原始代码）。确定删除？`
    : `确定删除实体类型「${t.name}（${t.code}）」？`
  if (!confirm(tip)) return
  await api.delete(`/admin/ontology/entity-types/${t.id}`)
  msg.success('已删除')
  reloadAll()
}

async function delRt(t) {
  const used = relations.value.filter(r => r.relation_type === t.code).length
  const tip = used
    ? `仍有 ${used} 条「${t.name}」关系实例，删除类型不会删除这些关系（其类型将显示为原始代码）。确定删除？`
    : `确定删除关系类型「${t.name}（${t.code}）」？`
  if (!confirm(tip)) return
  await api.delete(`/admin/ontology/relation-types/${t.id}`)
  msg.success('已删除')
  reloadAll()
}

onMounted(reloadAll)

// ---------------- 关系图谱 ----------------
const graphRef = ref(null)
let chart = null
let graphEntities = []
let graphObserver = null

function buildGraphOption() {
  const ets = schema.value.entity_types || []
  const categories = ets.map(t => ({ name: t.name }))
  const catIdx = Object.fromEntries(ets.map((t, i) => [t.code, i]))
  const degree = {}
  relations.value.forEach(r => {
    degree[r.from_id] = (degree[r.from_id] || 0) + 1
    degree[r.to_id] = (degree[r.to_id] || 0) + 1
  })
  const nodes = graphEntities.map(e => ({
    id: String(e.id),
    name: e.name,
    entityType: e.entity_type,
    category: catIdx[e.entity_type],
    symbolSize: Math.min(24 + (degree[e.id] || 0) * 4, 56),
    value: degree[e.id] || 0,
    itemStyle: catIdx[e.entity_type] === undefined ? { color: '#909399' } : undefined,
  }))
  const entMap = Object.fromEntries(graphEntities.map(e => [String(e.id), e]))
  const links = relations.value.map(r => ({
    source: String(r.from_id),
    target: String(r.to_id),
    value: relTypeName(r.relation_type),
    lineStyle: { color: 'source', curveness: 0.15 },
  }))
  return {
    tooltip: {
      confine: true,
      formatter: p => {
        if (p.dataType === 'edge') {
          const from = entMap[p.data.source]?.name || p.data.source
          const to = entMap[p.data.target]?.name || p.data.target
          return `${from} —${p.data.value}→ ${to}`
        }
        return `<b>${p.data.name}</b><br/>类型：${entityTypeName(p.data.entityType)}<br/>关联数：${p.data.value}`
      },
    },
    legend: [{ data: categories.map(c => c.name), bottom: 0, type: 'scroll' }],
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      categories,
      data: nodes,
      links,
      force: { repulsion: 320, edgeLength: [60, 130], gravity: 0.08 },
      label: { show: true, position: 'right', fontSize: 12 },
      labelLayout: { hideOverlap: true },
      edgeLabel: { show: true, fontSize: 10, color: '#999', formatter: p => p.data.value },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
      scaleLimit: { min: 0.3, max: 4 },
    }],
  }
}

async function refreshGraphData() {
  graphEntities = (await api.get('/admin/ontology/entities')).data.items
  if (chart) chart.setOption(buildGraphOption())
}

async function ensureGraph() {
  await nextTick()
  if (!graphRef.value || chart) return
  chart = echarts.init(graphRef.value)
  chart.on('click', p => { if (p.dataType === 'node') openEntityDetail(Number(p.data.id)) })
  graphObserver = new ResizeObserver(() => chart && chart.resize())
  graphObserver.observe(graphRef.value)
  await refreshGraphData()
}

function relayoutGraph() {
  if (!chart) return
  chart.dispose()
  chart = null
  ensureGraph()
}

watch(activeTab, t => { if (t === 'graph') ensureGraph() })
watch(relations, () => { if (chart) refreshGraphData() })

onBeforeUnmount(() => {
  graphObserver?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.onto-page { padding: 24px; height: 100%; overflow-y: auto; }
.onto-stats { display: flex; gap: 12px; margin-bottom: 16px; }
.stat-card { flex: 0 0 180px; }
.stat-card.grow { flex: 1; }
.type-badges { display: flex; flex-wrap: wrap; gap: 6px; }
.onto-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.spacer { flex: 1; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.onto-card { cursor: pointer; }
.onto-props { margin: 8px 0; }
.onto-prop { display: flex; gap: 6px; font-size: 12px; line-height: 1.7; }
.onto-prop-key { color: #888; flex: 0 0 64px; }
.onto-prop-val { color: #444; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.onto-empty { color: #aaa; text-align: center; padding: 48px 0; }
.onto-schema { display: flex; flex-direction: column; gap: 24px; }
.onto-detail-rel { margin-top: 16px; }
.onto-rel-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.onto-rel-text { flex: 1; font-size: 13px; }
.onto-graph { height: 560px; border: 1px solid #e0e0e6; border-radius: 8px; }
.graph-hint { color: #888; font-size: 12px; }
</style>
