<script setup>
// 增强数据表格：排序 / 列过滤 / 固定列 / 虚拟滚动 / 行详情抽屉 / CSV 导出
import { ref, computed, watch, nextTick } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import { columnLabel, cellText, isLink, fullText, cellColor } from './format'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  rows: { type: Array, default: () => [] }, // 二维数组
  stockNames: { type: Object, default: () => ({}) },
  truncated: { type: Boolean, default: false },
  totalRows: { type: Number, default: 0 },
})

const ROW_H = 36
const DEFAULT_PINNED = ['code', 'name']

// ---------------- 排序 / 过滤 ----------------
const sortKey = ref('')
const sortDir = ref('') // '' | asc | desc
const filters = ref({}) // col -> 过滤文本

function toggleSort(col) {
  if (sortKey.value !== col) {
    sortKey.value = col
    sortDir.value = 'asc'
  } else if (sortDir.value === 'asc') {
    sortDir.value = 'desc'
  } else {
    sortKey.value = ''
    sortDir.value = ''
  }
}

function setFilter(col, v) {
  filters.value = { ...filters.value, [col]: v }
}

const processedRows = computed(() => {
  let rs = props.rows
  // 过滤
  const activeFilters = Object.entries(filters.value).filter(([, v]) => v && v.trim())
  if (activeFilters.length) {
    rs = rs.filter((row) =>
      activeFilters.every(([col, v]) => {
        const idx = props.columns.indexOf(col)
        if (idx < 0) return true
        return String(row[idx] ?? '').toLowerCase().includes(v.trim().toLowerCase())
      }),
    )
  }
  // 排序
  if (sortKey.value && sortDir.value) {
    const idx = props.columns.indexOf(sortKey.value)
    const dir = sortDir.value === 'asc' ? 1 : -1
    rs = rs.slice().sort((a, b) => {
      const av = a[idx]
      const bv = b[idx]
      const an = Number(av)
      const bn = Number(bv)
      if (Number.isFinite(an) && Number.isFinite(bn)) return (an - bn) * dir
      return String(av ?? '').localeCompare(String(bv ?? ''), 'zh-CN') * dir
    })
  }
  return rs
})

// ---------------- 固定列 ----------------
const pinned = ref([...DEFAULT_PINNED])
function isPinned(col) {
  return pinned.value.includes(col)
}
function togglePin(col) {
  const next = pinned.value.slice()
  const i = next.indexOf(col)
  if (i >= 0) next.splice(i, 1)
  else next.push(col)
  pinned.value = next
}

// ---------------- 虚拟滚动 ----------------
const scrollRef = ref(null)
const scrollTop = ref(0)
const viewH = ref(400)

function onScroll() {
  scrollTop.value = scrollRef.value?.scrollTop || 0
}
function measure() {
  viewH.value = scrollRef.value?.clientHeight || 400
}
watch(scrollRef, () => {
  if (scrollRef.value) {
    measure()
    nextTick(measure)
  }
})

const virtualEnabled = computed(() => processedRows.value.length > 200)
const startIdx = computed(() => {
  if (!virtualEnabled.value) return 0
  return Math.max(0, Math.floor(scrollTop.value / ROW_H) - 10)
})
const endIdx = computed(() => {
  if (!virtualEnabled.value) return processedRows.value.length
  return Math.min(processedRows.value.length, Math.ceil((scrollTop.value + viewH.value) / ROW_H) + 10)
})
const visibleRows = computed(() => processedRows.value.slice(startIdx.value, endIdx.value))

// ---------------- 行详情 ----------------
const detailRow = ref(null)
function openDetail(row) {
  detailRow.value = row
}
function closeDetail() {
  detailRow.value = null
}
const detailEntries = computed(() => {
  if (!detailRow.value) return []
  return props.columns.map((col, i) => ({
    col,
    label: columnLabel(col),
    value: detailRow.value[i],
  }))
})

// ---------------- 单元格渲染 ----------------
function fmtCell(v, col) {
  const c = String(col || '').toLowerCase()
  if (c === 'code' && typeof v === 'string' && /^\d{6}$/.test(v)) {
    const name = props.stockNames[v]
    if (name) return `${name} (${v})`
  }
  return cellText(v, col)
}

// ---------------- 导出 CSV ----------------
function exportCsv() {
  const head = props.columns.map(columnLabel).join(',')
  const lines = processedRows.value.map((row) =>
    row.map((v) => {
      const s = cellText(v, '')
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
    }).join(','),
  )
  const blob = new Blob(['\ufeff' + [head, ...lines].join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `easytdx_export_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ---------------- 复制 TSV ----------------
async function copyTsv() {
  const head = props.columns.map(columnLabel).join('\t')
  const lines = processedRows.value
    .slice(0, 500)
    .map((row) => row.map((v) => cellText(v, '')).join('\t'))
  const text = [head, ...lines].join('\n')
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}
</script>

<template>
  <div class="etdx-table">
    <!-- 统一滚动容器：表头 sticky 顶置，横向滚动与行体同步 -->
    <div ref="scrollRef" class="etdx-table__scroll" @scroll="onScroll">
      <!-- 表头（纵向 sticky） -->
      <div class="etdx-table__head">
        <div
          v-for="(col, ci) in columns"
          :key="col"
          class="etdx-table__th"
          :class="[
            isPinned(col) && 'is-pinned',
            sortKey === col && `is-sorted-${sortDir}`,
          ]"
          :style="{ left: isPinned(col) ? (columns.slice(0, ci).filter((c) => isPinned(c)).length * 140) + 'px' : undefined }"
          @click="toggleSort(col)"
        >
          <span class="etdx-table__th-label">
            {{ columnLabel(col) }}
            <span v-if="sortKey === col" class="etdx-table__sort">
              <AppIcon :name="sortDir === 'asc' ? 'chevron-up' : 'chevron-down'" size="xs" />
            </span>
          </span>
          <span class="etdx-table__th-actions" @click.stop>
            <button
              type="button"
              class="etdx-table__pin ff-hit"
              :class="{ 'is-pinned': isPinned(col) }"
              :title="isPinned(col) ? '取消固定' : '固定该列'"
              @click="togglePin(col)"
            >
              <AppIcon name="pin" size="xs" />
            </button>
          </span>
        </div>
      </div>

      <!-- 过滤提示行 -->
      <div v-if="Object.keys(filters).some((k) => filters[k])" class="etdx-table__filterbar">
        <span class="etdx-table__filterinfo">
          <AppIcon name="filter" size="xs" />
          {{ Object.values(filters).filter(Boolean).length }} 个过滤条件 · 命中 {{ processedRows.length }} 行
          <button type="button" class="etdx-table__clearfilter" @click="filters = {}">清除</button>
        </span>
      </div>

      <!-- 行体（虚拟滚动：spacer 撑高 + 绝对定位行） -->
      <div
        class="etdx-table__spacer"
        :style="{ height: processedRows.length * ROW_H + 'px', minWidth: Math.max(columns.length * 140, 100) + 'px' }"
      >
        <div
          v-for="(row, vi) in visibleRows"
          :key="startIdx + vi"
          class="etdx-table__tr"
          :style="{ transform: `translateY(${(startIdx + vi) * ROW_H}px)` }"
          @click="openDetail(row)"
        >
          <div
            v-for="(col, ci) in columns"
            :key="col"
            class="etdx-table__td"
            :class="[isPinned(col) && 'is-pinned', cellColor(row[ci], col)]"
            :style="{ left: isPinned(col) ? (columns.slice(0, ci).filter((c) => isPinned(c)).length * 140) + 'px' : undefined }"
          >
            <a
              v-if="isLink(row[ci], col)"
              :href="row[ci]"
              target="_blank"
              rel="noopener"
              class="etdx-table__link"
              @click.stop
            >打开链接</a>
            <span v-else :title="fullText(row[ci])">{{ fmtCell(row[ci], col) }}</span>
          </div>
        </div>
        <div v-if="!processedRows.length" class="etdx-table__empty">无匹配数据</div>
      </div>
    </div>

    <!-- 行详情抽屉 -->
    <Teleport to="body">
      <Transition name="ff-overlay">
        <div v-if="detailRow" class="etdx-table__mask" @click.self="closeDetail">
          <Transition name="ff-drawer-right">
            <div class="etdx-table__drawer" role="dialog" aria-modal="true">
              <div class="etdx-table__drawer-head">
                <span class="etdx-table__drawer-title">行详情</span>
                <button type="button" class="etdx-table__drawer-close ff-hit" aria-label="关闭" @click="closeDetail">
                  <AppIcon name="x" size="sm" />
                </button>
              </div>
              <div class="etdx-table__drawer-body">
                <div v-for="e in detailEntries" :key="e.col" class="etdx-table__drawer-row">
                  <span class="etdx-table__drawer-k">{{ e.label }}</span>
                  <span class="etdx-table__drawer-v">
                    <a
                      v-if="isLink(e.value, e.col)"
                      :href="e.value"
                      target="_blank"
                      rel="noopener"
                      class="etdx-table__link"
                    >打开链接</a>
                    <template v-else>{{ fmtCell(e.value, e.col) }}</template>
                  </span>
                </div>
              </div>
            </div>
          </Transition>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.etdx-table {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.etdx-table__head {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  min-width: max-content;
  border-bottom: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
}
.etdx-table__filterbar {
  position: sticky;
  top: 33px;
  z-index: 4;
  display: flex;
  align-items: center;
  padding: 6px 10px;
  background: var(--ff-bg-subtle);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
}
.etdx-table__filterinfo {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.etdx-table__clearfilter {
  border: none;
  background: transparent;
  color: var(--ff-text-brand);
  cursor: pointer;
  font-size: var(--ff-fs-caption);
  font-weight: 600;
}
.etdx-table__scroll {
  position: relative;
  height: 420px;
  overflow: auto;
}
.etdx-table__spacer {
  position: relative;
}
.etdx-table__th {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 140px;
  max-width: 260px;
  padding: 8px 10px;
  font-size: var(--ff-fs-caption);
  font-weight: 700;
  color: var(--ff-text-secondary);
  cursor: pointer;
  user-select: none;
  border-right: 1px solid var(--ff-border-subtle);
}
.etdx-table__th:hover {
  color: var(--ff-text-primary);
  background: var(--ff-bg-hover);
}
.etdx-table__th.is-pinned {
  position: sticky;
  z-index: 3;
  background: var(--ff-bg-muted);
  box-shadow: 1px 0 0 var(--ff-border);
}
.etdx-table__th-label {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.etdx-table__sort {
  color: var(--ff-text-brand);
}
.etdx-table__th-actions {
  margin-left: auto;
  display: inline-flex;
}
.etdx-table__pin {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: var(--ff-radius-xs);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
  opacity: 0;
}
.etdx-table__th:hover .etdx-table__pin,
.etdx-table__pin.is-pinned {
  opacity: 1;
}
.etdx-table__pin.is-pinned {
  color: var(--ff-text-brand);
}
.etdx-table__tr {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  display: flex;
  min-width: max-content;
  height: 36px;
  border-bottom: 1px solid var(--ff-border-subtle);
  cursor: pointer;
  background: var(--ff-bg-surface);
}
.etdx-table__tr:nth-child(even) {
  background: var(--ff-bg-subtle);
}
.etdx-table__tr:hover {
  background: var(--ff-bg-muted);
}
.etdx-table__td {
  display: flex;
  align-items: center;
  min-width: 140px;
  max-width: 260px;
  padding: 0 10px;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  border-right: 1px solid var(--ff-border-subtle);
}
.etdx-table__td.is-pinned {
  position: sticky;
  z-index: 2;
  background: inherit;
  box-shadow: 1px 0 0 var(--ff-border);
}
.etdx-table__td.is-up {
  color: var(--ff-up-text);
}
.etdx-table__td.is-down {
  color: var(--ff-down-text);
}
.etdx-table__td.is-warn {
  color: var(--ff-warn-text);
}
.etdx-table__link {
  color: var(--ff-text-brand);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.etdx-table__empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body-sm);
}
/* 行详情抽屉 */
.etdx-table__mask {
  position: fixed;
  inset: 0;
  z-index: 1200;
  background: var(--ff-bg-overlay);
}
.etdx-table__drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(420px, 90vw);
  background: var(--ff-bg-surface);
  box-shadow: var(--ff-shadow-xl);
  display: flex;
  flex-direction: column;
  animation: etdx-drawer-in 200ms var(--ff-ease-decelerate);
}
@keyframes etdx-drawer-in {
  from { transform: translateX(24px); opacity: 0; }
  to { transform: translateX(0); opacity: 1; }
}
.etdx-table__drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-table__drawer-title {
  font-weight: 700;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-primary);
}
.etdx-table__drawer-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
}
.etdx-table__drawer-close:hover {
  background: var(--ff-bg-hover);
}
.etdx-table__drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--ff-space-3) var(--ff-space-4);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.etdx-table__drawer-row {
  display: flex;
  justify-content: space-between;
  gap: var(--ff-space-3);
  font-size: var(--ff-fs-body-sm);
  padding-bottom: 8px;
  border-bottom: 1px dashed var(--ff-border-subtle);
}
.etdx-table__drawer-k {
  color: var(--ff-text-secondary);
  flex-shrink: 0;
}
.etdx-table__drawer-v {
  color: var(--ff-text-primary);
  font-family: var(--ff-font-mono, monospace);
  word-break: break-all;
  text-align: right;
}

/* ── 移动端适配（D4）：窄屏表格横向滚动 ── */
@media (max-width: 768px) {
  .etdx-table {
    min-width: 720px;
  }
}
</style>
