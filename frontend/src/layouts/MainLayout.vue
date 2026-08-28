<!-- 管理后台布局：左侧导航侧栏 + 顶部栏 + 内容区（含 keep-alive 缓存） -->
<template>
  <n-layout has-sider class="main-layout">
    <!-- 侧边栏 -->
    <n-layout-sider
      bordered
      :width="240"
      :collapsed-width="64"
      collapse-mode="width"
      v-model:collapsed="collapsed"
    >
      <div class="logo-area" @click="router.push({ name: 'home' })">
        <div class="logo-mark">U</div>
        <transition name="fade">
          <div v-if="!collapsed" class="logo-text">
            <span class="brand">UniEmployee</span>
            <span class="brand-sub">数字员工平台</span>
          </div>
        </transition>
      </div>

      <div class="nav-section">
        <n-menu
          :collapsed="collapsed"
          :collapsed-width="64"
          :collapsed-icon-size="22"
          :options="menuOptions"
          :value="activeKey"
          @update:value="onMenuSelect"
        />
      </div>

      <div class="nav-section bottom-section">
        <n-menu
          :collapsed="collapsed"
          :collapsed-width="64"
          :collapsed-icon-size="22"
          :options="bottomNavOptions"
          :value="activeKey"
          @update:value="onMenuSelect"
        />
      </div>
    </n-layout-sider>

    <!-- 主区域 -->
    <n-layout>
      <!-- 顶栏 -->
      <n-layout-header bordered class="app-header">
        <div class="header-left">
          <n-button text @click="collapsed = !collapsed" class="collapse-btn">
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M4 5h12M4 10h8M4 15h12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </n-button>
          <span class="page-title">{{ currentPageTitle }}</span>
        </div>
        <div class="header-right">
          <n-tag v-if="auth.isAdmin" type="info" size="small" round :bordered="false" class="role-tag">管理员</n-tag>
          <n-dropdown :options="userMenuOptions" @select="onUserMenuSelect">
            <n-button quaternary size="small" class="user-btn">
              <div class="user-avatar">{{ auth.username.charAt(0).toUpperCase() }}</div>
              <span class="user-name">{{ auth.username }}</span>
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style="margin-left:4px;opacity:0.5"><path d="M3 5l3 3 3-3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </n-button>
          </n-dropdown>
        </div>
      </n-layout-header>

      <!-- 内容 -->
      <n-layout-content class="app-content">
        <router-view v-slot="{ Component }">
          <transition name="content-fade" mode="out-in">
            <component :is="Component" :key="route.name" />
          </transition>
        </router-view>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup>
import { ref, computed, h } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { NIcon } from 'naive-ui'
import { useAuthStore } from '../stores/auth.js'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const collapsed = ref(false)

function iconEl(svg) {
  return () => h(NIcon, null, {
    default: () => h('svg', { width: '18', height: '18', viewBox: '0 0 24 24', fill: 'none', innerHTML: svg })
  })
}

const mainNavOptions = [
  { label: '平台首页', key: 'home', icon: iconEl('<path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '对话工作台', key: 'chat', icon: iconEl('<path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: 'IM 频道', key: 'im', icon: iconEl('<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '会话历史', key: 'history', icon: iconEl('<path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '资源中心', key: 'resources', icon: iconEl('<path d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '个人中心', key: 'profile', icon: iconEl('<path d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
]

const adminOnlyNavOptions = [
  { label: '业务本体', key: 'ontology', icon: iconEl('<path d="M20 6a3 3 0 11-4 2.83L14.35 10a3 3 0 010 3.77L15 14.4A3 3 0 1121 13a3 3 0 01-3 3 2.87 2.87 0 01-1.23-.28L15.2 17.6a3 3 0 11-1.7 1.1 2.9 2.9 0 01-.13-.43L12.4 19a3 3 0 11-1.8-2.4 2.8 2.8 0 01.1-.26L8.83 15A3 3 0 115 12a3 3 0 012-2.8l-.57-1.6a3 3 0 111.4-1L15.2 7.4a2.9 2.9 0 01.28-1.2L14 4.73A3 3 0 1120 6z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '员工管理', key: 'admin', icon: iconEl('<path d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '用户管理', key: 'users', icon: iconEl('<path d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
  { label: '运行评估', key: 'evaluation', icon: iconEl('<path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
]

const bottomNavOptions = [
  { label: '返回首页', key: 'landing', icon: iconEl('<path d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>') },
]

const pageTitleMap = {
  home: '平台首页', chat: '对话工作台', history: '会话历史',
  trace: '执行过程', resources: '资源中心',
  admin: '员工管理', users: '用户管理', 'change-password': '修改密码',
  im: 'IM 频道', ontology: '业务本体', cases: '案例', 'case-detail': '案例详情',
  evaluation: '运行评估', profile: '个人中心',
}
const currentPageTitle = computed(() => pageTitleMap[route.name] || 'UniEmployee')

const activeKey = computed(() => {
  const n = route.name
  if (n === 'change-password') return undefined
  return n
})

const menuOptions = computed(() => {
  const items = [...mainNavOptions]
  if (auth.isAdmin) {
    // 员工管理插在资源中心后面（index 3）
    items.splice(3, 0, ...adminOnlyNavOptions)
  }
  return items
})

function onMenuSelect(key) {
  if (key === 'landing') {
    router.push({ name: 'landing' })
  } else if (key !== 'change-password') {
    router.push({ name: key })
  } else {
    router.push({ name: 'change-password' })
  }
}

const userMenuOptions = [
  { label: '个人中心', key: 'profile' },
  { label: '修改密码', key: 'change-password' },
  { type: 'divider', key: 'd1' },
  { label: '退出登录', key: 'logout' },
]

function onUserMenuSelect(key) {
  if (key === 'logout') {
    auth.logout()
    router.push({ name: 'login' })
  } else if (key === 'change-password') {
    router.push({ name: 'change-password' })
  } else if (key === 'profile') {
    router.push({ name: 'profile' })
  }
}
</script>

<style scoped>
.main-layout {
  height: 100vh;
}

/* 侧边栏 */
.logo-area {
  height: 64px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 20px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.logo-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #3b82f6, #06b6d4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  box-shadow: 0 0 20px rgba(59,130,246,0.25);
}
.logo-text { overflow: hidden; }
.brand {
  font-size: 15px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
}
.brand-sub {
  font-size: 11px;
  color: #64748b;
  white-space: nowrap;
}

.nav-section { padding: 8px; }
.nav-section-title {
  font-size: 10px;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 12px 4px;
}
.bottom-section {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  border-top: 1px solid rgba(255,255,255,0.06);
}

/* 顶栏 */
.app-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: rgba(255,255,255,0.95) !important;
  backdrop-filter: blur(8px);
}
.header-left {
  display: flex;
  align-items: center;
  gap: 14px;
}
.collapse-btn { color: #64748b; }
.page-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 用户按钮 */
.user-btn {
  display: flex !important;
  align-items: center;
  gap: 8px;
  padding: 4px 12px 4px 4px !important;
  border-radius: 20px !important;
  transition: background var(--transition-fast);
}
.user-btn:hover { background: #f1f5f9 !important; }
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.user-name {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}
.role-tag { font-weight: 500; }

/* 内容区 */
.app-content {
  height: calc(100vh - 56px);
  background: #f1f5f9;
  overflow-y: auto;
}

/* 内容区局部切换动画，避免管理后台整个布局闪烁 */
.content-fade-enter-active {
  transition: opacity 0.15s ease;
}
.content-fade-leave-active {
  transition: opacity 0.1s ease;
}
.content-fade-enter-from,
.content-fade-leave-to {
  opacity: 0;
}
</style>
