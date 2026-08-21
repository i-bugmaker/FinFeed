<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppBadge from '../ui/AppBadge.vue'
import EasyTdxNav from '../components/easytdx/EasyTdxNav.vue'
import EasyTdxParamForm from '../components/easytdx/EasyTdxParamForm.vue'
import EasyTdxResultPanel from '../components/easytdx/EasyTdxResultPanel.vue'
import EasyTdxTaskStatus from '../components/easytdx/EasyTdxTaskStatus.vue'
import easytdxApi from '../api/easytdx'

const loading = ref(false)
const meta = ref(null)
const strategies = ref([])
const navGroups = ref([])
const selectedFuncId = ref('')
const params = reactive({})
const task = ref(null)
const running = ref(false)
const recent = ref([])
const query = ref('')
const errMsg = ref('')

let pollTimer = null

const selectedFunc = computed(
  () => meta.value?.functions.find((f) => f.id === selectedFuncId.value) || null,
)

function buildNav(groups, functions) {
  return groups.map((g) => ({
    id: g.id,
    label: g.label,
    icon: g.icon,
    items: functions
      .filter((f) => f.group === g.id)
      .map((f) => ({ id: f.id, label: f.label })),
  }))
}

function resetParams(func) {
  for (const k of Object.keys(params)) delete params[k]
  for (const p of func.params || []) {
    params[p.key] = p.default ?? (p.type === 'bool' ? false : '')
  }
}

function selectFunc(id) {
  errMsg.value = ''
  selectedFuncId.value = id
  const func = meta.value.functions.find((f) => f.id === id)
  if (func) resetParams(func)
  task.value = null
}

async function loadMeta() {
  loading.value = true
  try {
    const [m, s] = await Promise.all([easytdxApi.meta(), easytdxApi.strategies()])
    meta.value = m
    strategies.value = s.strategies || []
    navGroups.value = buildNav(m.group_meta, m.functions)
    if (m.functions.length) selectFunc(m.functions[0].id)
  } catch (e) {
    errMsg.value = '加载功能清单失败：' + (e.message || e)
  } finally {
    loading.value = false
  }
}

async function loadRecent() {
  try {
    const r = await easytdxApi.tasks(8)
    recent.value = r.tasks || []
  } catch (e) {
    /* 静默降级 */
  }
}

async function run() {
  if (!selectedFunc.value) return
  errMsg.value = ''
  task.value = null
  running.value = true
  try {
    const r = await easytdxApi.run(selectedFuncId.value, { ...params })
    startPolling(r.task_id)
  } catch (e) {
    running.value = false
    errMsg.value = '提交失败：' + (e.message || e)
  }
}

function startPolling(taskId) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(() => pollTask(taskId), 800)
  pollTask(taskId)
}

async function pollTask(taskId) {
  try {
    const t = await easytdxApi.task(taskId)
    task.value = t
    if (t.status === 'success' || t.status === 'error') {
      stopPolling()
      running.value = false
      loadRecent()
    }
  } catch (e) {
    /* 单次轮询失败不打断 */
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(async () => {
  await loadMeta()
  await loadRecent()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="ff-page etdx-view">
    <header class="etdx-view__header">
      <div>
        <h1 class="ff-page__title">
          <AppIcon name="cpu" size="lg" /> easy-tdx 数据源
        </h1>
        <p class="ff-page__subtitle">
          通达信 / Mac / 扩展行情 / 巨潮 / 缠论 / 回测 —— 全部 easy-tdx 公开接口
        </p>
      </div>
      <AppBadge v-if="meta" variant="brand">{{ navGroups.reduce((n, g) => n + g.items.length, 0) }} 项功能</AppBadge>
    </header>

    <div v-if="errMsg" class="ff-alert ff-alert--danger etdx-view__err">
      <AppIcon name="alert-circle" size="md" /> {{ errMsg }}
    </div>

    <div class="etdx-view__body">
      <!-- 左：功能导航 -->
      <AppCard class="etdx-view__nav" :no-padding="true">
        <EasyTdxNav
          :groups="navGroups"
          :active-id="selectedFuncId"
          v-model:query="query"
          @select="selectFunc"
        />
      </AppCard>

      <!-- 右：参数 + 执行 + 结果 -->
      <div class="etdx-view__main">
        <AppCard v-if="selectedFunc" class="etdx-view__panel">
          <div class="etdx-view__func-head">
            <div>
              <div class="etdx-view__func-title">
                {{ selectedFunc.label }}
                <AppBadge variant="muted">{{ selectedFunc.group }}</AppBadge>
                <AppBadge variant="brand">{{ selectedFunc.client }}</AppBadge>
              </div>
              <p v-if="selectedFunc.help" class="etdx-view__func-help">{{ selectedFunc.help }}</p>
            </div>
            <AppButton
              variant="primary"
              icon="play"
              :loading="running"
              :disabled="running"
              @click="run"
            >
              {{ running ? '执行中…' : '执行' }}
            </AppButton>
          </div>

          <div class="etdx-view__content">
            <!-- 参数表单 -->
            <div class="etdx-view__form">
              <h3 class="ff-h3">参数</h3>
              <EasyTdxParamForm
                :func="selectedFunc"
                :model="params"
                :strategies="strategies"
              />
            </div>

            <!-- 结果 -->
            <div class="etdx-view__result">
              <h3 class="ff-h3">结果</h3>
              <EasyTdxResultPanel
                :result="task && task.status !== 'running' ? task.result : null"
                :func="selectedFunc"
                :loading="running"
              />
            </div>
          </div>
        </AppCard>

        <!-- 执行状态 / 日志 -->
        <AppCard class="etdx-view__status" :no-padding="true">
          <div class="etdx-view__status-head">
            <AppIcon name="list" size="sm" />
            <span>执行状态与日志</span>
          </div>
          <div class="etdx-view__status-body">
            <EasyTdxTaskStatus :task="task" />
          </div>
        </AppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.etdx-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
}
.etdx-view__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-4);
  margin-bottom: var(--ff-space-4);
}
.etdx-view__err {
  margin-bottom: var(--ff-space-4);
}
.etdx-view__body {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: var(--ff-space-4);
  align-items: start;
}
.etdx-view__nav {
  position: sticky;
  top: var(--ff-space-4);
  max-height: calc(100vh - 140px);
}
.etdx-view__main {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
  min-width: 0;
}
.etdx-view__func-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ff-space-4);
  margin-bottom: var(--ff-space-4);
}
.etdx-view__func-title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-title-sm);
  font-weight: 700;
  color: var(--ff-text-primary);
}
.etdx-view__func-help {
  margin: 6px 0 0;
  font-size: var(--ff-fs-body-sm);
  color: var(--ff-text-tertiary);
}
.etdx-view__content {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: var(--ff-space-5);
  align-items: start;
}
.etdx-view__form,
.etdx-view__result {
  min-width: 0;
}
.etdx-view__status-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-3) var(--ff-space-4);
  border-bottom: 1px solid var(--ff-border-subtle);
  font-size: var(--ff-fs-body-sm);
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-view__status-body {
  height: 260px;
}
.etdx-view__nav :deep(.etdx-nav) {
  height: calc(100vh - 140px);
}

@media (max-width: 1100px) {
  .etdx-view__body {
    grid-template-columns: 1fr;
  }
  .etdx-view__nav {
    position: static;
    max-height: 320px;
  }
  .etdx-view__content {
    grid-template-columns: 1fr;
  }
}
</style>
