<!-- 案例列表页：展示所有数字员工列表，点击进入详情（独立页面，无需登录） -->
<template>
  <div class="cases-page">
    <!-- 导航（与 LandingView 一致） -->
    <nav class="nav" :class="{ scrolled: navScrolled }">
      <div class="nav-inner">
        <a href="/" class="nav-logo">UniEmployee</a>
        <div class="nav-links">
          <a href="/#capabilities">能力</a>
          <a href="/#how">工作方式</a>
          <a href="/#matrix">岗位</a>
          <a class="active">案例</a>
        </div>
      </div>
    </nav>

    <div class="cases-content">
      <h1 class="page-title">数字员工案例</h1>
      <p class="page-desc">了解各岗位数字员工的能力与应用场景</p>

      <div class="case-grid">
        <div v-for="emp in employees" :key="emp.id" class="case-card card-hover" @click="goDetail(emp.id)">
          <div class="case-avatar" :style="{ background: empGradient(emp.id) }">{{ (emp.name || emp.id).charAt(0) }}</div>
          <div class="case-info">
            <div class="case-name">{{ emp.name }}</div>
            <div class="case-role">{{ emp.role }}</div>
            <div class="case-tags">
              <span class="case-tag" v-for="sk in (emp.skills || []).slice(0, 3)" :key="sk">{{ sk }}</span>
            </div>
          </div>
          <div class="case-arrow">→</div>
        </div>
        <div v-if="!employees.length && !loading" class="empty-hint">暂无案例数据</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api.js'

defineOptions({ name: 'CasesView' })
const router = useRouter()
const navScrolled = ref(false)
const employees = ref([])
const loading = ref(true)

const gradients = [
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#8b5cf6,#ec4899)',
  'linear-gradient(135deg,#10b981,#06b6d4)',
  'linear-gradient(135deg,#f59e0b,#ef4444)',
]
function empGradient(id) { return gradients[(id?.charCodeAt(0) || 0) % gradients.length] }

function goDetail(id) { router.push({ name: 'case-detail', params: { id } }) }

function onScroll() { navScrolled.value = window.scrollY > 40 }

onMounted(async () => {
  window.addEventListener('scroll', onScroll, { passive: true })
  try {
    const { data } = await api.get('/public/employees')
    employees.value = data || []
  } catch {} finally { loading.value = false }
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.cases-page { min-height: 100vh; background: var(--bg, #08090C); color: var(--text-1, #F5F5F7); }
.nav {
  position: fixed; top: 0; left: 0; right: 0; z-index: 100; height: 64px;
  display: flex; align-items: center;
  background: transparent; transition: all 0.3s;
}
.nav.scrolled { background: rgba(8,9,12,.72); backdrop-filter: blur(20px) saturate(180%); border-bottom: 1px solid rgba(255,255,255,0.07); }
.nav-inner { max-width: 1200px; margin: 0 auto; padding: 0 32px; width: 100%; display: flex; align-items: center; justify-content: space-between; }
.nav-logo {
  font-size: 1.1rem;
  font-weight: 450;
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, #5EEAD4, #818CF8, #FBB969);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-decoration: none;
}
.nav-links { display: flex; gap: 32px; }
.nav-links a { font-size: 14px; color: #9CA3AF; text-decoration: none; cursor: pointer; }
.nav-links a:hover, .nav-links a.active { color: #F5F5F7; }
.cases-content { max-width: 1200px; margin: 0 auto; padding: 60px 32px 64px; }
.page-title { font-size: 28px; font-weight: 300; color: #F5F5F7; margin-bottom: 8px; }
.page-desc { font-size: 15px; color: #9CA3AF; margin-bottom: 40px; font-weight: 300; }
.case-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
.case-card {
  display: flex; align-items: center; gap: 18px;
  padding: 20px 24px; background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.07);
  border-radius: 14px; cursor: pointer; transition: all 0.25s;
}
.case-card:hover { border-color: rgba(255,255,255,0.13); background: rgba(255,255,255,0.045); transform: translateY(-2px); }
.case-avatar { width: 56px; height: 56px; border-radius: 14px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: 700; color: #fff; flex-shrink: 0; }
.case-info { flex: 1; min-width: 0; }
.case-name { font-size: 16px; font-weight: 450; color: #F5F5F7; }
.case-role { font-size: 13px; color: #9CA3AF; margin-top: 2px; }
.case-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.case-tag { font-size: 11px; background: rgba(255,255,255,0.045); color: #9CA3AF; padding: 3px 10px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.07); }
.case-arrow { font-size: 18px; color: #5C5F66; flex-shrink: 0; }
.empty-hint { padding: 40px; text-align: center; color: #5C5F66; font-size: 14px; font-weight: 300; }
</style>
