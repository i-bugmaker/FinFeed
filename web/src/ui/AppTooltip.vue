<script setup>
/**
 * AppTooltip — 文字提示
 *
 * 通过 title 属性或默认 slot 触发，支持 4 个方位。
 */
import { ref, onMounted, onUnmounted, computed, nextTick } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
  placement: { type: String, default: 'top' }, // top / bottom / left / right
  delay: { type: Number, default: 120 },
})

const triggerRef = ref(null)
const tipRef = ref(null)
const show = ref(false)
let timer = null

const cls = computed(() => ['ff-tip', 'ff-tip--floating', `ff-tip--${props.placement}`])

function enter() {
  clearTimeout(timer)
  timer = setTimeout(() => {
    show.value = true
    nextTick(position)
  }, props.delay)
}

function leave() {
  clearTimeout(timer)
  show.value = false
}

function position() {
  if (!triggerRef.value || !tipRef.value) return
  const t = triggerRef.value.getBoundingClientRect()
  const c = tipRef.value.getBoundingClientRect()
  let top = 0
  let left = 0
  switch (props.placement) {
    case 'top':
      top = t.top - c.height - 8
      left = t.left + (t.width - c.width) / 2
      break
    case 'bottom':
      top = t.bottom + 8
      left = t.left + (t.width - c.width) / 2
      break
    case 'left':
      top = t.top + (t.height - c.height) / 2
      left = t.left - c.width - 8
      break
    case 'right':
      top = t.top + (t.height - c.height) / 2
      left = t.right + 8
      break
  }
  tipRef.value.style.top = `${top + window.scrollY}px`
  tipRef.value.style.left = `${left + window.scrollX}px`
}

onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <span
    ref="triggerRef"
    class="ff-tip__trigger"
    @mouseenter="enter"
    @mouseleave="leave"
    @focus="enter"
    @blur="leave"
  >
    <slot />
  </span>
  <Teleport to="body">
    <Transition name="ff-tip">
      <div v-show="show" ref="tipRef" :class="cls" role="tooltip">
        <slot name="content">{{ content }}</slot>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ff-tip__trigger {
  display: inline-flex;
}

/*
 * Teleport 到 body 的浮动气泡：全局 .ff-tip 是为纯 CSS（data-tip::after）
 * 变体定义的 position: relative，这里必须显式覆盖为 absolute 并自带气泡外观。
 */
.ff-tip--floating {
  position: absolute;
  z-index: var(--ff-z-tooltip);
  padding: var(--ff-space-1-5) var(--ff-space-2-5);
  background: var(--ff-bg-inverse);
  color: var(--ff-text-inverse);
  font-size: var(--ff-fs-caption);
  font-weight: var(--ff-fw-medium);
  line-height: 1.4;
  white-space: nowrap;
  border-radius: var(--ff-radius-sm);
  box-shadow: var(--ff-shadow-md);
  pointer-events: none;
}
</style>
