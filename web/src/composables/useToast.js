// 轻量 Toast 通知：模块级响应式队列，EasyTdxToast.vue 负责渲染
import { reactive } from 'vue'

let seq = 0
export const toasts = reactive([])

/**
 * @param {{type?: 'success'|'error'|'info', message: string, action?: string, onAction?: Function}} opts
 */
export function toast(opts) {
  const id = ++seq
  toasts.push({
    id,
    type: opts.type || 'info',
    message: opts.message,
    action: opts.action || '',
    onAction: opts.onAction || null,
  })
  if (opts.duration !== 0) {
    setTimeout(() => dismiss(id), opts.duration || 3500)
  }
  return id
}

export function dismiss(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

export function toastSuccess(message) {
  toast({ type: 'success', message })
}
export function toastError(message) {
  toast({ type: 'error', message, duration: 5000 })
}
