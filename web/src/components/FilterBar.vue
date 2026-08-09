<script setup>
import { ref, watch } from 'vue'
import { api } from '../api/client'

const props = defineProps({
  modelValue: { type: Object, default: () => ({}) },
  sources: { type: Array, default: () => [] },
  showFav: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'change'])

const local = ref({ ...props.modelValue })
watch(
  () => props.modelValue,
  (v) => (local.value = { ...v }),
  { deep: true },
)

const sentiments = [
  { k: 'all', label: '全部' },
  { k: 'positive', label: '利好' },
  { k: 'neutral', label: '中性' },
  { k: 'negative', label: '利空' },
]

function emitChange() {
  emit('update:modelValue', { ...local.value })
  emit('change', { ...local.value })
}

function setSentiment(k) {
  local.value.sentiment = k
  emitChange()
}
function setSource(s) {
  local.value.source = s === local.value.source ? 'all' : s
  emitChange()
}

async function exportAs(fmt) {
  try {
    const res = await api.exportNews(fmt, {
      start: local.value.start || undefined,
      end: local.value.end || undefined,
      favorites: local.value.favorites ? 1 : 0,
    })
    api.downloadBlob(res, `finfeed_news.${fmt}`)
  } catch (e) {
    alert('导出失败：' + (e.message || e))
  }
}
</script>

<template>
  <div class="filterbar card">
    <div class="row">
      <div class="search">
        <span class="ico">🔍</span>
        <input
          v-model="local.keyword"
          @keyup.enter="emitChange"
          placeholder="关键词 / 股票代码…"
        />
      </div>
      <input class="date" type="date" v-model="local.start" @change="emitChange" />
      <span class="tilde">~</span>
      <input class="date" type="date" v-model="local.end" @change="emitChange" />
      <button class="btn" @click="exportAs('json')">导出 JSON</button>
      <button class="btn" @click="exportAs('csv')">导出 CSV</button>
      <button class="btn" @click="exportAs('md')">导出 MD</button>
    </div>
    <div class="row">
      <span class="lbl">情绪</span>
      <button
        v-for="s in sentiments"
        :key="s.k"
        class="chip-btn"
        :class="[s.k === 'positive' ? 'pos' : s.k === 'negative' ? 'neg' : '', { active: (local.sentiment || 'all') === s.k }]"
        @click="setSentiment(s.k)"
      >
        {{ s.label }}
      </button>
      <label v-if="showFav" class="check">
        <input type="checkbox" v-model="local.favorites" @change="emitChange" /> 仅收藏
      </label>
    </div>
    <div class="row wrap">
      <span class="lbl">来源</span>
      <button class="chip-btn" :class="{ active: !local.source || local.source === 'all' }" @click="setSource('all')">
        全部
      </button>
      <button
        v-for="s in sources"
        :key="s.name"
        class="chip-btn"
        :class="{ active: local.source === s.name }"
        @click="setSource(s.name)"
      >
        {{ s.name }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.filterbar {
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: var(--sp-5);
}
.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.row.wrap {
  gap: 8px;
}
.search {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: 8px 12px;
  flex: 1;
  min-width: 240px;
}
.search input {
  border: none;
  background: none;
  outline: none;
  font-size: var(--fs-sm);
  width: 100%;
  color: var(--text-1);
}
.date {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  border-radius: var(--r-sm);
  padding: 8px 10px;
  font-size: var(--fs-sm);
  color: var(--text-1);
}
.tilde {
  color: var(--text-3);
}
.lbl {
  font-size: var(--fs-sm);
  color: var(--text-2);
  font-weight: 600;
  margin-right: 2px;
}
.chip-btn {
  border: 1px solid var(--border);
  background: var(--bg-surface);
  color: var(--text-2);
  border-radius: var(--r-pill);
  padding: 6px 14px;
  font-size: var(--fs-sm);
  font-weight: 500;
  transition: 0.15s;
}
.chip-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}
.chip-btn.active {
  background: var(--primary);
  color: var(--primary-text);
  border-color: var(--primary);
}
.chip-btn.pos.active {
  background: var(--up);
  border-color: var(--up);
}
.chip-btn.neg.active {
  background: var(--down);
  border-color: var(--down);
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
</style>
