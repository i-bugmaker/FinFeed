<script setup>
import { computed } from 'vue'
import { api } from '../api/client'
import { useAppStore } from '../store/app'

const props = defineProps({
  item: { type: Object, required: true },
})

const store = useAppStore()

/* 来源名 -> 稳定颜色（哈希），复刻改动前的彩色来源标签 */
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

/* 重要性分级（文字 + 配色），与改动前一致 */
const imp = computed(() => {
  const v = props.item.importance ?? 0
  if (v >= 8.0) return { cls: 'imp-vh', label: '极重要' }
  if (v >= 6.5) return { cls: 'imp-h', label: '重要' }
  if (v >= 5.0) return { cls: 'imp-m', label: '一般' }
  if (v >= 3.0) return { cls: 'imp-l', label: '较低' }
  return { cls: 'imp-vl', label: '低' }
})

/* 时间：去掉秒，保持 YYYY-MM-DD HH:MM */
const timeText = computed(() => {
  const t = props.item.publish_time || ''
  return t.length >= 16 ? t.slice(0, 16) : t
})

/* 情绪小圆点 */
const sentDot = computed(() => {
  const s = (props.item.sentiment || '').toLowerCase()
  if (s === 'positive') return 'pos'
  if (s === 'negative') return 'neg'
  return 'neu'
})

/* 新消息徽标：SSE 推送且尚未并入列表的条目 */
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
  <tr class="nt-row" :class="{ 'nt-unread': !item.is_read }" @click="markRead">
    <td class="nt-fav">
      <button
        class="nt-fav-btn"
        :class="{ active: item.is_favorite }"
        :title="item.is_favorite ? '取消收藏' : '收藏'"
        @click.stop="toggleFav"
      >
        {{ item.is_favorite ? '★' : '☆' }}
      </button>
    </td>
    <td class="nt-imp">
      <span class="nt-imp-badge" :class="imp.cls">{{ imp.label }}</span>
    </td>
    <td class="nt-time">{{ timeText }}</td>
    <td class="nt-source">
      <span class="nt-src-tag" :style="srcStyle">{{ item.source }}</span>
    </td>
    <td class="nt-title">
      <span class="nt-sent-dot" :class="sentDot"></span>
      <a :href="item.url" target="_blank" rel="noopener" @click.stop="markRead">{{ item.title }}</a>
      <span v-if="isNew" class="nt-new-badge">NEW</span>
    </td>
  </tr>
</template>
