<!-- 个人档案：用户自述画像（称呼/职位/职责/偏好），保存后所有数字员工
     对话时默认加载该内容作为「当前用户信息」上下文。入口在右上角用户菜单。 -->
<template>
  <div class="profile-page">
    <div class="page-head">
      <div>
        <div class="page-title">个人档案</div>
        <div class="page-sub">填写的信息会在与所有数字员工对话时自动加载，让员工更了解你</div>
      </div>
    </div>

    <div class="profile-card">
      <div class="section-title">账号信息</div>
      <div class="account-row">
        <div class="account-item">
          <span class="label">用户名</span>
          <span class="value">{{ username }}</span>
        </div>
        <div class="account-item">
          <span class="label">所属部门</span>
          <span class="value">{{ orgName || '未分配（管理员在用户管理中设置）' }}</span>
        </div>
      </div>
    </div>

    <div class="profile-card">
      <div class="section-title">个人画像</div>
      <div class="section-hint">由你自行维护，仅用于数字员工更好地服务你</div>
      <n-form label-placement="top" size="small">
        <n-form-item label="称呼 / 昵称">
          <n-input v-model:value="form.display_name" placeholder="希望数字员工怎么称呼你，如：王工、小张" :maxlength="30" />
        </n-form-item>
        <n-form-item label="职位">
          <n-input v-model:value="form.position" placeholder="如：产品经理、高级后端工程师" :maxlength="60" />
        </n-form-item>
        <n-form-item label="职责背景">
          <n-input v-model:value="form.duties" type="textarea" :rows="4" :maxlength="500" show-count placeholder="你的工作职责、专业领域，帮助员工判断你的专业程度与关注点" />
        </n-form-item>
        <n-form-item label="偏好与沟通风格">
          <n-input v-model:value="form.preferences" type="textarea" :rows="4" :maxlength="500" show-count placeholder="如：回复尽量简洁、直接给结论；技术细节可以展开讲；中文交流" />
        </n-form-item>
      </n-form>
      <div class="actions">
        <n-button type="primary" :loading="saving" @click="save">保存画像</n-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../api.js'

defineOptions({ name: 'ProfileView' })

const message = useMessage()
const username = ref('')
const orgName = ref('')
const saving = ref(false)
const form = reactive({ display_name: '', position: '', duties: '', preferences: '' })

async function load() {
  try {
    const { data } = await api.get('/me/profile')
    if (data.error) { message.error(data.error); return }
    username.value = data.username
    orgName.value = data.org_name || ''
    Object.assign(form, data.profile || {})
  } catch (e) {
    message.error('加载失败：' + e.message)
  }
}

async function save() {
  saving.value = true
  try {
    const { data } = await api.put('/me/profile', { ...form })
    if (data.error) { message.error('保存失败：' + data.error); return }
    message.success('已保存，下次对话即生效')
  } catch (e) {
    message.error('保存出错：' + e.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.profile-page { max-width: 720px; margin: 0 auto; padding: 24px 28px; overflow-y: auto; height: 100%; box-sizing: border-box; }
.page-head { margin-bottom: 20px; }
.page-title { font-size: 18px; font-weight: 600; color: #0f172a; }
.page-sub { font-size: 12px; color: #94a3b8; margin-top: 4px; }
.profile-card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 20px; margin-bottom: 16px; }
.section-title { font-size: 14px; font-weight: 600; color: #334155; }
.section-hint { font-size: 12px; color: #94a3b8; margin: 4px 0 14px; }
.account-row { display: flex; gap: 40px; margin-top: 12px; flex-wrap: wrap; }
.account-item { display: flex; flex-direction: column; gap: 4px; }
.account-item .label { font-size: 12px; color: #94a3b8; }
.account-item .value { font-size: 14px; color: #0f172a; font-weight: 500; }
.actions { margin-top: 8px; }
</style>
