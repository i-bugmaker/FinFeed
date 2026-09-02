<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../store/app'
import { api } from '../api/client'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'

const props = defineProps({
  item: { type: Object, required: true },
  mode: { type: String, default: 'news' }, // 'news' | 'sentiment'
})
const emit = defineEmits(['fav']) // 取消收藏时通知父页（收藏列表需即时移除卡片）
const store = useAppStore()
const router = useRouter()
const copied = ref(false)

const sentClass = computed(() => {
  const s = (props.item.sentiment || '').toLowerCase()
  if (s === 'positive') return 'up'
  if (s === 'negative') return 'down'
  return 'neutral'
})
const sentLabel = computed(() => {
  const s = (props.item.sentiment || '').toLowerCase()
  if (s === 'positive') return '利好'
  if (s === 'negative') return '利空'
  return '中性'
})
const importance = computed(() => props.item.importance ?? 0)

async function toggleFav() {
  try {
    const res = await api.toggleFavorite(props.item.id)
    props.item.is_favorite = res.is_favorite
    if (!res.is_favorite) emit('fav', props.item)
  } catch (e) {
    /* ignore */
  }
}

async function copyNews() {
  const text = `${props.item.title}\n${props.item.url || ''}`
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch (e) {}
}

/* 提交当前快讯到 AI 分析 */
function aiAnalyze() {
  const q = [
    props.item.title,
    props.item.source ? `（来源：${props.item.source}）` : '',
    props.item.publish_time ? `｜${props.item.publish_time}` : '',
  ].join('')
  router.push({ path: '/ai', query: { mode: 'flash', q, news_id: props.item.id } })
}
</script>

<template>
  <article
    class="ff-newscard"
    :class="[!item.is_read && 'ff-newscard--unread', `ff-newscard--${sentClass}`]"
    @click="api.markRead(item.id, true).catch(() => {})"
  >
    <div class="ff-newscard__main">
      <div class="ff-newscard__head">
        <AppBadge :text="sentLabel" :variant="sentClass" />
        <span v-if="importance >= 7" class="ff-newscard__importance" title="热度与重要度">
          <AppIcon name="zap" size="xs" tone="warn" /> {{ importance.toFixed(1) }}
        </span>
        <span class="ff-newscard__source">{{ item.source }}</span>
        <span class="ff-newscard__time ff-num">{{ item.publish_time || '' }}</span>
      </div>

      <a class="ff-newscard__title" :href="item.url" target="_blank" rel="noopener" @click.stop="api.markRead(item.id, true).catch(() => {})">
        {{ item.title }}
        <AppIcon name="external-link" size="xs" class="ff-newscard__link" />
      </a>

      <p v-if="item.intro" class="ff-newscard__intro">{{ item.intro }}</p>

      <div class="ff-newscard__meta">
        <div class="ff-newscard__tags" v-if="item.keywords?.length || item.stocks?.length">
          <span v-for="k in item.keywords?.slice(0, 5)" :key="k" class="ff-newscard__tag">#{{ k }}</span>
          <span v-for="s in item.stocks?.slice(0, 6)" :key="s" class="ff-newscard__stock">
            <AppIcon name="trending-up" size="xs" />
            {{ s }}
          </span>
        </div>
      </div>
    </div>

    <div class="ff-newscard__actions">
      <button
        class="ff-newscard__ai"
        title="提交到 AI 分析"
        aria-label="提交到 AI 分析"
        @click.stop="aiAnalyze"
      >
        <AppIcon name="sparkles" size="sm" tone="brand" />
      </button>

      <button
        class="ff-newscard__btn"
        :title="copied ? '已复制' : '复制内容'"
        @click.stop="copyNews"
      >
        <AppIcon :name="copied ? 'check' : 'copy'" size="sm" :tone="copied ? 'down' : 'muted'" />
      </button>

      <button
        class="ff-newscard__fav"
        :class="item.is_favorite && 'ff-newscard__fav--active'"
        :aria-label="item.is_favorite ? '取消收藏' : '收藏'"
        :title="item.is_favorite ? '取消收藏' : '收藏'"
        @click.stop="toggleFav"
      >
        <AppIcon :name="item.is_favorite ? 'star-filled' : 'star'" size="md" />
      </button>
    </div>
  </article>
</template>

<style scoped>
.ff-newscard {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: var(--ff-space-3);
  padding: 16px 20px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  transition: background-color var(--ff-dur-base) var(--ff-ease-standard), border-color var(--ff-dur-base) var(--ff-ease-standard), color var(--ff-dur-base) var(--ff-ease-standard), box-shadow var(--ff-dur-base) var(--ff-ease-standard), transform var(--ff-dur-base) var(--ff-ease-standard);
  cursor: pointer;
}

.ff-newscard:hover {
  border-color: var(--ff-border-strong);
  box-shadow: var(--ff-shadow-md);
  transform: translateY(-1px);
}

.ff-newscard--unread {
  border-left: 3px solid var(--ff-brand);
}

.ff-newscard--up {
  border-left: 3px solid var(--ff-up);
}

.ff-newscard--down {
  border-left: 3px solid var(--ff-down);
}

.ff-newscard__main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.ff-newscard__head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
  font-size: var(--ff-fs-xs);
}

.ff-newscard__importance {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-family: var(--ff-font-mono);
  font-weight: 700;
  color: var(--ff-warn-text);
  background: var(--ff-warn-subtle);
  padding: 2px 6px;
  border-radius: var(--ff-radius-xs);
  border: 1px solid var(--ff-warn-border);
}

.ff-newscard__source {
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border);
  padding: 2px 9px;
  border-radius: var(--ff-radius-pill);
  font-weight: 500;
}

.ff-newscard__time {
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-tertiary);
  margin-left: auto;
}

.ff-newscard__importance {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-up);
  font-weight: 600;
}

.ff-newscard__title {
  display: inline-flex;
  align-items: baseline;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-md);
  font-weight: 600;
  color: var(--ff-text-primary);
  line-height: var(--ff-lh-snug);
  text-decoration: none;
}

.ff-newscard__title:hover {
  color: var(--ff-text-brand);
}

.ff-newscard__link {
  flex-shrink: 0;
  opacity: 0.5;
}

.ff-newscard__intro {
  margin-top: var(--ff-space-2);
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
  line-height: var(--ff-lh-normal);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.ff-newscard__meta {
  margin-top: var(--ff-space-3);
  display: flex;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}

.ff-newscard__tag,
.ff-newscard__stock {
  font-size: var(--ff-fs-xs);
  padding: 2px 8px;
  border-radius: var(--ff-radius-pill);
}

.ff-newscard__tag {
  color: var(--ff-text-secondary);
  background: var(--ff-bg-subtle);
}

.ff-newscard__stock {
  color: var(--ff-text-brand);
  background: var(--ff-bg-brand-subtle);
  font-weight: 500;
}

.ff-newscard__fav {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 34px;
  height: 34px;
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

/* AI 分析按钮：默认隐藏，卡片 hover 时显示（独立样式，不依赖 ff-newscard__btn） */
.ff-newscard__ai {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  padding: 0;
  border: none;
  border-radius: var(--ff-radius-md);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
  opacity: 0;
  transform: scale(0.85);
  transition: opacity var(--ff-dur-fast), transform var(--ff-dur-fast), background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-newscard:hover .ff-newscard__ai {
  opacity: 1;
  transform: scale(1);
}
.ff-newscard__ai:hover {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-brand);
}

/* ── 移动端适配（D4）── */
@media (max-width: 768px) {
  .ff-newscard {
    gap: 10px;
  }
  .ff-newscard__head {
    flex-wrap: wrap;
  }
  .ff-newscard__meta {
    min-width: 0;
  }
}
</style>
