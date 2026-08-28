<script setup>
/**
 * ModelConfigDialog — 模型配置弹窗（工作台/设置页统一交互）
 *
 * mode="wizard"（默认，工作台首次配置）：三步流程 选择模型 → 填写密钥 → 完成
 * mode="form"（设置页添加/编辑模型）：单页表单，预设网格 + 字段 + 测试 + 保存
 *
 * 两种模式共用同一视觉语言（居中弹窗、预设卡片网格、品牌色），
 * 保证「添加模型」在任何入口的交互体验一致。
 */
import { ref, watch, computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  presets: { type: Array, default: () => [] },
  // 编辑模式：传入已有 provider 时回填表单
  provider: { type: Object, default: null },
  mode: { type: String, default: 'wizard' }, // 'wizard' | 'form'
})
const emit = defineEmits(['close', 'done'])

const isEdit = computed(() => !!props.provider?.id)

const step = ref(1)
const form = ref(blankForm())
const testing = ref(false)
const testResult = ref('')
const saving = ref(false)
const error = ref('')

function blankForm() {
  return {
    name: '', preset: 'deepseek', base_url: '', model: '', api_key: '',
    temperature: 0.3, max_tokens: 4096, timeout: 120, is_default: false, enabled: true,
  }
}

watch(() => props.open, (v) => {
  if (!v) return
  step.value = 1
  testResult.value = ''
  error.value = ''
  const p = props.provider
  if (p?.id) {
    // 编辑模式：回填已有字段，API Key 留空（留空则保留原密钥）
    form.value = {
      name: p.name || '', preset: p.preset || 'custom',
      base_url: p.base_url || '', model: p.model || '', api_key: '',
      temperature: p.temperature ?? 0.3, max_tokens: p.max_tokens ?? 4096,
      timeout: p.timeout ?? 120, is_default: !!p.is_default, enabled: p.enabled !== false,
    }
  } else {
    form.value = blankForm()
  }
})

function pick(p) {
  form.value.preset = p.key
  form.value.base_url = p.base_url
  form.value.model = p.model
  if (!form.value.name || form.value.name === '默认模型') form.value.name = p.label
}

const canTest = computed(() => form.value.base_url.trim() !== '')
const canSave = computed(() =>
  form.value.base_url.trim() !== '' &&
  form.value.model.trim() !== '' &&
  (isEdit.value ? true : form.value.api_key.trim() !== '')
)

async function test() {
  if (!canTest.value) return
  testing.value = true
  testResult.value = '测试中…'
  error.value = ''
  try {
    const { api } = await import('../../api/client')
    const f = { ...form.value }
    // 编辑且未填 Key：使用已保存密钥
    const payload = isEdit.value && !f.api_key ? { id: props.provider.id, use_saved: true } : f
    const r = await api.llmPost('/provider/test', payload)
    if (r && r.ok) {
      testResult.value = `连通正常（${r.model || ''}）${r.latency_ms ? ' · ' + Math.round(r.latency_ms) + 'ms' : ''}`
      if (props.mode === 'wizard') step.value = 3
    } else {
      testResult.value = r?.message || '连通失败'
    }
  } catch (e) {
    testResult.value = '测试失败：' + (e.message || e)
  } finally {
    testing.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  error.value = ''
  try {
    const { api } = await import('../../api/client')
    const f = { ...form.value }
    if (isEdit.value) f.id = props.provider.id
    if (!f.api_key) delete f.api_key
    const r = await api.llmPost('/provider/save', f)
    if (r && r.success) {
      emit('done', r.provider || null)
    } else {
      error.value = r?.error || '保存失败'
    }
  } catch (e) {
    error.value = '保存失败：' + (e.message || e)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="ow-fade">
      <div v-if="open" class="ow-mask" @click.self="emit('close')">
        <div class="ow-panel">
          <div class="ow-head">
            <div class="ow-title"><AppIcon name="sparkles" size="md" /> {{ isEdit ? '编辑模型' : '添加模型' }}</div>
            <button class="ow-x" @click="emit('close')"><AppIcon name="x" size="sm" /></button>
          </div>

          <!-- 步骤指示（仅向导模式） -->
          <div v-if="mode === 'wizard'" class="ow-steps">
            <span v-for="(s, i) in ['选择模型', '填写密钥', '完成']" :key="s" class="ow-step" :class="{ on: i + 1 === step, done: i + 1 < step }">
              <span class="ow-dot">{{ i + 1 < step ? '✓' : i + 1 }}</span>{{ s }}
            </span>
          </div>

          <!-- 步骤 1：选择预设 -->
          <div v-if="step === 1" class="ow-body">
            <p class="ow-desc">选择一个模型服务商，将自动填入接口地址与模型名：</p>
            <div class="ow-grid">
              <button
                v-for="p in presets"
                :key="p.key"
                class="ow-preset"
                :class="{ on: form.preset === p.key }"
                @click="pick(p)"
              >
                <span class="ow-pname">{{ p.label }}</span>
                <span class="ow-pmodel">{{ p.model }}</span>
              </button>
            </div>
            <p v-if="!presets.length" class="ow-desc">（暂无预设，请手动填写下方字段）</p>
            <div class="ow-foot">
              <button class="ow-btn ow-btn--ghost" @click="emit('close')">取消</button>
              <!-- 自定义预设 base_url 为空也允许进入下一步，在字段页手动填写 -->
              <button class="ow-btn ow-btn--primary" @click="step = 2">下一步</button>
            </div>
          </div>

          <!-- 步骤 2 / 表单模式：字段填写 -->
          <div v-else-if="step === 2" class="ow-body">
            <div class="ow-field">
              <label>名称</label>
              <input v-model="form.name" class="ow-input" placeholder="如：我的 DeepSeek" />
            </div>
            <div class="ow-field">
              <label>接口地址（Base URL）</label>
              <input v-model="form.base_url" class="ow-input" placeholder="https://..." />
            </div>
            <div class="ow-field">
              <label>模型名称</label>
              <input v-model="form.model" class="ow-input" placeholder="如：deepseek-chat" />
            </div>
            <div class="ow-field">
              <label>API Key</label>
              <input
                v-model="form.api_key"
                type="password"
                class="ow-input"
                :placeholder="isEdit ? '留空则保留原密钥' : 'sk-...'"
              />
            </div>
            <div class="ow-grid2">
              <div class="ow-field">
                <label>温度 (0–2)</label>
                <input v-model.number="form.temperature" type="number" step="0.1" min="0" max="2" class="ow-input" />
              </div>
              <div class="ow-field">
                <label>最大 Token</label>
                <input v-model.number="form.max_tokens" type="number" class="ow-input" />
              </div>
              <div class="ow-field">
                <label>超时（秒）</label>
                <input v-model.number="form.timeout" type="number" class="ow-input" />
              </div>
              <div class="ow-field ow-field--checks">
                <label class="ow-check"><input v-model="form.is_default" type="checkbox" /> 设为默认模型</label>
                <label class="ow-check"><input v-model="form.enabled" type="checkbox" /> 启用该模型</label>
              </div>
            </div>

            <p v-if="testResult" class="ow-test" :class="{ err: testResult.includes('失败') }">{{ testResult }}</p>
            <p v-if="error" class="ow-test err">{{ error }}</p>

            <div class="ow-foot">
              <button v-if="mode === 'wizard'" class="ow-btn ow-btn--ghost" @click="step = 1">上一步</button>
              <button v-else class="ow-btn ow-btn--ghost" @click="emit('close')">取消</button>
              <button class="ow-btn ow-btn--secondary" :disabled="!canTest || testing" @click="test">
                {{ testing ? '测试中…' : '测试连接' }}
              </button>
              <button class="ow-btn ow-btn--primary" :disabled="!canSave || saving" @click="save">
                {{ saving ? '保存中…' : isEdit ? '保存修改' : '保存并完成' }}
              </button>
            </div>
          </div>

          <!-- 步骤 3：完成（仅向导模式） -->
          <div v-else class="ow-body ow-done">
            <div class="ow-ok"><AppIcon name="check-circle" size="xl" /></div>
            <p class="ow-desc" style="text-align:center">配置完成！现在可以生成第一份每日复盘报告。</p>
            <div class="ow-foot" style="justify-content:center">
              <button class="ow-btn ow-btn--primary" @click="save">开始使用</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ow-mask { position: fixed; inset: 0; z-index: 1100; background: rgba(15, 25, 20, 0.45); display: flex; align-items: center; justify-content: center; padding: 20px; }
.ow-panel { width: min(780px, 94vw); max-height: 92vh; overflow-y: auto; background: var(--ff-bg-surface); border-radius: 16px; box-shadow: 0 16px 48px rgba(10, 30, 22, 0.3); border: 1px solid var(--ff-border); }
.ow-head { display: flex; align-items: center; justify-content: space-between; padding: 18px 26px; border-bottom: 1px solid var(--ff-border); position: sticky; top: 0; background: var(--ff-bg-surface); z-index: 2; }
.ow-title { display: flex; align-items: center; gap: 9px; font-size: 17px; font-weight: 700; color: var(--ff-text-primary); }
.ow-title :deep(svg) { color: var(--ff-brand); }
.ow-x { border: none; background: none; color: var(--ff-text-3); cursor: pointer; padding: 5px; border-radius: 6px; }
.ow-x:hover { background: var(--ff-bg-hover); }
.ow-steps { display: flex; gap: 10px; padding: 14px 26px; background: var(--ff-bg-subtle); border-bottom: 1px solid var(--ff-border); }
.ow-step { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--ff-text-3); font-weight: 600; }
.ow-step.on { color: var(--ff-brand-dark); }
.ow-step.done { color: var(--ff-brand); }
.ow-dot { width: 19px; height: 19px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11.5px; background: var(--ff-bg-subtle); color: var(--ff-text-3); }
.ow-step.on .ow-dot { background: var(--ff-brand); color: var(--ff-bg-surface); }
.ow-step.done .ow-dot { background: var(--ff-brand-subtle); color: var(--ff-brand); }
.ow-body { padding: 24px 26px; }
.ow-desc { font-size: 13.5px; color: var(--ff-text-secondary); margin-bottom: 15px; }
.ow-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; max-height: 320px; overflow-y: auto; }
.ow-preset { display: flex; flex-direction: column; gap: 3px; padding: 13px 14px; border: 1.5px solid var(--ff-border); border-radius: 11px; background: var(--ff-bg-surface); cursor: pointer; text-align: left; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); }
.ow-preset:hover { border-color: var(--ff-border-brand); }
.ow-preset.on { border-color: var(--ff-brand); background: var(--ff-bg-brand-subtle); box-shadow: 0 0 0 3px var(--ff-bg-brand-subtle); }
.ow-pname { font-size: 13.5px; font-weight: 600; color: var(--ff-text-primary); }
.ow-pmodel { font-size: 11.5px; color: var(--ff-text-3); font-family: var(--ff-font-mono, ui-monospace, monospace); }
.ow-grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.ow-field { margin-bottom: 14px; }
.ow-field label { display: block; font-size: 12.5px; font-weight: 600; color: var(--ff-text-secondary); margin-bottom: 6px; }
.ow-field--checks { display: flex; flex-direction: column; gap: 8px; justify-content: flex-end; padding-bottom: 2px; }
.ow-field--checks label { margin: 0; display: flex; align-items: center; gap: 7px; font-weight: 500; }
.ow-input { width: 100%; height: 40px; border: 1px solid var(--ff-border); border-radius: 10px; padding: 0 13px; font-size: 13.5px; outline: none; background: var(--ff-bg-surface); color: var(--ff-text-primary); transition: border-color 120ms, box-shadow 120ms; font-family: inherit; }
.ow-input:focus { border-color: var(--ff-border-focus); box-shadow: 0 0 0 3px var(--ff-focus-ring); }
.ow-check { font-size: 13px; color: var(--ff-text-primary); cursor: pointer; }
.ow-check input { width: 15px; height: 15px; accent-color: var(--ff-brand); }
.ow-test { font-size: 12.5px; color: var(--ff-brand); margin: 4px 0 10px; }
.ow-test.err { color: var(--ff-up); }
.ow-foot { display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px; }
.ow-btn { height: 38px; padding: 0 20px; border-radius: 10px; font-size: 13.5px; font-weight: 600; cursor: pointer; border: none; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard); }
.ow-btn--primary { background: var(--ff-brand); color: var(--ff-bg-surface); }
.ow-btn--primary:hover { background: var(--ff-brand-dark); }
.ow-btn--primary:disabled { opacity: 0.45; cursor: not-allowed; }
.ow-btn--secondary { background: var(--ff-bg-subtle); color: var(--ff-text-primary); border: 1px solid var(--ff-border); }
.ow-btn--secondary:disabled { opacity: 0.45; cursor: not-allowed; }
.ow-btn--ghost { background: none; color: var(--ff-text-2); }
.ow-done { display: flex; flex-direction: column; align-items: center; padding: 36px 26px; }
.ow-ok { color: var(--ff-brand); margin-bottom: 12px; }
.ow-fade-enter-active, .ow-fade-leave-active { transition: opacity 180ms, transform 180ms; }
.ow-fade-enter-from, .ow-fade-leave-to { opacity: 0; transform: translateY(10px) scale(0.98); }

@media (max-width: 900px) {
  .ow-grid { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 640px) {
  .ow-grid { grid-template-columns: 1fr; }
  .ow-grid2 { grid-template-columns: 1fr; }
}
</style>
