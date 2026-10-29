<template>
  <main class="research-desk" :class="{ 'modal-open': createOpen }">
    <div class="desk-wrap">
      <header class="desk-masthead">
        <div class="identity-lockup">
          <div class="seal" aria-hidden="true"><span>察</span><i></i></div>
          <div>
            <div class="wordmark">小察 <span>INDUSTRY INTELLIGENCE</span></div>
            <div class="desk-label">研究工作台 <span class="label-dot"></span> 分类研判 · 证据观察</div>
          </div>
        </div>
        <div class="mast-actions">
          <div class="updated-stamp"><span class="pulse-dot"></span> 数据持续沉淀中</div>
          <select v-if="auth.isAdmin && !isTopicDashboard" v-model="collectionTopicId" aria-label="采集主题">
            <option value="">选择采集主题</option>
            <option v-for="topic in topics" :key="topic.id" :value="topic.id">{{ topic.name }}</option>
          </select>
          <button v-if="auth.isAdmin" class="collection-start-button" type="button" :disabled="collectionBusy || (!isTopicDashboard && !collectionTopicId)" @click="startCollection">{{ collectionBusy ? '正在启动…' : '只抓取原文' }}</button>
          <button v-if="auth.isAdmin" class="collection-progress-button" type="button" @click="router.push({ name: 'market-intel-collection' })">采集进度</button>
          <button v-if="auth.isAdmin" class="collection-progress-button source-documents-button" type="button" @click="router.push({ name: 'market-intel-unverified', query: isTopicDashboard ? { topic: selectedTopic } : {} })">
            资料核验
            <span v-if="activeSourceDocCount" class="source-documents-count">{{ formatCount(activeSourceDocCount) }} 篇待补核验</span>
          </button>
          <button class="icon-button" type="button" aria-label="工作台配置与回收站" title="配置与回收站" :aria-expanded="openConfigMenu" @click="openConfigMenu = !openConfigMenu">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z"/><path d="m19.4 15 .1.1a1.7 1.7 0 1 1-2.4 2.4l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a1.7 1.7 0 1 1-3.4 0v-.2a1.7 1.7 0 0 0-2.9-1.2l-.1.1a1.7 1.7 0 1 1-2.4-2.4l.1-.1a1.7 1.7 0 0 0-1.2-2.9H4a1.7 1.7 0 1 1 0-3.4h.2a1.7 1.7 0 0 0 1.2-2.9l-.1-.1a1.7 1.7 0 1 1 2.4-2.4l.1.1a1.7 1.7 0 0 0 2.9-1.2V2a1.7 1.7 0 1 1 3.4 0v.2a1.7 1.7 0 0 0 2.9 1.2l.1-.1a1.7 1.7 0 1 1 2.4 2.4l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.2a1.7 1.7 0 1 1 0 3.4h-.2a1.7 1.7 0 0 0-1.2 2.9Z"/></svg>
            <span>配置</span>
          </button>
          <div v-if="openConfigMenu" class="config-menu">
            <template v-if="auth.isAdmin">
              <button type="button" @click="router.push({ name: 'market-intel-sources', query: isTopicDashboard ? { topic: selectedTopic } : {} }); openConfigMenu = false">数据源配置 <span>RSS、网页与接口来源，采集频率及运行状态</span></button>
              <button type="button" @click="goConfig('employee-skills')">技能配置 <span>研究流程与主题规程</span></button>
              <button type="button" @click="goConfig('employee-connectors')">连接器配置 <span>信息来源与采集工具</span></button>
              <button type="button" @click="router.push({ name: 'automation' }); openConfigMenu = false">采集任务 <span>定时与事件触发</span></button>
              <div class="config-menu-divider" aria-hidden="true"></div>
            </template>
            <button type="button" @click="toggleTrash(); openConfigMenu = false">{{ trashMode ? '返回研究列表' : `回收站（${deletedCount}）` }} <span>{{ trashMode ? '回到当前主题观察' : '已移入的记录，可查看并恢复' }}</span></button>
          </div>
        </div>
      </header>

      <div v-if="collectionError" class="notice error-notice" role="alert">{{ collectionError }} <button type="button" @click="collectionError = ''">关闭</button></div>

      <MarketIntelLinkIntake :topic-id="selectedTopic" :categories="currentTopic?.categories || []" @changed="loadWorkbench" />

      <section v-if="!isTopicDashboard" class="hero-grid" aria-labelledby="workbench-title">
        <div class="hero-copy">
          <p class="eyebrow">INDUSTRY JUDGEMENT <span>／</span> EVIDENCE TRACKING</p>
          <h1 id="workbench-title">从细分领域，<em>形成行业判断。</em></h1>
          <p class="hero-intro">按细分领域持续积累证据，再综合观察变化、机会与风险。每条资讯只归属一个领域，内容记录为研判提供依据。</p>
          <div class="hero-meta">
            <span><b>{{ totalObservations }}</b> 条研究依据</span>
            <span class="meta-divider"></span>
            <span><b>{{ coveredTopics }}</b> 个主题持续跟踪</span>
            <span class="meta-divider"></span>
            <span><b>{{ unclassifiedTotal }}</b> 条待分类</span>
          </div>
        </div>
        <div class="hero-graphic" aria-hidden="true">
          <div class="orbit orbit-one"></div><div class="orbit orbit-two"></div>
          <div class="orbit-core"><span>MARKET</span><b>观察</b><small>INTELLIGENCE</small></div>
          <span class="orbit-label label-a">技术演进</span><span class="orbit-label label-b">政策信号</span><span class="orbit-label label-c">产业链</span>
          <span class="orbit-node node-a"></span><span class="orbit-node node-b"></span><span class="orbit-node node-c"></span>
        </div>
      </section>

      <div v-if="error && !trashMode && !reviewMode" class="notice error-notice workbench-error" role="alert">{{ error }} <button type="button" @click="loadWorkbench">重试</button></div>

      <section v-if="!isTopicDashboard && !trashMode && !reviewMode" class="topic-section" aria-labelledby="topic-heading">
        <div class="section-heading">
          <div><span class="section-kicker">FOCUS AREAS</span><h2 id="topic-heading">研究主题</h2></div>
          <span class="section-note">从主题进入连续观察</span>
        </div>
        <div class="topic-grid">
          <button v-for="(topic, index) in topics" :key="topic.id" type="button"
            class="topic-card" :class="`topic-${topic.accent}`"
            :aria-label="`进入${topic.name}主题看板`" @click="selectTopic(topic.id)">
            <span class="topic-number">0{{ index + 1 }}</span>
            <span class="topic-symbol" aria-hidden="true">{{ topicSymbol(topic.id) }}</span>
            <span class="topic-copy"><span class="topic-eyebrow">{{ topic.eyebrow }}</span><strong>{{ topic.name }}</strong><small>{{ topic.description }}</small></span>
            <span class="topic-count">
              <b>{{ topic.observation_count || 0 }}</b><small>条依据</small>
              <small v-if="sourceDocTopicCounts[topic.id]?.raw_documents" class="topic-source-count">{{ formatCount(sourceDocTopicCounts[topic.id].raw_documents) }} 篇来源资料</small>
            </span>
            <span class="topic-arrow" aria-hidden="true">↗</span>
          </button>
        </div>
      </section>

      <section v-if="isTopicDashboard && loading" class="theme-page-state" role="status"><span class="loader-ring"></span><strong>正在打开主题看板…</strong><span>整理研判状态与近期研究依据</span></section>
      <section v-else-if="isTopicDashboard && !currentTopic && !error" class="theme-page-state theme-page-not-found" role="alert"><strong>没有找到这个研究主题</strong><button type="button" @click="backToThemes">返回研究主题</button></section>

      <section v-if="isTopicDashboard && currentTopic && !loading && !error && !trashMode && !reviewMode" class="theme-dashboard" :class="`theme-dashboard-${currentTopic.accent}`" aria-labelledby="theme-dashboard-title">
        <header class="theme-dashboard-head">
          <div>
            <div class="theme-breadcrumb"><button type="button" @click="backToThemes"><span aria-hidden="true">←</span> 研究主题</button><i>/</i><b>{{ currentTopic.name }}</b></div>
            <div v-if="!isEmbodiedTopic" class="theme-title-line"><span class="theme-title-mark" aria-hidden="true">{{ topicSymbol(currentTopic.id) }}</span><div><h2 id="theme-dashboard-title">{{ currentTopic.name }}</h2><p>{{ currentTopic.description }}</p></div></div>
          </div>
          <div class="theme-head-actions">
            <span class="theme-updated"><i></i>{{ currentTopic.latest_at ? `最近观察 ${formatDate(currentTopic.latest_at)}` : '等待第一条研究观察' }}</span>
            <button class="theme-research-button" type="button" @click="openCreate"><span aria-hidden="true">＋</span> 让小察研究</button>
          </div>
        </header>

        <EmbodiedTechnologyRadar v-if="isEmbodiedTopic" @synced="topics = $event" />

        <template v-else>
        <div class="theme-overview-grid">
          <article class="theme-verdict-panel">
            <div class="theme-panel-heading"><span class="theme-panel-icon" aria-hidden="true">⌁</span><span>主题综合判断</span><span class="theme-report-version">{{ topicJudgement?.report ? `第 ${topicJudgement.report.version} 版` : '尚未形成' }}</span></div>
            <template v-if="topicJudgement?.report">
              <h3>{{ topicJudgement.report.title || `${currentTopic.name} · 综合研判` }}</h3>
              <p>{{ topicJudgement.report.conclusion }}</p>
              <div class="theme-verdict-meta"><span>资料截止 {{ formatDate(topicJudgement.report.data_cutoff) }}</span><span>{{ topicJudgement.report.evidence_ids?.length || 0 }} 条观察被引用</span><span>可信度 {{ confidenceLabel(topicJudgement.report.confidence) }}</span></div>
            </template>
            <template v-else>
              <h3>主题判断正在建立，先从已积累的领域看起</h3>
              <p>当前已有 {{ reportedCategoryCount }} / {{ judgementOverview?.category_count || currentTopic.categories?.length || 0 }} 个细分领域形成研判。综合判断会在各领域积累证据后，归纳共同趋势、分化信号与相互影响。</p>
              <div class="theme-verdict-meta"><span>现阶段先看细分领域判断</span><span v-if="strongestCategory">依据较多：{{ strongestCategory.name }}</span><span>不以资讯数量代替趋势</span></div>
            </template>
            <button class="theme-verdict-link" type="button" :disabled="loading || !reportedCategoryCount" @click="openJudgement()">{{ topicJudgement?.report ? '查看完整主题研判' : '基于细分研判形成主题判断' }}<b aria-hidden="true">↗</b></button>
          </article>

          <aside class="theme-coverage-panel" aria-label="研究覆盖情况">
            <div class="theme-panel-heading"><span class="theme-panel-icon coverage-icon" aria-hidden="true">◌</span><span>研究覆盖</span></div>
            <div class="coverage-metric"><strong>{{ currentTopic.observation_count || 0 }}</strong><span>条有效研究依据</span></div>
            <div class="coverage-row"><span>已形成细分研判</span><b>{{ reportedCategoryCount }} / {{ judgementOverview?.category_count || currentTopic.categories?.length || 0 }}</b></div>
            <div class="coverage-row"><span>待吸收新依据</span><b :class="{ 'coverage-warning': pendingEvidenceCount }">{{ pendingEvidenceCount }} 条</b></div>
            <div class="coverage-meter" role="img" :aria-label="`已形成 ${reportedCategoryCount} 个细分研判`"><i :style="{ width: `${coveragePercent}%` }"></i></div>
            <small>覆盖表示研判与证据积累程度，不代表市场规模或增长率。</small>
          </aside>
        </div>

        <section class="theme-categories" aria-labelledby="theme-categories-title">
          <div class="theme-section-heading"><div><span class="theme-section-mark"></span><div><h3 id="theme-categories-title">细分领域</h3><p>从具体领域进入，查看趋势判断与支撑证据</p></div></div><span>{{ currentTopic.categories?.length || 0 }} 个观察方向</span></div>
          <div class="theme-category-grid">
            <button v-for="(category, index) in currentTopic.categories || []" :key="category.id" class="theme-category-card" :class="{ 'has-report': judgementForCategory(category.id)?.report, 'category-needs-update': judgementForCategory(category.id)?.freshness === 'stale' }" type="button" @click="openJudgement(category.id)">
              <span class="theme-category-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="theme-category-main"><strong>{{ category.name }}</strong><small>{{ judgementForCategory(category.id)?.report?.conclusion || category.description }}</small></span>
              <span class="theme-category-state" :class="`state-${judgementForCategory(category.id)?.freshness || 'missing'}`"><i></i>{{ judgementStatus(judgementForCategory(category.id)) }}</span>
              <span class="theme-category-foot"><span>{{ category.observation_count || 0 }} 条依据</span><span>{{ category.latest_at ? `更新于 ${formatDate(category.latest_at)}` : '暂无新记录' }}</span><span v-if="judgementForCategory(category.id)?.new_evidence_count" class="theme-pending-count">{{ judgementForCategory(category.id).new_evidence_count }} 条待吸收</span></span>
              <span class="theme-category-arrow" aria-hidden="true">↗</span>
            </button>
          </div>
        </section>

        <section class="theme-recent" aria-labelledby="theme-recent-title">
          <div class="theme-section-heading"><div><span class="theme-section-mark recent-mark"></span><div><h3 id="theme-recent-title">最近进入研究的进展</h3><p>按成果发布日期倒序；新观察归入细分领域后，成为持续更新判断的依据</p></div></div><span class="theme-section-aside">完整证据链可从细分领域进入</span></div>
          <div v-if="items.length" class="theme-signal-list">
            <button v-for="(item, index) in latestTopicItems" :key="item.id" class="theme-signal-row" type="button" @click="openObservation(item)">
              <span class="theme-signal-marker" :class="{ 'signal-latest': index === 0 }"><i></i></span>
              <time>{{ formatDate(item.published_at || item.captured_at) }}</time>
              <span class="theme-signal-copy"><strong>{{ item.title }}</strong><small>{{ item.summary || '打开研究观察查看详细内容与来源。' }}</small></span>
              <span class="theme-signal-category">{{ categoryLabel(item) }}</span><span class="theme-signal-arrow" aria-hidden="true">↗</span>
            </button>
          </div>
          <div v-else class="theme-signals-empty"><span aria-hidden="true">⌁</span><p>还没有进入这个主题的研究观察。可以先给小察一个话题或来源链接，让它开始收集与核验。</p><button type="button" @click="openCreate">添加第一条研究依据</button></div>
        </section>

        <div v-if="currentTopic.unclassified_count" class="theme-unclassified-notice"><span>有 {{ currentTopic.unclassified_count }} 条观察尚未归入细分领域</span><button type="button" @click="openUnclassifiedEvidence">确认分类</button></div>
        </template>
      </section>

      <section v-if="trashMode || reviewMode" class="content-section" aria-labelledby="observations-heading">
        <div class="section-heading feed-heading">
          <div><span class="section-kicker">{{ trashMode ? 'RECYCLE BIN' : 'CLASSIFICATION REVIEW' }}</span><h2 id="observations-heading">{{ trashMode ? '回收站' : `${currentTopic?.name || '研究'} · 待分类依据` }}</h2></div>
          <div class="feed-actions">
            <span class="result-count">{{ trashMode ? `${displayItems.length} 条已删除 · 共 ${deletedCount} 条` : `${displayItems.length} 条待分类依据` }}</span>
            <button v-if="trashMode" class="secondary-button" type="button" @click="toggleTrash">返回研究主题</button>
            <button v-else class="secondary-button" type="button" @click="closeUnclassifiedEvidence">返回研究主题</button>
          </div>
        </div>

        <div v-if="error" class="notice error-notice" role="alert">{{ error }} <button type="button" @click="loadWorkbench">重试</button></div>
        <div v-else-if="loading" class="loading-state" role="status"><span class="loader-ring"></span>正在整理研究记录…</div>
        <div v-else-if="displayItems.length" class="observation-layout">
          <div class="observation-list" aria-label="研究观察列表">
            <article v-for="(item, index) in displayItems" :key="item.id" class="observation-row">
              <button type="button" class="observation-card" :disabled="trashMode" @click="openObservation(item)">
                <div class="observation-topline"><span class="record-index">{{ String(index + 1).padStart(2, '0') }}</span><span class="ingest-badge" :class="`method-${item.ingest_method}`">{{ methodLabel(item.ingest_method) }}</span><time>{{ formatDate(item.captured_at) }}</time></div>
                <h3>{{ item.title }}</h3><p>{{ item.summary || '暂无摘要' }}</p>
                <div class="card-foot"><span class="category-tag" :class="{ unclassified: !item.category_id }">{{ categoryLabel(item) }}</span><span class="source-count">◉ {{ item.sources?.length || 0 }} 个来源</span><span v-if="item.source_name" class="source-name">{{ item.source_name }}</span><span v-if="trashMode && item.deleted_at" class="deleted-at">移入回收站 {{ formatDate(item.deleted_at) }}</span><span v-if="!trashMode" class="open-arrow">查看证据 ↗</span></div>
              </button>
              <div v-if="reviewMode" class="record-tools">
                <label class="category-editor"><span>所属领域</span>
                  <select :value="item.category_id || ''" :disabled="savingCategoryId === item.id" :aria-label="`设置“${item.title}”的所属领域`" @click.stop @change="saveItemCategory(item, $event)">
                    <option value="">待分类</option>
                    <option v-for="category in currentTopic?.categories || []" :key="category.id" :value="category.id">{{ category.name }}</option>
                  </select>
                  <span v-if="savingCategoryId === item.id" class="category-saving">保存中</span>
                </label>
                <button v-if="item.can_delete" class="record-action delete-action" type="button" :disabled="busyId === item.id" @click="requestDelete(item)">移入回收站</button>
              </div>
              <button v-if="trashMode && item.can_restore" class="record-action restore-action" type="button" :disabled="busyId === item.id" @click="restoreItem(item)">{{ busyId === item.id ? '恢复中…' : '恢复' }}</button>
            </article>
          </div>
        </div>
        <div v-else class="empty-layout">
          <div class="empty-card">
            <div class="empty-illustration" aria-hidden="true"><span class="empty-sun"></span><span class="empty-horizon"></span><span class="empty-line line-1"></span><span class="empty-line line-2"></span><span class="empty-line line-3"></span></div>
            <div class="empty-copy"><span class="section-kicker">{{ trashMode ? 'NOTHING IN THE BIN' : 'ALL CLASSIFIED' }}</span><h3>{{ trashMode ? '回收站是空的' : '待分类记录已处理' }}</h3><p>{{ trashMode ? '被移入回收站的研究观察会显示在这里；你可以随时恢复，正文与来源都会保留。' : '新采集内容会由小察判断所属细分领域。' }}</p></div>
          </div>
        </div>
        <div v-if="actionError" class="notice error-notice" role="alert">{{ actionError }} <button type="button" @click="actionError = ''">关闭</button></div>
      </section>

      <section v-if="!isTopicDashboard" class="acquisition-strip" aria-label="数据获取与配置">
        <div class="acquisition-intro"><span class="section-kicker">COLLECTION PIPELINE</span><h2>让研究持续发生</h2><p>同一套 agent run 支撑专题研究与后台采集任务。</p></div>
        <div class="pipeline-step"><span class="step-icon source-icon">01</span><div><b>自动采集任务</b><small>{{ enabledTaskCount }} 个任务运行中 / {{ tasks.length }} 个已配置</small></div><span class="step-state" :class="{ 'active-state': enabledTaskCount }">{{ enabledTaskCount ? '运行中' : '待启用' }}</span></div>
        <span class="pipeline-connector" aria-hidden="true">→</span>
        <div class="pipeline-step"><span class="step-icon agent-icon">02</span><div><b>Agent 研究注入</b><small>小察完成核验后写入主题观察</small></div><span class="step-state active-state">已打通</span></div>
        <span class="pipeline-connector" aria-hidden="true">→</span>
        <div class="pipeline-step"><span class="step-icon signal-icon">03</span><div><b>更新分类与主题研判</b><small>新证据更新细分判断，再汇总为主题趋势</small></div><span class="step-state">持续演进</span></div>
      </section>

      <section v-if="!isTopicDashboard" class="task-monitor" aria-label="小察采集任务">
        <div class="task-monitor-heading"><span>采集任务</span><small>{{ tasks.length }} 项 · 状态同步自自动任务</small></div>
        <div v-if="tasks.length" class="task-list">
          <div v-for="task in tasks" :key="task.id" class="task-row">
            <span class="task-status-dot" :class="{ enabled: task.enabled }"></span>
            <span class="task-name">{{ task.name }}</span>
            <span class="task-trigger">{{ task.trigger_type === 'cron' ? `定时 ${task.cron_expr || ''}` : '事件触发' }}</span>
            <span class="task-last-run">{{ task.last_run_at ? `最近运行 ${formatDateTime(task.last_run_at)}` : '尚未运行' }}</span>
            <span class="task-state-label" :class="{ enabled: task.enabled }">{{ task.enabled ? (task.last_status || '已启用') : '已停用' }}</span>
          </div>
        </div>
        <p v-else class="no-tasks">还没有配置小察采集任务<span v-if="auth.isAdmin">，可从右上角配置入口创建。</span></p>
      </section>

      <footer class="desk-footer"><span>小察 · 行业深度研究</span><span>所有研究观察保留采集方式、时间与来源，便于复核。</span><span>UNIEMPLOYEE <b>／</b> RESEARCH DESK</span></footer>
    </div>

    <MarketIntelCollectionDialog
      v-if="createOpen"
      :topics="topics"
      :initial-topic="selectedTopic"
      :initial-category="selectedCategoryId === '__unclassified__' ? '' : selectedCategoryId"
      @close="createOpen = false"
      @saved="handleCollectionSaved"
      @open="openSavedObservation"
    />

    <div v-if="deleteTarget" class="modal-backdrop confirm-backdrop" @click.self="deleteTarget = null">
      <section class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <span class="confirm-mark" aria-hidden="true">↘</span>
        <h2 id="delete-title">移入回收站？</h2>
        <p>“{{ deleteTarget.title }}”会从研究列表中隐藏。记录正文、来源和关联的 AI 研判都会保留，你可以在回收站恢复。</p>
        <div class="confirm-actions"><button class="secondary-button" type="button" :disabled="busyId === deleteTarget.id" @click="deleteTarget = null">取消</button><button class="danger-button" type="button" :disabled="busyId === deleteTarget.id" @click="confirmDelete">{{ busyId === deleteTarget.id ? '处理中…' : '移入回收站' }}</button></div>
      </section>
    </div>
  </main>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../../../api.js'
import { useAuthStore } from '../../../stores/auth.js'
import MarketIntelCollectionDialog from './MarketIntelCollectionDialog.vue'
import EmbodiedTechnologyRadar from './EmbodiedTechnologyRadar.vue'
import MarketIntelLinkIntake from './MarketIntelLinkIntake.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const topics = ref([])
const items = ref([])
const tasks = ref([])
const deletedCount = ref(0)
const trashMode = ref(route.query.view === 'trash')
const reviewMode = ref(route.query.evidence === 'unclassified')
const selectedCategoryId = ref(typeof route.query.category === 'string' ? route.query.category : '')
const deleteTarget = ref(null)
const busyId = ref('')
const savingCategoryId = ref('')
const actionError = ref('')
const judgementOverview = ref(null)
const routeTopicId = route.params.topicId || route.query.topic
const selectedTopic = ref(routeTopicId ? String(routeTopicId) : 'embodied-intelligence')
const loading = ref(true)
const error = ref('')
const openConfigMenu = ref(false)
const createOpen = ref(false)
const collectionBusy = ref(false)
const collectionTopicId = ref('')
const collectionError = ref('')
const sourceDocSummary = ref({})
const sourceDocTopicCounts = ref({})

const isTopicDashboard = computed(() => route.name === 'market-intel-topic')
const currentTopic = computed(() => topics.value.find(topic => topic.id === selectedTopic.value))
const isEmbodiedTopic = computed(() => currentTopic.value?.id === 'embodied-intelligence')
const topicJudgement = computed(() => judgementOverview.value?.topic_report || null)
const displayItems = computed(() => items.value)
const latestTopicItems = computed(() => [...items.value]
  .sort((a, b) => {
    const publishedA = Date.parse(a.published_at || a.captured_at || '')
    const publishedB = Date.parse(b.published_at || b.captured_at || '')
    const timeA = Number.isFinite(publishedA) ? publishedA : 0
    const timeB = Number.isFinite(publishedB) ? publishedB : 0
    return timeB - timeA || String(b.captured_at || '').localeCompare(String(a.captured_at || ''))
  })
  .slice(0, 4))
const reportedCategoryCount = computed(() => Number(judgementOverview.value?.reported_category_count || 0))
const pendingEvidenceCount = computed(() => (judgementOverview.value?.categories || []).reduce((sum, category) => sum + Number(category.new_evidence_count || 0), 0))
const embodiedTechEvidenceCount = computed(() => embodiedTechTracks.reduce((sum, track) => sum + categoryEvidenceCount(track.categoryId), 0))
const coveragePercent = computed(() => {
  const total = Number(judgementOverview.value?.category_count || currentTopic.value?.categories?.length || 0)
  return total ? Math.min(100, Math.round(reportedCategoryCount.value / total * 100)) : 0
})
const strongestCategory = computed(() => [...(judgementOverview.value?.categories || [])]
  .filter(category => Number(category.evidence_count || 0) > 0)
  .sort((a, b) => Number(b.evidence_count || 0) - Number(a.evidence_count || 0))[0] || null)
const totalObservations = computed(() => topics.value.reduce((sum, topic) => sum + Number(topic.observation_count || 0), 0))
const activeSourceDocCount = computed(() => {
  const summary = isTopicDashboard.value
    ? sourceDocTopicCounts.value[selectedTopic.value]
    : sourceDocSummary.value
  return Number(summary?.unverified || 0) + Number(summary?.needs_review || 0)
})
const coveredTopics = computed(() => topics.value.filter(topic => Number(topic.observation_count || 0) > 0).length)
const unclassifiedTotal = computed(() => topics.value.reduce((sum, topic) => sum + Number(topic.unclassified_count || 0), 0))
const enabledTaskCount = computed(() => tasks.value.filter(task => Number(task.enabled) === 1 || task.enabled === true).length)
const embodiedTechTracks = [
  { code: 'T01', title: 'VLA 与具身推理', description: '观察视觉、语言与动作统一建模，重点看跨任务泛化和真实机器人验证。', categoryId: 'vla-embodied-reasoning' },
  { code: 'T02', title: '世界模型与空间智能', description: '跟踪环境表征、空间理解、状态预测与面向行动的规划能力。', categoryId: 'world-model-spatial-intelligence' },
  { code: 'T03', title: '机器人学习与数据', description: '关注数据采集、示教学习、训练规模和跨本体迁移。', categoryId: 'robot-learning-data' },
  { code: 'T04', title: '灵巧操作与全身控制', description: '追踪灵巧操作、触觉反馈、动态运动和全身协调的进展。', categoryId: 'dexterous-manipulation-whole-body' },
  { code: 'T05', title: '仿真训练与工具链', description: '观察仿真环境、训练框架、合成数据与 Sim-to-Real 差距。', categoryId: 'simulation-training-toolchain' },
  { code: 'T06', title: '评测、安全与 Agent 融合', description: '关注能力基准、安全验证、可靠运行与 Agent 系统集成。', categoryId: 'evaluation-safety-agent-integration' },
]
const embodiedMaturityStages = [
  { level: 'L1', title: '实验室验证', description: '受控环境完成单项任务演示' },
  { level: 'L2', title: '真实场景试点', description: '进入客户现场开展小规模试用' },
  { level: 'L3', title: '付费部署', description: '客户付费，持续承担生产任务' },
  { level: 'L4', title: '规模化复制', description: '跨客户、跨场景稳定复用' },
]
const embodiedScenes = [
  { categoryId: 'industrial-robots', title: '制造现场', note: '现有记录以传统工业机器人市场与产量为主，作为自动化背景参照。' },
  { categoryId: 'commercial-service-robots', title: '商业服务', note: '已有服务机器人观察；需补客户、运行时长与人工介入等部署指标。' },
  { categoryId: 'home-service-robots', title: '家庭服务', note: '尚无有效观察，后续重点跟踪家务任务与家庭环境适应性。' },
]
const embodiedChainCategories = ['embodied-models', 'robot-platforms', 'industrial-robots', 'commercial-service-robots', 'robot-commercialization']
const hasIndustrialRobotEvidence = computed(() => items.value.some(item => item.category_id === 'industrial-robots'))

function topicSymbol(id) {
  return ({ 'embodied-intelligence': '◈', 'ai-frontier': '✳', 'policy-analysis': '§' })[id] || '◉'
}
function judgementForCategory(id) {
  return judgementOverview.value?.categories?.find(item => item.id === id) || null
}
function categoryName(id) {
  return currentTopic.value?.categories?.find(category => category.id === id)?.name || '细分领域'
}
function categoryEvidenceCount(id) {
  return Number(judgementForCategory(id)?.evidence_count ?? currentTopic.value?.categories?.find(category => category.id === id)?.observation_count ?? 0)
}
function judgementStatus(item) {
  if (!item?.report) return '尚未形成研判'
  if (item.freshness === 'stale') return `${item.new_evidence_count || 0} 条新依据待吸收`
  return '判断已更新'
}
function confidenceLabel(value) { return ({ high: '较高', medium: '中等', low: '有限' })[value] || '中等' }
function methodLabel(method) { return ({ agent: 'Agent 研究', manual: '手动录入', source_task: '来源任务', file_import: '文件导入' })[method] || '研究记录' }
function formatDate(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
function formatDateTime(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}
function formatCount(value) { return Number(value || 0).toLocaleString('zh-CN') }

async function loadSourceDocSummary() {
  if (!auth.isAdmin) return
  try {
    const { data } = await api.get('/market-research/source-documents/summary')
    sourceDocSummary.value = data.overall || {}
    sourceDocTopicCounts.value = data.topics || {}
  } catch {
    sourceDocSummary.value = {}
    sourceDocTopicCounts.value = {}
  }
}

async function loadWorkbench() {
  loading.value = true
  error.value = ''
  if (isTopicDashboard.value) judgementOverview.value = null
  try {
    const params = { limit: (trashMode.value || reviewMode.value) ? 100 : (isTopicDashboard.value ? 8 : 1), include_deleted: trashMode.value }
    if (!trashMode.value) {
      if (isTopicDashboard.value || reviewMode.value) params.topic_id = selectedTopic.value
      if (reviewMode.value) {
        params.category_id = ''
      }
    }
    const [workbenchResult, judgementResult] = await Promise.all([
      api.get('/market-research/workbench', { params }),
      (trashMode.value || reviewMode.value || !isTopicDashboard.value)
        ? Promise.resolve(null)
        : api.get(`/market-research/judgements/${encodeURIComponent(selectedTopic.value)}`),
    ])
    const { data } = workbenchResult
    topics.value = data.topics || []
    items.value = data.items || []
    if (judgementResult) judgementOverview.value = judgementResult.data
    tasks.value = data.tasks || []
    deletedCount.value = Number(data.deleted_count || 0)
  } catch (err) {
    error.value = err.response?.data?.detail || '研究记录暂时无法加载，请检查连接后重试。'
  } finally {
    loading.value = false
  }
}

function selectTopic(id) {
  if (isTopicDashboard.value && selectedTopic.value === id) return
  selectedCategoryId.value = ''
  trashMode.value = false
  reviewMode.value = false
  router.push({ name: 'market-intel-topic', params: { topicId: id } })
}
function backToThemes() {
  trashMode.value = false
  reviewMode.value = false
  router.push({ name: 'market-intel' })
}
function categoryLabel(item) {
  if (!item.category_id) return '待分类'
  return item.category_name || currentTopic.value?.categories?.find(category => category.id === item.category_id)?.name || '其他领域'
}
function openJudgement(categoryId = '') {
  const params = { topicId: selectedTopic.value }
  if (categoryId) params.categoryId = categoryId
  router.push({ name: 'market-intel-judgement', params })
}
function openUnclassifiedEvidence() {
  trashMode.value = false
  reviewMode.value = true
  selectedCategoryId.value = '__unclassified__'
  router.replace({ name: 'market-intel', query: { topic: selectedTopic.value, evidence: 'unclassified' } })
  loadWorkbench()
}
function closeUnclassifiedEvidence() {
  reviewMode.value = false
  selectedCategoryId.value = ''
  router.replace({ name: 'market-intel', query: { topic: selectedTopic.value } })
  loadWorkbench()
}
async function saveItemCategory(item, event) {
  const categoryId = event.target.value
  if (categoryId === (item.category_id || '') || savingCategoryId.value) return
  savingCategoryId.value = item.id
  actionError.value = ''
  try {
    const { data } = await api.put(`/market-research/observations/${encodeURIComponent(item.id)}/category`, {
      category_id: categoryId,
    })
    Object.assign(item, data)
    await loadWorkbench()
  } catch (err) {
    event.target.value = item.category_id || ''
    actionError.value = err.response?.data?.detail || '更新细分领域失败，请稍后重试。'
  } finally {
    savingCategoryId.value = ''
  }
}
function toggleTrash() {
  trashMode.value = !trashMode.value
  reviewMode.value = false
  actionError.value = ''
  router.replace({ name: 'market-intel', query: trashMode.value ? { view: 'trash' } : { topic: selectedTopic.value } })
  loadWorkbench()
}
function requestDelete(item) {
  actionError.value = ''
  deleteTarget.value = item
}
async function confirmDelete() {
  const item = deleteTarget.value
  if (!item || busyId.value) return
  busyId.value = item.id
  actionError.value = ''
  try {
    await api.delete(`/market-research/observations/${encodeURIComponent(item.id)}`)
    deleteTarget.value = null
    await loadWorkbench()
  } catch (err) {
    actionError.value = err.response?.data?.detail || '移入回收站失败，请稍后重试。'
  } finally {
    busyId.value = ''
  }
}
async function restoreItem(item) {
  if (busyId.value) return
  busyId.value = item.id
  actionError.value = ''
  try {
    await api.post(`/market-research/observations/${encodeURIComponent(item.id)}/restore`)
    await loadWorkbench()
  } catch (err) {
    actionError.value = err.response?.data?.detail || '恢复失败，请稍后重试。'
  } finally {
    busyId.value = ''
  }
}
function openObservation(item) {
  router.push({ name: 'market-intel-observation', params: { id: item.id }, query: { topic: item.topic_id, category: item.category_id || undefined } })
}
function goConfig(name) {
  router.push({ name, params: { id: 'market-intel' } })
  openConfigMenu.value = false
}
async function startCollection() {
  if (collectionBusy.value) return
  collectionBusy.value = true
  collectionError.value = ''
  try {
    const requestId = globalThis.crypto?.randomUUID?.() || `mcb-${Date.now()}-${Math.random().toString(16).slice(2)}`
    const { data } = await api.post('/market-research/collection-batches', {
      request_id: requestId,
      topic_id: isTopicDashboard.value ? selectedTopic.value : collectionTopicId.value,
      mode: 'fetch_only',
      max_items: 500,
    })
    await router.push({ name: 'market-intel-collection-detail', params: { batchId: data.id } })
  } catch (err) {
    collectionError.value = err.response?.data?.detail || '启动采集批次失败。'
  } finally { collectionBusy.value = false }
}
function openCreate() {
  createOpen.value = true
}
async function handleCollectionSaved(item) {
  const changingTopic = isTopicDashboard.value && selectedTopic.value !== item.topic_id
  selectedTopic.value = item.topic_id
  if (changingTopic) {
    router.replace({ name: 'market-intel-topic', params: { topicId: item.topic_id } })
  }
  selectedCategoryId.value = item.category_id || ''
  trashMode.value = false
  reviewMode.value = false
  if (!changingTopic) await loadWorkbench()
}
function openSavedObservation(item) {
  createOpen.value = false
  router.push({ name: 'market-intel-observation', params: { id: item.id }, query: { topic: item.topic_id, category: item.category_id || undefined } })
}
function onEscape(event) {
  if (event.key === 'Escape') {
    openConfigMenu.value = false
    deleteTarget.value = null
  }
}

onMounted(() => {
  loadWorkbench()
  loadSourceDocSummary()
  window.addEventListener('keydown', onEscape)
})
watch(() => route.params.topicId, (topicId, previousTopicId) => {
  if (!topicId || String(topicId) === String(previousTopicId || '')) return
  selectedTopic.value = String(topicId)
  trashMode.value = false
  reviewMode.value = false
  selectedCategoryId.value = ''
  loadWorkbench()
  loadSourceDocSummary()
})
onBeforeUnmount(() => window.removeEventListener('keydown', onEscape))
</script>

<style scoped>
.research-desk
{
  --paper: var(--ue-gray-100);
  --paper-deep: var(--ue-gray-200);
  --ink: var(--ue-gray-900);
  --muted: var(--ue-gray-500);
  --rule: var(--ue-gray-200);
  --accent: var(--ue-blue-500);
  --accent-light: var(--ue-blue-50);
  --amber: #b45309;
  min-height: 100%;
  padding: 0 36px 28px;
  color: var(--ink);
  background:
    radial-gradient(ellipse at 86% 4%, rgba(59, 130, 246, .08), transparent 30%),
    linear-gradient(120deg, rgba(255,255,255,.76), transparent 52%), var(--paper);
  font-family: 'DM Sans', 'Noto Sans SC', sans-serif;
  font-size: 14px;
  line-height: 1.65;
}
.desk-wrap
{
  max-width: 1510px;
  margin: 0 auto;
}
.desk-masthead
{
  height: 80px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--rule);
  position: relative;
  z-index: 4;
}
.identity-lockup
{
  display: flex;
  align-items: center;
  gap: 13px;
}
.seal
{
  position: relative;
  width: 40px;
  height: 40px;
  background: var(--accent);
  color: #ffffff;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: 'Noto Serif SC', serif;
  font-size: 18px;
  box-shadow: inset 0 0 0 1px #f8fafc;
}
.seal i
{
  position: absolute;
  width: 7px;
  height: 7px;
  right: -1px;
  bottom: 1px;
  border: 2px solid var(--paper);
  border-radius: 50%;
  background: #3b82f6;
}
.wordmark
{
  font: 700 17px/1.35 'Noto Serif SC', serif;
  letter-spacing: .02em;
}
.wordmark span
{
  margin-left: 8px;
  color: #64748b;
  font: 500 10px 'DM Mono', monospace;
  letter-spacing: .11em;
  vertical-align: 2px;
}
.desk-label
{
  margin-top: 2px;
  color: #64748b;
  font-size: 13px;
  letter-spacing: .04em;
}
.label-dot
{
  display: inline-block;
  width: 3px;
  height: 3px;
  margin: 0 6px 2px;
  border-radius: 50%;
  background: #3b82f6;
}
.mast-actions
{
  display: flex;
  align-items: center;
  gap: 16px;
  position: relative;
}
.updated-stamp
{
  color: #64748b;
  font: 12px 'DM Sans', 'Noto Sans SC', sans-serif;
  letter-spacing: .02em;
}
.collection-start-button,.collection-progress-button
{
  padding: 8px 11px;
  border: 1px solid #bd9b72;
  border-radius: 6px;
  color: #805d36;
  background: #fffaf3;
  cursor: pointer;
  font: 600 12px 'Noto Sans SC',sans-serif;
  white-space: nowrap;
}
.collection-progress-button { border-color:#e2e8f0; color:#65788a; background:#fff; }
.source-documents-button { display:inline-flex; align-items:center; gap:7px; }
.source-documents-count { padding:2px 6px; border-radius:999px; color:#755a36; background:#f7f0e5; font-size:10px; font-weight:500; }
.collection-start-button:disabled { opacity:.6; cursor:wait; }
.pulse-dot,.live-tick
{
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 6px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16,185,129,.14);
}
.icon-button
{
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 9px 13px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #ffffff;
  color: #475569;
  cursor: pointer;
  font-size: 13px;
  transition: .18s ease;
}
.icon-button:hover
{
  background: #fff;
  border-color: #93c5fd;
  color: var(--accent);
}
.icon-button svg
{
  width: 15px;
  height: 15px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.4;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.config-menu
{
  position: absolute;
  top: 42px;
  right: 0;
  width: 220px;
  padding: 6px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 16px 36px rgba(15,23,42,.12);
}
.config-menu button
{
  width: 100%;
  padding: 10px 11px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  text-align: left;
  color: #334155;
  cursor: pointer;
  font-size: 12px;
}
.config-menu button:hover
{
  background: #eff6ff;
}
.config-menu button span
{
  display: block;
  padding-top: 3px;
  color: #94a3b8;
  font-size: 12px;
}
.config-menu-divider
{
  height: 1px;
  margin: 5px 9px;
  background: #e2e8f0;
}
.hero-grid
{
  position: relative;
  min-height: 226px;
  padding: 30px 0 26px;
  display: grid;
  grid-template-columns: minmax(0,1fr) 360px;
  align-items: center;
  border-bottom: 1px solid var(--rule);
  overflow: hidden;
}
.hero-copy
{
  position: relative;
  z-index: 1;
  max-width: 720px;
}
.eyebrow,.section-kicker
{
  color: #64748b;
  font: 500 11px 'DM Mono', monospace;
  letter-spacing: .12em;
}
.eyebrow span
{
  margin: 0 5px;
  color: #3b82f6;
}
.hero-copy h1
{
  margin: 13px 0 11px;
  color: #0f172a;
  font: 600 clamp(34px, 3.3vw, 46px)/1.25 'Noto Serif SC', serif;
  letter-spacing: .045em;
}
.hero-copy h1 em
{
  color: #2563eb;
  font-style: normal;
}
.hero-intro
{
  max-width: 580px;
  margin: 0;
  color: #475569;
  font-size: 15px;
  line-height: 1.85;
}
.hero-meta
{
  margin-top: 21px;
  display: flex;
  align-items: center;
  gap: 16px;
  color: #64748b;
  font-size: 12px;
}
.hero-meta b
{
  color: #334155;
  font: 600 15px 'DM Mono', monospace;
}
.meta-divider
{
  height: 12px;
  width: 1px;
  background: #cbd5e1;
}
.hero-graphic
{
  position: relative;
  height: 225px;
  opacity: .95;
}
.orbit
{
  position: absolute;
  border: 1px solid rgba(59,130,246,.16);
  border-radius: 50%;
  transform: rotate(-23deg);
}
.orbit-one
{
  width: 270px;
  height: 120px;
  top: 53px;
  right: 28px;
}
.orbit-two
{
  width: 300px;
  height: 156px;
  top: 35px;
  right: 14px;
  transform: rotate(42deg);
}
.orbit-core
{
  position: absolute;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 113px;
  height: 113px;
  top: 58px;
  right: 107px;
  border: 1px solid rgba(59,130,246,.18);
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #ffffff, #dbeafe);
  box-shadow: 0 10px 30px rgba(15,23,42,.08);
}
.orbit-core span,.orbit-core small
{
  color: #64748b;
  font: 10px 'DM Mono', monospace;
  letter-spacing: .13em;
}
.orbit-core b
{
  padding: 4px 0;
  color: #1d4ed8;
  font: 500 24px 'Noto Serif SC', serif;
}
.orbit-label
{
  position: absolute;
  padding: 5px 9px;
  color: #64748b;
  border: 1px solid rgba(59,130,246,.14);
  background: #f8fafc;
  border-radius: 4px;
  font-size: 11px;
}
.label-a
{
  top: 31px;
  right: 92px;
}
.label-b
{
  top: 135px;
  right: 15px;
}
.label-c
{
  top: 159px;
  right: 206px;
}
.orbit-node
{
  position: absolute;
  width: 7px;
  height: 7px;
  border: 2px solid #ffffff;
  border-radius: 50%;
  background: #3b82f6;
  box-shadow: 0 0 0 1px rgba(59,130,246,.18);
}
.node-a
{
  top: 83px;
  right: 31px;
}
.node-b
{
  top: 166px;
  right: 126px;
  background: #06b6d4;
}
.node-c
{
  top: 40px;
  right: 223px;
  background: #60a5fa;
}
.topic-section,.category-section,.content-section
{
  padding: 30px 0 34px;
  border-bottom: 1px solid var(--rule);
}
.category-section
{
  padding-top: 24px;
  padding-bottom: 27px;
}
.section-heading
{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 15px;
}
.section-heading h2,.acquisition-intro h2
{
  margin: 5px 0 0;
  color: #0f172a;
  font: 600 21px 'Noto Serif SC', serif;
  letter-spacing: .025em;
}
.section-note
{
  color: #64748b;
  font-size: 12px;
}
.topic-grid
{
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  gap: 13px;
}
.topic-card
{
  position: relative;
  display: grid;
  grid-template-columns: 30px 40px minmax(0,1fr) auto;
  align-items: center;
  gap: 13px;
  min-height: 112px;
  padding: 17px 19px;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #ffffff;
  text-align: left;
  cursor: pointer;
  overflow: hidden;
  transition: .2s ease;
}
.topic-card::before
{
  position: absolute;
  content: '';
  width: 3px;
  inset: 0 auto 0 0;
  background: transparent;
  transition: .2s ease;
}
.topic-card:hover,.topic-card.selected
{
  border-color: #93c5fd;
  background: #ffffff;
  box-shadow: 0 5px 16px rgba(15,23,42,.05);
  transform: translateY(-1px);
}
.topic-card.selected::before
{
  background: #3b82f6;
}
.topic-number
{
  align-self: start;
  color: #94a3b8;
  font: 11px 'DM Mono', monospace;
}
.topic-symbol
{
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 50%;
  color: #2563eb;
  background: #eff6ff;
  font: 19px Georgia,serif;
}
.topic-copper .topic-symbol
{
  color: #b45309;
  background: #fffbeb;
  border-color: #fde68a;
}
.topic-blue .topic-symbol
{
  color: #2563eb;
  background: #eff6ff;
  border-color: #bfdbfe;
}
.topic-green .topic-symbol
{
  color: #0e7490;
  background: #ecfeff;
  border-color: #a5f3fc;
}
.topic-copy
{
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.topic-eyebrow
{
  color: #64748b;
  font: 11px 'DM Mono',monospace;
  letter-spacing: .08em;
  white-space: nowrap;
}
.topic-copy strong
{
  padding: 4px 0 3px;
  color: #0f172a;
  font: 600 16px 'Noto Serif SC',serif;
}
.topic-copy small
{
  color: #475569;
  font-size: 14px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  white-space: normal;
  max-width: 100%;
}
.topic-count
{
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding-right: 4px;
}
.topic-count b
{
  color: #334155;
  font: 500 20px 'DM Mono',monospace;
}
.topic-count small
{
  color: #94a3b8;
  font-size: 12px;
}
.topic-count .topic-source-count { margin-top:4px; color:#956b3d; font-size:10px; white-space:nowrap; }
.topic-arrow
{
  position: absolute;
  right: 8px;
  top: 8px;
  color: #94a3b8;
  font-size: 14px;
  opacity: 0;
  transform: translate(-2px,2px);
  transition: .18s ease;
}
.topic-card:hover .topic-arrow,.topic-card.selected .topic-arrow
{
  opacity: 1;
  transform: none;
}
.category-grid
{
  display: grid;
  grid-template-columns: repeat(3,minmax(0,1fr));
  gap: 10px;
}
.category-heading-actions
{
  display: flex;
  align-items: center;
  gap: 14px;
}
.category-card
{
  display: flex;
  min-width: 0;
  min-height: 168px;
  flex-direction: column;
  align-items: stretch;
  padding: 14px 16px 12px;
  border: 1px solid #dbe3ee;
  border-radius: 8px;
  color: #334155;
  background: rgba(255,255,255,.88);
  text-align: left;
  cursor: pointer;
  transition: border-color .16s ease, background-color .16s ease;
}
.category-card:hover,.category-card.selected
{
  border-color: #60a5fa;
  background: #ffffff;
}
.category-card.selected
{
  box-shadow: inset 3px 0 #3b82f6;
}
.category-card-heading
{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
}
.category-card-heading strong
{
  color: #0f172a;
  font: 600 16px 'Noto Serif SC',serif;
}
.category-card-heading b
{
  color: #1d4ed8;
  font: 500 18px 'DM Mono',monospace;
}
.category-description
{
  display: -webkit-box;
  min-height: 40px;
  margin-top: 5px;
  overflow: hidden;
  color: #64748b;
  font-size: 14px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.category-card-foot
{
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 9px;
  padding-top: 9px;
  margin-top: 2px;
  color: #94a3b8;
  font-size: 11px;
}
.report-state
{
  display: inline-flex;
  padding: 2px 7px;
  border-radius: 99px;
  color: #64748b;
  background: #edf1f6;
  font-size: 10px;
  white-space: nowrap;
}
.report-state.state-current
{
  color: #17654a;
  background: #e5f5ed;
}
.report-state.state-stale
{
  color: #965b08;
  background: #fff1d5;
}
.new-evidence-pill
{
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 5px;
  color: #a46205;
  background: #fff5df;
  font-size: 10px;
}
.category-open
{
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
  padding-top: 8px;
  color: #356eb5;
  font-size: 12px;
  font-weight: 600;
}
.category-open b
{
  font-size: 16px;
}
.category-unclassified .category-card-heading b,
.category-unclassified .category-card-foot
{
  color: #b45309;
}
.judgement-panel
{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  margin-top: 19px;
  padding: 19px 22px;
  border: 1px solid #cfe0f6;
  border-radius: 9px;
  background: linear-gradient(105deg, #ffffff 5%, #f1f7ff 100%);
  box-shadow: 0 4px 14px rgba(30,64,175,.035);
}
.judgement-copy { min-width: 0; }
.judgement-copy h2 { margin: 5px 0 3px; color: #102a56; font: 600 20px 'Noto Serif SC',serif; }
.judgement-copy p { margin: 0; color: #52657d; font-size: 14px; line-height: 1.65; }
.judgement-meta { display: flex; flex-wrap: wrap; gap: 7px 18px; margin-top: 9px; color: #8190a5; font-size: 13px; }
.judgement-meta b { color: #1d4ed8; font: 600 13px 'DM Mono',monospace; }
.judgement-button
{
  display: flex;
  min-width: 280px;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid #a9c8f3;
  border-radius: 8px;
  color: #1747a6;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: .16s ease;
}
.judgement-button:hover:not(:disabled) { border-color: #60a5fa; background: #f8fbff; box-shadow: 0 4px 13px rgba(37,99,235,.09); }
.judgement-button:disabled { color: #94a3b8; border-color: #e2e8f0; cursor: not-allowed; }
.judgement-button-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; border-radius: 9px; color: #2563eb; background: #eff6ff; font-size: 19px; }
.judgement-button > span:nth-child(2) { display: flex; min-width: 0; flex: 1; flex-direction: column; gap: 2px; }
.judgement-button strong { font-size: 13px; font-weight: 650; }
.judgement-button small { color: #8190a5; font-size: 12px; }
.judgement-arrow { font-size: 17px; }
.content-section
{
  padding-top: 34px;
}
.feed-heading
{
  margin-bottom: 17px;
}
.feed-heading h2
{
  font-size: 23px;
}
.feed-heading .section-kicker
{
  display: flex;
  align-items: center;
}
.live-tick
{
  width: 5px;
  height: 5px;
  margin: 0 0 0 8px;
}
.feed-actions
{
  display: flex;
  align-items: center;
  gap: 15px;
}
.secondary-button
{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 39px;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  color: #475569;
  background: #ffffff;
  cursor: pointer;
  font: 600 13px 'DM Sans', 'Noto Sans SC', sans-serif;
  transition: .16s ease;
}
.secondary-button:hover
{
  color: #1d4ed8;
  border-color: #93c5fd;
  background: #eff6ff;
}
.secondary-button:disabled
{
  opacity: .6;
  cursor: wait;
}
.result-count
{
  color: #64748b;
  font: 12px 'DM Sans', 'Noto Sans SC', sans-serif;
}
.add-button
{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 15px;
  border: 1px solid #2563eb;
  border-radius: 7px;
  color: #ffffff;
  background: #3b82f6;
  cursor: pointer;
  font-size: 13px;
  transition: .18s ease;
}
.add-button:hover
{
  background: #2563eb;
  box-shadow: 0 4px 12px rgba(37,99,235,.18);
}
.add-button:disabled
{
  opacity: .55;
  cursor: wait;
}
.add-button span
{
  font-size: 16px;
  line-height: 10px;
}
.observation-layout
{
  display: grid;
  grid-template-columns: minmax(0,1fr);
  align-items: start;
  gap: 14px;
}
.observation-list
{
  display: grid;
  gap: 11px;
}
.observation-row
{
  position: relative;
  min-width: 0;
}
.observation-card
{
  width: 100%;
  padding: 18px 20px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 9px;
  background: #ffffff;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: .16s ease;
}
.observation-card:hover
{
  border-color: #93c5fd;
  background: #ffffff;
  box-shadow: 0 4px 14px rgba(15,23,42,.06);
}
.observation-card:disabled
{
  cursor: default;
}
.observation-card:disabled:hover
{
  border-color: #e2e8f0;
  background: #ffffff;
  box-shadow: none;
}
.record-action
{
  min-width: 54px;
  padding: 5px 9px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: rgba(255,255,255,.95);
  cursor: pointer;
  font: 600 12px 'DM Sans', 'Noto Sans SC', sans-serif;
  transition: .16s ease;
}
.observation-row:has(.record-action) .observation-topline time
{
  margin-right: 0;
}
.record-tools
{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 4px 0;
}
.category-editor
{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
}
.category-editor select
{
  max-width: min(320px,58vw);
  padding: 5px 28px 5px 8px;
  border: 1px solid #dbe3ee;
  border-radius: 6px;
  color: #334155;
  background: #fff;
  font: 12px 'DM Sans','Noto Sans SC',sans-serif;
}
.category-editor select:focus-visible
{
  outline: 3px solid #dbeafe;
  border-color: #60a5fa;
}
.category-editor select:disabled
{
  opacity: .6;
}
.category-saving
{
  color: #2563eb;
}
.delete-action
{
  color: #b91c1c;
  border-color: #fecaca;
}
.delete-action:hover
{
  background: #fef2f2;
  border-color: #fca5a5;
}
.restore-action
{
  color: #1d4ed8;
  border-color: #bfdbfe;
}
.restore-action:hover
{
  background: #eff6ff;
  border-color: #93c5fd;
}
.record-action:disabled
{
  opacity: .6;
  cursor: wait;
}
.observation-topline
{
  display: flex;
  align-items: center;
  gap: 10px;
  color: #64748b;
  font: 12px 'DM Sans', 'Noto Sans SC', sans-serif;
}
.observation-topline time
{
  margin-left: auto;
}
.record-index
{
  color: #94a3b8;
}
.ingest-badge
{
  padding: 4px 8px;
  border-radius: 5px;
  color: #2563eb;
  background: #eff6ff;
  font: 11px 'DM Sans',sans-serif;
}
.method-source_task
{
  color: #1d4ed8;
  background: #eff6ff;
}
.method-manual
{
  color: #b45309;
  background: #fffbeb;
}
.method-file_import
{
  color: #0f766e;
  background: #ecfdf5;
}
.observation-card h3
{
  margin: 12px 0 7px;
  color: #0f172a;
  font: 600 17px/1.55 'Noto Serif SC',serif;
}
.observation-card p
{
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
  min-height: 48px;
  margin: 0;
  color: #475569;
  font-size: 15px;
  line-height: 1.75;
}
.card-foot
{
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 13px;
  margin-top: 12px;
  border-top: 1px solid #e2e8f0;
  color: #94a3b8;
  font-size: 12px;
}
.category-tag
{
  flex: 0 0 auto;
  padding: 3px 8px;
  border: 1px solid #bfdbfe;
  border-radius: 99px;
  color: #1d4ed8;
  background: #eff6ff;
  font-size: 11px;
  line-height: 1.5;
}
.category-tag.unclassified
{
  border-color: #fde68a;
  color: #92400e;
  background: #fffbeb;
}
.source-count
{
  color: #64748b;
}
.source-name
{
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.open-arrow
{
  margin-left: auto;
  color: #2563eb;
}
.deleted-at
{
  color: #b45309;
}
.confirm-backdrop
{
  z-index: 20;
}
.confirm-modal
{
  width: min(100%, 460px);
  padding: 27px 29px 23px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #ffffff;
  box-shadow: 0 24px 80px rgba(15,23,42,.2);
}
.confirm-mark
{
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 10px;
  color: #b45309;
  background: #fffbeb;
  font-size: 20px;
}
.confirm-modal h2
{
  margin: 16px 0 7px;
  color: #0f172a;
  font-size: 20px;
}
.confirm-modal p
{
  margin: 0;
  color: #475569;
  font-size: 14px;
  line-height: 1.8;
}
.confirm-actions
{
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  margin-top: 24px;
}
.danger-button
{
  min-height: 39px;
  padding: 8px 13px;
  border: 1px solid #b91c1c;
  border-radius: 7px;
  color: #ffffff;
  background: #dc2626;
  cursor: pointer;
  font: 600 13px 'DM Sans', 'Noto Sans SC', sans-serif;
}
.danger-button:hover
{
  background: #b91c1c;
}
.danger-button:disabled
{
  opacity: .6;
  cursor: wait;
}
.empty-layout
{
  min-height: 235px;
  display: grid;
  place-items: stretch;
}
.empty-card
{
  display: grid;
  grid-template-columns: 200px 1fr;
  align-items: center;
  min-height: 235px;
  padding: 22px 5.5%;
  border: 1px dashed #cbd5e1;
  border-radius: 7px;
  background: #ffffff;
}
.empty-illustration
{
  position: relative;
  width: 148px;
  height: 130px;
  margin: auto;
  overflow: hidden;
}
.empty-horizon
{
  position: absolute;
  inset: 65px 0 0;
  border-radius: 60% 40% 0 0;
  background: linear-gradient(150deg,#dbeafe,#eff6ff);
}
.empty-sun
{
  position: absolute;
  top: 13px;
  left: 54px;
  width: 50px;
  height: 50px;
  border-radius: 50%;
  background: #bfdbfe;
  box-shadow: 0 0 0 10px rgba(59,130,246,.12);
}
.empty-line
{
  position: absolute;
  height: 1px;
  background: #93c5fd;
  transform-origin: left;
}
.line-1
{
  width: 57px;
  top: 58px;
  left: 20px;
  transform: rotate(-21deg);
}
.line-2
{
  width: 64px;
  top: 80px;
  left: 83px;
  transform: rotate(-27deg);
}
.line-3
{
  width: 80px;
  top: 95px;
  left: 13px;
  transform: rotate(-8deg);
}
.empty-copy
{
  max-width: 550px;
}
.empty-copy h3
{
  margin: 8px 0 7px;
  color: #0f172a;
  font: 600 18px 'Noto Serif SC',serif;
}
.empty-copy p
{
  max-width: 500px;
  margin: 0 0 14px;
  color: #64748b;
  font-size: 14px;
  line-height: 1.85;
}
.loading-state
{
  min-height: 190px;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 12px;
  color: #64748b;
  font-size: 13px;
}
.loader-ring
{
  width: 23px;
  height: 23px;
  border: 2px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
@keyframes spin
{
  to
  {
    transform: rotate(360deg);
  }
}
.notice
{
  padding: 16px 18px;
  border-radius: 7px;
  font-size: 13px;
}
.error-notice
{
  background: #fef2f2;
  color: #b91c1c;
}
.error-notice button
{
  margin-left: 10px;
  border: 0;
  background: transparent;
  color: #991b1b;
  text-decoration: underline;
  cursor: pointer;
}
.acquisition-strip
{
  display: grid;
  grid-template-columns: 1.15fr 1fr 20px 1fr 20px 1fr;
  align-items: center;
  gap: 14px;
  padding: 28px 0 26px;
  border-bottom: 1px solid var(--rule);
}
.acquisition-intro h2
{
  margin-top: 4px;
  font-size: 18px;
}
.acquisition-intro p
{
  margin: 5px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}
.pipeline-step
{
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 9px;
}
.step-icon
{
  flex: 0 0 36px;
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: 1px solid #e2e8f0;
  border-radius: 50%;
  background: #eff6ff;
  color: #2563eb;
  font: 11px 'DM Mono',monospace;
}
.agent-icon
{
  color: #b45309;
  border-color: #fde68a;
  background: #fffbeb;
}
.signal-icon
{
  color: #0e7490;
  border-color: #a5f3fc;
  background: #ecfeff;
}
.pipeline-step div
{
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pipeline-step b
{
  color: #334155;
  font-size: 13px;
  font-weight: 600;
}
.pipeline-step small
{
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.5;
}
.step-state
{
  margin-left: auto;
  padding: 4px 8px;
  border-radius: 3px;
  background: #e2e8f0;
  color: #64748b;
  font-size: 11px;
  white-space: nowrap;
}
.active-state
{
  background: #ecfdf5;
  color: #047857;
}
.pipeline-connector
{
  color: #94a3b8;
  font-size: 15px;
  text-align: center;
}
.desk-footer
{
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 19px 0 6px;
  color: #94a3b8;
  font: 11px 'DM Sans', 'Noto Sans SC', sans-serif;
  letter-spacing: .035em;
}
.desk-footer b
{
  color: #b45309;
  font-weight: 500;
}
.task-monitor
{
  padding: 19px 0 14px;
  border-bottom: 1px solid var(--rule);
}
.task-monitor-heading
{
  display: flex;
  align-items: baseline;
  gap: 11px;
  margin-bottom: 11px;
  color: #475569;
  font: 600 14px 'Noto Serif SC',serif;
}
.task-monitor-heading small
{
  color: #94a3b8;
  font: 12px 'DM Sans', 'Noto Sans SC', sans-serif;
}
.task-list
{
  display: grid;
  gap: 7px;
}
.task-row
{
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 38px;
  padding: 7px 11px;
  border-radius: 6px;
  background: #f8fafc;
  color: #64748b;
  font-size: 12px;
}
.task-status-dot
{
  width: 6px;
  height: 6px;
  flex: 0 0 6px;
  border-radius: 50%;
  background: #cbd5e1;
}
.task-status-dot.enabled
{
  background: #10b981;
  box-shadow: 0 0 0 3px rgba(16,185,129,.14);
}
.task-name
{
  color: #475569;
  font-weight: 600;
}
.task-trigger
{
  color: #94a3b8;
  font: 11px 'DM Sans', 'Noto Sans SC', sans-serif;
}
.task-last-run
{
  margin-left: auto;
  color: #94a3b8;
}
.task-state-label
{
  min-width: 40px;
  text-align: right;
  color: #94a3b8;
}
.task-state-label.enabled
{
  color: #047857;
}
.no-tasks
{
  margin: 0;
  color: #94a3b8;
  font-size: 13px;
}
.modal-backdrop
{
  position: fixed;
  z-index: 20;
  inset: 56px 0 0;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgba(15,23,42,.48);
  backdrop-filter: blur(3px);
}
@media (max-width: 1120px)
{
  .research-desk
  {
    padding: 0 26px 22px;
  }
  .hero-grid
  {
    grid-template-columns: minmax(0,1fr) 290px;
  }
  .topic-card
  {
    grid-template-columns: 24px 34px minmax(0,1fr) auto;
    gap: 8px;
    padding: 14px;
  }
  .category-grid
  {
    grid-template-columns: repeat(2,minmax(0,1fr));
  }
  .topic-count
  {
    display: none;
  }
  .topic-symbol
  {
    width: 33px;
    height: 33px;
  }
  .acquisition-strip
  {
    grid-template-columns: 1fr 1fr 14px 1fr 14px 1fr;
    gap: 7px;
  }
  .step-state
  {
    display: none;
  }
}
@media (max-width: 800px)
{
  .research-desk
  {
    padding: 0 20px 20px;
  }
  .hero-grid
  {
    min-height: 218px;
    grid-template-columns: 1fr;
  }
  .hero-copy
  {
    max-width: 620px;
  }
  .hero-graphic
  {
    position: absolute;
    top: 14px;
    right: -72px;
    width: 275px;
    opacity: .27;
    pointer-events: none;
  }
  .hero-meta
  {
    gap: 10px;
  }
  .judgement-panel
  {
    align-items: stretch;
    flex-direction: column;
    gap: 14px;
    padding: 17px;
  }
  .judgement-button
  {
    width: 100%;
  }
  .hero-meta span:last-child
  {
    display: none;
  }
  .topic-grid
  {
    grid-template-columns: 1fr;
    gap: 9px;
  }
  .topic-card
  {
    min-height: 96px;
    grid-template-columns: 28px 38px minmax(0,1fr) auto;
  }
  .topic-count
  {
    display: flex;
    padding-right: 15px;
  }
  .observation-layout
  {
    grid-template-columns: 1fr;
  }
  .acquisition-strip
  {
    grid-template-columns: 1fr;
    gap: 13px;
  }
  .acquisition-intro
  {
    padding-bottom: 3px;
  }
  .pipeline-step
  {
    padding: 2px 3px;
  }
  .step-state
  {
    display: block;
  }
  .pipeline-connector
  {
    display: none;
  }
  .desk-footer
  {
    flex-wrap: wrap;
    gap: 6px;
  }
  .desk-footer span:nth-child(2)
  {
    width: 100%;
    order: 3;
  }
  .empty-card
  {
    grid-template-columns: 125px 1fr;
    padding: 18px;
  }
  .empty-illustration
  {
    transform: scale(.8);
  }
}
@media (max-width: 520px)
{
  .research-desk
  {
    padding: 0 12px 16px;
  }
  .desk-masthead
  {
    height: 66px;
  }
  .wordmark span
  {
    display: none;
  }
  .updated-stamp
  {
    display: none;
  }
  .hero-grid
  {
    padding: 28px 0 23px;
  }
  .hero-copy h1
  {
    font-size: 30px;
  }
  .hero-intro
  {
    max-width: 350px;
    font-size: 14px;
  }
  .hero-meta
  {
    flex-wrap: wrap;
    font-size: 11px;
  }
  .hero-meta b
  {
    font-size: 13px;
  }
  .section-note
  {
    display: none;
  }
  .topic-copy small
  {
    font-size: 13px;
  }
  .category-grid
  {
    grid-template-columns: 1fr;
  }
  .category-card
  {
    min-height: 102px;
    padding: 12px 14px;
  }
  .judgement-panel
  {
    margin-top: 14px;
    padding: 15px;
  }
  .judgement-copy h2
  {
    font-size: 18px;
  }
  .judgement-meta
  {
    flex-direction: column;
    gap: 2px;
  }
  .feed-heading
  {
    align-items: flex-start;
    gap: 8px;
  }
  .feed-heading h2
  {
    font-size: 19px;
  }
  .feed-actions
  {
    flex-direction: column-reverse;
    align-items: flex-end;
    gap: 5px;
  }
  .result-count
  {
    font-size: 11px;
  }
  .feed-actions .secondary-button
  {
    min-height: 32px;
    padding: 6px 9px;
    font-size: 11px;
  }
  .add-button
  {
    padding: 9px 11px;
    font-size: 12px;
  }
  .empty-card
  {
    grid-template-columns: 1fr;
    padding: 14px;
  }
  .empty-illustration
  {
    height: 95px;
    margin-bottom: 7px;
    transform: scale(.7);
  }
  .empty-copy h3
  {
    font-size: 18px;
  }
  .observation-topline
  {
    gap: 5px;
    font-size: 11px;
  }
  .observation-card
  {
    padding: 15px;
  }
  .observation-card h3
  {
    font-size: 16px;
  }
  .observation-card p
  {
    min-height: 48px;
    font-size: 14px;
  }
  .record-tools
  {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
  }
  .category-editor
  {
    width: 100%;
    justify-content: space-between;
  }
  .category-editor select
  {
    flex: 1;
    max-width: none;
  }
  .modal-backdrop
  {
    inset: 0;
    padding: 9px;
  }
  .task-row
  {
    flex-wrap: wrap;
    gap: 8px;
    padding: 9px;
  }
  .task-name
  {
    flex: 1;
  }
  .task-trigger
  {
    width: 100%;
    padding-left: 15px;
    font-size: 11px;
  }
  .task-last-run
  {
    margin-left: 15px;
  }
}

.theme-dashboard
{
  --theme-accent: #b45309;
  --theme-accent-soft: #fff7ed;
  margin: 12px 0 22px;
  padding: 27px 30px 25px;
  border: 1px solid #dfe6ed;
  border-top: 3px solid var(--theme-accent);
  border-radius: 12px;
  background: rgba(255,255,255,.78);
  box-shadow: 0 8px 22px rgba(31, 51, 76, .035);
}
.theme-dashboard-blue { --theme-accent: #2563eb; --theme-accent-soft: #eff6ff; }
.theme-dashboard-green { --theme-accent: #0e7490; --theme-accent-soft: #ecfeff; }
.theme-dashboard-copper .theme-dashboard-head { align-items:center; min-height:55px; padding-bottom:14px; }
.theme-dashboard-head
{
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 22px;
  border-bottom: 1px solid #e8edf2;
}
.theme-breadcrumb { display:flex; align-items:center; gap:9px; color:#718096; font-size:13px; }
.theme-breadcrumb button { display:inline-flex; align-items:center; gap:5px; padding:0; border:0; color:#657990; background:transparent; cursor:pointer; font:inherit; }
.theme-breadcrumb button:hover { color:var(--theme-accent); }
.theme-breadcrumb i { color:#b1bdca; font-style:normal; }
.theme-breadcrumb b { color:#44566d; font-weight:600; }
.theme-page-state { display:flex; min-height:240px; flex-direction:column; align-items:center; justify-content:center; gap:10px; color:#52657d; }
.theme-page-state strong { color:#243a54; font-size:18px; }
.theme-page-state > span:last-child { color:#8290a1; font-size:14px; }
.theme-page-not-found button { margin-top:7px; padding:8px 12px; border:1px solid #cfdae5; border-radius:6px; color:#36506f; background:#fff; cursor:pointer; font:600 14px 'Noto Sans SC',sans-serif; }
.theme-title-line { display:flex; align-items:center; gap:14px; margin-top:11px; }
.theme-title-mark
{
  display:grid;
  width:46px;
  height:46px;
  flex:0 0 auto;
  place-items:center;
  border:1px solid color-mix(in srgb, var(--theme-accent) 25%, white);
  border-radius:50%;
  color:var(--theme-accent);
  background:var(--theme-accent-soft);
  font:24px 'Noto Serif SC',serif;
}
.theme-title-line h2 { margin:0; color:#172b45; font:600 29px/1.25 'Noto Serif SC','Noto Sans SC',serif; }
.theme-title-line p { margin:4px 0 0; color:#64748b; font-size:15px; }
.theme-head-actions { display:flex; align-items:center; gap:14px; }
.theme-updated { display:inline-flex; align-items:center; gap:7px; color:#697b90; font-size:13px; white-space:nowrap; }
.theme-updated i { width:7px; height:7px; border-radius:50%; background:#55a981; }
.theme-research-button
{
  display:inline-flex;
  align-items:center;
  gap:7px;
  min-height:40px;
  padding:8px 13px;
  border:1px solid var(--theme-accent);
  border-radius:7px;
  color:#fff;
  background:var(--theme-accent);
  cursor:pointer;
  font:600 14px 'Noto Sans SC',sans-serif;
  white-space:nowrap;
}
.theme-research-button:hover { filter:brightness(.94); }
.theme-overview-grid { display:grid; grid-template-columns:minmax(0,1.8fr) minmax(260px,.78fr); gap:15px; margin-top:17px; }
.theme-verdict-panel,.theme-coverage-panel { min-width:0; border:1px solid #e3e9ef; border-radius:9px; }
.theme-verdict-panel { padding:21px 23px 18px; background:#fff; }
.theme-panel-heading { display:flex; align-items:center; gap:8px; color:#53677e; font-size:14px; font-weight:650; }
.theme-panel-icon { display:grid; width:23px; height:23px; place-items:center; border-radius:6px; color:var(--theme-accent); background:var(--theme-accent-soft); font-size:17px; }
.theme-report-version { margin-left:auto; padding:3px 8px; border-radius:99px; color:#64748b; background:#f1f4f7; font-size:12px; font-weight:500; }
.theme-verdict-panel h3 { max-width:790px; margin:17px 0 8px; color:#1b2e46; font:600 21px/1.5 'Noto Serif SC','Noto Sans SC',serif; }
.theme-verdict-panel > p { max-width:900px; margin:0; color:#52657d; font-size:16px; line-height:1.85; }
.theme-verdict-meta { display:flex; flex-wrap:wrap; gap:8px 18px; margin-top:15px; color:#708198; font-size:13px; }
.theme-verdict-meta span + span { position:relative; }
.theme-verdict-meta span + span::before { position:absolute; top:7px; left:-10px; width:3px; height:3px; border-radius:50%; background:#b4c0cc; content:''; }
.theme-verdict-link { display:inline-flex; align-items:center; gap:8px; margin-top:15px; padding:0; border:0; color:var(--theme-accent); background:transparent; cursor:pointer; font:600 14px 'Noto Sans SC',sans-serif; }
.theme-verdict-link:disabled { color:#95a2b1; cursor:not-allowed; }
.theme-verdict-link b { font-size:16px; font-weight:500; }
.theme-coverage-panel { padding:19px 20px 17px; background:#f7f9fb; }
.coverage-icon { border-radius:50%; }
.coverage-metric { display:flex; align-items:baseline; gap:10px; margin:16px 0 12px; color:#40536b; font-size:14px; }
.coverage-metric strong { color:#1d324d; font:600 34px/1 'DM Sans','Noto Sans SC',sans-serif; letter-spacing:-.04em; }
.coverage-row { display:flex; justify-content:space-between; gap:10px; padding:8px 0; border-top:1px solid #e5ebf0; color:#687b90; font-size:13px; }
.coverage-row b { color:#354a63; font-weight:600; }
.coverage-row b.coverage-warning { color:#a76709; }
.coverage-meter { height:5px; margin-top:7px; overflow:hidden; border-radius:99px; background:#e1e8ef; }
.coverage-meter i { display:block; height:100%; border-radius:inherit; background:var(--theme-accent); transition:width .25s ease; }
.theme-coverage-panel > small { display:block; margin-top:10px; color:#8794a3; font-size:12px; line-height:1.6; }
.theme-categories,.theme-recent { margin-top:27px; }
.theme-section-heading { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:12px; }
.theme-section-heading > div { display:flex; align-items:flex-start; gap:11px; }
.theme-section-mark { width:3px; min-height:39px; border-radius:4px; background:var(--theme-accent); }
.theme-section-heading h3 { margin:0; color:#20354e; font:600 20px/1.35 'Noto Serif SC','Noto Sans SC',serif; }
.theme-section-heading p { margin:3px 0 0; color:#718198; font-size:14px; }
.theme-section-heading > span { color:#74849a; font-size:13px; white-space:nowrap; }
.theme-section-mark.recent-mark { background:#7b8da2; }
.theme-section-aside { color:#74849a; font-size:13px; }
.theme-category-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.theme-category-card
{
  position:relative;
  display:grid;
  grid-template-columns:31px minmax(0,1fr);
  gap:0 12px;
  min-height:145px;
  padding:16px 43px 14px 15px;
  border:1px solid #e1e7ed;
  border-radius:8px;
  color:inherit;
  background:#fff;
  text-align:left;
  cursor:pointer;
  transition:border-color .16s ease,background .16s ease;
}
.theme-category-card:hover { border-color:color-mix(in srgb, var(--theme-accent) 48%, white); background:#fffefd; }
.theme-category-card.has-report { border-left:3px solid var(--theme-accent); padding-left:13px; }
.theme-category-index { grid-row:1/4; padding-top:2px; color:#9aa7b5; font:12px 'DM Mono',monospace; }
.theme-category-main { display:flex; flex-direction:column; min-width:0; }
.theme-category-main strong { color:#263b54; font-size:16px; font-weight:650; }
.theme-category-main small { display:-webkit-box; margin-top:6px; overflow:hidden; color:#63758b; font-size:14px; line-height:1.65; -webkit-box-orient:vertical; -webkit-line-clamp:2; }
.theme-category-state { display:flex; align-items:center; gap:6px; margin-top:10px; color:#7a8796; font-size:13px; }
.theme-category-state i { width:6px; height:6px; border-radius:50%; background:#b7c0ca; }
.theme-category-state.state-current { color:#38785d; }
.theme-category-state.state-current i { background:#4b9b72; }
.theme-category-state.state-stale { color:#9c690e; }
.theme-category-state.state-stale i { background:#d19b35; }
.theme-category-foot { display:flex; flex-wrap:wrap; grid-column:2; gap:5px 12px; margin-top:12px; color:#8793a2; font-size:12px; }
.theme-pending-count { color:#9b680f; }
.theme-category-arrow { position:absolute; top:17px; right:16px; color:#9aa8b8; font-size:18px; }
.theme-category-card:hover .theme-category-arrow { color:var(--theme-accent); }
.theme-signal-list { border-top:1px solid #e1e7ed; }
.theme-signal-row
{
  display:grid;
  grid-template-columns:20px 120px minmax(0,1fr) minmax(120px,180px) 18px;
  align-items:center;
  gap:13px;
  width:100%;
  min-height:77px;
  padding:11px 8px;
  border:0;
  border-bottom:1px solid #e6ebf0;
  color:inherit;
  background:transparent;
  text-align:left;
  cursor:pointer;
}
.theme-signal-row:hover { background:rgba(255,255,255,.68); }
.theme-signal-marker { position:relative; display:grid; place-items:center; height:100%; }
.theme-signal-marker::before { position:absolute; top:0; bottom:0; width:1px; background:#dce3ea; content:''; }
.theme-signal-marker i { z-index:1; width:8px; height:8px; border:2px solid #fff; border-radius:50%; background:#a8b5c3; box-shadow:0 0 0 1px #cbd5df; }
.theme-signal-marker.signal-latest i { background:var(--theme-accent); box-shadow:0 0 0 1px color-mix(in srgb, var(--theme-accent) 45%, white); }
.theme-signal-row time { color:#75859a; font-size:13px; }
.theme-signal-copy { display:flex; flex-direction:column; min-width:0; }
.theme-signal-copy strong { overflow:hidden; color:#2c4058; font-size:15px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.theme-signal-copy small { overflow:hidden; margin-top:3px; color:#74849a; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.theme-signal-category { justify-self:start; padding:4px 8px; border-radius:4px; color:#586b80; background:#edf2f6; font-size:12px; }
.theme-signal-arrow { color:#a1adba; }
.theme-signals-empty { display:flex; align-items:center; gap:14px; padding:17px 18px; border:1px dashed #cbd5df; border-radius:8px; background:rgba(255,255,255,.56); }
.theme-signals-empty > span { color:var(--theme-accent); font-size:25px; }
.theme-signals-empty p { flex:1; margin:0; color:#65778d; font-size:14px; line-height:1.7; }
.theme-signals-empty button,.theme-unclassified-notice button { padding:7px 10px; border:1px solid #d4dde6; border-radius:6px; color:#3d5875; background:#fff; cursor:pointer; font:600 13px 'Noto Sans SC',sans-serif; white-space:nowrap; }
.theme-unclassified-notice { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-top:18px; padding:11px 13px; border:1px solid #ead7ae; border-radius:7px; color:#805b19; background:#fffaf0; font-size:14px; }

@media (max-width: 980px)
{
  .theme-dashboard { padding:22px; }
  .theme-overview-grid { grid-template-columns:minmax(0,1.4fr) minmax(235px,.85fr); }
  .theme-category-grid { grid-template-columns:1fr; }
}
@media (max-width: 720px)
{
  .theme-dashboard { margin-top:8px; padding:18px 15px; }
  .theme-dashboard-head { align-items:flex-start; flex-direction:column; gap:15px; }
  .theme-head-actions { width:100%; justify-content:space-between; }
  .theme-title-line h2 { font-size:25px; }
  .theme-overview-grid { grid-template-columns:1fr; }
  .theme-verdict-panel { padding:18px 16px; }
  .theme-verdict-panel h3 { font-size:19px; }
  .theme-verdict-panel > p { font-size:15px; }
  .theme-section-heading { align-items:flex-start; }
  .theme-section-heading > span { display:none; }
  .theme-section-heading h3 { font-size:18px; }
  .theme-section-heading p { font-size:13px; }
  .theme-category-card { min-height:138px; padding-right:35px; }
  .theme-signal-row { grid-template-columns:17px minmax(0,1fr) 16px; gap:9px; padding:12px 2px; }
  .theme-signal-row time { grid-column:2; grid-row:1; font-size:12px; }
  .theme-signal-copy { grid-column:2; grid-row:2; }
  .theme-signal-copy strong { white-space:normal; }
  .theme-signal-copy small { white-space:normal; }
  .theme-signal-category { grid-column:2; grid-row:3; margin-top:5px; }
  .theme-signal-arrow { grid-column:3; grid-row:1/4; }
  .theme-signals-empty { align-items:flex-start; flex-wrap:wrap; }
  .theme-signals-empty p { flex-basis:calc(100% - 44px); }
  .theme-signals-empty button { margin-left:39px; }
}

.embodied-intro
{
  position:relative;
  display:flex;
  min-height:188px;
  align-items:center;
  justify-content:space-between;
  gap:30px;
  overflow:hidden;
  margin-top:20px;
  padding:27px 34px;
  border:1px solid #eadcc9;
  border-radius:10px;
  background:linear-gradient(105deg,#fffaf3 0%,#fffdf9 55%,#ffffff 100%);
}
.embodied-intro::after
{
  position:absolute;
  top:-115px;
  right:105px;
  width:310px;
  height:310px;
  border:1px solid rgba(180,83,9,.12);
  border-radius:50%;
  content:'';
}
.embodied-intro-copy { position:relative; z-index:1; max-width:850px; }
.embodied-kicker,.embodied-overline { color:#9b6a3e; font:600 11px 'DM Mono',monospace; letter-spacing:.13em; }
.embodied-intro h1 { margin:10px 0 8px; color:#273a4c; font:600 clamp(27px,3vw,36px)/1.3 'Noto Serif SC','Noto Sans SC',serif; letter-spacing:.015em; }
.embodied-intro-copy p { max-width:720px; margin:0; color:#5b6c7b; font-size:16px; line-height:1.8; }
.embodied-intro-mark { position:relative; z-index:1; display:grid; width:118px; height:118px; flex:0 0 auto; place-items:center; border:1px solid rgba(180,83,9,.28); border-radius:50%; color:#975317; background:rgba(255,255,255,.68); font:600 18px 'Noto Serif SC',serif; }
.embodied-intro-mark::before,.embodied-intro-mark::after { position:absolute; inset:9px; border:1px solid rgba(180,83,9,.18); border-radius:50%; content:''; }
.embodied-intro-mark::after { inset:20px; border-style:dashed; }
.embodied-intro-mark span { transform:translate(-12px,-6px); }
.embodied-intro-mark b { position:absolute; transform:translate(17px,14px); font-weight:600; }
.embodied-intro-mark i { position:absolute; top:27px; right:29px; width:7px; height:7px; border-radius:50%; background:#bf7b31; box-shadow:0 0 0 5px rgba(191,123,49,.12); }
.embodied-anchor-nav { position:sticky; top:0; z-index:3; display:flex; gap:7px; overflow-x:auto; padding:10px 0 13px; border-bottom:1px solid #e6e9ed; background:rgba(255,255,255,.94); backdrop-filter:blur(10px); }
.embodied-anchor-nav a { flex:0 0 auto; padding:7px 11px; border:1px solid transparent; border-radius:5px; color:#52657a; font-size:14px; text-decoration:none; }
.embodied-anchor-nav a:hover { border-color:#ead8c2; color:#8d4e16; background:#fff9f1; }
.embodied-brief-grid { display:grid; grid-template-columns:minmax(0,1.8fr) minmax(270px,.72fr); gap:14px; margin-top:18px; scroll-margin-top:65px; }
.embodied-judgement-card,.embodied-coverage-card { min-width:0; border:1px solid #e3e8ed; border-radius:9px; }
.embodied-judgement-card { padding:22px 25px 19px; background:#fff; }
.embodied-coverage-card { padding:20px 21px 18px; background:#f8f9fa; }
.embodied-block-heading { display:flex; align-items:center; gap:10px; }
.embodied-block-heading > div { display:flex; flex-direction:column; gap:2px; }
.embodied-heading-glyph { display:grid; width:31px; height:31px; flex:0 0 auto; place-items:center; border-radius:8px; color:#9b5d1d; background:#fff4e6; font-size:20px; }
.embodied-heading-glyph.coverage-glyph { color:#4b718d; background:#eaf2f7; }
.embodied-overline { color:#8b99a6; font-size:10px; }
.embodied-block-heading h3 { margin:0; color:#25394e; font:600 18px 'Noto Serif SC','Noto Sans SC',serif; }
.embodied-report-badge { margin-left:auto; padding:5px 9px; border-radius:99px; color:#805b36; background:#f8f1e8; font-size:13px; }
.embodied-judgement-card h4 { margin:20px 0 8px; color:#25394e; font:600 21px/1.55 'Noto Serif SC','Noto Sans SC',serif; }
.embodied-judgement-text { max-width:940px; margin:0; color:#526579; font-size:16px; line-height:1.85; }
.embodied-judgement-meta { display:flex; flex-wrap:wrap; gap:8px 20px; margin-top:14px; color:#768596; font-size:13px; }
.embodied-report-link { display:inline-flex; align-items:center; gap:8px; margin-top:16px; padding:0; border:0; color:#985817; background:transparent; cursor:pointer; font:600 14px 'Noto Sans SC',sans-serif; }
.embodied-report-link:disabled { color:#8a96a3; cursor:not-allowed; }
.embodied-report-link b { font-size:17px; font-weight:500; }
.embodied-coverage-number { display:flex; align-items:baseline; gap:9px; margin:17px 0 11px; color:#607185; font-size:14px; }
.embodied-coverage-number strong { color:#263b50; font:600 35px/1 'DM Sans','Noto Sans SC',sans-serif; letter-spacing:-.04em; }
.embodied-coverage-stat { display:flex; justify-content:space-between; gap:12px; padding:9px 0; border-top:1px solid #e4e9ee; color:#66788a; font-size:14px; }
.embodied-coverage-stat b { color:#3c5065; font-weight:600; }
.embodied-coverage-stat b.is-pending { color:#9a650f; }
.embodied-coverage-bar { height:5px; margin-top:8px; overflow:hidden; border-radius:99px; background:#e3e8ed; }
.embodied-coverage-bar i { display:block; height:100%; border-radius:inherit; background:#b46a27; transition:width .25s ease; }
.embodied-coverage-card > p { margin:10px 0 0; color:#7f8d9a; font-size:13px; line-height:1.65; }
.embodied-section { margin-top:28px; scroll-margin-top:76px; }
.embodied-section-heading { display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:13px; }
.embodied-section-heading > div { display:flex; align-items:flex-start; gap:12px; }
.embodied-section-index { display:grid; width:30px; height:30px; flex:0 0 auto; place-items:center; border:1px solid #e6d6c2; border-radius:50%; color:#975817; background:#fffaf3; font:11px 'DM Mono',monospace; }
.embodied-section-heading h3 { margin:0; color:#273c51; font:600 21px/1.35 'Noto Serif SC','Noto Sans SC',serif; }
.embodied-section-heading p { margin:4px 0 0; color:#6c7c8c; font-size:14px; line-height:1.65; }
.embodied-section-note { flex:0 0 auto; color:#7d8a98; font-size:13px; }
.embodied-tech-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.embodied-tech-card { min-width:0; padding:16px 17px 14px; border:1px solid #e2e7eb; border-radius:8px; background:#fff; }
.embodied-tech-top { display:flex; justify-content:space-between; align-items:center; color:#a0aab4; font:11px 'DM Mono',monospace; }
.embodied-track-state { padding:3px 7px; border-radius:99px; color:#8d622f; background:#fbf3e9; font:12px 'Noto Sans SC',sans-serif; }
.embodied-tech-card h4 { margin:12px 0 5px; color:#2d4155; font:600 16px 'Noto Sans SC',sans-serif; }
.embodied-tech-card p { min-height:48px; margin:0; color:#66788a; font-size:14px; line-height:1.7; }
.embodied-tech-card button { display:inline-flex; align-items:center; gap:6px; margin-top:11px; padding:0; border:0; color:#975817; background:transparent; cursor:pointer; font:600 13px 'Noto Sans SC',sans-serif; }
.embodied-tech-card button:hover { color:#713d0c; }
.embodied-data-note { margin:11px 0 0; padding:10px 13px; border-left:3px solid #c38b4c; color:#697987; background:#faf7f2; font-size:13px; line-height:1.7; }
.embodied-data-note b { margin-right:6px; color:#7e552a; }
.embodied-company-section { padding-top:2px; }
.embodied-company-layout { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(270px,.75fr); gap:12px; }
.embodied-company-groups { display:grid; gap:9px; }
.embodied-company-group { display:grid; grid-template-columns:105px minmax(0,1fr); align-items:center; gap:12px; min-height:63px; padding:12px 15px; border:1px solid #e3e8ed; border-radius:8px; background:#fff; }
.embodied-company-region { color:#66798b; font-size:14px; font-weight:600; }
.embodied-company-chips { display:flex; flex-wrap:wrap; gap:7px; }
.embodied-company-chips span { padding:5px 9px; border:1px solid #e6eaee; border-radius:5px; color:#43596c; background:#f9fafb; font-size:13px; }
.embodied-company-callout { display:flex; flex-direction:column; justify-content:center; padding:15px 18px; border:1px solid #e6e0d7; border-radius:8px; background:#fbf9f5; }
.embodied-company-callout > span { color:#8a5a22; font-size:14px; font-weight:650; }
.embodied-company-callout p { margin:7px 0; color:#4e6274; font-size:14px; line-height:1.7; }
.embodied-company-callout small { color:#83909c; font-size:13px; line-height:1.6; }
.embodied-maturity-scale { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); overflow:hidden; border:1px solid #e2e7eb; border-radius:8px; background:#fff; }
.embodied-maturity-step { position:relative; display:flex; min-height:100px; gap:12px; align-items:flex-start; padding:17px 14px; }
.embodied-maturity-step + .embodied-maturity-step { border-left:1px solid #e6eaee; }
.embodied-maturity-step > span { display:grid; width:34px; height:34px; flex:0 0 auto; place-items:center; border-radius:50%; color:#925719; background:#faf1e5; font:600 12px 'DM Mono',monospace; }
.embodied-maturity-step strong { color:#364b60; font-size:14px; }
.embodied-maturity-step p { margin:5px 0 0; color:#728191; font-size:13px; line-height:1.55; }
.embodied-maturity-foot { display:flex; align-items:center; justify-content:space-between; gap:15px; margin-top:10px; padding:11px 13px; border:1px solid #ece4d8; border-radius:7px; color:#6d7c89; background:#fffdf9; font-size:13px; line-height:1.7; }
.embodied-maturity-foot b { margin-right:5px; color:#4d5f70; }
.embodied-maturity-foot strong { flex:0 0 auto; color:#916126; font-size:13px; }
.embodied-scene-heading { display:flex; justify-content:space-between; gap:12px; margin:14px 0 8px; color:#506376; font-size:14px; }
.embodied-scene-heading span { color:#83909d; font-size:13px; }
.embodied-scene-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; }
.embodied-scene-card { min-width:0; padding:13px 15px; border:1px solid #e3e8ec; border-radius:7px; background:#fff; }
.embodied-scene-card > div { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.embodied-scene-card strong { color:#3b5064; font-size:14px; }
.embodied-scene-card > div span { color:#8a6b3f; font-size:12px; white-space:nowrap; }
.embodied-scene-card > div span.scene-has-evidence { color:#537761; }
.embodied-scene-card p { min-height:42px; margin:7px 0; color:#70808f; font-size:13px; line-height:1.6; }
.embodied-scene-card small { color:#8a6b3f; font-size:12px; }
.embodied-chain-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:9px; }
.embodied-chain-card { position:relative; display:flex; min-width:0; min-height:133px; flex-direction:column; align-items:flex-start; padding:15px 16px; border:1px solid #e1e7eb; border-radius:8px; color:inherit; background:#fff; text-align:left; cursor:pointer; }
.embodied-chain-card:hover { border-color:#d3ad7d; background:#fffdf9; }
.embodied-chain-card > span { min-height:38px; color:#54687b; font-size:14px; font-weight:600; line-height:1.45; }
.embodied-chain-card > strong { margin-top:5px; color:#31495f; font:600 24px/1 'DM Sans','Noto Sans SC',sans-serif; }
.embodied-chain-card > small { margin-top:3px; color:#82909c; font-size:12px; }
.embodied-chain-card > i { margin-top:auto; padding-top:11px; color:#82909b; font-size:12px; font-style:normal; }
.embodied-chain-card > b { position:absolute; top:15px; right:14px; color:#a8b2bc; font-size:15px; font-weight:400; }
.embodied-evidence-section { padding-top:2px; }
.embodied-evidence-list { border-top:1px solid #e1e7eb; }
.embodied-evidence-row { display:grid; grid-template-columns:32px 105px minmax(0,1fr) minmax(130px,180px) 82px 16px; align-items:center; gap:12px; width:100%; min-height:77px; padding:11px 8px; border:0; border-bottom:1px solid #e6ebef; color:inherit; background:transparent; text-align:left; cursor:pointer; }
.embodied-evidence-row:hover { background:rgba(255,255,255,.8); }
.embodied-evidence-number { color:#a1abb4; font:12px 'DM Mono',monospace; }
.embodied-evidence-row time { color:#758596; font-size:13px; }
.embodied-evidence-copy { display:flex; min-width:0; flex-direction:column; gap:4px; }
.embodied-evidence-copy strong { overflow:hidden; color:#2d4256; font-size:15px; font-weight:600; text-overflow:ellipsis; white-space:nowrap; }
.embodied-evidence-copy small { overflow:hidden; color:#748394; font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.embodied-evidence-tag { justify-self:start; max-width:100%; overflow:hidden; padding:5px 8px; border-radius:4px; color:#805b36; background:#f7f0e7; font-size:12px; text-overflow:ellipsis; white-space:nowrap; }
.embodied-evidence-sources { color:#768696; font-size:13px; white-space:nowrap; }
.embodied-evidence-row > b { color:#9aa6b1; font-weight:400; }
.embodied-reference-note { margin:0 0 9px; padding:9px 12px; border-left:3px solid #9aabb8; color:#647789; background:#f3f6f8; font-size:13px; line-height:1.65; }
.embodied-reference-note b { margin-right:6px; color:#455d71; }
.embodied-evidence-empty { display:flex; align-items:center; justify-content:space-between; gap:15px; padding:16px; border:1px dashed #cbd5df; border-radius:8px; background:#fff; }
.embodied-evidence-empty p { margin:0; color:#65778a; font-size:14px; line-height:1.7; }
.embodied-evidence-empty button { padding:8px 12px; border:1px solid #bd8b55; border-radius:6px; color:#8b541b; background:#fff; cursor:pointer; font:600 13px 'Noto Sans SC',sans-serif; white-space:nowrap; }

@media (max-width: 1100px)
{
  .embodied-chain-grid { grid-template-columns:repeat(3,minmax(0,1fr)); }
  .embodied-evidence-row { grid-template-columns:27px 90px minmax(0,1fr) 130px 16px; }
  .embodied-evidence-sources { display:none; }
}
@media (max-width: 820px)
{
  .embodied-brief-grid,.embodied-company-layout { grid-template-columns:1fr; }
  .embodied-tech-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .embodied-maturity-scale { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .embodied-maturity-step:nth-child(3) { border-left:0; border-top:1px solid #e6eaee; }
  .embodied-maturity-step:nth-child(4) { border-top:1px solid #e6eaee; }
}
@media (max-width: 620px)
{
  .embodied-intro { min-height:unset; padding:22px 18px; }
  .embodied-intro h1 { font-size:25px; }
  .embodied-intro-copy p { font-size:15px; }
  .embodied-intro-mark { width:74px; height:74px; font-size:13px; }
  .embodied-intro-mark::before { inset:6px; }
  .embodied-intro-mark::after { inset:13px; }
  .embodied-intro-mark span { transform:translate(-7px,-4px); }
  .embodied-intro-mark b { transform:translate(10px,9px); }
  .embodied-intro-mark i { top:17px; right:18px; width:5px; height:5px; }
  .embodied-anchor-nav { margin-right:-15px; margin-left:-15px; padding-right:15px; padding-left:15px; }
  .embodied-judgement-card,.embodied-coverage-card { padding:17px 15px; }
  .embodied-judgement-card h4 { font-size:18px; }
  .embodied-judgement-text { font-size:15px; }
  .embodied-section-heading { align-items:flex-start; }
  .embodied-section-heading > div { gap:8px; }
  .embodied-section-index { width:26px; height:26px; }
  .embodied-section-heading h3 { font-size:18px; }
  .embodied-section-heading p { font-size:13px; }
  .embodied-section-note { display:none; }
  .embodied-tech-grid,.embodied-chain-grid { grid-template-columns:1fr; }
  .embodied-scene-grid { grid-template-columns:1fr; }
  .embodied-scene-card p { min-height:unset; }
  .embodied-scene-heading { align-items:flex-start; flex-direction:column; gap:2px; }
  .embodied-tech-card p { min-height:unset; }
  .embodied-company-group { grid-template-columns:1fr; gap:8px; }
  .embodied-maturity-scale { grid-template-columns:1fr; }
  .embodied-maturity-step + .embodied-maturity-step { border-top:1px solid #e6eaee; border-left:0; }
  .embodied-maturity-step { min-height:unset; padding:13px; }
  .embodied-maturity-foot { align-items:flex-start; flex-direction:column; gap:5px; }
  .embodied-chain-card { min-height:unset; display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:4px 10px; }
  .embodied-chain-card > span { grid-column:1; min-height:unset; }
  .embodied-chain-card > strong { grid-column:2; grid-row:1 / 3; margin:0; }
  .embodied-chain-card > small { grid-column:1; }
  .embodied-chain-card > i { grid-column:1; margin-top:4px; padding-top:0; }
  .embodied-evidence-row { grid-template-columns:25px minmax(0,1fr) 16px; gap:7px 9px; padding:12px 2px; }
  .embodied-evidence-number { grid-row:1 / 4; }
  .embodied-evidence-row time { grid-column:2; grid-row:1; font-size:12px; }
  .embodied-evidence-copy { grid-column:2; grid-row:2; }
  .embodied-evidence-copy strong,.embodied-evidence-copy small { white-space:normal; }
  .embodied-evidence-tag { grid-column:2; grid-row:3; }
  .embodied-evidence-row > b { grid-column:3; grid-row:1 / 4; }
  .embodied-evidence-empty { align-items:flex-start; flex-direction:column; }
}
</style>
