<!-- 左侧栏：历史对话列表 -->
<template>
  <aside class="conv-sidebar" :class="{ open }" :aria-hidden="!open" :inert="!open">
    <div class="conv-head">
      <span class="conv-title">历史对话</span>
      <div class="conv-actions">
        <n-button size="tiny" @click="$emit('new')">+ 新会话</n-button>
        <n-button quaternary circle size="tiny" aria-label="关闭历史会话" @click="$emit('close')">×</n-button>
      </div>
    </div>
    <div class="conv-filters">
      <n-input
        :value="query"
        size="small"
        clearable
        placeholder="搜索当前员工的会话标题或摘要"
        :input-props="{ 'aria-label': '搜索会话' }"
        @update:value="value => $emit('search', value || '')"
      />
      <div class="conv-tabs" aria-label="会话状态">
        <button type="button" :class="{ selected: !archivedOnly }" :aria-pressed="!archivedOnly" @click="$emit('archive-filter', false)">最近</button>
        <button type="button" :class="{ selected: archivedOnly }" :aria-pressed="archivedOnly" @click="$emit('archive-filter', true)">已归档</button>
      </div>
    </div>
    <div class="conv-list">
      <div v-if="!list.length && loading" class="conv-empty">正在加载会话…</div>
      <div v-else-if="!list.length" class="conv-empty">
        {{ query ? '没有匹配的会话' : archivedOnly ? '暂无归档会话' : '暂无历史对话' }}
      </div>
      <div
        v-for="c in list" :key="c.conv_id"
        class="conv-item"
        :class="{ active: c.conv_id === activeId }"
      >
        <button type="button" class="conv-open" @click="$emit('select', c.conv_id)">
          <div class="conv-name"><span v-if="c.pinned" class="pin-mark">置顶 · </span>{{ c.title || c.preview || '新对话' }}</div>
          <div class="conv-meta">
            <span class="emp-tag">{{ empNames[c.employee_id] || c.employee_id }}</span>
            <span>{{ fmtTime(c.updated_at) }}</span>
          </div>
        </button>
        <n-dropdown trigger="click" :options="menuOptions(c)" @select="key => onAction(key, c)">
          <n-button quaternary circle size="tiny" class="conv-more" :aria-label="`管理会话 ${c.title || c.preview || '新对话'}`">···</n-button>
        </n-dropdown>
      </div>
      <div v-if="error" class="conv-error">{{ error }} <button type="button" @click="$emit('retry-load')">重试</button></div>
      <n-button v-if="hasMore" block size="small" class="load-more" :loading="loading" @click="$emit('load-more')">加载更多</n-button>
    </div>
    <n-modal v-model:show="renameOpen" preset="card" title="重命名会话" class="rename-modal" style="width: min(420px, calc(100vw - 32px))">
      <n-input v-model:value="renameValue" maxlength="60" show-count placeholder="输入会话名称" @keyup.enter="submitRename" />
      <template #footer>
        <div class="rename-actions">
          <n-button @click="renameOpen = false">取消</n-button>
          <n-button type="primary" :disabled="!renameValue.trim()" @click="submitRename">保存</n-button>
        </div>
      </template>
    </n-modal>
  </aside>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  list: { type: Array, default: () => [] },
  activeId: { type: [String, Number], default: null },
  empNames: { type: Object, default: () => ({}) },
  open: { type: Boolean, default: false },
  query: { type: String, default: '' },
  archivedOnly: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  hasMore: { type: Boolean, default: false },
  error: { type: String, default: '' },
})
const emit = defineEmits(['select', 'new', 'close', 'search', 'archive-filter', 'load-more', 'retry-load', 'rename', 'pin', 'archive'])
const renameOpen = ref(false)
const renameValue = ref('')
const renameTarget = ref(null)

function menuOptions(c) {
  return [
    { label: '重命名', key: 'rename' },
    ...(!c.archived_at ? [{ label: c.pinned ? '取消置顶' : '置顶', key: 'pin' }] : []),
    { label: c.archived_at ? '移出归档' : '归档', key: 'archive' },
  ]
}

function onAction(key, c) {
  if (key === 'rename') {
    renameTarget.value = c.conv_id
    renameValue.value = c.title || c.preview || ''
    renameOpen.value = true
  } else if (key === 'pin') {
    emit('pin', c.conv_id, !c.pinned)
  } else if (key === 'archive') {
    emit('archive', c.conv_id, !c.archived_at)
  }
}

function submitRename() {
  const title = renameValue.value.trim()
  if (!title || !renameTarget.value) return
  emit('rename', renameTarget.value, title)
  renameOpen.value = false
}

function fmtTime(s) { return (s || '').replace('T', ' ').slice(5, 16) }
</script>

<style scoped>
.conv-sidebar {
  position: absolute;
  z-index: 40;
  inset: 0 auto 0 0;
  width: min(320px, 88vw);
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-right: 1px solid #e2e8f0;
  box-shadow: 12px 0 32px rgba(15, 23, 42, 0.12);
  transform: translateX(-105%);
  transition: transform 180ms ease;
}
.conv-sidebar.open { transform: translateX(0); }
.conv-actions { display: flex; align-items: center; gap: 4px; }
.conv-head :deep(.n-button) { min-width: 28px; }
.conv-filters { padding: 12px 12px 8px; border-bottom: 1px solid #f1f5f9; }
.conv-tabs { display: flex; gap: 4px; margin-top: 9px; }
.conv-tabs button { border: 0; border-radius: 7px; padding: 5px 10px; color: #64748b; background: transparent; cursor: pointer; font-size: 12px; }
.conv-tabs button.selected { background: #eff6ff; color: #1d4ed8; font-weight: 600; }
.conv-tabs button:focus-visible, .conv-open:focus-visible, .conv-error button:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.rename-actions { display: flex; justify-content: flex-end; gap: 8px; }
@media (prefers-reduced-motion: reduce) {
  .conv-sidebar { transition: none; }
}
.conv-head {
  padding: 12px 14px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #f1f5f9;
}
.conv-title { font-size: 13px; font-weight: 600; color: #334155; }
.conv-list { flex: 1; overflow-y: auto; padding: 8px; }
.conv-empty { font-size: 12px; color: #94a3b8; text-align: center; padding: 24px 8px; line-height: 1.8; }
.conv-item {
  display: flex;
  align-items: center;
  border-radius: 8px;
  margin-bottom: 4px;
  transition: background 0.15s;
}
.conv-item:hover { background: #f1f5f9; }
.conv-item.active { background: #eff6ff; border: 1px solid #3b82f6; }
.conv-open { min-width: 0; flex: 1; padding: 10px 12px; border: 0; background: transparent; text-align: left; cursor: pointer; }
.conv-more { flex-shrink: 0; margin-right: 5px; }
.conv-name { font-size: 13px; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pin-mark { color: #2563eb; font-size: 11px; }
.conv-meta { font-size: 11px; color: #94a3b8; margin-top: 3px; display: flex; gap: 8px; }
.emp-tag { color: #3b82f6; }
.load-more { margin: 8px 0; }
.conv-error { margin: 12px 4px; color: #b91c1c; font-size: 12px; }
.conv-error button { border: 0; color: #1d4ed8; background: transparent; cursor: pointer; }
</style>
