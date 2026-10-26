import test from 'node:test'
import assert from 'node:assert/strict'
import { buildTopicInsights, sourceIdentity } from '../frontend/src/views/agent/market-intel/marketIntelTopicInsights.js'
import { loadRadarObservations } from '../frontend/src/views/agent/market-intel/marketIntelRadar.js'
const now=new Date(2026,9,25)
const categories=[{id:'tech',name:'技术',report:{confidence:'medium'},freshness:'current'},{id:'market',name:'市场',report:{confidence:'low'},freshness:'stale'},{id:'empty',name:'暂无资料'}]
const rows=[
 {id:'a',category_id:'tech',title:'技术实验',published_at:'2026-09-10',captured_at:'2026-09-10T08:00:00Z',updated_at:'2026-10-22T08:00:00Z',research_metadata:{stage:'厂商自报实验',tier:'很高'},sources:[{url:'https://example.com/release/?utm_source=first',organization:'发布机构'}]},
 {id:'b',category_id:'tech',title:'产品预览',published_at:'2026-10-20',captured_at:'2026-10-20T08:00:00Z',research_metadata:{stage:'产品/API阶段',tier:'极高'},sources:[{url:'https://example.com/release?utm_source=second',organization:'发布机构'}]},
 {id:'c',category_id:'market',title:'前期市场信息',published_at:'2026-06-20',sources:[{url:'https://example.com/previous'}]},
 {id:'d',category_id:'market',title:'客户试点',published_at:'2026-09-05',sources:[{url:'https://example.com/customer',organization:'客户'}]},
 {id:'e',category_id:'market',title:'【图片展示样例】',captured_at:'2026-09-01T08:00:00Z',sources:[]},
 {id:'f',category_id:'',title:'无日期观察',sources:[]},
 {id:'g',category_id:'tech',title:'未来日期',published_at:'2026-10-30',sources:[{url:'https://example.com/future'}]},
]
const report={evidence_ids:['a'],data_cutoff:'2026-09-15T08:00:00Z',created_at:'2026-09-16T08:00:00Z'}

test('uses comparable calendar windows and excludes unknown or future publication dates from recent counts',()=>{
 const data=buildTopicInsights(rows,categories,report,3,now)
 assert.deepEqual(data.filtered.map(r=>r.id),['a','b','d','e'])
 assert.deepEqual(data.previous.map(r=>r.id),['c'])
 assert.equal(data.rows.find(r=>r.id==='tech').delta,2)
 assert.equal(data.rows.find(r=>r.id==='market').delta,1)
 assert.equal(data.dateMissing.length,1)
 assert.equal(buildTopicInsights(rows,categories,report,0,now).filtered.length,7)
})

test('does not equate multiple records with independent original sources or high value with commercialization',()=>{
 const data=buildTopicInsights(rows,categories,report,3,now)
 assert.equal(data.uniqueSources,2)
 assert.equal(data.repeatedSourceRecords.length,1)
 assert.deepEqual(data.repeatedSourceRecords[0].items.map(r=>r.id),['a','b'])
 assert.equal(data.highValue.length,2)
 assert.equal(data.product.length,1)
 assert.equal(data.early.length,1)
 assert.equal(data.unmarked.length,2)
 assert.equal(data.sampleWarnings[0].id,'e')
 assert.equal(data.sourceMissing[0].id,'e')
 assert.equal(data.filtered.length,4) // 样例只提示，不擅自改变数据库计数。
})

test('new and edited records, saved confidence and evidence gaps stay traceable',()=>{
 const data=buildTopicInsights(rows,categories,report,3,now)
 assert.deepEqual(data.afterCutoff.map(r=>r.id),['a','b'])
 assert.deepEqual(data.cited.map(r=>r.id),['a'])
 assert.match(data.gaps.find(r=>r.id==='market').reasons.join(' '),/待吸收|有限/)
 assert.match(data.gaps.find(r=>r.id==='empty').reasons[0],/没有观察/)
 assert.equal(data.organizations[0].name,'发布机构')
 assert.equal(data.organizations[0].items.length,2)
 assert.equal(sourceIdentity('https://example.com/a?utm_source=x&id=2#part'),sourceIdentity('https://example.com/a?id=2'))
 assert.equal(sourceIdentity('javascript:alert(1)'), '')
})

test('all-record loading honors the current topic rather than hardcoding embodied intelligence',async()=>{
 let requested=''
 const api={get:async(_,options)=>{requested=options.params.topic_id;return {data:{items:[],topics:[]}}}}
 await loadRadarObservations(api,undefined,'policy-analysis')
 assert.equal(requested,'policy-analysis')
 const empty=buildTopicInsights([],categories,null,3,now)
 assert.equal(empty.filtered.length,0)
 assert.equal(empty.uniqueSources,0)
})
