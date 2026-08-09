<script setup>
import { computed } from 'vue'
import { useAppStore } from '../store/app'
import { api } from '../api/client'

const props = defineProps({
  item: { type: Object, required: true },
  mode: { type: String, default: 'news' }, // 'news' | 'sentiment'
})
const store = useAppStore()

const sentClass = computed(() => {
  const s = (props.item.sentiment || '').toLowerCase()
  if (s === 'positive') return 'sent-positive'
  if (s === 'negative') return 'sent-negative'
  return 'sent-neutral'
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
  <article class="news card" :class="{ unread: !item.is_read }" @click="api.markRead(item.id, true).catch(() => {})">
    <div class="main">
      <div class="head">
        <span v-if="mode === 'sentiment'" class="chip" :class="sentClass">{{ sentLabel }}</span>
        <span v-if="importance >= 7" class="imp" title="重要性">🔥 {{ importance.toFixed(1) }}</span>
        <span class="src-tag">{{ item.source }}</span>
        <span class="time text-3">{{ item.publish_time || '' }}</span>
      </div>
      <a class="title" :href="item.url" target="_blank" rel="noopener" @click.stop>{{ item.title }}</a>
      <p v-if="item.intro" class="intro text-2">{{ item.intro }}</p>
      <div class="meta">
        <span v-for="k in item.keywords?.slice(0, 5)" :key="k" class="tag">#{{ k }}</span>
        <span v-for="s in item.stocks?.slice(0, 6)" :key="s" class="stock">{{ s }}</span>
      </div>
    </div>
    <button class="fav" :class="{ active: item.is_favorite }" @click.stop="toggleFav" :title="item.is_favorite ? '取消收藏' : '收藏'">
      {{ item.is_favorite ? '★' : '☆' }}
    </button>
  </article>
</template>

<style scoped>
.news {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  transition: 0.15s;
}
.news:hover {
  box-shadow: var(--shadow-md);
  border-color: var(--border-strong);
}
.news.unread {
  border-left: 3px solid var(--primary);
}
.main {
  flex: 1;
  min-width: 0;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.src-tag {
  font-size: var(--fs-xs);
  color: var(--text-2);
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  padding: 2px 9px;
  border-radius: var(--r-pill);
  font-weight: 500;
}
.time {
  font-size: var(--fs-xs);
  margin-left: auto;
}
.imp {
  font-size: var(--fs-xs);
  color: var(--up);
  font-weight: 600;
}
.title {
  display: block;
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-1);
  line-height: 1.45;
}
.title:hover {
  color: var(--primary);
}
.intro {
  margin-top: 6px;
  font-size: var(--fs-sm);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  margin-top: 10px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.tag {
  font-size: var(--fs-xs);
  color: var(--text-2);
  background: var(--bg-surface-2);
  padding: 2px 8px;
  border-radius: var(--r-pill);
}
.stock {
  font-size: var(--fs-xs);
  color: var(--primary);
  background: var(--primary-subtle);
  padding: 2px 8px;
  border-radius: var(--r-pill);
  font-weight: 500;
}
.fav {
  background: none;
  border: none;
  font-size: 22px;
  color: var(--text-3);
  padding: 4px;
  line-height: 1;
  flex-shrink: 0;
}
.fav:hover {
  color: var(--star);
  background: var(--star-subtle);
  border-radius: var(--r-sm);
}
.fav.active {
  color: var(--star);
}
</style>
