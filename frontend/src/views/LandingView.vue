<!-- 落地页：产品介绍 Hero + 能力展示 + 工作流程 + 岗位矩阵 + CTA -->
<template>
  <div class="landing">
    <!-- 环境光晕 -->
    <div class="ambient">
      <div class="blob blob-1"></div>
      <div class="blob blob-2"></div>
      <div class="blob blob-3"></div>
    </div>

    <!-- 导航 -->
    <nav class="nav" :class="{ scrolled: navScrolled }">
      <div class="nav-inner">
        <a href="#hero" class="nav-logo" @click.prevent="scrollTo('hero')">UniEmployee</a>
        <div class="nav-links">
          <a href="#capabilities" @click.prevent="scrollTo('capabilities')">能力</a>
          <a href="#how" @click.prevent="scrollTo('how')">工作方式</a>
          <a href="#matrix" @click.prevent="scrollTo('matrix')">岗位</a>
          <a @click.prevent="goCases">案例</a>
          </div>
        </div>
      </nav>

    <!-- Hero -->
    <section class="hero" id="hero">
      <div class="container hero-inner">
        <div class="hero-content">
          <span class="eyebrow">企业数字员工平台</span>
          <h1 class="hero-title">构建你的专属<br><span class="grad">数字员工团队</span></h1>
          <p class="hero-subtitle">UniEmployee 是企业级数字员工平台，帮助企业快速创建、管理和运营数字员工，让 AI 从回答问题走向持续完成工作。</p>
          <div class="hero-actions">
            <a href="/app/home" class="btn-p">立即体验</a>
            <a href="/app/home" class="btn-s">预约演示</a>
          </div>
        </div>

        <div class="hero-visual">
          <div class="network">
            <div class="net-glow"></div>
            <svg class="net-svg" viewBox="0 0 500 480" preserveAspectRatio="none">
              <defs>
                <linearGradient id="ag" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#5EEAD4" stop-opacity=".6"/>
                  <stop offset="50%" stop-color="#818CF8" stop-opacity=".6"/>
                  <stop offset="100%" stop-color="#FBB969" stop-opacity=".6"/>
                </linearGradient>
                <filter id="lg"><feGaussianBlur stdDeviation="1.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
              </defs>
              <g stroke="rgba(255,255,255,.05)" stroke-width="1" fill="none">
                <path d="M 95 90 Q 170 160 245 230"/><path d="M 395 70 Q 320 150 245 230"/>
                <path d="M 245 230 Q 160 310 80 390"/><path d="M 245 230 Q 335 315 420 400"/>
                <path d="M 95 90 Q 245 25 395 70"/><path d="M 80 390 Q 250 460 420 400"/>
                <path d="M 95 90 Q 35 245 80 390"/><path d="M 395 70 Q 470 235 420 400"/>
              </g>
              <g stroke="url(#ag)" stroke-width="1.5" fill="none" filter="url(#lg)">
                <path d="M 95 90 Q 170 160 245 230" class="flow-line"/>
                <path d="M 395 70 Q 320 150 245 230" class="flow-line" style="animation-delay:-1s"/>
                <path d="M 245 230 Q 160 310 80 390" class="flow-line" style="animation-delay:-2s"/>
                <path d="M 245 230 Q 335 315 420 400" class="flow-line" style="animation-delay:-3s"/>
                <path d="M 95 90 Q 245 25 395 70" class="flow-line" style="animation-delay:-1.5s"/>
                <path d="M 80 390 Q 250 460 420 400" class="flow-line" style="animation-delay:-2.5s"/>
                <path d="M 95 90 Q 35 245 80 390" class="flow-line" style="animation-delay:-.5s"/>
                <path d="M 395 70 Q 470 235 420 400" class="flow-line" style="animation-delay:-3.5s"/>
              </g>
            </svg>

            <div class="net-card net-card-1"><div class="net-top"><div class="avatar av-1">市</div><div class="net-role">市场分析师</div></div><div class="net-status"><span class="dot dot-ok"></span><span>在线</span></div><div class="net-desc">行业研究与竞品分析</div></div>
            <div class="net-card net-card-2"><div class="net-top"><div class="avatar av-2">数</div><div class="net-role">数据分析师</div></div><div class="net-status"><span class="dot dot-busy"></span><span>执行中</span></div><div class="net-desc">数据洞察与报表分析</div></div>
            <div class="net-card net-card-3"><div class="net-top"><div class="avatar av-3">销</div><div class="net-role">销售顾问</div></div><div class="net-status"><span class="dot dot-ok"></span><span>在线</span></div><div class="net-desc">客户跟进与商机挖掘</div></div>
            <div class="net-card net-card-4"><div class="net-top"><div class="avatar av-4">行</div><div class="net-role">行政秘书</div></div><div class="net-status"><span class="dot dot-think"></span><span>分析中</span></div><div class="net-desc">日常行政事务处理</div></div>
            <div class="net-card net-card-5"><div class="net-top"><div class="avatar av-5">客</div><div class="net-role">客服专员</div></div><div class="net-status"><span class="dot dot-ok"></span><span>在线</span></div><div class="net-desc">客户咨询与问题处理</div></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 能力 -->
    <section class="caps" id="capabilities">
      <div class="container">
        <div class="section-header" :class="{ reveal: true, visible: capsVisible }" ref="capsRef">
          <h2 class="section-title">让数字员工真正完成工作</h2>
          <p class="section-subtitle">不仅回答问题，更持续创造价值。</p>
        </div>
        <div class="caps-grid">
          <div v-for="(cap, i) in capabilities" :key="cap.title"
               class="cap-card"
               :class="[`r${i+1}`, { reveal: true, visible: capsVisible }]"
               :style="{ transitionDelay: `${(i+1)*0.1}s` }">
            <div class="cap-icon" v-html="cap.icon"></div>
            <h3 class="cap-title">{{ cap.title }}</h3>
            <p class="cap-desc">{{ cap.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <!-- 工作方式 -->
    <section class="how" id="how">
      <div class="container">
        <div class="section-header" :class="{ reveal: true, visible: howVisible }" ref="howRef">
          <h2 class="section-title">数字员工如何工作</h2>
          <p class="section-subtitle">从需求到执行，让数字员工自主完成工作。</p>
        </div>
        <div class="timeline" :class="{ reveal: true, visible: howVisible }">
          <div class="tl-line"></div>
          <div v-for="step in steps" :key="step.label" class="tl-step">
            <div class="tl-icon" v-html="step.icon"></div>
            <span class="tl-label">{{ step.label }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- 岗位矩阵 -->
    <section class="matrix" id="matrix">
      <div class="container">
        <div class="section-header" :class="{ reveal: true, visible: matrixVisible }" ref="matrixRef">
          <h2 class="section-title">覆盖企业每一个岗位</h2>
          <p class="section-subtitle">构建属于企业自己的数字员工团队。</p>
        </div>
        <div class="matrix-grid">
          <div v-for="(m, i) in matrix" :key="m.role"
               class="m-card"
               :class="[`r${(i%4)+1}`, { reveal: true, visible: matrixVisible }]"
               :style="{ transitionDelay: `${(i%4+1)*0.1}s` }">
            <div class="m-top">
              <div class="avatar" :style="m.avatarStyle">{{ m.initial }}</div>
              <div class="m-role">{{ m.role }}</div>
            </div>
            <div class="m-desc">{{ m.desc }}</div>
            <div class="m-status"><span :class="['dot', m.dotClass]"></span>{{ m.status }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- CTA -->
    <section class="cta-section" id="cta" ref="ctaRef">
      <div class="cta-bg"></div>
      <div class="container cta-inner" :class="{ reveal: true, visible: ctaVisible }">
        <h2 class="cta-title">未来，每一家企业<br>都将拥有自己的<span class="grad">数字员工团队</span></h2>
        <p class="cta-sub">让数字员工成为企业真正的生产力。</p>
        <div class="cta-actions">
          <a href="/app/home" class="btn-p">立即体验</a>
          <a href="/app/home" class="btn-s">预约演示</a>
        </div>
      </div>
    </section>

    <!-- Footer -->
    <footer>
      <div class="container footer-inner">
        <div class="footer-brand">
          <span class="footer-logo">UniEmployee</span>
          <span class="footer-tagline">企业数字员工平台</span>
        </div>
        <div class="footer-meta">
          <span>© 2026 UniEmployee</span>
          <a href="https://github.com/wanrengang/UniEmployee">GitHub</a>
          <a href="#">联系我们</a>
          <a href="#">隐私政策</a>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const navScrolled = ref(false)
const capsVisible = ref(false)
const howVisible = ref(false)
const matrixVisible = ref(false)
const ctaVisible = ref(false)
const capsRef = ref(null)
const howRef = ref(null)
const matrixRef = ref(null)
const ctaRef = ref(null)
const capabilities = [
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8" stroke-dasharray="2 3"/></svg>', title: '理解工作', desc: '理解需求，制定执行计划。' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="8" cy="8" r="3"/><circle cx="16" cy="16" r="3"/><line x1="10.5" y1="10.5" x2="13.5" y2="13.5"/></svg>', title: '连接企业', desc: '连接知识、系统和业务能力。' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 12 Q 7 4 11 12 T 19 12 L21 12"/></svg>', title: '执行工作', desc: '自主完成复杂任务与业务流程。' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="9" cy="12" r="4"/><circle cx="15" cy="12" r="4"/></svg>', title: '协同成长', desc: '多个数字员工协同工作，持续学习成长。' },
]

const steps = [
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="14" cy="12" r="5"/><line x1="3" y1="12" x2="9" y2="12"/><path d="M6 9 L9 12 L6 15"/></svg>', label: '提出需求' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>', label: '理解工作' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="12" x2="16" y2="12"/><line x1="8" y1="15" x2="13" y2="15"/></svg>', label: '制定计划' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M10 8 L16 12 L10 16 Z" fill="currentColor" stroke="none"/></svg>', label: '执行任务' },
  { icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M8 15 L12 10 L16 14 M12 10 L12 7"/></svg>', label: '持续成长' },
]

const matrix = [
  { initial: '市', role: '市场分析师', desc: '行业研究与竞品分析', status: '在线', dotClass: 'dot-ok', avatarStyle: 'background:linear-gradient(135deg,var(--teal),var(--indigo));box-shadow:0 0 12px rgba(94,234,212,.3)' },
  { initial: '数', role: '数据分析师', desc: '数据洞察与报表分析', status: '分析中', dotClass: 'dot-think', avatarStyle: 'background:linear-gradient(135deg,var(--indigo),var(--violet));box-shadow:0 0 12px rgba(129,140,248,.3)' },
  { initial: '销', role: '销售顾问', desc: '客户跟进与商机挖掘', status: '执行中', dotClass: 'dot-busy', avatarStyle: 'background:linear-gradient(135deg,var(--amber),var(--rose));box-shadow:0 0 12px rgba(244,114,182,.3)' },
  { initial: '行', role: '行政秘书', desc: '日常行政事务处理', status: '在线', dotClass: 'dot-ok', avatarStyle: 'background:linear-gradient(135deg,#67E8F9,var(--teal));box-shadow:0 0 12px rgba(103,232,249,.3)' },
  { initial: '客', role: '客服专员', desc: '客户咨询与问题处理', status: '分析中', dotClass: 'dot-think', avatarStyle: 'background:linear-gradient(135deg,var(--rose),var(--amber));box-shadow:0 0 12px rgba(244,114,182,.3)' },
  { initial: '研', role: '研发助手', desc: '辅助技术研发与文档编写', status: '在线', dotClass: 'dot-ok', avatarStyle: 'background:linear-gradient(135deg,var(--violet),var(--indigo));box-shadow:0 0 12px rgba(167,139,250,.3)' },
  { initial: 'H', role: 'HR 助理', desc: '招聘筛选与员工关系管理', status: '执行中', dotClass: 'dot-busy', avatarStyle: 'background:linear-gradient(135deg,var(--teal),var(--amber));box-shadow:0 0 12px rgba(94,234,212,.3)' },
  { initial: '财', role: '财务顾问', desc: '财务分析与预算管理', status: '在线', dotClass: 'dot-ok', avatarStyle: 'background:linear-gradient(135deg,var(--amber),var(--indigo));box-shadow:0 0 12px rgba(251,185,105,.3)' },
]


let observers = []

function observe(el, ref) {
  if (!el) return
  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) { ref.value = true; io.unobserve(e.target) }
    })
  }, { threshold: 0.12 })
  io.observe(el)
  observers.push(io)
}

onMounted(() => {
  observe(capsRef.value, capsVisible)
  observe(howRef.value, howVisible)
  observe(matrixRef.value, matrixVisible)
  observe(ctaRef.value, ctaVisible)
})

onUnmounted(() => {
  observers.forEach(io => io.disconnect())
  window.removeEventListener('scroll', onScroll)
})

function onScroll() {
  navScrolled.value = window.scrollY > 40
}

function scrollTo(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
}

function goToApp(routeName) {
  const token = localStorage.getItem('token')
  if (token) router.push(routeName ? { name: routeName } : { name: 'home' })
  else router.push({ name: 'login', query: { next: routeName ? `/app/${routeName}` : '/app/home' } })
}

function goCases() {
  router.push({ name: 'cases' })
}
</script>

<style scoped>
/* ============================================================
   DESIGN SYSTEM — "Dawn Aurora"
   Deep space + soft multi-hue aurora gradient.
   ============================================================ */
.landing {
  --bg: #08090C;
  --bg-2: #0B0D12;
  --surface: rgba(255, 255, 255, 0.025);
  --surface-2: rgba(255, 255, 255, 0.045);
  --border: rgba(255, 255, 255, 0.07);
  --border-2: rgba(255, 255, 255, 0.13);
  --text-1: #F5F5F7;
  --text-2: #9CA3AF;
  --text-3: #5C5F66;
  --teal: #5EEAD4;
  --indigo: #818CF8;
  --amber: #FBB969;
  --rose: #F472B6;
  --violet: #A78BFA;
  --max-w: 1200px;
  --radius: 16px;
  --radius-sm: 12px;
  font-family: "PingFang SC", "SF Pro Display", -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
  background: var(--bg);
  color: var(--text-1);
  line-height: 1.6;
  overflow-y: auto;
  height: 100vh;
  font-weight: 300;
  letter-spacing: 0.02em;
}

/* Ambient glow */
.ambient {
  position: fixed; inset: 0; z-index: 0;
  pointer-events: none; overflow: hidden;
}
.blob {
  position: absolute; border-radius: 50%; filter: blur(90px); opacity: 0.16;
  animation: drift 28s ease-in-out infinite;
}
.blob-1 {
  width: 600px; height: 600px;
  background: radial-gradient(circle, var(--indigo), transparent 70%);
  top: -15%; left: 25%;
}
.blob-2 {
  width: 500px; height: 500px;
  background: radial-gradient(circle, var(--teal), transparent 70%);
  bottom: -10%; right: 5%; animation-delay: -14s;
}
.blob-3 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, var(--amber), transparent 70%);
  top: 40%; left: -10%; animation-delay: -7s; opacity: 0.08;
}
@keyframes drift {
  0%, 100% { transform: translate(0,0) scale(1); }
  33% { transform: translate(30px,-40px) scale(1.05); }
  66% { transform: translate(-20px,30px) scale(0.95); }
}

.container {
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 0 32px;
  position: relative;
  z-index: 1;
}
a { color: inherit; text-decoration: none; cursor: pointer; }

.eyebrow {
  display: inline-block;
  font-size: 0.8rem;
  font-weight: 400;
  letter-spacing: 0.14em;
  color: var(--teal);
  margin-bottom: 24px;
  text-transform: uppercase;
}
.section-header {
  text-align: center;
  max-width: 680px;
  margin: 0 auto 72px;
}
.section-title {
  font-size: clamp(2rem, 4.2vw, 3.25rem);
  font-weight: 200;
  letter-spacing: 0.03em;
  line-height: 1.25;
  margin-bottom: 20px;
}
.section-subtitle {
  font-size: clamp(1rem, 1.3vw, 1.15rem);
  color: var(--text-2);
  font-weight: 300;
  line-height: 1.7;
}

/* Buttons */
.btn-p, .btn-s {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 13px 32px;
  border-radius: 100px;
  font-size: 0.95rem;
  font-weight: 450;
  transition: all 0.3s cubic-bezier(.4,0,.2,1);
  cursor: pointer;
}
.btn-p {
  background: var(--text-1);
  color: var(--bg);
  border: 1px solid var(--text-1);
}
.btn-p:hover { transform: translateY(-1px); box-shadow: 0 8px 32px rgba(255,255,255,.12); }
.btn-s {
  background: transparent;
  color: var(--text-1);
  border: 1px solid var(--border-2);
}
.btn-s:hover { border-color: var(--text-2); background: var(--surface); }

/* Nav */
.nav {
  position: fixed; top: 0; left: 0; right: 0;
  z-index: 100; height: 64px;
  display: flex; align-items: center;
  background: transparent;
  transition: all 0.3s;
}
.nav.scrolled {
  background: rgba(8,9,12,.72);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--border);
}
.nav-inner {
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 0 32px;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.nav-logo {
  font-size: 1.1rem;
  font-weight: 450;
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, var(--teal), var(--indigo), var(--amber));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.nav-links { display: flex; gap: 40px; }
.nav-links a {
  font-size: 0.9rem;
  color: var(--text-2);
  font-weight: 350;
  transition: color 0.2s;
}
.nav-links a:hover { color: var(--text-1); }

/* Hero */
.hero {
  min-height: 100vh;
  display: flex;
  align-items: center;
  padding: 64px 0 40px;
  position: relative;
}
.hero-inner {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 48px;
  align-items: center;
  width: 100%;
}
.hero-content { max-width: 560px; }
.hero-title {
  font-size: clamp(2.75rem, 6.2vw, 5rem);
  font-weight: 200;
  line-height: 1.18;
  letter-spacing: 0.02em;
  margin-bottom: 28px;
}
.hero-title .grad {
  background: linear-gradient(135deg, var(--teal), var(--indigo), var(--amber));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.hero-subtitle {
  font-size: clamp(1rem, 1.25vw, 1.15rem);
  color: var(--text-2);
  line-height: 1.75;
  margin-bottom: 40px;
  max-width: 520px;
}
.hero-actions { display: flex; gap: 16px; flex-wrap: wrap; }

/* Network visual */
.hero-visual {
  position: relative; width: 100%;
  display: flex; justify-content: center; align-items: center;
}
.network {
  position: relative; width: 100%;
  max-width: 500px; aspect-ratio: 25/24;
}
.net-svg {
  position: absolute; inset: 0; width: 100%; height: 100%; z-index: 1;
}
.net-glow {
  position: absolute; inset: 10%; border-radius: 50%;
  background: radial-gradient(circle, rgba(129,140,248,.08), transparent 60%);
  filter: blur(30px); z-index: 0;
}
.net-card {
  position: absolute; transform: translate(-50%,-50%); z-index: 2;
  width: 145px; padding: 16px 14px;
  background: rgba(18,20,26,.65);
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%);
  border: 1px solid rgba(255,255,255,.08);
  border-radius: var(--radius-sm);
  transition: all 0.4s cubic-bezier(.4,0,.2,1);
  animation: float-card 6s ease-in-out infinite;
}
.net-card:hover {
  border-color: var(--border-2);
  background: rgba(22,24,32,.85);
  transform: translate(-50%,-50%) translateY(-3px);
}
.net-card-1 { left: 19%; top: 19%; animation-delay: 0s; }
.net-card-2 { left: 79%; top: 15%; animation-delay: -1.5s; }
.net-card-3 { left: 49%; top: 48%; animation-delay: -3s; }
.net-card-4 { left: 16%; top: 81%; animation-delay: -4.5s; }
.net-card-5 { left: 84%; top: 83%; animation-delay: -2s; }
@keyframes float-card {
  0%, 100% { transform: translate(-50%,-50%); }
  50% { transform: translate(-50%, calc(-50% - 5px)); }
}
.net-top { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.85rem; font-weight: 300;
  color: rgba(255,255,255,.95); flex-shrink: 0;
}
.net-role { font-size: 0.82rem; font-weight: 480; color: var(--text-1); line-height: 1.2; }
.net-status {
  display: flex; align-items: center; gap: 5px;
  font-size: 0.72rem; color: var(--text-2); margin-bottom: 6px;
}
.dot {
  width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
}
.dot-ok {
  background: var(--teal); box-shadow: 0 0 6px var(--teal);
  animation: pulse-d 2.5s ease-in-out infinite;
}
.dot-busy {
  background: var(--amber); box-shadow: 0 0 6px var(--amber);
  animation: pulse-b 1.8s ease-in-out infinite;
}
.dot-think {
  background: var(--indigo); box-shadow: 0 0 6px var(--indigo);
  animation: pulse-t 3s ease-in-out infinite;
}
@keyframes pulse-d { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.6; transform: scale(.8); } }
@keyframes pulse-b { 0%,100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(.7); } }
@keyframes pulse-t { 0%,100% { opacity: 0.9; transform: scale(1); } 50% { opacity: 0.4; transform: scale(.85); } }
.net-desc { font-size: 0.72rem; color: var(--text-2); line-height: 1.45; }
.flow-line { stroke-dasharray: 4 8; animation: flow 4s linear infinite; }
@keyframes flow { to { stroke-dashoffset: -24; } }

/* Capabilities */
.caps { padding: 140px 0; }
.caps-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}
.cap-card {
  padding: 36px 28px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all 0.35s cubic-bezier(.4,0,.2,1);
  position: relative; overflow: hidden;
}
.cap-card::before {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(135deg, transparent 40%, rgba(255,255,255,.02) 100%);
  opacity: 0; transition: opacity 0.35s; pointer-events: none;
}
.cap-card:hover { border-color: var(--border-2); background: var(--surface-2); transform: translateY(-4px); }
.cap-card:hover::before { opacity: 1; }
.cap-icon {
  width: 44px; height: 44px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 12px; background: var(--surface-2);
  border: 1px solid var(--border); margin-bottom: 24px;
  color: var(--teal);
}
.cap-card:nth-child(2) .cap-icon { color: var(--indigo); }
.cap-card:nth-child(3) .cap-icon { color: var(--amber); }
.cap-card:nth-child(4) .cap-icon { color: var(--rose); }
.cap-icon :deep(svg) { width: 22px; height: 22px; }
.cap-title { font-size: 1.15rem; font-weight: 450; margin-bottom: 10px; }
.cap-desc { font-size: 0.9rem; color: var(--text-2); line-height: 1.65; }

/* How it works */
.how { padding: 140px 0; }
.timeline {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 0 20px;
  max-width: 1000px;
  margin: 0 auto;
}
.tl-line {
  position: absolute; top: 24px;
  left: 60px; right: 60px;
  height: 1px;
  background: linear-gradient(90deg, var(--teal), var(--indigo), var(--amber), var(--rose));
  opacity: 0.3; z-index: 0;
}
.tl-line::after {
  content: '';
  position: absolute; top: 0; left: 0; width: 100%; height: 100%;
  background: linear-gradient(90deg, transparent, var(--teal), transparent);
  background-size: 30% 100%; background-repeat: no-repeat;
  animation: tl-flow 6s linear infinite;
}
@keyframes tl-flow {
  0% { background-position: -30% 0; }
  100% { background-position: 130% 0; }
}
.tl-step {
  position: relative; z-index: 1;
  display: flex; flex-direction: column;
  align-items: center; text-align: center;
  flex: 1; padding: 0 8px;
}
.tl-icon {
  width: 48px; height: 48px; border-radius: 50%;
  background: var(--bg-2); border: 1px solid var(--border-2);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 20px; transition: all 0.3s;
}
.tl-icon :deep(svg) { width: 22px; height: 22px; color: var(--text-1); }
.tl-step:hover .tl-icon { border-color: var(--teal); box-shadow: 0 0 16px rgba(94,234,212,.2); }
.tl-step:nth-child(2):hover .tl-icon { border-color: var(--indigo); box-shadow: 0 0 16px rgba(129,140,248,.2); }
.tl-step:nth-child(3):hover .tl-icon { border-color: var(--amber); box-shadow: 0 0 16px rgba(251,185,105,.2); }
.tl-step:nth-child(4):hover .tl-icon { border-color: var(--rose); box-shadow: 0 0 16px rgba(244,114,182,.2); }
.tl-step:nth-child(5):hover .tl-icon { border-color: var(--violet); box-shadow: 0 0 16px rgba(167,139,250,.2); }
.tl-label { font-size: 0.95rem; font-weight: 450; }

/* Matrix */
.matrix { padding: 140px 0; }
.matrix-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.m-card {
  padding: 28px 24px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all 0.35s cubic-bezier(.4,0,.2,1);
  position: relative; overflow: hidden;
}
.m-card::after {
  content: '';
  position: absolute; top: 0; right: 0;
  width: 120px; height: 120px;
  background: radial-gradient(circle at top right, rgba(129,140,248,.06), transparent 70%);
  opacity: 0; transition: opacity 0.35s; pointer-events: none;
}
.m-card:hover { border-color: var(--border-2); background: var(--surface-2); transform: translateY(-3px); }
.m-card:hover::after { opacity: 1; }
.m-top { display: flex; align-items: center; gap: 14px; margin-bottom: 16px; }
.m-role { font-size: 1rem; font-weight: 450; }
.m-desc { font-size: 0.85rem; color: var(--text-2); line-height: 1.6; margin-bottom: 14px; }
.m-status { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; color: var(--text-2); }

/* CTA */
.cta-section {
  padding: 160px 0;
  position: relative;
  overflow: hidden;
  text-align: center;
}
.cta-bg {
  position: absolute; inset: 0; z-index: 0; pointer-events: none;
}
.cta-bg::before {
  content: '';
  position: absolute; top: 50%; left: 50%;
  transform: translate(-50%,-50%);
  width: 900px; height: 600px;
  background: radial-gradient(ellipse at center, rgba(251,185,105,.1), rgba(244,114,182,.06) 30%, rgba(129,140,248,.04) 60%, transparent 80%);
  filter: blur(40px);
}
.cta-bg::after {
  content: '';
  position: absolute; bottom: -20%; left: 50%;
  transform: translateX(-50%);
  width: 600px; height: 300px;
  background: radial-gradient(ellipse at center, rgba(94,234,212,.06), transparent 70%);
  filter: blur(30px);
}
.cta-inner { position: relative; z-index: 1; }
.cta-title {
  font-size: clamp(2.25rem, 5vw, 4rem);
  font-weight: 200;
  line-height: 1.25;
  letter-spacing: 0.02em;
  margin-bottom: 24px;
  max-width: 800px;
  margin-left: auto;
  margin-right: auto;
}
.cta-title .grad {
  background: linear-gradient(135deg, var(--amber), var(--rose), var(--violet));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  white-space: nowrap;
}
.cta-sub {
  font-size: clamp(1rem, 1.3vw, 1.15rem);
  color: var(--text-2);
  margin-bottom: 48px;
}
.cta-actions { display: flex; gap: 16px; justify-content: center; flex-wrap: wrap; }

/* Footer */
footer {
  padding: 60px 0 48px;
  border-top: 1px solid var(--border);
  position: relative; z-index: 1;
}
.footer-inner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 24px;
}
.footer-brand { display: flex; flex-direction: column; gap: 4px; }
.footer-logo { font-size: 1rem; font-weight: 450; }
.footer-tagline { font-size: 0.82rem; color: var(--text-3); }
.footer-meta {
  display: flex;
  align-items: center;
  gap: 24px;
  font-size: 0.82rem;
  color: var(--text-3);
  flex-wrap: wrap;
}
.footer-meta a { color: var(--text-3); transition: color .2s; }
.footer-meta a:hover { color: var(--text-2); }

/* Reveal animation */
.reveal {
  opacity: 0;
  transform: translateY(24px);
  transition: opacity 0.8s cubic-bezier(.4,0,.2,1), transform 0.8s cubic-bezier(.4,0,.2,1);
}
.reveal.visible { opacity: 1; transform: translateY(0); }
.r1 { transition-delay: 0.1s; }
.r2 { transition-delay: 0.2s; }
.r3 { transition-delay: 0.3s; }
.r4 { transition-delay: 0.4s; }

/* Responsive */
@media (max-width: 1024px) {
  .hero-inner { grid-template-columns: 1fr; gap: 60px; }
  .hero-content { max-width: 100%; text-align: center; }
  .hero-actions { justify-content: center; }
  .hero-visual { order: -1; max-width: 500px; margin: 0 auto; }
  .caps-grid { grid-template-columns: repeat(2, 1fr); }
  .matrix-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) { .nav-links { display: none; } }
@media (max-width: 640px) {
  .container { padding: 0 24px; }
  .net-card { width: 128px; padding: 12px 11px; }
}
</style>