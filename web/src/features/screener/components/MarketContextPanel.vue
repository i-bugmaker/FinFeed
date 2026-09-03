<script setup>
// 市场环境面板（智能选股 · 短线 overlay 综合考量展示）。
// 展示五路盘面信号：大盘走势 / 涨跌停分布 / ETF 资金流向 / 大资金动向 / 龙虎榜，
// 合成「短线风险偏好分」与情绪系数，并说明 overlay 对维度权重的影响。
// 数据契约：ScreenerResult.market_context（MarketContext.to_dict() + overlay 诊断）。
import { computed } from 'vue'

const props = defineProps({
  ctx: { type: Object, default: null },
})

const c = computed(() => props.ctx || {})
const ls = computed(() => c.value.limit_stats || {})
const ov = computed(() => c.value.overlay || {})

const REGIME_CLS = (s) => (s >= 62 ? 'is-hot' : s >= 40 ? 'is-mid' : 'is-cold')

function pctCls(p) {
  const n = Number(p)
  return n > 0.001 ? 'is-up' : n < -0.001 ? 'is-down' : ''
}
function pctTxt(p) {
  const n = Number(p)
  if (!Number.isFinite(n)) return '—'
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`
}
function yv(d, i) {
  return Math.abs(Number(d?.net_yi) || 0).toFixed(2)
}
function fmtDelta(delta) {
  if (!delta || typeof delta !== 'object') return ''
  return Object.entries(delta)
    .filter(([, v]) => Math.abs(Number(v)) > 1e-4)
    .map(([d, v]) => `${d}: ${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(2)}`)
    .join(' / ')
}
const hasFlags = computed(() => {
  const f = ov.value?.delta
  return f && typeof f === 'object' && Object.keys(f).length > 0
})
</script>

<template>
  <div v-if="ctx" class="mkt">
    <!-- 缺数据提示 -->
    <div v-if="c.unavailable?.length" class="mkt-note">
      <span class="mkt-note__dot" /> 信号缺失（{{ c.unavailable.join(' / ') }}）：对应分量权重已均摊给其余信号，整体结论仍有效
    </div>

    <!-- ── 概览：风险偏好仪表 + 涨跌停温度 ── -->
    <div class="mkt-overview">
      <div class="mkt-regime">
        <div class="mkt-regime__head">
          <div>
            <div class="mkt-label">短线风险偏好</div>
            <div class="mkt-regime__score">
              {{ Number(c.regime_score ?? 50).toFixed(0) }}
              <span class="mkt-regime__unit">/ 100</span>
            </div>
          </div>
          <div class="mkt-regime__tags">
            <span class="mkt-chip" :class="REGIME_CLS(Number(c.regime_score))">{{ c.regime_label || '—' }}</span>
            <span class="mkt-chip is-plain" :title="'情绪系数：用于调节动量/题材等短线维权重，1.0=中性'">
              情绪 ×{{ Number(c.appetite ?? 1).toFixed(3) }}
            </span>
          </div>
        </div>
        <div class="mkt-gauge" role="img" :aria-label="`风险偏好分 ${c.regime_score}`">
          <div class="mkt-gauge__track">
            <div class="mkt-gauge__seg is-cold" />
            <div class="mkt-gauge__seg is-mid" />
            <div class="mkt-gauge__seg is-hot" />
            <div class="mkt-gauge__pin" :style="{ left: `${Number(c.regime_score ?? 50)}%` }" />
          </div>
          <div class="mkt-gauge__scale">
            <span>0 谨慎</span><span>50 均衡</span><span>100 强势</span>
          </div>
        </div>
        <p v-if="c.overlay?.note" class="mkt-note--inline">{{ c.overlay.note }}</p>
        <p v-else-if="!c.overlay?.overlay_applied && c.overlay?.available" class="mkt-note--inline">
          客观加权模式（ic/auto/ml）不叠加主观情绪权重，以下榜单仅供参考
        </p>
        <p v-else class="mkt-note--inline">风险偏好用于调节动量 / 题材维的进攻权重（详见过滤与权重配置）</p>
      </div>

      <div class="mkt-limit">
        <div class="mkt-label">涨跌停温度<template v-if="!c.limit_available">（无数据）</template></div>
        <div class="mkt-limit__grid">
          <div class="mkt-limit__cell is-up-bg"><span class="mkt-limit__num">{{ ls.up ?? '—' }}</span><span class="mkt-limit__name">涨停</span></div>
          <div class="mkt-limit__cell is-down-bg"><span class="mkt-limit__num">{{ ls.down ?? '—' }}</span><span class="mkt-limit__name">跌停</span></div>
          <div class="mkt-limit__cell"><span class="mkt-limit__num">{{ ls.broken ?? '—' }}</span><span class="mkt-limit__name">炸板</span></div>
          <div class="mkt-limit__cell is-warn-bg"><span class="mkt-limit__num">{{ ls.max_streak ?? '—' }}</span><span class="mkt-limit__name">最高连板</span></div>
        </div>
        <div v-if="c.limit_available" class="mkt-limit__sub">
          炸板率 <b :class="Number(ls.broken_rate) > 25 ? 'is-warn' : ''">{{ Number(ls.broken_rate ?? 0).toFixed(1) }}%</b>
          <span class="mkt-limit__sep">·</span>
          多空比 {{ Number(ls.up) }}:{{ Number(ls.down) }}
        </div>
      </div>

      <div class="mkt-indices">
        <div class="mkt-label">大盘指数<template v-if="!c.index_available">（无数据）</template></div>
        <div v-if="c.indices?.length" class="mkt-indices__list">
          <div v-for="ix in c.indices" :key="ix.code" class="mkt-idx">
            <span class="mkt-idx__name" :title="ix.name">{{ ix.name }}</span>
            <span class="mkt-idx__pct" :class="pctCls(ix.pct)">{{ pctTxt(ix.pct) }}</span>
          </div>
        </div>
        <div v-else class="mkt-blank">—</div>
      </div>
    </div>

    <!-- ── 资金榜单 ── -->
    <div class="mkt-boards">
      <div v-if="c.etf_available" class="mkt-board-pair">
        <div class="mkt-board">
          <h4 class="mkt-board__title">ETF 主力净流入</h4>
          <div v-if="c.etf_in?.length" class="mkt-rows">
            <div v-for="(r, i) in c.etf_in.slice(0, 8)" :key="r.code" class="mkt-row">
              <span class="mkt-row__rank">{{ i + 1 }}</span>
              <span class="mkt-row__name" :title="r.name">{{ r.name }}</span>
              <span class="mkt-row__pct" :class="pctCls(r.pct)">{{ pctTxt(r.pct) }}</span>
              <span class="mkt-row__amt is-in">+{{ yv(r, i) }}亿</span>
            </div>
          </div>
          <div v-else class="mkt-blank">暂无净流入</div>
        </div>
        <div class="mkt-board">
          <h4 class="mkt-board__title">ETF 主力净流出</h4>
          <div v-if="c.etf_out?.length" class="mkt-rows">
            <div v-for="(r, i) in c.etf_out.slice(0, 8)" :key="r.code" class="mkt-row">
              <span class="mkt-row__rank">{{ i + 1 }}</span>
              <span class="mkt-row__name" :title="r.name">{{ r.name }}</span>
              <span class="mkt-row__pct" :class="pctCls(r.pct)">{{ pctTxt(r.pct) }}</span>
              <span class="mkt-row__amt is-out">-{{ yv(r, i) }}亿</span>
            </div>
          </div>
          <div v-else class="mkt-blank">暂无净流出</div>
        </div>
      </div>

      <div v-if="c.big_available" class="mkt-board-pair">
        <div class="mkt-board">
          <h4 class="mkt-board__title">全A主力净流入</h4>
          <div v-if="c.big_in?.length" class="mkt-rows">
            <div v-for="(r, i) in c.big_in.slice(0, 8)" :key="r.code" class="mkt-row">
              <span class="mkt-row__rank">{{ i + 1 }}</span>
              <span class="mkt-row__name" :title="r.name">{{ r.name }}</span>
              <span class="mkt-row__pct" :class="pctCls(r.pct)">{{ pctTxt(r.pct) }}</span>
              <span class="mkt-row__amt is-in">+{{ yv(r, i) }}亿</span>
            </div>
          </div>
          <div v-else class="mkt-blank">暂无净流入</div>
        </div>
        <div class="mkt-board">
          <h4 class="mkt-board__title">全A主力净流出</h4>
          <div v-if="c.big_out?.length" class="mkt-rows">
            <div v-for="(r, i) in c.big_out.slice(0, 8)" :key="r.code" class="mkt-row">
              <span class="mkt-row__rank">{{ i + 1 }}</span>
              <span class="mkt-row__name" :title="r.name">{{ r.name }}</span>
              <span class="mkt-row__pct" :class="pctCls(r.pct)">{{ pctTxt(r.pct) }}</span>
              <span class="mkt-row__amt is-out">-{{ yv(r, i) }}亿</span>
            </div>
          </div>
          <div v-else class="mkt-blank">暂无净流出</div>
        </div>
      </div>

      <div v-if="c.lhb_available" class="mkt-board-pair">
        <div class="mkt-board">
          <h4 class="mkt-board__title">龙虎榜净买入</h4>
          <div v-if="c.lhb_net_buy?.length" class="mkt-rows">
            <div v-for="(r, i) in c.lhb_net_buy.slice(0, 8)" :key="r.code" class="mkt-row">
              <span class="mkt-row__rank">{{ i + 1 }}</span>
              <span class="mkt-row__name" :title="r.reason || r.name">{{ r.name }}</span>
              <span class="mkt-row__amt is-in">+{{ yv(r, i) }}亿</span>
            </div>
          </div>
          <div v-else class="mkt-blank">暂无（盘前/未上榜）</div>
        </div>
        <div class="mkt-board">
          <h4 class="mkt-board__title">龙虎榜净卖出</h4>
          <div v-if="c.lhb_net_sell?.length" class="mkt-rows">
            <div v-for="(r, i) in c.lhb_net_sell.slice(0, 8)" :key="r.code" class="mkt-row">
              <span class="mkt-row__rank">{{ i + 1 }}</span>
              <span class="mkt-row__name" :title="r.reason || r.name">{{ r.name }}</span>
              <span class="mkt-row__amt is-out">-{{ yv(r, i) }}亿</span>
            </div>
          </div>
          <div v-else class="mkt-blank">暂无（盘前/未上榜）</div>
        </div>
      </div>
    </div>

    <div class="mkt-foot">
      <span v-if="c.as_of">采集 {{ c.as_of }}</span>
      <template v-if="hasFlags">
        <span class="mkt-foot__sep">·</span>
        <span>权重微调 <b>{{ fmtDelta(ov.delta) }}</b></span>
      </template>
      <span v-if="ov.available !== undefined && !ov.overlay_applied && ov.available" class="mkt-foot__sep" />
      <span class="mkt-foot__sep">·</span>
      <span>榜单命中个股在结果表「入选逻辑」中标注</span>
    </div>
  </div>
</template>

<style scoped>
.mkt { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: var(--ff-space-3); padding: var(--ff-space-3) var(--ff-space-4); overflow-y: auto; }
.mkt-label { font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-tertiary); margin-bottom: 6px; }
.mkt-blank { color: var(--ff-text-tertiary); font-size: var(--ff-fs-caption); padding: 8px 0; }

.mkt-note { display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: var(--ff-radius-md); background: var(--ff-warn-subtle); color: var(--ff-warn-text); border: 1px solid var(--ff-warn-border, var(--ff-border)); font-size: var(--ff-fs-caption); }
.mkt-note__dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; flex: none; }

/* 概览三卡 */
.mkt-overview { display: grid; grid-template-columns: 1.35fr 1fr 1fr; gap: var(--ff-space-3); }
.mkt-regime, .mkt-limit, .mkt-indices { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md); padding: var(--ff-space-3); }
.mkt-regime__head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--ff-space-2); }
.mkt-regime__score { font-size: 34px; font-weight: 800; line-height: 1; font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; color: var(--ff-text-primary); margin-top: 4px; }
.mkt-regime__unit { font-size: var(--ff-fs-caption); font-weight: 500; color: var(--ff-text-tertiary); margin-left: 4px; }
.mkt-regime__tags { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.mkt-chip { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: var(--ff-radius-pill); font-size: var(--ff-fs-caption); font-weight: 600; }
.mkt-chip.is-hot { background: var(--ff-up-subtle); color: var(--ff-up-text); }
.mkt-chip.is-cold { background: var(--ff-down-subtle, var(--ff-bg-muted)); color: var(--ff-down-text); }
.mkt-chip.is-mid { background: var(--ff-warn-subtle); color: var(--ff-warn-text); }
.mkt-chip.is-plain { background: var(--ff-bg-muted); color: var(--ff-text-secondary); }
.mkt-gauge { margin: 10px 0 6px; }
.mkt-gauge__track { position: relative; height: 8px; border-radius: var(--ff-radius-pill); display: flex; overflow: hidden; background: var(--ff-bg-muted); }
.mkt-gauge__seg { flex: 1; }
.mkt-gauge__seg.is-cold { background: linear-gradient(90deg, #22c55e55, #22c55e33); }
.mkt-gauge__seg.is-mid { background: linear-gradient(90deg, #f59e0b33, #f59e0b44); }
.mkt-gauge__seg.is-hot { background: linear-gradient(90deg, #ef444433, #ef4444aa); }
.mkt-gauge__pin { position: absolute; top: -3px; width: 3px; height: 14px; border-radius: 2px; background: var(--ff-text-primary); transform: translateX(-50%); transition: left var(--ff-dur-normal, .3s); box-shadow: 0 0 0 2px var(--ff-bg-surface); }
.mkt-gauge__scale { display: flex; justify-content: space-between; font-size: var(--ff-fs-micro); color: var(--ff-text-tertiary); margin-top: 4px; }
.mkt-note--inline { margin: 2px 0 0; font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); line-height: 1.5; }

/* 涨跌停 */
.mkt-limit__grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; }
.mkt-limit__cell { display: flex; flex-direction: column; align-items: center; gap: 2px; padding: 6px 4px; border-radius: var(--ff-radius-sm); background: var(--ff-bg-subtle); }
.mkt-limit__cell.is-up-bg { background: var(--ff-up-subtle); }
.mkt-limit__cell.is-down-bg { background: var(--ff-down-subtle, var(--ff-bg-subtle)); }
.mkt-limit__cell.is-warn-bg { background: var(--ff-warn-subtle); }
.mkt-limit__num { font-size: var(--ff-fs-h3); font-weight: 700; font-family: var(--ff-font-mono); line-height: 1.1; }
.mkt-limit__cell.is-up-bg .mkt-limit__num { color: var(--ff-up-text); }
.mkt-limit__cell.is-down-bg .mkt-limit__num { color: var(--ff-down-text); }
.mkt-limit__cell.is-warn-bg .mkt-limit__num { color: var(--ff-warn-text); }
.mkt-limit__name { font-size: var(--ff-fs-micro); color: var(--ff-text-tertiary); }
.mkt-limit__sub { margin-top: 8px; font-size: var(--ff-fs-caption); color: var(--ff-text-secondary); }
.mkt-limit__sep { margin: 0 6px; color: var(--ff-text-tertiary); }
.is-warn { color: var(--ff-warn-text); }

/* 指数 */
.mkt-indices__list { display: flex; flex-direction: column; gap: 5px; }
.mkt-idx { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
.mkt-idx__name { font-size: var(--ff-fs-caption); color: var(--ff-text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mkt-idx__pct { font-size: var(--ff-fs-caption); font-weight: 600; font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; white-space: nowrap; }

/* 榜单对 */
.mkt-boards { display: flex; flex-direction: column; gap: var(--ff-space-3); }
.mkt-board-pair { display: grid; grid-template-columns: 1fr 1fr; gap: var(--ff-space-3); }
.mkt-board { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: var(--ff-radius-md); padding: var(--ff-space-3); min-width: 0; }
.mkt-board__title { margin: 0 0 6px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-secondary); }
.mkt-rows { display: flex; flex-direction: column; }
.mkt-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px dashed var(--ff-border-subtle); min-width: 0; }
.mkt-row:last-child { border-bottom: none; }
.mkt-row__rank { width: 16px; flex: none; font-size: var(--ff-fs-micro); color: var(--ff-text-tertiary); font-family: var(--ff-font-mono); }
.mkt-row__name { flex: 1; min-width: 0; font-size: var(--ff-fs-caption); color: var(--ff-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mkt-row__pct { flex: none; font-size: var(--ff-fs-micro); font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; min-width: 52px; text-align: right; }
.mkt-row__amt { flex: none; font-size: var(--ff-fs-caption); font-weight: 600; font-family: var(--ff-font-mono); font-variant-numeric: tabular-nums; min-width: 66px; text-align: right; }
.mkt-row__amt.is-in { color: var(--ff-up-text); }
.mkt-row__amt.is-out { color: var(--ff-down-text); }
.is-up { color: var(--ff-up-text); }
.is-down { color: var(--ff-down-text); }

.mkt-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; font-size: var(--ff-fs-caption); color: var(--ff-text-tertiary); }
.mkt-foot__sep { margin: 0 6px; color: var(--ff-border-strong); }

@media (max-width: 1100px) {
  .mkt-overview { grid-template-columns: 1fr 1fr; }
  .mkt-indices { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  .mkt-overview, .mkt-board-pair { grid-template-columns: 1fr; }
}
</style>
