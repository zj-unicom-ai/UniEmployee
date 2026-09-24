<!-- 会话产物文件卡片：支持 HTML 看板、DOCX 和文本类文件预览及下载 -->
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
      <n-button v-if="isDocx" size="tiny" @click="toggleDocxPreview">
        {{ showDocxPreview ? '收起文档' : '预览文档' }}
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
    <div v-if="isDocx && showDocxPreview" class="docx-preview">
      <div v-if="loadingDocx" class="html-preview-state">正在加载文档…</div>
      <div v-else-if="docxError" class="html-preview-state html-preview-error">
        {{ docxError }}
        <n-button size="tiny" @click="loadDocxPreview">重试</n-button>
      </div>
      <DocumentPreview v-else-if="docxHtml" :html="docxHtml" :title="file.name" />
    </div>
  </div>
</template>

<script setup>
// 产物文件优先按 artifact_id 访问受 ACL 控制的文件端点；旧消息仍走 path 兼容入口。
// HTML 看板和 DOCX 可在线预览，文本类文件可展开预览，其他文件可下载。
import { computed, ref, watch } from 'vue'
import api from '../../api.js'
import ReportViewer from '../agent/analyst/ReportViewer.vue'
import DocumentPreview from './DocumentPreview.vue'

const props = defineProps({ file: { type: Object, required: true } })

const PREVIEW_EXTS = ['md', 'txt', 'csv', 'log', 'json']
const downloading = ref(false)
const showPreview = ref(false)
const previewText = ref('')
const showHtmlPreview = ref(false)
const loadingHtml = ref(false)
const htmlError = ref('')
const reportHtml = ref('')
const showDocxPreview = ref(false)
const loadingDocx = ref(false)
const docxError = ref('')
const docxHtml = ref('')
const requestSeq = ref(0)
let previewController = null

const ext = computed(() => (props.file.name || '').split('.').pop().toLowerCase())
const isHtml = computed(() => ext.value === 'html' || ext.value === 'htm')
const isDocx = computed(() => ext.value === 'docx')
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

function fileEndpoint(preview = false) {
  if (props.file.artifact_id) {
    const suffix = preview ? '/preview' : '/file'
    return { url: `/workspace/artifacts/${encodeURIComponent(props.file.artifact_id)}${suffix}`, params: {} }
  }
  return { url: preview ? '/workspace/preview' : '/workspace/file', params: { path: props.file.path } }
}

async function download() {
  downloading.value = true
  try {
    const endpoint = fileEndpoint()
    const res = await api.get(endpoint.url, {
      params: endpoint.params,
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
      const endpoint = fileEndpoint()
      const res = await api.get(endpoint.url, {
        params: endpoint.params,
        responseType: 'text',
      })
      previewText.value = res.data
    } catch (e) {
      previewText.value = '（预览加载失败）'
    }
  }
}

function errorMessage(error, fallback) {
  const data = error?.response?.data
  if (typeof data === 'string') {
    try {
      const parsed = JSON.parse(data)
      if (parsed.detail) return parsed.detail
    } catch {}
    if (data.trim()) return data.slice(0, 160)
  }
  return data?.detail || error?.message || fallback
}

async function loadHtmlPreview() {
  previewController?.abort()
  const controller = new AbortController()
  previewController = controller
  const seq = ++requestSeq.value
  loadingHtml.value = true
  htmlError.value = ''
  try {
    const endpoint = fileEndpoint()
    const res = await api.get(endpoint.url, {
      params: endpoint.params,
      responseType: 'text',
      timeout: 30000,
      signal: controller.signal,
    })
    if (seq !== requestSeq.value) return
    reportHtml.value = typeof res.data === 'string' ? res.data : ''
    if (!reportHtml.value.trim()) htmlError.value = '看板内容为空'
  } catch (e) {
    if (seq === requestSeq.value && e.code !== 'ERR_CANCELED') {
      htmlError.value = '看板加载失败：' + errorMessage(e, '请稍后重试')
    }
  } finally {
    if (seq === requestSeq.value) loadingHtml.value = false
  }
}

async function loadDocxPreview() {
  previewController?.abort()
  const controller = new AbortController()
  previewController = controller
  const seq = ++requestSeq.value
  loadingDocx.value = true
  docxError.value = ''
  try {
    const endpoint = fileEndpoint(true)
    const res = await api.get(endpoint.url, {
      params: endpoint.params,
      responseType: 'text',
      timeout: 30000,
      signal: controller.signal,
    })
    if (seq !== requestSeq.value) return
    docxHtml.value = typeof res.data === 'string' ? res.data : ''
    if (!docxHtml.value.trim()) docxError.value = '文档内容为空'
  } catch (e) {
    if (seq === requestSeq.value && e.code !== 'ERR_CANCELED') {
      docxError.value = '文档加载失败：' + errorMessage(e, '请稍后重试')
    }
  } finally {
    if (seq === requestSeq.value) loadingDocx.value = false
  }
}

function toggleHtmlPreview() {
  showHtmlPreview.value = !showHtmlPreview.value
  if (showHtmlPreview.value && !reportHtml.value) loadHtmlPreview()
}

function toggleDocxPreview() {
  showDocxPreview.value = !showDocxPreview.value
  if (showDocxPreview.value && !docxHtml.value) loadDocxPreview()
}

watch(() => [props.file.artifact_id, props.file.path, props.file.name].join('|'), () => {
  previewController?.abort()
  requestSeq.value += 1
  showPreview.value = false
  previewText.value = ''
  reportHtml.value = ''
  htmlError.value = ''
  loadingHtml.value = false
  docxHtml.value = ''
  docxError.value = ''
  loadingDocx.value = false
  showHtmlPreview.value = isHtml.value
  showDocxPreview.value = isDocx.value
  if (isHtml.value) loadHtmlPreview()
  else if (isDocx.value) loadDocxPreview()
}, { immediate: true })
</script>

<style scoped>
.file-card {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  box-sizing: border-box;
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
.docx-preview { margin-top: 8px; }
.html-preview-state { display: flex; align-items: center; gap: 8px; min-height: 48px; color: #64748b; font-size: 12px; }
.html-preview-error { color: #b91c1c; }
</style>
