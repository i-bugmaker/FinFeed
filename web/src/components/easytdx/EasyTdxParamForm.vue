<script setup>
import { computed } from 'vue'
import AppInput from '../../ui/AppInput.vue'
import AppSelect from '../../ui/AppSelect.vue'
import AppSwitch from '../../ui/AppSwitch.vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  func: { type: Object, required: true },
  model: { type: Object, required: true }, // 参数键值（响应式）
  strategies: { type: Array, default: () => [] }, // 回测策略 [{name,label,params}]
})

// 枚举选项 → AppSelect 期望的 { label, value }
function enumOptions(param) {
  return (param.options || []).map((o) => ({ label: o.label, value: o.value }))
}

// 回测：当前选中策略的 schema，用于动态渲染子参数
const selectedStrategy = computed(() => {
  if (props.func.group !== 'backtest') return null
  return props.strategies.find((s) => s.name === props.model.strategy) || null
})

function onStrategyChange(name) {
  // 切换策略时重置其专属参数，仅保留公共字段
  const keep = { strategy: name }
  for (const k of Object.keys(props.model)) {
    if (k !== 'strategy') delete props.model[k]
  }
  Object.assign(props.model, keep)
  // 填入默认值
  const strat = props.strategies.find((s) => s.name === name)
  if (strat) {
    for (const p of strat.params || []) {
      if (!(p.name in props.model)) props.model[p.name] = p.default
    }
  }
}
</script>

<template>
  <div class="etdx-form">
    <p v-if="!func.params || !func.params.length" class="etdx-form__none">
      该功能无需参数。
    </p>

    <div v-for="param in func.params" :key="param.key" class="etdx-form__row">
      <!-- 枚举 -->
      <AppSelect
        v-if="param.type === 'enum'"
        v-model="model[param.key]"
        :label="param.label"
        :options="enumOptions(param)"
        :placeholder="param.placeholder || '请选择'"
        :hint="param.help"
      />
      <!-- 布尔 -->
      <div v-else-if="param.type === 'bool'" class="etdx-form__bool">
        <span class="etdx-form__bool-label">{{ param.label }}</span>
        <AppSwitch :model-value="model[param.key]" @change="(v) => (model[param.key] = v)" />
        <span v-if="param.help" class="etdx-form__bool-hint">{{ param.help }}</span>
      </div>
      <!-- 数字 -->
      <AppInput
        v-else-if="param.type === 'number'"
        v-model="model[param.key]"
        type="number"
        :label="param.label"
        :placeholder="param.placeholder"
        :hint="param.help"
        :min="param.minv"
        :max="param.maxv"
        :step="param.step"
      />
      <!-- 日期整数 YYYYMMDD -->
      <AppInput
        v-else-if="param.type === 'dateint'"
        v-model="model[param.key]"
        :label="param.label"
        :placeholder="param.placeholder || 'YYYYMMDD'"
        :hint="param.help"
      />
      <!-- 股票列表（多行） -->
      <div v-else-if="param.type === 'stocklist'" class="etdx-form__field">
        <label class="ff-field__label">{{ param.label }}</label>
        <textarea
          v-model="model[param.key]"
          class="etdx-form__textarea"
          :placeholder="param.placeholder || '每行一只：市场 代码'"
          rows="3"
        ></textarea>
        <p v-if="param.help" class="ff-field__message">{{ param.help }}</p>
      </div>
      <!-- 策略（回测） -->
      <AppSelect
        v-else-if="param.type === 'strategy'"
        v-model="model[param.key]"
        :label="param.label"
        :options="strategies.map((s) => ({ label: s.label, value: s.name }))"
        placeholder="选择回测策略"
        :hint="param.help"
        @change="onStrategyChange"
      />
      <!-- 文本 兜底 -->
      <AppInput
        v-else
        v-model="model[param.key]"
        :label="param.label"
        :placeholder="param.placeholder"
        :hint="param.help"
      />
    </div>

    <!-- 回测策略的专属参数 -->
    <template v-if="selectedStrategy">
      <div class="etdx-form__subhead">
        <AppIcon name="sliders" size="sm" /> 策略参数 · {{ selectedStrategy.label }}
      </div>
      <div
        v-for="p in selectedStrategy.params"
        :key="'s_' + p.name"
        class="etdx-form__row"
      >
        <AppInput
          v-model="model[p.name]"
          type="number"
          :label="p.label"
          :min="p.min"
          :max="p.max"
          :hint="p.description"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.etdx-form {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.etdx-form__none {
  margin: 0;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
}
.etdx-form__bool {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2) 0;
}
.etdx-form__bool-label {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  font-weight: 500;
}
.etdx-form__bool-hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-form__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.etdx-form__textarea {
  width: 100%;
  resize: vertical;
  padding: var(--ff-space-2) var(--ff-space-3);
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-body-sm);
  font-family: var(--ff-font-mono, monospace);
  line-height: 1.5;
  outline: none;
  transition: border-color var(--ff-dur-fast);
}
.etdx-form__textarea:focus {
  border-color: var(--ff-border-brand);
}
.etdx-form__subhead {
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
</style>
