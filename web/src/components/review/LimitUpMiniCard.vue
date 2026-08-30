<script setup>
/**
 * LimitUpMiniCard — 连板天梯精简概览（仪表盘内嵌）
 *
 * 与完整模块的关系：
 *  - 完整天梯（晋级 / 断板 / 连跌梯队全量列表）已独立为「连板天地」模块（/limitup-ladder）
 *  - 仪表盘只保留概览数字 + 跳转入口，不再重复渲染梯队列表，避免与顶部「今日市场速览」冗余
 *
 * 数据由父组件（DashboardView）从 /api/market/thslimitup?section=ladder 统一取数后传入，
 * 本组件不自行请求，保证仪表盘一次刷新只打一次接口。
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  /** 最高连板高度（板） */
  maxHeight: { type: Number, default: 0 },
  /** 晋级个股总数（全梯队求和） */
  advance: { type: Number, default: 0 },
  /** 断板个股总数 */
  broken: { type: Number, default: 0 },
  /** 连跌个股总数（连跌天梯） */
  downStreak: { type: Number, default: 0 },
  /** 数据日期 */
  date: { type: String, default: '' },
  /** 父组件取数中 */
  loading: { type: Boolean, default: false },
})

const router = useRouter()

const cells = computed(() => [
  {
    key: 'advance',
    label: '晋级',
    value: props.advance,
    tone: 'up',
    note: '今日封板成功，按连板高度分层',
  },
  {
    key: 'broken',
    label: '断板',
    value: props.broken,
    tone: 'muted',
    note: '昨日 N 连板今日未封板，归位到其本应冲击的层级',
  },
  {
    key: 'downStreak',
    label: '连跌',
    value: props.downStreak,
    tone: 'down',
    note: '连续跌停个股（通达信跌停池）',
  },
])

function goDetail() {
  router.push('/limitup-ladder')
}
</script>

<template>
  <div class="lu-mini">
    <AppSkeleton v-if="loading && !advance && !broken && !downStreak" variant="text" :lines="2" />

    <template v-else>
      <div class="lu-mini__cells">
        <div
          v-for="c in cells"
          :key="c.key"
          class="lu-mini__cell"
          :class="'is-' + c.tone"
          :title="c.note"
        >
          <span class="lu-mini__label">{{ c.label }}</span>
          <span class="lu-mini__value ff-num">{{ c.value }}</span>
        </div>
      </div>

      <div class="lu-mini__side">
        <span v-if="maxHeight" class="lu-mini__peak" title="市场最高连板高度">
          最高 <b class="ff-num">{{ maxHeight }}</b> 板
        </span>
        <button type="button" class="lu-mini__more" @click="goDetail">
          查看详情
          <AppIcon name="chevron-right" size="xs" />
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.lu-mini {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
  flex-wrap: wrap;
}

.lu-mini__cells {
  display: flex;
  align-items: stretch;
  gap: var(--ff-space-2);
  flex-wrap: wrap;
}

.lu-mini__cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 68px;
  padding: 6px 12px;
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-subtle);
}

.lu-mini__label {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
}

.lu-mini__value {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
}

.lu-mini__cell.is-up {
  border-left: 3px solid var(--ff-up);
}
.lu-mini__cell.is-up .lu-mini__value {
  color: var(--ff-text-up);
}
.lu-mini__cell.is-down {
  border-left: 3px solid var(--ff-down);
}
.lu-mini__cell.is-down .lu-mini__value {
  color: var(--ff-down-text);
}
.lu-mini__cell.is-muted {
  border-left: 3px solid var(--ff-border);
}
.lu-mini__cell.is-muted .lu-mini__value {
  color: var(--ff-text-tertiary);
}

.lu-mini__side {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-3);
  margin-left: auto;
}

.lu-mini__peak {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.lu-mini__peak b {
  font-weight: 700;
  color: #ff2d55;
  font-variant-numeric: tabular-nums;
}

.lu-mini__more {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 var(--ff-space-3);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-brand-text);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.lu-mini__more:hover {
  background: var(--ff-bg-brand-subtle);
  border-color: var(--ff-brand-border);
}

@media (max-width: 640px) {
  .lu-mini__side {
    margin-left: 0;
    width: 100%;
    justify-content: space-between;
  }
}
</style>
