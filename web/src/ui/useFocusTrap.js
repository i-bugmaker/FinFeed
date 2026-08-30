// 弹层焦点管理 composable：打开时聚焦容器内首个可聚焦元素、
// Tab 循环限制在容器内、关闭后焦点归还触发元素。
// getActive 返回弹层开关（ref/computed），getContainer 返回容器 DOM。
import { watch, onUnmounted } from 'vue'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function useFocusTrap(getActive, getContainer) {
  let lastFocused = null

  function focusFirst(container) {
    const els = container.querySelectorAll(FOCUSABLE)
    const target = els.length ? els[0] : container
    target.focus({ preventScroll: true })
  }

  function onKeydown(e) {
    if (e.key !== 'Tab') return
    const container = getContainer()
    // 容器不可见（v-show 隐藏）时不拦截
    if (!container || container.offsetParent === null) return
    const els = Array.from(container.querySelectorAll(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null
    )
    if (!els.length) return
    const first = els[0]
    const last = els[els.length - 1]
    if (!container.contains(document.activeElement)) {
      // 焦点漂移到背景（如点击遮罩后），拉回容器
      e.preventDefault()
      focusFirst(container)
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus({ preventScroll: true })
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus({ preventScroll: true })
    }
  }

  watch(getActive, (v) => {
    if (v) {
      lastFocused = document.activeElement
      // 等 v-show 显示后再聚焦
      setTimeout(() => {
        const c = getContainer()
        if (c && c.offsetParent !== null) focusFirst(c)
      }, 30)
      document.addEventListener('keydown', onKeydown, true)
    } else {
      document.removeEventListener('keydown', onKeydown, true)
      if (lastFocused && typeof lastFocused.focus === 'function') {
        lastFocused.focus({ preventScroll: true })
      }
      lastFocused = null
    }
  })

  onUnmounted(() => document.removeEventListener('keydown', onKeydown, true))
}
