<script setup>
// 结果工具条：复制 / 导出 CSV / 导出 JSON / 重新执行 / 截断提示
import AppIcon from '../../ui/AppIcon.vue'
import { columnLabel, cellText } from './format'
import { toast } from '../../composables/useToast'

const props = defineProps({
  result: { type: Object, default: null },
  rerunning: { type: Boolean, default: false },
})
const emit = defineEmits(['rerun', 'fullscreen'])

function downloadBlob(filename, content, mime) {
  const blob = new Blob([content], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function exportCsv() {
  const r = props.result
  if (!r || r.type !== 'table') return
  const head = r.columns.map(columnLabel).join(',')
  const lines = r.rows.map((row) =>
    row.map((v) => {
      const s = cellText(v, '')
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
    }).join(','),
  )
  downloadBlob(`easytdx_${new Date().toISOString().slice(0, 10)}.csv`, '\ufeff' + [head, ...lines].join('\n'), 'text/csv;charset=utf-8')
  toast({ type: 'success', message: '已导出 CSV' })
}

function exportJson() {
  const r = props.result
  if (!r) return
  downloadBlob(`easytdx_${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(r, null, 2), 'application/json')
  toast({ type: 'success', message: '已导出 JSON' })
}

async function copy() {
  const r = props.result
  if (!r) return
  const head = r.columns ? r.columns.map(columnLabel).join('\t') : ''
  const lines = r.rows
    ? r.rows.slice(0, 500).map((row) => row.map((v) => cellText(v, '')).join('\t'))
    : []
  const text = head ? [head, ...lines].join('\n') : JSON.stringify(r, null, 2)
  try {
    await navigator.clipboard.writeText(text)
    toast({ type: 'success', message: '已复制到剪贴板' })
  } catch {
    toast({ type: 'error', message: '复制失败，请手动选择复制' })
  }
}
</script>

<template>
  <div class="etdx-rtb">
    <div class="etdx-rtb__meta">
      <AppIcon name="list" size="sm" />
      <span v-if="result?.type === 'table'">
        {{ result.row_count }} 行 × {{ result.columns.length }} 列
      </span>
      <span v-else-if="result?.type === 'json'">JSON 结果</span>
      <span v-else>结果</span>
      <span v-if="result?.truncated" class="etdx-rtb__truncated">
        （已截断显示前 {{ result.rows.length }} 行）
      </span>
    </div>

    <div class="etdx-rtb__actions">
      <button
        v-if="result?.type === 'table'"
        type="button"
        class="etdx-rtb__btn"
        title="复制为 TSV"
        @click="copy"
      >
        <AppIcon name="copy" size="xs" /> 复制
      </button>
      <button
        v-if="result?.type === 'table'"
        type="button"
        class="etdx-rtb__btn"
        title="导出 CSV"
        @click="exportCsv"
      >
        <AppIcon name="file-csv" size="xs" /> CSV
      </button>
      <button
        type="button"
        class="etdx-rtb__btn"
        title="导出原始 JSON"
        @click="exportJson"
      >
        <AppIcon name="file-json" size="xs" /> JSON
      </button>
      <button type="button" class="etdx-rtb__btn" title="全屏查看" @click="emit('fullscreen')">
        <AppIcon name="monitor" size="xs" /> 全屏
      </button>
      <button
        type="button"
        class="etdx-rtb__btn"
        :disabled="rerunning"
        title="重新执行当前功能"
        @click="emit('rerun')"
      >
        <AppIcon name="refresh" size="xs" :spin="rerunning" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.etdx-rtb {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-2) var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
  flex-wrap: wrap;
}
.etdx-rtb__meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  margin-right: auto;
}
.etdx-rtb__truncated {
  color: var(--ff-text-warning, #b7791f);
}
.etdx-rtb__actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.etdx-rtb__btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-sm);
  background: var(--ff-bg-surface);
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-caption);
  cursor: pointer;
  transition: border-color var(--ff-dur-fast), color var(--ff-dur-fast), background var(--ff-dur-fast);
}
.etdx-rtb__btn:hover:not(:disabled) {
  border-color: var(--ff-border-brand);
  color: var(--ff-text-brand);
  background: var(--ff-bg-hover);
}
.etdx-rtb__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
