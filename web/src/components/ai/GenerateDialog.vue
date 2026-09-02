<script setup>
/**
 * GenerateDialog — 新建报告弹窗（报告优先首页 / 命令面板共用）
 * 报告类型 →（个股代码）→ 范围 / 窗口 / 焦点 → 数据预估 → 提交。
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAiStore } from '../../store/ai'
import AppModal from '../../ui/AppModal.vue'
import AppButton from '../../ui/AppButton.vue'
import AppSelect from '../../ui/AppSelect.vue'
import AppInput from '../../ui/AppInput.vue'
import { toastSuccess, toastError } from '../../composables/useToast'

const props = defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['update:open', 'close'])

const store = useAiStore()
const router = useRouter()

// 可选报告类型：去除 flash（flash 仅由快讯/快捷入口触发）
const types = computed(() => {
  const list = store.reportTypes?.length
    ? store.reportTypes
    : [
        { key: 'review', label: '复盘简报' },
        { key: 'stock', label: '个股深度' },
        { key: 'sentiment', label: '舆情研判' },
      ]
  return list.filter((t) => t.key !== 'flash')
})

const reportType = ref('review')
const stockInput = ref('')
const scope = ref('all')
const window = ref(24)
const focus = ref('')
const submitting = ref(false)
const errMsg = ref('')

const scopeOptions = computed(() => store.scopeOptions.map((s) => ({ label: s.label, value: s.key })))
const windowOptions = computed(() => store.windowOptions.map((w) => ({ label: `${w} 小时`, value: w })))

const activeType = computed(() => types.value.find((t) => t.key === reportType.value) || types.value[0])

// 提交前数据预估（/api/llm/preview）
const estText = computed(() => {
  const p = store.preview
  if (!p || !p.matched) return ''
  const est = p.estimate || {}
  return `窗口命中 ${p.matched} 条 · 预计送分析 ${est.selected ?? p.matched} 条 · 约 ${est.chunks ?? 1} 批 · 耗时约 ${est.eta_seconds ?? '—'}s`
})

function refreshPreview() {
  store.fetchPreview({ hours: Number(window.value) || 24, scope: scope.value })
}

function resetForm() {
  reportType.value = store.config.report_type || 'review'
  scope.value = store.config.scope || 'all'
  window.value = Number(store.config.window) || 24
  focus.value = store.config.focus || ''
  stockInput.value = ''
  errMsg.value = ''
  refreshPreview()
}

watch(
  () => props.open,
  (v) => {
    if (v) resetForm()
  }
)

watch([scope, window], () => refreshPreview())

async function submit() {
  if (submitting.value) return
  if (reportType.value === 'stock' && !stockInput.value.trim()) {
    errMsg.value = '个股深度报告需要输入股票代码'
    return
  }
  if (!store.modelAvailable) {
    errMsg.value = '尚未配置模型，请先在设置中完成配置后生成'
    return
  }
  submitting.value = true
  errMsg.value = ''
  try {
    const r = await store.submitAnalysis({
      provider_id: store.status?.default_provider?.id,
      scope: scope.value,
      window: Number(window.value) || 24,
      focus: focus.value || '',
      report_type: reportType.value,
      stock_code: stockInput.value.trim(),
    })
    if (r.ok) {
      emit('update:open', false)
      emit('close')
      toastSuccess('已提交' + (activeType.value?.label || '') + '分析任务，可在本页查看进度')
    } else {
      errMsg.value = r.error || '提交失败'
      if (!store.modelAvailable) {
        errMsg.value = '尚未配置模型，请先在设置中完成配置后生成'
      }
    }
  } catch (e) {
    errMsg.value = '提交失败：' + (e.message || e)
  } finally {
    submitting.value = false
  }
}

function goSettings() {
  emit('update:open', false)
  emit('close')
  router.push('/ai/settings')
}
</script>

<template>
  <AppModal
    :model-value="open"
    title="新建报告"
    size="md"
    :show-ok="false"
    :show-cancel="true"
    cancel-text="关闭"
    @update:model-value="emit('update:open', $event)"
    @close="emit('close')"
  >
    <div class="gd">
      <!-- 报告类型 -->
      <div class="gd__field">
        <span class="gd__label">报告类型</span>
        <div class="gd__types">
          <button
            v-for="t in types"
            :key="t.key"
            class="gd__type"
            :class="{ on: reportType === t.key }"
            :title="t.desc || ''"
            @click="reportType = t.key; store.saveConfig({ report_type: t.key })"
          >{{ t.label }}</button>
        </div>
      </div>

      <!-- 个股代码（仅 stock） -->
      <div v-if="reportType === 'stock'" class="gd__field">
        <AppInput
          v-model="stockInput"
          label="股票代码"
          placeholder="输入股票代码，如 600519"
        />
      </div>

      <!-- 范围 / 窗口 -->
      <div class="gd__field gd__row">
        <AppSelect v-model="scope" label="分析范围" :options="scopeOptions" />
        <AppSelect v-model="window" label="时间窗口" :options="windowOptions" />
      </div>

      <!-- 焦点 -->
      <div class="gd__field">
        <AppInput v-model="focus" label="自定义焦点（可选）" placeholder="如：重点关注半导体与新能源" />
      </div>

      <!-- 数据预估 -->
      <p v-if="estText" class="gd__est">{{ estText }}</p>

      <p v-if="errMsg" class="gd__err">{{ errMsg }}</p>

      <p v-if="!store.modelAvailable" class="gd__warn">
        尚未配置模型，无法生成分析。
        <button class="gd__link" @click="goSettings">去设置 →</button>
      </p>
    </div>

    <template #footer>
      <AppButton variant="ghost" @click="emit('update:open', false); emit('close')">关闭</AppButton>
      <AppButton variant="primary" icon="zap" :loading="submitting" :disabled="submitting || !store.modelAvailable" @click="submit">
        生成{{ activeType?.label || '' }}
      </AppButton>
    </template>
  </AppModal>
</template>

<style scoped>
.gd { display: flex; flex-direction: column; gap: 14px; }
.gd__field { display: flex; flex-direction: column; gap: 6px; }
.gd__label { font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); }
.gd__types { display: inline-flex; gap: 4px; background: var(--ff-bg-subtle); border-radius: 10px; padding: 3px; align-self: flex-start; flex-wrap: wrap; }
.gd__type { border: none; background: none; border-radius: 8px; padding: 7px 14px; font-size: var(--ff-fs-caption); font-weight: 600; color: var(--ff-text-2); cursor: pointer; }
.gd__type.on { background: var(--ff-bg-surface); color: var(--ff-brand-dark); box-shadow: 0 1px 4px rgba(16, 40, 30, 0.12); }
.gd__row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.gd__est { font-size: var(--ff-fs-xs); color: var(--ff-text-3); margin: 0; }
.gd__err { font-size: var(--ff-fs-caption); color: var(--ff-up); margin: 0; }
.gd__warn { display: flex; align-items: center; gap: 6px; font-size: var(--ff-fs-caption); color: #b45309; background: #fef7e6; border: 1px solid #f5d9a0; border-radius: 9px; padding: 9px 12px; margin: 0; }
.gd__link { border: none; background: none; color: var(--ff-brand); font-weight: 600; cursor: pointer; padding: 0; }
@media (max-width: 560px) {
  .gd__row { grid-template-columns: 1fr; }
}
</style>