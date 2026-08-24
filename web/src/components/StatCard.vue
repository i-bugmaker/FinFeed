<script setup>
/**
 * StatCard — KPI 指标卡
 * icon: 指标图标；to: 点击卡片跳转的路由；tone: '' / up / down
 */
import { useRouter } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps({
  label: { type: String, default: '' },
  value: { type: [String, Number], default: '—' },
  sub: { type: String, default: '' },
  tone: { type: String, default: '' }, // '', up, down
  icon: { type: String, default: '' },
  to: { type: String, default: '' },
})

const router = useRouter()
function go() {
  if (props.to) router.push(props.to)
}
</script>

<template>
  <div
    class="ff-statcard"
    :class="[tone && `ff-statcard--${tone}`, to && 'ff-statcard--link']"
    :role="to ? 'button' : undefined"
    :tabindex="to ? 0 : undefined"
    :aria-label="to ? `查看 ${label}` : undefined"
    @click="go"
    @keydown.enter="go"
  >
    <div class="ff-statcard__head">
      <AppIcon v-if="icon" :name="icon" size="sm" :tone="tone || 'muted'" class="ff-statcard__icon" />
      <span class="ff-statcard__label">{{ label }}</span>
      <AppIcon v-if="to" name="arrow-right" size="xs" class="ff-statcard__arrow" />
    </div>
    <div class="ff-statcard__value ff-num" :class="tone && `ff-t-${tone}`">{{ value }}</div>
    <div v-if="sub" class="ff-statcard__sub">{{ sub }}</div>
  </div>
</template>

<style scoped>
.ff-statcard {
  position: relative;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-xs);
  overflow: hidden;
  transition: all var(--ff-dur-base) var(--ff-ease-standard);
}
.ff-statcard::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--ff-border-strong);
  transition: width var(--ff-dur-fast);
}
.ff-statcard--up::before {
  background: var(--ff-up);
  box-shadow: 0 0 10px var(--ff-up);
}
.ff-statcard--down::before {
  background: var(--ff-down);
  box-shadow: 0 0 10px var(--ff-down);
}
.ff-statcard--link {
  cursor: pointer;
}
.ff-statcard--link:hover,
.ff-statcard--link:focus-visible {
  box-shadow: var(--ff-shadow-md);
  border-color: var(--ff-border-strong);
  transform: translateY(-2px);
  outline: none;
}
.ff-statcard--link:hover::before {
  width: 4px;
}
.ff-statcard--link:focus-visible {
  box-shadow: var(--ff-focus-ring), var(--ff-shadow-sm);
}
.ff-statcard--link:active {
  transform: translateY(0);
  box-shadow: var(--ff-shadow-sm);
}

.ff-statcard__head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.ff-statcard__icon {
  flex-shrink: 0;
}
.ff-statcard__label {
  font-size: 13px;
  color: var(--ff-text-secondary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ff-statcard__arrow {
  margin-left: auto;
  color: var(--ff-text-tertiary);
  opacity: 0;
  transform: translateX(-2px);
  transition:
    opacity var(--ff-dur-fast) var(--ff-ease-standard),
    transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-statcard--link:hover .ff-statcard__arrow {
  opacity: 1;
  transform: translateX(0);
}

.ff-statcard__value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--ff-text-primary);
  letter-spacing: -0.02em;
  font-family: var(--ff-font-mono);
  font-variant-numeric: tabular-nums;
}

.ff-statcard__sub {
  font-size: 12px;
  color: var(--ff-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
