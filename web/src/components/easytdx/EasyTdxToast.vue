<script setup>
// Toast 通知容器：渲染 useToast 队列，支持撤销 action
import AppIcon from '../../ui/AppIcon.vue'
import { toasts, dismiss } from '../../composables/useToast'

const ICONS = { success: 'check-circle', error: 'alert-circle', info: 'info' }
</script>

<template>
  <Teleport to="body">
    <div class="etdx-toasts" role="status" aria-live="polite">
      <TransitionGroup name="etdx-toast">
        <div v-for="t in toasts" :key="t.id" class="etdx-toast" :class="`etdx-toast--${t.type}`">
          <AppIcon :name="ICONS[t.type]" size="sm" class="etdx-toast__icon" />
          <span class="etdx-toast__msg">{{ t.message }}</span>
          <button
            v-if="t.action"
            type="button"
            class="etdx-toast__action"
            @click="t.onAction && t.onAction(); dismiss(t.id)"
          >
            {{ t.action }}
          </button>
          <button type="button" class="etdx-toast__close" aria-label="关闭" @click="dismiss(t.id)">
            <AppIcon name="x" size="xs" />
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<style scoped>
.etdx-toasts {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 1600;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: min(360px, calc(100vw - 32px));
}
.etdx-toast {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: var(--ff-bg-surface-raised);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  box-shadow: var(--ff-shadow-lg);
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
}
.etdx-toast--success .etdx-toast__icon { color: var(--ff-up); }
.etdx-toast--error .etdx-toast__icon { color: var(--ff-down); }
.etdx-toast--info .etdx-toast__icon { color: var(--ff-brand); }
.etdx-toast__msg { flex: 1; min-width: 0; }
.etdx-toast__action {
  border: none;
  background: transparent;
  color: var(--ff-text-brand);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  cursor: pointer;
  padding: 2px 4px;
  flex-shrink: 0;
}
.etdx-toast__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--ff-radius-xs);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
}
.etdx-toast__close:hover { background: var(--ff-bg-hover); color: var(--ff-text-primary); }
.etdx-toast-enter-active,
.etdx-toast-leave-active {
  transition: all 200ms var(--ff-ease-spring);
}
.etdx-toast-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.97);
}
.etdx-toast-leave-to {
  opacity: 0;
  transform: translateX(16px);
}
</style>
