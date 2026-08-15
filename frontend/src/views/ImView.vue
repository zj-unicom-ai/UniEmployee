<template>
  <div class="im-dev-wrap">
    <div class="im-dev-card">正在开发中，敬请期待。</div>
  </div>
</template>

<script setup>
defineOptions({ name: 'ImView' })
</script>

<style scoped>
.im-dev-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}
.im-dev-card {
  padding: 18px 24px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  color: #64748b;
  font-size: 14px;
}
</style>
