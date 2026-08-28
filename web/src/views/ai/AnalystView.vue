<script setup>
/**
 * AnalystView — 分析师工作区（三栏）
 * 左：会话列表（持久化）｜中：对话流 + 输入区｜右：上下文面板
 * 支持 @标的解析、引用报告（report_id）、Markdown 渲染回答、会话恢复。
 */
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import { api } from '../../api/client'
import AppIcon from '../../ui/AppIcon.vue'
import SessionList from '../../components/ai/SessionList.vue'
import ContextPanel from '../../components/ai/ContextPanel.vue'
import MarkdownView from '../../components/ai/MarkdownView.vue'

const route = useRoute()
const router = useRouter()
const store = useAiStore()

const chatLog = ref([]) // [{role, text, pending, error, stopped}]
const chatInput = ref('')
const sending = ref(false)
const loadingMsgs = ref(false)
const activeSessionId = ref(null)
const showCtxMobile = ref(false)
const chatScrollEl = ref(null)
let abortController = null

// 标的代码表（@ 解析用）
const stockTable = ref([])
const atCandidates = ref([])
const atPos = ref(-1) // 正在 @ 输入的游标位置

const stockNamesLoaded = ref(false)
async function loadStockNames() {
  if (stockNamesLoaded.value) return
  try {
    const r = await api.stockNames()
    stockTable.value = r?.names || r?.items || r?.stocks || []
    if (Array.isArray(r)) stockTable.value = r
    stockNamesLoaded.value = true
  } catch (e) {
    stockTable.value = []
  }
}

// 输入 @ 检测
function onInput(e) {
  const v = chatInput.value
  const cur = e.target.selectionStart ?? v.length
  const before = v.slice(0, cur)
  const m = before.match(/@([\u4e00-\u9fa5A-Za-z0-9]*)$/)
  if (m) {
    atPos.value = cur - m[0].length
    const kw = m[1] || ''
    const table = Array.isArray(stockTable.value) ? stockTable.value : []
    atCandidates.value = table
      .filter((s) => (s.name || '').includes(kw) || (s.code || '').includes(kw))
      .slice(0, 6)
  } else {
    atCandidates.value = []
    atPos.value = -1
  }
}
function pickStock(s) {
  const before = chatInput.value.slice(0, atPos.value)
  const after = chatInput.value.slice(atPos.value).replace(/^@[\u4e00-\u9fa5A-Za-z0-9]*/, '')
  chatInput.value = `${before}@${s.name}${after} `
  atCandidates.value = []
  atPos.value = -1
}

// 解析当前消息中的标的（发送前）
function parseStockInText(text) {
  const table = Array.isArray(stockTable.value) ? stockTable.value : []
  const m = text.match(/@([\u4e00-\u9fa5A-Za-z]{2,})/)
  if (!m) return null
  const hit = table.find((s) => s.name === m[1]) || table.find((s) => (s.name || '').includes(m[1]))
  if (!hit) return null
  return { name: hit.name, code: hit.code || '', sector: hit.sector || '' }
}

// 会话管理
async function newSession() {
  const s = await store.createSession('新会话')
  if (s) {
    activeSessionId.value = s.id
    chatLog.value = []
    await store.loadSessions()
  }
}
async function selectSession(id) {
  activeSessionId.value = id
  loadingMsgs.value = true
  try {
    const r = await api.llm('/sessions/messages', { id })
    chatLog.value = (r.messages || []).map((m) => ({ role: m.role, text: m.content }))
  } catch (e) {
    chatLog.value = []
  } finally {
    loadingMsgs.value = false
    scrollToBottom()
  }
}
async function onRename(id, title) {
  await store.renameSession(id, title)
}
async function onDelete(id) {
  if (activeSessionId.value === id) {
    activeSessionId.value = null
    chatLog.value = []
  }
  await store.deleteSession(id)
}

// 发送
function scrollToBottom() {
  nextTick(() => {
    const el = chatScrollEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function sendChat() {
  const q = chatInput.value.trim()
  if (!q || sending.value) return
  // 会话兜底：无会话时自动创建
  if (!activeSessionId.value) {
    const s = await store.createSession(q.slice(0, 16) || '新会话')
    if (!s) return
    activeSessionId.value = s.id
  }
  const sid = activeSessionId.value

  // 解析 @ 标的
  const stock = parseStockInText(q)
  if (stock) store.setContextStock({ ...stock, change: 0 })

  chatLog.value.push({ role: 'user', text: q })
  chatInput.value = ''
  const aiIndex = chatLog.value.length
  chatLog.value.push({ role: 'ai', text: '', pending: true })
  scrollToBottom()

  // 持久化用户消息
  store.saveMessage(sid, 'user', q)

  const history = chatLog.value
    .slice(0, aiIndex)
    .filter((m) => !m.pending && m.text)
    .slice(-12)
    .map((m) => ({ role: m.role === 'ai' ? 'assistant' : 'user', content: m.text }))

  const payload = { question: q, history }
  if (store.contextReport?.id) payload.report_id = store.contextReport.id

  abortController = new AbortController()
  sending.value = true
  try {
    const r = await api.llmPost('/chat', payload, { signal: abortController.signal })
    const text = r.reply || r.answer || r.text || (r.ok === false ? r.error : JSON.stringify(r))
    chatLog.value[aiIndex] = { role: 'ai', text, pending: false }
    store.saveMessage(sid, 'assistant', text)
    if (!store.contextReport?.id && !stock) store.clearContext()
  } catch (e) {
    const stopped = e?.name === 'CanceledError' || e?.code === 'ERR_CANCELED' || e?.message?.includes('canceled')
    if (stopped) {
      chatLog.value[aiIndex] = { role: 'ai', text: '[已停止生成]', pending: false, stopped: true }
    } else {
      chatLog.value[aiIndex] = { role: 'ai', text: '出错了：' + (e.message || String(e)), pending: false, error: true }
    }
  } finally {
    sending.value = false
    abortController = null
    scrollToBottom()
  }
}
function stopChat() {
  if (abortController) {
    abortController.abort()
    abortController = null
  }
}
function onChatEnter() {
  if (sending.value) stopChat()
  else sendChat()
}

// 引用报告（从路由 query 或工作台跳转）
watch(
  () => route.query.report_id,
  (v) => {
    if (!v) return
    const rid = Number(v)
    if (rid && rid !== store.contextReport?.id) {
      api.llm('/report', { id: rid })
        .then((r) => {
          if (r.report) store.setContextReport({ id: rid, title: r.report.title, created_at: r.report.created_at })
        })
        .catch(() => {})
    }
  },
  { immediate: true }
)

const suggestions = [
  '帮我复盘一下今天的市场行情',
  '解读最近报告中的半导体板块',
  '有哪些板块资金流入明显？',
]

// 从快讯模块跳转而来（携带 q 参数）：自动填入并发送分析请求
let qHandled = false
watch(
  () => route.query.q,
  async (v) => {
    if (!v || qHandled) return
    qHandled = true
    await nextTick()
    setTimeout(async () => {
      if (activeSessionId.value === null && store.sessions.length) {
        await selectSession(store.sessions[0].id)
      }
      chatInput.value = `请分析这条快讯：${v}`
      await sendChat()
      router.replace({ query: {} })
    }, 500)
  },
  { immediate: true }
)

onMounted(async () => {
  loadStockNames()
  await store.loadSessions()
  // 自动选中最近会话；无会话时显示空状态引导
  if (store.sessions.length) selectSession(store.sessions[0].id)
  store.startPolling()
})
onBeforeUnmount(() => {
  store.stopPolling()
  if (abortController) abortController.abort()
})
</script>

<template>
  <div class="an">
    <!-- 沉浸式对话布局占据整屏高度，不适合加可见页头；
         用视觉隐藏的 h1 保留文档语义与读屏导航锚点 -->
    <h1 class="ff-sr-only">AI 分析师对话</h1>

    <!-- 左：会话列表（桌面常驻，移动端隐藏） -->
    <aside class="an__sessions">
      <SessionList
        :sessions="store.sessions"
        :active-id="activeSessionId"
        @select="selectSession"
        @create="newSession"
        @rename="onRename"
        @delete="onDelete"
      />
    </aside>

    <!-- 中：对话 -->
    <section class="an__chat">
      <div ref="chatScrollEl" class="an__scroll">
        <div v-if="loadingMsgs" class="an__loading"><span class="an__spinner"></span> 正在加载会话…</div>

        <template v-else-if="chatLog.length">
          <div v-for="(m, i) in chatLog" :key="i" class="an__msg" :class="`an__msg--${m.role}`">
            <div class="an__avatar" :class="`an__avatar--${m.role}`">
              <AppIcon v-if="m.role === 'ai'" name="sparkles" size="xs" />
              <span v-else>我</span>
            </div>
            <div class="an__bubble" :class="[m.pending && 'an__bubble--pending', m.error && 'an__bubble--error', m.stopped && 'an__bubble--stopped']">
              <template v-if="m.pending">
                <AppIcon name="sparkles" size="sm" class="an__spin" />
                <span class="an__typing">AI 正在思考…</span>
                <span class="an__dots"><span /><span /><span /></span>
              </template>
              <!-- 用户消息：纯文本白字，避免 Markdown 深色文字与深底气泡冲突 -->
              <span v-else-if="m.role === 'user'" class="an__bubble-text">{{ m.text }}</span>
              <MarkdownView v-else :content="m.text" compact />
            </div>
          </div>
        </template>

        <div v-else class="an__empty">
          <div class="an__empty-ic"><AppIcon name="chatter" size="xl" /></div>
          <p class="an__empty-title">向 FinFeed 的 AI 提问市场 / 新闻相关问题</p>
          <p class="an__empty-sub">支持 @ 标的与引用报告 · 会话自动保存</p>
          <div class="an__sug">
            <button v-for="s in suggestions" :key="s" class="an__sug-btn" @click="chatInput = s; sendChat()">{{ s }}</button>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="an__input-wrap">
        <!-- @ 候选 -->
        <div v-if="atCandidates.length" class="an__atbox">
          <div v-for="s in atCandidates" :key="s.code || s.name" class="an__at-item" @mousedown.prevent="pickStock(s)">
            <AppIcon name="target" size="sm" />
            <span class="an__at-name">{{ s.name }}</span>
            <span class="an__at-code">{{ s.code }}</span>
          </div>
        </div>
        <!-- 引用报告提示 -->
        <div v-if="store.contextReport" class="an__ctxref">
          <AppIcon name="file-text" size="xs" />
          已引用：{{ store.contextReport.title }}
          <button class="an__ctxref-x" @click="store.setContextReport(null)"><AppIcon name="x" size="xs" /></button>
        </div>
        <div class="an__chips">
          <button class="an__chip" @click="chatInput = '/复盘 '">/复盘</button>
          <button class="an__chip" @click="chatInput = '/解读 '">/解读</button>
          <button class="an__chip" @click="chatInput += '@'">@ 标的</button>
        </div>
        <div class="an__input">
          <input
            v-model="chatInput"
            class="an__field"
            placeholder="输入问题…（Enter 发送 / Shift+Enter 换行）"
            :disabled="sending"
            @input="onInput"
            @keydown.enter.exact.prevent="onChatEnter"
          />
          <button v-if="!sending" class="an__send" :disabled="!chatInput.trim()" @click="sendChat">
            <AppIcon name="send" size="md" />
          </button>
          <button v-else class="an__send an__send--stop" @click="stopChat">
            <AppIcon name="x" size="md" />
          </button>
        </div>
      </div>
    </section>

    <!-- 右：上下文（桌面展示，移动端抽屉） -->
    <aside class="an__ctx">
      <ContextPanel
        :stock="store.contextStock"
        :report="store.contextReport"
        :window-hours="24"
        @clear="store.clearContext()"
      />
    </aside>

    <!-- 移动端上下文按钮与浮层 -->
    <button v-if="store.contextStock || store.contextReport" class="an__ctx-fab" @click="showCtxMobile = true" title="上下文">
      <AppIcon name="columns" size="md" />
    </button>
    <Transition name="an-fade">
      <div v-if="showCtxMobile" class="an__ctx-mobile" @click.self="showCtxMobile = false">
        <div class="an__ctx-mobile-panel">
          <button class="an__ctx-mobile-x" @click="showCtxMobile = false"><AppIcon name="x" size="sm" /></button>
          <ContextPanel
            :stock="store.contextStock"
            :report="store.contextReport"
            :window-hours="24"
            @clear="store.clearContext()"
          />
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.an { display: flex; gap: 14px; height: calc(100vh - 210px); min-height: 480px; }
.an__sessions { width: 220px; flex-shrink: 0; background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; padding: 12px; }
.an__chat { flex: 1; min-width: 0; background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; display: flex; flex-direction: column; overflow: hidden; }
.an__scroll { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.an__loading { text-align: center; color: var(--ff-text-3); font-size: 13px; padding: 30px; display: flex; align-items: center; justify-content: center; gap: 8px; }
.an__spinner { width: 14px; height: 14px; border: 2px solid var(--ff-border); border-top-color: var(--ff-brand); border-radius: 50%; animation: an-rot 0.8s linear infinite; }
@keyframes an-rot { to { transform: rotate(360deg); } }
.an__msg { display: flex; align-items: flex-start; gap: 9px; max-width: 100%; }
.an__msg--user { flex-direction: row-reverse; }
.an__avatar { width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; flex-shrink: 0; }
.an__avatar--ai { background: var(--ff-bg-brand-subtle); color: var(--ff-brand); }
.an__avatar--user { background: var(--ff-brand); color: var(--ff-bg-surface); }
.an__bubble { max-width: 78%; padding: 10px 14px; border-radius: 4px 12px 12px 12px; font-size: 13.5px; line-height: 1.65; word-break: break-word; }
.an__msg--user .an__bubble { background: var(--ff-brand); color: var(--ff-bg-surface); border-radius: 12px 4px 12px 12px; }
.an__bubble-text { white-space: pre-wrap; color: var(--ff-bg-surface); font-weight: 500; font-size: 13.5px; line-height: 1.65; }
.an__msg--ai .an__bubble { background: var(--ff-bg-subtle); color: var(--ff-text-primary); border: 1px solid var(--ff-border); }
.an__bubble--pending { background: var(--ff-bg-brand-subtle); border: 1px dashed var(--ff-border-brand); display: inline-flex; align-items: center; gap: 8px; }
.an__bubble--error { background: var(--ff-down-subtle); border-color: var(--ff-up-border); color: var(--ff-up); }
.an__bubble--stopped { font-style: italic; color: var(--ff-text-2); }
.an__spin { color: var(--ff-brand); animation: an-rot 1s linear infinite; }
.an__typing { color: var(--ff-brand-dark); font-weight: 500; font-size: 13px; }
.an__dots { display: inline-flex; gap: 3px; }
.an__dots span { width: 5px; height: 5px; border-radius: 50%; background: var(--ff-brand); animation: an-bounce 1.2s infinite; }
.an__dots span:nth-child(2) { animation-delay: 0.2s; }
.an__dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes an-bounce { 0%,100% { transform: translateY(0); opacity: 0.4; } 30% { transform: translateY(-4px); opacity: 1; } }
.an__empty { margin: auto; text-align: center; padding: 20px; max-width: 420px; }
.an__empty-ic { color: var(--ff-text-3); margin-bottom: 10px; }
.an__empty-title { font-size: 15px; font-weight: 600; color: var(--ff-text-primary); }
.an__empty-sub { font-size: 12.5px; color: var(--ff-text-3); margin-top: 4px; }
.an__sug { display: flex; flex-direction: column; gap: 8px; margin-top: 18px; }
.an__sug-btn { border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 10px; padding: 10px 14px; font-size: 13px; color: var(--ff-text-2); cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); text-align: left; }
.an__sug-btn:hover { border-color: var(--ff-border-brand); color: var(--ff-brand-dark); background: var(--ff-bg-brand-subtle); }
.an__input-wrap { padding: 12px 14px; border-top: 1px solid var(--ff-border); position: relative; }
.an__chips { display: flex; gap: 6px; margin-bottom: 8px; }
.an__chip { border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 12px; padding: 3px 11px; font-size: 11.5px; font-weight: 600; color: var(--ff-text-2); cursor: pointer; font-family: var(--ff-font-mono, ui-monospace, monospace); }
.an__chip:hover { border-color: var(--ff-brand); color: var(--ff-brand); }
.an__input { display: flex; gap: 8px; align-items: center; }
.an__field { flex: 1; height: 38px; border: 1px solid var(--ff-border); border-radius: 10px; padding: 0 13px; font-size: 13.5px; outline: none; background: var(--ff-bg-surface); color: var(--ff-text-primary); transition: border-color 120ms, box-shadow 120ms; }
.an__field:focus { border-color: var(--ff-border-focus); box-shadow: 0 0 0 3px var(--ff-focus-ring); }
.an__field:disabled { opacity: 0.6; }
.an__send { width: 38px; height: 38px; border: none; border-radius: 10px; background: var(--ff-brand); color: var(--ff-bg-surface); display: flex; align-items: center; justify-content: center; cursor: pointer; transition: background 120ms; flex-shrink: 0; }
.an__send:hover { background: var(--ff-brand-dark); }
.an__send:disabled { opacity: 0.4; cursor: not-allowed; }
.an__send--stop { background: var(--ff-up); }
.an__ctx { width: 230px; flex-shrink: 0; background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; padding: 14px; overflow-y: auto; }
.an__atbox { position: absolute; bottom: calc(100% - 8px); left: 14px; right: 14px; background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 10px; box-shadow: 0 8px 24px rgba(16, 40, 30, 0.14); padding: 6px; z-index: 20; max-height: 200px; overflow-y: auto; }
.an__at-item { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-radius: 7px; cursor: pointer; font-size: 13px; }
.an__at-item:hover { background: var(--ff-bg-brand-subtle); }
.an__at-name { font-weight: 600; color: var(--ff-text-primary); }
.an__at-code { font-size: 11px; color: var(--ff-text-3); font-family: var(--ff-font-mono, ui-monospace, monospace); }
.an__ctxref { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ff-brand-dark); background: var(--ff-bg-brand-subtle); border: 1px solid var(--ff-border-brand); border-radius: 8px; padding: 4px 9px; margin-bottom: 8px; max-width: 100%; }
.an__ctxref-x { border: none; background: none; color: var(--ff-brand-dark); cursor: pointer; display: inline-flex; padding: 0; }
.an__ctx-fab { display: none; }
.an__ctx-mobile { position: fixed; inset: 0; z-index: 60; background: rgba(15, 25, 20, 0.35); display: flex; justify-content: flex-end; }
.an__ctx-mobile-panel { width: 280px; max-width: 85vw; height: 100%; background: var(--ff-bg-surface); padding: 40px 16px 16px; overflow-y: auto; box-shadow: -8px 0 24px rgba(10, 30, 22, 0.15); position: relative; }
.an__ctx-mobile-x { position: absolute; top: 12px; right: 12px; border: none; background: var(--ff-bg-subtle); border-radius: 8px; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; color: var(--ff-text-2); cursor: pointer; }
.an-fade-enter-active, .an-fade-leave-active { transition: opacity 180ms; }
.an-fade-enter-from, .an-fade-leave-to { opacity: 0; }

@media (max-width: 1100px) {
  .an__ctx { display: none; }
  .an__ctx-fab { display: flex; position: fixed; right: 18px; bottom: 90px; width: 42px; height: 42px; border-radius: 50%; background: var(--ff-brand); color: var(--ff-bg-surface); border: none; box-shadow: 0 6px 18px rgba(37, 99, 235, 0.35); align-items: center; justify-content: center; z-index: 30; }
}
@media (max-width: 768px) {
  .an { height: calc(100vh - 180px); }
  .an__sessions { display: none; }
  .an__bubble { max-width: 88%; }
}
</style>
