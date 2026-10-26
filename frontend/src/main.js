// 前端入口：初始化 Vue 应用，挂载 Vue Router、Pinia 状态管理、Naive UI 组件库
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import naive from 'naive-ui'
import router from './router'
import App from './App.vue'
import './styles/global.css'

// A deployment can replace hashed lazy chunks while this SPA is still open.
// Reload once with a cache-busting URL so Vue Router can pick up the new manifest.
const assetRefreshParam = '__asset_refresh'
window.addEventListener('vite:preloadError', event => {
  event.preventDefault()
  const refreshUrl = new URL(window.location.href)
  if (refreshUrl.searchParams.has(assetRefreshParam)) return
  refreshUrl.searchParams.set(assetRefreshParam, String(Date.now()))
  window.location.replace(refreshUrl)
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)
app.mount('#app')
router.isReady().then(() => {
  const currentUrl = new URL(window.location.href)
  if (!currentUrl.searchParams.has(assetRefreshParam)) return
  currentUrl.searchParams.delete(assetRefreshParam)
  window.history.replaceState(window.history.state, '', currentUrl)
}).catch(() => {})
