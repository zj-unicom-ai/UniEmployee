<!-- DOCX 的静态 HTML 视图；无脚本、无同源权限，文档内容限制在沙箱 iframe 内。 -->
<template>
  <iframe
    class="document-preview-frame"
    :srcdoc="html"
    :title="title || 'Word 文档预览'"
    sandbox=""
    referrerpolicy="no-referrer"
  />
</template>

<script setup>
defineProps({
  html: { type: String, required: true },
  title: { type: String, default: '' },
})
</script>

<style scoped>
.document-preview-frame {
  display: block;
  width: 100%;
  height: min(72vh, 900px);
  min-height: 460px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #f3f5f8;
}

@media (max-width: 640px) {
  .document-preview-frame { min-height: 420px; }
}
</style>
