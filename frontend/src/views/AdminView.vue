<!-- 员工管理：员工列表入口（卡片网格 + 新建弹窗）。基础信息与技能/工具/知识库/SOP/连接器
     的配置在员工详情页的各独立子页中完成，本页只做总览与跳转。 -->
<template>
  <div class="emp-list-page">
    <div class="page-head">
      <div>
        <div class="page-title">员工管理</div>
        <div class="page-sub">配置数字员工的基础信息与技能 / 工具 / 知识库 / SOP / 连接器</div>
      </div>
      <n-button type="primary" @click="openNew">+ 新建员工</n-button>
    </div>

    <div v-if="loading" class="page-empty">加载中…</div>
    <div v-else-if="!employees.length" class="page-empty">暂无员工，点击右上角「新建员工」创建</div>
    <div v-else class="cards">
      <div v-for="e in employees" :key="e.id" class="emp-card" @click="goDetail(e.id)">
        <div class="card-top">
          <div class="avatar">{{ (e.name || '?').slice(0, 1) }}</div>
          <div class="card-title">
            <div class="name">{{ e.name }}</div>
            <div class="role">{{ e.role || '未设置角色' }}</div>
          </div>
          <span class="backend-tag">{{ e.backend || 'state' }}</span>
        </div>
        <div class="model">{{ e.model || '未设置模型' }}</div>
        <div class="stats">
          <span>技能 {{ (e.skills || []).length }}</span>
          <span>工具 {{ (e.tools || []).length }}</span>
          <span>知识库 {{ (e.kbs || []).length }}</span>
          <span>SOP {{ (e.sops || []).length }}</span>
          <span>连接器 {{ (e.connectors || []).length }}</span>
        </div>
        <div class="card-enter">配置详情 →</div>
      </div>
    </div>

    <!-- 新建弹窗：只填基础信息，创建后跳详情页继续配置资源 -->
    <n-modal v-model:show="showNew" preset="card" title="新建员工" style="width: 560px">
      <n-form label-placement="left" :label-width="90" size="small">
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
          <n-input v-model:value="form.persona" type="textarea" :rows="4" placeholder="描述该员工的身份、语气与工作原则…" />
        </n-form-item>
      </n-form>
      <template #footer>
        <div class="modal-footer">
          <n-button @click="showNew = false">取消</n-button>
          <n-button type="primary" :loading="creating" @click="createEmp">创建并配置</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api.js'

defineOptions({ name: 'AdminView' })

const router = useRouter()
const message = useMessage()

const backendOptions = [
  { label: 'state（默认，标准工具后端）', value: 'state' },
  { label: 'local_shell（数据分析沙箱）', value: 'local_shell' },
]

const employees = ref([])
const loading = ref(false)
const showNew = ref(false)
const creating = ref(false)
const form = reactive({ name: '', role: '', model: '', backend: 'state', persona: '' })

function openNew() {
  Object.assign(form, { name: '', role: '', model: '', backend: 'state', persona: '' })
  showNew.value = true
}

async function reload() {
  loading.value = true
  try {
    const [empRes, defRes] = await Promise.all([
      api.get('/admin/employees'),
      api.get('/admin/defaults').catch(() => ({ data: {} })),
    ])
    employees.value = (empRes.data || []).filter(x => x && !x.error)
    if (!form.model && defRes.data?.model) form.model = defRes.data.model
  } catch (e) {
    message.error('加载员工列表失败：' + e.message)
  } finally {
    loading.value = false
  }
}

function goDetail(id) {
  router.push(`/app/admin/employee/${id}`)
}

async function createEmp() {
  if (!form.name.trim()) { message.warning('请填写名称'); return }
  creating.value = true
  try {
    const { data } = await api.post('/admin/employees', {
      name: form.name.trim(), role: form.role.trim(), model: form.model.trim(),
      backend: form.backend, persona: form.persona,
    })
    if (data.error) { message.error('创建失败：' + data.error); return }
    message.success('已创建：' + data.id)
    showNew.value = false
    goDetail(data.id)
  } catch (e) {
    message.error('创建出错：' + e.message)
  } finally {
    creating.value = false
  }
}

onMounted(reload)
</script>

<style scoped>
.emp-list-page { height: 100%; overflow-y: auto; padding: 24px 28px; }
.page-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.page-title { font-size: 18px; font-weight: 600; color: #0f172a; }
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 4px; }
.page-empty { color: #94a3b8; font-size: 13px; padding: 60px 0; text-align: center; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
.emp-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 16px; cursor: pointer; transition: all 0.15s; }
.emp-card:hover { border-color: #3b82f6; box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1); }
.card-top { display: flex; align-items: center; gap: 10px; }
.avatar { width: 40px; height: 40px; border-radius: 50%; background: #eff6ff; color: #2563eb; display: flex; align-items: center; justify-content: center; font-size: 17px; font-weight: 600; flex-shrink: 0; }
.card-title { flex: 1; min-width: 0; }
.name { font-size: 15px; font-weight: 600; color: #0f172a; }
.role { font-size: 12px; color: #64748b; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.backend-tag { font-size: 11px; color: #7c3aed; background: #f5f3ff; border-radius: 10px; padding: 2px 8px; flex-shrink: 0; }
.model { font-size: 12px; color: #64748b; margin-top: 10px; font-family: ui-monospace, monospace; }
.stats { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 10px; font-size: 12px; color: #94a3b8; }
.card-enter { font-size: 12px; color: #3b82f6; margin-top: 12px; opacity: 0; transition: opacity 0.15s; }
.emp-card:hover .card-enter { opacity: 1; }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; }
</style>
