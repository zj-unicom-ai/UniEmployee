<!-- 左侧栏：历史对话列表 -->
<template>
  <div class="conv-sidebar">
    <div class="conv-head">
      <span class="conv-title">历史对话</span>
      <n-button size="tiny" @click="$emit('new')">+ 新会话</n-button>
    </div>
    <div class="conv-list">
      <div v-if="!list.length" class="conv-empty">暂无历史对话<br>发条消息开始吧</div>
      <div
        v-for="c in list" :key="c.conv_id"
        class="conv-item"
        :class="{ active: c.conv_id === activeId }"
        @click="$emit('select', c.conv_id)"
      >
        <div class="conv-name">{{ c.title || c.preview || '新对话' }}</div>
        <div class="conv-meta">
          <span class="emp-tag">{{ empNames[c.employee_id] || c.employee_id }}</span>
          <span>{{ fmtTime(c.updated_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  list: { type: Array, default: () => [] },
  activeId: { type: [String, Number], default: null },
  empNames: { type: Object, default: () => ({}) },
})
defineEmits(['select', 'new'])

function fmtTime(s) { return (s || '').replace('T', ' ').slice(5, 16) }
</script>

<style scoped>
.conv-sidebar {
  width: 240px;
  border-right: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
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
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.15s;
}
.conv-item:hover { background: #f1f5f9; }
.conv-item.active { background: #eff6ff; border: 1px solid #3b82f6; }
.conv-name { font-size: 13px; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.conv-meta { font-size: 11px; color: #94a3b8; margin-top: 3px; display: flex; gap: 8px; }
.emp-tag { color: #3b82f6; }
</style>
