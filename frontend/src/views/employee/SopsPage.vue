<!-- 员工详情 · SOP 选择页：勾选该员工遵循的 SOP 流程文档（可展开预览内容） -->
<template>
  <ResourcePicker
    :employee="employee" field-key="sops" title="SOP 流程文档"
    hint="勾选后 SOP 全文会同步进员工 Store，运行时 read_file 查阅；SOP 编辑在「资源中心」进行。"
    :items="items" @changed="$emit('changed')"
  />
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../../api.js'
import ResourcePicker from '../../components/employee/ResourcePicker.vue'

defineOptions({ name: 'SopsPage' })
defineProps({ employee: Object })
defineEmits(['changed'])

const items = ref([])

onMounted(async () => {
  const { data } = await api.get('/admin/catalog')
  items.value = (data.sops || []).map(s => {
    const firstLine = (s.content || '').split('\n').find(l => l.trim()) || ''
    return {
      id: s.id, name: s.name,
      description: firstLine.slice(0, 120) || s.description,
      tags: s.content ? [{ label: `${s.content.length} 字` }] : [],
    }
  })
})
</script>
