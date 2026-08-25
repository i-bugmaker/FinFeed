<script setup>
/**
 * ReportsView — 研究报告列表
 * 搜索 / 筛选 / 多选批量操作（删除、置顶）/ 状态徽标 / 失败重试入口。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppIcon from '../../ui/AppIcon.vue'
import AppInput from '../../ui/AppInput.vue'

const router = useRouter()
const store = useAiStore()

const q = ref('')
const pinnedOnly = ref(false)
const selected = ref(new Set())
const busy = ref(false)

const filtered = computed(() => {
  let list = store.reports
  if (pinnedOnly.value) list = list.filter((r) => r.pinned)
  const kw = q.value.trim().toLowerCase()
  if (kw) list = list.filter((r) => (r.title || '').toLowerCase().includes(kw) || (r.model || '').toLowerCase().includes(kw))
  // 严格按生成时间从新到旧排序（置顶不改变时间顺序）
  return [...list].sort((a, b) => (b.created_ts || 0) - (a.created_ts || 0))
})

const allSelected = computed(() => filtered.value.length > 0 && filtered.value.every((r) => selected.value.has(r.id)))
function toggleAll() {
  if (allSelected.value) selected.value.clear()
  else filtered.value.forEach((r) => selected.value.add(r.id))
}
function toggleOne(id) {
  if (selected.value.has(id)) selected.value.delete(id)
  else selected.value.add(id)
}

async function batchDelete() {
  if (!selected.value.size) return
  if (!window.confirm(`删除选中的 ${selected.value.size} 份报告？`)) return
  busy.value = true
  await store.deleteReports([...selected.value])
  selected.value.clear()
  busy.value = false
}
async function batchPin(pin) {
  if (!selected.value.size) return
  busy.value = true
  await store.pinReports([...selected.value], pin)
  selected.value.clear()
  busy.value = false
}
async function togglePin(r) {
  await store.pinReport(r.id, !r.pinned)
}
async function askDelete(r) {
  if (window.confirm('确认删除该报告？')) await store.deleteReport(r.id)
}

function fmtDate(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}
function statusMeta(r) {
  if (r.status === 'failed') return { label: '失败', cls: 'bad' }
  return { label: r.pinned ? '置顶' : '完成', cls: 'ok' }
}

onMounted(async () => {
  await store.loadReports({ limit: 50 })
  store.startPolling()
  store.loadInit()
})
</script>

<template>
  <div class="rv">
    <div class="rv__bar">
      <AppInput v-model="q" class="rv__search" placeholder="搜索标题 / 模型…" icon="search" />
      <button class="rv__filter" :class="{ on: pinnedOnly }" @click="pinnedOnly = !pinnedOnly">
        <AppIcon name="bookmark" size="sm" /> 只看置顶
      </button>
      <span class="rv__count">共 {{ store.reportsTotal }} 份</span>
      <span class="rv__sp"></span>
      <template v-if="selected.size">
        <button class="rv__btn" :disabled="busy" @click="batchPin(true)">置顶</button>
        <button class="rv__btn rv__btn--danger" :disabled="busy" @click="batchDelete">删除（{{ selected.size }}）</button>
      </template>
    </div>

    <div v-if="filtered.length" class="rv__table-wrap">
      <table class="rv__table">
        <thead>
          <tr>
            <th class="rv__chk"><input type="checkbox" :checked="allSelected" @change="toggleAll" /></th>
            <th>标题</th>
            <th>模型</th>
            <th>范围 / 窗口</th>
            <th>资讯数</th>
            <th>生成时间</th>
            <th>状态</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in filtered" :key="r.id" :class="{ sel: selected.has(r.id) }">
            <td class="rv__chk"><input type="checkbox" :checked="selected.has(r.id)" @change="toggleOne(r.id)" @click.stop /></td>
            <td class="rv__title-cell">
              <span class="rv__title" @click="router.push('/ai/reports/' + r.id)">{{ r.title || '报告 #' + r.id }}</span>
              <span v-if="r.error" class="rv__err">{{ r.error.slice(0, 40) }}</span>
            </td>
            <td class="rv__mono">{{ r.model || '—' }}</td>
            <td>{{ r.scope || 'all' }} / {{ r.window_hours || 24 }}h</td>
            <td class="rv__mono">{{ r.news_count || 0 }}</td>
            <td class="rv__muted">{{ fmtDate(r.created_ts) }}</td>
            <td>
              <span class="rv__badge" :class="statusMeta(r).cls">{{ statusMeta(r).label }}</span>
            </td>
            <td class="rv__ops">
              <button v-if="r.status === 'failed'" class="rv__op" title="重试" @click="store.retryTask(r.task_id)">
                <AppIcon name="refresh" size="sm" />
              </button>
              <button class="rv__op" :title="r.pinned ? '取消置顶' : '置顶'" @click="togglePin(r)">
                <AppIcon :name="r.pinned ? 'bookmark' : 'bookmark'" size="sm" :class="r.pinned && 'rv__pin-on'" />
              </button>
              <button class="rv__op" title="删除" @click="askDelete(r)">
                <AppIcon name="trash" size="sm" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="rv__empty">
      <AppIcon name="file-text" size="xl" />
      <p>{{ q ? '没有匹配的报告' : '还没有研究报告' }}</p>
      <button v-if="!q" class="rv__empty-btn" @click="router.push('/ai/tasks')">去生成一份</button>
    </div>
  </div>
</template>

<style scoped>
.rv { display: flex; flex-direction: column; gap: 14px; }
.rv__bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.rv__search { width: 260px; }
.rv__filter { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 9px; padding: 7px 12px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.rv__filter.on { border-color: var(--ff-brand, #2f7d5b); color: var(--ff-brand-dark, #1d4e39); background: var(--ff-bg-brand-subtle, #eaf4ef); }
.rv__count { font-size: 12.5px; color: var(--ff-text-3, #9ca3af); }
.rv__sp { flex: 1; }
.rv__btn { border: 1px solid var(--ff-border, #e5e7eb); background: var(--ff-bg-surface, #fff); border-radius: 8px; padding: 6px 12px; font-size: 12.5px; font-weight: 600; color: var(--ff-text-2, #6b7280); cursor: pointer; }
.rv__btn--danger { color: var(--ff-down, #e5484d); border-color: #f5c6c8; }
.rv__btn:disabled { opacity: 0.5; cursor: not-allowed; }
.rv__table-wrap { background: var(--ff-bg-surface, #fff); border: 1px solid var(--ff-border, #e5e7eb); border-radius: 13px; overflow-x: auto; }
.rv__table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 760px; }
.rv__table th { background: var(--ff-bg-subtle, #f3f6f4); font-size: 11.5px; font-weight: 700; color: var(--ff-text-3, #8aa096); text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--ff-border, #e5e7eb); white-space: nowrap; }
.rv__table td { padding: 10px 12px; border-bottom: 1px solid var(--ff-border, #eef1f0); color: var(--ff-text-primary, #1f2937); }
.rv__table tr:hover td { background: var(--ff-bg-hover, #fafbfa); }
.rv__table tr.sel td { background: var(--ff-bg-brand-subtle, #f0f8f4); }
.rv__chk { width: 34px; text-align: center; }
.rv__chk input { accent-color: var(--ff-brand, #2f7d5b); cursor: pointer; }
.rv__title-cell { max-width: 340px; }
.rv__title { font-weight: 600; cursor: pointer; color: var(--ff-text-primary, #1f2937); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rv__title:hover { color: var(--ff-brand, #2f7d5b); }
.rv__err { display: block; font-size: 11px; color: var(--ff-down, #e5484d); margin-top: 2px; }
.rv__mono { font-family: var(--ff-font-mono, ui-monospace, monospace); font-size: 12px; }
.rv__muted { color: var(--ff-text-3, #9ca3af); font-size: 12px; }
.rv__badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 10px; }
.rv__badge.ok { background: var(--ff-down-subtle, #e8f7ee); color: var(--ff-up, #12a150); }
.rv__badge.bad { background: var(--ff-up-subtle, #fdecec); color: var(--ff-down, #e5484d); }
.rv__ops { display: flex; gap: 4px; }
.rv__op { border: none; background: none; color: var(--ff-text-3, #9ca3af); cursor: pointer; padding: 4px; border-radius: 6px; }
.rv__op:hover { color: var(--ff-brand, #2f7d5b); background: var(--ff-bg-hover, #f3f6f4); }
.rv__pin-on { color: var(--ff-brand, #2f7d5b); }
.rv__empty { text-align: center; padding: 60px 20px; color: var(--ff-text-3, #9ca3af); background: var(--ff-bg-surface, #fff); border: 1px dashed var(--ff-border, #d8dfdb); border-radius: 13px; }
.rv__empty p { font-size: 14px; margin: 10px 0 14px; }
.rv__empty-btn { border: none; background: var(--ff-brand, #2f7d5b); color: #fff; border-radius: 9px; padding: 9px 18px; font-size: 13px; font-weight: 600; cursor: pointer; }
</style>
