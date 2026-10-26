<template>
  <section class="link-intake" aria-label="链接自动入库">
    <form @submit.prevent="submit"><div class="intake-heading"><strong>给小察一个链接</strong><span>读取原文 → 分类去重 → 保存观察 → 更新细分研判 → 综合判断</span></div><div class="intake-input"><input v-model="url" type="url" required maxlength="2000" aria-label="原文链接" placeholder="粘贴公开文章链接，自动整理入库并更新研判" :disabled="submitting"/><button type="submit" :disabled="submitting || !url.trim()">{{ submitting ? '提交中…' : '自动入库与研判' }}</button></div><details><summary>指定细分领域（默认自动判断）</summary><select v-model="categoryId" aria-label="指定链接所属细分领域"><option value="">自动判断</option><option v-for="cat in categories" :key="cat.id" :value="cat.id">{{ cat.name }}</option></select></details></form>
    <p v-if="error" role="alert" class="intake-error">{{ error }}</p>
    <div v-if="scopedJobs.length" class="intake-jobs"><div class="jobs-heading"><span>后台任务 · 关闭页面后继续处理</span><button type="button" @click="expanded = !expanded">{{ expanded ? '收起' : '查看任务记录' }}</button></div><article v-for="job in scopedJobs.slice(0, expanded ? 30 : 3)" :key="job.id"><div class="job-main"><span :class="['job-state',job.status]">{{ statusName(job) }}</span><a :href="job.url" target="_blank" rel="noopener noreferrer">{{ job.url }}</a><RouterLink v-if="job.observation_id" :to="{name:'market-intel-observation',params:{id:job.observation_id}}">查看入库观察 ↗</RouterLink><button v-if="['failed','interrupted'].includes(job.status)" type="button" :disabled="submitting" @click="retry(job)">继续处理</button></div><div class="job-progress"><span v-for="(step,index) in steps" :key="step.key" :class="{finished: job.status==='done' || stepIndex(job)>index, current: job.stage===step.key}">{{ step.name }}</span></div><p v-if="job.error" class="intake-error">{{ job.observation_id ? '观察已入库，后续处理未完成。' : '' }}{{ job.error }}</p></article></div>
  </section>
</template>
<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import api from '../../../api.js'
const props = defineProps({ topicId: {type:String, default:'embodied-intelligence'}, categories:{type:Array, default:()=>[]} })
const emit = defineEmits(['changed'])
const url=ref(''), categoryId=ref(''), jobs=ref([]), error=ref(''), submitting=ref(false), expanded=ref(false)
const steps=[{key:'fetch',name:'抓取原文'},{key:'extract',name:'提取与分类'},{key:'save',name:'去重入库'},{key:'category',name:'细分研判'},{key:'topic',name:'主题综合'}]
const scopedJobs=computed(()=>jobs.value.filter(j=>j.topic_id===props.topicId))
const stepIndex=job=>job.stage==='done'?5:steps.findIndex(s=>s.key===job.stage)
const statusName=job=>({done:'全部完成',failed:'处理失败',interrupted:'已中断',queued:'排队中',running:steps.find(s=>s.key===job.stage)?.name||'处理中'})[job.status]||job.status
let timer, disposed=false, polling=false
watch(()=>props.topicId,()=>{categoryId.value=''; error.value=''})
async function poll(){
 if(polling||disposed)return
 polling=true
 try{
  const {data}=await api.get('/market-research/intake')
  if(disposed)return
  const old=new Map(jobs.value.map(j=>[j.id,j]))
  jobs.value=data.items||[]
  if(jobs.value.some(j=>old.has(j.id)&&['observation_id','category_report_id','topic_report_id'].some(k=>j[k]&&j[k]!==old.get(j.id)[k])))emit('changed')
 }catch(err){if(!disposed)error.value=err.response?.data?.detail||'任务状态暂时无法读取，请稍后刷新页面。'}
 finally{polling=false;if(!disposed)timer=setTimeout(poll,jobs.value.some(j=>['queued','running'].includes(j.status))?3000:15000)}
}
async function submit(){
 if(submitting.value)return
 submitting.value=true;error.value=''
 try{const {data}=await api.post('/market-research/intake',{url:url.value.trim(),topic_id:props.topicId,category_id:categoryId.value});jobs.value=[data,...jobs.value.filter(j=>j.id!==data.id)];url.value='';clearTimeout(timer);await poll()}
 catch(err){error.value=err.response?.data?.detail||'链接提交失败，请重试'}finally{submitting.value=false}
}
async function retry(job){if(submitting.value)return;submitting.value=true;error.value='';try{await api.post(`/market-research/intake/${encodeURIComponent(job.id)}/retry`);clearTimeout(timer);await poll()}catch(err){error.value=err.response?.data?.detail||'重试失败'}finally{submitting.value=false}}
onMounted(poll)
onBeforeUnmount(()=>{disposed=true;clearTimeout(timer)})
</script>
<style scoped>
.link-intake{margin:18px 0 22px;padding:17px 19px;background:#f4f8fc;border:1px solid #d5e1ee;border-radius:8px;color:#34516f;font-size:12px}.intake-heading{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-bottom:12px}.intake-heading strong{font-size:16px;color:#23476c}.intake-heading>span{color:#7c8d9f}.intake-input{display:flex;gap:8px}.intake-input input{flex:1;min-width:0;padding:10px;border:1px solid #cad6e3;border-radius:5px;font:inherit;background:white}.intake-input button{background:#2a78d6;color:white;border:0;border-radius:5px;padding:8px 14px;font:inherit;white-space:nowrap}button{cursor:pointer}button:disabled{opacity:.5}details{margin-top:9px;color:#7a8b9c}summary{cursor:pointer}select{margin-top:8px;padding:5px;max-width:100%;border:1px solid #ccd7e2;border-radius:4px}.intake-error{color:#a34136;font-size:12px;overflow-wrap:anywhere}.intake-jobs{margin-top:17px;border-top:1px solid #dce5ee;padding-top:12px}.jobs-heading,.job-main{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.jobs-heading{justify-content:space-between;color:#7a8b9d}.jobs-heading button,.job-main button{background:none;border:0;color:#2b74b9;font:inherit}.intake-jobs article{margin-top:12px;padding-top:10px;border-top:1px solid #e2e8ef}.job-main>a{max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#497397}.job-state{font-weight:600;color:#426d99}.job-state.failed,.job-state.interrupted{color:#ac653b}.job-state.done{color:#248368}.job-progress{display:flex;gap:13px;margin-top:10px;flex-wrap:wrap;color:#9aa8b5;font-size:11px}.job-progress .finished{color:#32836a}.job-progress .current{color:#2a78d6;font-weight:600}@media(max-width:640px){.link-intake{padding:14px}.intake-input{flex-direction:column}.job-main>a{max-width:100%}.intake-input button{align-self:flex-end}}
</style>
