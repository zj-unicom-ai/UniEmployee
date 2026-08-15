<!-- 登录页：用户名密码表单，成功跳转后台首页，需改密时跳改密页 -->
<template>
  <div class="login-page">
    <!-- 装饰性背景 -->
    <div class="login-bg">
      <div class="glow glow-1"></div>
      <div class="glow glow-2"></div>
      <div class="grid-pattern"></div>
    </div>

    <div class="login-card">
      <div class="brand-section">
        <div class="logo-mark">U</div>
        <h1 class="brand gradient-text">UniEmployee</h1>
        <p class="sub">企业级数字员工平台</p>
      </div>

      <n-form ref="formRef" :model="form" :rules="rules" @keyup.enter="doLogin" class="login-form">
        <n-form-item path="username">
          <n-input
            v-model:value="form.username"
            placeholder="用户名"
            size="large"
            :input-props="{ autocomplete: 'username' }"
            clearable
          />
        </n-form-item>
        <n-form-item path="password">
          <n-input
            v-model:value="form.password"
            type="password"
            show-password-on="click"
            placeholder="密码"
            size="large"
            :input-props="{ autocomplete: 'current-password' }"
          />
        </n-form-item>
      </n-form>

      <div v-if="error" class="error-msg">{{ error }}</div>

      <n-button
        type="primary"
        size="large"
        block
        :loading="loading"
        @click="doLogin"
        class="login-btn"
      >
        登 录
      </n-button>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const form = reactive({ username: '', password: '' })
const rules = {
  username: { required: true, message: '请输入用户名', trigger: 'blur' },
  password: { required: true, message: '请输入密码', trigger: 'blur' },
}
const error = ref('')
const loading = ref(false)

if (auth.isLoggedIn) {
  router.replace(route.query.next || { name: 'home' })
}

async function doLogin() {
  if (!form.username || !form.password) { error.value = '请输入用户名和密码'; return }
  error.value = ''
  loading.value = true
  try {
    const data = await auth.login(form.username, form.password)
    if (data.must_change_password) {
      router.push({ name: 'change-password', query: { next: route.query.next || '/app/home' } })
    } else {
      router.push(route.query.next || { name: 'home' })
    }
  } catch (e) {
    const resp = e.response?.data
    error.value = resp?.detail || resp?.error || `登录失败 (${e.response?.status || '网络错误'})`
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: #0f172a;
}

/* 背景装饰 */
.login-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
}
.glow-1 {
  width: 700px; height: 700px;
  top: -200px; left: 50%;
  transform: translateX(-50%);
  background: rgba(59,130,246,0.10);
}
.glow-2 {
  width: 500px; height: 500px;
  bottom: -200px; right: -100px;
  background: rgba(6,182,212,0.06);
}
.grid-pattern {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}

/* 登录卡片 */
.login-card {
  position: relative;
  width: 400px;
  padding: 48px 40px 36px;
  background: #1e293b;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 24px;
  box-shadow: 0 32px 80px rgba(0,0,0,0.4);
  z-index: 1;
}

.brand-section {
  text-align: center;
  margin-bottom: 36px;
}
.logo-mark {
  width: 56px; height: 56px;
  border-radius: 16px;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  margin: 0 auto 20px;
  box-shadow: 0 0 32px rgba(59,130,246,0.3);
}
.brand {
  font-size: 26px;
  font-weight: 700;
  margin-bottom: 6px;
}
.sub {
  font-size: 14px;
  color: #64748b;
  line-height: 1.5;
}

.login-form {
  margin-bottom: 4px;
}

.error-msg {
  color: #f87171;
  font-size: 13px;
  text-align: center;
  margin-bottom: 12px;
  min-height: 20px;
}

.login-btn {
  margin-top: 8px;
  font-size: 15px;
  font-weight: 600;
  height: 46px;
  border-radius: 12px;
}
.login-btn:hover {
  box-shadow: 0 0 24px rgba(59,130,246,0.35);
}

.tip {
  font-size: 12px;
  color: #475569;
  text-align: center;
  margin-top: 24px;
}
</style>
