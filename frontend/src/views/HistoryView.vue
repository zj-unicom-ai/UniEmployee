<!-- 会话历史：分页表格展示所有历史对话，支持按员工筛选和翻页 -->
<template>
  <div class="hist-page">
    <div class="hist-toolbar">
      <n-select v-model:value="empFilter" :options="empOptions" placeholder="全部员工" clearable size="small" style="width:200px" @update:value="onFilterChange" />
      <n-input v-model:value="searchTerm" clearable size="small" class="search-input" placeholder="搜索标题或摘要" :input-props="{ 'aria-label': '搜索会话' }" @update:value="onSearchChange" />
      <n-select v-model:value="archiveFilter" :options="archiveOptions" size="small" style="width:120px" @update:value="onFilterChange" />
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
    <n-modal v-model:show="renameOpen" preset="card" title="重命名会话" style="width:min(420px, calc(100vw - 32px))">
      <n-input v-model:value="renameTitle" maxlength="60" show-count placeholder="输入会话名称" @keyup.enter="saveRename" />
      <template #footer>
        <div class="modal-actions">
          <n-button @click="renameOpen = false">取消</n-button>
          <n-button type="primary" :disabled="!renameTitle.trim()" @click="saveRename">保存</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, h, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NTag, NSpace, useDialog, useMessage } from 'naive-ui'
import api from '../api.js'
import PaginationBar from '../components/PaginationBar.vue'
import { routeNameForEmployee } from '../utils/employeeRoutes.js'

defineOptions({ name: 'HistoryView' })

const router = useRouter()
const dialog = useDialog()
const message = useMessage()

const employees = ref([])
const empNames = reactive({})
const convList = ref([])
const total = ref(0)
const loading = ref(true)
const empFilter = ref(null)
const page = ref(1)
const pageSize = ref(10)
const searchTerm = ref('')
const archiveFilter = ref('active')
const archiveOptions = [
  { label: '未归档', value: 'active' },
  { label: '已归档', value: 'archived' },
]
const renameOpen = ref(false)
const renameTitle = ref('')
const renameId = ref('')
let searchTimer = null
let requestSeq = 0

const empOptions = computed(() => employees.value.map(e => ({ label: e.name, value: e.id })))

function fmtTime(s) { return (s || '').replace('T', ' ').slice(5, 16) }

const columns = computed(() => [
  {
    title: '标题',
    key: 'title',
    render: (row) => h('a', {
      style: 'color:#3b82f6;font-weight:500;cursor:pointer;text-decoration:none',
      // 按员工类型分流：定制型员工（如 xiaoshu）跳专属对话路由，编排型跳 chat
      onClick: () => router.push({ name: routeNameForEmployee(row.employee_id), query: { conv: row.conv_id } }),
    }, `${row.pinned ? '置顶 · ' : ''}${(row.title && row.title.trim()) ? row.title : (row.preview || '新对话')}`),
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
    width: 320,
    render: (row) => h(NSpace, { size: 'small' }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => beginRename(row) }, { default: () => '重命名' }),
        ...(!row.archived_at ? [h(NButton, { size: 'tiny', quaternary: true, onClick: () => updateConv(row, { pinned: !row.pinned }) }, { default: () => row.pinned ? '取消置顶' : '置顶' })] : []),
        h(NButton, { size: 'tiny', quaternary: true, onClick: () => updateConv(row, { archived: !row.archived_at }) }, { default: () => row.archived_at ? '移出归档' : '归档' }),
        h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => router.push({ name: 'trace', query: { conv: row.conv_id } }) }, { default: () => '执行过程' }),
        h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => confirmDelete(row) }, { default: () => '删除' }),
      ],
    }),
  },
])

function confirmDelete(row) {
  dialog.warning({
    title: '删除会话',
    content: `确定删除会话「${(row.title || row.conv_id).slice(0, 40)}」？会话将从列表移除。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: () => deleteConv(row.conv_id),
  })
}

async function deleteConv(cid) {
  try {
    const { data } = await api.delete(`/conversations/${cid}`)
    if (data.error) { message.error(data.error); return }
    await loadConversations()
  } catch (e) { message.error(e.response?.data?.detail || '删除失败') }
}

function beginRename(row) {
  renameId.value = row.conv_id
  renameTitle.value = row.title || row.preview || ''
  renameOpen.value = true
}

async function saveRename() {
  const title = renameTitle.value.trim()
  if (!title || !renameId.value) return
  if (await updateConv({ conv_id: renameId.value }, { title })) renameOpen.value = false
}

async function updateConv(row, changes) {
  try {
    await api.patch(`/conversations/${row.conv_id}`, changes)
    await loadConversations()
    message.success('会话已更新')
    return true
  } catch (e) {
    message.error(e.response?.data?.detail || '会话操作失败')
    return false
  }
}

async function loadEmployees() {
  try {
    const { data } = await api.get('/employees')
    employees.value = data
    data.forEach(e => { empNames[e.id] = e.name })
  } catch {}
}

async function loadConversations() {
  const seq = ++requestSeq
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value,
      q: searchTerm.value.trim(), archived: archiveFilter.value === 'archived' }
    if (empFilter.value) params.employee_id = empFilter.value
    const { data } = await api.get('/conversations', { params })
    if (seq !== requestSeq) return
    if (!data.items?.length && page.value > 1) {
      page.value--
      await loadConversations()
      return
    }
    convList.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    if (seq === requestSeq) message.error(e.response?.data?.detail || '会话加载失败')
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function onFilterChange() {
  clearTimeout(searchTimer)
  page.value = 1
  loadConversations()
}

function onSearchChange(value) {
  searchTerm.value = value || ''
  clearTimeout(searchTimer)
  requestSeq++
  searchTimer = setTimeout(() => {
    page.value = 1
    loadConversations()
  }, 300)
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
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  requestSeq++
})
</script>

<style scoped>
.hist-page { padding: 24px; }
.hist-toolbar { display: flex; align-items: center; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
.search-input { width: min(320px, 100%); }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
