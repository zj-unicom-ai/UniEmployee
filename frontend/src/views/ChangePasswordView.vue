<!-- 修改密码：旧密码验证 + 新密码表单，首次登录强制跳转 -->
<template>
  <div class="cp-page">
    <div class="cp-card tech-card">
      <div class="cp-logo">🔒</div>
      <h2>修改密码</h2>
      <p class="cp-sub">出于安全要求，请设置新密码后继续使用。</p>

      <n-form ref="formRef" :model="form" :rules="rules">
        <n-form-item path="old_password">
          <n-input v-model:value="form.old_password" type="password" show-password-on="click" placeholder="原密码" :input-props="{ autocomplete: 'current-password' }" />
        </n-form-item>
        <n-form-item path="new_password">
          <n-input v-model:value="form.new_password" type="password" show-password-on="click" placeholder="新密码（至少 8 位）" :input-props="{ autocomplete: 'new-password' }" />
        </n-form-item>
        <n-form-item path="confirm">
          <n-input v-model:value="form.confirm" type="password" show-password-on="click" placeholder="确认新密码" :input-props="{ autocomplete: 'new-password' }" @keyup.enter="doChange" />
        </n-form-item>
      </n-form>

      <div v-if="error" class="cp-err">{{ error }}</div>
      <n-button type="primary" block :loading="loading" @click="doChange">确认修改</n-button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ old_password: '', new_password: '', confirm: '' })
const rules = {
  old_password: { required: true, message: '请输入原密码', trigger: 'blur' },
  new_password: { required: true, validator: (r, v) => v && v.length >= 8 ? true : new Error('新密码至少 8 位'), trigger: 'blur' },
  confirm: { required: true, validator: (r, v) => v === form.new_password ? true : new Error('两次输入不一致'), trigger: 'blur' },
}
const error = ref('')
const loading = ref(false)

async function doChange() {
  if (!form.old_password || !form.new_password) { error.value = '请填写完整'; return }
  if (form.new_password.length < 8) { error.value = '新密码至少 8 位'; return }
  if (form.new_password !== form.confirm) { error.value = '两次输入的新密码不一致'; return }
  error.value = ''
  loading.value = true
  try {
    const { data } = await api.post('/auth/change-password', { old_password: form.old_password, new_password: form.new_password })
    if (data.error) { error.value = data.error; return }
    alert('密码修改成功，请重新登录')
    auth.logout()
    router.push({ name: 'login', query: { next: route.query.next || '/app/home' } })
  } catch (e) {
    error.value = e.response?.data?.detail || '修改失败：' + e.message
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.cp-page { display: flex; align-items: center; justify-content: center; min-height: calc(100vh - 56px); padding: 24px; }
.cp-card { width: 400px; padding: 36px 34px; }
.cp-logo { width: 56px; height: 56px; border-radius: 16px; background: linear-gradient(135deg, #f59e0b, #ef4444); display: flex; align-items: center; justify-content: center; font-size: 26px; margin: 0 auto 20px; box-shadow: 0 0 24px rgba(245, 158, 11, 0.3); }
.cp-card h2 { font-size: 20px; font-weight: 600; text-align: center; color: #0f172a; margin-bottom: 6px; }
.cp-sub { font-size: 13px; color: #64748b; text-align: center; margin-bottom: 28px; line-height: 1.7; }
.cp-err { color: #ef4444; font-size: 13px; text-align: center; margin-bottom: 12px; min-height: 20px; }
</style>
