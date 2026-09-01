/**
 * useScrollRestore — 记忆并恢复「内容区滚动容器」的滚动位置
 *
 * 问题根因：
 *   应用外壳 .ff-app 固定 100dvh 且 overflow: hidden，真正的滚动发生在内层容器
 *   （App.vue 中 [data-scroll-container]，overflow-y: auto）。vue-router 的
 *   scrollBehavior 只作用于 window，对该容器无效；而路由切换使用 out-in 转场，
 *   旧组件先被卸载，容器内容高度塌缩为 0，浏览器随之把 scrollTop 钳制回 0 ——
 *   于是「跳转他页再返回」时总是停在顶部，浏览位置丢失。
 *
 * 解决思路：
 *   1. 记录：组件挂载期间监听容器 scroll（passive + rAF 节流）持续留存最新位置；
 *      onBeforeUnmount 时再补读一次兜底。相比只在卸载瞬间取值，持续记录不依赖
 *      任何卸载时序，转场动画期间也不会丢值。
 *   2. 恢复：onMounted 后启动 rAF 轮询。数据为异步加载，内容高度逐帧增长，
 *      只有 scrollHeight 足够时目标位置才能写进去，因此需重试到写入成功或超时；
 *      内容未就绪前不写入，避免被钳制到半途造成视觉跳动。
 *   3. 体验保护：恢复期间临时关闭容器的 scroll-behavior: smooth（否则会「缓慢滑回」）；
 *      用户在恢复过程中主动滚动 / 触摸 / 按键则立即中止，以用户意图为准。
 *
 * 作用域：模块级 Map，仅存活于当前 JS 运行时（覆盖组件卸载/挂载与路由切换），
 * 不做持久化 —— 整页刷新本就该回到顶部。
 *
 * 用法（在需要记忆滚动位置的路由组件内一行接入）：
 *   import { useScrollRestore } from '../composables/useScrollRestore'
 *   useScrollRestore()                    // 默认以当前路由 path 为 key
 *   useScrollRestore('limitup-ladder')   // 或显式指定 key
 */
import { onMounted, onBeforeUnmount, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'

// 应用唯一滚动容器：优先读语义化 data 属性，回退到样式类（兼容未打标的旧外壳）
const CONTAINER_SELECTOR = '[data-scroll-container], .ff-app__content'

// 恢复重试窗口：覆盖首屏渲染 + 异步取数（默认 3s，约 180 帧）；超时即放弃，不做半程跳转
const RESTORE_DEADLINE_MS = 3000

// 命中即视为「用户已接管滚动」，立即中止恢复
const ABORT_EVENTS = ['wheel', 'touchstart', 'keydown']

// key -> scrollTop；组件卸载后仍存活，供返回时复用
const positions = new Map()

function getContainer() {
  if (typeof document === 'undefined') return null
  return document.querySelector(CONTAINER_SELECTOR)
}

/**
 * 瞬时写入 scrollTop：临时关掉容器上的 scroll-behavior: smooth，
 * 否则 CSS 会把赋值变成平滑动画，出现肉眼可见的「滑回」过程。
 */
function writeScrollTop(el, top) {
  const prev = el.style.scrollBehavior
  el.style.scrollBehavior = 'auto'
  el.scrollTop = top
  const actual = el.scrollTop
  el.style.scrollBehavior = prev
  return actual
}

export function useScrollRestore(key) {
  const route = useRoute()
  const cacheKey = key || route.path

  let el = null
  let rafSave = 0
  let rafRestore = 0
  let timerId = 0
  let restoring = false

  // ── 记录 ────────────────────────────────────────────────────────────
  function snapshot() {
    if (restoring || !el) return
    // 卸载阶段容器内容会塌缩、元素也会被移出文档，浏览器随之把 scrollTop 钳回 0。
    // 这种「被动归零」不是用户行为，必须忽略 —— 否则会把真实浏览位置冲掉。
    //   · 元素已脱离文档：读取到的 0 无意义
    //   · 内容高度不足以滚动：说明正处于塌缩过程，保留上一次有效位置
    if (!el.isConnected) return
    if (el.scrollHeight <= el.clientHeight) return
    const top = el.scrollTop
    // 顶部状态无需记忆（默认即顶部），直接清掉旧值
    if (top > 0) positions.set(cacheKey, top)
    else positions.delete(cacheKey)
  }

  function onScroll() {
    if (restoring || rafSave || !el) return
    rafSave = requestAnimationFrame(() => {
      rafSave = 0
      snapshot()
    })
  }

  // ── 恢复 ────────────────────────────────────────────────────────────
  function stopRestore() {
    restoring = false
    if (rafRestore) {
      cancelAnimationFrame(rafRestore)
      rafRestore = 0
    }
    if (timerId) {
      clearTimeout(timerId)
      timerId = 0
    }
    for (const ev of ABORT_EVENTS) window.removeEventListener(ev, stopRestore)
  }

  function restore() {
    const target = positions.get(cacheKey)
    if (!target || target <= 0) return

    restoring = true
    const deadline = Date.now() + RESTORE_DEADLINE_MS
    // 恢复期间接管：用户主动交互即刻让位
    for (const ev of ABORT_EVENTS) {
      window.addEventListener(ev, stopRestore, { passive: true, once: true })
    }

    const step = () => {
      if (!restoring) return
      const container = getContainer()
      if (!container) {
        stopRestore()
        return
      }
      const maxTop = container.scrollHeight - container.clientHeight
      // 内容高度足够才写入，否则继续等下一帧（数据异步到位后高度会增长）
      if (maxTop >= target) {
        const actual = writeScrollTop(container, target)
        // 容差 1px：浏览器对小数 scrollTop 的取整
        if (Math.abs(actual - target) <= 1) {
          stopRestore()
          return
        }
      }
      if (Date.now() >= deadline) {
        // 超时：内容始终不足以容纳目标位置（数据未到位 / 内容变短），放弃恢复，
        // 不做「半程跳转」到容器底部，保持可预期的停在顶部
        stopRestore()
        return
      }
      rafRestore = requestAnimationFrame(step)
    }

    rafRestore = requestAnimationFrame(step)
    // 后台标签页 rAF 会被暂停，用定时器做硬性收口，避免轮询常驻
    timerId = setTimeout(stopRestore, RESTORE_DEADLINE_MS + 200)
  }

  onMounted(() => {
    el = getContainer()
    if (!el) return
    el.addEventListener('scroll', onScroll, { passive: true })
    restore()
  })

  // beforeUnmount 补读一次兜底。注意：实测中转场结束时旧元素可能已被移出文档，
  // 此处读到的值未必有效 —— 真正的位置来源是持续记录，snapshot() 内的两道守卫
  // （isConnected / 内容仍可滚动）会过滤掉卸载塌缩造成的「被动归零」。
  onBeforeUnmount(() => {
    if (rafSave) {
      cancelAnimationFrame(rafSave)
      rafSave = 0
    }
    snapshot()
  })

  onUnmounted(() => {
    stopRestore()
    if (el) {
      el.removeEventListener('scroll', onScroll)
      el = null
    }
  })

  return { positions }
}

export default useScrollRestore
