<!--
数据分析 · 对话问数主页面
布局：左历史 / 中对话 / 右本体面板（折叠）
顶栏：数据源选择器 + 配置入口（库表/术语/SQL 示例）
复用 useChatStream SSE 流
-->
<template>
  <div class="analyst-layout">
    <!-- 左：历史会话 -->
    <div class="left-panel">
      <div class="panel-header">
        <span>会话历史</span>
        <n-button size="tiny" type="primary" @click="newConv">+ 新会话</n-button>
      </div>
      <div class="conv-list">
        <div
          v-for="c in convList" :key="c.conv_id"
          class="conv-item"
          :class="{ active: convId === c.conv_id }"
          @click="openConversation(c.conv_id)"
        >
          <div class="conv-title">{{ c.title || '未命名会话' }}</div>
          <div class="conv-meta">{{ formatTime(c.updated_at || c.created_at) }}</div>
        </div>
        <n-empty v-if="!convList.length" description="暂无历史" size="small" />
      </div>
    </div>

    <!-- 中：对话区 -->
    <div class="center-panel">
      <!-- 顶栏 -->
      <div class="chat-header">
        <div class="header-left">
          <n-select
            v-model:value="datasourceId"
            :options="dsOptions"
            size="small"
            placeholder="选择数据源"
            style="width: 220px"
          />
          <n-tag v-if="datasourceName" size="tiny" type="info">{{ datasourceName }}</n-tag>
        </div>
        <div class="header-right">
          <n-button size="tiny" text @click="$router.push({ name: 'analyst-datasources' })">库表</n-button>
          <n-button size="tiny" text @click="$router.push({ name: 'analyst-terminologies' })">术语</n-button>
          <n-button size="tiny" text @click="$router.push({ name: 'analyst-sql-examples' })">SQL 示例</n-button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div class="msgs" ref="msgsRef">
        <!-- 空态：未提问时展示当前数据源的前 3 个 SQL 示例作为快捷话术 -->
        <div v-if="!messages.length" class="welcome-box">
          <div class="welcome-hero">
            <div class="hero-avatar">小数</div>
            <div class="hero-text">
              <div class="hero-title">数据分析专家 · 小数</div>
              <div class="hero-sub">
                <template v-if="datasourceName">
                  当前数据源「<span class="ds-name">{{ datasourceName }}</span>」，试试这些问法
                </template>
                <template v-else>试试这些问法</template>
              </div>
            </div>
          </div>

          <div v-if="quickPrompts.length" class="prompt-grid">
            <div
              v-for="(ex, i) in quickPrompts"
              :key="ex.id || i"
              class="prompt-card"
              @click="usePrompt(ex)"
            >
              <div class="prompt-index">{{ String(i + 1).padStart(2, '0') }}</div>
              <div class="prompt-body">
                <div class="prompt-q">{{ ex.question }}</div>
                <div v-if="ex.description" class="prompt-desc">{{ ex.description }}</div>
              </div>
              <div class="prompt-cta">
                <span>点击提问</span>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 7h8m0 0L7.5 3.5M11 7l-3.5 3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </div>
            </div>
          </div>

          <div v-else class="welcome-empty">
            <div class="empty-icon">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none"><path d="M9 19V6m6 13V8M4 2v20h16M4 2h16M4 22h16" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <div class="empty-title">当前数据源暂无快捷话术</div>
            <div class="empty-desc">
              可前往
              <n-button size="tiny" text type="primary" @click="$router.push({ name: 'analyst-sql-examples' })">SQL 示例</n-button>
              为该数据源配置常见问法
            </div>
          </div>
        </div>
        <template v-for="(msg, idx) in messages" :key="idx">
          <ChatMessage
            :msg="msg"
            :idx="idx"
          />
          <!-- SQL 语句展示：msg.sql 由 SSE sql 事件或工具 trace 填充 -->
          <SqlViewer v-if="msg.sql" :sql="msg.sql" style="margin: 4px 0 12px" />
        </template>
      </div>

      <!-- 输入栏 -->
      <div class="input-bar">
        <div v-if="pendingFiles.length" class="att-chips">
          <n-tag
            v-for="(f, i) in pendingFiles" :key="i"
            size="small" closable type="info"
            @close="pendingFiles.splice(i, 1)"
          >{{ f.name }}</n-tag>
        </div>
        <div class="input-row">
          <n-button size="small" quaternary :loading="uploading"
                    title="上传 Excel/CSV 表格（自动注册为可查询数据表）"
                    @click="fileInputRef?.click()">
            📎
          </n-button>
          <input
            ref="fileInputRef" type="file" hidden multiple
            accept=".csv,.xlsx,.xls"
            @change="onFilePick"
          />
          <n-input
            v-model:value="inputText"
            type="textarea"
            :rows="2"
            size="small"
            placeholder="向小数提问，如：本月销售额 TOP10 客户；也可粘贴后上传表格直接问"
            :disabled="stream.sending.value"
            @keydown.enter.exact.prevent="onSend"
          />
          <n-button
            type="primary"
            size="small"
            :loading="stream.sending.value || uploading"
            :disabled="(!inputText.trim() && !pendingFiles.length) || (!datasourceId && !pendingFiles.length)"
            @click="onSend"
          >发送</n-button>
        </div>
      </div>
    </div>

    <!-- 右：本体面板（默认折叠） -->
    <div class="right-panel" :class="{ collapsed: !showOntology }">
      <div class="panel-header">
        <span v-if="!showOntology" @click="showOntology = true" class="toggle-btn">
          ◀ 展开本体
        </span>
        <template v-else>
          <span>本体关联</span>
          <n-button size="tiny" text @click="showOntology = false">▶</n-button>
        </template>
      </div>
      <div v-if="showOntology" class="ontology-content">
        <n-empty description="SQL 结果涉及实体时展示" size="small" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import api from '../../../api.js'
import * as analystApi from '../../../api/analyst.js'
import { useChatStream, renderMd } from '../../../composables/useChatStream.js'
import ChatMessage from '../../../components/chat/ChatMessage.vue'
import SqlViewer from '../../../components/agent/analyst/SqlViewer.vue'

defineOptions({ name: 'AnalystView' })
const message = useMessage()
const route = useRoute()

const datasourceId = ref(null)
const datasources = ref([])
const dsOptions = computed(() =>
  datasources.value.map(d => ({ label: d.name, value: d.id }))
)
const datasourceName = computed(() =>
  datasources.value.find(d => d.id === datasourceId.value)?.name || ''
)

// 当前数据源的前 3 个启用 SQL 示例（作为空态快捷话术）
const quickPrompts = ref([])

async function loadQuickPrompts() {
  if (!datasourceId.value) { quickPrompts.value = []; return }
  try {
    const all = await analystApi.listSqlExamples({ datasource_id: datasourceId.value })
    quickPrompts.value = (all || []).filter(x => x.enabled).slice(0, 3)
  } catch {
    quickPrompts.value = []
  }
}

// 切换数据源时重新加载示例
watch(datasourceId, () => loadQuickPrompts())

// 点击快捷话术：填入输入框并聚焦（不自动发送，让用户可再编辑）
function usePrompt(ex) {
  inputText.value = ex.question
  // 自动发送：直接调用 onSend
  onSend()
}

const convId = ref(null)
const convList = ref([])
const messages = ref([])
const inputText = ref('')
const msgsRef = ref(null)
const stageStates = reactive({})
const stageDetail = reactive({})
const showOntology = ref(false)

// 表格问答附件：选中的待上传文件（发送时先上传再随消息发出）
const pendingFiles = ref([])
const uploading = ref(false)
const fileInputRef = ref(null)

function onFilePick(e) {
  const files = Array.from(e.target.files || [])
  for (const f of files) {
    if (!/\.(csv|xlsx|xls)$/i.test(f.name)) {
      message.warning('仅支持 csv/xlsx/xls 表格文件：' + f.name)
      continue
    }
    if (pendingFiles.value.length >= 5) {
      message.warning('单条消息最多 5 个附件')
      break
    }
    pendingFiles.value.push(f)
  }
  e.target.value = ''
}

const stream = useChatStream({ stageStates, stageDetail, messages, scrollToBottom })

function scrollToBottom() {
  nextTick(() => {
    if (msgsRef.value) msgsRef.value.scrollTop = msgsRef.value.scrollHeight
  })
}

function formatTime(t) {
  if (!t) return ''
  return t.replace('T', ' ').slice(0, 16)
}

async function loadDatasources() {
  try {
    datasources.value = await analystApi.listDatasources()
    const enabled = datasources.value.filter(d => d.enabled)
    if (enabled.length && !datasourceId.value) {
      datasourceId.value = enabled[0].id
    }
  } catch (e) {
    message.error('加载数据源失败：' + (e.response?.data?.detail || e.message))
  }
}

async function loadConversations() {
  try {
    convList.value = await analystApi.listAnalystConversations(20)
  } catch {}
}

async function newConv() {
  try {
    const data = await analystApi.createAnalystConversation()
    convId.value = data.conversation_id
    messages.value = []
    stream.resetPipeline()
    await loadConversations()
  } catch (e) {
    message.error('创建会话失败：' + (e.response?.data?.detail || e.message))
  }
}

async function openConversation(cid) {
  try {
    const data = await analystApi.getAnalystConversation(cid)
    if (data.error) return
    convId.value = cid
    messages.value = []
    stream.resetPipeline()
    for (const t of (data.turns || [])) {
      if (t.role === 'user') {
        messages.value.push({ role: 'user', content: t.content, time: formatTime(t.created_at) })
      } else {
        const msg = {
          role: 'bot', content: '', html: renderMd(t.content || ''),
          _md: t.content || '', trace: [], time: formatTime(t.created_at),
        }
        if (t.tool_calls && t.tool_calls.length) {
          msg.trace = t.tool_calls.map(tc => ({
            type: 'tool', name: tc.name || '',
            args: tc.args && Object.keys(tc.args).length ? JSON.stringify(tc.args) : '',
            status: 'done', preview: tc.result || '',
          }))
        }
        messages.value.push(msg)
      }
    }
    scrollToBottom()
  } catch {}
}

async function onSend() {
  const text = inputText.value.trim()
  if (!text && !pendingFiles.value.length) return
  // 纯表格问答（只带附件）不强制选数据源；数据库问数仍需数据源
  if (!datasourceId.value && !pendingFiles.value.length) {
    message.warning('请先选择数据源')
    return
  }
  if (!convId.value) {
    await newConv()
    if (!convId.value) return
  }
  // 先上传表格附件（.csv/.xlsx/.xls），后端发送消息时自动注册为 DuckDB 表
  let attachments = []
  if (pendingFiles.value.length) {
    uploading.value = true
    try {
      for (const f of pendingFiles.value) {
        const form = new FormData()
        form.append('file', f)
        const { data } = await api.post(`/conversations/${convId.value}/attachments`, form)
        if (data.error) {
          message.error('附件「' + f.name + '」上传失败：' + data.error)
        } else {
          attachments.push(data)
        }
      }
    } catch (e) {
      message.error('附件上传失败：' + (e.response?.data?.detail || e.message))
    }
    uploading.value = false
    pendingFiles.value = []
    if (!attachments.length) return
  }
  // 把 datasource_id 作为结构化参数传到后端（query param），由 streaming.py
  // 注入到 sql_db_* 工具的 contextvar，工具内部 datasource_id 参数为空时兜底。
  // 不再用文本前缀 [数据源: xxx]，避免 LLM 把名字当 ID 瞎猜。
  await stream.sendTo(
    `/api/conversations/${convId.value}/messages`,
    text,
    attachments,
    datasourceId.value,
  )
  inputText.value = ''
  await loadConversations()
}

onMounted(async () => {
  await loadDatasources()
  await loadConversations()
  // 优先从 URL ?conv=xxx 恢复指定会话（从会话历史页跳转过来时）
  const qconv = route.query.conv
  if (qconv) {
    await openConversation(qconv)
  } else if (!convId.value && convList.value.length) {
    await openConversation(convList.value[0].conv_id)
  } else if (!convId.value) {
    await newConv()
  }
  // 进入页面或打开历史会话后，加载当前数据源的话术示例
  await loadQuickPrompts()
})
</script>

<style scoped>
.analyst-layout {
  display: flex;
  height: 100%;
  background: #f8fafc;
}

/* 左侧历史 */
.left-panel {
  width: 240px;
  border-right: 1px solid #e5e7eb;
  background: #fff;
  display: flex;
  flex-direction: column;
}
.panel-header {
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  border-bottom: 1px solid #f3f4f6;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}
.conv-item {
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 4px;
}
.conv-item:hover { background: #f9fafb; }
.conv-item.active { background: #eff6ff; }
.conv-title {
  font-size: 13px;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.conv-meta { font-size: 11px; color: #9ca3af; margin-top: 2px; }

/* 中间对话 */
.center-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  min-width: 0;
}
.chat-header {
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
}
.header-left, .header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.msgs {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}

/* 空态：欢迎话术区 */
.welcome-box {
  max-width: 820px;
  margin: 32px auto 0;
  padding: 0 12px;
}

.welcome-hero {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 22px;
  border-radius: 14px;
  background: linear-gradient(135deg, #f5f3ff 0%, #eff6ff 100%);
  border: 1px solid #ede9fe;
  margin-bottom: 18px;
}
.hero-avatar {
  width: 44px; height: 44px;
  border-radius: 12px;
  background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px; font-weight: 600;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);
}
.hero-text { min-width: 0; }
.hero-title {
  font-size: 15px; font-weight: 600; color: #0f172a;
}
.hero-sub {
  font-size: 12.5px; color: #64748b; margin-top: 4px;
  line-height: 1.5;
}
.ds-name { color: #4f46e5; font-weight: 500; }

.prompt-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
}
.prompt-card {
  position: relative;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px 16px 12px 44px;
  cursor: pointer;
  transition: all 0.18s ease;
  min-height: 96px;
}
.prompt-card:hover {
  border-color: #7c3aed;
  box-shadow: 0 6px 16px rgba(124, 58, 237, 0.12);
  transform: translateY(-1px);
}
.prompt-index {
  position: absolute;
  left: 14px; top: 14px;
  width: 22px; height: 22px;
  border-radius: 6px;
  background: #f5f3ff;
  color: #7c3aed;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 600;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: -0.5px;
}
.prompt-body { flex: 1; min-width: 0; }
.prompt-q {
  font-size: 13.5px; font-weight: 500;
  color: #1f2937; line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.prompt-desc {
  font-size: 12px; color: #94a3b8;
  margin-top: 6px; line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.prompt-cta {
  display: flex; align-items: center; gap: 4px;
  margin-top: 10px;
  font-size: 12px; color: #7c3aed;
  opacity: 0;
  transition: opacity 0.18s ease;
}
.prompt-card:hover .prompt-cta { opacity: 1; }

.welcome-empty {
  text-align: center;
  padding: 48px 24px;
  background: #fff;
  border: 1px dashed #e5e7eb;
  border-radius: 12px;
}
.empty-icon {
  display: inline-flex;
  width: 56px; height: 56px;
  border-radius: 14px;
  background: #f8fafc;
  color: #94a3b8;
  align-items: center; justify-content: center;
  margin-bottom: 12px;
}
.empty-title {
  font-size: 14px; font-weight: 500; color: #475569;
}
.empty-desc {
  font-size: 12.5px; color: #94a3b8;
  margin-top: 6px;
}
.input-bar {
  padding: 8px 12px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.input-row {
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.input-row .n-input { flex: 1; }
.att-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

/* 右侧本体 */
.right-panel {
  width: 280px;
  border-left: 1px solid #e5e7eb;
  background: #fff;
  display: flex;
  flex-direction: column;
  transition: width 0.2s;
}
.right-panel.collapsed { width: 40px; }
.toggle-btn {
  cursor: pointer;
  font-size: 12px;
  color: #6b7280;
}
.ontology-content {
  flex: 1;
  padding: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
