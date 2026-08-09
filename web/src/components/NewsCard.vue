<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/app'
import { api } from '../api/client'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'

const props = defineProps({
  item: { type: Object, required: true },
  mode: { type: String, default: 'news' }, // 'news' | 'sentiment'
})
const store = useAppStore()

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
  } catch (e) {
    /* ignore */
  }
}
</script>

<template>
  <article
    class="ff-newscard"
    :class="!item.is_read && 'ff-newscard--unread'"
    @click="api.markRead(item.id, true).catch(() => {})"
  >
    <div class="ff-newscard__main">
      <div class="ff-newscard__head">
        <AppBadge v-if="mode === 'sentiment'" :text="sentLabel" :variant="sentClass" />
        <span v-if="importance >= 7" class="ff-newscard__importance" title="重要性">
          <AppIcon name="flame" size="xs" tone="up" /> {{ importance.toFixed(1) }}
        </span>
        <span class="ff-newscard__source">{{ item.source }}</span>
        <span class="ff-newscard__time">{{ item.publish_time || '' }}</span>
      </div>
      <a class="ff-newscard__title" :href="item.url" target="_blank" rel="noopener" @click.stop>
        {{ item.title }}
        <AppIcon name="external-link" size="xs" class="ff-newscard__link" />
      </a>
      <p v-if="item.intro" class="ff-newscard__intro">{{ item.intro }}</p>
      <div class="ff-newscard__meta">
        <span v-for="k in item.keywords?.slice(0, 5)" :key="k" class="ff-newscard__tag">#{{ k }}</span>
        <span v-for="s in item.stocks?.slice(0, 6)" :key="s" class="ff-newscard__stock">{{ s }}</span>
      </div>
    </div>
    <button
      class="ff-newscard__fav"
      :class="item.is_favorite && 'ff-newscard__fav--active'"
      :aria-label="item.is_favorite ? '取消收藏' : '收藏'"
      @click.stop="toggleFav"
    >
      <AppIcon :name="item.is_favorite ? 'star-filled' : 'star'" size="lg" />
    </button>
  </article>
</template>

<style scoped>
.ff-newscard {
  display: flex;
  align-items: flex-start;
  gap: var(--ff-space-3);
  padding: var(--ff-space-4) var(--ff-space-5);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast);
  cursor: pointer;
}

.ff-newscard:hover {
  border-color: var(--ff-border-hover);
  box-shadow: var(--ff-shadow-sm);
}

.ff-newscard--unread {
  border-left: 3px solid var(--ff-border-brand);
}

.ff-newscard__main {
  flex: 1 1 auto;
  min-width: 0;
}

.ff-newscard__head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  margin-bottom: var(--ff-space-2);
  flex-wrap: wrap;
}

.ff-newscard__source {
  font-size: var(--ff-fs-xs);
  color: var(--ff-text-secondary);
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
</style>
