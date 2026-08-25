<script setup>
/**
 * OnboardWizard — 首次配置 3 步向导
 * 无可用模型时弹出：选择预设 → 填写 Key → 测试连通 → 完成。
 */
import { ref } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  presets: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'done'])

const step = ref(1)
const form = ref({
  name: '', preset: 'deepseek', base_url: '', model: '', api_key: '',
})
const testing = ref(false)
const testResult = ref('')
const error = ref('')

function pick(p) {
  form.value.preset = p.key
  form.value.base_url = p.base_url
  form.value.model = p.model
  form.value.name = p.label
}

async function test() {
  testing.value = true
  testResult.value = '测试中…'
  error.value = ''
  try {
    const { api } = await import('../../api/client')
    const r = await api.llmPost('/provider/test', {
      name: form.value.name || '默认模型',
      preset: form.value.preset,
      base_url: form.value.base_url,
      model: form.value.model,
      api_key: form.value.api_key,
      is_default: true,
      enabled: true,
    })
    if (r && r.ok) {
      testResult.value = `连通正常（${r.model || ''}）${r.latency_ms ? ' · ' + Math.round(r.latency_ms) + 'ms' : ''}`
      step.value = 3
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
  error.value = ''
  try {
    const { api } = await import('../../api/client')
    const r = await api.llmPost('/provider/save', {
      name: form.value.name || '默认模型',
      preset: form.value.preset,
      base_url: form.value.base_url,
      model: form.value.model,
      api_key: form.value.api_key,
      temperature: 0.3,
      max_tokens: 4096,
      timeout: 120,
      is_default: true,
      enabled: true,
    })
    if (r && r.success) {
      emit('done')
    } else {
      error.value = r?.error || '保存失败'
    }
  } catch (e) {
    error.value = '保存失败：' + (e.message || e)
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="ow-fade">
      <div v-if="open" class="ow-mask" @click.self="emit('close')">
        <div class="ow-panel">
          <div class="ow-head">
            <div class="ow-title"><AppIcon name="sparkles" size="md" /> 配置 AI 分析模型</div>
            <button class="ow-x" @click="emit('close')"><AppIcon name="x" size="sm" /></button>
          </div>

          <!-- 步骤指示 -->
          <div class="ow-steps">
            <span v-for="(s, i) in ['选择模型', '填写密钥', '完成']" :key="s" class="ow-step" :class="{ on: i + 1 === step, done: i + 1 < step }">
              <span class="ow-dot">{{ i + 1 < step ? '✓' : i + 1 }}</span>{{ s }}
            </span>
          </div>

          <!-- 步骤 1：选择预设 -->
          <div v-if="step === 1" class="ow-body">
            <p class="ow-desc">选择一个模型服务商，将自动填入接口地址与模型名：</p>
            <div class="ow-grid">
              <button v-for="p in presets" :key="p.key" class="ow-preset" :class="{ on: form.preset === p.key }" @click="pick(p)">
                <span class="ow-pname">{{ p.label }}</span>
                <span class="ow-pmodel">{{ p.model }}</span>
              </button>
            </div>
            <div class="ow-foot">
              <button class="ow-btn ow-btn--ghost" @click="emit('close')">暂不配置</button>
              <button class="ow-btn ow-btn--primary" :disabled="!form.base_url" @click="step = 2">下一步</button>
            </div>
          </div>

          <!-- 步骤 2：填写 Key -->
          <div v-else-if="step === 2" class="ow-body">
            <div class="ow-field">
              <label>名称</label>
              <input v-model="form.name" class="ow-input" placeholder="如：我的 DeepSeek" />
            </div>
            <div class="ow-field">
              <label>API Key</label>
              <input v-model="form.api_key" type="password" class="ow-input" placeholder="sk-..." />
            </div>
            <div class="ow-field">
              <label>接口地址</label>
              <input v-model="form.base_url" class="ow-input" />
            </div>
            <div class="ow-field">
              <label>模型名称</label>
              <input v-model="form.model" class="ow-input" />
            </div>
            <p v-if="testResult" class="ow-test" :class="{ err: testResult.includes('失败') }">{{ testResult }}</p>
            <div class="ow-foot">
              <button class="ow-btn ow-btn--ghost" @click="step = 1">上一步</button>
              <button class="ow-btn ow-btn--secondary" :loading="testing" @click="test">{{ testing ? '测试中…' : '测试连接' }}</button>
              <button class="ow-btn ow-btn--primary" :disabled="!form.api_key || !testResult.includes('连通正常')" @click="save">保存并完成</button>
            </div>
          </div>

          <!-- 步骤 3：完成 -->
          <div v-else class="ow-body ow-done">
            <div class="ow-ok"><AppIcon name="check-circle" size="xl" /></div>
            <p class="ow-desc" style="text-align:center">配置完成！现在可以生成第一份每日复盘报告。</p>
            <div class="ow-foot" style="justify-content:center">
              <button class="ow-btn ow-btn--primary" @click="emit('done')">开始使用</button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ow-mask { position: fixed; inset: 0; z-index: 1100; background: rgba(15, 25, 20, 0.45); display: flex; align-items: center; justify-content: center; padding: 20px; }
.ow-panel { width: 520px; max-width: 100%; background: var(--ff-bg-surface, #fff); border-radius: 16px; box-shadow: 0 16px 48px rgba(10, 30, 22, 0.3); border: 1px solid var(--ff-border, #e5e7eb); overflow: hidden; }
.ow-head { display: flex; align-items: center; justify-content: space-between; padding: 16px 20px; border-bottom: 1px solid var(--ff-border, #e5e7eb); }
.ow-title { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; color: var(--ff-text-primary, #1f2937); }
.ow-title :deep(svg) { color: var(--ff-brand, #2f7d5b); }
.ow-x { border: none; background: none; color: var(--ff-text-3, #9ca3af); cursor: pointer; padding: 4px; border-radius: 6px; }
.ow-x:hover { background: var(--ff-bg-hover, #f3f4f6); }
.ow-steps { display: flex; gap: 8px; padding: 14px 20px; background: var(--ff-bg-subtle, #f9fafb); border-bottom: 1px solid var(--ff-border, #e5e7eb); }
.ow-step { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ff-text-3, #9ca3af); font-weight: 600; }
.ow-step.on { color: var(--ff-brand-dark, #1d4e39); }
.ow-step.done { color: var(--ff-brand, #2f7d5b); }
.ow-dot { width: 18px; height: 18px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11px; background: var(--ff-bg-subtle, #e5e9e7); color: var(--ff-text-3, #9ca3af); }
.ow-step.on .ow-dot { background: var(--ff-brand, #2f7d5b); color: #fff; }
.ow-step.done .ow-dot { background: var(--ff-brand-subtle, #eaf4ef); color: var(--ff-brand, #2f7d5b); }
.ow-body { padding: 20px; }
.ow-desc { font-size: 13px; color: var(--ff-text-secondary, #6b7280); margin-bottom: 14px; }
.ow-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; max-height: 300px; overflow-y: auto; }
.ow-preset { display: flex; flex-direction: column; gap: 2px; padding: 10px 12px; border: 1.5px solid var(--ff-border, #e5e7eb); border-radius: 10px; background: #fff; cursor: pointer; text-align: left; transition: all 120ms; }
.ow-preset:hover { border-color: var(--ff-border-brand, #9fc3b1); }
.ow-preset.on { border-color: var(--ff-brand, #2f7d5b); background: var(--ff-bg-brand-subtle, #eaf4ef); box-shadow: 0 0 0 3px var(--ff-bg-brand-subtle, #eaf4ef); }
.ow-pname { font-size: 13px; font-weight: 600; color: var(--ff-text-primary, #1f2937); }
.ow-pmodel { font-size: 11px; color: var(--ff-text-3, #9ca3af); font-family: var(--ff-font-mono, ui-monospace, monospace); }
.ow-field { margin-bottom: 12px; }
.ow-field label { display: block; font-size: 12px; font-weight: 600; color: var(--ff-text-secondary, #6b7280); margin-bottom: 5px; }
.ow-input { width: 100%; height: 36px; border: 1px solid var(--ff-border, #d1d5db); border-radius: 9px; padding: 0 12px; font-size: 13px; outline: none; background: #fff; color: var(--ff-text-primary, #1f2937); transition: border-color 120ms, box-shadow 120ms; }
.ow-input:focus { border-color: var(--ff-border-focus, #4f9e76); box-shadow: 0 0 0 3px var(--ff-focus-ring, rgba(47, 125, 91, 0.15)); }
.ow-test { font-size: 12px; color: var(--ff-brand, #2f7d5b); margin: 4px 0 10px; }
.ow-test.err { color: var(--ff-down, #e5484d); }
.ow-foot { display: flex; gap: 10px; justify-content: flex-end; margin-top: 18px; }
.ow-btn { height: 34px; padding: 0 16px; border-radius: 9px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 120ms; }
.ow-btn--primary { background: var(--ff-brand, #2f7d5b); color: #fff; }
.ow-btn--primary:hover { background: var(--ff-brand-dark, #1d4e39); }
.ow-btn--primary:disabled { opacity: 0.45; cursor: not-allowed; }
.ow-btn--secondary { background: var(--ff-bg-subtle, #f1f4f2); color: var(--ff-text-primary, #1f2937); border: 1px solid var(--ff-border, #d8dfdb); }
.ow-btn--ghost { background: none; color: var(--ff-text-2, #6b7280); }
.ow-done { display: flex; flex-direction: column; align-items: center; padding: 32px 20px; }
.ow-ok { color: var(--ff-brand, #2f7d5b); margin-bottom: 10px; }
.ow-fade-enter-active, .ow-fade-leave-active { transition: opacity 180ms, transform 180ms; }
.ow-fade-enter-from, .ow-fade-leave-to { opacity: 0; transform: translateY(10px) scale(0.98); }
</style>
