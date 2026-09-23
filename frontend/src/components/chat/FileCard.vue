<!-- 会话产物文件卡片：数字员工生成的 Word 方案/纪要/CSV 等文件，支持下载与文本类预览 -->
<template>
  <div class="file-card">
    <div class="file-row">
      <span class="file-icon">{{ icon }}</span>
      <div class="file-info">
        <div class="file-name" :title="file.path">{{ file.name }}</div>
        <div class="file-meta">{{ isHtml ? '网页看板 · ' : '' }}{{ sizeText }}</div>
      </div>
      <n-button v-if="previewable" size="tiny" @click="togglePreview">
        {{ showPreview ? '收起预览' : '预览' }}
      </n-button>
      <n-button v-if="isHtml" size="tiny" type="primary" @click="toggleHtmlPreview">
        {{ showHtmlPreview ? '收起看板' : '打开看板' }}
      </n-button>
      <n-button size="tiny" type="primary" :loading="downloading" @click="download">下载</n-button>
    </div>
    <pre v-if="showPreview" class="file-preview">{{ previewText }}</pre>
    <div v-if="isHtml && showHtmlPreview" class="html-preview">
      <div v-if="loadingHtml" class="html-preview-state">正在加载看板…</div>
      <div v-else-if="htmlError" class="html-preview-state html-preview-error">
        {{ htmlError }}
        <n-button size="tiny" @click="loadHtmlPreview">重试</n-button>
      </div>
      <ReportViewer v-else-if="reportHtml" :html="reportHtml" />
    </div>
  </div>
</template>

<script setup>
// 产物文件下载走 /api/workspace/file（Bearer 鉴权，blob 落地为浏览器下载）；
// HTML 看板自动以内嵌沙箱预览；文本类文件可展开预览，其他文件可下载。
import { computed, onMounted, ref } from 'vue'
import api from '../../api.js'
import ReportViewer from '../agent/analyst/ReportViewer.vue'

const props = defineProps({ file: { type: Object, required: true } })

const PREVIEW_EXTS = ['md', 'txt', 'csv', 'log', 'json']
const downloading = ref(false)
const showPreview = ref(false)
const previewText = ref('')
const showHtmlPreview = ref(false)
const loadingHtml = ref(false)
const htmlError = ref('')
const reportHtml = ref('')

const ext = computed(() => (props.file.name || '').split('.').pop().toLowerCase())
const isHtml = computed(() => ext.value === 'html' || ext.value === 'htm')
const icon = computed(() => {
  if (isHtml.value) return '📊'
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

async function loadHtmlPreview() {
  if (loadingHtml.value) return
  loadingHtml.value = true
  htmlError.value = ''
  try {
    const res = await api.get('/workspace/file', {
      params: { path: props.file.path },
      responseType: 'text',
    })
    reportHtml.value = typeof res.data === 'string' ? res.data : ''
    if (!reportHtml.value.trim()) htmlError.value = '看板内容为空'
  } catch (e) {
    htmlError.value = '看板加载失败：' + (e.response?.data?.detail || e.message)
  } finally {
    loadingHtml.value = false
  }
}

function toggleHtmlPreview() {
  showHtmlPreview.value = !showHtmlPreview.value
  if (showHtmlPreview.value && !reportHtml.value) loadHtmlPreview()
}

onMounted(() => {
  if (isHtml.value) {
    showHtmlPreview.value = true
    loadHtmlPreview()
  }
})
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
.html-preview { margin-top: 8px; }
.html-preview-state { display: flex; align-items: center; gap: 8px; min-height: 48px; color: #64748b; font-size: 12px; }
.html-preview-error { color: #b91c1c; }
</style>
