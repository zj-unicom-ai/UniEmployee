<!-- 中栏：执行流水线状态 -->
<template>
  <div class="pipeline-sidebar">
    <div class="pipeline-title">执行流水线</div>
    <div class="pipeline-body">
      <template v-for="(s, i) in STAGES" :key="s[0]">
        <div v-if="i" class="connector" :class="{ done: states[s[0]] === 'done' }"></div>
        <div class="stage" :class="states[s[0]] || 'pending'">
          <div class="dot"></div>
          <div>
            <div class="stage-name">{{ i + 1 }}. {{ s[1] }}</div>
            <div v-if="detail[s[0]]" class="stage-detail">{{ detail[s[0]] }}</div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
defineProps({
  states: { type: Object, default: () => ({}) },
  detail: { type: Object, default: () => ({}) },
})

const STAGES = [
  ['input', '用户输入'], ['employee', 'Employee 加载'], ['sop', '加载 SOP'],
  ['skills', '加载 Skills'], ['planning', '智能体规划'], ['skill', '调用 Skill'],
  ['report', '输出回复'],
]
</script>

<style scoped>
.pipeline-sidebar {
  width: 240px;
  border-right: 1px solid #e2e8f0;
  padding: 16px;
  overflow-y: auto;
  background: #ffffff;
}
.pipeline-title { font-size: 13px; font-weight: 600; color: #334155; margin-bottom: 12px; }
.pipeline-body { display: flex; flex-direction: column; }
.stage { display: flex; gap: 10px; padding: 6px 0; opacity: 0.4; }
.stage.active, .stage.done { opacity: 1; }
.dot {
  width: 18px; height: 18px; border-radius: 50%;
  border: 2px solid #cbd5e1; flex-shrink: 0; margin-top: 1px; position: relative;
}
.stage.active .dot { border-color: #3b82f6; background: #eff6ff; }
.stage.done .dot { border-color: #10b981; background: #10b981; }
.stage.done .dot::after {
  content: ""; position: absolute; left: 5px; top: 2px;
  width: 4px; height: 8px; border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg);
}
.stage-name { font-size: 13px; font-weight: 500; color: #0f172a; }
.stage-detail { font-size: 11px; color: #64748b; margin-top: 2px; line-height: 1.5; white-space: pre-wrap; }
.connector { width: 2px; height: 14px; background: #e2e8f0; margin-left: 8px; }
.connector.done { background: #10b981; }
</style>
