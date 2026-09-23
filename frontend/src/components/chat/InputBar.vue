<!-- 底部输入栏 + 附件选择 + 提示气泡 -->
<template>
  <div class="input-bar" :class="{ 'drop-active': dropActive, 'full-width-mode': fullWidth }"
       @dragover.prevent="dropActive = true" @dragenter.prevent="dropActive = true"
       @dragleave="onDragLeave" @drop.prevent="onDrop" @paste="onPaste">
    <div v-if="dropActive" class="drop-hint">松开即可添加附件</div>
    <div v-if="pendingFiles.length" class="att-chips">
      <span v-for="(f, i) in pendingFiles" :key="i" class="att-chip" :title="f.name">
        <span class="att-icon">📎</span>
        <span class="att-name">{{ f.name }}</span>
        <span class="att-size">{{ fmtSize(f.size) }}</span>
        <button class="att-remove" type="button" :disabled="disabled || uploading"
                :aria-label="`移除附件 ${f.name}`" @click="removeFile(i)">×</button>
      </span>
    </div>
    <div class="input-row">
      <button class="att-btn" type="button" title="上传附件" aria-label="上传附件"
              :disabled="disabled || uploading" @click="pickFile">📎</button>
      <n-input
        v-model:value="text"
        type="textarea"
        :autosize="{ minRows: 1, maxRows: 6 }"
        placeholder="向数字员工提问…"
        :input-props="{ 'aria-label': '输入消息' }"
        @keydown.enter="onEnter"
        :disabled="disabled"
      />
      <n-button v-if="sending" type="error" class="send-button stop-button"
                aria-label="停止生成" title="停止生成" @click="$emit('stop')">停止</n-button>
      <n-button v-else type="primary" class="send-button" :disabled="uploading"
                :loading="uploading" @click="onSend">{{ uploading ? '上传中' : '发送' }}</n-button>
      <n-popover v-if="hint" trigger="hover" placement="top-start" :width="340">
        <template #trigger>
          <button class="hint-icon" type="button" aria-label="查看建议问题">?</button>
        </template>
        <div style="white-space:pre-line;font-size:13px;line-height:1.7;max-height:300px;overflow-y:auto">{{ hint }}</div>
      </n-popover>
    </div>
    <div class="input-footer">Enter 发送 · Shift+Enter 换行 · 可拖入或粘贴文件</div>
    <input ref="fileInput" type="file" multiple hidden @change="onFilesPicked" />
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  disabled: { type: Boolean, default: false },
  sending: { type: Boolean, default: false },
  fullWidth: { type: Boolean, default: false },
  hint: { type: String, default: '' },
  uploading: { type: Boolean, default: false },
})
const emit = defineEmits(['send', 'stop'])

const text = ref('')
const pendingFiles = ref([])
const fileInput = ref(null)
const dropActive = ref(false)

function pickFile() {
  fileInput.value?.click()
}

function onFilesPicked(e) {
  addFiles(Array.from(e.target.files || []))
  e.target.value = '' // 允许重复选择同一文件
}

function addFiles(files) {
  if (props.disabled || props.uploading) return
  const seen = new Set(pendingFiles.value.map(f => `${f.name}:${f.size}:${f.lastModified}`))
  for (const file of files) {
    if (pendingFiles.value.length >= 5) break
    const key = `${file.name}:${file.size}:${file.lastModified}`
    if (!seen.has(key)) { pendingFiles.value.push(file); seen.add(key) }
  }
}

function onDrop(e) {
  dropActive.value = false
  addFiles(Array.from(e.dataTransfer?.files || []))
}

function onDragLeave(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) dropActive.value = false
}

function onPaste(e) {
  if (props.disabled || props.uploading) return
  const files = Array.from(e.clipboardData?.items || [])
    .filter(item => item.kind === 'file')
    .map(item => item.getAsFile())
    .filter(Boolean)
  if (files.length) { e.preventDefault(); addFiles(files) }
}

function removeFile(i) {
  pendingFiles.value.splice(i, 1)
}

function onEnter(e) {
  if (e.isComposing || e.keyCode === 229 || e.shiftKey) return
  e.preventDefault()
  onSend()
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
  emit('send', v, files, () => {
    text.value = ''
    pendingFiles.value = []
  })
}

function sendText(value) {
  text.value = String(value || '')
  onSend()
}

defineExpose({ sendText })
</script>

<style scoped>
.input-bar {
  position: relative;
  padding: 12px max(24px, calc((100% - 1080px) / 2)) 10px;
  background: #ffffff;
  border-top: 1px solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.input-bar.full-width-mode { padding: 12px clamp(24px, 4vw, 72px) 10px; }
.input-bar.drop-active { background: #eff6ff; outline: 2px dashed #60a5fa; outline-offset: -6px; }
.drop-hint { position: absolute; inset: 0; z-index: 2; display: grid; place-items: center; background: rgba(239, 246, 255, 0.94); color: #1d4ed8; font-weight: 600; pointer-events: none; }
.input-row {
  display: flex;
  gap: 10px;
  align-items: center;
}
.input-row :deep(.n-input) { flex: 1; min-width: 0; }
.att-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  border-radius: 8px;
  background: #f1f5f9;
  font-size: 16px;
  border: 0;
  color: #475569;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
}
.att-btn:hover { background: #e2e8f0; }
.att-btn:disabled, .att-remove:disabled { cursor: not-allowed; opacity: 0.5; }
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
.att-remove { cursor: pointer; color: #94a3b8; flex-shrink: 0; width: 22px; height: 22px; border: 0; border-radius: 6px; background: transparent; font-size: 17px; line-height: 1; }
.att-remove:hover { color: #dc2626; }
.att-remove:focus-visible, .att-btn:focus-visible, .hint-icon:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; }
.send-button { flex-shrink: 0; min-width: 72px; }
.input-footer { color: #94a3b8; font-size: 11px; padding-left: 42px; }
.hint-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px; height: 24px; border-radius: 50%;
  background: #e2e8f0; color: #64748b;
  border: 0;
  font-size: 14px; font-weight: 700; cursor: pointer;
  transition: all 0.15s; flex-shrink: 0; margin-left: 6px;
}
.hint-icon:hover { background: #3b82f6; color: #fff; }

@media (max-width: 640px) {
  .input-bar, .input-bar.full-width-mode { padding: 10px 12px max(10px, env(safe-area-inset-bottom)); }
  .input-row { gap: 7px; }
  .att-btn { width: 34px; height: 34px; }
  .input-footer { padding-left: 40px; font-size: 10px; }
  .hint-icon { display: none; }
}
</style>
