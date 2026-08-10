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
  padding: var(--ff-space-3) var(--ff-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1-5);
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-lg);
  box-shadow: var(--ff-shadow-sm);
  overflow: hidden;
  transition:
    transform var(--ff-dur-fast) var(--ff-ease-standard),
    box-shadow var(--ff-dur-fast) var(--ff-ease-standard),
    border-color var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-statcard::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--ff-border-strong);
}
.ff-statcard--up::before {
  background: var(--ff-up);
}
.ff-statcard--down::before {
  background: var(--ff-down);
}
.ff-statcard--link {
  cursor: pointer;
}
.ff-statcard--link:hover,
.ff-statcard--link:focus-visible {
  box-shadow: var(--ff-shadow-md);
  border-color: var(--ff-border-strong);
  outline: none;
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
  gap: var(--ff-space-1-5);
  min-width: 0;
}
.ff-statcard__icon {
  flex-shrink: 0;
}
.ff-statcard__label {
  font-size: var(--ff-fs-body-sm);
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
  font-size: var(--ff-fs-2xl);
  font-weight: 600;
  line-height: var(--ff-lh-tight);
  color: var(--ff-text-primary);
  letter-spacing: var(--ff-ls-tight);
  font-variant-numeric: tabular-nums;
}

.ff-statcard__sub {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
