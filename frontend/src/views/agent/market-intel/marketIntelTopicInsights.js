import { normalizeObservation } from './marketIntelRadar.js'

export function sourceIdentity(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol)) return ''
    url.hash = ''
    for (const key of [...url.searchParams.keys()]) if (/^utm_|^(fbclid|gclid|mc_cid|mc_eid)$/i.test(key)) url.searchParams.delete(key)
    url.searchParams.sort()
    url.pathname = url.pathname.replace(/\/+$/, '') || '/'
    return url.toString()
  } catch { return '' }
}

export function buildTopicInsights(observations, categories, report, months = 3, now = new Date()) {
  const records = observations.map(normalizeObservation)
  const currentMonth = now.getFullYear() * 12 + now.getMonth()
  const today = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`
  const age = record => record.date ? currentMonth - (+record.date.slice(0,4) * 12 + +record.date.slice(5,7) - 1) : null
  const inWindow = (record, offset = 0) => {
    const distance = age(record)
    return distance !== null && distance >= offset && distance < offset + months && (record.date.length < 10 || record.date <= today)
  }
  const filtered = months ? records.filter(r => inWindow(r)) : records
  const previous = months ? records.filter(r => inWindow(r, months)) : []
  const urlsFor = rows => new Set(rows.flatMap(r => r.sources.map(s => sourceIdentity(s.url)).filter(Boolean)))
  const definitions = [...categories, ...(!categories.some(c => c.id === '') ? [{id:'', name:'待分类'}] : [])]
  const rows = definitions.map(category => {
    const items = filtered.filter(r => r.category === category.id)
    const prior = previous.filter(r => r.category === category.id)
    const stages = Object.fromEntries(['研究论文','厂商自报实验','开放可复现','工具/平台可用','产品/API阶段','未标注'].map(stage => [stage, items.filter(r => r.stage === stage).length]))
    return { ...category, items, count:items.length, previous:prior.length, delta:items.length-prior.length,
      distinctSources:urlsFor(items).size, stages,
      highValue:items.filter(r=>['极高','很高'].includes(r.tier)).length,
      priority:items.filter(r=>r.priority==='A').length,
      latest:items.map(r=>r.date).sort().at(-1)||'',
    }
  })
  const sourceMap = new Map(), orgMap = new Map()
  filtered.forEach(record => {
    const unique = new Set()
    record.sources.forEach(source => {
      const key = sourceIdentity(source.url)
      if (!key || unique.has(key)) return
      unique.add(key)
      if (!sourceMap.has(key)) sourceMap.set(key, { url:key, title:source.title || source.organization || key, items:[] })
      sourceMap.get(key).items.push(record)
    })
    record.organizations.forEach(name => {
      if (!orgMap.has(name)) orgMap.set(name, {name,items:[]})
      orgMap.get(name).items.push(record)
    })
  })
  const sources = [...sourceMap.values()].sort((a,b)=>b.items.length-a.items.length || a.url.localeCompare(b.url))
  const organizations = [...orgMap.values()].sort((a,b)=>b.items.length-a.items.length || a.name.localeCompare(b.name,'zh'))
  const cited = new Set(report?.evidence_ids || [])
  const afterCutoff = filtered.filter(record => report && ((record.captured_at || '') > (report.data_cutoff || report.created_at) || (record.updated_at || '') > report.created_at))
  const gaps = rows.filter(row=>row.id).flatMap(row => {
    const reasons=[]
    if (!row.count) reasons.push(months ? '当前窗口没有观察记录' : '尚无观察记录')
    else if (row.distinctSources < 3) reasons.push(`仅 ${row.distinctSources} 篇不同原文，需补充交叉来源`)
    if (row.count && (!row.report || row.freshness==='stale')) reasons.push(row.report ? '现有研判待吸收变化' : '已有资料，尚未形成细分研判')
    if (row.count && row.report?.confidence==='low') reasons.push('已保存研判的置信度有限')
    return reasons.length ? [{...row,reasons}] : []
  }).sort((a,b)=>(b.freshness==='stale')-(a.freshness==='stale') || b.count-a.count)
  return { records, filtered, previous, rows, sources, organizations, gaps, afterCutoff,
    uniqueSources:sourceMap.size,
    repeatedSourceRecords:sources.filter(s=>s.items.length>1),
    sourceMissing:filtered.filter(r=>!r.sources.some(s=>sourceIdentity(s.url))),
    unmarked:filtered.filter(r=>r.stage==='未标注'),
    highValue:filtered.filter(r=>['极高','很高'].includes(r.tier)),
    product:filtered.filter(r=>r.stage==='产品/API阶段'),
    early:filtered.filter(r=>['研究论文','厂商自报实验'].includes(r.stage)),
    activeCategories:rows.filter(r=>r.count).length,
    cited:filtered.filter(r=>cited.has(r.id)),
    dateMissing:records.filter(r=>!r.date),
    sampleWarnings:filtered.filter(r=>r.research_metadata?.record_kind==='illustration' || /【图片展示样例】/.test(r.title)),
  }
}
