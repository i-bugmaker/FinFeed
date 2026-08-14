/**
 * useAutoToday — 日期选择框「默认当日 + 随时间自动更新」逻辑
 *
 * 行为：
 *  - 初始化即选中本地当日（YYYY-MM-DD），满足「默认选中当日日期」。
 *  - 若用户未手动改过日期（touched=false），每隔 interval 毫秒重新校准为「当前日期」，
 *    跨午夜、跨交易日时自动滚动到新的当日，满足「随时间自动更新为当前日期」。
 *  - 用户一旦手动选择（markTouched）即停止自动覆盖，尊重用户意图；
 *    提供 reset() 一键回到「自动跟随今日」。
 *
 * 用法：
 *  const { date, touched, markTouched, reset } = useAutoToday()
 *  <AppDatePicker v-model="date" @change="markTouched" />
 */
import { ref, onMounted, onUnmounted } from 'vue'

export function todayStr() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export function useAutoToday(options = {}) {
  const { interval = 60000, enabled = true } = options
  const date = ref(todayStr())
  const touched = ref(false)
  let timer = null

  function syncToday() {
    if (touched.value) return
    const t = todayStr()
    if (t !== date.value) date.value = t
  }

  function markTouched() {
    touched.value = true
  }

  function reset() {
    touched.value = false
    date.value = todayStr()
  }

  onMounted(() => {
    if (enabled) {
      // 立刻校准一次，避免挂载时与真实当前日期存在时区/时序偏差
      syncToday()
      timer = setInterval(syncToday, interval)
    }
  })

  onUnmounted(() => {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })

  return { date, touched, markTouched, reset, syncToday }
}
