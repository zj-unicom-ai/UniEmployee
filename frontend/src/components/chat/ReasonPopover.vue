<!-- 点踩原因弹窗 -->
<template>
  <div v-if="show" class="reason-popover" :style="style">
    <div class="reason-title">请告诉我们哪里不好：</div>
    <div class="reason-options">
      <span
        v-for="r in REASONS" :key="r.value"
        class="reason-chip"
        :class="{ active: selected === r.value }"
        @click="$emit('select', r.value)"
      >{{ r.label }}</span>
    </div>
    <div class="reason-actions">
      <n-button size="tiny" @click="$emit('cancel')">取消</n-button>
      <n-button size="tiny" type="error" :disabled="!selected" @click="$emit('confirm', selected)">提交</n-button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  show: Boolean,
  selected: { type: String, default: null },
  style: { type: Object, default: () => ({}) },
})
defineEmits(['select', 'cancel', 'confirm'])

const REASONS = [
  { value: 'irrelevant', label: '答非所问' },
  { value: 'factual_error', label: '事实错误' },
  { value: 'wrong_process', label: '流程不对' },
  { value: 'too_slow', label: '太慢' },
  { value: 'other', label: '其他' },
]
</script>

<style scoped>
.reason-popover {
  position: absolute;
  bottom: calc(100% + 8px); left: 0; z-index: 10;
  background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
  padding: 12px 14px; box-shadow: 0 8px 24px rgba(0,0,0,0.12); min-width: 260px;
}
.reason-title { font-size: 12px; color: #64748b; margin-bottom: 10px; font-weight: 500; }
.reason-options { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.reason-chip {
  font-size: 12px; padding: 4px 12px; border-radius: 16px;
  border: 1px solid #e2e8f0; cursor: pointer; transition: all 0.15s; color: #475569;
  background: #f8fafc;
}
.reason-chip:hover { border-color: #3b82f6; color: #3b82f6; background: #eff6ff; }
.reason-chip.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }
.reason-actions { display: flex; gap: 8px; justify-content: flex-end; }
</style>
