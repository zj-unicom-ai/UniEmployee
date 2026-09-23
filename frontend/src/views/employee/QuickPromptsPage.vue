<!-- 员工详情 · 快捷问法配置：每名员工最多维护 3 条欢迎区问题 -->
<template>
  <div class="quick-prompts-page">
    <div class="page-intro">
      <div>
        <h2>新对话快捷问法</h2>
        <p>这些问题会显示在 {{ employee?.name || '该员工' }} 的新对话欢迎区。留空时不显示通用问题。</p>
      </div>
      <span class="count-pill">{{ filledCount }} / 3 条</span>
    </div>

    <div class="prompt-list">
      <section v-for="(prompt, index) in prompts" :key="index" class="prompt-slot">
        <div class="slot-index">{{ String(index + 1).padStart(2, '0') }}</div>
        <div class="slot-field">
          <div class="slot-label">快捷问题 {{ index + 1 }}</div>
          <n-input
            v-model:value="prompts[index]"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 4 }"
            maxlength="160"
            show-count
            :placeholder="`输入适合 ${employee?.name || '该员工'} 的常见问题；留空则不显示`"
          />
        </div>
      </section>
    </div>

    <div class="page-foot">
      <span>访客点击问题后会立即发送给该员工。</span>
      <n-button type="primary" :loading="saving" @click="save">保存快捷问法</n-button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'QuickPromptsPage' })
const props = defineProps({ employee: Object })
const emit = defineEmits(['changed'])
const message = useMessage()
const prompts = ref(['', '', ''])
const saving = ref(false)
const filledCount = computed(() => prompts.value.filter(x => x.trim()).length)

watch(() => props.employee, (employee) => {
  const saved = Array.isArray(employee?.quick_prompts) ? employee.quick_prompts.slice(0, 3) : []
  prompts.value = [saved[0] || '', saved[1] || '', saved[2] || '']
}, { immediate: true })

async function save() {
  const values = prompts.value.map(x => x.trim()).filter(Boolean)
  if (values.length > 3) return
  saving.value = true
  try {
    const { data } = await api.put(`/admin/employees/${props.employee.id}/quick-prompts`, { prompts: values })
    if (data.error) { message.error(data.error); return }
    prompts.value = [data.prompts[0] || '', data.prompts[1] || '', data.prompts[2] || '']
    message.success('快捷问法已保存')
    emit('changed')
  } catch (e) {
    message.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.quick-prompts-page { max-width: 880px; }
.page-intro { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin: 4px 0 20px; }
.page-intro h2 { margin: 0; color: #0f172a; font-size: 16px; font-weight: 650; }
.page-intro p { margin: 6px 0 0; color: #64748b; font-size: 12px; line-height: 1.6; }
.count-pill { flex: 0 0 auto; border-radius: 999px; padding: 4px 10px; color: #1d4ed8; background: #eff6ff; font-size: 12px; font-weight: 600; }
.prompt-list { display: flex; flex-direction: column; gap: 12px; }
.prompt-slot { display: flex; align-items: flex-start; gap: 12px; padding: 14px; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; }
.slot-index { display: grid; width: 30px; height: 30px; place-items: center; flex: 0 0 auto; border-radius: 8px; color: #2563eb; background: #eff6ff; font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.slot-field { min-width: 0; flex: 1; }
.slot-label { margin: 1px 0 7px; color: #334155; font-size: 12px; font-weight: 600; }
.page-foot { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-top: 18px; color: #94a3b8; font-size: 12px; }
@media (max-width: 560px) { .page-intro, .page-foot { align-items: stretch; flex-direction: column; } .count-pill { align-self: flex-start; } }
</style>
