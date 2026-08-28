<!-- 员工详情 · 技能选择页：勾选该员工可用的技能（SKILL.md 规程，运行时 read_file 查阅） -->
<template>
  <ResourcePicker
    :employee="employee" field-key="skills" title="技能 Skills"
    hint="勾选后该员工运行时可查阅对应 SKILL.md 规程；技能编辑在「资源中心」进行。"
    :items="items" @changed="$emit('changed')"
  />
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../../api.js'
import ResourcePicker from '../../components/employee/ResourcePicker.vue'

defineOptions({ name: 'SkillsPage' })
defineProps({ employee: Object })
defineEmits(['changed'])

const items = ref([])

onMounted(async () => {
  const { data } = await api.get('/admin/catalog')
  items.value = (data.skills || []).map(s => ({
    id: s.id, name: s.name, description: s.description,
    tags: s.is_custom ? [{ label: '自定义' }] : [],
  }))
})
</script>
