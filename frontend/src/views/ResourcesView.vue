<!-- 资源中心：技能/工具/知识库/SOP/连接器 的查看与 CRUD，普通用户只读 -->
<template>
  <div class="res-page">
    <n-tabs v-model:value="activeTab" type="line" animated>
      <!-- 技能 -->
      <n-tab-pane name="skills" tab="技能">
        <div class="res-toolbar">
          <span class="res-title">技能（{{ catalog.skills?.length || 0 }}）</span>
          <n-button v-if="isAdmin" size="small" type="primary" @click="openModal('skills')">+ 新建技能</n-button>
        </div>
        <div class="card-grid">
          <div v-for="it in (catalog.skills || [])" :key="it.id" class="res-card tech-card">
            <div class="card-head"><span class="card-name">{{ it.name }}</span><n-tag v-if="it.dir" size="tiny" round bordered>内置</n-tag></div>
            <div class="card-id">{{ it.id }}</div>
            <div class="card-desc">{{ it.description }}</div>
            <div class="card-acts">
              <n-button size="tiny" quaternary @click="viewSkillContent(it)">查看内容</n-button>
              <n-button v-if="isAdmin" size="tiny" quaternary type="error" @click="delItem('skills', it.id)">删除</n-button>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <!-- 工具 -->
      <n-tab-pane name="tools" tab="工具">
        <div class="res-toolbar"><span class="res-title">工具（{{ catalog.tools?.length || 0 }}）</span></div>
        <div class="card-grid">
          <div v-for="it in (catalog.tools || [])" :key="it.id" class="res-card tech-card">
            <div class="card-head"><span class="card-name">{{ it.name }}</span>
              <n-tag v-if="it.is_global" type="info" size="tiny" round bordered>内置</n-tag>
              <n-tag v-if="it.needs_approval" type="warning" size="tiny" round bordered>需审批</n-tag>
            </div>
            <div class="card-id">{{ it.id }}</div>
            <div class="card-desc">{{ it.description }}</div>
          </div>
        </div>
      </n-tab-pane>

      <!-- 知识库 -->
      <n-tab-pane name="kbs" tab="知识库">
        <div class="res-toolbar"><span class="res-title">知识库（{{ catalog.knowledge_bases?.length || 0 }}）</span><n-button v-if="isAdmin" size="small" type="primary" @click="openModal('kbs')">+ 新建</n-button></div>
        <div class="card-grid">
          <div v-for="kb in (catalog.knowledge_bases || [])" :key="kb.id" class="res-card tech-card">
            <div class="card-head"><span class="card-name">{{ kb.name }}</span></div>
            <div class="card-id">{{ kb.id }}</div>
            <div class="card-desc">{{ kb.description }}</div>
            <div class="card-desc" style="margin-top:4px">RAGFlow Dataset：{{ kb.ragflow_dataset_id || '未配置' }}</div>
            <div class="card-acts"><n-button v-if="isAdmin" size="tiny" quaternary @click="openModal('kbs', kb)">编辑</n-button><n-button v-if="isAdmin" size="tiny" quaternary type="error" @click="delItem('kbs', kb.id)">删除</n-button></div>
          </div>
        </div>
        <div style="margin-top:24px">
          <div class="res-toolbar"><span class="res-title">RAGFlow 数据集</span></div>
          <div v-if="ragflowDatasets.length" class="card-grid">
            <div v-for="d in ragflowDatasets" :key="d.id" class="res-card tech-card">
              <div class="card-name">{{ d.name }}</div>
              <div class="card-id">{{ d.id }}</div>
              <div class="card-desc">{{ d.document_count || 0 }} 文档 · {{ d.chunk_count || 0 }} 片段</div>
            </div>
          </div>
          <div v-else class="res-empty">RAGFlow 未返回数据集</div>
        </div>
      </n-tab-pane>

      <!-- SOP -->
      <n-tab-pane name="sops" tab="SOP">
        <div class="res-toolbar"><span class="res-title">SOP 流程文档（{{ catalog.sops?.length || 0 }}）</span><n-button v-if="isAdmin" size="small" type="primary" @click="openModal('sops')">+ 新建 SOP</n-button></div>
        <div class="card-grid">
          <div v-for="it in (catalog.sops || [])" :key="it.id" class="res-card tech-card">
            <div class="card-name">{{ it.name }}</div>
            <div class="card-id">{{ it.id }}</div>
            <div class="card-desc">{{ it.description }}</div>
            <div v-if="it.content" class="card-content" @click.stop="toggleSopContent(it.id)">
              <div class="content-preview" :class="{ expanded: sopExpanded[it.id] }">{{ it.content }}</div>
              <span class="expand-btn">{{ sopExpanded[it.id] ? '收起' : '展开全文' }}</span>
            </div>
            <div class="card-acts"><n-button v-if="isAdmin" size="tiny" quaternary @click="openModal('sops', it)">编辑</n-button><n-button v-if="isAdmin" size="tiny" quaternary type="error" @click="delItem('sops', it.id)">删除</n-button></div>
          </div>
        </div>
      </n-tab-pane>

      <!-- 连接器 -->
      <n-tab-pane name="connectors" tab="连接器">
        <div class="res-toolbar"><span class="res-title">连接器（{{ catalog.connectors?.length || 0 }}）</span><n-button v-if="isAdmin" size="small" type="primary" @click="openModal('connectors')">+ 新建连接器</n-button></div>
        <div class="card-grid">
          <div v-for="it in (catalog.connectors || [])" :key="it.id" class="res-card tech-card">
            <div class="card-name">{{ it.name }}</div>
            <div class="card-id">{{ it.id }}</div>
            <div class="card-desc">{{ it.description }}</div>
            <div class="card-acts"><n-button v-if="isAdmin" size="tiny" quaternary @click="openModal('connectors', it)">编辑</n-button><n-button v-if="isAdmin" size="tiny" quaternary type="error" @click="delItem('connectors', it.id)">删除</n-button></div>
          </div>
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 编辑弹窗 -->
    <n-modal v-model:show="modalShow" preset="card" :title="modalTitle" style="width:640px;max-width:92vw">
      <n-form label-placement="left" :label-width="80" size="small">
        <n-form-item v-if="modalType !== 'skills' && !editing?.id" label="ID"><n-input v-model:value="modalForm.id" placeholder="唯一标识，如 my-skill" /></n-form-item>
        <n-form-item v-if="modalType !== 'skills'" label="名称"><n-input v-model:value="modalForm.name" placeholder="显示名称" /></n-form-item>
        <n-form-item v-if="modalType !== 'skills'" label="描述"><n-input v-model:value="modalForm.description" type="textarea" :rows="2" /></n-form-item>
        <n-form-item v-if="modalType === 'kbs'" label="RAGFlow Dataset">
          <n-select v-model:value="modalForm.ragflow_dataset_id" :options="ragflowOptions" clearable filterable placeholder="选择或留空使用全局 RAGFLOW_DATASET_IDS" />
        </n-form-item>
        <n-form-item v-if="modalType === 'skills'" label="技能文件">
          <n-upload
            :default-upload="false"
            accept=".zip"
            :max="1"
            @change="onSkillFileChange"
          >
            <n-button>选择 zip 文件</n-button>
          </n-upload>
          <template #extra>
            上传包含 SKILL.md 的 zip 压缩包（支持 scripts/ 等附属目录），
            id/名称/描述自动从 SKILL.md frontmatter 读取，同名技能自动覆盖更新
          </template>
        </n-form-item>
        <n-form-item v-if="modalType === 'skills' && skillFile" label=" ">
          <n-alert type="info" :title="'已选择：' + (skillFile.name || '')" style="width:100%">
            保存后将自动解析 SKILL.md 中的 name/description 并注册技能
          </n-alert>
        </n-form-item>
        <n-form-item v-if="modalType === 'sops'" label="内容"><n-input v-model:value="modalForm.content" type="textarea" :rows="8" /></n-form-item>
        <n-form-item v-if="modalType === 'connectors'" label="配置 JSON"><n-input v-model:value="modalForm.config" type="textarea" :rows="6" placeholder='{"transport":"stdio","command":"...","args":[...]}' /></n-form-item>

      </n-form>
      <template #footer>
        <n-space>
          <n-button @click="modalShow = false">取消</n-button>
          <n-button type="primary" @click="saveItem">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 查看技能详情弹窗 -->
    <n-modal v-model:show="viewSkillModalShow" preset="card" title="技能内容" style="width:720px;max-width:92vw">
      <div class="skill-detail">
        <div class="skill-detail-name">{{ viewSkill?.name }}</div>
        <div class="skill-detail-id">ID: {{ viewSkill?.id }}</div>
        <div class="skill-detail-desc">{{ viewSkill?.description }}</div>
        <div class="skill-detail-label">SKILL.md 内容</div>
        <pre class="skill-detail-content">{{ skillContent || '（暂无内容，技能文件可能不存在）' }}</pre>
      </div>
      <template #footer>
        <n-space>
          <n-button @click="viewSkillModalShow = false">关闭</n-button>
          <n-button v-if="isAdmin" type="primary" @click="openModal('skills', viewSkill); viewSkillModalShow = false">编辑</n-button>
        </n-space>
      </template>
    </n-modal>


  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useMessage, useDialog } from 'naive-ui'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'

defineOptions({ name: 'ResourcesView' })

const message = useMessage()
const dialog = useDialog()
const auth = useAuthStore()
const isAdmin = computed(() => auth.isAdmin)

const catalog = ref({})
const ragflowDatasets = ref([])
const activeTab = ref('skills')
const sopExpanded = reactive({})

const modalShow = ref(false)
const viewSkillModalShow = ref(false)
const modalType = ref('')
const editing = ref(null)
const viewSkill = ref(null)
const skillContent = ref('')
const skillFile = ref(null)
const modalForm = reactive({ id: '', name: '', description: '', ragflow_dataset_id: '', content: '', config: '', title: '', keywords: '' })
const ragflowOptions = computed(() => (ragflowDatasets.value || []).map(d => ({
  label: `${d.name}（${d.id}）`,
  value: d.id,
  document_count: d.document_count,
})))

const modalTitleMap = {
  skills: '技能', tools: '工具', sops: 'SOP', connectors: '连接器', kbs: '知识库',
}
const modalTitle = ref('')

function onSkillFileChange({ file }) {
  skillFile.value = file.file || file
}

function toggleSopContent(id) { sopExpanded[id] = !sopExpanded[id] }


async function viewSkillContent(skill) {
  viewSkill.value = skill
  skillContent.value = ''
  try {
    const { data } = await api.get(`/admin/skills/${skill.id}/content`)
    skillContent.value = data.content || '（技能文件无内容）'
  } catch {
    skillContent.value = '（无法读取技能内容）'
  }
  viewSkillModalShow.value = true
}

async function loadCatalog() {
  try {
    const { data } = await api.get(isAdmin.value ? '/admin/catalog' : '/catalog')
    catalog.value = data
  } catch {}
}

async function loadRagflowDatasets() {
  if (!auth.isAdmin) return
  try {
    const { data } = await api.get('/admin/ragflow/datasets')
    ragflowDatasets.value = data.datasets || []
  } catch {
    ragflowDatasets.value = []
  }
}


async function openModal(type, item = null) {
  modalType.value = type
  editing.value = item
  modalTitle.value = (item ? '编辑' : '新建') + modalTitleMap[type]
  Object.keys(modalForm).forEach(k => modalForm[k] = '')
  skillFile.value = null
  if (item) {
    modalForm.id = item.id || ''
    modalForm.name = item.name || ''
    modalForm.description = item.description || ''
    modalForm.ragflow_dataset_id = item.ragflow_dataset_id || ''
    modalForm.content = item.content || ''
    // 连接器列表不含 config，编辑时需单独拉详情回填
    if (type === 'connectors') { fillConnectorConfig(item); } else {
      modalForm.config = typeof item.config === 'string' ? item.config : JSON.stringify(item.config, null, 2)
    }
    modalForm.title = item.title || ''
    modalForm.keywords = Array.isArray(item.keywords) ? item.keywords.join(', ') : (item.keywords || '')
  }
  // 技能编辑时先加载现有 SKILL.md 内容，便于直接改内容保存
  if (type === 'skills' && item) {
    try {
      const { data } = await api.get(`/admin/skills/${item.id}/content`)
      modalForm.content = data.content || ''
    } catch {}
  }
  modalShow.value = true
}

async function fillConnectorConfig(conn) {
  try {
    const { data } = await api.get(`/admin/connectors/${conn.id}`)
    const cfg = data.config
    modalForm.config = typeof cfg === 'string' ? cfg : JSON.stringify(cfg ?? {}, null, 2)
  } catch {
    modalForm.config = ''
  }
}

async function saveItem() {
  const type = modalType.value
  const isEdit = !!editing.value

  // 技能类型：走 zip 上传接口
  if (type === 'skills') {
    if (skillFile.value) {
      const formData = new FormData()
      formData.append('file', skillFile.value.file?.file || skillFile.value)
      try {
        const { data } = await api.post('/admin/skills/upload', formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        if (data.error) { message.error(data.error); return }
        message.success('技能已上传：' + (data.name || data.id))
        modalShow.value = false
        await loadCatalog()
      } catch (e) { message.error('上传失败：' + (e.response?.data?.error || e.message)) }
      return
    }
    // 没选择 zip：编辑自定义技能时直接保存 SKILL.md 内容
    if (isEdit) {
      try {
        const { data } = await api.put(`/admin/skills/${editing.value.id}/content`, { content: modalForm.content })
        if (data.error) { message.error(data.error); return }
        message.success('技能内容已更新')
        modalShow.value = false
        await loadCatalog()
      } catch (e) { message.error('保存失败：' + (e.response?.data?.error || e.message)) }
      return
    }
    message.warning('新建技能请选择 zip 文件')
    return
  }

  const base = type === 'kbs' ? `/admin/knowledge-bases` : `/admin/${type}`
  const payload = { ...modalForm }
  if (type === 'connectors' && payload.config) { try { payload.config = JSON.parse(payload.config) } catch { message.error('配置 JSON 格式错误'); return } }
  try {
    if (isEdit) {
      await api.put(`${base}/${editing.value.id}`, payload)
    } else {
      await api.post(base, payload)
    }
    message.success(isEdit ? '已更新' : '已创建')
    modalShow.value = false
    await loadCatalog()
  } catch (e) { message.error('保存失败：' + (e.response?.data?.error || e.message)) }
}

function delItem(type, id) {
  dialog.warning({
    title: '删除', content: '确认删除？该操作不可恢复。',
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const base = type === 'kbs' ? `/admin/knowledge-bases` : `/admin/${type}`
        await api.delete(`${base}/${id}`)
        message.success('已删除')
        await loadCatalog()
      } catch (e) { message.error('删除失败：' + e.message) }
    },
  })
}

onMounted(() => {
  loadCatalog()
  loadRagflowDatasets()
})
</script>

<style scoped>
.res-page { padding: 24px; height: 100%; overflow-y: auto; }
.res-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.res-title { font-size: 15px; font-weight: 600; color: #0f172a; flex: 1; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.res-card { padding: 14px; }
.card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.card-name { font-size: 14px; font-weight: 600; color: #0f172a; }
.card-id { font-size: 11px; color: #94a3b8; }
.card-desc { font-size: 13px; color: #64748b; margin-top: 6px; line-height: 1.55; }
.card-content { margin-top: 8px; border-top: 1px solid #f1f5f9; padding-top: 8px; }
.content-preview { font-size: 12px; color: #475569; line-height: 1.7; white-space: pre-wrap; max-height: 60px; overflow: hidden; transition: max-height 0.25s ease; }
.content-preview.expanded { max-height: 2000px; }
.expand-btn { font-size: 11px; color: #3b82f6; cursor: pointer; margin-top: 4px; display: inline-block; }
.expand-btn:hover { text-decoration: underline; }
.card-acts { margin-top: 10px; display: flex; gap: 6px; }





/* 技能详情弹窗 */
.skill-detail { padding: 4px 0; }
.skill-detail-name { font-size: 16px; font-weight: 600; color: #0f172a; margin-bottom: 4px; }
.skill-detail-id { font-size: 12px; color: #94a3b8; margin-bottom: 8px; }
.skill-detail-desc { font-size: 13px; color: #64748b; margin-bottom: 16px; line-height: 1.5; }
.skill-detail-label { font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 8px; }
.skill-detail-content { font-size: 13px; color: #0f172a; line-height: 1.7; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; white-space: pre-wrap; word-break: break-word; max-height: 480px; overflow: auto; }

.res-empty { padding: 40px; text-align: center; color: #94a3b8; font-size: 13px; }
</style>
