<template>
  <div class="detail-page">
    <!-- 导航（与 LandingView 一致） -->
    <nav class="nav" :class="{ scrolled: navScrolled }">
      <div class="nav-inner">
        <a href="/" class="nav-logo">UniEmployee</a>
        <div class="nav-links">
          <a href="/#capabilities">能力</a>
          <a href="/#how">工作方式</a>
          <a href="/#matrix">岗位</a>
          <a href="/cases">案例</a>
          <a class="active">详情</a>
        </div>
      </div>
    </nav>

    <div class="detail-content">
      <div class="detail-back" @click="router.push({name:'cases'})">← 返回案例列表</div>
      <div v-if="!emp" class="empty-hint">员工不存在</div>
      <div v-else>
        <div class="detail-header">
          <div class="detail-avatar" :style="{ background: empGradient(emp.id) }">{{ (emp.name || emp.id).charAt(0) }}</div>
          <div>
            <div class="detail-name">{{ emp.name }}</div>
            <div class="detail-role">{{ emp.role }}</div>
          </div>
        </div>
        <div class="detail-section">
          <h3>技能配置</h3>
          <div class="detail-tags">
            <span class="detail-tag" v-for="sk in (emp.skills || [])" :key="sk">{{ sk }}</span>
            <span v-if="!emp.skills?.length" class="text-muted">暂未配置</span>
          </div>
        </div>
        <div class="detail-section">
          <h3>工具列表</h3>
          <div class="detail-tags">
            <span class="detail-tag tool-tag" v-for="t in (emp.tools || [])" :key="t">{{ t }}</span>
            <span v-if="!emp.tools?.length" class="text-muted">暂未配置</span>
          </div>
        </div>
        <div class="detail-section">
          <h3>说明</h3>
          <p class="text-muted">详细的能力介绍和典型案例正在完善中，敬请期待</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '../api.js'

defineOptions({ name: 'CaseDetailView' })
const router = useRouter()
const route = useRoute()
const navScrolled = ref(false)
const emp = ref(null)

const gradients = [
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#8b5cf6,#ec4899)',
  'linear-gradient(135deg,#10b981,#06b6d4)',
  'linear-gradient(135deg,#f59e0b,#ef4444)',
]
function empGradient(id) { return gradients[(id?.charCodeAt(0) || 0) % gradients.length] }

function onScroll() { navScrolled.value = window.scrollY > 40 }

onMounted(async () => {
  window.addEventListener('scroll', onScroll, { passive: true })
  try {
    const { data } = await api.get(`/public/employees/${route.params.id}`)
    emp.value = data.error ? null : data
  } catch { emp.value = null }
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.detail-page { min-height: 100vh; background: #08090C; color: #F5F5F7; }
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
.detail-content { max-width: 800px; margin: 0 auto; padding: 32px 32px 64px; }
.detail-back { font-size: 13px; color: #818CF8; cursor: pointer; margin-bottom: 24px; display: inline-block; }
.detail-back:hover { text-decoration: underline; }
.detail-header { display: flex; align-items: center; gap: 20px; margin-bottom: 32px; }
.detail-avatar { width: 64px; height: 64px; border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 26px; font-weight: 700; color: #fff; flex-shrink: 0; }
.detail-name { font-size: 22px; font-weight: 400; color: #F5F5F7; }
.detail-role { font-size: 14px; color: #9CA3AF; margin-top: 4px; font-weight: 300; }
.detail-section { margin-bottom: 28px; }
.detail-section h3 { font-size: 15px; font-weight: 500; color: #D1D5DB; margin-bottom: 12px; }
.detail-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.detail-tag { font-size: 12px; background: rgba(129,140,248,0.1); color: #818CF8; padding: 4px 10px; border-radius: 8px; }
.tool-tag { background: rgba(16,185,129,0.1); color: #34D399; }
.text-muted { font-size: 13px; color: #5C5F66; font-weight: 300; }
.empty-hint { padding: 40px; text-align: center; color: #5C5F66; font-size: 14px; font-weight: 300; }
</style>
