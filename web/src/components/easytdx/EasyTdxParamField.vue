<script setup>
// 参数单项：按类型渲染（enum / bool / number / dateint / stocklist / strategy / text）+ 标的徽章
import AppInput from '../../ui/AppInput.vue'
import AppSelect from '../../ui/AppSelect.vue'
import AppSwitch from '../../ui/AppSwitch.vue'

const props = defineProps({
  param: { type: Object, required: true },
  model: { type: Object, required: true },
  strategies: { type: Array, default: () => [] },
  stock: { type: Object, default: null },
  badgeMode: { type: Boolean, default: false },
})
const emit = defineEmits(['change-stock', 'strategy-change'])

function enumOptions(param) {
  return (param.options || []).map((o) => ({ label: o.label, value: o.value }))
}

function isStockCode(param) {
  return props.badgeMode && param.key === 'code'
}
function isStockMarket(param) {
  return props.badgeMode && param.key === 'market'
}
function isStockHidden(param) {
  return isStockCode(param) || isStockMarket(param)
}
</script>

<template>
  <div class="etdx-field">
    <!-- 标的徽章（替代 market/code 裸输入） -->
    <div v-if="isStockCode(param) && stock" class="etdx-field__stock">
      <label class="ff-field__label">标的</label>
      <div class="etdx-field__stock-badge">
        <span class="etdx-field__stock-name">{{ stock.name }}</span>
        <span class="etdx-field__stock-code">{{ stock.code }}.{{ stock.market }}</span>
        <button type="button" class="etdx-field__stock-swap" @click="emit('change-stock')">
          更换
        </button>
      </div>
    </div>

    <template v-else-if="!isStockHidden(param)">
      <AppSelect
        v-if="param.type === 'enum'"
        v-model="model[param.key]"
        :label="param.label"
        :options="enumOptions(param)"
        :placeholder="param.placeholder || '请选择'"
        :hint="param.help"
      />
      <div v-else-if="param.type === 'bool'" class="etdx-field__bool">
        <span class="etdx-field__bool-label">{{ param.label }}</span>
        <AppSwitch :model-value="model[param.key]" @change="(v) => (model[param.key] = v)" />
        <span v-if="param.help" class="etdx-field__bool-hint">{{ param.help }}</span>
      </div>
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
      <AppInput
        v-else-if="param.type === 'dateint'"
        v-model="model[param.key]"
        :label="param.label"
        :placeholder="param.placeholder || 'YYYYMMDD'"
        :hint="param.help"
      />
      <div v-else-if="param.type === 'stocklist'" class="etdx-field__area">
        <label class="ff-field__label">{{ param.label }}</label>
        <textarea
          v-model="model[param.key]"
          class="etdx-field__textarea"
          :placeholder="param.placeholder || '每行一只：市场 代码'"
          rows="3"
        ></textarea>
        <p v-if="param.help" class="ff-field__message">{{ param.help }}</p>
      </div>
      <AppSelect
        v-else-if="param.type === 'strategy'"
        v-model="model[param.key]"
        :label="param.label"
        :options="strategies.map((s) => ({ label: s.label, value: s.name }))"
        placeholder="选择回测策略"
        :hint="param.help"
        @change="emit('strategy-change', $event)"
      />
      <AppInput
        v-else
        v-model="model[param.key]"
        :label="param.label"
        :placeholder="param.placeholder"
        :hint="param.help"
      />
    </template>
  </div>
</template>

<style scoped>
.etdx-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.etdx-field__stock {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.etdx-field__stock-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: 7px 8px 7px 12px;
  background: var(--ff-bg-brand-subtle);
  border: 1px solid var(--ff-border-brand-subtle);
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-body-sm);
  width: fit-content;
  max-width: 100%;
}
.etdx-field__stock-name {
  font-weight: 600;
  color: var(--ff-text-brand);
}
.etdx-field__stock-code {
  color: var(--ff-text-secondary);
  font-family: var(--ff-font-mono, monospace);
  font-size: var(--ff-fs-caption);
}
.etdx-field__stock-swap {
  margin-left: var(--ff-space-2);
  padding: 2px 8px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  cursor: pointer;
}
.etdx-field__stock-swap:hover {
  color: var(--ff-text-brand);
  border-color: var(--ff-border-brand);
}
.etdx-field__bool {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2) 0;
}
.etdx-field__bool-label {
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  font-weight: 500;
}
.etdx-field__bool-hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-field__area {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.etdx-field__textarea {
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
.etdx-field__textarea:focus {
  border-color: var(--ff-border-brand);
}

/* 窄屏：bool 行提示独占一行、徽章允许换行，避免挤压溢出 */
@media (max-width: 768px) {
  .etdx-field__bool {
    flex-wrap: wrap;
    row-gap: 2px;
  }
  .etdx-field__bool-hint {
    flex-basis: 100%;
  }
  .etdx-field__stock-badge {
    flex-wrap: wrap;
  }
}
</style>
