<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'
import HighlightText from './HighlightText.vue'

const props = defineProps({
  item: { type: Object, required: true },
  keyword: { type: String, default: '' },
})

const expanded = ref(false)
const detailContent = ref('')
const detailLoading = ref(false)

/* 展开时按需加载正文：列表接口不携带正文，经 /api/detail 获取（后端会自动补齐并落库） */
async function toggle() {
  expanded.value = !expanded.value
  markRead()
  if (expanded.value && !detailContent.value) {
    detailLoading.value = true
    try {
      const res = await api.detail(props.item.id)
      detailContent.value = res?.news?.content || ''
    } catch (e) {
      detailContent.value = ''
    } finally {
      detailLoading.value = false
    }
  }
}

const store = useAppStore()
const router = useRouter()

/* 来源配色：从固定调色板按哈希取色。
   此前用「哈希 → 任意色相」生成随机色，饱和度和明度失控，
   五颜六色地散落在列表里是主要的视觉噪音来源。
   改为 8 色协调调色板：色相均匀分布，饱和度/明度收在统一区间。 */
const SRC_PALETTE = [
  [214, 68, 45], // 靛蓝
  [168, 50, 37], // 青绿
  [28, 72, 44],  // 橙棕
  [280, 46, 50], // 紫
  [338, 56, 46], // 玫红
  [196, 55, 39], // 天蓝
  [44, 62, 39],  // 琥珀
  [100, 40, 36], // 草绿
]
function srcPalette(str) {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = (h << 5) - h + str.charCodeAt(i)
    h |= 0
  }
  return SRC_PALETTE[Math.abs(h) % SRC_PALETTE.length]
}
const srcStyle = computed(() => {
  const [h, s, l] = srcPalette(props.item.source || '未知')
  return {
    color: `hsl(${h}, ${s}%, ${l}%)`,
    background: `hsla(${h}, ${s}%, ${l}%, 0.09)`,
    borderColor: `hsla(${h}, ${s}%, ${l}%, 0.2)`,
  }
})

/* 重要性分级
   注意：AppBadge 未定义 default/muted 变体，此前会回落到底座样式（--ff-up 实心红），
   导致「一般 / 较低 / 低」也渲染成红色告警徽标。这里统一改用已定义的语义变体。 */
const imp = computed(() => {
  const v = props.item.importance ?? 0
  if (v >= 8.0) return { variant: 'danger', label: '极重要', accent: 'var(--ff-danger)' }
  if (v >= 6.5) return { variant: 'warn', label: '重要', accent: 'var(--ff-warn)' }
  if (v >= 5.0) return { variant: 'neutral', label: '一般', accent: 'var(--ff-brand)' }
  if (v >= 3.0) return { variant: 'neutral', label: '较低', accent: 'var(--ff-text-tertiary)' }
  return { variant: 'neutral', label: '低', accent: 'var(--ff-text-tertiary)' }
})

/* 时间：精确到秒 */
const timeText = computed(() => props.item.publish_time || '')

/* 情绪 */
const sentTone = computed(() => {
  const s = (props.item.sentiment || '').toLowerCase()
  if (s === 'positive') return 'up'
  if (s === 'negative') return 'down'
  return 'neutral'
})

const sentMeta = computed(() => {
  if (sentTone.value === 'up') return { label: '利好', icon: 'trending-up' }
  if (sentTone.value === 'down') return { label: '利空', icon: 'trending-down' }
  return { label: '中性', icon: 'minus' }
})

/* 新消息徽标 */
const isNew = computed(() => store.pendingNews.some((n) => n.id === props.item.id))

async function toggleFav() {
  try {
    const res = await api.toggleFavorite(props.item.id)
    props.item.is_favorite = res.is_favorite
  } catch (e) {
    /* ignore */
  }
}
function markRead() {
  if (!props.item.is_read) api.markRead(props.item.id, true).catch(() => {})
}

/* 提交当前快讯到 AI 分析 */
function aiAnalyze() {
  const q = [
    props.item.title,
    props.item.source ? `（来源：${props.item.source}）` : '',
    props.item.publish_time ? `｜${props.item.publish_time}` : '',
  ].join('')
  router.push({ path: '/ai/analyst', query: { q } })
}

/* ── 展开动画 ────────────────────────────────────────────────
   <tr> 无法可靠地做高度过渡，因此动画施加在 <td> 内的包裹层上：
   高度 0 → scrollHeight → auto，配合透明度形成「下滑」展开。
   :css="false" 由 JS 全权驱动，避免 Vue 的 CSS 时序与测量冲突。 */
const ANIM_ENTER = 280
const ANIM_LEAVE = 200

function prefersReduced() {
  return typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
}

function settle(el, dur, done) {
  let finished = false
  const finish = (e) => {
    if (finished) return
    if (e && e.target !== el) return
    if (e && e.propertyName !== 'height') return
    finished = true
    el.removeEventListener('transitionend', finish)
    done()
  }
  if (dur === 0) return finish()
  el.addEventListener('transitionend', finish)
  // 兜底：transitionend 未触发时（元素被提前卸载等）也要放行
  setTimeout(finish, dur + 60)
}

function onEnter(el, done) {
  const dur = prefersReduced() ? 0 : ANIM_ENTER
  el.style.overflow = 'hidden'
  el.style.height = '0px'
  el.style.opacity = '0'
  void el.offsetHeight // 强制回流，锁定起始高度
  const target = el.scrollHeight
  el.style.transition = `height ${dur}ms var(--ff-ease-decelerate), opacity ${Math.round(dur * 0.7)}ms var(--ff-ease-standard)`
  el.style.height = `${target}px`
  el.style.opacity = '1'
  settle(el, dur, () => {
    el.style.height = 'auto'
    el.style.overflow = ''
    el.style.transition = ''
    el.style.opacity = ''
    done()
  })
}

function onLeave(el, done) {
  const dur = prefersReduced() ? 0 : ANIM_LEAVE
  el.style.overflow = 'hidden'
  el.style.height = `${el.scrollHeight}px`
  el.style.opacity = '1'
  void el.offsetHeight
  el.style.transition = `height ${dur}ms var(--ff-ease-accelerate), opacity ${Math.round(dur * 0.8)}ms var(--ff-ease-standard)`
  el.style.height = '0px'
  el.style.opacity = '0'
  settle(el, dur, () => {
    el.style.height = ''
    el.style.overflow = ''
    el.style.transition = ''
    el.style.opacity = ''
    done()
  })
}
</script>

<template>
  <tr
    class="ff-table__row ff-newsrow__row"
    :class="{ 'ff-newsrow__row--unread': !item.is_read, 'ff-newsrow__row--open': expanded }"
    @click="markRead"
  >
    <td class="ff-table__cell ff-table__cell--center">
      <button
        class="ff-newscard__fav"
        :class="item.is_favorite && 'ff-newscard__fav--active'"
        :aria-label="item.is_favorite ? '取消收藏' : '收藏'"
        @click.stop="toggleFav"
      >
        <AppIcon :name="item.is_favorite ? 'star-filled' : 'star'" size="md" />
      </button>
    </td>
    <td class="ff-table__cell ff-table__cell--center">
      <AppBadge :text="imp.label" :variant="imp.variant" />
    </td>
    <td class="ff-table__cell ff-table__cell--nowrap">{{ timeText }}</td>
    <td class="ff-table__cell ff-table__cell--center">
      <span class="ff-newsrow__src" :style="srcStyle">{{ item.source }}</span>
    </td>
    <td class="ff-table__cell">
      <div class="ff-newsrow__title">
        <AppIcon
          class="ff-newsrow__sent"
          :name="sentTone === 'up' ? 'arrow-up-right' : sentTone === 'down' ? 'arrow-down-right' : 'minus'"
          :tone="sentTone === 'neutral' ? 'muted' : sentTone"
          size="xs"
        />
        <button
          class="ff-newsrow__headbtn"
          :class="{ 'is-expanded': expanded }"
          :aria-expanded="expanded"
          :title="expanded ? '收起详情' : '展开详情'"
          @click="toggle"
        >
          <AppIcon :name="expanded ? 'chevron-down' : 'chevron-right'" size="xs" class="ff-newsrow__caret" />
          <HighlightText :text="item.title" :keyword="keyword" />
        </button>
        <AppBadge v-if="isNew" text="NEW" variant="brand" class="ff-newsrow__new" />
        <button
          class="ff-newsrow__ai"
          :title="`AI 分析：${item.title}`"
          aria-label="提交到 AI 分析"
          @click.stop="aiAnalyze"
        >
          <AppIcon name="sparkles" size="sm" />
        </button>
        <a
          v-if="item.url"
          class="ff-newsrow__link"
          :href="item.url"
          target="_blank"
          rel="noopener"
          title="跳转原文"
          aria-label="跳转原文"
          @click.stop
        >
          <AppIcon name="external-link" size="sm" />
        </a>
      </div>
    </td>
  </tr>

  <!-- 详情展开行：前四列留空占位，内容落在「标题」列正下方，与标题精确对齐 -->
  <tr class="ff-newsrow__detail-row">
    <td class="ff-newsrow__spacer" aria-hidden="true"></td>
    <td class="ff-newsrow__spacer" aria-hidden="true"></td>
    <td class="ff-newsrow__spacer" aria-hidden="true"></td>
    <td class="ff-newsrow__spacer" aria-hidden="true"></td>
    <td class="ff-newsrow__detail-cell">
      <Transition :css="false" @enter="onEnter" @leave="onLeave">
        <div v-if="expanded" class="nr-wrap">
          <div class="nr-panel" :style="{ '--nr-accent': imp.accent }">
            <!-- ① 正文 -->
            <div class="nr-panel__body">
              <div v-if="detailLoading" class="nr-skeleton" aria-live="polite" aria-busy="true">
                <span class="nr-skeleton__line" style="width: 100%"></span>
                <span class="nr-skeleton__line" style="width: 94%"></span>
                <span class="nr-skeleton__line" style="width: 72%"></span>
              </div>
              <p v-else-if="detailContent" class="nr-panel__text">{{ detailContent }}</p>
              <p v-else-if="item.intro" class="nr-panel__text">{{ item.intro }}</p>
              <p v-else class="nr-panel__empty">
                <AppIcon name="file-text" size="sm" />
                <span>该条快讯暂无正文，可点击下方「查看原文」获取完整信息。</span>
              </p>
            </div>

            <!-- ② 元信息 + 操作 -->
            <div class="nr-panel__foot">
              <span class="nr-sent" :class="`nr-sent--${sentTone}`">
                <AppIcon :name="sentMeta.icon" size="xs" />{{ sentMeta.label }}
              </span>
              <div class="nr-panel__actions">
                <a
                  v-if="item.url"
                  class="nr-btn"
                  :href="item.url"
                  target="_blank"
                  rel="noopener"
                >
                  <AppIcon name="external-link" size="sm" />查看原文
                </a>
                <button class="nr-btn nr-btn--primary" @click="aiAnalyze">
                  <AppIcon name="sparkles" size="sm" />AI 分析
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </td>
  </tr>
</template>

<style scoped>
.ff-newsrow__src {
  display: inline-block;
  font-size: var(--ff-fs-xs);
  padding: 2px 8px;
  border-radius: var(--ff-radius-pill);
  border: 1px solid;
  font-weight: 500;
  white-space: nowrap;
}

.ff-newsrow__title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  min-width: 0;
}

.ff-newsrow__headbtn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 1 1 auto;
  min-width: 0;
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-body-lg);
  font-weight: 600;
  line-height: 1.4;
  text-align: left;
  transition: color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-newsrow__headbtn .ff-highlight {
  display: inline;
}
.ff-newsrow__headbtn:hover {
  color: var(--ff-text-brand);
}
.ff-newsrow__headbtn.is-expanded {
  color: var(--ff-text-brand);
}
.ff-newsrow__caret {
  flex-shrink: 0;
  color: var(--ff-text-tertiary);
  transition: transform var(--ff-dur-base) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-newsrow__headbtn:hover .ff-newsrow__caret {
  color: var(--ff-text-brand);
}
.ff-newsrow__headbtn.is-expanded .ff-newsrow__caret {
  transform: rotate(90deg);
  color: var(--ff-text-brand);
}

.ff-newsrow__link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: var(--ff-radius-md);
  color: var(--ff-icon-muted);
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-newsrow__link:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-brand);
}

/* ══════════════════════════════════════════════════════════
   展开区 · 引述块（Quote Block）

   刻意不做独立卡片：在 55px 行高的紧凑表格里塞带边框、阴影、
   圆角的白卡片，形态与表格行差异过大，必然像贴上去的补丁。
   改为让正文成为标题的延续——
   · 展开行与内容行共用同一底色，形成一整条连续色带
   · 只用一条左侧竖线标记内容起点，上接标题行的展开箭头
   · 无边框 / 无阴影 / 无独立底色，层级完全靠缩进建立
   ══════════════════════════════════════════════════════════ */

/* 展开行 + 内容行同底色 = 一个连续的视觉整体 */
.ff-table tbody tr.ff-newsrow__row--open > td,
.ff-table tbody tr.ff-newsrow__detail-row > td {
  background: var(--ff-bg-subtle);
  border-bottom-color: transparent;
}
/* 压过 .ff-table--hover 的行悬停，否则连续色带会被逐行截断 */
.ff-table tbody tr.ff-newsrow__detail-row:hover > td {
  background: var(--ff-bg-subtle);
}

/* 折叠时行内无内容，兜底压成 0 高，避免残留 1px 空隙 */
.ff-newsrow__spacer,
.ff-newsrow__detail-cell {
  padding: 0 !important;
  border-bottom: 0 !important;
}

.nr-wrap {
  will-change: height; /* 高度由 JS 过渡驱动 */
}

/* 引述块本体：一条竖线 + 缩进，仅此而已 */
.nr-panel {
  /* 左外边距对齐 .ff-table__cell 的 16px 内边距 → 竖线正好落在展开箭头正下方 */
  margin: 0 0 var(--ff-space-4) var(--ff-space-4);
  /* 左内边距 18px = 标题文字缩进(caret 14 + gap 6) − 竖线宽 2 → 正文与标题文字左对齐 */
  padding: var(--ff-space-1) 0 var(--ff-space-2) 18px;
  border-left: 2px solid var(--nr-accent, var(--ff-brand));
  border-radius: 0 var(--ff-radius-sm) var(--ff-radius-sm) 0;
}

/* ① 正文 —— 比标题低一档字号，行高放宽，读作「标题的正文」 */
.nr-panel__body {
  padding-bottom: var(--ff-space-3);
}
.nr-panel__text {
  max-width: 74ch;
  margin: 0;
  font-size: 15px;
  font-weight: 400;
  line-height: 1.75;
  color: var(--ff-text-secondary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  /* 与 AI 分析结果正文（mdv）保持同一渲染观感 */
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
}
.nr-panel__empty {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin: 0;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
}

/* 加载骨架：改用呼吸式明暗，横扫式 shimmer 在浅底上过于跳眼 */
.nr-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
  padding: var(--ff-space-1) 0;
}
.nr-skeleton__line {
  height: 9px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-border-strong);
  animation: nr-pulse 1.5s var(--ff-ease-standard) infinite;
}
.nr-skeleton__line:nth-child(2) { animation-delay: 0.12s; }
.nr-skeleton__line:nth-child(3) { animation-delay: 0.24s; }
@keyframes nr-pulse {
  0%, 100% { opacity: 0.28; }
  50% { opacity: 0.68; }
}

/* ② 情绪 + 操作 */
.nr-panel__foot {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}
.nr-sent {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 24px;
  padding: 0 var(--ff-space-2-5);
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-xs);
  font-weight: 600;
  white-space: nowrap;
}
.nr-sent--up { background: var(--ff-up-subtle); color: var(--ff-up-text); }
.nr-sent--down { background: var(--ff-down-subtle); color: var(--ff-down-text); }
.nr-sent--neutral { background: var(--ff-neutral-subtle); color: var(--ff-neutral-text); }

.nr-panel__actions {
  display: flex;
  align-items: center;
  gap: var(--ff-space-1-5);
  margin-left: auto;
}
.nr-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 28px;
  padding: 0 var(--ff-space-2-5);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-surface);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-xs);
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard);
}
.nr-btn:hover {
  background: var(--ff-bg-surface);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}
.nr-btn--primary {
  border-color: transparent;
  background: var(--ff-brand-subtle);
  color: var(--ff-text-brand);
}
.nr-btn--primary:hover {
  background: var(--ff-brand);
  border-color: transparent;
  color: var(--ff-text-inverse);
}

/* 焦点可见性 */
.nr-btn:focus-visible,
.ff-newsrow__headbtn:focus-visible,
.ff-newsrow__link:focus-visible,
.ff-newsrow__ai:focus-visible,
.ff-newscard__fav:focus-visible {
  outline: 2px solid var(--ff-border-focus);
  outline-offset: 2px;
}

.ff-newsrow__sent {
  flex-shrink: 0;
}

.ff-newsrow__new {
  flex-shrink: 0;
}

/* AI 分析按钮：默认隐藏，行 hover 时显示 */
.ff-newsrow__ai {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--ff-radius-md);
  background: var(--ff-brand-subtle);
  color: var(--ff-text-brand);
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0;
  transform: scale(0.85);
  transition: opacity var(--ff-dur-fast), transform var(--ff-dur-fast), background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-table__row:hover .ff-newsrow__ai {
  opacity: 1;
  transform: scale(1);
}
.ff-newsrow__ai:hover {
  background: var(--ff-brand);
  color: var(--ff-text-inverse);
}

.ff-newscard__fav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  padding: 0;
  border: none;
  border-radius: var(--ff-radius-md);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}

.ff-newscard__fav:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-icon-warn);
}

.ff-newscard__fav--active {
  color: var(--ff-icon-warn);
}

@media (prefers-reduced-motion: reduce) {
  .nr-skeleton__line {
    animation: none;
  }
  .ff-newsrow__caret,
  .nr-btn {
    transition: none;
  }
}

@media (max-width: 768px) {
  .nr-panel {
    margin-right: var(--ff-space-3);
    padding-left: var(--ff-space-3);
  }
  .nr-panel__text {
    line-height: 1.75;
  }
  .nr-panel__foot {
    flex-wrap: wrap;
    gap: var(--ff-space-2);
  }
  .nr-panel__actions {
    width: 100%;
    margin-left: 0;
  }
  .nr-btn {
    flex: 1 1 auto;
  }
}
</style>
