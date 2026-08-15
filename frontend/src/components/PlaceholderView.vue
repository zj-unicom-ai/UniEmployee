<!-- 占位页：开发中页面的临时提示 -->
<template>
  <div class="placeholder">
    <div class="icon">{{ icon }}</div>
    <h2>{{ title }}</h2>
    <p>正在开发中，敬请期待</p>
    <n-button tag="a" href="/" type="primary" ghost style="margin-top:12px">返回首页</n-button>
  </div>
</template>

<script setup>
defineProps({ title: String, icon: { type: String, default: '🔧' } })
</script>

<style scoped>
.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 60vh;
  flex-direction: column;
  gap: 12px;
}
.icon { font-size: 48px; }
h2 { color: #e6edf3; font-size: 20px; font-weight: 600; }
p { color: #8b949e; font-size: 14px; }
</style>
