<script setup>
// 执行栏：执行 / 中止按钮 + 校验提示 + 状态反馈
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import AppButton from '../../ui/AppButton.vue'
import { useEasytdxStore } from '../../store/easytdx'

const store = useEasytdxStore()

const func = computed(() => store.selectedFunc)

// 必填校验：当前仅检查「需个股参数的函数在无标的下不可执行」
const blocked = computed(() => {
  if (!func.value) return false
  const needsStock =
    func.value.params?.some((p) => p.key === 'code') ||
    func.value.params?.some((p) => p.key === 'stocks')
  return needsStock && !store.stock
})

function onRun() {
  if (store.running) return
  if (blocked.value) {
    store.errMsg = '请先选择股票标的（输入名称或代码），再执行「' + func.value.label + '」'
    return
  }
  store.run()
}

function onAbort() {
  store.stopPolling()
  store.task = null
  store.running = false
}
</script>

<template>
  <div class="etdx-runbar">
    <AppButton
      v-if="!store.running"
      variant="primary"
      block
      icon="play"
      :disabled="blocked"
      title="执行当前功能"
      @click="onRun"
    >
      执行{{ func ? ' · ' + func.label : '' }}
    </AppButton>

    <div v-else class="etdx-runbar__running">
      <span class="etdx-runbar__spinner">
        <AppIcon name="refresh" size="md" spin />
      </span>
      <span class="etdx-runbar__text">执行中… {{ store.task?.progress || 0 }}%</span>
      <AppButton variant="danger-ghost" size="sm" icon="x" @click="onAbort">
        中止
      </AppButton>
    </div>

    <p v-if="blocked && !store.running" class="etdx-runbar__hint">
      该功能需要个股标的，请先在顶部选择股票
    </p>
  </div>
</template>

<style scoped>
.etdx-runbar {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.etdx-runbar__running {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 10px 12px;
  background: var(--ff-bg-brand-subtle);
  border: 1px solid var(--ff-border-brand-subtle);
  border-radius: var(--ff-radius-md);
}
.etdx-runbar__spinner {
  color: var(--ff-text-brand);
  display: inline-flex;
}
.etdx-runbar__text {
  flex: 1;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-brand);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.etdx-runbar__hint {
  margin: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-warning);
}
</style>
