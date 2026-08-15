<!-- 会话历史：分页表格展示所有历史对话，支持按员工筛选和翻页 -->
<template>
  <div class="hist-page">
    <div class="hist-toolbar">
      <n-select v-model:value="empFilter" :options="empOptions" placeholder="全部员工" clearable size="small" style="width:200px" @update:value="onFilterChange" />
    </div>

    <n-data-table
      :columns="columns"
      :data="convList"
      :loading="loading"
      :bordered="false"
      size="small"
    />
    <PaginationBar
      :page="page"
      :page-size="pageSize"
      :total="total"
      @update:page="onPageChange"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, h, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, NSpace, useDialog } from 'naive-ui'
import api from '../api.js'
import PaginationBar from '../components/PaginationBar.vue'

defineOptions({ name: 'HistoryView' })

const router = useRouter()
const dialog = useDialog()

const employees = ref([])
const empNames = reactive({})
const convList = ref([])
const total = ref(0)
const loading = ref(true)
const empFilter = ref(null)
const page = ref(1)
const pageSize = ref(10)

const empOptions = computed(() => employees.value.map(e => ({ label: e.name, value: e.id })))

function fmtTime(s) { return (s || '').replace('T', ' ').slice(5, 16) }

const columns = computed(() => [
  {
    title: '标题',
    key: 'title',
    render: (row) => h('a', {
      style: 'color:#3b82f6;font-weight:500;cursor:pointer;text-decoration:none',
      onClick: () => router.push({ name: 'chat', query: { conv: row.conv_id } }),
    }, (row.title && row.title.trim()) ? row.title : (row.preview || '新对话')),
  },
  {
    title: '员工',
    key: 'employee_id',
    width: 100,
    render: (row) => h(NTag, { type: 'success', size: 'small', round: true, bordered: false }, { default: () => empNames[row.employee_id] || row.employee_id }),
  },
  { title: '消息数', key: 'message_count', width: 80 },
  { title: '更新时间', key: 'updated_at', width: 120, render: (row) => fmtTime(row.updated_at) },
  {
    title: '操作',
    key: 'actions',
    width: 160,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => router.push({ name: 'trace', query: { conv: row.conv_id } }) }, { default: () => '执行过程' }),
        h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => confirmDelete(row) }, { default: () => '删除' }),
      ],
    }),
  },
])

function confirmDelete(row) {
  dialog.warning({
    title: '删除会话',
    content: `确定删除会话「${(row.title || row.conv_id).slice(0, 40)}」？该会话的全部消息将被清除，不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteConv(row.conv_id),
  })
}

async function deleteConv(cid) {
  try {
    const { data } = await api.delete(`/conversations/${cid}`)
    if (data.error) { return }
    await loadConversations()
  } catch {}
}

async function loadEmployees() {
  try {
    const { data } = await api.get('/employees')
    employees.value = data
    data.forEach(e => { empNames[e.id] = e.name })
  } catch {}
}

async function loadConversations() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (empFilter.value) params.employee_id = empFilter.value
    const { data } = await api.get('/conversations', { params })
    convList.value = data.items || []
    total.value = data.total || 0
  } catch {} finally {
    loading.value = false
  }
}

function onFilterChange() {
  page.value = 1
  loadConversations()
}

function onPageChange(p) {
  page.value = p
  loadConversations()
}

function onPageSizeChange(size) {
  pageSize.value = size
  page.value = 1
  loadConversations()
}

onMounted(async () => {
  await loadEmployees()
  await loadConversations()
})
</script>

<style scoped>
.hist-page { padding: 24px; }
.hist-toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; }
</style>
