<script setup>
/**
 * ToastHost — 全局轻提示渲染宿主
 *
 * 挂载于 App.vue（全局唯一），消费 useToast 的响应式队列。
 * 样式复用 components.css §12 的 .ff-toasts/.ff-toast 设计规范。
 * 注意：勿再挂载 EasyTdxToast，否则同一队列会被渲染两次。
 */
import { toasts, dismiss } from '../composables/useToast'
import AppIcon from '../ui/AppIcon.vue'

const ICONS = {
  success: 'check-circle',
  error: 'alert-circle',
  warn: 'alert-triangle',
  info: 'info',
}
</script>

<template>
  <Teleport to="body">
    <div class="ff-toasts" aria-live="polite">
      <TransitionGroup name="ff-toast">
        <div
          v-for="t in toasts"
          :key="t.id"
          class="ff-toast"
          :class="`ff-toast--${t.type}`"
          role="status"
        >
          <AppIcon :name="ICONS[t.type] || 'info'" size="sm" class="ff-toast__icon" />
          <span class="ff-toast__msg">{{ t.message }}</span>
          <button
            v-if="t.action"
            type="button"
            class="ff-toast__action"
            @click="t.onAction && t.onAction(); dismiss(t.id)"
          >
            {{ t.action }}
          </button>
          <button type="button" class="ff-toast__close" aria-label="关闭" @click="dismiss(t.id)">
            <AppIcon name="x" size="xs" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.ff-toast__msg {
  flex: 1;
  min-width: 0;
}

.ff-toast__action,
.ff-toast__close {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  padding: 2px 4px;
  border: none;
  background: none;
  color: inherit;
  opacity: 0.75;
  cursor: pointer;
  font-size: var(--ff-fs-body-sm);
  font-weight: var(--ff-fw-semibold);
}

.ff-toast__action:hover,
.ff-toast__close:hover {
  opacity: 1;
}
</style>
