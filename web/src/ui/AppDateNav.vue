<script setup>
/**
 * AppDateNav — 胶囊式日期切换组件（‹ / 日期 / › / 今）
 *
 * 全站统一的「单日切换」控件，财经日历、多标的分时对比等模块共用，
 * 保证视觉与交互完全一致。
 *
 * 结构：
 *   ‹ | 2026年08月30日        | › | 今
 *      | 周日 [今天/历史/前瞻] |
 *
 * 约定：
 *  - modelValue 为空字符串时视为「今天」，实际日期取自 today 或本地当日。
 *  - todayValue 指定点击「今」时发出的值，默认发出 today 的 ISO；
 *    需要「实时」语义的调用方显式传 today-value=""。
 *  - allowFuture=false 时上限自动钳到「今天」（历史数据类模块）。
 *  - 越界（超出 min/max）不静默失败，emit('out-of-range') 交由上层提示。
 */
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import AppDatePicker from './AppDatePicker.vue'

const props = defineProps({
  /** 当前日期（YYYY-MM-DD）；'' 表示今天 */
  modelValue: { type: String, default: '' },
  /** 「今天」基准日期，缺省回退到浏览器本地日期（服务器日期优先场景由调用方传入） */
  today: { type: String, default: '' },
  /** 可选最小日期，'' 表示不限 */
  min: { type: String, default: '' },
  /** 可选最大日期，'' 表示不限 */
  max: { type: String, default: '' },
  /** 是否允许选择未来日期 */
  allowFuture: { type: Boolean, default: false },
  /** 点击「今」时发出的值；默认（null）发出 today 的 ISO */
  todayValue: { type: String, default: null },
  disabled: { type: Boolean, default: false },
  title: { type: String, default: '当前展示数据对应的日期' },
})

const emit = defineEmits(['update:modelValue', 'change', 'out-of-range'])

const WEEK_CN = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const pad = (n) => String(n).padStart(2, '0')
const toISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
function parseISO(s) {
  const [y, m, d] = String(s).split('-').map(Number)
  return new Date(y, (m || 1) - 1, d || 1)
}
function shiftISO(s, n) {
  const d = parseISO(s)
  d.setDate(d.getDate() + n)
  return toISO(d)
}

const todayISO = computed(() => props.today || toISO(new Date()))
/** 当前生效日期：'' 视为今天 */
const curISO = computed(() => props.modelValue || todayISO.value)
const effMin = computed(() => props.min || '')
const effMax = computed(() => props.max || (props.allowFuture ? '' : todayISO.value))
const isTodaySel = computed(() => curISO.value === todayISO.value)

const resolvedTodayValue = computed(() =>
  props.todayValue === null ? todayISO.value : props.todayValue,
)

const dateL1 = computed(() => {
  const d = parseISO(curISO.value)
  return `${d.getFullYear()}年${pad(d.getMonth() + 1)}月${pad(d.getDate())}日`
})
const dateWeek = computed(() => WEEK_CN[parseISO(curISO.value).getDay()] || '')
const tagText = computed(() => {
  if (isTodaySel.value) return '今天'
  return curISO.value > todayISO.value ? '前瞻' : '历史'
})

const prevDisabled = computed(
  () => props.disabled || !!(effMin.value && curISO.value <= effMin.value),
)
const nextDisabled = computed(
  () => props.disabled || !!(effMax.value && curISO.value >= effMax.value),
)
const todayDisabled = computed(
  () => props.disabled || resolvedTodayValue.value === props.modelValue,
)

function commit(v) {
  if (v === props.modelValue) return
  emit('update:modelValue', v)
  emit('change', v)
}

function reject(v, reason) {
  emit('out-of-range', { value: v, min: effMin.value, max: effMax.value, reason })
}

/** 校验后提交；越界则交给上层提示（reason: 'min' | 'max'） */
function commitGuarded(v) {
  if (effMin.value && v < effMin.value) return reject(v, 'min')
  if (effMax.value && v > effMax.value) return reject(v, 'max')
  commit(v)
}

function step(n) {
  if (props.disabled) return
  commitGuarded(shiftISO(curISO.value, n))
}

function goToday() {
  if (props.disabled) return
  commit(resolvedTodayValue.value)
}

// ---------------- 月历弹层 ----------------
const pickerRef = ref(null)
const pickerOpen = ref(false)

// .stop 阻断冒泡：避免 AppDatePicker 的「点击外部关闭」监听器立即把弹层关掉
function togglePicker() {
  if (props.disabled) return
  pickerOpen.value = !pickerOpen.value
  const p = pickerRef.value
  if (!p) return
  if (pickerOpen.value) p.openPopup()
  else p.closePopup()
}

function onPicked(v) {
  if (!v) return
  pickerOpen.value = false
  pickerRef.value?.closePopup()
  commitGuarded(v)
}
</script>

<template>
  <div
    class="ff-datenav"
    :class="{ 'is-off': !isTodaySel, 'is-disabled': disabled }"
    :title="title"
  >
    <button
      type="button"
      class="ff-datenav__btn"
      title="前一天"
      aria-label="前一天"
      :disabled="prevDisabled"
      @click="step(-1)"
    >‹</button>

    <button
      type="button"
      class="ff-datenav__main"
      title="点击选择日期"
      :disabled="disabled"
      @click.stop="togglePicker"
    >
      <span class="ff-datenav__l1 ff-num">{{ dateL1 }}</span>
      <span class="ff-datenav__l2">
        <span>{{ dateWeek }}</span>
        <span class="ff-datenav__tag" :class="isTodaySel ? 'is-live' : 'is-alt'">{{ tagText }}</span>
        <AppIcon name="chevron-down" size="xs" class="ff-datenav__caret" />
      </span>
    </button>

    <button
      type="button"
      class="ff-datenav__btn"
      title="后一天"
      aria-label="后一天"
      :disabled="nextDisabled"
      @click="step(1)"
    >›</button>

    <button
      type="button"
      class="ff-datenav__today"
      title="回到今天（最新数据）"
      aria-label="回到今天"
      :disabled="todayDisabled"
      @click="goToday"
    >今</button>

    <!-- 月历弹层锚点：零尺寸定位容器，弹层相对其左下角展开 -->
    <div class="ff-datenav__anchor">
      <AppDatePicker
        ref="pickerRef"
        :trigger="false"
        :model-value="curISO"
        :min="effMin"
        :max="effMax"
        @update:model-value="onPicked"
      />
    </div>
  </div>
</template>

<style scoped>
.ff-datenav {
  position: relative;
  display: inline-flex;
  align-items: stretch;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-surface);
  overflow: visible; /* 月历弹层需要溢出显示 */
  flex: none;
  transition: border-color var(--ff-dur-fast);
}
.ff-datenav:hover { border-color: var(--ff-border-strong); }
.ff-datenav.is-disabled { opacity: 0.55; }

.ff-datenav__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  font-size: 16px;
  line-height: 1;
  color: var(--ff-icon-muted);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-datenav__btn:hover:not(:disabled) { background: var(--ff-bg-hover); color: var(--ff-text-brand); }
.ff-datenav__btn:disabled { opacity: 0.35; cursor: default; }

.ff-datenav__main {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 2px;
  min-width: 140px;
  padding: 3px 10px;
  border-left: 1px solid var(--ff-border-subtle);
  border-right: 1px solid var(--ff-border-subtle);
  text-align: left;
  transition: background var(--ff-dur-fast);
}
.ff-datenav__main:hover:not(:disabled) { background: var(--ff-bg-hover); }
.ff-datenav__main:disabled { cursor: default; }

.ff-datenav__l1 {
  font-size: 14px;
  font-weight: 700;
  color: var(--ff-text-primary);
  letter-spacing: 0.2px;
  line-height: 1;
  white-space: nowrap;
}
.ff-datenav.is-off .ff-datenav__l1 { color: var(--ff-text-brand); }

.ff-datenav__l2 {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--ff-text-tertiary);
  line-height: 1;
  white-space: nowrap;
}

.ff-datenav__tag {
  display: inline-flex;
  align-items: center;
  height: 15px;
  padding: 0 6px;
  border-radius: var(--ff-radius-pill);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.ff-datenav__tag.is-live {
  background: var(--ff-bg-subtle);
  color: var(--ff-text-secondary);
  border: 1px solid var(--ff-border-subtle);
}
.ff-datenav__tag.is-alt {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
  border: 1px solid var(--ff-brand-border);
}

.ff-datenav__caret {
  color: var(--ff-icon-muted);
  opacity: 0.7;
}

.ff-datenav__today {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ff-text-secondary);
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.ff-datenav__today:hover:not(:disabled) { background: var(--ff-bg-brand-subtle); color: var(--ff-text-brand); }
.ff-datenav__today:disabled { opacity: 0.35; cursor: default; }

/* 弹层锚点：贴在日期区左下角，零尺寸不占布局 */
.ff-datenav__anchor {
  position: absolute;
  left: 30px;
  bottom: 0;
  width: 0;
  height: 0;
}
</style>
