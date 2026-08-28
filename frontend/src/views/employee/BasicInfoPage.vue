<!-- 员工详情 · 基础信息页：名称/角色/模型/运行后端/人设编辑与删除员工 -->
<template>
  <div class="basic-page">
    <n-form label-placement="left" :label-width="100" size="small" class="basic-form">
      <n-form-item label="员工 ID">
        <n-input :value="employee?.id || ''" readonly />
      </n-form-item>
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
        <n-input v-model:value="form.persona" type="textarea" :rows="8" placeholder="描述该员工的身份、语气与工作原则…" />
      </n-form-item>
    </n-form>
    <div class="actions">
      <n-button type="primary" :loading="saving" @click="save">保存</n-button>
      <n-popconfirm @positive-click="delEmp">
        <template #trigger>
          <n-button type="error" ghost>删除该员工</n-button>
        </template>
        确认删除员工「{{ employee?.name }}」？该操作不可恢复。
      </n-popconfirm>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'BasicInfoPage' })

const props = defineProps({ employee: Object })
const emit = defineEmits(['changed'])

const router = useRouter()
const message = useMessage()

const backendOptions = [
  { label: 'state（默认，标准工具后端）', value: 'state' },
  { label: 'local_shell（数据分析沙箱）', value: 'local_shell' },
]

const form = reactive({ name: '', role: '', model: '', backend: 'state', persona: '' })
const saving = ref(false)

watch(() => props.employee, (e) => {
  if (!e) return
  form.name = e.name || ''; form.role = e.role || ''; form.model = e.model || ''
  form.backend = e.backend || 'state'; form.persona = e.persona || ''
}, { immediate: true })

async function save() {
  if (!form.name.trim()) { message.warning('请填写名称'); return }
  saving.value = true
  try {
    const { data } = await api.put(`/admin/employees/${props.employee.id}`, {
      name: form.name.trim(), role: form.role.trim(), model: form.model.trim(),
      backend: form.backend, persona: form.persona,
    })
    if (data.error) { message.error('保存失败：' + data.error); return }
    message.success('已更新')
    emit('changed')
  } catch (e) {
    message.error('保存出错：' + e.message)
  } finally {
    saving.value = false
  }
}

async function delEmp() {
  try {
    await api.delete(`/admin/employees/${props.employee.id}`)
    message.success('已删除')
    router.push('/app/admin')
  } catch (e) {
    message.error('删除出错：' + e.message)
  }
}
</script>

<style scoped>
.basic-page { max-width: 720px; }
.actions { margin-top: 20px; display: flex; gap: 10px; }
</style>
