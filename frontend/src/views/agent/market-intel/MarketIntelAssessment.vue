<template>
  <section class="industry-assessment" aria-label="行业研判">
    <template v-if="report">
      <header class="assessment-lead">
        <div class="lead-caption"><span>当前行业判断</span><span class="draft-label">AI 辅助研判 · 草稿</span></div>
        <h2>{{ report.title }}</h2>
        <p class="lead-conclusion">{{ report.conclusion }}</p>
        <div class="assessment-meta"><span>第 {{ report.version }} 版</span><span>资料截止 {{ date(report.data_cutoff) }}</span><span>更新于 {{ date(report.created_at) }}</span><span>置信度：{{ confidence(report.confidence) }}</span><span>{{ overview.reported_category_count }} 个细分领域提供研判</span></div>
        <div class="assessment-actions"><button type="button" @click="openReport()">阅读完整报告 ↗</button><button type="button" class="primary" @click="chatOpen = true">更新研判 / 继续追问</button></div>
      </header>
      <div v-if="freshness === 'stale'" class="assessment-stale" role="status">研究依据或细分研判已有变化，本版判断尚未全部吸收。请先更新有变化的细分研判，再更新综合判断。</div>
      <p class="scope-note">以下结论基于已保存的细分研判综合形成，按资料截止时间阅读；统计页的筛选不会重写本版结论。</p>
      <div class="assessment-lenses"><article v-for="section in lenses" :key="section.title"><h3>{{ section.title }}</h3><div class="assessment-prose" v-html="renderMd(section.content)"></div></article></div>
      <section v-for="section in actionSections" :key="section.title" class="assessment-section"><h3>{{ section.title }}</h3><div class="assessment-prose" v-html="renderMd(section.content)"></div></section>
      <details class="category-judgements" open><summary>细分方向：{{ categoriesWithReports.length }} 项持续跟踪</summary><div class="category-assessment-grid"><button v-for="category in categoriesWithReports" :key="category.id" type="button" @click="openReport(category.id)"><span>{{ category.name }} <small>{{ !category.evidence_count ? '无当前有效依据' : category.freshness === 'stale' ? '待更新' : `置信度${confidence(category.report.confidence)}` }}</small></span><p>{{ category.evidence_count ? category.report.conclusion : '原引用已移出本领域或被删除，旧结论不再作为当前综合研判的依据；补充资料后可重新研判。' }}</p><b>查看判断与证据 ↗</b></button></div></details>
      <details class="assessment-section"><summary>本版直接关联的研究依据（{{ cited.length }} 条）</summary><div class="assessment-evidence"><button v-for="item in cited" :key="item.id" type="button" @click="openObservation(item)"><span>{{ (item.published_at || item.captured_at || '').slice(0,10) }}</span>{{ item.title }} ↗</button></div></details>
    </template>
    <div v-else class="assessment-missing"><h2>行业研判尚未形成</h2><p>先对已有资料形成细分研判，再综合技术、市场与产业变化，保存可持续更新的判断。</p><button type="button" @click="openReport()">进入研判工作台</button></div>
    <MarketIntelTopicChatDialog v-if="chatOpen" :topic="overview.topic" :current-judgement="report" :category-judgements="overview.categories || []" :observation-count="records.length" :initial-prompt="updatePrompt" @close="closeChat" />
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { renderMd } from '../../../composables/useChatStream.js'
import MarketIntelTopicChatDialog from './MarketIntelTopicChatDialog.vue'
import { assessmentSections, assessmentState } from './marketIntelAssessment.js'
const props = defineProps({ overview: { type: Object, default: () => ({}) }, records: { type: Array, default: () => [] } })
const emit = defineEmits(['refresh'])
const router = useRouter(), chatOpen = ref(false)
const report = computed(() => props.overview.topic_report?.report)
const sections = computed(() => assessmentSections(report.value?.content_markdown))
const lenses = computed(() => sections.value.filter(s => /技术进展|市场与应用|产业发展/.test(s.title)))
const actionSections = computed(() => sections.value.filter(s => /机会与行动|未来跟踪|风险与边界/.test(s.title)))
const categoriesWithReports = computed(() => (props.overview.categories || []).filter(c => c.report))
const cited = computed(() => props.records.filter(r => report.value?.evidence_ids?.includes(r.id)))
const freshness = computed(() => assessmentState(props.overview, props.records))
const date = value => value ? new Date(value).toLocaleDateString('zh-CN') : '未记录'
const confidence = value => ({ high: '较高', medium: '中等', low: '有限' })[value] || '未标注'
const updatePrompt = '请基于本主题已保存的最新细分研判，更新一份面向行业持续跟踪的综合研判，调用 save_market_judgement 保存新版本。不要绕过分类直接总结资讯清单。正文使用二级标题：技术进展、市场与应用、产业发展、机会与行动、未来跟踪、风险与边界。前三节分别回答关键变化、影响和当前判断；未来跟踪列出未来30/90/180天需观察的信号与判断升级/下调的触发条件。区分已发生事实、分析推断和企业计划，关联实际引用观察及来源，指出资料缺口。若细分研判待更新，先说明哪些细分需要吸收新证据，不声称已吸收全部新记录。'
function openReport(categoryId) { router.push({ name: 'market-intel-judgement', params: { topicId: 'embodied-intelligence', ...(categoryId ? { categoryId } : {}) } }) }
function openObservation(item) { router.push({ name: 'market-intel-observation', params: { id: item.id }, query: { topic: 'embodied-intelligence' } }) }
function closeChat() { chatOpen.value = false; emit('refresh') }
</script>

<style scoped>
.industry-assessment { color:#233141; }
.assessment-lead { padding:25px 26px; background:#f2f7fd; border:1px solid #cfdeee; border-left:4px solid #2a78d6; border-radius:8px; }
.lead-caption { display:flex; gap:12px; align-items:center; font-size:12px; color:#4776a8; }
.draft-label { padding:2px 7px; background:white; border:1px solid #d3dfed; border-radius:4px; font-size:11px; }
h2 { margin:13px 0; font-size:23px; line-height:1.5; font-weight:650; letter-spacing:-.3px; }
.lead-conclusion { font-size:16px; line-height:1.95; margin:0; max-width:1000px; }
.assessment-meta { display:flex; flex-wrap:wrap; gap:7px 18px; font-size:12px; color:#6d7f92; margin-top:18px; }
.assessment-actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:20px; }
button { cursor:pointer; font:inherit; }
.assessment-actions button,.assessment-missing button { border:1px solid #bed0e3; background:white; color:#2767aa; padding:8px 13px; border-radius:5px; font-size:13px; }
.assessment-actions .primary { background:#2a78d6; color:white; border-color:#2a78d6; }
.scope-note { color:#7a8796; font-size:12px; line-height:1.8; margin:14px 0; }
.assessment-lenses { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:16px; }
.assessment-lenses article,.assessment-section { border:1px solid #e1e6ec; border-radius:8px; background:#fcfcfb; padding:22px; margin-bottom:16px; min-width:0; }
h3 { margin:0 0 14px; font-size:18px; color:#244568; }
.assessment-prose { font-size:14px; line-height:1.95; color:#45596e; overflow-wrap:anywhere; }
.assessment-prose :deep(p) { margin:0 0 13px; }
.assessment-prose :deep(p:last-child) { margin-bottom:0; }
.assessment-prose :deep(strong) { color:#213b55; font-weight:650; }
.assessment-prose :deep(a) { color:#2674c6; text-decoration:underline; text-underline-offset:3px; }
.assessment-prose :deep(ul),.assessment-prose :deep(ol) { padding-left:20px; margin:10px 0; }
.assessment-prose :deep(li) { margin-bottom:10px; }
.assessment-prose :deep(table) { width:100%; border-collapse:collapse; font-size:12px; }
.assessment-prose :deep(td),.assessment-prose :deep(th) { text-align:left; padding:10px; border:1px solid #dfe6ee; }
.category-judgements { margin:0 0 18px; }
summary { cursor:pointer; font-weight:600; color:#365773; font-size:14px; }
.category-assessment-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:14px; }
.category-assessment-grid button { border:1px solid #e0e6ec; background:#fff; padding:17px; border-radius:6px; text-align:left; color:#31485e; }
.category-assessment-grid button:hover { border-color:#76a6d5; }
.category-assessment-grid button>span { display:flex; justify-content:space-between; gap:10px; font-size:14px; font-weight:600; }
.category-assessment-grid small { font-size:11px; font-weight:400; color:#8190a0; white-space:nowrap; }
.category-assessment-grid p { font-size:13px; line-height:1.85; color:#65788b; display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; margin:11px 0; }
.category-assessment-grid b { color:#3275b6; font-size:12px; font-weight:500; }
.assessment-stale { border:1px solid #ebd393; background:#fff9e9; padding:12px 16px; color:#8a6516; font-size:13px; margin-top:15px; border-radius:6px; }
.assessment-evidence { display:flex; flex-direction:column; margin-top:12px; }
.assessment-evidence button { border:0; border-bottom:1px solid #e5ebf0; padding:10px 0; background:none; text-align:left; color:#396c9b; font-size:13px; }
.assessment-evidence span { color:#8a98a6; margin-right:12px; font-size:12px; }
.assessment-missing { padding:30px; border:1px dashed #ccd8e5; border-radius:8px; color:#65788b; }
button:focus-visible,summary:focus-visible { outline:2px solid #2a78d6; outline-offset:3px; }
@media(max-width:1100px) { .assessment-lenses { grid-template-columns:1fr; } }
@media(max-width:640px) { .assessment-lead { padding:19px 16px; } h2 { font-size:20px; } .lead-conclusion { font-size:14px; } .assessment-lenses article,.assessment-section { padding:17px; } .category-assessment-grid { grid-template-columns:1fr; } }
</style>
