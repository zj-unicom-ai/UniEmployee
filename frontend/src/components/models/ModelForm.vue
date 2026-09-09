<!-- 模型管理 · 新增/编辑表单弹窗：供应商/类型/基础模型/API 配置/额外参数。
     参照 Aix-DB llm-form.vue 适配为 JS + scoped CSS。 -->
<template>
  <n-modal
    :show="show"
    :mask-closable="false"
    preset="card"
    :title="modelId ? '编辑模型' : '添加模型'"
    style="width: 560px"
    @update:show="(v) => emit('update:show', v)"
  >
    <n-form
      ref="formRef"
      :model="formData"
      :rules="rules"
      label-placement="left"
      label-width="90px"
      require-mark-placement="right-hanging"
    >
      <n-form-item label="模型名称" path="name">
        <n-input v-model:value="formData.name" placeholder="如：DeepSeek V4" />
      </n-form-item>
      <n-form-item label="供应商" path="supplier">
        <n-select v-model:value="formData.supplier" :options="supplierOptions" placeholder="请选择" />
      </n-form-item>
      <n-form-item label="模型类型" path="model_type">
        <n-select v-model:value="formData.model_type" :options="modelTypeOptions" placeholder="请选择" />
      </n-form-item>
      <n-form-item label="基础模型" path="base_model">
        <n-input v-model:value="formData.base_model" placeholder="如 deepseek-v4-flash、gpt-4o" />
      </n-form-item>
      <n-form-item label="协议类型" path="protocol">
        <n-select v-model:value="formData.protocol" :options="protocolOptions" />
      </n-form-item>
      <n-form-item label="API 域名" path="api_domain">
        <n-input v-model:value="formData.api_domain" placeholder="https://api.deepseek.com" />
      </n-form-item>
      <n-form-item label="API Key" path="api_key">
        <n-input v-model:value="formData.api_key" type="password" show-password-on="click" placeholder="本地模型可留空" />
      </n-form-item>
      <n-divider dashed>额外配置</n-divider>
      <n-dynamic-input v-model:value="formData.config_list" :on-create="onCreateConfig">
        <template #default="{ value }">
          <div style="display: flex; gap: 8px; width: 100%">
            <n-input v-model:value="value.key" placeholder="Key" />
            <n-input v-model:value="value.val" placeholder="Value" />
          </div>
        </template>
      </n-dynamic-input>
    </n-form>
    <template #footer>
      <div style="display: flex; justify-content: space-between">
        <n-button secondary :loading="testing" @click="handleTest">测试连接</n-button>
        <div>
          <n-button style="margin-right: 12px" @click="handleClose">取消</n-button>
          <n-button type="primary" :loading="loading" @click="handleSave">保存</n-button>
        </div>
      </div>
    </template>
  </n-modal>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

const props = defineProps({
  show: Boolean,
  modelId: { type: [Number, null], default: null },
})
const emit = defineEmits(['update:show', 'success'])
const message = useMessage()

const formRef = ref(null)
const loading = ref(false)
const testing = ref(false)

const formData = reactive({
  name: '', supplier: 1, model_type: 1, base_model: '',
  protocol: 1, api_domain: '', api_key: '',
  config_list: [],
})

const supplierOptions = [
  { label: 'OpenAI', value: 1 },
  { label: 'Azure OpenAI', value: 2 },
  { label: 'Ollama', value: 3 },
  { label: 'vLLM', value: 4 },
  { label: 'DeepSeek', value: 5 },
  { label: 'Qwen', value: 6 },
  { label: 'Moonshot', value: 7 },
  { label: 'ZhipuAI', value: 8 },
  { label: 'MiniMax', value: 10 },
  { label: 'Other', value: 9 },
]
const modelTypeOptions = [
  { label: '大语言模型', value: 1 },
  { label: 'Embedding', value: 2 },
  { label: 'Rerank', value: 3 },
]
const protocolOptions = [
  { label: 'OpenAI 兼容', value: 1 },
  { label: 'Ollama', value: 2 },
]

const rules = {
  name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
  supplier: [{ required: true, message: '请选择供应商', trigger: 'change', type: 'number' }],
  model_type: [{ required: true, message: '请选择模型类型', trigger: 'change', type: 'number' }],
  base_model: [{ required: true, message: '请输入基础模型名称', trigger: 'blur' }],
  api_domain: [{ required: true, message: '请输入 API 域名', trigger: 'blur' }],
}

const defaultDomains = {
  1: 'https://api.openai.com/v1',
  3: 'http://localhost:11434/v1',
  5: 'https://api.deepseek.com',
  6: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  7: 'https://api.moonshot.cn/v1',
  8: 'https://open.bigmodel.cn/api/paas/v4/',
  10: 'https://api.minimaxi.com/v1',
}

watch(() => formData.supplier, (val) => {
  if (defaultDomains[val] && !formData.api_domain) {
    formData.api_domain = defaultDomains[val]
  }
  if (val === 3) formData.protocol = 2
  else formData.protocol = 1
})

watch(() => props.show, async (val) => {
  if (!val) return
  if (props.modelId) {
    try {
      const { data } = await api.get(`/admin/ai-models/${props.modelId}`)
      Object.assign(formData, data)
      if (!formData.config_list) formData.config_list = []
    } catch (e) {
      message.error('获取模型详情失败')
    }
  } else {
    Object.assign(formData, {
      name: '', supplier: 1, model_type: 1, base_model: '',
      protocol: 1, api_domain: '', api_key: '', config_list: [],
    })
  }
})

const handleClose = () => emit('update:show', false)

const handleTest = async () => {
  testing.value = true
  try {
    const { data } = await api.post('/admin/ai-models/status', { ...formData })
    if (data.success) message.success(data.message || '连接成功')
    else message.error(data.message || '连接失败')
  } catch (e) {
    message.error(e?.response?.data?.detail || '连接失败')
  } finally {
    testing.value = false
  }
}

const handleSave = async () => {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  loading.value = true
  try {
    if (props.modelId) {
      await api.put('/admin/ai-models', { ...formData, id: props.modelId })
    } else {
      await api.post('/admin/ai-models', formData)
    }
    message.success('保存成功')
    emit('success')
    handleClose()
  } catch (e) {
    message.error(e?.response?.data?.detail || '保存失败')
  } finally {
    loading.value = false
  }
}

const onCreateConfig = () => ({ key: '', val: '' })
</script>
