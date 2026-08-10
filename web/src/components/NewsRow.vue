<script setup>
import { computed } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'

const props = defineProps({
  item: { type: Object, required: true },
})

const store = useAppStore()

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

/* 时间：去掉秒 */
const timeText = computed(() => {
  const t = props.item.publish_time || ''
  return t.length >= 16 ? t.slice(0, 16) : t
})

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
        <a :href="item.url" target="_blank" rel="noopener" @click.stop="markRead">
          {{ item.title }}
        </a>
        <AppBadge v-if="isNew" text="NEW" variant="brand" class="ff-newsrow__new" />
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

.ff-newsrow__title a {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--ff-text-primary);
  text-decoration: none;
  font-size: var(--ff-fs-body-lg);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ff-newsrow__title a:hover {
  color: var(--ff-text-brand);
}

.ff-newsrow__sent {
  flex-shrink: 0;
}

.ff-newsrow__new {
  flex-shrink: 0;
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
</style>
