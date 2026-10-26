import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizeObservation, filterObservations, loadRadarObservations } from '../frontend/src/views/agent/market-intel/marketIntelRadar.js'

test('reads every API page without bundled records, including an empty platform', async () => {
  const offsets = []
  const rows = Array.from({ length: 205 }, (_, i) => ({ id: `platform-${i}`, title: `进展${i}`, sources: [], captured_at: '2026-10-23' }))
  const api = { get: async (url, { params }) => {
    assert.equal(url, '/market-research/workbench')
    assert.equal(params.topic_id, 'embodied-intelligence')
    offsets.push(params.offset)
    return { data: { topics: [], items: rows.slice(params.offset, params.offset + params.limit) } }
  } }
  const result = await loadRadarObservations(api)
  assert.deepEqual(offsets, [0, 100, 200])
  assert.equal(result.items.length, 205)
  assert.deepEqual(result.items.map(i => i.id), rows.map(i => i.id))
  assert.deepEqual((await loadRadarObservations({ get: async () => ({ data: { items: [] } }) })).items, [])
})

test('uses stored fields and marks absent dimensions instead of guessing from prose', () => {
  const item = normalizeObservation({ title: 'NVIDIA 产品发布 极高价值', category_id: '', published_at: '2026-02-30', captured_at: '2026-10-23T08:00:00Z', sources: [] })
  assert.equal(item.date, '2026-10-23')
  assert.equal(item.dateLabel, '采集日期')
  assert.equal(item.category, '')
  assert.deepEqual(item.organizations, [])
  assert.equal(item.stage, '未标注')
  assert.equal(item.tier, '未标注')
  const published = normalizeObservation({ published_at: '2026-07', sources: [{ organization: '研究院' }, { organization: '研究院' }] })
  assert.equal(published.date, '2026-07')
  assert.deepEqual(published.organizations, ['研究院'])
})

test('all views can share category, month, organization and text filters', () => {
  const rows = [
    { id: 'a', title: '模型进展', category_id: 'vla', published_at: '2026-10-22', sources: [{ organization: '研究院' }] },
    { id: 'b', title: '其他进展', category_id: 'vla', published_at: '2026-07', sources: [] },
    { id: 'c', title: '其他领域', category_id: 'data', published_at: '2026-10', sources: [] },
  ].map(normalizeObservation)
  const now = new Date(2026, 9, 23)
  const result = filterObservations(rows, { months: '3', categories: ['vla'], organization: '研究院', query: '模型', month: '2026-10' }, now)
  assert.deepEqual(result.map(i => i.id), ['a'])
  assert.deepEqual(filterObservations(rows, { organization: '__unknown' }, now).map(i => i.id), ['b', 'c'])
  assert.equal(filterObservations(rows, { query: '不存在' }, now).length, 0)
})


test('reads explicit database markdown labels using the reference grouping rules', () => {
  const item = normalizeObservation({ content_markdown: '### 优先级\n\nA\n\n### 进展阶段\n\nAPI预览\n\n### 商业价值判断\n\n很高：工业场景。\n\n### 开放程度\n\nAPI可用\n\n### 证据属性\n\n官方实验/自报', sources: [] })
  assert.equal(item.stage, '产品/API阶段')
  assert.equal(item.tier, '很高')
  assert.equal(item.priority, 'A')
  assert.equal(item.openness, 'API/合作预览')
  assert.equal(item.evidenceType, '官方实验/自报')
  assert.equal(filterObservations([item], { stage: '研究论文' }).length, 0)
  assert.equal(filterObservations([item], { stage: '产品/API阶段', priority: 'A' }).length, 1)
})

import { assessmentSections, assessmentState } from '../frontend/src/views/agent/market-intel/marketIntelAssessment.js'

test('assessment cards are extracted from the stored report with its evidence links', () => {
  const sections = assessmentSections('# 报告\n介绍\n\n## 技术进展\n\n技术变化与[依据](/app/market-intel/observations/db-id)\n\n## 市场与应用\n\n市场判断\n\n## 未来跟踪\n\n- 判断升级信号')
  assert.deepEqual(sections.map(s => s.title), ['技术进展', '市场与应用', '未来跟踪'])
  assert.match(sections[0].content, /db-id/)
  assert.deepEqual(assessmentSections(''), [])
})

test('assessment freshness accounts for unsynthesized evidence and deleted references', () => {
  assert.equal(assessmentState({}, []), 'missing')
  const overview = { topic_report: { report: { evidence_ids: ['a'] }, freshness: 'current' }, categories: [] }
  assert.equal(assessmentState(overview, [{ id: 'a' }]), 'current')
  assert.equal(assessmentState(overview, []), 'stale')
  assert.equal(assessmentState({ ...overview, categories: [{ freshness: 'stale' }] }, [{ id: 'a' }]), 'stale')
})

test('new structured database dimensions take precedence over legacy markdown labels', () => {
  const normalized = normalizeObservation({ content_markdown: '### 进展阶段\n\nAPI预览', research_metadata: { stage:'厂商自报实验', tier:'很高', priority:'B', openness:'开源可用', evidenceType:'论文/研究原文' } })
  assert.equal(normalized.stage, '厂商自报实验')
  assert.equal(normalized.tier, '很高')
  assert.equal(normalized.priority, 'B')
  assert.equal(normalized.openness, '开源可用')
})

test('historical category without active evidence does not keep new topic assessment stale', () => {
  assert.equal(assessmentState({ topic_report: { report: { evidence_ids:['current'] }, freshness:'current' }, categories:[{freshness:'stale',evidence_count:0}] }, [{id:'current'}]), 'current')
})
