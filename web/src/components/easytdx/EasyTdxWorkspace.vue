<script setup>
// Zone C · 工作区：参数面板（左） + 结果面板（右），支持拖拽分栏与参数面板折叠
import { ref, onBeforeUnmount, computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import EasyTdxParamPanel from './EasyTdxParamPanel.vue'
import EasyTdxResultPanel from './EasyTdxResultPanel.vue'
import { useEasytdxStore } from '../../store/easytdx'

const store = useEasytdxStore()
const wsRef = ref(null)

const dragging = ref(false)

// 拖拽分栏（pointer 事件）
function onSplitterDown(e) {
  if (!wsRef.value) return
  const container = wsRef.value.getBoundingClientRect()
  const startX = e.clientX
  const startW = store.ui.paneWidth
  dragging.value = true
  e.preventDefault()
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  const onMove = (ev) => {
    let w = startW + (ev.clientX - startX)
    const maxW = Math.max(320, container.width - 420)
    w = Math.min(Math.max(280, w), maxW)
    // 吸附点
    for (const snap of [320, 360, 480]) {
      if (Math.abs(w - snap) <= 12) {
        w = snap
        break
      }
    }
    store.ui.paneWidth = w
  }
  const onUp = () => {
    dragging.value = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}

function resetPane() {
  store.ui.paneWidth = 320
}

onBeforeUnmount(() => {
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
})
</script>

<template>
  <div ref="wsRef" class="etdx-ws" :class="{ 'is-dragging': dragging }">
    <!-- 参数面板 -->
    <section
      v-if="store.ui.paramPanelOpen"
      class="etdx-ws__param"
      :style="{ width: store.ui.paneWidth + 'px' }"
    >
      <div class="etdx-ws__param-head">
        <span class="etdx-ws__param-title">参数</span>
        <button
          type="button"
          class="etdx-ws__icon-btn"
          title="收起参数面板"
          @click="store.toggleParamPanel()"
        >
          <AppIcon name="chevrons-left" size="sm" />
        </button>
      </div>
      <div class="etdx-ws__param-body">
        <EasyTdxParamPanel />
      </div>
    </section>

    <!-- 分隔条 -->
    <div
      v-if="store.ui.paramPanelOpen"
      class="etdx-ws__splitter"
      title="拖动调整参数区宽度，双击复位"
      @pointerdown="onSplitterDown"
      @dblclick="resetPane"
    />

    <!-- 结果面板 -->
    <section class="etdx-ws__result">
      <div v-if="!store.ui.paramPanelOpen" class="etdx-ws__result-toolbar">
        <button
          type="button"
          class="etdx-ws__icon-btn"
          title="展开参数面板"
          @click="store.toggleParamPanel()"
        >
          <AppIcon name="sliders" size="sm" />
          <span>参数</span>
        </button>
      </div>
      <EasyTdxResultPanel />
    </section>
  </div>
</template>

<style scoped>
.etdx-ws {
  display: flex;
  align-items: stretch;
  min-height: 480px;
  min-width: 0;
  position: relative;
}
.etdx-ws__param {
  flex-shrink: 0;
  max-width: 560px;
  min-width: 280px;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-self: flex-start;
  transition: width 140ms var(--ff-ease-standard);
}
.etdx-ws.is-dragging .etdx-ws__param {
  transition: none;
}
.etdx-ws__param-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ff-space-2-5) var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-ws__param-title {
  font-size: var(--ff-fs-body-sm);
  font-weight: 700;
  color: var(--ff-text-secondary);
}
.etdx-ws__param-body {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
  max-height: calc(100vh - 220px);
}
.etdx-ws__splitter {
  flex-shrink: 0;
  width: 8px;
  margin: 0 -4px;
  cursor: col-resize;
  position: relative;
  z-index: 2;
}
.etdx-ws__splitter::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 3px;
  width: 2px;
  background: transparent;
  border-radius: 2px;
  transition: background var(--ff-dur-fast);
}
.etdx-ws__splitter:hover::after,
.etdx-ws.is-dragging .etdx-ws__splitter::after {
  background: var(--ff-border-brand);
}
.etdx-ws__result {
  flex: 1;
  min-width: 0;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.etdx-ws__result-toolbar {
  display: flex;
  align-items: center;
  padding: var(--ff-space-2) var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-ws__icon-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  cursor: pointer;
  transition: border-color var(--ff-dur-fast), color var(--ff-dur-fast), background var(--ff-dur-fast);
}
.etdx-ws__icon-btn:hover {
  border-color: var(--ff-border-brand);
  color: var(--ff-text-brand);
  background: var(--ff-bg-hover);
}
@media (max-width: 1023px) {
  .etdx-ws {
    flex-direction: column;
    min-height: 0;
  }
  .etdx-ws__param {
    width: 100% !important;
    max-width: none;
  }
  .etdx-ws__param-body {
    max-height: 40vh;
  }
  .etdx-ws__splitter {
    display: none;
  }
}
</style>
