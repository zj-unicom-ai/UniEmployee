<template>
  <div class="judgement-dashboard" :class="`accent-${themeAccent}`">
    <section class="dashboard-overview">
      <div class="overview-main">
        <div class="overview-copy">
          <span class="eyebrow">当前核心判断</span>
          <h2>{{ leadFinding?.title || report.title || '行业趋势研判' }}</h2>
          <p>{{ leadFinding?.summary || shortConclusion }}</p>
          <div class="lead-meta">
            <span class="confidence-mark" :class="`confidence-${report.confidence || 'medium'}`">
              研判置信度 · {{ confidenceLabel(report.confidence) }}
            </span>
            <span>资料截止 {{ formatDate(report.data_cutoff) }}</span>
            <span>第 {{ report.version }} 版</span>
          </div>
        </div>
        <div class="coverage-card" aria-label="本版观察引用覆盖率">
          <div class="coverage-head"><strong>{{ coveragePercent }}%</strong><span>观察引用覆盖</span></div>
          <div class="coverage-track" role="img" :aria-label="`本版引用 ${citedEvidence} 条，共 ${totalEvidence} 条观察`">
            <span :style="{ width: `${coveragePercent}%` }"></span>
          </div>
          <p><b>{{ citedEvidence }}</b> 条本版引用 <i>/</i> {{ totalEvidence }} 条累计观察</p>
        </div>
      </div>
      <div class="overview-stats">
        <div><strong>{{ totalEvidence }}</strong><span>领域观察</span></div>
        <div><strong>{{ citedEvidence }}</strong><span>本版引用</span></div>
        <div><strong>{{ report.sources?.length || 0 }}</strong><span>可追溯来源</span></div>
        <div><strong :class="{ pending: newEvidence }">{{ newEvidence }}</strong><span>待吸收新依据</span></div>
        <div v-if="isTopic"><strong>{{ reportedCategoryCount }}<small> / {{ categoryCount }}</small></strong><span>细分领域已研判</span></div>
      </div>
    </section>

    <section v-if="isTopic && dimensionAnalyses.length" class="dimension-section" aria-labelledby="dimensions-title">
      <header class="dimension-head">
        <div><span class="eyebrow">CROSS-CUTTING ANALYSIS</span><h2 id="dimensions-title">交叉分析维度</h2></div>
        <p>九个问题拆开看：证据量只描述资料覆盖，不表示技术水平。类别会交叉复用，同一观察可能出现在多个维度。</p>
      </header>
      <div class="dimension-grid">
        <article v-for="dimension in dimensionAnalyses" :key="dimension.id" class="dimension-card">
          <header class="dimension-title-row">
            <div><span class="dimension-index">{{ dimension.index }}</span><h3>{{ dimension.title }}</h3></div>
            <span class="dimension-lens">分析视角</span>
          </header>
          <p class="dimension-question">{{ dimension.question }}</p>
          <div class="dimension-metrics" :aria-label="`${dimension.observationCount} 条观察，${dimension.originalCount} 篇不同原文，${dimension.organizationCount} 个来源机构`">
            <span><strong>{{ dimension.observationCount }}</strong> 条观察</span>
            <span><strong>{{ dimension.originalCount }}</strong> 篇不同原文</span>
            <span><strong>{{ dimension.organizationCount }}</strong> 个来源机构</span>
            <span><strong>{{ dimension.citedCount }}</strong> 条被本版主题直接引用</span>
          </div>
          <div v-if="dimension.categoryReports.length" class="dimension-judgements">
            <div v-for="category in dimension.categoryReports" :key="category.id" class="dimension-judgement">
              <button type="button" class="dimension-category-link" @click="$emit('openCategory', category.id)">
                {{ category.name }}<span aria-hidden="true">↗</span>
              </button>
              <span class="dimension-confidence" :class="`confidence-${category.confidence || 'medium'}`">
                {{ category.report ? `置信度${confidenceLabel(category.confidence)}` : '尚未形成研判' }}
              </span>
              <p>{{ category.summary || category.description }}</p>
            </div>
          </div>
          <p v-else class="dimension-empty">相关细分领域尚无保存研判。</p>
          <div v-if="dimension.latestObservations.length" class="dimension-evidence">
            <span class="dimension-evidence-label">近期相关观察</span>
            <button v-for="item in dimension.latestObservations" :key="item.id" type="button" @click="$emit('openObservation', item)">
              <time>{{ formatDate(item.published_at || item.captured_at) }}</time><strong>{{ item.title }}</strong><span aria-hidden="true">↗</span>
            </button>
          </div>
          <p v-else class="dimension-empty">该维度当前没有可关联的观察记录。</p>
        </article>
      </div>
    </section>

    <slot name="topic-insights"></slot>

    <section v-if="isTopic && categories.length && !evidence.length" class="dashboard-section evidence-distribution" aria-labelledby="distribution-title">
      <header class="dashboard-section-head">
        <div><span class="eyebrow">研究证据地图</span><h2 id="distribution-title">细分领域积累分布</h2></div>
        <p>{{ categoryEvidenceTotal }} 条观察 · 条数代表资料积累，不代表市场规模</p>
      </header>
      <div class="category-chart">
        <button
          v-for="item in categories"
          :key="item.id"
          type="button"
          class="category-chart-row"
          :class="categoryChartState(item)"
          :aria-label="`${item.name}，${categoryEvidenceCount(item)} 条观察，${categoryStatus(item)}，打开细分领域研判`"
          @click="$emit('openCategory', item.id)"
        >
          <span class="category-chart-name">{{ item.name }}<small>{{ categoryStatus(item) }}</small></span>
          <span class="category-chart-track" role="img" :aria-label="`${categoryEvidenceCount(item)} 条观察`"><i :style="{ width: categoryBarWidth(item) }"></i></span>
          <strong>{{ categoryEvidenceCount(item) }}</strong>
        </button>
      </div>
      <div class="chart-legend"><span><i class="legend-current"></i>已有研判</span><span><i class="legend-stale"></i>研判需更新</span><span><i class="legend-pending"></i>有资料，待研判</span><span><i class="legend-empty"></i>暂无资料</span></div>
    </section>

    <section v-else-if="!isTopic && evidence.length" class="evidence-visual-grid" aria-label="研究依据分布图">
      <article class="dashboard-section visual-panel" aria-labelledby="timeline-title">
        <header class="dashboard-section-head">
          <div><span class="eyebrow">资料时间分布</span><h2 id="timeline-title">近 6 个月观察记录</h2></div>
          <span class="visual-total">{{ recentEvidenceTotal }} 条</span>
        </header>
        <div class="timeline-chart" role="img" :aria-label="`最近六个月观察记录数量：${timelineBuckets.map(item => `${item.label}${item.count}条`).join('，')}`">
          <div v-for="item in timelineBuckets" :key="item.key" class="timeline-column">
            <strong>{{ item.count || '' }}</strong>
            <div class="timeline-bar-area"><i :style="{ height: timelineBarHeight(item) }"></i></div>
            <span>{{ item.label }}</span>
          </div>
        </div>
        <p class="visual-caption">优先按文章发布时间归月；发布时间缺失时按入库时间。统计基于当前加载的 {{ evidence.length }} 条记录。</p>
      </article>

      <article class="dashboard-section visual-panel" aria-labelledby="sources-title">
        <header class="dashboard-section-head">
          <div><span class="eyebrow">来源结构</span><h2 id="sources-title">研究记录来自哪里</h2></div>
          <span class="visual-total">{{ sourceCounts.length }} 类</span>
        </header>
        <div v-if="sourceCounts.length" class="source-chart">
          <div v-for="source in sourceCounts" :key="source.name" class="source-chart-row">
            <span :title="source.name">{{ source.name }}</span>
            <i class="source-bar-track"><b :style="{ width: sourceBarWidth(source) }"></b></i>
            <strong>{{ source.count }}</strong>
          </div>
        </div>
        <p v-else class="visual-caption">当前加载的记录尚未标注来源机构。</p>
        <p class="visual-caption">按来源机构归并记录数；同一机构的多篇资料合并显示。</p>
      </article>
    </section>

    <section v-if="findings.length" class="dashboard-section" aria-labelledby="findings-title">
      <header class="dashboard-section-head">
        <div><span class="eyebrow">趋势判断</span><h2 id="findings-title">关键变化</h2></div>
        <p>每项判断都可回到本领域的观察记录核对</p>
      </header>
      <div class="finding-grid">
        <article v-for="finding in findings" :key="finding.id" class="finding-card">
          <div class="finding-topline"><span class="finding-index">{{ finding.id }}</span><span>{{ finding.confidence || '综合判断' }}</span></div>
          <h3>{{ finding.title }}</h3>
          <p>{{ finding.summary }}</p>
          <div v-if="finding.evidence.length" class="finding-evidence">
            <span class="evidence-label">关联观察</span>
            <button v-for="item in finding.evidence" :key="item.id" type="button" @click="$emit('openObservation', item)">
              <time>{{ formatDate(item.published_at || item.captured_at) }}</time><strong>{{ item.title }}</strong><span aria-hidden="true">↗</span>
            </button>
          </div>
          <div v-else class="finding-footnote">依据详见下方完整研判正文</div>
        </article>
      </div>
    </section>

    <section v-if="drivers.length" class="driver-strip" aria-labelledby="drivers-title">
      <div class="driver-heading"><span class="eyebrow">变化从何而来</span><h2 id="drivers-title">趋势驱动</h2></div>
      <div class="driver-list">
        <div v-for="(driver, index) in drivers.slice(0, 5)" :key="`${index}-${driver.title}`" class="driver-item">
          <span class="driver-node"></span><strong>{{ driver.title }}</strong><p>{{ driver.detail }}</p>
        </div>
      </div>
    </section>

    <section v-if="watchItems.length" class="dashboard-section watch-section" aria-labelledby="watch-title">
      <header class="dashboard-section-head">
        <div><span class="eyebrow">未来观察清单</span><h2 id="watch-title">哪些信号会改变判断</h2></div>
        <p>出现上调或下调信号时，再调整趋势判断</p>
      </header>
      <div class="watch-grid" aria-label="后续跟踪指标与判断条件">
        <article v-for="item in watchItems" :key="item.name" class="watch-card">
          <header class="watch-metric"><span class="watch-glyph" aria-hidden="true">⌁</span><div><strong>{{ item.name }}</strong><small>{{ item.measure }}</small></div></header>
          <div class="watch-directions" :class="{ 'single-trigger': !item.up && !item.down }">
            <template v-if="item.up || item.down">
              <div v-if="item.up" class="watch-trigger up-trigger"><span><b aria-hidden="true">↗</b> 判断上调</span><p>{{ item.up }}</p></div>
              <div v-if="item.down" class="watch-trigger down-trigger"><span><b aria-hidden="true">↘</b> 判断下调</span><p>{{ item.down }}</p></div>
            </template>
            <div v-else class="watch-trigger signal-trigger"><span><b aria-hidden="true">◎</b> 触发信号</span><p>{{ item.trigger || item.measure }}</p></div>
          </div>
        </article>
      </div>
    </section>

    <section v-if="opportunities.length || risks.length" class="signal-columns">
      <article v-if="opportunities.length" class="signal-panel opportunity-panel">
        <header><span class="signal-mark">机会</span><h2>可关注的产业机会</h2></header>
        <ul><li v-for="item in opportunities.slice(0, 4)" :key="item.title"><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></li></ul>
      </article>
      <article v-if="risks.length" class="signal-panel risk-panel">
        <header><span class="signal-mark">风险</span><h2>仍需验证的约束</h2></header>
        <ul><li v-for="item in risks.slice(0, 4)" :key="item.title"><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></li></ul>
      </article>
    </section>

    <section v-if="gaps.length" class="dashboard-section gap-section" aria-labelledby="gaps-title">
      <header class="dashboard-section-head">
        <div><span class="eyebrow">证据边界</span><h2 id="gaps-title">当前还缺什么证据</h2></div>
        <p>这些缺口限制了结论的外推范围</p>
      </header>
      <div class="gap-grid">
        <article v-for="gap in gaps.slice(0, 4)" :key="gap.name" class="gap-card">
          <strong>{{ gap.name }}</strong><p>{{ gap.impact }}</p><small>{{ gap.evidence }}</small>
        </article>
      </div>
    </section>

    <section class="detail-disclosures" aria-label="详细研究资料">
      <details class="detail-disclosure">
        <summary><span>查看完整研究正文</span><small>研究口径、分析过程、详细证据与结论</small></summary>
        <div class="full-report md" v-html="renderMd(report.content_markdown || report.conclusion)"></div>
      </details>
      <details class="detail-disclosure source-disclosure">
        <summary><span>展开全部来源</span><small>{{ report.sources?.length || 0 }} 个来源链接</small></summary>
        <div v-if="report.sources?.length" class="source-list">
          <a v-for="(source, index) in report.sources" :key="`${source.url}-${index}`" class="source-row" :href="source.url || undefined" target="_blank" rel="noopener noreferrer">
            <span class="source-index">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="source-copy"><strong>{{ source.title || source.organization || '来源资料' }}</strong><small>{{ source.organization }}<template v-if="source.published_at"> · {{ source.published_at }}</template></small></span>
            <span v-if="source.url" class="source-open" aria-hidden="true">↗</span>
          </a>
        </div>
        <p v-else class="empty-copy">当前版本没有保存外部来源。</p>
      </details>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { assessmentSections } from './marketIntelAssessment.js'
import { sourceIdentity } from './marketIntelTopicInsights.js'
import { renderMd } from '../../../composables/useChatStream.js'

const props = defineProps({
  report: { type: Object, required: true },
  evidence: { type: Array, default: () => [] },
  totalEvidence: { type: Number, default: 0 },
  citedEvidence: { type: Number, default: 0 },
  newEvidence: { type: Number, default: 0 },
  isTopic: { type: Boolean, default: false },
  categories: { type: Array, default: () => [] },
  themeAccent: { type: String, default: 'blue' },
  reportedCategoryCount: { type: Number, default: 0 },
  categoryCount: { type: Number, default: 0 },
})
defineEmits(['openObservation', 'openCategory'])

const markdown = computed(() => String(props.report.content_markdown || ''))
const executiveSection = computed(() => sectionByHeading(markdown.value, /结论摘要|关键判断|核心判断|核心研判/))
const findings = computed(() => {
  const lines = executiveSection.value.split(/\r?\n/)
  const starts = []
  lines.forEach((line, index) => { if (/^(?:\*\*J\d+|#{3,4}\s+J\d+)\b/.test(line.trim())) starts.push(index) })
  if (!starts.length) {
    return assessmentSections(markdown.value).filter(s => /技术进展|市场与应用|产业(?:发展|与生态)/.test(s.title)).map((s,index) => {
      const categories = props.categories.filter(c => s.content.includes(c.id)).map(c=>c.id)
      return { id:`J${index+1}`, title:s.title, confidence:confidenceLabel(props.report.confidence),
        summary:plainText(s.content.split('\n\n').filter(p=>!p.startsWith('依据')).slice(0,2).join(' ')).slice(0,650),
        evidence:props.evidence.filter(e=>categories.includes(e.category_id)).slice(0,3) }
    })
  }
  return starts.map((start, index) => {
    const end = starts[index + 1] ?? lines.length
    const title = lines[start].trim().replace(/^#{3,4}\s+/, '').replace(/^\*\*|\*\*$/g, '')
    const bodyLines = lines.slice(start + 1, end).filter(line => {
      const value = line.trim()
      return value && !/^#{1,6}\s+/.test(value) && !/^\|/.test(value) && !/^---+$/.test(value)
    }).slice(0, 6)
    const id = title.match(/^(J\d+)/)?.[1] || `J${index + 1}`
    const detail = claimDetail(markdown.value, id)
    const evidenceIds = [...new Set(detail.match(/mro_[a-f0-9]{32}/g) || [])]
    const evidenceMap = new Map(props.evidence.map(item => [item.id, item]))
    return {
      id,
      title: plainText(title.replace(/【[^】]*】/g, '').replace(/（置信度[：:].*?）/, '')).replace(/^J\d+\s*[｜|]\s*/, ''),
      confidence: title.match(/置信度[：:]?\s*([^】）)]+)/)?.[1] || '',
      summary: plainText(bodyLines.map(line => line.trim().replace(/^[-*]\s+/, '')).join(' ')).replace(/\s*依据详见下方完整研判正文/g, '').slice(0, 420),
      evidence: evidenceIds.map(itemId => evidenceMap.get(itemId)).filter(Boolean).slice(0, 3),
    }
  }).slice(0, 6)
})
const leadFinding = computed(() => findings.value[0])
const shortConclusion = computed(() => plainText(props.report.conclusion || '').slice(0, 220))
const coveragePercent = computed(() => props.totalEvidence
  ? Math.min(100, Math.round((props.citedEvidence / props.totalEvidence) * 100)) : 0)
const drivers = computed(() => {
  const section = sectionByHeading(markdown.value, /趋势驱动|驱动因素|主要驱动/)
  return [...parseList(section, 'numbered'), ...parseList(section, 'bullets')]
})
const opportunities = computed(() => {
  const section = sectionByHeading(markdown.value, /机会/)
  return [...parseList(section, 'numbered'), ...parseList(section, 'bullets')]
})
const risks = computed(() => parseList(sectionByHeading(markdown.value, /风险|约束|风险与边界/), 'bullets'))
const watchItems = computed(() => {
  const section = sectionByHeading(markdown.value, /后续跟踪指标|跟踪信号|未来跟踪/)
  const table = markdownTableData(section, /跟踪|指标|观察项/)
  if (table.rows.length) {
    const nameIndex = Math.max(0, table.headers.findIndex(value => /跟踪项|跟踪指标|指标(?:\/事件)?|观察项|监测项/.test(value)))
    const measureIndex = table.headers.findIndex((value, index) => index !== nameIndex && /口径|要求|观察对象|测量|当前状态|基准/.test(value))
    const upIndex = table.headers.findIndex(value => /上调|升级|判断升级/.test(value))
    const downIndex = table.headers.findIndex(value => /下调|降级|证伪/.test(value))
    const triggerIndex = table.headers.findIndex(value => /触发|证伪条件|判断.*信号/.test(value))
    return table.rows.map(cells => ({
      name: cells[nameIndex] || cells[0],
      measure: measureIndex >= 0 ? cells[measureIndex] : '',
      up: upIndex >= 0 ? stripSignalLabel(cells[upIndex], '上调') : '',
      down: downIndex >= 0 ? stripSignalLabel(cells[downIndex], '下调') : '',
      trigger: triggerIndex >= 0 ? cells[triggerIndex] : cells.filter((_, index) => index !== nameIndex).find(Boolean) || '',
    })).filter(item => item.name && (item.up || item.down || item.trigger || item.measure))
  }
  return [...parseList(section, 'numbered'), ...parseList(section, 'bullets')]
    .map(item => ({ name: item.title, measure: '', up: '', down: '', trigger: item.detail || item.title }))
    .filter(item => item.name)
})
const gaps = computed(() => {
  const rows = markdownTable(sectionByHeading(markdown.value, /不确定性与证据缺口|证据缺口/), /缺口/)
  return rows.map(cells => ({ name: cells[0], impact: cells[1], evidence: cells[2] })).filter(item => item.name)
})
const categoryEvidenceTotal = computed(() => props.categories.reduce((sum, item) => sum + categoryEvidenceCount(item), 0))
const categoryEvidenceMax = computed(() => Math.max(1, ...props.categories.map(categoryEvidenceCount)))
const timelineBuckets = computed(() => {
  const now = new Date()
  const buckets = Array.from({ length: 6 }, (_, index) => {
    const date = new Date(now.getFullYear(), now.getMonth() - (5 - index), 1)
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    return { key, label: `${date.getMonth() + 1}月`, count: 0 }
  })
  const bucketMap = new Map(buckets.map(item => [item.key, item]))
  for (const record of props.evidence) {
    const date = new Date(record.published_at || record.captured_at || '')
    if (Number.isNaN(date.getTime())) continue
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}`
    const bucket = bucketMap.get(key)
    if (bucket) bucket.count += 1
  }
  return buckets
})
const recentEvidenceTotal = computed(() => timelineBuckets.value.reduce((sum, item) => sum + item.count, 0))
const timelineMax = computed(() => Math.max(1, ...timelineBuckets.value.map(item => item.count)))
const sourceCounts = computed(() => {
  const counts = new Map()
  for (const record of props.evidence) {
    const source = record.source_name || record.sources?.find(item => item.organization)?.organization || '未标注来源'
    counts.set(source, (counts.get(source) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name, 'zh-CN'))
    .slice(0, 6)
})
const sourceMax = computed(() => Math.max(1, ...sourceCounts.value.map(item => item.count)))
const reportedCategoryCount = computed(() => Number(props.reportedCategoryCount || 0))
const categoryCount = computed(() => Number(props.categoryCount || 0))
const dimensionDefinitions = [
  { id: 'capability', title: '模型能力与任务泛化', categoryIds: ['foundation-models', 'multimodal-ai'], question: '能力改进是否跨任务、跨数据和跨模型成立，还是集中在单一基准与特定配置？' },
  { id: 'multimodal', title: '多模态感知与交互', categoryIds: ['multimodal-ai'], question: '实时语音、视频和动作链路能否稳定处理打断、长时序、噪声与跨模态冲突？' },
  { id: 'efficiency', title: '推理效率、成本与能耗', categoryIds: ['compute-infrastructure', 'foundation-models'], question: '吞吐、延迟、显存、能耗和单位成功任务成本是否在相同工作负载下比较？' },
  { id: 'context', title: '上下文、记忆与检索', categoryIds: ['foundation-models', 'ai-agents'], question: '长上下文或外部记忆能否保留证据召回、顺序鲁棒性、权限边界与更新正确性？' },
  { id: 'agents', title: '智能体执行与工具可靠性', categoryIds: ['ai-agents', 'ai-applications'], question: '多步任务的完成率、失败恢复、人工介入和工具调用边界是否被完整披露？' },
  { id: 'evaluation', title: '数据、训练与评测复现', categoryIds: ['foundation-models', 'multimodal-ai', 'ai-ecosystem'], question: '训练数据、评测协议、代码/权重和独立复测是否足以判断结果可复现？' },
  { id: 'deployment', title: '行业落地与客户转化', categoryIds: ['ai-applications', 'ai-agents', 'compute-infrastructure'], question: '论文、演示、试点、认证、付费部署与持续使用是否被明确区分？' },
  { id: 'safety', title: '安全、治理与行动边界', categoryIds: ['ai-agents', 'ai-ecosystem', 'ai-applications'], question: '权限、数据隔离、记忆污染、审计、回滚和第三方安全验证覆盖到哪一步？' },
  { id: 'ecosystem', title: '开放生态与供应链', categoryIds: ['ai-ecosystem', 'foundation-models', 'compute-infrastructure'], question: '开放资源、许可、平台依赖和算力可获得性如何影响复现与实际选择？' },
]
const dimensionAnalyses = computed(() => {
  const citedIds = new Set(props.report.evidence_ids || [])
  return dimensionDefinitions.map((definition, index) => {
    const categoryReports = props.categories
      .filter(category => definition.categoryIds.includes(category.id))
      .map(category => {
        const conclusion = plainText(category.report?.conclusion || '')
        return {
          ...category,
          confidence: category.report?.confidence || '',
          summary: conclusion.length > 260 ? `${conclusion.slice(0, 260)}…` : conclusion,
        }
      })
    const categoryIds = new Set(definition.categoryIds)
    const records = props.evidence.filter(item => categoryIds.has(item.category_id || item.category || ''))
    const originals = new Set()
    const organizations = new Set()
    for (const record of records) {
      for (const source of record.sources || []) {
        const identity = sourceIdentity(source.url)
        if (identity) originals.add(identity)
        if (source.organization?.trim()) organizations.add(source.organization.trim())
      }
      if (!record.sources?.length && record.source_name?.trim()) organizations.add(record.source_name.trim())
    }
    const latestObservations = [...records]
      .sort((left, right) => String(right.published_at || right.captured_at || '').localeCompare(String(left.published_at || left.captured_at || '')))
      .slice(0, 2)
    return {
      ...definition,
      index: String(index + 1).padStart(2, '0'),
      observationCount: records.length,
      originalCount: originals.size,
      organizationCount: organizations.size,
      citedCount: records.filter(record => citedIds.has(record.id)).length,
      categoryReports,
      latestObservations,
    }
  })
})

function categoryEvidenceCount(item) { return Number(item?.evidence_count ?? item?.observation_count ?? 0) }
function categoryBarWidth(item) { return `${Math.max(categoryEvidenceCount(item) ? 4 : 0, (categoryEvidenceCount(item) / categoryEvidenceMax.value) * 100)}%` }
function categoryStatus(item) {
  if (item.freshness === 'stale') return '有新依据待吸收'
  if (item.report) return '已有研判'
  return categoryEvidenceCount(item) ? '有资料，待研判' : '暂无资料'
}
function categoryChartState(item) {
  if (item.freshness === 'stale') return 'chart-stale'
  if (item.report) return 'chart-current'
  return categoryEvidenceCount(item) ? 'chart-pending' : 'chart-empty'
}
function timelineBarHeight(item) { return `${item.count ? Math.max(7, (item.count / timelineMax.value) * 100) : 0}%` }
function sourceBarWidth(item) { return `${Math.max(4, (item.count / sourceMax.value) * 100)}%` }

function sectionByHeading(markdownValue, pattern) {
  const lines = String(markdownValue || '').split(/\r?\n/)
  const start = lines.findIndex(line => /^##\s+/.test(line) && pattern.test(line))
  if (start < 0) return ''
  const end = lines.findIndex((line, index) => index > start && /^##\s+/.test(line))
  return lines.slice(start + 1, end < 0 ? lines.length : end).join('\n')
}

function subsectionByHeading(section, pattern) {
  const lines = String(section || '').split(/\r?\n/)
  const start = lines.findIndex(line => /^###\s+/.test(line) && pattern.test(line))
  if (start < 0) return ''
  const end = lines.findIndex((line, index) => index > start && /^#{2,3}\s+/.test(line))
  return lines.slice(start + 1, end < 0 ? lines.length : end).join('\n')
}

function claimDetail(markdownValue, claimId) {
  const lines = String(markdownValue || '').split(/\r?\n/)
  const start = lines.findIndex(line => new RegExp(`^###\\s+${claimId}\\b`).test(line))
  if (start < 0) return ''
  const end = lines.findIndex((line, index) => index > start && /^#{2,3}\s+/.test(line))
  return lines.slice(start + 1, end < 0 ? lines.length : end).join('\n')
}

function markdownTable(section, headingPattern) {
  return markdownTableData(section, headingPattern).rows
}

function markdownTableData(section, headingPattern) {
  const lines = String(section || '').split(/\r?\n/)
  const start = lines.findIndex(line => /^\s*\|/.test(line) && headingPattern.test(line))
  if (start < 0) return { headers: [], rows: [] }
  const parseCells = line => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(plainText)
  const headers = parseCells(lines[start])
  const rows = []
  for (let index = start + 2; index < lines.length && /^\s*\|/.test(lines[index]); index++) {
    const cells = parseCells(lines[index])
    if (cells.length > 1) rows.push(cells)
  }
  return { headers, rows }
}

function parseList(section, kind) {
  const matcher = kind === 'numbered' ? /^\s*\d+\.\s+(.+)$/ : /^\s*-\s+(.+)$/
  return String(section || '').split(/\r?\n/).flatMap(line => {
    const match = line.match(matcher)
    if (!match) return []
    const raw = match[1].replace(/\s+---\s+依据详见下方完整研判正文\s*$/, '')
    const parts = raw.match(/^\*\*(.+?)\*\*[：:]\s*(.*)$/)
    const labeled = raw.match(/^(.{2,48}?)[：:]\s*(.+)$/)
    return [{
      title: plainText(parts?.[1] || labeled?.[1] || raw),
      detail: plainText(parts?.[2] ?? labeled?.[2] ?? raw),
    }]
  })
}

function stripSignalLabel(value, label) {
  return plainText(value).replace(new RegExp(`^${label}\\s*`), '')
}

function plainText(value) {
  return String(value || '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*|__|`|~~/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function confidenceLabel(value) {
  return ({ high: '较高', medium: '中等', low: '有限' })[value] || '中等'
}

function formatDate(value) {
  if (!value) return '时间未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
}
</script>

<style scoped>
.judgement-dashboard { --chart-accent:#4b79a8; display:grid; gap:18px; margin-top:20px; color:#26384e; }
.judgement-dashboard.accent-copper { --chart-accent:#ad7652; }
.judgement-dashboard.accent-green { --chart-accent:#4d8b68; }
.dashboard-overview,.dashboard-section,.driver-strip,.signal-panel,.detail-disclosure { min-width:0; border:1px solid #dfe6ee; border-radius:10px; background:#fff; box-shadow:0 3px 14px rgba(31,54,79,.035); }
.dashboard-overview { overflow:hidden; }
.overview-main { display:grid; grid-template-columns:minmax(0,1fr) 270px; gap:34px; align-items:center; padding:27px 30px 23px; background:linear-gradient(112deg,#fff 0%,#fff 72%,#f6f8fb 100%); }
.eyebrow { color:#74849a; font-size:13px; font-weight:650; }
.overview-copy h2 { max-width:900px; margin:8px 0 10px; color:#18314d; font:650 clamp(23px,2.5vw,31px)/1.45 'Noto Serif SC','Noto Sans SC',serif; }
.overview-copy > p { display:-webkit-box; max-width:920px; margin:0; overflow:hidden; color:#51657d; font-size:16px; line-height:1.8; -webkit-box-orient:vertical; -webkit-line-clamp:4; }
.lead-meta { display:flex; flex-wrap:wrap; align-items:center; gap:8px 16px; margin-top:17px; color:#7a899b; font-size:13px; }
.confidence-mark { padding:4px 9px; border-radius:5px; color:#345a86; background:#edf3f9; font-weight:650; }
.confidence-high { color:#276a4c; background:#e9f5ed; }.confidence-low { color:#99600c; background:#fff4de; }
.coverage-card { padding:18px; border-left:1px solid #e4e9ef; }
.coverage-head { display:flex; align-items:baseline; justify-content:space-between; gap:10px; }
.coverage-head strong { color:#2f5f94; font:650 32px/1 'DM Sans','Noto Sans SC',sans-serif; }
.coverage-head span { color:#62748b; font-size:13px; }
.coverage-track { height:8px; margin:15px 0 9px; overflow:hidden; border-radius:99px; background:#e9edf2; }
.coverage-track span { display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,#4b79a8,#bf815c); transition:width .25s ease; }
.coverage-card p { margin:0; color:#718096; font-size:13px; }.coverage-card p b { color:#324c6a; font-weight:700; }.coverage-card p i { padding:0 4px; color:#acb6c2; font-style:normal; }
.overview-stats { display:flex; flex-wrap:wrap; border-top:1px solid #e8edf2; background:#fbfcfd; }
.overview-stats > div { display:flex; min-width:135px; flex:1; flex-direction:column; gap:1px; padding:14px 20px 15px; border-right:1px solid #e8edf2; }
.overview-stats > div:last-child { border-right:0; }
.overview-stats strong { color:#294766; font-size:21px; font-weight:700; line-height:1.35; }.overview-stats strong small { color:#9aa8b8; font-size:14px; font-weight:500; }.overview-stats span { color:#77879a; font-size:14px; }.overview-stats .pending { color:#a76b1a; }
.dashboard-section { padding:22px 24px 24px; }
.dashboard-section-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:16px; }
.dashboard-section-head h2,.driver-heading h2 { margin:3px 0 0; color:#213a56; font:650 21px/1.4 'Noto Serif SC','Noto Sans SC',serif; }
.dashboard-section-head > p { margin:0; color:#8290a1; font-size:14px; }
.dimension-section { padding:24px; border:1px solid #d9e3ec; border-top:3px solid var(--chart-accent); border-radius:9px; background:#f8fafc; }
.dimension-head { display:flex; justify-content:space-between; align-items:flex-end; gap:20px; margin-bottom:16px; }
.dimension-head h2 { margin:3px 0 0; color:#213a56; font:650 22px/1.4 'Noto Serif SC','Noto Sans SC',serif; }
.dimension-head > p { max-width:650px; margin:0; color:#7d8c9c; font-size:13px; line-height:1.7; }
.dimension-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:13px; }
.dimension-card { min-width:0; padding:17px 18px 16px; border:1px solid #e0e7ee; border-radius:7px; background:#fff; }
.dimension-title-row { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.dimension-title-row > div { display:flex; min-width:0; align-items:center; gap:10px; }
.dimension-index { display:grid; width:27px; height:27px; flex:0 0 auto; place-items:center; border-radius:50%; color:#315f89; background:#eaf1f7; font:700 11px 'DM Sans','Noto Sans SC',sans-serif; }
.dimension-title-row h3 { margin:0; color:#2e455e; font-size:16px; font-weight:700; line-height:1.5; }
.dimension-lens { flex:0 0 auto; color:#8c99a7; font-size:11px; }
.dimension-question { min-height:42px; margin:9px 0 12px; color:#718094; font-size:13px; line-height:1.65; }
.dimension-metrics { display:flex; flex-wrap:wrap; gap:6px 13px; padding:10px 0; border-top:1px solid #edf1f4; border-bottom:1px solid #edf1f4; color:#8190a0; font-size:11px; }
.dimension-metrics span { white-space:nowrap; }
.dimension-metrics strong { color:#395977; font:700 13px 'DM Sans','Noto Sans SC',sans-serif; }
.dimension-judgements { display:grid; gap:10px; padding-top:12px; }
.dimension-judgement { min-width:0; }
.dimension-category-link { display:inline-flex; align-items:center; gap:6px; padding:0; border:0; color:#376d9d; background:transparent; font:650 12px 'Noto Sans SC',sans-serif; cursor:pointer; }
.dimension-category-link:hover { color:#174c7d; text-decoration:underline; text-underline-offset:3px; }
.dimension-confidence { margin-left:8px; color:#587b66; font-size:11px; }
.dimension-confidence.confidence-low { color:#a36c19; }
.dimension-judgement p { margin:4px 0 0; color:#52687d; font-size:13px; line-height:1.75; }
.dimension-empty { margin:12px 0 0; color:#8a98a6; font-size:12px; }
.dimension-evidence { display:grid; gap:2px; padding-top:11px; margin-top:12px; border-top:1px solid #edf1f4; }
.dimension-evidence-label { margin-bottom:2px; color:#8996a4; font-size:11px; }
.dimension-evidence button { display:grid; min-width:0; grid-template-columns:76px minmax(0,1fr) 12px; gap:8px; align-items:start; padding:4px 0; border:0; color:#546a7f; background:transparent; text-align:left; cursor:pointer; }
.dimension-evidence button:hover strong { color:#27669b; text-decoration:underline; text-underline-offset:2px; }
.dimension-evidence time { padding-top:1px; color:#8a98a6; font-size:11px; white-space:nowrap; }
.dimension-evidence strong { overflow-wrap:anywhere; font-size:12px; font-weight:600; line-height:1.5; }
.dimension-evidence button > span { color:#6486ab; font-size:12px; }
.dimension-category-link:focus-visible,.dimension-evidence button:focus-visible { outline:3px solid #9fc1e5; outline-offset:3px; border-radius:3px; }
.evidence-distribution { background:linear-gradient(145deg,#fff 0%,#fff 65%,#f8fafc 100%); }
.category-chart { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:13px 28px; }
.category-chart-row { display:grid; min-width:0; grid-template-columns:minmax(130px,1fr) minmax(80px,1.55fr) 35px; align-items:center; gap:11px; padding:3px 0; border:0; color:inherit; background:transparent; text-align:left; cursor:pointer; }
.category-chart-row:hover .category-chart-name { color:#245b8f; }
.category-chart-row:focus-visible { outline:3px solid #9fc1e5; outline-offset:4px; border-radius:4px; }
.category-chart-name { display:flex; min-width:0; flex-direction:column; gap:2px; color:#40566e; font-size:13px; font-weight:650; line-height:1.45; }
.category-chart-name small { color:#9aa6b3; font-size:11px; font-weight:500; }
.category-chart-track { height:10px; overflow:hidden; border-radius:99px; background:#edf1f5; }
.category-chart-track i { display:block; height:100%; border-radius:inherit; background:var(--chart-accent); transition:width .28s ease; }
.category-chart-row.chart-pending .category-chart-track i { background:#c49a5e; }
.category-chart-row.chart-stale .category-chart-track i { background:#d69b32; }
.category-chart-row.chart-empty .category-chart-track i { background:#cbd4de; }
.category-chart-row > strong { color:#40566e; font:700 14px 'DM Sans','Noto Sans SC',sans-serif; text-align:right; }
.chart-legend { display:flex; flex-wrap:wrap; gap:8px 18px; padding-top:16px; margin-top:18px; border-top:1px solid #edf0f3; color:#8290a1; font-size:12px; }
.chart-legend span { display:inline-flex; align-items:center; gap:7px; }
.chart-legend i { width:8px; height:8px; border-radius:50%; background:var(--chart-accent); }
.chart-legend .legend-stale { background:#d69b32; }.chart-legend .legend-pending { background:#c49a5e; }.chart-legend .legend-empty { background:#cbd4de; }
.evidence-visual-grid { display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr); gap:14px; }
.visual-panel { min-width:0; padding-bottom:18px; }
.visual-total { padding:4px 9px; border-radius:99px; color:#516e8c; background:#eef3f8; font-size:12px; white-space:nowrap; }
.timeline-chart { display:grid; min-height:180px; grid-template-columns:repeat(6,minmax(0,1fr)); align-items:end; gap:14px; padding:8px 4px 0; border-bottom:1px solid #dfe6ed; background:repeating-linear-gradient(to top,transparent 0,transparent 43px,#edf1f5 44px,#edf1f5 45px); }
.timeline-column { display:flex; height:165px; min-width:0; flex-direction:column; align-items:center; justify-content:flex-end; gap:6px; color:#8391a1; font-size:12px; }
.timeline-column > strong { min-height:16px; color:#55728f; font:650 12px 'DM Sans','Noto Sans SC',sans-serif; }
.timeline-bar-area { display:flex; width:min(100%,42px); height:118px; align-items:flex-end; justify-content:center; }
.timeline-bar-area i { display:block; width:100%; min-height:0; border-radius:5px 5px 0 0; background:linear-gradient(180deg,color-mix(in srgb,var(--chart-accent) 78%,white),var(--chart-accent)); }
.timeline-column > span { min-height:18px; white-space:nowrap; }
.visual-caption { margin:12px 0 0; color:#8b98a7; font-size:12px; line-height:1.6; }
.source-chart { display:grid; gap:12px; padding:9px 0 0; }
.source-chart-row { display:grid; grid-template-columns:minmax(90px,1fr) minmax(70px,1.5fr) 24px; align-items:center; gap:10px; color:#596d83; font-size:13px; }
.source-chart-row > span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.source-bar-track { display:block; height:9px; overflow:hidden; border-radius:99px; background:#edf1f5; }
.source-bar-track b { display:block; height:100%; border-radius:inherit; background:var(--chart-accent); }
.source-chart-row > strong { color:#536a83; font:650 13px 'DM Sans','Noto Sans SC',sans-serif; text-align:right; }
.finding-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.finding-card { display:flex; min-width:0; flex-direction:column; padding:17px 17px 15px; border:1px solid #e3e9ef; border-top:3px solid #6686a7; border-radius:7px; background:#fff; }
.finding-card:nth-child(3n+2) { border-top-color:#b37753; }.finding-card:nth-child(3n) { border-top-color:#708f79; }
.finding-topline { display:flex; justify-content:space-between; gap:10px; color:#8593a4; font-size:13px; }
.finding-index { color:#3d6289; font-weight:750; letter-spacing:.04em; }
.finding-card h3 { margin:9px 0 8px; color:#2c415a; font-size:17px; font-weight:700; line-height:1.55; }
.finding-card > p { display:-webkit-box; flex:1; margin:0; overflow:hidden; color:#5c6e82; font-size:15px; line-height:1.75; -webkit-box-orient:vertical; -webkit-line-clamp:5; }
.finding-evidence { display:grid; gap:5px; padding-top:13px; margin-top:13px; border-top:1px solid #edf0f4; }
.evidence-label { margin-bottom:2px; color:#8b98a7; font-size:12px; }
.finding-evidence button { display:grid; grid-template-columns:80px minmax(0,1fr) 14px; gap:8px; align-items:start; padding:5px 0; border:0; color:#4b6178; background:transparent; text-align:left; cursor:pointer; }
.finding-evidence time { padding-top:1px; color:#8997a7; font-size:12px; white-space:nowrap; }
.finding-evidence strong { font-size:13px; font-weight:600; line-height:1.55; }.finding-evidence button > span { color:#6486ab; }
.finding-evidence button:hover strong { color:#2e659b; text-decoration:underline; text-underline-offset:2px; }
.finding-footnote { padding-top:12px; margin-top:12px; border-top:1px solid #edf0f4; color:#8794a3; font-size:13px; }
.driver-strip { display:grid; grid-template-columns:200px minmax(0,1fr); gap:20px; align-items:start; padding:21px 24px; background:#f9fafb; }
.driver-heading { padding-top:2px; }
.driver-list { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:0; }
.driver-item { position:relative; min-width:0; padding:0 14px; border-left:1px solid #dfe5eb; }
.driver-node { display:block; width:9px; height:9px; margin:3px 0 9px; border-radius:50%; background:#b77c58; box-shadow:0 0 0 3px #f1e6df; }
.driver-item strong { display:block; color:#415870; font-size:14px; line-height:1.55; }
.driver-item p { margin:5px 0 0; color:#748296; font-size:13px; line-height:1.65; }
.watch-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:11px; }
.watch-card { min-width:0; padding:15px; border:1px solid #e4e9ef; border-radius:7px; background:#fcfdfe; }
.watch-metric { display:flex; align-items:center; gap:10px; padding-bottom:11px; border-bottom:1px solid #edf0f3; }
.watch-glyph { display:grid; width:30px; height:30px; flex:0 0 auto; place-items:center; border-radius:8px; color:var(--chart-accent); background:#edf3f8; font-size:21px; }
.watch-metric strong { display:block; color:#344b64; font-size:15px; }.watch-metric small { display:block; margin-top:2px; color:#8491a1; font-size:12px; line-height:1.5; }
.watch-directions { display:grid; grid-template-columns:1fr 1fr; gap:9px; padding-top:11px; }
.watch-directions.single-trigger { grid-template-columns:1fr; }
.watch-trigger { min-width:0; padding:10px; border-radius:6px; background:#f5f8f6; }
.watch-trigger > span { display:flex; align-items:center; gap:5px; margin-bottom:6px; color:#397150; font-size:12px; font-weight:700; }
.watch-trigger > span b { font-size:15px; }
.down-trigger { background:#faf5f1; }.down-trigger > span { color:#9a6240; }
.signal-trigger { background:#f2f6fa; }.signal-trigger > span { color:var(--chart-accent); }
.watch-trigger p { margin:0; color:#596c80; font-size:13px; line-height:1.65; }
.signal-columns { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.signal-panel { padding:20px 22px; }.signal-panel header { display:flex; align-items:center; gap:10px; margin-bottom:13px; }
.signal-panel h2 { margin:0; color:#29425d; font:650 19px 'Noto Serif SC','Noto Sans SC',serif; }
.signal-mark { padding:4px 7px; border-radius:4px; color:#397150; background:#eaf4ed; font-size:12px; font-weight:700; }.risk-panel .signal-mark { color:#9a6240; background:#f8eee8; }
.signal-panel ul { display:grid; gap:0; padding:0; margin:0; list-style:none; }
.signal-panel li { padding:11px 0; border-top:1px solid #edf0f3; }.signal-panel li strong { color:#465b71; font-size:15px; }.signal-panel li p { margin:3px 0 0; color:#6c7c8e; font-size:14px; line-height:1.7; }
.gap-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }
.gap-card { padding:14px; border-left:3px solid #c28c57; background:#faf8f4; }.gap-card strong { color:#5e503e; font-size:15px; }.gap-card p { margin:7px 0; color:#746a5c; font-size:13px; line-height:1.6; }.gap-card small { color:#9a8b78; font-size:12px; line-height:1.55; }
.detail-disclosures { display:grid; gap:10px; }
.detail-disclosure { overflow:hidden; }
.detail-disclosure summary { position:relative; display:flex; align-items:center; justify-content:space-between; gap:15px; padding:15px 18px; color:#344b64; cursor:pointer; list-style:none; }
.detail-disclosure summary::-webkit-details-marker { display:none; }
.detail-disclosure summary::after { content:'＋'; margin-left:auto; color:#6482a0; font-size:17px; }
.detail-disclosure[open] summary::after { content:'−'; }
.detail-disclosure summary span { font-size:15px; font-weight:700; }.detail-disclosure summary small { color:#8592a1; font-size:13px; }
.full-report { padding:18px clamp(18px,3vw,32px) 28px; border-top:1px solid #edf0f3; color:#43586f; font-size:15px; line-height:1.85; }
.full-report :deep(h1),.full-report :deep(h2),.full-report :deep(h3) { margin:24px 0 10px; color:#203a56; font-size:19px; line-height:1.5; }.full-report :deep(h2:first-child) { margin-top:0; }.full-report :deep(p) { margin:0 0 13px; }.full-report :deep(ul),.full-report :deep(ol) { padding-left:24px; }.full-report :deep(li) { margin:5px 0; }.full-report :deep(table) { display:block; width:100%; overflow-x:auto; border-collapse:collapse; }.full-report :deep(th),.full-report :deep(td) { padding:9px 11px; border:1px solid #e3e8ed; text-align:left; vertical-align:top; }.full-report :deep(th) { color:#3d5874; background:#f4f6f8; }
.source-list { padding:0 18px 10px; border-top:1px solid #edf0f3; }.source-row { display:flex; align-items:center; gap:12px; padding:11px 2px; border-bottom:1px solid #edf0f3; color:inherit; text-decoration:none; }.source-row:hover .source-copy strong { color:#28659a; }
.source-index { color:#9aa6b3; font-size:12px; }.source-copy { display:flex; min-width:0; flex:1; flex-direction:column; gap:2px; }.source-copy strong { overflow:hidden; color:#40576f; font-size:13px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }.source-copy small { color:#8996a5; font-size:12px; }.source-open { color:#4c7fae; }.empty-copy { margin:15px 18px; color:#8996a5; font-size:13px; }
.finding-evidence button:focus-visible,.detail-disclosure summary:focus-visible { outline:3px solid #94b9dc; outline-offset:2px; }
@media(max-width:1100px) { .finding-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.driver-strip { grid-template-columns:1fr; }.driver-list { grid-template-columns:repeat(3,minmax(0,1fr)); row-gap:14px; }.driver-item:nth-child(4) { border-left:0; }.evidence-visual-grid { grid-template-columns:1fr 1fr; } }
@media(max-width:760px) { .overview-main { grid-template-columns:1fr; gap:18px; padding:22px; }.coverage-card { padding:15px 0 0; border-left:0; border-top:1px solid #e4e9ef; }.overview-stats > div { min-width:110px; padding:12px 15px; }.dashboard-section { padding:19px; }.dashboard-section-head { align-items:flex-start; flex-direction:column; gap:5px; }.signal-columns { grid-template-columns:1fr; }.gap-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }.evidence-visual-grid { grid-template-columns:1fr; }.dimension-head { align-items:flex-start; flex-direction:column; gap:7px; }.dimension-grid { grid-template-columns:1fr; } }
@media(max-width:520px) { .judgement-dashboard { gap:12px; margin-top:13px; }.overview-main { padding:18px; }.overview-copy h2 { font-size:22px; }.overview-copy > p { font-size:15px; }.overview-stats > div { min-width:50%; flex:0 0 50%; border-bottom:1px solid #e8edf2; }.overview-stats > div:nth-child(2n) { border-right:0; }.finding-grid,.driver-list,.gap-grid,.category-chart,.watch-grid { grid-template-columns:1fr; }.category-chart-row { grid-template-columns:minmax(120px,1fr) minmax(70px,1.4fr) 28px; gap:8px; }.category-chart-name { font-size:12px; }.driver-item,.driver-item:nth-child(4) { padding:0 0 12px 16px; border-left:1px solid #dfe5eb; }.driver-item:last-child { padding-bottom:0; }.driver-node { position:absolute; top:1px; left:-5px; }.driver-heading h2 { margin-bottom:12px; }.watch-directions { grid-template-columns:1fr; }.timeline-chart { gap:7px; }.detail-disclosure summary { flex-wrap:wrap; padding:14px; }.detail-disclosure summary small { width:100%; order:3; }.detail-disclosure summary::after { position:absolute; right:30px; }.source-list { padding:0 14px 8px; }.source-copy strong { white-space:normal; }.dimension-section { padding:16px; }.dimension-card { padding:14px; }.dimension-title-row h3 { font-size:15px; }.dimension-metrics { gap:6px 10px; }.dimension-evidence button { grid-template-columns:67px minmax(0,1fr) 12px; gap:6px; } }
@media(prefers-reduced-motion:reduce) { .coverage-track span { transition:none; } }
</style>
