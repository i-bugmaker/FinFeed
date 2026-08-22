<script setup>
// 参数面板：功能信息头 + 动态参数表单 + 执行栏
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import AppBadge from '../../ui/AppBadge.vue'
import EasyTdxParamField from './EasyTdxParamField.vue'
import EasyTdxRunBar from './EasyTdxRunBar.vue'
import { useEasytdxStore } from '../../store/easytdx'
import { clientLabel } from './format'

const store = useEasytdxStore()

const func = computed(() => store.selectedFunc)

// 标的徽章模式：功能含 market/code 参数且与当前标的匹配
const badgeMode = computed(() => {
  if (!store.stock || !func.value) return false
  const hasCode = func.value.params?.some((p) => p.key === 'code')
  if (!hasCode) return false
  const code = store.params.code
  const codeMatched = code === '' || code === store.stock.code
  const hasMarket = func.value.params?.some((p) => p.key === 'market')
  const marketMatched = !hasMarket || store.params.market === store.stock.market
  return codeMatched && marketMatched
})

// 回测：当前选中策略 schema
const selectedStrategy = computed(() => {
  if (func.value?.group !== 'backtest') return null
  return store.strategies.find((s) => s.name === store.params.strategy) || null
})

function onStrategyChange(name) {
  const keep = { strategy: name }
  for (const k of Object.keys(store.params)) {
    if (k !== 'strategy') delete store.params[k]
  }
  store.params = { ...store.params, ...keep }
  const strat = store.strategies.find((s) => s.name === name)
  if (strat) {
    const next = { ...store.params }
    for (const p of strat.params || []) {
      if (!(p.name in next)) next[p.name] = p.default
    }
    store.params = next
  }
}
</script>

<template>
  <div class="etdx-param" v-if="func">
    <div class="etdx-param__head">
      <div class="etdx-param__title">
        <span class="etdx-param__title-text">{{ func.label }}</span>
        <div class="etdx-param__badges">
          <AppBadge variant="muted">{{ store.groupLabels[func.group] || func.group }}</AppBadge>
          <AppBadge variant="brand">{{ clientLabel(func.client) }}</AppBadge>
        </div>
      </div>
      <p v-if="func.help" class="etdx-param__help">{{ func.help }}</p>
    </div>

    <div class="etdx-param__body">
      <p v-if="!func.params || !func.params.length" class="etdx-param__none">
        该功能无需参数，点击下方「执行」即可。
      </p>

      <template v-for="param in func.params" :key="param.key">
        <EasyTdxParamField
          :param="param"
          :model="store.params"
          :strategies="store.strategies"
          :stock="store.stock"
          :badge-mode="badgeMode"
          @change-stock="store.clearStock()"
          @strategy-change="onStrategyChange"
        />
      </template>

      <!-- 回测策略的专属参数 -->
      <template v-if="selectedStrategy">
        <div class="etdx-param__subhead">
          <AppIcon name="sliders" size="sm" /> 策略参数 · {{ selectedStrategy.label }}
        </div>
        <div v-for="p in selectedStrategy.params" :key="'s_' + p.name" class="etdx-param__subfield">
          <EasyTdxParamField
            :param="{ key: p.name, label: p.label, type: 'number', minv: p.min, maxv: p.max, help: p.description }"
            :model="store.params"
          />
        </div>
      </template>
    </div>

    <div class="etdx-param__footer">
      <EasyTdxRunBar />
    </div>
  </div>

  <div v-else class="etdx-param etdx-param--empty">
    <AppIcon name="cpu" size="xl" />
    <p>从左侧选择一个功能开始</p>
  </div>
</template>

<style scoped>
.etdx-param {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.etdx-param__head {
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-param__title {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.etdx-param__title-text {
  font-size: var(--ff-fs-title-sm);
  font-weight: 700;
  color: var(--ff-text-primary);
}
.etdx-param__badges {
  display: flex;
  gap: 6px;
}
.etdx-param__help {
  margin: 8px 0 0;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
  line-height: 1.6;
}
.etdx-param__body {
  flex: 1;
  min-height: 0;
  padding: var(--ff-space-3) var(--ff-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  overflow-y: auto;
}
.etdx-param__none {
  margin: 0;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
}
.etdx-param__subhead {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-top: var(--ff-space-2);
  padding-top: var(--ff-space-3);
  border-top: 1px dashed var(--ff-border-subtle);
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-param__subfield {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.etdx-param__footer {
  padding: var(--ff-space-3) var(--ff-space-4);
  border-top: 1px solid var(--ff-border-subtle);
}
.etdx-param--empty {
  align-items: center;
  justify-content: center;
  gap: var(--ff-space-2);
  color: var(--ff-text-tertiary);
  text-align: center;
  padding: var(--ff-space-10) var(--ff-space-4);
}
.etdx-param--empty p {
  margin: 0;
  font-size: var(--ff-fs-body-sm);
}
</style>
