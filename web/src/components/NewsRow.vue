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

/* 来源名 -> 稳定颜色（哈希） */
function hashColor(str) {
  let h = 0
  for (let i = 0; i < str.length; i++) {
    h = (h << 5) - h + str.charCodeAt(i)
    h |= 0
  }
  const hue = Math.abs(h) % 360
  return `hsl(${hue}, 60%, 45%)`
}
const srcColor = computed(() => hashColor(props.item.source || '未知'))
const srcStyle = computed(() => {
  const c = srcColor.value
  return { color: c, background: c + '1a', borderColor: c + '55' }
})

/* 重要性分级 */
const imp = computed(() => {
  const v = props.item.importance ?? 0
  if (v >= 8.0) return { variant: 'danger', label: '极重要' }
  if (v >= 6.5) return { variant: 'warn', label: '重要' }
  if (v >= 5.0) return { variant: 'default', label: '一般' }
  if (v >= 3.0) return { variant: 'muted', label: '较低' }
  return { variant: 'muted', label: '低' }
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
</script>

<template>
  <tr class="ff-table__row" :class="{ 'ff-table__row--unread': !item.is_read }" @click="markRead">
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

  <!-- 详情展开行 -->
  <tr v-if="expanded" class="ff-table__row ff-newsrow__detail-row">
    <td class="ff-table__cell" colspan="5">
      <div class="ff-newsrow__detail">
        <p v-if="detailLoading" class="ff-newsrow__detail-loading">
          <AppIcon name="refresh" size="xs" spin /> 正文加载中…
        </p>
        <p v-else-if="detailContent" class="ff-newsrow__detail-intro">{{ detailContent }}</p>
        <p v-else-if="item.intro" class="ff-newsrow__detail-intro">{{ item.intro }}</p>
        <p v-else class="ff-newsrow__detail-intro ff-newsrow__detail-muted">暂无正文内容，可点击右上角「跳转原文」查看。</p>
        <div v-if="item.keywords?.length || item.stocks?.length" class="ff-newsrow__detail-tags">
          <span v-for="k in item.keywords?.slice(0, 5)" :key="k" class="ff-newsrow__detail-tag">#{{ k }}</span>
          <span v-for="s in item.stocks?.slice(0, 6)" :key="s" class="ff-newsrow__detail-stock">
            <AppIcon name="trending-up" size="xs" /> {{ s }}
          </span>
        </div>
        <div class="ff-newsrow__detail-actions">
          <a v-if="item.url" class="ff-newsrow__detail-origin" :href="item.url" target="_blank" rel="noopener">
            <AppIcon name="external-link" size="sm" /> 查看原文
          </a>
          <button class="ff-newsrow__detail-btn" @click="aiAnalyze">
            <AppIcon name="sparkles" size="sm" /> AI 分析
          </button>
        </div>
      </div>
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
  transition: transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-newsrow__headbtn.is-expanded .ff-newsrow__caret {
  transform: rotate(90deg);
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

/* ── 详情展开行 ── */
.ff-newsrow__detail {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 2px 6px 34px;
}
.ff-newsrow__detail-intro {
  font-size: var(--ff-fs-body);
  font-weight: 400;
  color: var(--ff-text-primary);
  line-height: 1.75;
  letter-spacing: 0.015em;
  white-space: pre-wrap;
  word-break: break-word;
  overflow-wrap: break-word;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  text-rendering: optimizeLegibility;
  max-width: 92ch;
}
.ff-newsrow__detail-loading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-body);
  color: var(--ff-text-tertiary);
}
.ff-newsrow__detail-muted {
  font-size: var(--ff-fs-body);
  color: var(--ff-text-tertiary);
}
.ff-newsrow__detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ff-space-2);
}
.ff-newsrow__detail-tag {
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-secondary);
  background: var(--ff-bg-subtle);
  padding: 2px 8px;
  border-radius: var(--ff-radius-pill);
}
.ff-newsrow__detail-stock {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-brand);
  background: var(--ff-bg-brand-subtle);
  font-weight: 500;
  padding: 2px 8px;
  border-radius: var(--ff-radius-pill);
}
.ff-newsrow__detail-actions {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}
.ff-newsrow__detail-origin,
.ff-newsrow__detail-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 28px;
  padding: 0 12px;
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  cursor: pointer;
  text-decoration: none;
}
.ff-newsrow__detail-origin {
  border: 1px solid var(--ff-border-strong);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
}
.ff-newsrow__detail-origin:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.ff-newsrow__detail-btn {
  border: 1px solid var(--ff-brand-border);
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-brand);
}
.ff-newsrow__detail-btn:hover {
  background: var(--ff-brand);
  color: #fff;
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
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-brand);
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
  color: #fff;
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

/* ── 移动端适配（D4）：表格行内换行保护 ── */
@media (max-width: 768px) {
  .nr__title {
    overflow-wrap: anywhere;
  }
}
</style>
