<script setup>
/**
 * LimitUpSummaryCard — 连板天梯（晋级 + 断板）
 *
 * 数据来源：/api/market/thslimitup?section=ladder（状态元信息来自 section=intensity）
 * 展示：连板天梯（晋级 + 断板归位）+ 连跌天梯。
 * 涨停 / 炸板 / 跌停 / 炸板率 / 封板率等强度指标由页面顶部「今日市场速览」统一呈现，
 * 此处不再重复展示。
 *
 * 复用方：独立模块「连板天地」（/limitup-ladder，本组件全量渲染）。
 * 取数结束 emit('loaded', { ok }) 供页面落地「最后更新」时间戳。
 *
 * 天梯为「晋级 + 断板」合并视图：
 *   · 晋级股：今日封板成功，红色实色展示（红涨，--ff-up 体系）
 *   · 断板股：昨日 N 连板今日未封板，按「昨日高度 + 1」归入其本应冲击的
 *     层级（二连板断板 → 三连板位置），仅以虚化灰度 + 「断板」徽章呈现，
 *     不打叉、不参与数量统计。
 */
import { ref, watch, onMounted, computed } from 'vue'
import { api } from '../../api/client'
import AppEmpty from '../../ui/AppEmpty.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import AppIcon from '../../ui/AppIcon.vue'
import { fmtChg, chgClass, fmtPrice, fmtRatio, fmtSignedAmount } from './format'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['loaded'])

const loading = ref(false)
const err = ref('')
const intensity = ref(null) // { date, source, fallback, cached_date } —— 仅供状态元信息
const ladder = ref([]) // [{ height, number, stocks }]
const downLadder = ref([]) // 通达信连跌天梯 [{ height, number, stocks }]
const brokenLadder = ref([]) // 断板梯队 [{ height, number, stocks }]（昨日高度+1 归位）

// 连板梯队：降序排列的高度列表（height desc）
const tiers = computed(() => {
  return [...ladder.value].sort((a, b) => (b.height || 0) - (a.height || 0))
})
// 断板梯队（已按高度降序，但保险起见再排一次）
const brokenTiers = computed(() => {
  return [...brokenLadder.value].sort((a, b) => (b.height || 0) - (a.height || 0))
})
// 全梯队晋级个股总数
const totalStockCount = computed(() =>
  tiers.value.reduce((sum, t) => sum + ((t.stocks || []).length || 0), 0),
)

// 合并天梯：晋级层级 ∪ 断板归位层级；同层先晋级后断板
const mergedTiers = computed(() => {
  const byHeight = new Map()
  for (const t of tiers.value) {
    byHeight.set(t.height, { height: t.height, stocks: t.stocks || [], broken: [] })
  }
  for (const b of brokenTiers.value) {
    const h = b.height
    if (!byHeight.has(h)) byHeight.set(h, { height: h, stocks: [], broken: [] })
    byHeight.get(h).broken = b.stocks || []
  }
  return [...byHeight.values()].sort((a, b) => b.height - a.height)
})

function tierClass(t) {
  return {
    'is-hot': t.height >= 4 && (t.stocks || []).length > 0,
    'is-broken-only': (t.stocks || []).length === 0 && (t.broken || []).length > 0,
    'is-col2': t.height === 1 && (t.stocks || []).length > 0,
  }
}

// 断板归因：题材/原因 + 断板事实，完整展示不省略
// （断板股同样要能看到「为什么板的」，缺失原因时至少给出断板高度信息）
function brokenReason(s) {
  const r = (s && s.reason ? String(s.reason) : '').trim()
  const tail = `昨日 ${s?.prev_height ?? '—'} 连板 · 今日断板`
  return r ? `${r} · ${tail}` : tail
}

// 数据日期 / 缓存状态提示条（来自 intensity 载荷的 date / source / fallback / cached_date）
const dataMeta = computed(() => {
  const d = intensity.value || {}
  const source = d.source || ''
  const fallback = d.fallback || ''
  const date = (fallback.includes('db_latest') && d.cached_date)
    ? d.cached_date
    : (d.date || d.cached_date || '')
  let label = '实时'
  let tone = 'live'
  if (fallback) {
    label = fallback.includes('db_latest') ? '最近交易日缓存' : '当日缓存'
    tone = 'cache'
  } else if (source === 'live_partial') {
    label = '实时 · 部分降级'
    tone = 'degraded'
  } else if (source === 'db') {
    label = '数据库缓存'
    tone = 'cache'
  }
  return { date, label, tone }
})

async function fetchIntensity() {
  const res = await api.market('thslimitup', { section: 'intensity' })
  // 后端包装 { success, data }；data 即强度载荷（date/source/fallback/…）
  intensity.value = (res && (res.data || res)) || null
}
async function fetchLadder() {
  const res = await api.market('thslimitup', { section: 'ladder' })
  const d = res && (res.data || res)
  ladder.value = (d && d.ladder) || []
  downLadder.value = (d && d.down_ladder) || []
  brokenLadder.value = (d && d.broken_ladder) || []
}
// 通达信连跌天梯：按连续跌停天数分组（height desc）
const downTiers = computed(() => {
  return [...downLadder.value].sort((a, b) => (b.height || 0) - (a.height || 0))
})
const totalDownCount = computed(() =>
  downTiers.value.reduce((sum, t) => sum + ((t.stocks || []).length || 0), 0),
)

async function load() {
  loading.value = true
  err.value = ''
  try {
    await Promise.all([fetchIntensity(), fetchLadder()])
  } catch (e) {
    err.value = e.message || String(e)
  } finally {
    loading.value = false
    emit('loaded', { ok: !err.value })
  }
}

watch(() => props.refreshKey, () => load())
onMounted(load)
</script>

<template>
  <div class="lu-sum">
    <div v-if="loading" class="lu-sum__load">
      <AppSkeleton variant="text" :lines="4" />
    </div>
    <div v-else-if="err && !intensity && !tiers.length" class="lu-sum__err">
      <AppEmpty icon="flame" title="暂无涨停摘要" :description="err" />
    </div>
    <AppEmpty v-else-if="!intensity && !tiers.length" icon="flame" title="暂无涨停摘要" />

    <template v-else>
      <!-- 数据日期 / 缓存状态提示条 -->
      <div class="lu-sum__meta">
        <span class="lu-sum__meta-date">数据日期 <b class="ff-num">{{ dataMeta.date || '—' }}</b></span>
        <span class="lu-sum__meta-src" :class="`is-${dataMeta.tone}`">
          <i class="lu-sum__dot"></i>{{ dataMeta.label }}
        </span>
      </div>

      <!-- 连板天梯（晋级 + 断板合并视图，全量） -->
      <div v-if="mergedTiers.length" class="lu-sum__ladder">
        <div class="lu-sum__ladder-head">
          <span class="lu-sum__ladder-title">
            <AppIcon name="columns" size="sm" /> 连板天梯
          </span>
          <span class="lu-sum__ladder-count">晋级 <b class="ff-num">{{ totalStockCount }}</b> 只</span>
        </div>
        <div
          v-for="t in mergedTiers"
          :key="'t' + t.height"
          class="lu-sum__tier"
          :class="tierClass(t)"
        >
          <div class="lu-sum__tier-head">
            <span class="lu-sum__tier-badge ff-num" :class="{ 'lu-sum__tier-badge--ghost': !t.stocks.length }">
              {{ t.height }}板
              <span class="lu-sum__tier-count ff-num">{{ (t.stocks || []).length }}</span>
            </span>
          </div>
          <div class="lu-sum__tier-grid">
            <!-- 晋级卡片（红涨体系；连板高度由梯队头部统一标注，卡片不再重复） -->
            <article
              v-for="(s, i) in t.stocks"
              :key="(s.code || '') + '-' + i"
              class="lu-sum__card"
            >
              <header class="lu-sum__card-head">
                <span class="lu-sum__card-name">{{ s.name }}</span>
                <span class="lu-sum__card-code ff-num">{{ s.code }}</span>
              </header>
              <div class="lu-sum__card-quote">
                <span class="lu-sum__card-price ff-num">{{ fmtPrice(s.price) }}</span>
                <span class="lu-sum__card-chg ff-num" :class="chgClass(s.change_pct)">{{ fmtChg(s.change_pct) }}</span>
              </div>
              <p class="lu-sum__card-reason">{{ s.reason || '—' }}</p>
              <footer class="lu-sum__card-foot">
                <span class="lu-sum__card-tags">
                  <span v-if="s.limit_up_time" class="lu-sum__card-tag">封板 {{ s.limit_up_time }}</span>
                  <span v-if="s.main_net_amount" class="lu-sum__card-tag" :class="chgClass(s.main_net_amount)">
                    主力 {{ fmtSignedAmount(s.main_net_amount) }}
                  </span>
                  <span v-if="s.turnover_ratio" class="lu-sum__card-tag">换手 {{ fmtRatio(s.turnover_ratio) }}%</span>
                </span>
              </footer>
            </article>
            <!-- 断板卡片（虚化灰度，不打叉、不计入统计；归因完整展示） -->
            <article
              v-for="s in t.broken"
              :key="'b' + (s.code || '')"
              class="lu-sum__card lu-sum__card--broken"
            >
              <header class="lu-sum__card-head">
                <span class="lu-sum__card-name">{{ s.name }}</span>
                <span class="lu-sum__card-code ff-num">{{ s.code }}</span>
              </header>
              <div class="lu-sum__card-quote">
                <span class="lu-sum__card-price ff-num">{{ s.price ? fmtPrice(s.price) : '—' }}</span>
                <span class="lu-sum__card-chg ff-num" :class="chgClass(s.change_pct)">{{ fmtChg(s.change_pct) }}</span>
              </div>
              <p class="lu-sum__card-reason">{{ brokenReason(s) }}</p>
              <footer class="lu-sum__card-foot">
                <span class="lu-sum__card-tags">
                  <span class="lu-sum__card-tag lu-sum__card-tag--broken">断板</span>
                  <span v-if="s.main_net_amount" class="lu-sum__card-tag" :class="chgClass(s.main_net_amount)">
                    主力 {{ fmtSignedAmount(s.main_net_amount) }}
                  </span>
                </span>
              </footer>
            </article>
          </div>
        </div>
      </div>

      <!-- 连跌天梯：通达信跌停池，按连续跌停天数分组 -->
      <div v-if="downTiers.length" class="lu-sum__ladder lu-sum__down">
        <div class="lu-sum__ladder-head">
          <span class="lu-sum__ladder-title">
            <AppIcon name="columns" size="sm" /> 连跌天梯
          </span>
          <span class="lu-sum__ladder-count">共 <b class="ff-num">{{ totalDownCount }}</b> 只</span>
        </div>
        <div
          v-for="t in downTiers"
          :key="'dg' + t.height"
          class="lu-sum__tier"
          :class="{ 'is-down-hot': t.height >= 4, 'is-col2': t.height === 1 }"
        >
          <div class="lu-sum__tier-head">
            <span class="lu-sum__tier-badge lu-sum__tier-badge--down ff-num">
              跌停{{ t.height }}
              <span class="lu-sum__tier-count ff-num">{{ (t.stocks || []).length }}</span>
            </span>
          </div>
          <div class="lu-sum__tier-grid">
            <article
              v-for="(s, i) in t.stocks"
              :key="(s.code || '') + '-' + i"
              class="lu-sum__card lu-sum__card--down"
            >
              <header class="lu-sum__card-head">
                <span class="lu-sum__card-name">{{ s.name }}</span>
                <span class="lu-sum__card-code ff-num">{{ s.code }}</span>
              </header>
              <div class="lu-sum__card-quote">
                <span class="lu-sum__card-price ff-num">{{ fmtPrice(s.price) }}</span>
                <span class="lu-sum__card-chg ff-num" :class="chgClass(s.change_pct)">{{ fmtChg(s.change_pct) }}</span>
              </div>
              <p class="lu-sum__card-reason">{{ s.reason || '—' }}</p>
              <footer class="lu-sum__card-foot">
                <span class="lu-sum__card-tags">
                  <span v-if="s.limit_up_time" class="lu-sum__card-tag">封板 {{ s.limit_up_time }}</span>
                  <span v-if="s.main_net_amount" class="lu-sum__card-tag" :class="chgClass(s.main_net_amount)">
                    封单 {{ fmtSignedAmount(s.main_net_amount) }}
                  </span>
                  <span v-if="s.turnover_ratio" class="lu-sum__card-tag">换手 {{ fmtRatio(s.turnover_ratio) }}%</span>
                </span>
              </footer>
            </article>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.lu-sum {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
}
.lu-sum__load {
  min-height: 120px;
}

/* 数据日期 / 缓存状态提示条 */
.lu-sum__meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
  padding-bottom: var(--ff-space-2);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu-sum__meta-date b {
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-secondary);
}
.lu-sum__meta-src {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  white-space: nowrap;
}
.lu-sum__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.lu-sum__meta-src.is-live {
  color: var(--ff-text-up);
}
.lu-sum__meta-src.is-live .lu-sum__dot {
  background: var(--ff-text-up);
}
.lu-sum__meta-src.is-cache,
.lu-sum__meta-src.is-degraded {
  color: var(--ff-warn-text);
}
.lu-sum__meta-src.is-cache .lu-sum__dot,
.lu-sum__meta-src.is-degraded .lu-sum__dot {
  background: var(--ff-warn-text);
}

/* ================= 连板天梯：梯队分组 + 列表行 ================= */
.lu-sum__ladder {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.lu-sum__ladder-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-2);
}
.lu-sum__ladder-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  color: var(--ff-text-primary);
}
.lu-sum__ladder-title :deep(.ff-icon) {
  color: var(--ff-brand-text);
}
.lu-sum__ladder-count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.lu-sum__ladder-count b {
  font-weight: var(--ff-fw-semibold);
  font-variant-numeric: tabular-nums;
  color: var(--ff-text-up);
}

/* 梯队分组 */
.lu-sum__tier {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.lu-sum__tier-head {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--ff-space-2);
}
.lu-sum__tier-badge {
  display: inline-flex;
  align-items: baseline;
  justify-content: center;
  min-width: 46px;
  padding: 1px 10px;
  border-radius: var(--ff-radius-pill);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-bold);
  color: var(--ff-up-fg);
  background: linear-gradient(90deg, var(--ff-up-strong), var(--ff-up));
  font-variant-numeric: tabular-nums;
  line-height: 1.6;
}
.lu-sum__tier.is-hot .lu-sum__tier-badge {
  background: linear-gradient(90deg, #ff8a3d, #ff2d55);
}
/* 仅含断板股的层级：徽章虚化 */
.lu-sum__tier-badge--ghost {
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-muted);
  border: 1px solid var(--ff-border);
}
.lu-sum__tier-count {
  margin-left: 6px;
  padding-left: 6px;
  border-left: 1px solid rgba(255, 255, 255, 0.35);
  font-size: var(--ff-fs-overline);
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  font-variant-numeric: tabular-nums;
  opacity: 0.85;
}
.lu-sum__tier-badge--ghost .lu-sum__tier-count {
  border-left-color: var(--ff-border);
  color: var(--ff-text-tertiary);
  opacity: 1;
}

/* ================= 连跌天梯（通达信跌停池）================= */
.lu-sum__down {
  padding-top: var(--ff-space-4);
  border-top: 1px solid var(--ff-border-subtle);
}
.lu-sum__down .lu-sum__ladder-title :deep(.ff-icon) {
  color: var(--ff-down-text);
}
.lu-sum__tier-badge--down {
  color: var(--ff-down-fg);
  background: linear-gradient(90deg, var(--ff-down-strong), var(--ff-down));
}
.lu-sum__tier.is-down-hot .lu-sum__tier-badge--down {
  background: linear-gradient(90deg, #7c3aed, #312e81);
}
/* ================= 梯队卡片网格 =================
   统一列宽 + grid-auto-rows: 1fr —— 同一梯队内所有卡片严格等高，
   行高由该梯队内容最多的一张决定，消除长短卡片参差 */
.lu-sum__tier-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(216px, 1fr));
  grid-auto-rows: 1fr;
  gap: var(--ff-space-3);
}

/* ================= 个股卡片 ================= */
.lu-sum__card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
  /* 统一基线高度：与归因区 3 行基线 + 两行标签基线配套，
     使晋级 / 断板 / 连跌卡片落在同一尺寸上，梯队之间不再参差 */
  min-height: 196px;
  padding: 14px 14px 13px;
  /* 扁平卡片：细边框 + 纯色底，不使用阴影／光晕／顶部色线 */
  border: 1px solid var(--ff-border-subtle);
  border-radius: 12px;
  background: var(--ff-bg-surface);
  cursor: default;
  transition: background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard),
    transform var(--ff-dur-base) var(--ff-ease-standard),
    opacity var(--ff-dur-fast) var(--ff-ease-standard);
}

/* 高板卡片：浅红渐变底提供类型区分；不加任何色线／光晕 */
.lu-sum__tier.is-hot .lu-sum__card {
  background: linear-gradient(180deg, var(--ff-up-subtle), var(--ff-bg-surface) 72%);
}
/* 连跌卡片：浅绿渐变底 */
.lu-sum__tier .lu-sum__card--down {
  background: linear-gradient(180deg, var(--ff-down-subtle), var(--ff-bg-surface) 72%);
}
.lu-sum__tier .lu-sum__card--down .lu-sum__card-price {
  color: var(--ff-down-text);
}
/* hover：只做边框加深 + 背景微变 + 轻微上浮 */
.lu-sum__card:hover {
  border-color: var(--ff-border-strong);
  background: var(--ff-bg-hover);
  transform: translateY(-1px);
}

/* 卡片头：股票名称 + 代码（连板高度由梯队头部标注，卡片不重复） */
.lu-sum__card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}
.lu-sum__card-name {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--ff-fs-body);
  font-weight: var(--ff-fw-bold);
  line-height: 1.35;
  color: var(--ff-text-primary);
  /* 完整显示：超长换行，不做省略 */
  overflow-wrap: anywhere;
}
.lu-sum__card-code {
  flex-shrink: 0;
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

/* 报价行：现价 + 涨跌幅（涨跌幅为药丸 chip，红涨绿跌） */
.lu-sum__card-quote {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.lu-sum__card-price {
  font-size: 17px;
  font-weight: var(--ff-fw-bold);
  line-height: 1.2;
  color: var(--ff-text-up);
  font-variant-numeric: tabular-nums;
}
.lu-sum__card-chg {
  padding: 1px 7px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-muted);
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.lu-sum__card-chg.is-up {
  background: var(--ff-up-subtle);
  color: var(--ff-text-up);
}
.lu-sum__card-chg.is-down {
  background: var(--ff-down-subtle);
  color: var(--ff-down-text);
}

/* 归因：完整展示，不截断、不省略（断板股同样显示题材原因）
   flex: 1 吸收卡片剩余高度，配合 grid-auto-rows 让同梯队卡片底部标签齐平 */
.lu-sum__card-reason {
  flex: 1 1 auto;
  /* 3 行基线（4.5em = 3 × 1.5 行高）：短归因不压矮卡片，
     保证不同梯队、不同长度的卡片落在同一高度上 */
  min-height: 4.5em;
  margin: 0;
  font-size: var(--ff-fs-caption);
  line-height: 1.5;
  color: var(--ff-text-secondary);
  overflow-wrap: anywhere;
}

/* 卡片底：标签组（自动换行不省略）
   min-height 预留两行标签高度 —— 断板卡只有 1 个标签、晋级卡有 3 个，
   不锁基线会因标签行数不同而让卡片高度参差 */
.lu-sum__card-foot {
  display: flex;
  align-items: center;
  min-width: 0;
  min-height: 40px;
}
.lu-sum__card-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.lu-sum__card-tag {
  padding: 0 6px;
  border-radius: var(--ff-radius-sm);
  font-size: var(--ff-fs-overline);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  font-variant-numeric: tabular-nums;
  line-height: 1.75;
  white-space: nowrap;
}
.lu-sum__card-tag--broken {
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-muted);
  font-weight: var(--ff-fw-semibold);
}

/* ============ 断板卡片：虚化灰度（不打叉） ============ */
.lu-sum__card--broken {
  background: var(--ff-bg-subtle);
  border-color: var(--ff-border);
  opacity: 0.78;
  filter: grayscale(0.3);
}
.lu-sum__card--broken:hover {
  opacity: 1;
  background: var(--ff-bg-hover);
}
.lu-sum__card--broken .lu-sum__card-name {
  color: var(--ff-text-tertiary);
  text-decoration: line-through;
  text-decoration-thickness: 1.5px;
  text-decoration-color: var(--ff-text-tertiary);
}
.lu-sum__card--broken .lu-sum__card-price {
  color: var(--ff-text-tertiary);
}
.lu-sum__card--broken .lu-sum__card-reason {
  color: var(--ff-text-secondary);
}

/* 窄屏：收回两列，保证归因完整可读（等高规则 1fr 保持生效） */
@media (max-width: 640px) {
  .lu-sum__tier-grid {
    grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
    gap: var(--ff-space-2);
  }
}

.is-up {
  color: var(--ff-text-up);
}
.is-down {
  color: var(--ff-down-text);
}
.is-flat {
  color: var(--ff-text-tertiary);
}
</style>
