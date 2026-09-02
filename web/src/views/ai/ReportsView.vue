<script setup>
/**
 * ReportsView — 研究报告列表
 * 搜索 / 筛选（只看置顶）/ 状态徽标 / 失败重试入口。
 */
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppIcon from '../../ui/AppIcon.vue'
import AppInput from '../../ui/AppInput.vue'
import AppButton from '../../ui/AppButton.vue'
import AppSkeleton from '../../ui/AppSkeleton.vue'
import { toastSuccess, toastError } from '../../composables/useToast'

const router = useRouter()
const store = useAiStore()

const q = ref('')
const pinnedOnly = ref(false)

const filtered = computed(() => {
  let list = store.reports
  if (pinnedOnly.value) list = list.filter((r) => r.pinned)
  const kw = q.value.trim().toLowerCase()
  if (kw) list = list.filter((r) => (r.title || '').toLowerCase().includes(kw) || (r.model || '').toLowerCase().includes(kw))
  // 严格按生成时间从新到旧排序（置顶不改变时间顺序）
  return [...list].sort((a, b) => (b.created_ts || 0) - (a.created_ts || 0))
})

async function togglePin(r) {
  await store.pinReport(r.id, !r.pinned)
}
async function askDelete(r) {
  if (window.confirm('确认删除该报告？')) await store.deleteReport(r.id)
}
// 失败重试：内存任务优先，跨重启回退报告归档参数
async function retryReport(r) {
  try {
    await store.retryReport(r)
    toastSuccess('已重新提交生成任务，可在任务中心查看进度')
  } catch (e) {
    toastError('重试失败：' + (e.message || e))
  }
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
    <!-- 模块页头按产品要求移除，h1 保留 sr-only 保文档语义 -->
    <h1 class="ff-sr-only">研究报告</h1>

    <div class="rv__bar">
      <AppInput v-model="q" class="rv__search" placeholder="搜索标题 / 模型…" icon="search" />
      <button class="rv__filter" :class="{ on: pinnedOnly }" @click="pinnedOnly = !pinnedOnly">
        <AppIcon name="bookmark" size="sm" /> 只看置顶
      </button>
      <span class="rv__count">共 {{ store.reportsTotal }} 份</span>
    </div>

    <div v-if="filtered.length" class="rv__table-wrap">
      <table class="rv__table">
        <thead>
          <tr>
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
          <tr v-for="r in filtered" :key="r.id">
            <td class="rv__title-cell">
              <span class="rv__title" @click="router.push('/ai/reports/' + r.id)">{{ r.title || '报告 #' + r.id }}</span>
              <span v-if="r.error" class="rv__err">{{ r.error.slice(0, 40) }}</span>
            </td>
            <td class="rv__mono">{{ r.model || '—' }}</td>
            <td>{{ store.scopeLabel(r.scope) }} / {{ r.window_hours || 24 }} 小时</td>
            <td class="rv__mono">{{ r.news_count || 0 }}</td>
            <td class="rv__muted">{{ fmtDate(r.created_ts) }}</td>
            <td>
              <span class="rv__badge" :class="statusMeta(r).cls">{{ statusMeta(r).label }}</span>
            </td>
            <td class="rv__ops">
              <button v-if="r.status === 'failed'" class="rv__op" title="重试" @click="retryReport(r)">
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

    <div v-else-if="store.reportsLoading" class="rv__empty">
      <AppSkeleton variant="text" :lines="6" />
    </div>

    <div v-else class="rv__empty">
      <AppIcon name="file-text" size="xl" />
      <p>{{ q ? '没有匹配的报告' : '还没有研究报告' }}</p>
      <AppButton v-if="!q" variant="primary" icon="zap" @click="router.push('/ai')">去生成一份</AppButton>
    </div>
  </div>
</template>

<style scoped>
.rv { display: flex; flex-direction: column; gap: 14px; }
.rv__bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.rv__search { width: 260px; }
.rv__filter { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--ff-border); background: var(--ff-bg-surface); border-radius: 9px; padding: 7px 12px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.rv__filter.on { border-color: var(--ff-brand); color: var(--ff-brand-dark); background: var(--ff-bg-brand-subtle); }
.rv__count { font-size: var(--ff-fs-caption); color: var(--ff-text-3); }
.rv__table-wrap { background: var(--ff-bg-surface); border: 1px solid var(--ff-border); border-radius: 13px; overflow-x: auto; }
.rv__table { width: 100%; border-collapse: collapse; font-size: var(--ff-fs-caption); min-width: 760px; }
.rv__table th { background: var(--ff-bg-subtle); font-size: var(--ff-fs-xs); font-weight: 600; color: var(--ff-text-3); text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--ff-border); white-space: nowrap; }
.rv__table td { padding: 10px 12px; border-bottom: 1px solid var(--ff-border); color: var(--ff-text-primary); }
.rv__table tr:hover td { background: var(--ff-bg-hover); }
.rv__title-cell { max-width: 340px; }
.rv__title { font-weight: 600; cursor: pointer; color: var(--ff-text-primary); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rv__title:hover { color: var(--ff-brand); }
.rv__err { display: block; font-size: var(--ff-fs-xs); color: var(--ff-up); margin-top: 2px; }
.rv__mono { font-family: var(--ff-font-mono, ui-monospace, monospace); font-size: var(--ff-fs-xs); }
.rv__muted { color: var(--ff-text-3); font-size: var(--ff-fs-xs); }
.rv__badge { display: inline-block; font-size: var(--ff-fs-xs); font-weight: 600; padding: 2px 9px; border-radius: 10px; }
.rv__badge.ok { background: var(--ff-down-subtle); color: var(--ff-down); }
.rv__badge.bad { background: var(--ff-up-subtle); color: var(--ff-up); }
.rv__ops { display: flex; gap: 4px; }
.rv__op { border: none; background: none; color: var(--ff-text-3); cursor: pointer; padding: 4px; border-radius: 6px; }
.rv__op:hover { color: var(--ff-brand); background: var(--ff-bg-hover); }
.rv__pin-on { color: var(--ff-brand); }
.rv__empty { text-align: center; padding: 60px 20px; color: var(--ff-text-3); background: var(--ff-bg-surface); border: 1px dashed var(--ff-border); border-radius: 13px; }
.rv__empty p { font-size: var(--ff-fs-body-sm); margin: 10px 0 14px; }
.rv__empty-btn { border: none; background: var(--ff-brand); color: var(--ff-bg-surface); border-radius: 9px; padding: 9px 18px; font-size: var(--ff-fs-caption); font-weight: 600; cursor: pointer; }

/* ── 窄屏适配（≤768px：搜索框占满一行；表格已带 min-width 横向滚动）── */
@media (max-width: 768px) {
  .rv__search { width: 100%; flex: 1 1 100%; }
}
</style>
