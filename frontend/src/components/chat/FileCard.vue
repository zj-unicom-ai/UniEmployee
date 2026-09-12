<!-- 会话产物文件卡片：数字员工生成的 Word 方案/纪要/CSV 等文件，支持下载与文本类预览 -->
<template>
  <div class="file-card">
    <div class="file-row">
      <span class="file-icon">{{ icon }}</span>
      <div class="file-info">
        <div class="file-name" :title="file.path">{{ file.name }}</div>
        <div class="file-meta">{{ sizeText }}</div>
      </div>
      <n-button v-if="previewable" size="tiny" @click="togglePreview">
        {{ showPreview ? '收起预览' : '预览' }}
      </n-button>
      <n-button size="tiny" type="primary" :loading="downloading" @click="download">下载</n-button>
    </div>
    <pre v-if="showPreview" class="file-preview">{{ previewText }}</pre>
  </div>
</template>

<script setup>
// 产物文件下载走 /api/workspace/file（Bearer 鉴权，blob 落地为浏览器下载）；
// 文本类文件（md/txt/csv/log/json）可展开预览，二进制（docx 等）仅下载。
import { computed, ref } from 'vue'
import api from '../../api.js'

const props = defineProps({ file: { type: Object, required: true } })

const PREVIEW_EXTS = ['md', 'txt', 'csv', 'log', 'json']
const downloading = ref(false)
const showPreview = ref(false)
const previewText = ref('')

const ext = computed(() => (props.file.name || '').split('.').pop().toLowerCase())
const icon = computed(() => {
  if (ext.value === 'docx' || ext.value === 'doc') return '📄'
  if (ext.value === 'csv' || ext.value === 'xlsx') return '📊'
  if (['md', 'txt', 'log'].includes(ext.value)) return '📝'
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext.value)) return '🖼'
  return '📎'
})
const previewable = computed(() => PREVIEW_EXTS.includes(ext.value))
const sizeText = computed(() => {
  const s = props.file.size || 0
  if (s > 1024 * 1024) return (s / 1024 / 1024).toFixed(1) + ' MB'
  if (s > 1024) return (s / 1024).toFixed(1) + ' KB'
  return s + ' B'
})

async function download() {
  downloading.value = true
  try {
    const res = await api.get('/workspace/file', {
      params: { path: props.file.path },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(res.data)
    const a = document.createElement('a')
    a.href = url
    a.download = props.file.name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('文件下载失败:', e)
  } finally {
    downloading.value = false
  }
}

async function togglePreview() {
  showPreview.value = !showPreview.value
  if (showPreview.value && !previewText.value) {
    try {
      const res = await api.get('/workspace/file', {
        params: { path: props.file.path },
        responseType: 'text',
      })
      previewText.value = res.data
    } catch (e) {
      previewText.value = '（预览加载失败）'
    }
  }
}
</script>

<style scoped>
.file-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 10px;
  margin: 6px 0;
  background: #f8fafc;
}
.file-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.file-icon { font-size: 20px; }
.file-info { flex: 1; min-width: 0; }
.file-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.file-meta { font-size: 11px; color: #94a3b8; }
.file-preview {
  margin: 8px 0 0;
  max-height: 300px;
  overflow: auto;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
