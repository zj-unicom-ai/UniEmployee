<!-- 数字员工产物工作区：汇总个人产物并支持本部门显式共享。 -->
<template>
  <main class="artifact-page">
    <header class="artifact-heading">
      <div class="heading-copy">
        <div class="heading-kicker">工作成果 · 文件归档</div>
        <h1>产物工作区</h1>
        <p>集中找回数字员工生成的报告、看板和文档；账号加入部门后，可共享单个产物，原对话仍保持私有。</p>
      </div>
      <div class="heading-index" aria-hidden="true">
        <span>当前视图</span>
        <strong>{{ total.toLocaleString() }}</strong>
        <small>项产物</small>
      </div>
    </header>

    <section class="artifact-controls" aria-label="搜索和筛选产物">
      <n-input
        v-model:value="query"
        clearable
        class="artifact-search"
        placeholder="搜索文件名、员工或会话标题"
        :input-props="{ 'aria-label': '搜索产物' }"
        @update:value="onSearchChange"
      >
        <template #prefix><span class="search-glyph" aria-hidden="true">⌕</span></template>
      </n-input>
      <n-select
        :value="scope"
        :options="scopeOptions"
        class="scope-select"
        aria-label="产物范围"
        @update:value="onScopeChange"
      />
      <n-button
        quaternary
        aria-label="显示或隐藏 Python 执行脚本"
        :aria-pressed="showScripts"
        @click="toggleScriptsVisibility"
      >
        {{ showScripts ? '隐藏执行脚本' : '显示执行脚本' }}
      </n-button>
      <n-button quaternary :loading="loading" aria-label="刷新产物" @click="loadArtifacts">
        <template #icon><span aria-hidden="true">↻</span></template>
        刷新
      </n-button>
    </section>

    <section class="artifact-results" aria-live="polite">
      <div class="results-label">
        <span>{{ currentScopeLabel }}</span>
        <span class="result-count">{{ total }} 项</span>
      </div>

      <n-spin :show="loading">
        <div v-if="items.length" class="artifact-list">
          <article v-for="item in items" :key="item.artifact_id" class="artifact-row">
            <div class="file-type-mark" :class="`type-${fileKind(item.name)}`" aria-hidden="true">
              {{ fileIcon(item.name) }}
            </div>

            <div class="artifact-details">
              <div class="artifact-title-line">
                <h2 :title="item.name">{{ item.name }}</h2>
                <n-tag v-if="item.shared_with_department" size="small" type="success" :bordered="false">
                  本部门共享
                </n-tag>
                <n-tag v-else size="small" :bordered="false">未共享</n-tag>
              </div>
              <div class="artifact-subline">
                <template v-if="item.is_owner">
                  <span>{{ item.employee_id || '数字员工' }}</span>
                  <span class="subline-dot">·</span>
                  <span class="conversation-title" :title="item.conversation_title || '新对话'">
                    {{ item.conversation_title || '新对话' }}
                  </span>
                </template>
                <span v-else>同部门成员共享给你</span>
                <span class="subline-dot">·</span>
                <span>{{ fmtTime(item.created_at) }}</span>
                <span class="subline-dot">·</span>
                <span>{{ fmtSize(item.size) }}</span>
              </div>
            </div>

            <div class="artifact-actions">
              <n-button size="small" type="primary" secondary @click="preview(item)">查看</n-button>
              <n-button
                v-if="item.is_owner && (item.can_share || item.shared_with_department)"
                size="small"
                quaternary
                :loading="sharingId === item.artifact_id"
                @click="toggleDepartmentShare(item)"
              >
                {{ item.shared_with_department ? '撤销共享' : '共享到本部门' }}
              </n-button>
              <n-button
                v-if="item.is_owner && item.conv_id"
                size="small"
                quaternary
                :loading="openingConvId === item.artifact_id"
                @click="openConversation(item)"
              >
                打开对话
              </n-button>
            </div>
          </article>
        </div>

        <div v-else-if="!loading" class="artifact-empty">
          <div class="empty-mark" aria-hidden="true">▤</div>
          <h2>{{ query ? '没有匹配的产物' : emptyTitle }}</h2>
          <p>{{ query ? '试试缩短关键词，或切换产物范围。' : emptyDescription }}</p>
          <n-button v-if="scope === 'shared' && !query" quaternary @click="onScopeChange('all')">
            查看全部可见产物
          </n-button>
          <n-button v-else-if="!query" type="primary" secondary @click="router.push({ name: 'chat' })">
            前往对话工作台
          </n-button>
        </div>
      </n-spin>

      <PaginationBar
        v-if="total > pageSize"
        :page="page"
        :page-size="pageSize"
        :total="total"
        @update:page="onPageChange"
      />
    </section>

    <n-modal
      v-model:show="previewOpen"
      preset="card"
      :title="previewFile?.name || '查看产物'"
      class="artifact-preview-modal"
      :style="{ width: 'min(1120px, calc(100vw - 32px))' }"
    >
      <FileCard v-if="previewFile" :file="previewFile" />
    </n-modal>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../api.js'
import PaginationBar from '../components/PaginationBar.vue'
import FileCard from '../components/chat/FileCard.vue'
import { routeNameForEmployee } from '../utils/employeeRoutes.js'

defineOptions({ name: 'ArtifactWorkspaceView' })

const router = useRouter()
const message = useMessage()
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 15
const scope = ref('all')
const query = ref('')
const showScripts = ref(false)
const loading = ref(false)
const sharingId = ref(null)
const openingConvId = ref(null)
const previewOpen = ref(false)
const previewFile = ref(null)
const scopeOptions = [
  { label: '全部可见', value: 'all' },
  { label: '我创建的', value: 'mine' },
  { label: '部门共享给我', value: 'shared' },
]
const currentScopeLabel = computed(() => scopeOptions.find(x => x.value === scope.value)?.label || '全部可见')
const emptyTitle = computed(() => scope.value === 'shared' ? '暂时没有部门共享产物' : '这里还没有产物')
const emptyDescription = computed(() => scope.value === 'shared'
  ? '同事共享到你所在部门的文件会显示在这里。'
  : '在对话中让数字员工生成报告、看板或文档，它们会自动归档到这里。')

let searchTimer = null
let requestSeq = 0

async function loadArtifacts() {
  const seq = ++requestSeq
  loading.value = true
  try {
    const { data } = await api.get('/workspace/artifacts', {
      params: {
        q: query.value,
        scope: scope.value,
        page: page.value,
        page_size: pageSize,
        show_scripts: showScripts.value,
      },
    })
    if (seq !== requestSeq) return
    items.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    if (seq === requestSeq) message.error(error.response?.data?.detail || '产物列表加载失败')
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function onSearchChange() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    loadArtifacts()
  }, 250)
}

function onScopeChange(value) {
  scope.value = value
  page.value = 1
  loadArtifacts()
}

function toggleScriptsVisibility() {
  showScripts.value = !showScripts.value
  page.value = 1
  loadArtifacts()
}

function onPageChange(value) {
  page.value = value
  loadArtifacts()
}

function preview(item) {
  previewFile.value = { ...item, name: item.name, path: item.path }
  previewOpen.value = true
}

async function toggleDepartmentShare(item) {
  const shared = !item.shared_with_department
  sharingId.value = item.artifact_id
  try {
    await api.put(`/workspace/artifacts/${item.artifact_id}/department-share`, { shared })
    message.success(shared ? '已共享到本部门' : '已撤销部门共享')
    await loadArtifacts()
  } catch (error) {
    message.error(error.response?.data?.detail || '共享设置失败')
  } finally {
    sharingId.value = null
  }
}

async function openConversation(item) {
  if (!item.conv_id || !item.employee_id) {
    message.warning('该产物没有可打开的关联对话')
    return
  }
  openingConvId.value = item.artifact_id
  const target = { name: routeNameForEmployee(item.employee_id), query: { conv: item.conv_id } }
  try {
    const targetPath = router.resolve(target).fullPath
    await router.push(target)
    if (router.currentRoute.value.fullPath !== targetPath) {
      message.error('对话页面未成功打开，请刷新后重试')
    }
  } catch (error) {
    message.error(error?.message || '打开对话失败，请稍后重试')
  } finally {
    openingConvId.value = null
  }
}

function extension(name) { return (name || '').split('.').pop().toLowerCase() }
function fileKind(name) {
  const ext = extension(name)
  if (['html', 'htm'].includes(ext)) return 'dashboard'
  if (['csv', 'xlsx', 'xls'].includes(ext)) return 'sheet'
  if (['doc', 'docx', 'pdf', 'ppt', 'pptx'].includes(ext)) return 'document'
  return 'text'
}
function fileIcon(name) {
  return ({ dashboard: '▥', sheet: '▦', document: '▤', text: '≡' })[fileKind(name)]
}
function fmtSize(size) {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size >= 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${size || 0} B`
}
function fmtTime(value) {
  if (!value) return '时间未知'
  return value.replace('T', ' ').slice(5, 16)
}

onMounted(loadArtifacts)
onBeforeUnmount(() => clearTimeout(searchTimer))
</script>

<style scoped>
.artifact-page {
  min-height: 100%;
  max-width: 1440px;
  margin: 0 auto;
  padding: 30px clamp(20px, 3vw, 44px) 42px;
  color: #172033;
}
.artifact-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding: 0 0 24px 18px;
  border-left: 3px solid #4f6bed;
  border-bottom: 1px solid #e5eaf2;
}
.heading-kicker {
  margin-bottom: 8px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .12em;
}
.heading-copy h1 { margin: 0; color: #15213a; font-size: 27px; font-weight: 650; letter-spacing: -.035em; }
.heading-copy p { margin: 9px 0 0; color: #64748b; font-size: 13px; line-height: 1.6; }
.heading-index { display: flex; flex: 0 0 auto; align-items: baseline; gap: 8px; white-space: nowrap; color: #77839a; font-size: 11px; }
.heading-index strong { color: #384fbb; font: 600 30px/1 ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: -.06em; }
.heading-index small { font-size: 10px; }
.artifact-controls { display: flex; align-items: center; gap: 10px; padding: 20px 0 16px; }
.artifact-search { flex: 1; max-width: 560px; }
.search-glyph { color: #76839a; font-size: 20px; line-height: 1; }
.scope-select { width: 170px; }
.artifact-results { min-height: 340px; }
.results-label { display: flex; align-items: center; justify-content: space-between; padding: 10px 2px; color: #44516a; font-size: 12px; font-weight: 650; }
.result-count { color: #94a3b8; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }
.artifact-list { border-top: 1px solid #e8edf4; }
.artifact-row {
  display: flex;
  align-items: center;
  gap: 16px;
  min-height: 82px;
  padding: 12px 8px;
  border-bottom: 1px solid #e8edf4;
  transition: background-color .15s ease;
}
.artifact-row:hover { background: #f8faff; }
.file-type-mark {
  display: grid;
  flex: 0 0 42px;
  width: 42px;
  height: 48px;
  place-items: center;
  border: 1px solid #dce4f0;
  border-radius: 7px 7px 10px 7px;
  background: #f8faff;
  color: #5267c7;
  font-size: 20px;
}
.type-dashboard { color: #4362d5; background: #eef2ff; border-color: #dce4ff; }
.type-sheet { color: #25846c; background: #edf8f4; border-color: #d7eee6; }
.type-document { color: #bd6f42; background: #fff5ee; border-color: #f4e0d1; }
.type-text { color: #65758f; }
.artifact-details { min-width: 0; flex: 1; }
.artifact-title-line { display: flex; align-items: center; gap: 8px; min-width: 0; }
.artifact-title-line h2 { overflow: hidden; margin: 0; color: #1e293b; font-size: 14px; font-weight: 620; text-overflow: ellipsis; white-space: nowrap; }
.artifact-subline { display: flex; align-items: center; gap: 7px; min-width: 0; margin-top: 7px; color: #8a96a9; font-size: 11px; }
.conversation-title { overflow: hidden; max-width: 340px; text-overflow: ellipsis; white-space: nowrap; }
.subline-dot { color: #c2cad6; }
.artifact-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 2px; }
.artifact-empty { display: flex; min-height: 310px; flex-direction: column; align-items: center; justify-content: center; color: #718096; text-align: center; }
.empty-mark { display: grid; width: 50px; height: 56px; place-items: center; border: 1px solid #dce4f0; border-radius: 8px; color: #7185db; font-size: 26px; }
.artifact-empty h2 { margin: 16px 0 4px; color: #28344c; font-size: 15px; font-weight: 600; }
.artifact-empty p { margin: 0 0 14px; font-size: 12px; }
.artifact-preview-modal :deep(.n-card__content) { max-height: calc(88vh - 100px); overflow: auto; }
@media (max-width: 760px) {
  .artifact-page { padding: 20px 14px 30px; }
  .artifact-heading { align-items: flex-start; padding-left: 12px; }
  .heading-copy h1 { font-size: 23px; }
  .heading-copy p { max-width: 34ch; }
  .heading-index { display: none; }
  .artifact-controls { flex-wrap: wrap; }
  .artifact-search { flex-basis: 100%; max-width: none; }
  .scope-select { flex: 1; width: auto; }
  .artifact-row { align-items: flex-start; gap: 11px; padding: 13px 2px; }
  .file-type-mark { flex-basis: 36px; width: 36px; height: 42px; }
  .artifact-title-line { flex-wrap: wrap; }
  .artifact-title-line h2 { max-width: 100%; }
  .artifact-subline { flex-wrap: wrap; row-gap: 3px; }
  .artifact-actions { flex-direction: column; align-items: flex-end; gap: 3px; }
  .conversation-title { max-width: 22ch; }
}
@media (prefers-reduced-motion: reduce) {
  .artifact-row { transition: none; }
}
</style>
