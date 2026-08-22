<script setup>
// 键值卡片视图：JSON 结果渲染（长文本折叠）
import { ref, computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import { columnLabel, cellText, isLink } from './format'

const props = defineProps({
  data: { type: Object, default: () => ({}) },
  exclude: { type: Array, default: () => [] }, // 已由其他渲染器消费的键
})

const entries = computed(() =>
  Object.entries(props.data || {}).filter(([k]) => !props.exclude.includes(k)),
)

// 纯标量字典 → 展开为子行
function isPlainDict(v) {
  return (
    v !== null &&
    typeof v === 'object' &&
    !Array.isArray(v) &&
    Object.values(v).every((x) => x === null || typeof x !== 'object')
  )
}

function fmt(v, col = '') {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') {
    if (Array.isArray(v)) return v.length ? `${v.length} 项` : '空数组'
    const keys = Object.keys(v)
    return keys.length ? `${keys.length} 个字段` : '空对象'
  }
  return cellText(v, col)
}

// 长文本折叠
const EXPANDED = Symbol('expanded')
const expandedKeys = ref(new Set())
function toggleExpand(k) {
  const s = new Set(expandedKeys.value)
  if (s.has(k)) s.delete(k)
  else s.add(k)
  expandedKeys.value = s
}
function isLongText(v) {
  return typeof v === 'string' && v.length > 80
}
</script>

<template>
  <div class="etdx-kv">
    <div v-for="e in entries" :key="e.k" class="etdx-kv__card">
      <span class="etdx-kv__k" :title="e.k">{{ columnLabel(e.k) }}</span>

      <div v-if="isPlainDict(e.v)" class="etdx-kv__nested">
        <div v-for="(sv, sk) in e.v" :key="sk" class="etdx-kv__row">
          <span class="etdx-kv__k2" :title="String(sk)">{{ columnLabel(sk) }}</span>
          <span class="etdx-kv__v2">
            <a
              v-if="isLink(sv, String(sk))"
              :href="sv"
              target="_blank"
              rel="noopener"
              class="etdx-kv__link"
            >打开链接</a>
            <template v-else>{{ cellText(sv, String(sk)) }}</template>
          </span>
        </div>
      </div>

      <span v-else class="etdx-kv__v">
        <a
          v-if="isLink(e.v, e.k)"
          :href="e.v"
          target="_blank"
          rel="noopener"
          class="etdx-kv__link"
        >打开链接</a>
        <template v-else>
          <span v-if="isLongText(e.v)">
            <span v-if="expandedKeys.has(e.k)">{{ e.v }}</span>
            <span v-else class="etdx-kv__clamp">{{ e.v }}</span>
            <button type="button" class="etdx-kv__toggle" @click="toggleExpand(e.k)">
              {{ expandedKeys.has(e.k) ? '收起' : '展开全文' }}
            </button>
          </span>
          <template v-else>{{ fmt(e.v, e.k) }}</template>
        </template>
      </span>
    </div>
  </div>
</template>

<style scoped>
.etdx-kv {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: var(--ff-space-3);
}
.etdx-kv__card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--ff-space-3);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  transition: border-color var(--ff-dur-fast), box-shadow var(--ff-dur-fast);
}
.etdx-kv__card:hover {
  border-color: var(--ff-border);
  box-shadow: var(--ff-shadow-sm);
}
.etdx-kv__k {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-weight: 600;
}
.etdx-kv__v {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  font-family: var(--ff-font-mono, monospace);
  word-break: break-all;
}
.etdx-kv__clamp {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.etdx-kv__toggle {
  display: block;
  margin-top: 4px;
  border: none;
  background: transparent;
  color: var(--ff-text-brand);
  font-size: var(--ff-fs-caption);
  cursor: pointer;
  padding: 0;
}
.etdx-kv__nested {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 2px;
}
.etdx-kv__row {
  display: flex;
  justify-content: space-between;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-body-sm);
}
.etdx-kv__k2 {
  color: var(--ff-text-secondary);
  flex-shrink: 0;
}
.etdx-kv__v2 {
  color: var(--ff-text-primary);
  font-family: var(--ff-font-mono, monospace);
  word-break: break-all;
  text-align: right;
}
.etdx-kv__link {
  color: var(--ff-text-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
