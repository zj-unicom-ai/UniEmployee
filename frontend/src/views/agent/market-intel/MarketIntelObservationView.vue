<template>
  <main class="observation-page">
    <div class="page-wrap">
      <div class="page-toolbar">
        <button class="back-link" type="button" @click="goBack">
          <span aria-hidden="true">←</span> 返回{{ topicName || '研究主题' }}
        </button>
        <span class="breadcrumb">小察 <i>／</i> {{ topicName || '行业观察' }} <i>／</i> 研究详情</span>
      </div>

      <div v-if="loading" class="state-card" role="status">
        <span class="loader-ring"></span>
        正在读取研究观察…
      </div>

      <div v-else-if="error" class="state-card error-state" role="alert">
        <div>
          <h1>{{ errorTitle }}</h1>
          <p>{{ error }}</p>
        </div>
        <button class="primary-button" type="button" @click="loadObservation">重新加载</button>
      </div>

      <template v-else-if="observation">
        <header class="record-header">
          <div class="record-eyebrow"><span class="status-dot"></span> FIELD OBSERVATION <i>／</i> {{ topicName }}</div>
          <h1>{{ observation.title }}</h1>
          <p v-if="observation.summary" class="record-summary">{{ observation.summary }}</p>
          <div class="record-meta">
            <span class="topic-tag">{{ topicName }}</span>
            <label class="category-control">
              <span>所属领域</span>
              <select :value="observation.category_id || ''" :disabled="savingCategory" aria-label="调整文章所属细分领域" @change="saveCategory">
                <option value="">待分类</option>
                <option v-for="category in observation.category_options || []" :key="category.id" :value="category.id">{{ category.name }}</option>
              </select>
              <small v-if="savingCategory" role="status">保存中</small>
            </label>
            <span class="method-tag" :class="`method-${observation.ingest_method}`">{{ methodLabel(observation.ingest_method) }}</span>
            <span v-if="observation.published_at">信息发布于 {{ observation.published_at }}</span>
            <span>{{ observation.sources?.length || 0 }} 个来源</span>
          </div>
        </header>
        <p v-if="categoryError" class="category-error" role="alert">{{ categoryError }}</p>

        <section class="analysis-entry" aria-label="AI 研判">
          <div class="analysis-entry-mark" aria-hidden="true">∿</div>
          <div class="analysis-entry-copy"><h2>基于这条观察开展 AI 研判</h2><p>结合记录正文与引用来源，梳理影响、机会、风险和后续验证信号。</p></div>
          <button class="analysis-entry-button" type="button" @click="goAnalysis">进入 AI 研判 <span aria-hidden="true">↗</span></button>
        </section>

        <div class="detail-grid">
          <article class="content-card">
            <header class="card-heading">
              <div>
                <span class="section-kicker">RESEARCH NOTE</span>
                <h2>研究记录</h2>
              </div>
              <span class="captured-time">捕捉于 {{ formatDateTime(observation.captured_at) }}</span>
            </header>
            <div class="record-content" v-html="contentHtml"></div>
            <footer class="record-byline">
              <span class="byline-mark">察</span>
              <span>{{ observation.created_by_name || '小察研究工作台' }}</span>
              <i>·</i>
              <span>{{ methodLabel(observation.ingest_method) }}写入</span>
            </footer>
          </article>

          <aside class="source-card">
            <header class="source-heading">
              <div><span class="section-kicker">EVIDENCE</span><h2>证据来源</h2></div>
              <span class="source-count">{{ observation.sources?.length || 0 }}</span>
            </header>
            <a v-for="(source, index) in observation.sources || []" :key="`${source.url}-${index}`"
              class="source-item" :href="source.url || undefined" target="_blank" rel="noopener noreferrer"
              :class="{ disabled: !source.url }">
              <span class="source-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="source-copy">
                <strong>{{ source.title || source.organization || source.url || '未命名来源' }}</strong>
                <small>{{ source.organization }}<template v-if="source.organization && source.published_at"> · </template>{{ source.published_at }}</small>
              </span>
              <span v-if="source.url" class="external-arrow" aria-hidden="true">↗</span>
            </a>
            <div v-if="!observation.sources?.length" class="empty-sources">
              暂未登记引用链接。研究结论用于趋势判断前，请补充可追溯来源。
            </div>
            <div class="source-note">
              <span class="note-mark">i</span>
              <p>来源链接会在新窗口打开。请结合正文中的事实说明与验证边界阅读。</p>
            </div>
            <div v-if="observation.research_metadata?.source_provenance" class="quality-note">
              <strong>原文归属已校验</strong>
              <span>引述已与原文匹配；独立交叉验证尚未完成。</span>
              <small>文档版本 {{ observation.research_metadata.source_provenance.document_version_id }}</small>
            </div>
          </aside>
        </div>
      </template>
    </div>
  </main>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'
import { renderMd } from '../../../composables/useChatStream.js'

const route = useRoute()
const router = useRouter()
const observation = ref(null)
const loading = ref(true)
const error = ref('')
const errorTitle = ref('研究观察无法打开')
const savingCategory = ref(false)
const categoryError = ref('')
const contentHtml = computed(() => renderMd(
  observation.value?.content_markdown || '这条观察还没有补充研究正文。',
))

const topicName = computed(() => ({
  'embodied-intelligence': '具身智能',
  'ai-frontier': 'AI 前沿观察',
  'policy-analysis': '政策分析',
}[observation.value?.topic_id || route.query.topic] || '行业观察'))

function methodLabel(method) {
  return ({ agent: 'Agent 研究', manual: '手动录入', source_task: '来源任务', file_import: '文件导入' })[method] || '研究记录'
}

function formatDateTime(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

async function loadObservation() {
  loading.value = true
  error.value = ''
  errorTitle.value = '研究观察无法打开'
  try {
    const { data } = await api.get(`/market-research/observations/${encodeURIComponent(route.params.id)}`)
    observation.value = data
    categoryError.value = ''
  } catch (err) {
    observation.value = null
    if (err.response?.status === 404) {
      errorTitle.value = '没有找到这条研究观察'
      error.value = '记录可能已被移除，或当前账号没有访问权限。'
    } else {
      error.value = err.response?.data?.detail || '研究记录暂时无法加载，请检查连接后重试。'
    }
  } finally {
    loading.value = false
  }
}

async function saveCategory(event) {
  const categoryId = event.target.value
  if (!observation.value || categoryId === (observation.value.category_id || '') || savingCategory.value) return
  savingCategory.value = true
  categoryError.value = ''
  try {
    const { data } = await api.put(`/market-research/observations/${encodeURIComponent(route.params.id)}/category`, {
      category_id: categoryId,
    })
    observation.value = { ...observation.value, ...data }
    event.target.value = data.category_id || ''
    router.replace({ query: {
      ...route.query,
      category: data.category_id || '__unclassified__',
    } })
  } catch (err) {
    event.target.value = observation.value.category_id || ''
    categoryError.value = err.response?.data?.detail || '更新所属领域失败，请稍后重试。'
  } finally {
    savingCategory.value = false
  }
}

function goBack() {
  router.push({
    name: 'market-intel-topic',
    params: { topicId: observation.value?.topic_id || route.query.topic || 'embodied-intelligence' },
  })
}

function goAnalysis() {
  router.push({
    name: 'market-intel-observation-analysis',
    params: { id: route.params.id },
    query: {
      topic: observation.value?.topic_id || route.query.topic,
      category: route.query.category,
    },
  })
}

watch(() => route.params.id, loadObservation, { immediate: true })
</script>

<style scoped>
.observation-page {
  min-height: 100%;
  padding: 22px 34px 42px;
  color: #0f172a;
  background: #f1f5f9;
}

.page-wrap {
  width: min(100%, 1380px);
  margin: 0 auto;
}

.page-toolbar,
.record-meta,
.record-byline {
  display: flex;
  align-items: center;
}

.page-toolbar {
  justify-content: space-between;
  gap: 16px;
  min-height: 34px;
  margin-bottom: 22px;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid #e2e8f0;
  border-radius: 7px;
  color: #475569;
  background: #fff;
  cursor: pointer;
  font: 500 12px var(--font-sans, sans-serif);
  transition: .16s ease;
}

.back-link:hover {
  color: #2563eb;
  border-color: #bfdbfe;
  background: #eff6ff;
}

.back-link span {
  font-size: 16px;
  line-height: 1;
}

.breadcrumb {
  color: #94a3b8;
  font-size: 12px;
}

.breadcrumb i,
.record-eyebrow i {
  margin: 0 5px;
  color: #cbd5e1;
  font-style: normal;
}

.record-header {
  padding: 27px 30px 24px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 4px 18px rgba(15, 23, 42, .035);
}

.analysis-entry {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-top: 13px;
  padding: 17px 21px;
  border: 1px solid #bfdbfe;
  border-radius: 11px;
  background: linear-gradient(110deg, #eff6ff 0%, #ffffff 78%);
}

.analysis-entry-mark {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid #bfdbfe;
  border-radius: 10px;
  color: #2563eb;
  background: #ffffff;
  font-size: 27px;
  line-height: 1;
}

.analysis-entry-copy {
  min-width: 0;
  flex: 1;
}

.analysis-entry-copy h2 {
  margin: 0;
  color: #1e3a8a;
  font-size: 16px;
  font-weight: 650;
}

.analysis-entry-copy p {
  margin: 3px 0 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.65;
}

.analysis-entry-button {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-height: 40px;
  flex: 0 0 auto;
  padding: 8px 13px;
  border: 1px solid #2563eb;
  border-radius: 7px;
  color: #ffffff;
  background: #3b82f6;
  cursor: pointer;
  font: 600 14px var(--font-sans, sans-serif);
  transition: .16s ease;
}

.analysis-entry-button:hover {
  background: #2563eb;
}

.analysis-entry-button:focus-visible {
  outline: 3px solid #93c5fd;
  outline-offset: 2px;
}

.record-eyebrow,
.section-kicker {
  color: #64748b;
  font: 600 11px var(--font-mono, ui-monospace, monospace);
  letter-spacing: .12em;
}

.record-eyebrow {
  display: flex;
  align-items: center;
}

.status-dot {
  width: 7px;
  height: 7px;
  margin-right: 8px;
  border-radius: 50%;
  background: #3b82f6;
  box-shadow: 0 0 0 3px #eff6ff;
}

.record-header h1 {
  max-width: 1050px;
  margin: 14px 0 10px;
  color: #0f172a;
  font: 650 clamp(23px, 2.7vw, 34px)/1.4 var(--font-sans, sans-serif);
  letter-spacing: -.025em;
}

.record-summary {
  max-width: 1060px;
  margin: 0;
  color: #475569;
  font-size: 16px;
  line-height: 1.85;
}

.record-meta {
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 19px;
  color: #64748b;
  font-size: 12px;
}

.topic-tag,
.method-tag,
.category-tag {
  padding: 5px 9px;
  border-radius: 999px;
  color: #1d4ed8;
  background: #eff6ff;
  font-weight: 600;
}

.method-tag {
  color: #475569;
  background: #f1f5f9;
}

.category-control {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 3px 7px 3px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 999px;
  color: #1e40af;
  background: #eff6ff;
  font-size: 12px;
  font-weight: 600;
}

.category-control select {
  max-width: min(280px, 52vw);
  padding: 3px 20px 3px 7px;
  border: 0;
  border-radius: 999px;
  outline: none;
  color: #1e3a8a;
  background: rgba(255, 255, 255, .8);
  font: 600 13px var(--font-sans, sans-serif);
}

.category-control select:focus-visible {
  outline: 2px solid #60a5fa;
}

.category-control select:disabled {
  opacity: .65;
}

.category-control small {
  color: #2563eb;
  font-size: 12px;
  white-space: nowrap;
}

.category-error {
  margin: 10px 0 0;
  padding: 9px 12px;
  border: 1px solid #fecaca;
  border-radius: 7px;
  color: #b91c1c;
  background: #fff7f7;
  font-size: 14px;
}

.category-tag {
  color: #1e40af;
  background: #dbeafe;
}

.category-tag.unclassified {
  color: #92400e;
  background: #fef3c7;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(280px, .75fr);
  align-items: start;
  gap: 16px;
  margin-top: 16px;
}

.content-card,
.source-card,
.state-card {
  border: 1px solid #e2e8f0;
  border-radius: 11px;
  background: #fff;
  box-shadow: 0 4px 18px rgba(15, 23, 42, .035);
}

.content-card {
  padding: 24px 28px 20px;
}

.card-heading,
.source-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.card-heading h2,
.source-heading h2 {
  margin: 5px 0 0;
  color: #0f172a;
  font-size: 18px;
  font-weight: 650;
}

.captured-time {
  color: #94a3b8;
  font-size: 12px;
}

.record-content {
  margin-top: 22px;
  padding-top: 19px;
  border-top: 1px solid #e2e8f0;
  color: #334155;
  font-size: 16px;
  line-height: 1.9;
  overflow-wrap: anywhere;
}

.record-content :deep(h2) {
  margin: 26px 0 11px;
  padding-left: 12px;
  border-left: 3px solid #3b82f6;
  color: #0f172a;
  font-size: 19px;
  font-weight: 650;
  line-height: 1.5;
}

.record-content :deep(h2:first-child) {
  margin-top: 0;
}

.record-content :deep(h3) {
  margin: 22px 0 9px;
  color: #1e293b;
  font-size: 17px;
  font-weight: 650;
  line-height: 1.55;
}

.record-content :deep(p) {
  margin: 0 0 16px;
}

.record-content :deep(img) {
  display: block;
  max-width: 100%;
  max-height: 560px;
  width: auto;
  height: auto;
  margin: 20px auto 24px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  box-shadow: 0 8px 24px rgba(15, 23, 42, .08);
  object-fit: contain;
}

.record-content :deep(p:has(> img)) {
  margin-bottom: 20px;
}

.record-content :deep(ul),
.record-content :deep(ol) {
  margin: 0 0 17px;
  padding-left: 25px;
}

.record-content :deep(li) {
  margin: 6px 0;
  padding-left: 3px;
}

.record-content :deep(strong) {
  color: #1e293b;
  font-weight: 650;
}

.record-content :deep(a) {
  color: #2563eb;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.record-byline {
  gap: 8px;
  margin-top: 24px;
  padding-top: 15px;
  border-top: 1px solid #f1f5f9;
  color: #64748b;
  font-size: 12px;
}

.record-byline i {
  color: #cbd5e1;
  font-style: normal;
}

.byline-mark {
  display: grid;
  width: 23px;
  height: 23px;
  place-items: center;
  border-radius: 50%;
  color: #2563eb;
  background: #eff6ff;
  font-family: 'Noto Serif SC', serif;
}

.source-card {
  position: sticky;
  top: 18px;
  padding: 21px;
}

.source-count {
  display: grid;
  min-width: 28px;
  height: 28px;
  place-items: center;
  padding: 0 7px;
  border-radius: 8px;
  color: #2563eb;
  background: #eff6ff;
  font: 600 11px var(--font-mono, ui-monospace, monospace);
}

.source-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
  padding: 13px 11px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  color: inherit;
  text-decoration: none;
  transition: .16s ease;
}

.source-item:hover {
  border-color: #bfdbfe;
  background: #f8fbff;
}

.source-item.disabled {
  cursor: default;
}

.source-index {
  padding-top: 1px;
  color: #94a3b8;
  font: 10px var(--font-mono, ui-monospace, monospace);
}

.source-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
}

.source-copy strong {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.source-item:hover .source-copy strong {
  color: #2563eb;
}

.source-copy small {
  color: #94a3b8;
  font-size: 11px;
  line-height: 1.5;
}

.external-arrow {
  margin-left: auto;
  color: #3b82f6;
  font-size: 14px;
}

.empty-sources {
  margin-top: 14px;
  padding: 13px;
  border-radius: 8px;
  color: #92400e;
  background: #fffbeb;
  font-size: 13px;
  line-height: 1.7;
}

.source-note {
  display: flex;
  gap: 9px;
  margin-top: 17px;
  padding: 12px 10px 0;
  border-top: 1px solid #f1f5f9;
  color: #64748b;
}
.quality-note { display:flex; flex-direction:column; gap:5px; margin-top:12px; padding:11px 12px; border:1px solid #dce9df; border-radius:6px; color:#64806b; background:#f3f8f4; font-size:11px; line-height:1.5; }
.quality-note strong { color:#4f765b; font-size:12px; }
.quality-note small { overflow-wrap:anywhere; color:#8a9d8e; font:10px 'DM Mono',monospace; }

.note-mark {
  display: grid;
  flex: 0 0 17px;
  width: 17px;
  height: 17px;
  place-items: center;
  border-radius: 50%;
  color: #2563eb;
  background: #eff6ff;
  font: 600 10px Georgia, serif;
}

.source-note p {
  margin: 0;
  font-size: 12px;
  line-height: 1.65;
}

.state-card {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 15px;
  min-height: 170px;
  padding: 26px;
  color: #64748b;
  font-size: 12px;
}

.error-state {
  justify-content: space-between;
}

.error-state h1 {
  margin: 0;
  color: #0f172a;
  font-size: 17px;
}

.error-state p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
}

.primary-button {
  padding: 9px 13px;
  border: 1px solid #2563eb;
  border-radius: 7px;
  color: #fff;
  background: #3b82f6;
  cursor: pointer;
  font-size: 11px;
}

.primary-button:hover {
  background: #2563eb;
}

.loader-ring {
  width: 21px;
  height: 21px;
  border: 2px solid #dbeafe;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin .8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }
  .source-card {
    position: static;
  }
}

@media (max-width: 620px) {
  .analysis-entry {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .analysis-entry-button {
    margin-left: 55px;
  }

  .observation-page {
    padding: 14px 12px 26px;
  }
  .page-toolbar {
    align-items: flex-start;
    flex-direction: column;
    margin-bottom: 13px;
  }
  .record-header {
    padding: 19px 17px;
  }
  .record-header h1 {
    font-size: 22px;
  }
  .record-summary {
    font-size: 15px;
  }
  .content-card {
    padding: 18px 16px;
  }
  .card-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .record-content {
    font-size: 15px;
  }
  .source-card {
    padding: 17px 14px;
  }
  .error-state {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
