<!-- 通用资源勾选组件：搜索 + 全选/清空 + 勾选列表 + 独立保存。
     供技能/工具/SOP 等结构化列表页复用；知识库/连接器等需要差异化展示的页面自建布局。 -->
<template>
  <div class="picker">
    <div class="picker-head">
      <div>
        <div class="picker-title">{{ title }}<span class="picker-count">已选 {{ selectedSet.size }} / {{ items.length }}</span></div>
        <div v-if="hint" class="picker-hint">{{ hint }}</div>
      </div>
      <div class="picker-ops">
        <n-input v-model:value="keyword" size="small" clearable placeholder="搜索名称/描述…" style="width: 200px" />
        <n-button size="small" quaternary @click="selectAll(true)">全选</n-button>
        <n-button size="small" quaternary @click="selectAll(false)">清空</n-button>
      </div>
    </div>

    <div v-if="!filtered.length" class="picker-empty">{{ keyword ? '无匹配项' : '暂无可选项' }}</div>
    <div v-else class="picker-list">
      <label
        v-for="it in filtered" :key="it.id"
        class="picker-item" :class="{ on: selectedSet.has(it.id) }"
      >
        <input type="checkbox" :checked="selectedSet.has(it.id)" @change="toggle(it.id, $event)" />
        <div class="item-main">
          <div class="item-name">
            {{ it.name }}
            <span v-for="t in it.tags || []" :key="t.label" class="item-tag" :class="t.type">{{ t.label }}</span>
          </div>
          <div v-if="it.description" class="item-desc">{{ it.description }}</div>
        </div>
      </label>
    </div>

    <div class="picker-foot">
      <n-button type="primary" size="small" :loading="saving" :disabled="!dirty" @click="save">
        保存{{ dirty ? '（有未保存修改）' : '' }}
      </n-button>
      <n-button v-if="dirty" size="small" quaternary @click="reset">还原</n-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'ResourcePicker' })

const props = defineProps({
  employee: { type: Object, required: true },
  fieldKey: { type: String, required: true },   // PUT 的字段名：skills / tools / sops
  title: { type: String, required: true },
  hint: { type: String, default: '' },
  items: { type: Array, default: () => [] },    // [{id, name, description, tags:[{label,type}]}]
})
const emit = defineEmits(['changed'])

const message = useMessage()
const keyword = ref('')
const saving = ref(false)
const selectedSet = ref(new Set())

const initialIds = computed(() => new Set(props.employee?.[props.fieldKey] || []))
const dirty = computed(() =>
  selectedSet.value.size !== initialIds.value.size ||
  [...selectedSet.value].some(id => !initialIds.value.has(id)))

watch(() => props.employee, () => reset(), { immediate: true })

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return props.items
  return props.items.filter(it =>
    (it.name || '').toLowerCase().includes(kw) ||
    (it.description || '').toLowerCase().includes(kw))
})

function reset() {
  selectedSet.value = new Set(props.employee?.[props.fieldKey] || [])
}

function toggle(id, e) {
  const s = new Set(selectedSet.value)
  if (e.target.checked) s.add(id)
  else s.delete(id)
  selectedSet.value = s
}

function selectAll(on) {
  selectedSet.value = on
    ? new Set(props.items.map(it => it.id))
    : new Set()
}

async function save() {
  saving.value = true
  try {
    const { data } = await api.put(`/admin/employees/${props.employee.id}`, {
      [props.fieldKey]: [...selectedSet.value],
    })
    if (data.error) { message.error('保存失败：' + data.error); return }
    message.success('已保存')
    emit('changed')
  } catch (e) {
    message.error('保存出错：' + e.message)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.picker { max-width: 860px; }
.picker-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.picker-title { font-size: 14px; font-weight: 600; color: #334155; }
.picker-count { font-size: 12px; font-weight: 400; color: #94a3b8; margin-left: 10px; }
.picker-hint { font-size: 12px; color: #94a3b8; margin-top: 4px; line-height: 1.6; max-width: 520px; }
.picker-ops { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.picker-empty { font-size: 13px; color: #94a3b8; padding: 32px 0; text-align: center; background: #fafbfc; border-radius: 8px; }
.picker-list { display: flex; flex-direction: column; gap: 8px; }
.picker-item { display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; cursor: pointer; transition: all 0.15s; }
.picker-item:hover { border-color: #93c5fd; }
.picker-item.on { background: #eff6ff; border-color: #3b82f6; }
.picker-item input { margin-top: 3px; accent-color: #3b82f6; }
.item-main { flex: 1; min-width: 0; }
.item-name { font-size: 13px; font-weight: 500; color: #0f172a; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.item-desc { font-size: 12px; color: #64748b; margin-top: 3px; line-height: 1.5; }
.item-tag { font-size: 10px; padding: 1px 7px; border-radius: 8px; background: #f1f5f9; color: #64748b; font-weight: 400; }
.item-tag.warn { background: #fffbeb; color: #b45309; }
.item-tag.info { background: #ecfeff; color: #0e7490; }
.picker-foot { margin-top: 14px; display: flex; gap: 8px; }
</style>
