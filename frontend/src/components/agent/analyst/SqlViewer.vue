<!--
数据分析 · SQL 展示组件
入参 sql（string）：要展示的 SQL 语句
特性：语法高亮 + 一键复制 + 折叠/展开（长 SQL 默认折叠为 4 行高度，点击展开）
-->
<template>
  <div class="sql-viewer" :class="{ collapsed: !expanded }">
    <div class="sv-toolbar">
      <n-button size="tiny" text @click="toggleExpand">
        <svg class="sv-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9" v-if="!expanded" />
          <polyline points="6 15 12 9 18 15" v-else />
        </svg>
        {{ expanded ? '收起' : '展开' }}
      </n-button>
      <span class="sv-label">SQL</span>
      <n-button size="tiny" text @click="copy" :loading="copying">
        <svg class="sv-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
        复制
      </n-button>
    </div>

    <pre class="sv-sql" v-html="highlighted"></pre>

    <div v-if="canCollapse && !expanded" class="sv-fade" />
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useMessage, NButton } from 'naive-ui'
import { highlightSql, formatSql } from '../../../utils/sqlFormat.js'

const props = defineProps({
  sql: { type: String, default: '' },
  // 超过多少行才允许折叠
  collapseThreshold: { type: Number, default: 4 },
})

const message = useMessage()
const expanded = ref(false)
const copying = ref(false)

const formatted = computed(() => formatSql(props.sql || ''))
const highlighted = computed(() => highlightSql(formatted.value))

const lineCount = computed(() => formatted.value.split('\n').length)
const canCollapse = computed(() => lineCount.value > props.collapseThreshold)

function toggleExpand() {
  if (canCollapse.value) expanded.value = !expanded.value
}

async function copy() {
  if (!props.sql) return
  copying.value = true
  try {
    await navigator.clipboard.writeText(props.sql)
    message.success('SQL 已复制')
  } catch {
    // 降级方案
    const ta = document.createElement('textarea')
    ta.value = props.sql
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    try {
      document.execCommand('copy')
      message.success('SQL 已复制')
    } catch {
      message.error('复制失败，请手动复制')
    }
    document.body.removeChild(ta)
  } finally {
    copying.value = false
  }
}
</script>

<style scoped>
.sql-viewer {
  position: relative;
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 8px;
  overflow: hidden;
  font-size: 12px;
}
.sv-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 8px;
  background: #0f172a;
  border-bottom: 1px solid #334155;
}
.sv-toolbar .n-button { color: #94a3b8; }
.sv-toolbar .n-button:hover { color: #e2e8f0; }
.sv-label {
  margin-left: auto;
  font-size: 11px;
  color: #64748b;
  letter-spacing: 0.5px;
}
.sv-icon { width: 14px; height: 14px; }

.sv-sql {
  margin: 0;
  padding: 10px 14px;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, Monaco, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #e2e8f0;
  white-space: pre-wrap;
  word-break: break-word;
  tab-size: 2;
}
:deep(.sql-kw) { color: #60a5fa; font-weight: 600; }
:deep(.sql-str) { color: #fbbf24; }

.sql-viewer.collapsed .sv-sql {
  max-height: calc(1.6em * 4 + 20px);
  overflow: hidden;
}
.sv-fade {
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 28px;
  background: linear-gradient(to bottom, transparent, #1e293b);
  pointer-events: none;
}
</style>
