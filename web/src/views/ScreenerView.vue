<script setup>
// 智能选股 · Web 视图
// 基于五维加权评分模型，实时拉取 easy-tdx 行情并展示入选候选。
import { ref, reactive, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useScreenerStore } from '../store/screener'
import AppIcon from '../ui/AppIcon.vue'
import AppButton from '../ui/AppButton.vue'
import AppBadge from '../ui/AppBadge.vue'
import AppSwitch from '../ui/AppSwitch.vue'

const store = useScreenerStore()

// 控制参数
const top = ref(50)
const technical = ref(false)
const demo = ref(false)
const expandedRows = ref(new Set())
const showMethodology = ref(false)

// 板块过滤（默认与后端一致：主板/科创板/创业板开，北交所关）
const BOARD_OPTIONS = [
  { key: 'main', label: '主板' },
  { key: 'kcb', label: '科创板' },
  { key: 'cyb', label: '创业板' },
  { key: 'bj', label: '北交所' },
]
const BOARD_LABEL = { main: '主板', kcb: '科创板', cyb: '创业板', bj: '北交所' }
const boards = reactive({ main: true, kcb: true, cyb: true, bj: false })
watch(
  () => store.config?.filters?.boards,
  (b) => {
    if (b && typeof b === 'object') {
      for (const k of Object.keys(boards)) {
        if (typeof b[k] === 'boolean') boards[k] = b[k]
      }
    }
  },
  { immediate: true },
)

const loading = computed(() => store.running)
const result = computed(() => store.task?.result)
const task = computed(() => store.task)
const errMsg = computed(() => store.errMsg)
const logs = computed(() => task.value?.logs || [])
const latestLog = computed(() => {
  if (!logs.value.length) return ''
  return logs.value[logs.value.length - 1].msg
})

const tierMeta = {
  strong: { label: '入选', variant: 'success' },
  watch: { label: '关注', variant: 'warn' },
  observe: { label: '观察', variant: 'muted' },
  none: { label: '不入选', variant: 'default' },
}

const headers = [
  { key: 'rank', label: '排名', w: '48px' },
  { key: 'code', label: '代码', w: '100px' },
  { key: 'name', label: '名称', w: '120px' },
  { key: 'board', label: '板块', w: '72px' },
  { key: 'price', label: '现价', w: '80px', align: 'right' },
  { key: 'change_pct', label: '涨跌幅', w: '80px', align: 'right' },
  { key: 'total_score', label: '综合分', w: '80px', align: 'right' },
  { key: 'tier', label: '评级', w: '72px' },
  { key: 'capital_score', label: '资金', w: '72px', align: 'right' },
  { key: 'momentum_score', label: '动量', w: '72px', align: 'right' },
  { key: 'valuation_score', label: '估值', w: '72px', align: 'right' },
  { key: 'liquidity_score', label: '量价', w: '72px', align: 'right' },
  { key: 'quality_score', label: '质量', w: '72px', align: 'right' },
]

function toggleRow(code) {
  const next = new Set(expandedRows.value)
  if (next.has(code)) next.delete(code)
  else next.add(code)
  expandedRows.value = next
}

async function onRun() {
  expandedRows.value = new Set()
  await store.run({
    top: top.value,
    technical: technical.value,
    demo: demo.value,
    boards: { ...boards },
  })
}

function fmtScore(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return v.toFixed(1)
}

function fmtPrice(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  return v.toFixed(2)
}

function fmtPct(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

function fmtAmount(v) {
  if (v === null || v === undefined || !Number.isFinite(v) || v <= 0) return '—'
  if (v >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (v >= 1e4) return `${(v / 1e4).toFixed(2)}万`
  return v.toFixed(0)
}

function chgClass(v) {
  if (v === null || v === undefined || !Number.isFinite(v)) return ''
  if (v > 0) return 'is-up'
  if (v < 0) return 'is-down'
  return ''
}

onMounted(() => {
  store.loadConfig()
  store.loadRecent()
})

onBeforeUnmount(() => {
  store.stopPolling()
})
</script>

<template>
  <div class="screener-shell">
    <!-- ═══════ 顶部控制区 ═══════ -->
    <header class="screener-top">
      <div class="screener-title">
        <span class="screener-title__mark">
          <AppIcon name="filter" size="sm" />
        </span>
        <div>
          <h1 class="screener-title__name">智能选股</h1>
          <p class="screener-title__sub">五维加权评分 · 资金面 / 动量 / 估值 / 量价 / 质量</p>
        </div>
      </div>

      <div class="screener-controls">
        <label class="screener-field">
          <span class="screener-field__label">显示前</span>
          <input
            v-model.number="top"
            type="number"
            min="10"
            max="300"
            class="screener-field__input screener-field__input--sm"
          />
          <span class="screener-field__unit">只</span>
        </label>

        <label class="screener-field screener-field--switch">
          <AppSwitch v-model="technical" />
          <span class="screener-field__label">技术面富化</span>
        </label>

        <label class="screener-field screener-field--switch">
          <AppSwitch v-model="demo" />
          <span class="screener-field__label">演示数据</span>
        </label>

        <div class="screener-board-filter">
          <span class="screener-board-filter__label">板块</span>
          <button
            v-for="b in BOARD_OPTIONS"
            :key="b.key"
            type="button"
            class="screener-board-chip"
            :class="{ 'is-on': boards[b.key] }"
            @click="boards[b.key] = !boards[b.key]"
          >
            {{ b.label }}
          </button>
        </div>

        <AppButton
          variant="primary"
          icon="play"
          :loading="loading"
          :disabled="loading"
          @click="onRun"
        >
          {{ loading ? '选股中…' : '开始选股' }}
        </AppButton>
      </div>
    </header>

    <!-- ═══════ 状态 / 进度 ═══════ -->
    <div v-if="loading || latestLog || errMsg" class="screener-status">
      <div v-if="loading" class="screener-status__progress">
        <span class="screener-status__bar">
          <span class="screener-status__fill" :style="{ width: (task?.progress || 0) + '%' }" />
        </span>
        <span class="screener-status__pct">{{ task?.progress || 0 }}%</span>
      </div>
      <span v-if="latestLog" class="screener-status__log">
        <AppIcon name="refresh" :spin="loading" size="xs" />
        {{ latestLog }}
      </span>
      <span v-if="errMsg" class="screener-status__err">
        <AppIcon name="alert-circle" size="xs" />
        {{ errMsg }}
      </span>
    </div>

    <!-- ═══════ 统计卡片区 ═══════ -->
    <div v-if="result" class="screener-stats">
      <div class="screener-stat">
        <span class="screener-stat__label">全市场</span>
        <span class="screener-stat__value">{{ result.universe_size }}</span>
      </div>
      <div class="screener-stat">
        <span class="screener-stat__label">通过过滤</span>
        <span class="screener-stat__value">{{ result.screened_size }}</span>
      </div>
      <div class="screener-stat screener-stat--strong">
        <span class="screener-stat__label">入选</span>
        <span class="screener-stat__value">{{ store.strongCount }}</span>
      </div>
      <div class="screener-stat screener-stat--watch">
        <span class="screener-stat__label">关注</span>
        <span class="screener-stat__value">{{ store.watchCount }}</span>
      </div>
      <div class="screener-stat screener-stat--observe">
        <span class="screener-stat__label">观察</span>
        <span class="screener-stat__value">{{ store.observeCount }}</span>
      </div>
      <div v-if="result.snapshot_time" class="screener-stat">
        <span class="screener-stat__label">快照时间</span>
        <span class="screener-stat__value screener-stat__value--sm">{{ result.snapshot_time }}</span>
      </div>
    </div>

    <!-- ═══════ 主体 ═══════ -->
    <div class="screener-body">
      <!-- 左侧：结果表 -->
      <section class="screener-main">
        <div class="screener-card">
          <div class="screener-card__head">
            <AppIcon name="filter" size="sm" />
            <span>评分结果</span>
            <span v-if="result" class="screener-card__count">共 {{ result.scores.length }} 只</span>
            <span class="screener-card__sp" />
            <button
              type="button"
              class="screener-card__toggle"
              @click="showMethodology = !showMethodology"
            >
              <AppIcon name="info" size="xs" />
              方法论
            </button>
          </div>

          <div class="screener-card__body screener-card__body--table">
            <div v-if="!result" class="screener-empty">
              <AppIcon name="filter" size="xl" />
              <p>点击「开始选股」运行五维加权评分模型</p>
              <p class="screener-empty__hint">首次使用建议先开启「演示数据」验证流程</p>
            </div>

            <template v-else>
              <div class="screener-table-wrap">
                <table class="screener-table">
                  <thead>
                    <tr>
                      <th
                        v-for="h in headers"
                        :key="h.key"
                        :style="{ width: h.w }"
                        :class="h.align && `is-${h.align}`"
                      >
                        {{ h.label }}
                      </th>
                      <th style="width: 40px"></th>
                    </tr>
                  </thead>
                  <tbody>
                    <template v-for="(row, idx) in result.scores" :key="row.code">
                      <tr
                        :class="[
                          'screener-row',
                          `screener-row--${row.tier}`,
                          expandedRows.has(row.code) && 'screener-row--expanded',
                        ]"
                        @click="toggleRow(row.code)"
                      >
                        <td>{{ idx + 1 }}</td>
                        <td class="screener-table__code">{{ row.code }}</td>
                        <td class="screener-table__name">{{ row.name }}</td>
                        <td>
                          <span class="screener-table__board" :class="`is-${row.board || 'main'}`">
                            {{ BOARD_LABEL[row.board] || '—' }}
                          </span>
                        </td>
                        <td class="is-right">{{ fmtPrice(row.price) }}</td>
                        <td class="is-right" :class="chgClass(row.change_pct)">
                          {{ fmtPct(row.change_pct) }}
                        </td>
                        <td class="is-right screener-table__score">{{ fmtScore(row.total_score) }}</td>
                        <td>
                          <AppBadge
                            :text="tierMeta[row.tier]?.label || row.tier"
                            :variant="tierMeta[row.tier]?.variant || 'default'"
                          />
                        </td>
                        <td class="is-right">{{ fmtScore(row.capital_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.momentum_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.valuation_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.liquidity_score) }}</td>
                        <td class="is-right">{{ fmtScore(row.quality_score) }}</td>
                        <td class="is-center">
                          <AppIcon
                            :name="expandedRows.has(row.code) ? 'chevron-up' : 'chevron-down'"
                            size="xs"
                          />
                        </td>
                      </tr>
                      <tr v-if="expandedRows.has(row.code)" class="screener-detail">
                        <td :colspan="headers.length + 1">
                          <div class="screener-detail__body">
                            <div class="screener-detail__meta">
                              <span>成交额 {{ fmtAmount(row.amount) }}</span>
                              <span>振幅 {{ fmtScore(row.amplitude) }}%</span>
                              <span>PE_TTM {{ fmtScore(row.pe_ttm) }}</span>
                              <span v-if="row.realized_vol_ann !== null && row.realized_vol_ann !== undefined">
                                年化波动 {{ fmtScore(row.realized_vol_ann) }}%
                              </span>
                              <span v-if="row.drawdown_from_high !== null && row.drawdown_from_high !== undefined">
                                距高点回撤 {{ fmtScore(row.drawdown_from_high) }}%
                              </span>
                              <AppBadge
                                v-if="row.ma_align"
                                text="均线多头排列"
                                variant="success"
                              />
                            </div>
                            <p v-if="row.rationale" class="screener-detail__text">
                              <strong>入选逻辑：</strong>{{ row.rationale }}
                            </p>
                            <div v-if="row.highlights?.length" class="screener-detail__tags">
                              <span class="screener-detail__tag-title">亮点</span>
                              <span
                                v-for="tag in row.highlights"
                                :key="tag"
                                class="screener-detail__tag screener-detail__tag--good"
                              >{{ tag }}</span>
                            </div>
                            <div v-if="row.guardrail_failures?.length" class="screener-detail__tags">
                              <span class="screener-detail__tag-title">护栏降级</span>
                              <span
                                v-for="tag in row.guardrail_failures"
                                :key="tag"
                                class="screener-detail__tag screener-detail__tag--warn"
                              >{{ tag }}</span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    </template>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </div>

        <!-- 方法论面板 -->
        <div v-if="showMethodology && store.config" class="screener-card screener-methodology">
          <div class="screener-card__head">
            <AppIcon name="info" size="sm" />
            <span>评分方法论</span>
            <span class="screener-card__sp" />
            <button type="button" class="screener-card__toggle" @click="showMethodology = false">
              <AppIcon name="x" size="xs" />
            </button>
          </div>
          <div class="screener-card__body">
            <div class="screener-methodology__content" v-html="store.config.methodology.replace(/\n/g, '<br>')" />
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.screener-shell {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  padding: var(--ff-page-pad-y) var(--ff-page-pad-x);
  overflow: hidden;
}

/* ── 顶部 ── */
.screener-top {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
  padding: var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm);
}

.screener-title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
}

.screener-title__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--ff-bg-brand);
  color: #fff;
  box-shadow: 0 2px 8px rgba(47, 125, 91, 0.25);
}

.screener-title__name {
  font-size: var(--ff-fs-h3);
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.01em;
}

.screener-title__sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

.screener-controls {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
}

.screener-field {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}

.screener-field__label {
  font-weight: 500;
  white-space: nowrap;
}

.screener-field__input {
  height: 36px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  padding: 0 10px;
  font-size: var(--ff-fs-body);
  color: var(--ff-text-primary);
  background: var(--ff-bg-surface);
  transition: border-color var(--ff-dur-fast);
}

.screener-field__input:focus {
  outline: none;
  border-color: var(--ff-border-focus);
}

.screener-field__input--sm {
  width: 64px;
  text-align: center;
}

.screener-field__unit {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
}

.screener-field--switch {
  gap: var(--ff-space-1-5);
  cursor: pointer;
}

/* ── 板块过滤 ── */
.screener-board-filter {
  display: flex;
  align-items: center;
  gap: var(--ff-space-1-5);
}

.screener-board-filter__label {
  font-size: var(--ff-fs-body-sm);
  font-weight: 500;
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}

.screener-board-chip {
  height: 26px;
  padding: 0 12px;
  border: 1px solid var(--ff-border);
  border-radius: 999px;
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  cursor: pointer;
  transition: all var(--ff-dur-fast);
  white-space: nowrap;
}

.screener-board-chip:hover {
  border-color: var(--ff-brand);
  color: var(--ff-brand);
}

.screener-board-chip.is-on {
  background: var(--ff-brand);
  border-color: var(--ff-brand);
  color: var(--ff-bg-surface);
}

/* 结果表板块徽标 */
.screener-table__board {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  border: 1px solid var(--ff-border);
  color: var(--ff-text-secondary);
  background: var(--ff-bg-muted);
  white-space: nowrap;
}

.screener-table__board.is-kcb {
  color: var(--ff-brand);
  border-color: var(--ff-border-strong);
  background: color-mix(in srgb, var(--ff-brand) 8%, transparent);
}

.screener-table__board.is-cyb {
  color: var(--ff-warn-text);
  border-color: var(--ff-border-strong);
  background: color-mix(in srgb, var(--ff-warn-text) 8%, transparent);
}

/* ── 状态条 ── */
.screener-status {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  padding: 10px var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
}

.screener-status__progress {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  width: 160px;
  flex: none;
}

.screener-status__bar {
  flex: 1;
  height: 6px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  overflow: hidden;
}

.screener-status__fill {
  height: 100%;
  border-radius: var(--ff-radius-pill);
  background: linear-gradient(90deg, var(--ff-brand), var(--ff-brand-hover));
  transition: width 0.4s var(--ff-ease-standard);
}

.screener-status__pct {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--ff-text-brand);
  min-width: 38px;
  text-align: right;
}

.screener-status__log {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ff-text-tertiary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.screener-status__err {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ff-danger-text);
  background: var(--ff-danger-subtle);
  border: 1px solid var(--ff-danger-border);
  border-radius: var(--ff-radius-md);
  padding: 4px 10px;
  margin-left: auto;
}

/* ── 统计卡 ── */
.screener-stats {
  flex: none;
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--ff-space-3);
}

.screener-stat {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1);
  padding: var(--ff-space-3) var(--ff-space-4);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
}

.screener-stat__label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

.screener-stat__value {
  font-size: var(--ff-fs-2xl);
  font-weight: 700;
  font-family: var(--ff-font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-primary);
  line-height: 1;
}

.screener-stat__value--sm {
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
}

.screener-stat--strong .screener-stat__value {
  color: var(--ff-up-text);
}
.screener-stat--watch .screener-stat__value {
  color: var(--ff-warn-text);
}
.screener-stat--observe .screener-stat__value {
  color: var(--ff-neutral-text);
}

/* ── 主体布局 ── */
.screener-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: var(--ff-space-4);
  overflow: hidden;
}

.screener-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  overflow: hidden;
}

/* ── 通用卡片 ── */
.screener-card {
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.screener-card__head {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}

.screener-card__head > svg {
  color: var(--ff-text-brand);
}

.screener-card__count {
  font-weight: 400;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-caption);
}

.screener-card__sp {
  margin-left: auto;
}

.screener-card__toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
  color: var(--ff-text-secondary);
  background: transparent;
  border: 1px solid var(--ff-border);
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}

.screener-card__toggle:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}

.screener-card__body {
  padding: var(--ff-space-3) var(--ff-space-4);
}

.screener-card__body--table {
  padding: 0;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── 空状态 ── */
.screener-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-10) var(--ff-space-4);
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body);
  text-align: center;
}

.screener-empty__hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

.screener-empty--sm {
  padding: var(--ff-space-6) var(--ff-space-4);
  font-size: var(--ff-fs-body-sm);
}

/* ── 表格 ── */
.screener-table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.screener-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ff-fs-body-sm);
}

.screener-table thead {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--ff-bg-surface);
}

.screener-table th {
  padding: 10px 8px;
  font-weight: 600;
  color: var(--ff-text-secondary);
  text-align: left;
  border-bottom: 1px solid var(--ff-border-subtle);
  white-space: nowrap;
  font-size: var(--ff-fs-caption);
}

.screener-table td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--ff-border-subtle);
  color: var(--ff-text-primary);
  white-space: nowrap;
  vertical-align: middle;
}

.screener-table th.is-right,
.screener-table td.is-right {
  text-align: right;
}

.screener-table th.is-center,
.screener-table td.is-center {
  text-align: center;
}

.screener-row {
  cursor: pointer;
  transition: background var(--ff-dur-fast);
}

.screener-row:hover {
  background: var(--ff-bg-hover);
}

.screener-row--strong {
  background: var(--ff-up-subtle);
}

.screener-row--watch {
  background: var(--ff-warn-subtle);
}

.screener-row--strong:hover,
.screener-row--watch:hover {
  filter: brightness(0.98);
}

.screener-table__code {
  font-family: var(--ff-font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-secondary);
}

.screener-table__name {
  font-weight: 600;
}

.screener-table__score {
  font-weight: 700;
  color: var(--ff-text-brand);
  font-family: var(--ff-font-mono);
  font-variant-numeric: tabular-nums;
}

.is-up {
  color: var(--ff-up-text);
}
.is-down {
  color: var(--ff-down-text);
}

/* ── 展开详情 ── */
.screener-detail td {
  padding: 0;
  border-bottom: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
}

.screener-detail__body {
  padding: var(--ff-space-3) var(--ff-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}

.screener-detail__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ff-space-2) var(--ff-space-4);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
}

.screener-detail__text {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-secondary);
  line-height: 1.6;
}

.screener-detail__text strong {
  color: var(--ff-text-primary);
}

.screener-detail__tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ff-space-2);
}

.screener-detail__tag-title {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  font-weight: 500;
}

.screener-detail__tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-caption);
  font-weight: 500;
}

.screener-detail__tag--good {
  background: var(--ff-up-subtle);
  color: var(--ff-up-text);
}

.screener-detail__tag--warn {
  background: var(--ff-warn-subtle);
  color: var(--ff-warn-text);
}

/* ── 方法论面板 ── */
.screener-methodology {
  flex: none;
  max-height: 360px;
  display: flex;
  flex-direction: column;
}

.screener-methodology .screener-card__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.screener-methodology__content {
  font-size: var(--ff-fs-body-sm);
  line-height: 1.7;
  color: var(--ff-text-secondary);
}

.screener-methodology__content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: var(--ff-space-3) 0;
}

.screener-methodology__content :deep(th),
.screener-methodology__content :deep(td) {
  padding: 6px 8px;
  border: 1px solid var(--ff-border);
  text-align: left;
  font-size: var(--ff-fs-caption);
}

.screener-methodology__content :deep(th) {
  background: var(--ff-bg-subtle);
  font-weight: 600;
}

.screener-methodology__content :deep(blockquote) {
  margin: var(--ff-space-3) 0;
  padding: var(--ff-space-3) var(--ff-space-4);
  border-left: 3px solid var(--ff-brand);
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  border-radius: 0 var(--ff-radius-md) var(--ff-radius-md) 0;
}

/* ── 响应式 ── */
@media (max-width: 1180px) {
  .screener-stats {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .screener-top {
    flex-direction: column;
    align-items: flex-start;
  }
  .screener-controls {
    flex-wrap: wrap;
  }
  .screener-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
