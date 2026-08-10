<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'
import AppInput from '../ui/AppInput.vue'
import AppDateRange from '../ui/AppDateRange.vue'
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

// 单一日期区间选择器 ↔ local.start / local.end 映射
const range = computed({
  get: () => ({ start: local.value.start || '', end: local.value.end || '' }),
  set: (v) => {
    local.value.start = v.start || ''
    local.value.end = v.end || ''
    emitChange()
  },
})

const exportOpen = ref(false)
const exportRoot = ref(null)

const exportFormats = [
  { k: 'json', label: 'JSON', desc: '结构化数据，便于二次处理', icon: 'file-json', color: 'var(--ff-brand)' },
  { k: 'csv', label: 'CSV', desc: '表格软件通用格式', icon: 'file-csv', color: 'var(--ff-accent-teal)' },
  { k: 'md', label: 'Markdown', desc: '适合阅读与文档归档', icon: 'file-md', color: 'var(--ff-accent-violet)' },
]

function toggleExport() {
  exportOpen.value = !exportOpen.value
}
function closeExport() {
  exportOpen.value = false
}
function onDocClick(e) {
  if (!exportRoot.value) return
  if (!exportRoot.value.contains(e.target)) closeExport()
}
function onEsc(e) {
  if (e.key === 'Escape') closeExport()
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onEsc)
})
onUnmounted(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onEsc)
})

async function exportAs(fmt) {
  closeExport()
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
      <AppDateRange
        v-model="range"
        class="ff-filterbar__daterange"
        @change="emitChange"
      />
      <div ref="exportRoot" class="ff-export">
        <AppButton
          variant="secondary"
          size="sm"
          icon="download"
          icon-right="chevron-down"
          :class="{ 'is-open': exportOpen }"
          aria-haspopup="menu"
          :aria-expanded="exportOpen"
          @click="toggleExport"
        >
          导出
        </AppButton>
        <div v-if="exportOpen" class="ff-menu ff-menu--bottom ff-export__menu" role="menu">
          <button
            v-for="f in exportFormats"
            :key="f.k"
            type="button"
            class="ff-menu__item"
            role="menuitem"
            @click="exportAs(f.k)"
          >
            <AppIcon :name="f.icon" size="sm" :color="f.color" class="ff-export__icon" />
            <span class="ff-menu__item-text">
              <span class="ff-export__label">{{ f.label }}</span>
              <span class="ff-export__desc">{{ f.desc }}</span>
            </span>
          </button>
        </div>
      </div>
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
      <div class="ff-filterbar__chips">
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
  /* 来源行整体不换行：标签与首个 chip 始终同行 */
  flex-wrap: nowrap;
}

/* 来源标签容器：完整展示全部标签，超宽时在容器内自动换行 */
.ff-filterbar__chips {
  display: flex;
  flex: 1 1 0;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ff-space-2);
  min-width: 0;
}
/* chip 自身不压缩；标签不压缩，避免被挤到下一行 */
.ff-filterbar__chips .ff-chip {
  flex-shrink: 0;
}
.ff-filterbar__row--wrap .ff-filterbar__label {
  flex-shrink: 0;
}

/* 来源行：胶囊样式美化 */
.ff-filterbar__row--wrap .ff-chip {
  height: 28px;
  padding: 0 var(--ff-space-3);
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-medium);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  border: 1px solid var(--ff-border);
  letter-spacing: var(--ff-ls-normal);
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    color var(--ff-dur-fast) var(--ff-ease-standard),
    transform var(--ff-dur-instant) var(--ff-ease-standard);
}
.ff-filterbar__row--wrap .ff-chip:hover {
  background: var(--ff-bg-hover);
  border-color: var(--ff-border-strong);
  color: var(--ff-text-primary);
}
.ff-filterbar__row--wrap .ff-chip:active {
  transform: scale(0.97);
}
.ff-filterbar__row--wrap .ff-chip--active {
  background: var(--ff-brand);
  border-color: var(--ff-brand);
  color: var(--ff-brand-fg);
  font-weight: var(--ff-fw-semibold);
  box-shadow: var(--ff-shadow-xs);
}
.ff-filterbar__row--wrap .ff-chip--active:hover {
  background: var(--ff-brand-hover);
  border-color: var(--ff-brand-hover);
  color: var(--ff-brand-fg);
}

.ff-filterbar__search {
  flex: 1 1 240px;
  min-width: 200px;
}

.ff-filterbar__daterange {
  flex: 0 0 auto;
}

.ff-filterbar__label {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-1);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  font-weight: 600;
  /* 由父级 gap 控制标签与首个 chip 的间距，避免与换行后的对齐错位 */
}

.ff-export {
  position: relative;
  display: inline-flex;
}
.ff-export .is-open {
  background: var(--ff-bg-active);
  border-color: var(--ff-border-strong);
}
.ff-export__menu {
  top: calc(100% + 6px);
  right: 0;
  left: auto;
  min-width: 240px;
  padding: var(--ff-space-1);
}
.ff-export__icon {
  color: var(--ff-text-tertiary);
  flex-shrink: 0;
}
.ff-export__label {
  display: block;
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-primary);
  line-height: var(--ff-lh-snug);
}
.ff-export__desc {
  display: block;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  margin-top: 2px;
  line-height: var(--ff-lh-snug);
}
.ff-export__menu .ff-menu__item {
  align-items: flex-start;
  padding: var(--ff-space-2) var(--ff-space-2-5);
  min-height: 44px;
}

@media (max-width: 767px) {
  .ff-filterbar__daterange {
    width: 100%;
  }
  .ff-filterbar__daterange .ff-daterange__trigger {
    width: 100%;
  }
}
</style>
