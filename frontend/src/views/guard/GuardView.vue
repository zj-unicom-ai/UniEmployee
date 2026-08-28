<!-- 安全护栏模块：二级导航容器（敏感词过滤 / 工具调用护栏 / 后续扩展…）。
     顶栏标题随子路由切换。 -->
<template>
  <div class="guard-view">
    <n-tabs :value="activeTab" type="line" size="small" @update:value="go">
      <n-tab name="sensitive-words" tab="敏感词过滤" />
      <n-tab name="tool-calls" tab="工具调用护栏" />
    </n-tabs>
    <div class="guard-body">
      <router-view />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

defineOptions({ name: 'GuardView' })

const route = useRoute()
const router = useRouter()
const activeTab = computed(() => {
  const m = route.path.match(/\/app\/guard\/([^/]+)/)
  return m ? m[1] : 'sensitive-words'
})
function go(key) {
  router.push(`/app/guard/${key}`)
}
</script>

<style scoped>
.guard-view { height: 100%; display: flex; flex-direction: column; padding: 18px 28px 0; }
.guard-body { flex: 1; overflow-y: auto; padding: 16px 2px 24px; }
</style>
