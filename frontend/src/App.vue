<!-- 根组件：Naive UI Provider 包裹，全局路由视图 + 页面切换过渡动画 -->
<template>
  <n-config-provider :theme="null" :theme-overrides="themeOverrides">
    <n-global-style />
    <n-loading-bar-provider>
      <n-message-provider>
        <n-dialog-provider>
          <router-view v-slot="{ Component, route }">
            <transition name="fade" mode="out-in">
              <component :is="Component" :key="rootViewKey(route)" />
            </transition>
          </router-view>
        </n-dialog-provider>
      </n-message-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup>
import {
  NConfigProvider,
  NGlobalStyle,
  NLoadingBarProvider,
  NMessageProvider,
  NDialogProvider
} from 'naive-ui'
import { themeOverrides } from './styles/theme.js'

// /app 下的所有子路由都复用同一个后台布局，key 固定为 app-main，
// 避免点击左侧菜单时整个 MainLayout 被重新挂载导致页面闪烁。
function rootViewKey(route) {
  return route.matched.some(r => r.name === 'app-main') ? 'app-main' : route.path
}
</script>

<style>
/* 页面切换淡入淡出 */
.fade-enter-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}
.fade-leave-to {
  opacity: 0;
}
</style>
