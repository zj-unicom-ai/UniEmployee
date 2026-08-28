<!-- 安全护栏 · 敏感词过滤：总开关 + 词库管理（增/删/搜索）+ 最近拦截记录 -->
<template>
  <div class="words-page">
    <div class="switch-bar">
      <div class="switch-info">
        <div class="switch-title">输入硬拦截</div>
        <div class="switch-sub">用户输入命中词库时直接拒绝进入模型；员工回复命中词库时记录审计日志</div>
      </div>
      <n-switch v-model:value="sensitiveEnabled" :loading="savingSwitch" @update:value="saveSwitch" />
    </div>

    <div class="toolbar">
      <n-input v-model:value="newWord" size="small" placeholder="输入敏感词，回车添加" style="width: 240px"
               @keyup.enter="add" clearable />
      <n-input v-model:value="newCategory" size="small" placeholder="分类（可选，如：涉政）" style="width: 160px" />
      <n-button type="primary" size="small" :loading="adding" @click="add">添加</n-button>
      <div class="flex-sp"></div>
      <n-input v-model:value="keyword" size="small" clearable placeholder="搜索词库…" style="width: 180px" />
    </div>

    <n-empty v-if="!filtered.length" description="词库为空，添加第一个敏感词" style="padding: 40px 0" />
    <div v-else class="word-list">
      <div v-for="w in filtered" :key="w.id" class="word-item">
        <span class="word">{{ w.word }}</span>
        <span v-if="w.category" class="cat">{{ w.category }}</span>
        <span class="time">{{ w.created_at }}</span>
        <n-button text size="tiny" type="error" @click="del(w)">删除</n-button>
      </div>
    </div>

    <div class="logs-section">
      <div class="logs-title">最近拦截记录</div>
      <n-empty v-if="!logs.length" description="暂无记录" style="padding: 24px 0" />
      <div v-else class="log-list">
        <div v-for="l in logs" :key="l.id" class="log-item">
          <span class="log-type" :class="l.event_type">{{ l.event_type === 'input_blocked' ? '输入拦截' : '输出标记' }}</span>
          <span class="log-detail">{{ l.detail }}</span>
          <span class="log-time">{{ l.created_at }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import api from '../../api.js'

defineOptions({ name: 'SensitiveWordsPage' })

const message = useMessage()
const sensitiveEnabled = ref(true)
const savingSwitch = ref(false)
const words = ref([])
const logs = ref([])
const newWord = ref('')
const newCategory = ref('')
const keyword = ref('')
const adding = ref(false)

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  if (!kw) return words.value
  return words.value.filter(w => (w.word || '').toLowerCase().includes(kw)
    || (w.category || '').toLowerCase().includes(kw))
})

async function load() {
  const [s, w, l] = await Promise.all([
    api.get('/admin/guard/settings'),
    api.get('/admin/guard/words'),
    api.get('/admin/guard/logs', { params: { limit: 50 } }),
  ])
  sensitiveEnabled.value = s.data.sensitive_enabled === '1'
  words.value = w.data.words || []
  logs.value = (l.data.logs || []).filter(x => x.event_type !== 'tool_denied')
}

async function saveSwitch(v) {
  savingSwitch.value = true
  try {
    await api.put('/admin/guard/settings', { sensitive_enabled: v ? '1' : '0' })
    message.success(v ? '已开启敏感词拦截' : '已关闭敏感词拦截')
  } catch (e) {
    message.error('保存失败：' + e.message)
    sensitiveEnabled.value = !v
  } finally {
    savingSwitch.value = false
  }
}

async function add() {
  const w = newWord.value.trim()
  if (!w) return
  adding.value = true
  try {
    const { data } = await api.post('/admin/guard/words', {
      word: w, category: newCategory.value.trim(),
    })
    if (data.error) { message.error(data.error); return }
    message.success('已添加')
    newWord.value = ''
    await load()
  } catch (e) {
    message.error('添加失败：' + e.message)
  } finally {
    adding.value = false
  }
}

async function del(w) {
  await api.delete(`/admin/guard/words/${w.id}`)
  message.success('已删除')
  await load()
}

onMounted(load)
</script>

<style scoped>
.words-page { max-width: 900px; }
.switch-bar { display: flex; align-items: center; justify-content: space-between; gap: 16px; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px 18px; margin-bottom: 16px; }
.switch-title { font-size: 14px; font-weight: 600; color: #334155; }
.switch-sub { font-size: 12px; color: #94a3b8; margin-top: 3px; }
.toolbar { display: flex; gap: 8px; margin-bottom: 12px; align-items: center; }
.flex-sp { flex: 1; }
.word-list { display: flex; flex-wrap: wrap; gap: 8px; }
.word-item { display: flex; align-items: center; gap: 8px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 5px 12px; font-size: 13px; }
.word { color: #0f172a; font-weight: 500; }
.cat { font-size: 11px; color: #b45309; background: #fffbeb; border-radius: 8px; padding: 1px 7px; }
.time { font-size: 11px; color: #cbd5e1; }
.logs-section { margin-top: 24px; }
.logs-title { font-size: 14px; font-weight: 600; color: #334155; margin-bottom: 10px; }
.log-list { display: flex; flex-direction: column; gap: 6px; }
.log-item { display: flex; align-items: center; gap: 10px; background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 14px; font-size: 12px; }
.log-type { font-size: 11px; border-radius: 8px; padding: 1px 8px; flex-shrink: 0; }
.log-type.input_blocked { background: #fef2f2; color: #b91c1c; }
.log-type.output_flagged { background: #fffbeb; color: #b45309; }
.log-detail { color: #475569; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-time { color: #cbd5e1; flex-shrink: 0; }
</style>
