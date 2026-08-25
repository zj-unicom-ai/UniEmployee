<!-- 底部输入栏 + 附件选择 + 提示气泡 -->
<template>
  <div class="input-bar">
    <div v-if="pendingFiles.length" class="att-chips">
      <span v-for="(f, i) in pendingFiles" :key="i" class="att-chip" :title="f.name">
        <span class="att-icon">📎</span>
        <span class="att-name">{{ f.name }}</span>
        <span class="att-size">{{ fmtSize(f.size) }}</span>
        <span class="att-remove" @click="removeFile(i)">✕</span>
      </span>
    </div>
    <div class="input-row">
      <span class="att-btn" title="上传附件" @click="pickFile">📎</span>
      <n-input
        v-model:value="text"
        placeholder="输入消息，回车发送"
        @keyup.enter="onSend"
        :disabled="disabled"
      />
      <n-button type="primary" :loading="disabled || uploading" @click="onSend">发送</n-button>
      <n-popover v-if="hint" trigger="hover" placement="top-start" :width="340">
        <template #trigger>
          <span class="hint-icon">?</span>
        </template>
        <div style="white-space:pre-line;font-size:13px;line-height:1.7;max-height:300px;overflow-y:auto">{{ hint }}</div>
      </n-popover>
    </div>
    <input ref="fileInput" type="file" multiple hidden @change="onFilesPicked" />
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  uploading: { type: Boolean, default: false },
})
const emit = defineEmits(['send'])

const text = ref('')
const pendingFiles = ref([])
const fileInput = ref(null)

function pickFile() {
  fileInput.value?.click()
}

function onFilesPicked(e) {
  const files = Array.from(e.target.files || [])
  for (const f of files) {
    if (pendingFiles.value.length >= 5) break
    pendingFiles.value.push(f)
  }
  e.target.value = '' // 允许重复选择同一文件
}

function removeFile(i) {
  pendingFiles.value.splice(i, 1)
}

function fmtSize(n) {
  if (!n) return ''
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + 'MB'
  if (n >= 1024) return Math.round(n / 1024) + 'KB'
  return n + 'B'
}

function onSend() {
  const v = text.value.trim()
  if ((!v && !pendingFiles.value.length) || props.disabled || props.uploading) return
  const files = pendingFiles.value.slice()
  text.value = ''
  pendingFiles.value = []
  emit('send', v, files)
}
</script>

<style scoped>
.input-bar {
  padding: 10px 20px 12px;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.att-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  border-radius: 8px;
  background: #f1f5f9;
  font-size: 16px;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}
.att-btn:hover { background: #e2e8f0; }
.att-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.att-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  color: #0369a1;
  border-radius: 8px;
  padding: 3px 8px;
  font-size: 12px;
  max-width: 260px;
}
.att-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.att-size { color: #94a3b8; flex-shrink: 0; }
.att-remove { cursor: pointer; color: #94a3b8; flex-shrink: 0; }
.att-remove:hover { color: #dc2626; }
.hint-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px; height: 24px; border-radius: 50%;
  background: #e2e8f0; color: #64748b;
  font-size: 14px; font-weight: 700; cursor: pointer;
  transition: all 0.15s; flex-shrink: 0; margin-left: 6px;
}
.hint-icon:hover { background: #3b82f6; color: #fff; }
</style>
