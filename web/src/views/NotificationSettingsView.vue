<script setup>
/**
 * NotificationSettingsView — 通知设置
 *
 * 四个区块：
 *  1. 全局规则：总开关 / 主题基准阈值 / 市场状态动态调节（含当前 regime 徽标）
 *  2. 推送渠道：钉钉/企微/飞书/Telegram/Server酱 webhook 的增删改、启停、测试发送
 *  3. 主题订阅：关键词组合管理（命中即推送）
 *  4. 推送日志 + 情感校准胜率
 */
import { ref, computed, onMounted } from 'vue'
import { alertsApi } from '../api/alerts'
import { toastSuccess, toastError } from '../composables/useToast'
import AppCard from '../ui/AppCard.vue'
import AppButton from '../ui/AppButton.vue'
import AppIcon from '../ui/AppIcon.vue'
import AppInput from '../ui/AppInput.vue'
import AppSelect from '../ui/AppSelect.vue'
import AppSwitch from '../ui/AppSwitch.vue'
import AppStatus from '../ui/AppStatus.vue'
import AppSkeleton from '../ui/AppSkeleton.vue'
import AppEmpty from '../ui/AppEmpty.vue'

// ---------------- 加载 ----------------
const loading = ref(true)
const loadErr = ref('')

const settings = ref(null)
const regime = ref(null)
const webhooks = ref([])
const channelTypes = ref([])
const topics = ref([])
const watchlist = ref([])
const logs = ref([])
const calibration = ref(null)

// ---------------- 全局设置 ----------------
const savingSettings = ref(false)
async function saveSettings(patch) {
  savingSettings.value = true
  try {
    const res = await alertsApi.updateSettings(patch)
    settings.value = res.settings
  } catch (e) {
    console.error(e)
    toastError('设置保存失败：' + (e?.message || e))
  } finally {
    savingSettings.value = false
  }
}

const REGIME_LABEL = {
  bull: { text: '强势（普涨）', tone: 'up' },
  bear: { text: '弱势（跌停潮）', tone: 'down' },
  rotate: { text: '分化（轮动）', tone: 'warn' },
  normal: { text: '常态', tone: 'success' },
}
const regimeInfo = computed(() => REGIME_LABEL[regime.value?.regime || 'normal'] || REGIME_LABEL.normal)
const effectiveThreshold = computed(() => {
  if (!settings.value) return '-'
  if (!settings.value.use_regime) return settings.value.base_importance
  return (settings.value.base_importance * (regime.value?.threshold_multiplier || 1)).toFixed(2)
})

// 数字输入的本地草稿（v-model），失焦时提交
const baseImportance = ref(5)
const watchlistMin = ref(0)
function commitSetting(key, value) {
  const num = Number(value)
  if (Number.isNaN(num) || num < 0 || num > 10) {
    toastError('阈值需在 0–10 之间，本次修改未保存')
    return
  }
  saveSettings({ [key]: num })
}

// ---------------- 渠道 ----------------
const showForm = ref(false)
const editingId = ref(null) // null=新增
const form = ref(emptyForm())
const savingChannel = ref(false)
const testingId = ref(null)

function emptyForm() {
  return { name: '', type: 'dingtalk', url: '', extra: '', enabled: true,
           min_importance: 0, quiet_start: '', quiet_end: '' }
}
const typeOptions = () => channelTypes.value.map((c) => ({ label: c.label, value: c.type }))
const typeLabel = (t) => channelTypes.value.find((c) => c.type === t)?.label || t

const EXTRA_LABEL = {
  telegram: 'Chat ID',
  serverchan: '',
}
const showExtra = computed(() => form.value.type === 'telegram')

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  showForm.value = true
}
function openEdit(wh) {
  editingId.value = wh.id
  form.value = { ...wh }
  showForm.value = true
}
async function submitForm() {
  if (!form.value.url.trim()) {
    toastError('Webhook 地址为必填项，请填写后保存')
    return
  }
  savingChannel.value = true
  try {
    const payload = { ...form.value }
    if (!showExtra.value) payload.extra = ''
    if (editingId.value == null) {
      await alertsApi.createWebhook(payload)
      toastSuccess(`渠道「${payload.name || typeLabel(payload.type)}」已创建`)
    } else {
      await alertsApi.updateWebhook(editingId.value, payload)
      toastSuccess(`渠道「${payload.name || typeLabel(payload.type)}」已保存`)
    }
    showForm.value = false
    await loadWebhooks()
  } catch (e) {
    console.error(e)
    toastError('渠道保存失败：' + (e?.message || e))
  } finally {
    savingChannel.value = false
  }
}
async function toggleChannel(wh, v) {
  try {
    await alertsApi.updateWebhook(wh.id, { enabled: v })
    wh.enabled = v
  } catch (e) {
    console.error(e)
    toastError('渠道状态切换失败：' + (e?.message || e))
  }
}
async function testChannel(wh) {
  testingId.value = wh.id
  try {
    const res = await alertsApi.testWebhook(wh.id)
    testResult.value = { ok: res.ok, name: wh.name, message: res.message }
    if (res.ok) toastSuccess(`测试消息已发送至「${wh.name || typeLabel(wh.type)}」`)
    else toastError(`测试发送失败：${res.message || '未知错误'}`)
  } catch (e) {
    testResult.value = { ok: false, name: wh.name, message: e?.message || '请求失败' }
    toastError(`测试发送失败：${e?.message || '请求失败'}`)
  } finally {
    testingId.value = null
  }
}
const testResult = ref(null)
async function removeChannel(wh) {
  if (!window.confirm(`确定删除渠道「${wh.name || typeLabel(wh.type)}」？`)) return
  try {
    await alertsApi.deleteWebhook(wh.id)
    toastSuccess('渠道已删除')
    await loadWebhooks()
  } catch (e) {
    console.error(e)
    toastError('删除失败：' + (e?.message || e))
  }
}

// ---------------- 主题订阅 ----------------
const showTopicForm = ref(false)
const topicForm = ref({ name: '', keywords: '', description: '' })
const topicKeywords = (t) => (t.keywords || []).join('、')
const kwInput = computed({
  get: () => topicForm.value.keywords,
  set: (v) => { topicForm.value.keywords = v },
})
const savingTopic = ref(false)
async function submitTopic() {
  const kws = topicForm.value.keywords.split(/[,，、\s]+/).filter(Boolean)
  if (!topicForm.value.name.trim() || !kws.length) {
    toastError('请填写主题名称和至少一个关键词')
    return
  }
  savingTopic.value = true
  try {
    await alertsApi.createTopic({ name: topicForm.value.name, keywords: kws,
                                  description: topicForm.value.description })
    toastSuccess(`主题「${topicForm.value.name}」已创建`)
    topicForm.value = { name: '', keywords: '', description: '' }
    showTopicForm.value = false
    await loadTopics()
  } catch (e) {
    console.error(e)
    toastError('主题创建失败：' + (e?.message || e))
  } finally {
    savingTopic.value = false
  }
}
async function toggleTopic(t, v) {
  try {
    await alertsApi.updateTopic(t.id, { is_enabled: v })
    t.is_enabled = v
  } catch (e) {
    console.error(e)
    toastError('主题状态切换失败：' + (e?.message || e))
  }
}
async function removeTopic(t) {
  if (!window.confirm(`确定删除主题「${t.name}」？`)) return
  try {
    await alertsApi.deleteTopic(t.id)
    toastSuccess(`主题「${t.name}」已删除`)
    await loadTopics()
  } catch (e) {
    console.error(e)
    toastError('删除失败：' + (e?.message || e))
  }
}

// ---------------- 校准 ----------------
const runningCal = ref(false)
async function runCalibration() {
  runningCal.value = true
  try {
    await alertsApi.runCalibration()
    toastSuccess('情感校准已启动，结果稍后自动刷新')
    // 后台线程执行，延迟刷新结果
    setTimeout(refreshCalibration, 15000)
    setTimeout(refreshCalibration, 45000)
  } catch (e) {
    console.error(e)
    toastError('校准启动失败：' + (e?.message || e))
  } finally {
    runningCal.value = false
  }
}
async function refreshCalibration() {
  try {
    calibration.value = (await alertsApi.calibration()).calibration
  } catch (e) { /* ignore */ }
}

// ---------------- 数据加载 ----------------
async function loadWebhooks() {
  webhooks.value = (await alertsApi.listWebhooks()).webhooks
}
async function loadTopics() {
  topics.value = (await alertsApi.listTopics()).topics
}
async function loadAll() {
  loading.value = true
  try {
    const [s, r, ct, wl, lg, cal] = await Promise.all([
      alertsApi.getSettings(),
      alertsApi.regime().catch(() => null),
      alertsApi.channels(),
      alertsApi.watchlist().catch(() => ({ stocks: [] })),
      alertsApi.logs(20),
      alertsApi.calibration().catch(() => ({ calibration: null })),
    ])
    settings.value = s.settings
    baseImportance.value = s.settings.base_importance
    watchlistMin.value = s.settings.watchlist_min_importance
    regime.value = r?.regime || null
    channelTypes.value = ct.channels
    watchlist.value = wl.stocks
    logs.value = lg.logs
    calibration.value = cal.calibration
    await Promise.all([loadWebhooks(), loadTopics()])
    loadErr.value = ''
  } catch (e) {
    loadErr.value = e?.message || String(e)
    console.error(e)
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="ff-page ff-notify-view">
    <h1 class="ff-sr-only">通知设置</h1>
    <AppSkeleton v-if="loading" variant="card" :lines="4" />

    <template v-else-if="loadErr">
      <AppCard>
        <AppEmpty title="加载失败" icon="alert-circle">
          <template #description>{{ loadErr }}</template>
          <template #action>
            <AppButton variant="secondary" icon="refresh" @click="loadAll">重试</AppButton>
          </template>
        </AppEmpty>
      </AppCard>
    </template>

    <template v-else>
      <!-- 全局规则 -->
      <AppCard class="ff-notify-view__card">
        <div class="ff-notify-view__card-head">
          <AppIcon name="sliders" size="sm" />
          <strong>全局规则</strong>
          <AppSwitch
            :model-value="settings.enabled"
            label="启用推送"
            @change="(v) => saveSettings({ enabled: v })"
          />
        </div>
        <div class="ff-notify-view__grid">
          <div class="ff-notify-view__field">
            <label>主题基准阈值</label>
            <div class="ff-notify-view__inline">
              <AppInput
                v-model="baseImportance"
                type="number"
                @blur="commitSetting('base_importance', baseImportance)"
              />
              <span class="ff-notify-view__hint">0–10，主题关键词命中新闻需达到该重要性才推送</span>
            </div>
          </div>
          <div class="ff-notify-view__field">
            <label>市场状态动态调节</label>
            <div class="ff-notify-view__inline">
              <AppSwitch
                :model-value="settings.use_regime"
                label="按市况调节"
                @change="(v) => saveSettings({ use_regime: v })"
              />
              <span v-if="regime" class="ff-notify-view__regime">
                当前：<AppStatus :tone="regimeInfo.tone" :text="regimeInfo.text" />
                <span class="ff-text-muted">生效阈值 {{ effectiveThreshold }}</span>
              </span>
            </div>
          </div>
          <div class="ff-notify-view__field">
            <label>自选股推送下限</label>
            <div class="ff-notify-view__inline">
              <AppInput
                v-model="watchlistMin"
                type="number"
                @blur="commitSetting('watchlist_min_importance', watchlistMin)"
              />
              <span class="ff-notify-view__hint">0 = 自选股相关新闻全量推送；自选股在「股票监控」页维护</span>
            </div>
          </div>
        </div>
        <div v-if="watchlist.length" class="ff-notify-view__watchlist">
          <AppIcon name="monitor" size="xs" />
          已订阅 {{ watchlist.length }} 只自选股：{{ watchlist.map((s) => s.name || s.code).join('、') }}
        </div>
      </AppCard>

      <!-- 推送渠道 -->
      <AppCard class="ff-notify-view__card">
        <div class="ff-notify-view__card-head">
          <AppIcon name="send" size="sm" />
          <strong>推送渠道</strong>
          <span class="ff-text-muted">命中规则后推送到已启用的渠道；同一新闻 24h 内每渠道只推一次</span>
          <AppButton size="sm" variant="primary" icon="plus" @click="openCreate">新增渠道</AppButton>
        </div>

        <div v-if="testResult" class="ff-notify-view__test" :class="{ 'is-ok': testResult.ok }">
          <AppIcon :name="testResult.ok ? 'check-circle' : 'alert-circle'" size="xs" />
          <span>「{{ testResult.name }}」{{ testResult.message }}</span>
          <button type="button" class="ff-notify-view__test-close" aria-label="关闭提示" @click="testResult = null">
            <AppIcon name="x" size="xs" />
          </button>
        </div>

        <div v-if="webhooks.length" class="ff-notify-view__channels">
          <div v-for="wh in webhooks" :key="wh.id" class="ff-notify-view__channel" :class="{ 'is-off': !wh.enabled }">
            <div class="ff-notify-view__channel-main">
              <div class="ff-notify-view__channel-title">
                <strong>{{ wh.name || typeLabel(wh.type) }}</strong>
                <span class="ff-notify-view__chip">{{ typeLabel(wh.type) }}</span>
                <span v-if="wh.min_importance > 0" class="ff-notify-view__chip">≥{{ wh.min_importance }}</span>
                <span v-if="wh.quiet_start && wh.quiet_end" class="ff-notify-view__chip">
                  静默 {{ wh.quiet_start }}–{{ wh.quiet_end }}
                </span>
              </div>
              <div class="ff-notify-view__channel-url">{{ wh.url }}</div>
              <div v-if="wh.extra" class="ff-notify-view__channel-url">Chat ID: {{ wh.extra }}</div>
            </div>
            <div class="ff-notify-view__channel-actions">
              <AppSwitch :model-value="wh.enabled" @change="(v) => toggleChannel(wh, v)" />
              <AppButton size="sm" variant="ghost" icon="send"
                          :loading="testingId === wh.id" @click="testChannel(wh)">测试</AppButton>
              <AppButton size="sm" variant="ghost" icon="edit" @click="openEdit(wh)">编辑</AppButton>
              <AppButton size="sm" variant="ghost" icon="trash" @click="removeChannel(wh)">删除</AppButton>
            </div>
          </div>
        </div>
        <AppEmpty v-else title="还没有配置推送渠道" icon="send"
                   description="添加钉钉 / 企业微信 / 飞书群机器人、Telegram Bot 或 Server酱 的 Webhook 地址，新闻命中自选股或主题订阅时自动推送。" />

        <!-- 新增/编辑表单 -->
        <div v-if="showForm" class="ff-notify-view__form">
          <div class="ff-notify-view__form-row">
            <AppSelect v-model="form.type" label="渠道类型" :options="typeOptions()" />
            <AppInput v-model="form.name" label="名称（可选）" placeholder="如：盯盘群" />
          </div>
          <AppInput v-model="form.url" label="Webhook 地址"
                     placeholder="钉钉/企微/飞书机器人地址、https://api.telegram.org/bot<TOKEN> 或 https://sctapi.ftqq.com/<KEY>.send" />
          <div class="ff-notify-view__form-row">
            <AppInput v-if="showExtra" v-model="form.extra" label="Telegram Chat ID" placeholder="如 123456789" />
            <AppInput v-model="form.min_importance" label="渠道最低重要性（0 = 全推）" type="number" min="0" max="10" step="0.5" />
          </div>
          <div class="ff-notify-view__form-row">
            <AppInput v-model="form.quiet_start" label="免打扰开始（HH:MM，可选）" placeholder="22:30" />
            <AppInput v-model="form.quiet_end" label="免打扰结束（HH:MM，可选）" placeholder="08:00" />
          </div>
          <div class="ff-notify-view__form-actions">
            <AppButton size="sm" variant="primary" :loading="savingChannel" @click="submitForm">保存</AppButton>
            <AppButton size="sm" variant="ghost" @click="showForm = false">取消</AppButton>
          </div>
        </div>
      </AppCard>

      <!-- 主题订阅 -->
      <AppCard class="ff-notify-view__card">
        <div class="ff-notify-view__card-head">
          <AppIcon name="bookmark" size="sm" />
          <strong>主题订阅</strong>
          <span class="ff-text-muted">新闻标题/摘要命中任一关键词且达到主题阈值时推送</span>
          <AppButton size="sm" variant="primary" icon="plus" @click="showTopicForm = !showTopicForm">
            {{ showTopicForm ? '收起' : '新增主题' }}
          </AppButton>
        </div>

        <div v-if="showTopicForm" class="ff-notify-view__form">
          <div class="ff-notify-view__form-row">
            <AppInput v-model="topicForm.name" label="主题名称" placeholder="如：新能源" />
            <AppInput v-model="kwInput" label="关键词（逗号/空格分隔）" placeholder="锂电, 光伏, 储能" />
          </div>
          <div class="ff-notify-view__form-actions">
            <AppButton size="sm" variant="primary" :loading="savingTopic" :disabled="savingTopic" @click="submitTopic">保存</AppButton>
          </div>
        </div>

        <div v-if="topics.length" class="ff-notify-view__topics">
          <div v-for="t in topics" :key="t.id" class="ff-notify-view__topic">
            <div>
              <strong>{{ t.name }}</strong>
              <span class="ff-notify-view__topic-kw">{{ topicKeywords(t) }}</span>
            </div>
            <div class="ff-notify-view__channel-actions">
              <AppSwitch :model-value="t.is_enabled" @change="(v) => toggleTopic(t, v)" />
              <AppButton size="sm" variant="ghost" icon="trash" @click="removeTopic(t)">删除</AppButton>
            </div>
          </div>
        </div>
        <AppEmpty v-else-if="!showTopicForm" title="暂无主题订阅" icon="bookmark"
                   description="添加关键词组合（如「美联储」「降准」「固态电池」），相关重要新闻会自动推送。" />
      </AppCard>

      <!-- 推送日志 -->
      <AppCard class="ff-notify-view__card">
        <div class="ff-notify-view__card-head">
          <AppIcon name="clock" size="sm" />
          <strong>最近推送</strong>
        </div>
        <div v-if="logs.length" class="ff-notify-view__logs">
          <div v-for="l in logs" :key="l.id" class="ff-notify-view__log">
            <span class="ff-notify-view__log-time">{{ l.pushed_at }}</span>
            <span class="ff-notify-view__chip">{{ typeLabel(l.webhook_type) }}</span>
            <a :href="l.url" target="_blank" rel="noopener" class="ff-notify-view__log-title">{{ l.title }}</a>
          </div>
        </div>
        <AppEmpty v-else title="暂无推送记录" icon="inbox"
                   description="告警命中并成功推送后，会在这里留下记录。" />
      </AppCard>

      <!-- 情感校准 -->
      <AppCard class="ff-notify-view__card">
        <div class="ff-notify-view__card-head">
          <AppIcon name="activity" size="sm" />
          <strong>情感信号校准</strong>
          <span class="ff-text-muted">用关联个股 T+1 收益回测各情感标签的真实胜率（每日 17:30 自动运行）</span>
          <AppButton size="sm" variant="ghost" icon="refresh" :loading="runningCal" @click="runCalibration">
            立即校准
          </AppButton>
        </div>
        <div v-if="calibration && calibration.sample" class="ff-notify-view__cal">
          <div class="ff-notify-view__cal-meta">
            样本 {{ calibration.sample }} 条 · 运行于 {{ calibration.run_at }}
          </div>
          <table class="ff-table ff-table--hover">
            <thead>
              <tr>
                <th>情感标签</th><th>样本数</th><th>平均 T+1 收益</th><th>上涨胜率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(v, label) in calibration.by_label" :key="label">
                <td>{{ label }}</td>
                <td class="ff-num">{{ v.n }}</td>
                <td class="ff-num">{{ (v.avg_ret * 100).toFixed(2) }}%</td>
                <td class="ff-num">{{ (v.win_rate * 100).toFixed(1) }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
        <AppEmpty v-else title="尚无校准结果" icon="activity"
                   description="校准需要积累「新闻-个股」关联数据与对应日线；点击「立即校准」可手动触发一次。" />
      </AppCard>
    </template>
  </div>
</template>

<style scoped>
.ff-notify-view {
  max-width: var(--ff-container-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-4);
}

.ff-notify-view__card {
  padding: var(--ff-space-4) var(--ff-space-5);
}

.ff-notify-view__card-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-3);
}
.ff-notify-view__card-head > strong {
  font-size: var(--ff-fs-body);
}
.ff-notify-view__card-head > .ff-text-muted {
  flex: 1 1 auto;
  font-size: var(--ff-fs-caption);
}
.ff-notify-view__card-head > .app-button {
  margin-left: auto;
}

.ff-notify-view__grid {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ff-notify-view__field > label {
  display: block;
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-secondary);
  margin-bottom: 4px;
}
.ff-notify-view__inline {
  display: flex;
  align-items: center;
  gap: var(--ff-space-3);
  flex-wrap: wrap;
}
.ff-notify-view__inline .app-input {
  width: 110px;
}
.ff-notify-view__hint {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.ff-notify-view__regime {
  display: inline-flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
}

.ff-notify-view__watchlist {
  margin-top: var(--ff-space-3);
  padding-top: var(--ff-space-3);
  border-top: 1px dashed var(--ff-border);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-secondary);
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
}

.ff-notify-view__channels,
.ff-notify-view__topics {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}

.ff-notify-view__channel,
.ff-notify-view__topic {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ff-space-3);
  padding: var(--ff-space-2-5) var(--ff-space-3);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-md);
  transition: opacity var(--ff-dur-fast) var(--ff-ease-standard);
}
.ff-notify-view__channel.is-off {
  opacity: 0.55;
}

.ff-notify-view__channel-title {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-body-sm);
}
.ff-notify-view__chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: var(--ff-radius-pill);
  background: var(--ff-bg-subtle);
  border: 1px solid var(--ff-border-subtle);
  font-size: 11px;
  font-weight: 600;
  color: var(--ff-text-secondary);
  white-space: nowrap;
}
.ff-notify-view__channel-url {
  margin-top: 2px;
  font-size: var(--ff-fs-caption);
  font-family: var(--ff-font-mono);
  color: var(--ff-text-tertiary);
  word-break: break-all;
}
.ff-notify-view__channel-actions {
  display: flex;
  align-items: center;
  gap: var(--ff-space-1);
  flex-shrink: 0;
}

.ff-notify-view__topic-kw {
  margin-left: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}

.ff-notify-view__test {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  margin-bottom: var(--ff-space-3);
  padding: var(--ff-space-2) var(--ff-space-3);
  border-radius: var(--ff-radius-md);
  font-size: var(--ff-fs-caption);
  border: 1px solid var(--ff-border);
  background: var(--ff-bg-subtle);
}
.ff-notify-view__test.is-ok {
  border-color: var(--ff-border-subtle);
  background: var(--ff-brand-subtle);
}
.ff-notify-view__test-close {
  display: inline-flex;
  align-items: center;
  margin-left: auto;
  flex-shrink: 0;
  padding: 2px;
  border: none;
  background: none;
  color: inherit;
  cursor: pointer;
  opacity: 0.5;
}
.ff-notify-view__test-close:hover {
  opacity: 1;
}

.ff-notify-view__form {
  margin-top: var(--ff-space-3);
  padding: var(--ff-space-3);
  border: 1px dashed var(--ff-border);
  border-radius: var(--ff-radius-md);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
}
.ff-notify-view__form-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--ff-space-3);
}
.ff-notify-view__form-actions {
  display: flex;
  gap: var(--ff-space-2);
}

.ff-notify-view__logs,
.ff-notify-view__cal {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-1);
}
.ff-notify-view__log {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  padding: 3px 0;
}
.ff-notify-view__log-time {
  color: var(--ff-text-tertiary);
  font-family: var(--ff-font-mono);
  white-space: nowrap;
}
.ff-notify-view__log-title {
  color: var(--ff-text-secondary);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ff-notify-view__log-title:hover {
  color: var(--ff-brand-text);
}
.ff-notify-view__cal-meta {
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  margin-bottom: var(--ff-space-2);
}
</style>
