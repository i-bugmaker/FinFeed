<script setup>
// Zone A · 命令条：全局标的上下文 + 命令面板入口 + 聚焦模式 + 连接状态
import AppIcon from '../../ui/AppIcon.vue'
import EasyTdxStockPicker from './EasyTdxStockPicker.vue'
import { useEasytdxStore } from '../../store/easytdx'

const store = useEasytdxStore()

function onSelectStock(s) {
  store.selectStock(s)
}

function onClearStock() {
  store.clearStock()
}
</script>

<template>
  <header class="etdx-cmdbar">
    <div class="etdx-cmdbar__brand">
      <span class="etdx-cmdbar__logo">
        <AppIcon name="cpu" size="lg" />
      </span>
      <div class="etdx-cmdbar__title">
        <h1 class="etdx-cmdbar__name">easy-tdx 数据源</h1>
        <p class="etdx-cmdbar__sub">通达信 / Mac / 扩展行情 / 巨潮 / 缠论 / 回测</p>
      </div>
    </div>

    <div class="etdx-cmdbar__stock">
      <EasyTdxStockPicker
        :stock="store.stock"
        compact
        placeholder="输入股票名称 / 代码查询"
        @select="onSelectStock"
        @clear="onClearStock"
        @change-stock="onClearStock"
      />
    </div>

    <div class="etdx-cmdbar__actions">
      <span v-if="store.funcCount" class="etdx-cmdbar__count" title="可用功能数">
        {{ store.funcCount }} 项功能
      </span>
      <button
        type="button"
        class="etdx-cmdbar__btn"
        :class="{ 'is-active': store.ui.paletteOpen }"
        title="搜索功能"
        @click="store.setPalette(true)"
      >
        <AppIcon name="search" size="sm" />
        <span class="etdx-cmdbar__btn-label">搜索功能</span>
      </button>
      <button
        type="button"
        class="etdx-cmdbar__btn"
        :class="{ 'is-active': store.ui.focusMode }"
        title="聚焦模式：隐藏导航与参数，结果全宽"
        @click="store.toggleFocusMode()"
      >
        <AppIcon name="panel-left" size="sm" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.etdx-cmdbar {
  display: flex;
  align-items: center;
  gap: var(--ff-space-4);
  flex-wrap: wrap;
  margin-bottom: var(--ff-space-4);
}
.etdx-cmdbar__brand {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  min-width: 240px;
}
.etdx-cmdbar__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: var(--ff-radius-lg);
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
  flex-shrink: 0;
}
.etdx-cmdbar__title h1 {
  font-size: var(--ff-fs-title-sm);
  font-weight: 800;
  color: var(--ff-text-primary);
  line-height: 1.3;
}
.etdx-cmdbar__sub {
  margin: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-cmdbar__stock {
  flex: 1;
  min-width: 240px;
  max-width: 460px;
}
.etdx-cmdbar__actions {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-left: auto;
}
.etdx-cmdbar__count {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 3px 10px;
  white-space: nowrap;
}
.etdx-cmdbar__btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 12px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  cursor: pointer;
  transition: border-color var(--ff-dur-fast), background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.etdx-cmdbar__btn:hover {
  border-color: var(--ff-border-brand);
  color: var(--ff-text-primary);
  background: var(--ff-bg-hover);
}
.etdx-cmdbar__btn.is-active {
  border-color: var(--ff-border-brand);
  color: var(--ff-text-brand);
  background: var(--ff-bg-brand-subtle);
}
.etdx-cmdbar__btn-label {
  white-space: nowrap;
}
@media (max-width: 768px) {
  .etdx-cmdbar__btn-label,
  .etdx-cmdbar__count {
    display: none;
  }
}
</style>
