<!-- 平台首页：欢迎横幅、统计卡片、快捷入口、数字员工列表 -->
<template>
  <div class="home-page">
    <!-- 顶部欢迎横幅：渐变主色 + 装饰光斑 -->
    <div class="hero-section">
      <div class="hero-deco hero-deco-1"></div>
      <div class="hero-deco hero-deco-2"></div>
      <div class="hero-content">
        <div class="hero-badge">
          <span class="hero-badge-dot"></span>
          UniEmployee · 数字员工平台
        </div>
        <h1 class="hero-title">
          欢迎回来，<span class="hero-name">{{ auth.username }}</span>
        </h1>
        <p class="hero-sub">让 AI 成为你的数字劳动力 — 配置人设、技能、工具与知识库，开启企业级数字员工协作</p>
        <div class="hero-actions">
          <n-button type="primary" @click="router.push({name:'chat'})" class="start-btn">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:6px"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
            开始对话
          </n-button>
        </div>
      </div>
    </div>

    <!-- 统计卡片：左侧色条 + 大数字 -->
    <div class="stats-grid">
      <div v-for="s in basicStats" :key="s.label" class="stat-card card">
        <div class="stat-bar" :style="{ background: s.accent }"></div>
        <div class="stat-icon" :style="{ background: s.color }">{{ s.icon }}</div>
        <div class="stat-body">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <!-- Token 统计栏 -->
    <div class="token-bar" v-if="tokenStats.length">
      <div v-for="s in tokenStats" :key="s.label" class="token-item">
        <span class="token-label">{{ s.icon }} {{ s.label }}</span>
        <span class="token-value">{{ s.value }}</span>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">快捷入口</h2>
      </div>
      <div class="quick-grid">
        <div class="quick-card card card-hover" @click="router.push({name:'chat'})">
          <div class="quick-icon" style="background:linear-gradient(135deg,#3b82f6,#2563eb)">💬</div>
          <div class="quick-info">
            <div class="quick-label">对话工作台</div>
            <div class="quick-desc">与你的数字员工交流</div>
          </div>
        </div>
        <div class="quick-card card card-hover" @click="router.push({name:'history'})">
          <div class="quick-icon" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9)">🕘</div>
          <div class="quick-info">
            <div class="quick-label">会话历史</div>
            <div class="quick-desc">查看过往对话记录</div>
          </div>
        </div>
        <div v-if="auth.isAdmin" class="quick-card card card-hover" @click="router.push({name:'admin'})">
          <div class="quick-icon" style="background:linear-gradient(135deg,#10b981,#047857)">👥</div>
          <div class="quick-info">
            <div class="quick-label">员工管理</div>
            <div class="quick-desc">配置数字员工</div>
          </div>
        </div>
        <div class="quick-card card card-hover" @click="router.push({name:'resources'})">
          <div class="quick-icon" style="background:linear-gradient(135deg,#f59e0b,#b45309)">📚</div>
          <div class="quick-info">
            <div class="quick-label">资源中心</div>
            <div class="quick-desc">管理技能与知识库</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 数字员工 -->
    <div class="section">
      <div class="section-header">
        <h2 class="section-title">数字员工</h2>
        <n-button text type="primary" @click="router.push({name:'chat'})" class="section-more">查看全部 →</n-button>
      </div>
      <div class="emp-grid">
        <div
          v-for="emp in employees"
          :key="emp.id"
          class="emp-card card card-hover"
          @click="startChat(emp)"
        >
          <div class="emp-avatar" :style="{ background: empGradient(emp.id) }">
            {{ emp.name?.charAt(0) || '?' }}
          </div>
          <div class="emp-info">
            <div class="emp-name">{{ emp.name }}</div>
            <div class="emp-role">{{ emp.role }}</div>
            <div class="emp-status">
              <span class="status-dot"></span>
              在线
            </div>
          </div>
        </div>
        <div v-if="!employees.length && !loading" class="empty-hint">
          暂无已分配的数字员工
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'

defineOptions({ name: 'HomeView' })

const router = useRouter()
const auth = useAuthStore()
const employees = ref([])
const loading = ref(true)

const basicStats = reactive([
  { icon: '👥', label: '数字员工', value: '—', color: 'rgba(59,130,246,0.12)', accent: 'linear-gradient(180deg,#3b82f6,#06b6d4)' },
  { icon: '⚡', label: '技能', value: '—', color: 'rgba(16,185,129,0.12)', accent: 'linear-gradient(180deg,#10b981,#06b6d4)' },
  { icon: '🔧', label: '工具', value: '—', color: 'rgba(139,92,246,0.12)', accent: 'linear-gradient(180deg,#8b5cf6,#ec4899)' },
  { icon: '💬', label: '会话', value: '—', color: 'rgba(245,158,11,0.12)', accent: 'linear-gradient(180deg,#f59e0b,#ef4444)' },
])

const tokenStats = reactive([
  { icon: '🔤', label: '累计 Token 消耗', value: '—' },
  { icon: '📊', label: '今日 Token 消耗', value: '—' },
])

const gradients = [
  'linear-gradient(135deg,#3b82f6,#06b6d4)',
  'linear-gradient(135deg,#8b5cf6,#ec4899)',
  'linear-gradient(135deg,#10b981,#06b6d4)',
  'linear-gradient(135deg,#f59e0b,#ef4444)',
]
function empGradient(id) {
  return gradients[(id?.charCodeAt(0) || 0) % gradients.length]
}

async function loadData() {
  try {
    const [catalogRes, empRes, convRes, tokenRes] = await Promise.all([
      api.get('/catalog'),
      api.get('/employees'),
      api.get('/conversations', { params: { limit: 0 } }),
      api.get('/traces/stats'),
    ])
    const cat = catalogRes.data
    const emps = empRes.data || []
    employees.value = Array.isArray(emps)
      ? emps.map(e => ({ id: e.id, ...e }))
      : []
    basicStats[0].value = employees.value.length
    basicStats[1].value = cat.skills?.length || 0
    basicStats[2].value = cat.tools?.length || 0
    const convData = convRes.data
    basicStats[3].value = Array.isArray(convData) ? convData.length : (convData?.total ?? 0)
    const tokens = tokenRes.data || {}
    tokenStats[0].value = tokens.total_tokens ? (tokens.total_tokens / 1000).toFixed(0) + 'k' : '—'
    tokenStats[1].value = tokens.today_tokens ? (tokens.today_tokens / 1000).toFixed(0) + 'k' : '—'
  } catch {} finally { loading.value = false }
}

function startChat(empId) {
  router.push({ name: 'chat', query: { emp: empId } })
}

onMounted(loadData)
</script>

<style scoped>
.home-page {
  min-width: 1000px;
  padding: 32px 40px 64px;
}

/* 欢迎横幅：渐变主背景 + 装饰光斑 */
.hero-section {
  position: relative;
  overflow: hidden;
  background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 45%, #06b6d4 100%);
  border-radius: 18px;
  padding: 36px 40px;
  margin-bottom: 28px;
  box-shadow: 0 12px 40px rgba(30,58,138,0.25);
}
.hero-deco {
  position: absolute;
  border-radius: 50%;
  filter: blur(48px);
  pointer-events: none;
}
.hero-deco-1 {
  width: 280px; height: 280px;
  top: -80px; right: -40px;
  background: rgba(255,255,255,0.18);
}
.hero-deco-2 {
  width: 220px; height: 220px;
  bottom: -100px; left: 30%;
  background: rgba(6,182,212,0.35);
}
.hero-content { position: relative; z-index: 1; }
.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border: 1px solid rgba(255,255,255,0.25);
  background: rgba(255,255,255,0.12);
  border-radius: 999px;
  color: rgba(255,255,255,0.92);
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 14px;
  backdrop-filter: blur(6px);
}
.hero-badge-dot {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #4ade80;
  box-shadow: 0 0 8px #4ade80;
  animation: pulse 2s ease-in-out infinite;
}
.hero-title {
  font-size: 30px;
  font-weight: 700;
  color: #fff;
  margin-bottom: 10px;
  line-height: 1.2;
  letter-spacing: -0.01em;
}
.hero-name {
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero-sub {
  font-size: 14px;
  color: rgba(255,255,255,0.85);
  line-height: 1.6;
  margin-bottom: 20px;
  max-width: 580px;
}
.start-btn {
  height: 42px;
  padding: 0 24px !important;
  border-radius: 10px !important;
  font-weight: 600;
  font-size: 14px;
  background: rgba(255,255,255,0.95) !important;
  color: #1e3a8a !important;
  border: none !important;
  box-shadow: 0 4px 14px rgba(0,0,0,0.15);
}
.start-btn:hover {
  background: #fff !important;
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(0,0,0,0.2);
}

/* 统计卡片：左侧色条 + 大数字 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 18px;
}
.stat-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 18px 18px 22px;
  overflow: hidden;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(15,23,42,0.08);
}
.stat-bar {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
  border-radius: 0 4px 4px 0;
}
.stat-icon {
  width: 46px;
  height: 46px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
}
.stat-body { flex: 1; min-width: 0; }
.stat-value {
  font-size: 26px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1;
  letter-spacing: -0.01em;
}
.stat-label {
  font-size: 13px;
  color: #64748b;
  margin-top: 4px;
}

/* Token 统计栏 */
.token-bar {
  display: flex;
  gap: 14px;
  margin-bottom: 32px;
}
.token-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}
.token-item:hover {
  border-color: #cbd5e1;
  box-shadow: 0 4px 14px rgba(15,23,42,0.05);
}
.token-label { font-size: 13px; color: #64748b; }
.token-value { font-size: 18px; font-weight: 700; color: #0f172a; }

/* 分节 */
.section { margin-bottom: 32px; }
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.section-title {
  font-size: 17px;
  font-weight: 700;
  color: #0f172a;
  position: relative;
  padding-left: 12px;
}
.section-title::before {
  content: '';
  position: absolute;
  left: 0; top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 16px;
  border-radius: 2px;
  background: linear-gradient(180deg, #3b82f6, #06b6d4);
}
.section-more { font-size: 13px; }

/* 快捷入口 */
.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.quick-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.quick-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 28px rgba(15,23,42,0.08);
}
.quick-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  flex-shrink: 0;
  box-shadow: 0 6px 16px rgba(0,0,0,0.10);
}
.quick-label {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}
.quick-desc {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
}

/* 员工网格 */
.emp-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
}
.emp-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.emp-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 12px 30px rgba(15,23,42,0.10);
  border-color: #cbd5e1;
}
.emp-avatar {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 8px 20px rgba(0,0,0,0.12);
}
.emp-name {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}
.emp-role {
  font-size: 13px;
  color: #64748b;
  margin-top: 2px;
}
.emp-status {
  font-size: 12px;
  color: #10b981;
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 0 rgba(16,185,129,0.5);
  animation: pulse-dot 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
@keyframes pulse-dot {
  0% { box-shadow: 0 0 0 0 rgba(16,185,129,0.5); }
  70% { box-shadow: 0 0 0 6px rgba(16,185,129,0); }
  100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); }
}

/* 空态 */
.empty-hint {
  grid-column: 1 / -1;
  padding: 40px;
  text-align: center;
  color: #94a3b8;
  font-size: 14px;
  background: #fff;
  border: 1px dashed #e2e8f0;
  border-radius: 12px;
}
</style>
