import { taxonomy } from './radarTaxonomy.js'

// 仅提取明确标注的 Markdown 小节，不做语义猜测。
export function labeledSection(markdown, label) {
  const sections = String(markdown || '').split(/^#{1,6}\s+/m).slice(1)
  const section = sections.find(s => s.split('\n')[0].trim() === label)
  return section ? section.slice(section.indexOf('\n') + 1).trim() : ''
}
export function normalizeObservation(item) {
  const dateValue = value => {
    const match = String(value || '').match(/^(\d{4})-(\d{2})(?:-(\d{2}))?/)
    if (!match || +match[2] < 1 || +match[2] > 12) return ''
    if (match[3] && (+match[3] < 1 || +match[3] > new Date(+match[1], +match[2], 0).getDate())) return ''
    return match[0]
  }
  const published = dateValue(item.published_at)
  const sources = Array.isArray(item.sources) ? item.sources : []
  const marked = label => labeledSection(item.content_markdown, label)
  const stageRaw = marked('进展阶段'), opennessRaw = marked('开放程度'), evidenceRaw = marked('证据属性')
  const valueRaw = marked('商业价值判断'), priorityRaw = marked('优先级')
  const metadata = item.research_metadata || {}
  const dimension = (key, raw) => taxonomy[key].labels.includes(metadata[key]) ? metadata[key] : taxonomy[key].mapping?.[raw] || (taxonomy[key].labels.includes(raw) ? raw : '未标注')
  return {
    ...item, sources,
    stageRaw, opennessRaw, evidenceRaw, valueRaw,
    stage: dimension('stage', stageRaw),
    openness: dimension('openness', opennessRaw),
    evidenceType: dimension('evidenceType', evidenceRaw),
    tier: taxonomy.tier.labels.includes(metadata.tier) ? metadata.tier : valueRaw.match(/^(极高|很高|中高|高)(?=潜力|长期价值|[：:、，。\s]|$)/)?.[1] || '未标注',
    priority: /^[ABC]$/.test(metadata.priority || '') ? metadata.priority : /^[ABC]$/.test(priorityRaw) ? priorityRaw : '未标注',
    date: published || dateValue(item.captured_at),
    dateLabel: published ? '发布日期' : '采集日期',
    organizations: [...new Set(sources.map(s => s.organization?.trim()).filter(Boolean))],
    category: item.category_id || '',
  }
}

export function filterObservations(items, { months = '', categories = [], organization = '', query = '', month = '', stage = '', tier = '', priority = '', openness = '', evidenceType = '' }, now = new Date()) {
  const current = now.getFullYear() * 12 + now.getMonth()
  const q = query.trim().toLowerCase()
  return items.filter(item => {
    const age = item.date ? current - (+item.date.slice(0, 4) * 12 + +item.date.slice(5, 7) - 1) : null
    return (!stage || item.stage === stage) && (!tier || item.tier === tier) &&
      (!priority || item.priority === priority) && (!openness || item.openness === openness) &&
      (!evidenceType || item.evidenceType === evidenceType) && (!months || (age !== null && age >= 0 && age < +months)) &&
      (!categories.length || categories.includes(item.category)) &&
      (!organization || (organization === '__unknown' ? !item.organizations.length : item.organizations.includes(organization))) &&
      (!month || item.date.startsWith(month)) &&
      (!q || [item.title, item.summary, item.content_markdown, ...item.organizations].join(' ').toLowerCase().includes(q))
  })
}

// 获取到最后一页，不把工作台的“最近 8 条”或接口单页上限当作全量。
export async function loadRadarObservations(api, signal, topicId = 'embodied-intelligence') {
  const items = new Map()
  let topics = []
  for (let offset = 0; ; offset += 100) {
    const { data } = await api.get('/market-research/workbench', {
      params: { topic_id: topicId, limit: 100, offset }, signal,
    })
    topics = data.topics || []
    const page = data.items || []
    for (const item of page) items.set(item.id, normalizeObservation(item))
    if (page.length < 100) break
  }
  return { items: [...items.values()], topics }
}
