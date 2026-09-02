<script setup>
/**
 * ContextPanel — 分析师右栏上下文面板
 * 实时展示当前对话的上下文：@标的卡片、引用报告、数据快照。
 */
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  stock: { type: Object, default: null },
  report: { type: Object, default: null },
  windowHours: { type: Number, default: 24 },
})
const emit = defineEmits(['clear'])

const hasAny = computed(() => !!(props.stock || props.report))

function fmtChange(v) {
  if (v == null) return ''
  const n = Number(v)
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}
function tone(v) {
  const n = Number(v || 0)
  return n > 0 ? 'up' : n < 0 ? 'down' : 'flat'
}
</script>

<template>
  <div class="cp">
    <div class="cp__head">
      <span class="cp__title">上下文</span>
      <button v-if="hasAny" class="cp__clear" title="清空上下文" @click="emit('clear')">
        <AppIcon name="x" size="xs" /> 清空
      </button>
    </div>

    <div v-if="!hasAny" class="cp__empty">
      <AppIcon name="info" size="md" />
      <p>在输入框中使用 <code>@标的</code> 或「引用报告」添加分析上下文，回答将基于这些材料。</p>
    </div>

    <div v-if="stock" class="cp__card cp__stock">
      <div class="cp__label">标的</div>
      <div class="cp__row">
        <div class="cp__name">{{ stock.name || stock.code || '' }}</div>
        <div class="cp__chip" :class="tone(stock.change)">{{ fmtChange(stock.change) }}</div>
      </div>
      <div v-if="stock.code" class="cp__sub">{{ stock.code }} · {{ stock.market || stock.sector || '—' }}</div>
      <div v-if="stock.price" class="cp__price">{{ stock.price }}</div>
      <div v-if="stock.flags && stock.flags.length" class="cp__flags">
        <span v-for="f in stock.flags" :key="f" class="cp__flag">{{ f }}</span>
      </div>
    </div>

    <div v-if="report" class="cp__card cp__report">
      <div class="cp__label">引用报告</div>
      <div class="cp__rtitle">{{ report.title || '报告 #' + report.id }}</div>
      <div v-if="report.section" class="cp__sub">章节：{{ report.section }}</div>
      <div class="cp__sub">{{ report.created_at || '' }}</div>
    </div>

    <div v-if="hasAny" class="cp__card cp__meta">
      <div class="cp__label">数据快照</div>
      <div class="cp__row"><span>时间窗口</span><span>{{ windowHours }} 小时</span></div>
    </div>
  </div>
</template>

<style scoped>
.cp { display: flex; flex-direction: column; gap: 10px; }
.cp__head { display: flex; align-items: center; justify-content: space-between; }
.cp__title { font-size: var(--ff-fs-caption); font-weight: 700; color: var(--ff-text-primary); }
.cp__clear {
  display: inline-flex; align-items: center; gap: 3px; border: none; background: none;
  font-size: var(--ff-fs-xs); color: var(--ff-text-3); cursor: pointer; padding: 2px 4px; border-radius: 5px;
}
.cp__clear:hover { color: var(--ff-up); }
.cp__empty { text-align: center; color: var(--ff-text-3); font-size: var(--ff-fs-xs); padding: 18px 6px; line-height: 1.7; }
.cp__empty code { font-size: var(--ff-fs-xs); background: var(--ff-bg-subtle); padding: 1px 5px; border-radius: 4px; }
.cp__card { border: 1px dashed var(--ff-border); background: var(--ff-bg-surface); border-radius: 10px; padding: 10px 12px; }
.cp__label { font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-text-3); letter-spacing: .06em; margin-bottom: 6px; }
.cp__row { display: flex; align-items: center; justify-content: space-between; gap: 8px; font-size: var(--ff-fs-caption); }
.cp__name { font-weight: 700; font-size: var(--ff-fs-body-sm); }
.cp__chip { font-size: var(--ff-fs-xs); font-weight: 600; padding: 1px 8px; border-radius: 10px; }
.cp__chip.up { color: var(--ff-text-up); background: var(--ff-up-subtle); }
.cp__chip.down { color: var(--ff-text-down); background: var(--ff-down-subtle); }
.cp__chip.flat { color: var(--ff-text-3); background: var(--ff-bg-subtle); }
.cp__sub { font-size: var(--ff-fs-xs); color: var(--ff-text-3); margin-top: 3px; }
.cp__price { font-family: var(--ff-font-mono, ui-monospace, monospace); font-size: var(--ff-fs-data-lg); font-weight: 700; margin-top: 4px; }
.cp__flags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
.cp__flag { font-size: var(--ff-fs-xs); font-weight: 600; background: var(--ff-bg-subtle); color: var(--ff-text-secondary); padding: 2px 8px; border-radius: 8px; }
.cp__rtitle { font-size: var(--ff-fs-caption); font-weight: 600; line-height: 1.45; }
</style>
