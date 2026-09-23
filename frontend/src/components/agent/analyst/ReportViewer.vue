<!--
数据分析 · 报告展示组件
入参 html（string）：report-generation 技能输出的完整 HTML（含 ECharts CDN 与脚本）
特性：iframe srcdoc 沙箱渲染 + 下载 .html + 受控新窗口 + 高度自适应
-->
<template>
  <div class="report-viewer">
    <div class="rv-toolbar">
      <span class="rv-label">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="15" y2="17"/></svg>
        数据分析报告
      </span>
      <div class="rv-actions">
        <n-button size="tiny" text @click="download">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          下载
        </n-button>
        <n-button size="tiny" text @click="openInNew">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
          新窗口
        </n-button>
        <n-button size="tiny" text @click="toggleExpand">
          <svg class="rv-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9" v-if="!expanded" />
            <polyline points="6 15 12 9 18 15" v-else />
          </svg>
          {{ expanded ? '收起' : '展开' }}
        </n-button>
      </div>
    </div>

    <div class="rv-body" :class="{ collapsed: !expanded }">
      <!--
        sandbox: allow-scripts 让 ECharts 能跑；不放 allow-same-origin 避免 DOM 被父页操作
        srcdoc: 直接内嵌完整 HTML 字符串，包括 ECharts CDN 与初始化脚本
        高度自适应：iframe 加载完后读取 contentDocument.body.scrollHeight 调整 iframe 高度
      -->
      <iframe
        ref="iframeRef"
        :srcdoc="html"
        sandbox="allow-scripts"
        class="rv-iframe"
        @load="onLoad"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useMessage, NButton } from 'naive-ui'

const props = defineProps({
  html: { type: String, default: '' },
})

const message = useMessage()
const iframeRef = ref(null)
const expanded = ref(true)

function toggleExpand() {
  expanded.value = !expanded.value
}

function onLoad() {
  // iframe 加载后等待 ECharts 渲染完，再根据内容高度自适应
  // 多次延迟测量兜底，避免 ECharts 异步初始化造成高度短小
  const tryResize = (attempts = 6) => {
    try {
      const doc = iframeRef.value?.contentWindow?.document
      if (!doc) return
      const h = Math.max(doc.body.scrollHeight, doc.documentElement.scrollHeight, 320)
      iframeRef.value.style.height = h + 'px'
    } catch {}
    if (attempts > 0) setTimeout(() => tryResize(attempts - 1), 200)
  }
  tryResize()
}

watch(() => props.html, () => {
  // HTML 变更后下一帧重新测量
  setTimeout(onLoad, 300)
})

function download() {
  try {
    const blob = new Blob([props.html], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    // 文件名用 <title> 内容，取不到就用时间戳
    const m = props.html.match(/<title>([^<]+)<\/title>/i)
    a.download = (m ? m[1].trim() : `report-${Date.now()}`).replace(/[\\/:*?"<>|]/g, '_') + '.html'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    message.success('已下载报告 HTML')
  } catch (e) {
    message.error('下载失败：' + (e?.message || ''))
  }
}

function openInNew() {
  const id = (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`)
  const storageKey = `uniemployee:report-viewer:${id}`
  try {
    // 新窗口打开真实的受控 viewer 页面，避免 about:blank 动态文档刷新后丢失。
    // 报告内容只交给 viewer 壳页面，再由壳页面放进 sandbox iframe；报告脚本
    // 没有 allow-same-origin，因此无法读取主站 localStorage。
    localStorage.setItem(storageKey, JSON.stringify({
      html: props.html,
      createdAt: Date.now(),
    }))
    const url = `/report-viewer.html?id=${encodeURIComponent(id)}`
    // 不把 noopener 作为 window.open feature 传入：部分浏览器会因此返回
    // null，即使标签页实际已打开。viewer 是受控壳页面，拿到句柄后立即
    // 切断 opener，报告本身仍运行在无 allow-same-origin 的 sandbox 中。
    const win = window.open(url, '_blank')
    if (!win) {
      message.warning('新窗口被浏览器拦截，请允许本站弹窗后重试')
    } else {
      try { win.opener = null } catch {}
    }
  } catch (e) {
    try { localStorage.removeItem(storageKey) } catch {}
    message.error('打开失败：' + (e?.message || ''))
  }
}
</script>

<style scoped>
.report-viewer {
  position: relative;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  overflow: hidden;
}
.rv-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 10px;
  background: #f9fafb;
  border-bottom: 1px solid #f3f4f6;
}
.rv-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: #4f46e5;
}
.rv-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.rv-actions .n-button { color: #64748b; font-size: 12px; }
.rv-actions .n-button:hover { color: #4f46e5; }
.rv-icon { width: 14px; height: 14px; }

.rv-body {
  position: relative;
  background: #fff;
}
.rv-body.collapsed {
  max-height: 240px;
  overflow: hidden;
}
.rv-body.collapsed::after {
  content: '';
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 60px;
  background: linear-gradient(to bottom, transparent, #fff);
  pointer-events: none;
}
.rv-iframe {
  display: block;
  width: 100%;
  height: min(72vh, 900px);
  border: none;
  min-height: 520px;
  background: #fff;
}
</style>
