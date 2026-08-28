<!-- 用户管理：组织树 + 用户列表 CRUD + 员工分配管理 + 密码重置 -->
<template>
  <div class="users-page">
    <div class="users-layout">
      <!-- 左侧：组织树 -->
      <div class="org-panel">
        <div class="org-toolbar">
          <span class="org-title">组织架构</span>
          <n-button size="tiny" quaternary type="primary" @click="openOrgCreate(null)">+ 部门</n-button>
        </div>
        <n-tree
          block-line
          :data="orgTree"
          :selected-keys="selectedOrg ? [selectedOrg] : []"
          :default-expand-all="true"
          key-field="id"
          label-field="label"
          children-field="children"
          :render-suffix="renderOrgSuffix"
          @update:selected-keys="onOrgSelect"
        />
      </div>

      <!-- 右侧：用户列表 -->
      <div class="user-panel">
        <div class="users-toolbar">
          <span class="users-title">{{ selectedOrgName ? `${selectedOrgName} · 用户` : '全部用户' }}</span>
          <n-button size="small" type="primary" @click="openCreate">+ 新建用户</n-button>
        </div>

        <n-data-table :columns="columns" :data="users" :bordered="false" size="small" />
        <PaginationBar
          :page="page"
          :page-size="pageSize"
          :total="total"
          @update:page="onPageChange"
        />
      </div>
    </div>

    <!-- 新建用户弹窗 -->
    <n-modal v-model:show="createModal" preset="card" title="新建用户" style="width:400px">
      <n-form label-placement="left" :label-width="70" size="small">
        <n-form-item label="用户名"><n-input v-model:value="createForm.username" placeholder="登录用户名" /></n-form-item>
        <n-form-item label="密码"><n-input v-model:value="createForm.password" type="password" placeholder="初始密码" /></n-form-item>
        <n-form-item label="角色">
          <n-select v-model:value="createForm.role" :options="[{label:'普通用户（user）',value:'user'},{label:'管理员（admin）',value:'admin'}]" />
        </n-form-item>
        <n-form-item label="部门">
          <n-tree-select
            v-model:value="createForm.org_id"
            :options="orgTreeSelect"
            placeholder="不归属任何部门"
            clearable
          />
        </n-form-item>
      </n-form>
      <template #footer><n-space><n-button @click="createModal=false">取消</n-button><n-button type="primary" @click="doCreate">创建</n-button></n-space></template>
    </n-modal>

    <!-- 调整部门弹窗 -->
    <n-modal v-model:show="orgMoveModal" preset="card" :title="`调整部门 · ${orgMoveTarget.name}`" style="width:400px">
      <n-form label-placement="left" :label-width="70" size="small">
        <n-form-item label="部门">
          <n-tree-select
            v-model:value="orgMoveForm.org_id"
            :options="orgTreeSelect"
            placeholder="不归属任何部门"
            clearable
          />
        </n-form-item>
      </n-form>
      <template #footer><n-space><n-button @click="orgMoveModal=false">取消</n-button><n-button type="primary" @click="doOrgMove">保存</n-button></n-space></template>
    </n-modal>

    <!-- 重置密码弹窗 -->
    <n-modal v-model:show="pwModal" preset="card" :title="`重置密码 · ${pwTarget.name}`" style="width:400px">
      <n-form label-placement="left" :label-width="70" size="small">
        <n-form-item label="新密码"><n-input v-model:value="pwForm.password" type="password" placeholder="新密码" /></n-form-item>
      </n-form>
      <template #footer><n-space><n-button @click="pwModal=false">取消</n-button><n-button type="primary" @click="doResetPw">确认</n-button></n-space></template>
    </n-modal>

    <!-- 分配员工弹窗 -->
    <n-modal v-model:show="assignModal" preset="card" :title="`分配数字员工 · ${assignTarget.name}`" style="width:560px">
      <p class="assign-hint">勾选=分配该数字员工给此用户，取消勾选=取消分配。普通用户只能使用被分配的数字员工。</p>
      <div class="assign-list">
        <div v-for="e in assignList" :key="e.employee_id" class="assign-item">
          <n-checkbox v-model:checked="e.granted">
            <span class="assign-name">{{ e.name }}</span>
            <span class="assign-id">{{ e.employee_id }}</span>
          </n-checkbox>
        </div>
      </div>
      <template #footer><n-space><n-button @click="assignModal=false">取消</n-button><n-button type="primary" @click="doSaveAssign">保存分配</n-button></n-space></template>
    </n-modal>

    <!-- 部门编辑弹窗（新建/重命名） -->
    <n-modal v-model:show="orgEditModal" preset="card" :title="orgEditForm.id ? '编辑部门' : '新建部门'" style="width:400px">
      <n-form label-placement="left" :label-width="70" size="small">
        <n-form-item label="名称"><n-input v-model:value="orgEditForm.name" placeholder="部门名称" /></n-form-item>
        <n-form-item label="上级部门">
          <n-tree-select
            v-model:value="orgEditForm.parent_id"
            :options="orgTreeSelectForEdit"
            placeholder="作为顶级部门"
            clearable
          />
        </n-form-item>
      </n-form>
      <template #footer><n-space><n-button @click="orgEditModal=false">取消</n-button><n-button type="primary" @click="doOrgEditSave">保存</n-button></n-space></template>
    </n-modal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, h, onMounted } from 'vue'
import { NButton, NTag, NSpace, NDropdown, useDialog, useMessage } from 'naive-ui'
import { useAuthStore } from '../stores/auth.js'
import api from '../api.js'
import PaginationBar from '../components/PaginationBar.vue'

defineOptions({ name: 'UsersView' })

const dialog = useDialog()
const message = useMessage()
const auth = useAuthStore()

const users = ref([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const loading = ref(false)

// 组织树
const orgs = ref([])
const selectedOrg = ref(null)   // null = 全部用户

// 新建用户
const createModal = ref(false)
const createForm = reactive({ username: '', password: '', role: 'user', org_id: null })

// 调整用户部门
const orgMoveModal = ref(false)
const orgMoveTarget = reactive({ id: '', name: '' })
const orgMoveForm = reactive({ org_id: null })

// 部门编辑（新建/重命名）
const orgEditModal = ref(false)
const orgEditForm = reactive({ id: '', name: '', parent_id: null })

// 重置密码
const pwModal = ref(false)
const pwTarget = reactive({ id: '', name: '' })
const pwForm = reactive({ password: '' })

// 分配员工
const assignModal = ref(false)
const assignTarget = reactive({ id: '', name: '' })
const assignList = ref([])

function fmtTime(s) { return (s || '').replace(' ', ' ').slice(5, 16) }

// ---- 组织树 ----

const orgTree = computed(() => buildTree(null))

function buildTree(parentId) {
  return orgs.value
    .filter(o => (o.parent_id || null) === parentId)
    .map(o => {
      const children = buildTree(o.id)
      return {
        id: o.id,
        label: o.name,
        member_count: o.member_count,
        children: children.length ? children : undefined,
        isLeaf: !children.length,
      }
    })
}

// TreeSelect 选项（用户归属选择，可清空=不归属）
const orgTreeSelect = computed(() => toSelectOptions(orgTree.value))

function toSelectOptions(nodes) {
  return (nodes || []).map(n => ({
    key: n.id, label: n.label, children: toSelectOptions(n.children),
  }))
}

// 编辑部门时的父部门选项（排除自身及其子树，防环）
const orgTreeSelectForEdit = computed(() => {
  if (!orgEditForm.id) return orgTreeSelect.value
  const excluded = new Set([orgEditForm.id])
  const collect = (nodes) => (nodes || []).filter(n => {
    if (excluded.has(n.id)) { collectChildren(n); return false }
    return true
  }).map(n => ({ key: n.key, label: n.label, children: collect(n.children) }))
  const collectChildren = (n) => (n.children || []).forEach(c => { excluded.add(c.id); collectChildren(c) })
  return collect(orgTree.value)
})

const selectedOrgName = computed(() => {
  const o = orgs.value.find(x => x.id === selectedOrg.value)
  return o ? o.name : ''
})

function renderOrgSuffix({ option }) {
  return h('div', { class: 'org-node-actions' }, [
    h('span', { class: 'org-count' }, option.member_count ? `${option.member_count}人` : ''),
    h(NDropdown, {
      trigger: 'click',
      size: 'small',
      options: [
        { label: '新建子部门', key: 'add' },
        { label: '重命名', key: 'rename' },
        { label: '删除', key: 'del' },
      ],
      onSelect: (key) => onOrgAction(key, option),
    }, { default: () => h('span', { class: 'org-more' }, '···') }),
  ])
}

function onOrgAction(key, node) {
  if (key === 'add') openOrgCreate(node.id)
  else if (key === 'rename') openOrgRename(node.id)
  else if (key === 'del') delOrg(node.id)
}

function onOrgSelect(keys) {
  selectedOrg.value = keys[0] || null
  page.value = 1
  loadUsers()
}

async function loadOrgs() {
  try {
    const { data } = await api.get('/admin/orgs')
    orgs.value = data || []
  } catch {}
}

function openOrgCreate(parentId) {
  orgEditForm.id = ''
  orgEditForm.name = ''
  orgEditForm.parent_id = parentId || null
  orgEditModal.value = true
}

function openOrgRename(orgId) {
  const o = orgs.value.find(x => x.id === orgId)
  if (!o) return
  orgEditForm.id = orgId
  orgEditForm.name = o.name
  orgEditForm.parent_id = o.parent_id || null
  orgEditModal.value = true
}

async function doOrgEditSave() {
  if (!orgEditForm.name.trim()) { message.warning('请填写部门名称'); return }
  try {
    const body = { name: orgEditForm.name.trim(), parent_id: orgEditForm.parent_id || null }
    let res
    if (orgEditForm.id) {
      // 编辑：parent_id 变化时带 move 标记
      const o = orgs.value.find(x => x.id === orgEditForm.id)
      const moved = (o.parent_id || null) !== body.parent_id
      res = await api.put(`/admin/orgs/${orgEditForm.id}`, { ...body, move: moved })
    } else {
      res = await api.post('/admin/orgs', body)
    }
    if (res.data.error) { message.error(res.data.error); return }
    message.success('已保存')
    orgEditModal.value = false
    await loadOrgs()
  } catch (e) { message.error('保存失败：' + e.message) }
}

function delOrg(orgId) {
  const o = orgs.value.find(x => x.id === orgId)
  if (!o) return
  dialog.warning({
    title: '删除部门', content: `确认删除部门「${o.name}」？需先清空其子部门与成员。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try {
        const { data } = await api.delete(`/admin/orgs/${orgId}`)
        if (data.error) { message.error(data.error); return }
        message.success('已删除')
        if (selectedOrg.value === orgId) selectedOrg.value = null
        await loadOrgs()
        await loadUsers()
      } catch (e) { message.error(e.message) }
    },
  })
}

// ---- 用户列表 ----

const columns = computed(() => [
  {
    title: '用户名', key: 'username',
    render: (row) => h('span', null, [
      row.username,
      row.id === 'u_admin' ? h('span', { style: 'color:#94a3b8;font-size:11px;margin-left:6px' }, '(初始)') : null,
    ]),
  },
  {
    title: '部门', key: 'org_name', width: 140,
    render: (row) => row.org_name
      ? h(NTag, { size: 'small', round: true, bordered: false }, { default: () => row.org_name })
      : h('span', { style: 'color:#cbd5e1' }, '—'),
  },
  {
    title: '角色', key: 'role', width: 100,
    render: (row) => h(NTag, { type: row.role === 'admin' ? 'warning' : 'success', size: 'small', round: true, bordered: false }, { default: () => row.role }),
  },
  {
    title: '状态', key: 'status', width: 80,
    render: (row) => h(NTag, { type: row.status === 'active' ? 'success' : 'error', size: 'small', round: true, bordered: false }, { default: () => row.status === 'active' ? '正常' : '禁用' }),
  },
  { title: '创建时间', key: 'created_at', width: 120, render: (row) => fmtTime(row.created_at) },
  {
    title: '操作', key: 'actions', width: 320,
    render: (row) => {
      const isSelf = row.id === auth.user?.id
      return h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => openAssign(row) }, { default: () => '分配员工' }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => openOrgMove(row) }, { default: () => '调部门' }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => openResetPw(row) }, { default: () => '改密' }),
          h(NButton, { size: 'tiny', quaternary: true, onClick: () => toggleStatus(row) }, { default: () => row.status === 'active' ? '禁用' : '启用' }),
          h(NButton, { size: 'tiny', quaternary: true, type: 'error', disabled: isSelf, onClick: () => delUser(row) }, { default: () => '删除' }),
        ],
      })
    },
  },
])

async function loadUsers() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (selectedOrg.value) params.org_id = selectedOrg.value
    const { data } = await api.get('/admin/users', { params })
    users.value = data.items || []
    total.value = data.total || 0
  } catch {} finally { loading.value = false }
}

function onPageChange(p) {
  page.value = p
  loadUsers()
}

function openCreate() {
  createForm.username = ''; createForm.password = ''; createForm.role = 'user'
  // 默认选中当前筛选的部门
  createForm.org_id = selectedOrg.value || null
  createModal.value = true
}

async function doCreate() {
  if (!createForm.username || !createForm.password) { message.warning('请填写用户名和密码'); return }
  try {
    const { data } = await api.post('/admin/users', { ...createForm })
    if (data.error) { message.error(data.error); return }
    message.success('已创建')
    createModal.value = false
    await Promise.all([loadUsers(), loadOrgs()])
  } catch (e) { message.error('创建失败：' + e.message) }
}

function openOrgMove(row) {
  orgMoveTarget.id = row.id; orgMoveTarget.name = row.username
  orgMoveForm.org_id = row.org_id || null
  orgMoveModal.value = true
}

async function doOrgMove() {
  try {
    const { data } = await api.put(`/admin/users/${orgMoveTarget.id}`, {
      org_id: orgMoveForm.org_id || null, set_org: true,
    })
    if (data.error) { message.error(data.error); return }
    message.success('已调整部门')
    orgMoveModal.value = false
    await Promise.all([loadUsers(), loadOrgs()])
  } catch (e) { message.error('调整失败：' + e.message) }
}

function openResetPw(row) {
  pwTarget.id = row.id; pwTarget.name = row.username
  pwForm.password = ''
  pwModal.value = true
}

async function doResetPw() {
  if (!pwForm.password) { message.warning('请输入新密码'); return }
  try {
    const { data } = await api.put(`/admin/users/${pwTarget.id}/password`, { password: pwForm.password })
    if (data.error) { message.error(data.error); return }
    message.success('已改密')
    pwModal.value = false
  } catch (e) { message.error('改密失败：' + e.message) }
}

async function toggleStatus(row) {
  const ns = row.status === 'active' ? 'disabled' : 'active'
  if (ns === 'disabled') {
    dialog.warning({
      title: '禁用用户', content: `确认禁用用户「${row.username}」？禁用后该用户无法登录。`,
      positiveText: '禁用', negativeText: '取消',
      onPositiveClick: async () => {
        try { await api.put(`/admin/users/${row.id}`, { status: ns }); message.success('已禁用'); await loadUsers() } catch (e) { message.error(e.message) }
      },
    })
  } else {
    try { await api.put(`/admin/users/${row.id}`, { status: ns }); message.success('已启用'); await loadUsers() } catch (e) { message.error(e.message) }
  }
}

function delUser(row) {
  dialog.warning({
    title: '删除用户', content: `确认删除用户「${row.username}」？该操作不可恢复。`,
    positiveText: '删除', negativeText: '取消',
    onPositiveClick: async () => {
      try { await api.delete(`/admin/users/${row.id}`); message.success('已删除'); await Promise.all([loadUsers(), loadOrgs()]) } catch (e) { message.error(e.message) }
    },
  })
}

async function openAssign(row) {
  assignTarget.id = row.id; assignTarget.name = row.username
  try {
    const { data } = await api.get(`/admin/users/${row.id}/employees`)
    if (data.error) { message.error(data.error); return }
    assignList.value = (data.employees || []).map(e => ({ ...e, granted: !!e.granted, _wasGranted: !!e.granted }))
    assignModal.value = true
  } catch (e) { message.error('加载失败：' + e.message) }
}

async function doSaveAssign() {
  const uid = assignTarget.id
  try {
    for (const e of assignList.value) {
      if (e.granted && !e._wasGranted) {
        await api.post(`/admin/users/${uid}/employees`, { employee_id: e.employee_id, overrides: {} })
      } else if (!e.granted && e._wasGranted) {
        await api.delete(`/admin/users/${uid}/employees/${e.employee_id}`)
      }
    }
    message.success('已保存分配')
    assignModal.value = false
  } catch (e) { message.error('保存失败：' + e.message) }
}

onMounted(async () => {
  await loadOrgs()
  await loadUsers()
})
</script>

<style scoped>
.users-page { padding: 24px; }
.users-layout { display: flex; gap: 16px; align-items: flex-start; }
.org-panel {
  width: 240px; flex-shrink: 0; padding: 12px;
  border: 1px solid #e2e8f0; border-radius: 10px;
  background: #fff; max-height: calc(100vh - 140px); overflow-y: auto;
}
.org-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.org-title { font-size: 13px; font-weight: 600; color: #0f172a; }
.org-node-actions { display: flex; align-items: center; gap: 6px; }
.org-count { font-size: 11px; color: #94a3b8; }
.org-more {
  cursor: pointer; color: #94a3b8; font-weight: 700; letter-spacing: 1px;
  padding: 0 4px; border-radius: 4px;
}
.org-more:hover { color: #2563eb; background: #eff6ff; }
.user-panel { flex: 1; min-width: 0; }
.users-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.users-title { font-size: 15px; font-weight: 600; color: #0f172a; flex: 1; }
.assign-hint { font-size: 13px; color: #64748b; margin-bottom: 16px; line-height: 1.6; }
.assign-list { display: flex; flex-direction: column; gap: 8px; }
.assign-item { padding: 10px 12px; border: 1px solid #e2e8f0; border-radius: 8px; }
.assign-name { font-weight: 500; color: #0f172a; }
.assign-id { color: #94a3b8; font-size: 12px; margin-left: 8px; }
</style>
