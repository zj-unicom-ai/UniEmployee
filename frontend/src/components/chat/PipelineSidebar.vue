<!-- 中栏：执行流水线状态 -->
<template>
  <aside class="pipeline-sidebar" :class="{ open }" :aria-hidden="!open" :inert="!open">
    <div class="pipeline-head">
      <div>
        <div class="pipeline-title">执行详情</div>
        <div class="pipeline-subtitle">仅显示当前实时事件，历史记录请查看完整 Trace</div>
      </div>
      <n-button quaternary circle size="small" aria-label="关闭执行详情" @click="$emit('close')">×</n-button>
    </div>
    <div class="pipeline-body">
      <div class="section-title">当前 Agent 配置</div>
      <div v-if="!hasConfig" class="empty-note">发送消息后显示本轮使用的配置</div>
      <template v-for="s in CONFIG_STAGES" :key="s[0]">
        <div v-if="states[s[0]]" class="stage" :class="states[s[0]]">
          <div class="dot"></div>
          <div>
            <div class="stage-name">{{ s[1] }}</div>
            <div v-if="detail[s[0]]" class="stage-detail">{{ detail[s[0]] }}</div>
          </div>
        </div>
      </template>
      <div class="section-title runtime-title">本轮执行事件</div>
      <div v-if="!hasRuntime" class="empty-note">尚无实时执行事件</div>
      <div v-else class="empty-note">灰色项表示本轮未收到对应事件</div>
      <template v-for="(s, i) in RUNTIME_STAGES" :key="s[0]">
        <div v-if="i" class="connector" :class="{ done: states[s[0]] === 'done' }"></div>
        <div class="stage" :class="states[s[0]] || 'pending'">
          <div class="dot"></div>
          <div>
            <div class="stage-name">{{ s[1] }}</div>
            <div v-if="detail[s[0]]" class="stage-detail">{{ detail[s[0]] }}</div>
          </div>
        </div>
      </template>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  states: { type: Object, default: () => ({}) },
  detail: { type: Object, default: () => ({}) },
  open: { type: Boolean, default: false },
})
defineEmits(['close'])

const CONFIG_STAGES = [
  ['employee', '员工与模型'], ['sop', '可用 SOP（配置）'],
  ['skills', '可用 Skills（配置）'],
]
const RUNTIME_STAGES = [
  ['input', '提交消息'], ['planning', '规划清单事件'],
  ['skill', '工具调用事件'], ['report', '运行结果'],
]
const hasConfig = computed(() => CONFIG_STAGES.some(([id]) => props.states[id]))
const hasRuntime = computed(() => RUNTIME_STAGES.some(([id]) => props.states[id]))
</script>

<style scoped>
.pipeline-sidebar {
  position: absolute;
  z-index: 40;
  inset: 0 0 0 auto;
  width: min(360px, 92vw);
  padding: 18px;
  overflow-y: auto;
  background: #ffffff;
  border-left: 1px solid #e2e8f0;
  box-shadow: -12px 0 32px rgba(15, 23, 42, 0.12);
  transform: translateX(105%);
  transition: transform 180ms ease;
}
.pipeline-sidebar.open { transform: translateX(0); }
.pipeline-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.pipeline-title { font-size: 15px; font-weight: 650; color: #0f172a; }
.pipeline-subtitle { font-size: 12px; color: #64748b; margin-top: 3px; }
.pipeline-body { display: flex; flex-direction: column; }
.section-title { margin: 4px 0 8px; font-size: 12px; font-weight: 650; color: #64748b; }
.runtime-title { margin-top: 22px; }
.empty-note { padding: 8px 0; color: #94a3b8; font-size: 12px; }
.stage { display: flex; gap: 10px; padding: 6px 0; opacity: 0.4; }
.stage.active, .stage.done, .stage.error, .stage.configured, .stage.stopped { opacity: 1; }
.dot {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid #cbd5e1; flex-shrink: 0; margin-top: 1px; position: relative;
}
.stage.active .dot { border-color: #3b82f6; background: #eff6ff; }
.stage.configured .dot { border-color: #3b82f6; background: #eff6ff; }
.stage.done .dot { border-color: #10b981; background: #10b981; }
.stage.error .dot { border-color: #ef4444; background: #fef2f2; }
.stage.stopped .dot { border-color: #f59e0b; background: #fffbeb; }
.stage.error .dot::after {
  content: "×"; position: absolute; inset: 0;
  color: #ef4444; font-size: 13px; font-weight: 700; line-height: 15px; text-align: center;
}
.stage.error .stage-name { color: #b91c1c; }
.stage.error .stage-detail { color: #dc2626; }
.stage.done .dot::after {
  content: ""; position: absolute; left: 5px; top: 2px;
  width: 4px; height: 8px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg);
}
.stage-name { font-size: 13px; font-weight: 500; color: #0f172a; }
.stage-detail { font-size: 11px; color: #64748b; margin-top: 2px; line-height: 1.5; white-space: pre-wrap; }
.connector { width: 2px; height: 14px; background: #e2e8f0; margin-left: 8px; }
.connector.done { background: #10b981; }
@media (prefers-reduced-motion: reduce) {
  .pipeline-sidebar { transition: none; }
}
</style>
