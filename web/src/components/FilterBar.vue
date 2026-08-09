<script setup>
import { ref, watch } from 'vue'
import { api } from '../api/client'
import AppInput from '../ui/AppInput.vue'
import AppDatePicker from '../ui/AppDatePicker.vue'
import AppButton from '../ui/AppButton.vue'
import AppCheckbox from '../ui/AppCheckbox.vue'
import AppIcon from '../ui/AppIcon.vue'

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
  <div class="ff-filterbar">
    <div class="ff-filterbar__row">
      <AppInput
        v-model="local.keyword"
        class="ff-filterbar__search"
        prefix-icon="search"
        placeholder="关键词 / 股票代码…"
        clearable
        @enter="emitChange"
        @blur="emitChange"
      />
      <AppDatePicker
        v-model="local.start"
        class="ff-filterbar__date"
        placeholder="开始日期"
        @change="emitChange"
      />
      <span class="ff-filterbar__sep">~</span>
      <AppDatePicker
        v-model="local.end"
        class="ff-filterbar__date"
        placeholder="结束日期"
        @change="emitChange"
      />
      <AppButton variant="secondary" size="sm" icon="download" icon-right="chevron-down" @click="exportAs('json')">JSON</AppButton>
      <AppButton variant="secondary" size="sm" icon="download" icon-right="chevron-down" @click="exportAs('csv')">CSV</AppButton>
      <AppButton variant="secondary" size="sm" icon="download" icon-right="chevron-down" @click="exportAs('md')">MD</AppButton>
    </div>

    <div class="ff-filterbar__row">
      <span class="ff-filterbar__label">
        <AppIcon name="activity" size="xs" /> 情绪
      </span>
      <button
        v-for="s in sentiments"
        :key="s.k"
        type="button"
        class="ff-chip"
        :class="[
          `ff-chip--${s.k === 'positive' ? 'up' : s.k === 'negative' ? 'down' : 'default'}`,
          (local.sentiment || 'all') === s.k && 'ff-chip--active',
        ]"
        @click="setSentiment(s.k)"
      >
        {{ s.label }}
      </button>
      <AppCheckbox
        v-if="showFav"
        v-model="local.favorites"
        label="仅收藏"
        @change="emitChange"
      />
    </div>

    <div class="ff-filterbar__row ff-filterbar__row--wrap">
      <span class="ff-filterbar__label">
        <AppIcon name="layers" size="xs" /> 来源
      </span>
      <button
        type="button"
        class="ff-chip"
        :class="(!local.source || local.source === 'all') && 'ff-chip--active'"
        @click="setSource('all')"
      >
        全部
      </button>
      <button
        v-for="s in sources"
        :key="s.name"
        type="button"
        class="ff-chip"
        :class="local.source === s.name && 'ff-chip--active'"
        @click="setSource(s.name)"
      >
        {{ s.name }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ff-filterbar {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  margin-bottom: var(--ff-space-5);
  padding: var(--ff-space-4);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-surface);
}

.ff-filterbar__row {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}

.ff-filterbar__row--wrap {
  gap: var(--ff-space-2);
}

.ff-filterbar__search {
  flex: 1 1 240px;
  min-width: 200px;
}

.ff-filterbar__date {
  width: 150px;
}

.ff-filterbar__sep {
  color: var(--ff-text-tertiary);
  font-weight: 500;
}

.ff-filterbar__label {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  font-size: var(--ff-fs-sm);
  color: var(--ff-text-secondary);
  font-weight: 600;
  margin-right: var(--ff-space-1);
}

@media (max-width: 767px) {
  .ff-filterbar__date {
    width: 100%;
  }
}
</style>
