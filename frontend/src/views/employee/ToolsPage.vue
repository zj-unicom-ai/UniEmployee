<!-- 员工详情 · 工具选择页：勾选该员工可用的原子工具（审批工具带提示） -->
<template>
  <ResourcePicker
    :employee="employee" field-key="tools" title="工具 Tools"
    hint="勾选「start_refund」等需审批工具会自动启用人工审批拦截；get_current_time 为全局工具，所有员工默认可用。"
    :items="items" @changed="$emit('changed')"
  />
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../../api.js'
import ResourcePicker from '../../components/employee/ResourcePicker.vue'

defineOptions({ name: 'ToolsPage' })
defineProps({ employee: Object })
defineEmits(['changed'])

const items = ref([])

onMounted(async () => {
  const { data } = await api.get('/admin/catalog')
  items.value = (data.tools || []).map(t => {
    const tags = []
    if (t.is_global) tags.push({ label: '全局默认', type: 'info' })
    if (t.needs_approval) tags.push({ label: '需人工审批', type: 'warn' })
    return { id: t.id, name: t.name, description: t.description, tags }
  })
})
</script>
