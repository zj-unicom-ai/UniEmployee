<template>
  <div class="im-page">
    <div class="toolbar"><div><h2>IM 频道</h2><p>管理 Web、飞书等消息频道。</p></div><n-button v-if="isAdmin" type="primary" @click="openCreate">新建频道</n-button></div>
    <n-alert v-if="error" type="error">{{ error }}</n-alert>
    <n-spin :show="loading"><n-empty v-if="!loading && !items.length" description="暂无 IM 频道" />
      <n-grid v-else cols="1 m:2" :x-gap="16" :y-gap="16"><n-gi v-for="item in items" :key="item.id"><n-card size="small" :title="item.name">
        <template #header-extra><n-tag size="small" :type="item.enabled ? 'success' : 'default'">{{ item.enabled ? '已启用' : '已停用' }}</n-tag></template>
        <p>{{ item.description || '暂无描述' }}</p><div>类型：{{ item.provider }}</div><div>员工：{{ item.employees?.length || 0 }} 个</div>
        <div v-if="item.provider === 'feishu'">凭证：{{ item.config?.configured ? '已配置' : '未配置' }}</div>
        <template #footer><n-space><n-button size="small" @click="edit(item)">编辑</n-button><n-button size="small" @click="toggle(item)">{{ item.enabled ? '停用' : '启用' }}</n-button></n-space></template>
      </n-card></n-gi></n-grid></n-spin>
    <n-modal v-model:show="showForm" preset="card" :title="editing ? '编辑频道' : '新建频道'" style="width:520px"><n-form>
      <n-form-item label="名称"><n-input v-model:value="form.name" /></n-form-item><n-form-item label="描述"><n-input v-model:value="form.description" /></n-form-item>
        <n-form-item label="类型"><n-select v-model:value="form.provider" :options="providerOptions" :disabled="!!editing" /></n-form-item><n-form-item label="启用"><n-switch v-model:value="form.enabled" /></n-form-item>
      <template v-if="form.provider === 'feishu'"><n-divider>飞书凭证</n+      </n-divider><n-form-item label="App ID"><n-input v-model:value="form.app_id" /></n-form-item><n-form-item label="App Secret"><n-input v-model:value="form.app_secret" type="password" show-password-on="click" /></n-form-item><n-form-item label="Tenant Key"><n-input v-model:value="form.tenant_key" /></n-form-item></template>
    </n-form><template #footer><n-button @click="showForm=false">取消</n-button><n-button type="primary" :loading="saving" @click="save">保存</n-button></template></n-modal>
  </div>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api.js'
const items=ref([]), loading=ref(false), saving=ref(false), error=ref(''), showForm=ref(false), editing=ref(null)
const form=reactive({name:'',description:'',provider:'web',enabled:true,app_id:'',app_secret:'',tenant_key:''})
const providerOptions=[{label:'Web',value:'web'},{label:'飞书',value:'feishu'},{label:'钉钉',value:'dingtalk'},{label:'企业微信',value:'wecom'}]
const isAdmin=computed(()=>JSON.parse(localStorage.getItem('user')||'{}').role==='admin')
async function load(){loading.value=true;try{items.value=(await api.get('/im/channels')).data.items||[]}catch(e){error.value=e.response?.data?.detail||'频道加载失败'}finally{loading.value=false}}
function openCreate(){editing.value=null;Object.assign(form,{name:'',description:'',provider:'web',enabled:true,app_id:'',app_secret:'',tenant_key:''});showForm.value=true}
function edit(i){editing.value=i;Object.assign(form,{name:i.name,description:i.description||'',provider:i.provider,enabled:i.enabled,app_id:'',app_secret:'',tenant_key:''});showForm.value=true}
async function save(){if(!form.name.trim())return;saving.value=true;try{const u=editing.value?`/im/channels/${editing.value.id}`:'/im/channels';const saved=await api[editing.value?'put':'post'](u,{name:form.name,description:form.description,provider:form.provider,enabled:form.enabled});const channelId=editing.value?.id||saved.data.id;if(form.provider==='feishu'&&form.app_id&&form.app_secret&&form.tenant_key)await api.put(`/im/channels/${channelId}/credentials`,{app_id:form.app_id,app_secret:form.app_secret,tenant_key:form.tenant_key});showForm.value=false;await load()}catch(e){error.value=e.response?.data?.detail||'保存失败'}finally{saving.value=false}}
async function toggle(i){try{await api.put(`/im/channels/${i.id}`,{enabled:!i.enabled});await load()}catch(e){error.value=e.response?.data?.detail||'更新失败'}}
onMounted(load)
</script>
<style scoped>.im-page{padding:24px;height:100%;overflow:auto}.toolbar{display:flex;justify-content:space-between;margin-bottom:20px}h2{margin:0 0 6px}.toolbar p{margin:0;color:#64748b}.im-page p{color:#64748b}</style>
