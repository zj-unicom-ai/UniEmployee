// 路由定义：落地页 → 登录页 → 管理后台（含鉴权守卫）
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'landing',
    component: () => import('../views/LandingView.vue'),
  },
  {
    path: '/cases',
    name: 'cases',
    component: () => import('../views/CasesView.vue'),
  },
  {
    path: '/cases/:id',
    name: 'case-detail',
    component: () => import('../views/CaseDetailView.vue'),
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
  },
  {
    path: '/app',
    name: 'app-main',
    component: () => import('../layouts/MainLayout.vue'),
    redirect: '/app/home',
    children: [
      { path: 'home', name: 'home', component: () => import('../views/HomeView.vue') },
      { path: 'chat', name: 'chat', component: () => import('../views/ChatView.vue') },
      { path: 'history', name: 'history', component: () => import('../views/HistoryView.vue') },
      { path: 'trace', name: 'trace', component: () => import('../views/TraceView.vue') },
      { path: 'admin', name: 'admin', component: () => import('../views/AdminView.vue') },
      {
        path: 'admin/employee/:id',
        component: () => import('../views/employee/EmployeeDetailView.vue'),
        children: [
          { path: '', name: 'employee-basic', component: () => import('../views/employee/BasicInfoPage.vue') },
          { path: 'skills', name: 'employee-skills', component: () => import('../views/employee/SkillsPage.vue') },
          { path: 'tools', name: 'employee-tools', component: () => import('../views/employee/ToolsPage.vue') },
          { path: 'knowledge-bases', name: 'employee-kbs', component: () => import('../views/employee/KnowledgeBasesPage.vue') },
          { path: 'sops', name: 'employee-sops', component: () => import('../views/employee/SopsPage.vue') },
          { path: 'connectors', name: 'employee-connectors', component: () => import('../views/employee/ConnectorsPage.vue') },
        ],
      },
      { path: 'users', name: 'users', component: () => import('../views/UsersView.vue') },
      { path: 'resources', name: 'resources', component: () => import('../views/ResourcesView.vue') },
      { path: 'ontology', name: 'ontology', component: () => import('../views/OntologyView.vue') },
      { path: 'evaluation', name: 'evaluation', component: () => import('../views/AdminEvaluation.vue') },
      {
        path: 'settings',
        name: 'settings',
        redirect: '/app/settings/guard/sensitive-words',
        component: () => import('../views/guard/GuardView.vue'),
        children: [
          { path: 'guard/sensitive-words', name: 'guard-words', component: () => import('../views/guard/SensitiveWordsPage.vue') },
          { path: 'guard/tool-calls', name: 'guard-tools', component: () => import('../views/guard/ToolCallsPage.vue') },
          { path: 'audit', name: 'audit-logs', component: () => import('../views/audit/AuditLogsPage.vue') },
        ],
      },
      { path: 'im', name: 'im', component: () => import('../views/ImView.vue') },
      { path: 'change-password', name: 'change-password', component: () => import('../views/ChangePasswordView.vue') },
      { path: 'profile', name: 'profile', component: () => import('../views/ProfileView.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  // 落地页和登录页不需要登录
  if (to.name === 'landing' || to.name === 'login' || to.name === 'cases' || to.name === 'case-detail') {
    // 已登录用户访问登录页 → 跳到后台
    if (to.name === 'login' && token) {
      next({ name: 'home' })
    } else {
      next()
    }
  } else if (!token) {
    // 受保护路由 → 跳登录
    next({ name: 'login', query: { next: to.fullPath } })
  } else {
    next()
  }
})

export default router
