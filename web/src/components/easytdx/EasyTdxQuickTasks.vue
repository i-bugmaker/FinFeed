<script setup>
import AppIcon from '../../ui/AppIcon.vue'

defineProps({
  hasStock: { type: Boolean, default: false },
})
const emit = defineEmits(['run'])

// 快捷任务：按真实使用场景预置，点击即执行
const TASKS = [
  { id: 'kline', label: '个股K线', desc: '日K蜡烛图', icon: 'bar-chart', func: 'mac_stock_kline', needsStock: true, params: { period: 'DAILY', count: 200, adjust: 'QFQ' } },
  { id: 'quote', label: '实时报价', desc: '现价 / 涨跌 / 量额', icon: 'trending-up', func: 'mac_stock_quotes', needsStock: true, params: { stocks: '' } },
  { id: 'tick', label: '当日分时', desc: '分笔价格走势', icon: 'activity', func: 'mac_tick_chart', needsStock: true, params: {} },
  { id: 'trades', label: '逐笔成交', desc: '最近成交明细', icon: 'list', func: 'mac_transactions', needsStock: true, params: { count: 500 } },
  { id: 'capital', label: '资金流向', desc: '主力 / 大单净流入', icon: 'coins', func: 'mac_capital_flow', needsStock: true, params: {} },
  { id: 'finance', label: '财务数据', desc: '每股收益 / 净资产', icon: 'file-text', func: 'finance_info', needsStock: true, params: {} },
  { id: 'xdxr', label: '除权除息', desc: '分红送转记录', icon: 'calendar', func: 'xdxr_info', needsStock: true, params: {} },
  { id: 'announce', label: '公司公告', desc: '巨潮最新公告', icon: 'book', func: 'cninfo_announcements', needsStock: true, params: { count: 20 } },
  { id: 'chanlun', label: '缠论分析', desc: '笔 / 段 / 中枢 / 买卖点', icon: 'candles', func: 'chanlun_analyze', needsStock: true, params: { period: 'DAILY', count: 300, adjust: 'QFQ' } },
  { id: 'backtest', label: '策略回测', desc: '双均线回测资金曲线', icon: 'cpu', func: 'backtest_run', needsStock: true, params: { period: 'DAILY', count: 500, adjust: 'QFQ', strategy: 'ma_cross', cash: 100000, fast: 5, slow: 20 } },
  { id: 'unusual', label: '异动监控', desc: '全市场异动扫描', icon: 'activity', func: 'mac_unusual', needsStock: false, params: { market: 'SH', count: 100 } },
  { id: 'board', label: '板块涨幅榜', desc: '行业板块排行', icon: 'layers', func: 'mac_board_ranking', needsStock: false, params: { board_type: 'HY', top_n: 30 } },
]

function run(task) {
  emit('run', task)
}
</script>

<template>
  <div class="etdx-tasks">
    <button
      v-for="t in TASKS"
      :key="t.id"
      type="button"
      class="etdx-tasks__card"
      @click="run(t)"
    >
      <span class="etdx-tasks__icon"><AppIcon :name="t.icon" size="md" /></span>
      <span class="etdx-tasks__meta">
        <span class="etdx-tasks__label">
          {{ t.label }}
          <span v-if="t.needsStock && !hasStock" class="etdx-tasks__need">需标</span>
        </span>
        <span class="etdx-tasks__desc">{{ t.desc }}</span>
      </span>
      <AppIcon name="chevron-right" size="xs" class="etdx-tasks__arrow" />
    </button>
  </div>
</template>

<style scoped>
.etdx-tasks {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--ff-space-3);
}
.etdx-tasks__card {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  cursor: pointer;
  text-align: left;
  transition:
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    box-shadow var(--ff-dur-fast) var(--ff-ease-standard),
    transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.etdx-tasks__card:hover {
  border-color: var(--ff-border-brand);
  box-shadow: var(--ff-shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.08));
  transform: translateY(-1px);
}
.etdx-tasks__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
}
.etdx-tasks__meta {
  flex: 1;
  min-width: 0;
}
.etdx-tasks__label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-primary);
}
.etdx-tasks__need {
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  color: var(--ff-text-warning);
  border: 1px solid var(--ff-border-warning);
  border-radius: var(--ff-radius-pill);
  padding: 0 6px;
}
.etdx-tasks__desc {
  display: block;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.etdx-tasks__arrow {
  color: var(--ff-icon-muted);
  flex-shrink: 0;
}
</style>
