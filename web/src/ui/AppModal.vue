<script setup>
/**
 * AppModal — 自定义弹窗
 *
 * 支持标题栏、页脚按钮插槽、点击遮罩关闭、ESC 关闭、尺寸变体。
 */
import { ref, watch, onMounted, onUnmounted } from 'vue'
import AppIcon from './AppIcon.vue'
import AppButton from './AppButton.vue'
import { useFocusTrap } from './useFocusTrap'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  size: { type: String, default: 'md' }, // sm / md / lg / xl
  closable: { type: Boolean, default: true },
  maskClosable: { type: Boolean, default: true },
  showCancel: { type: Boolean, default: true },
  showOk: { type: Boolean, default: true },
  okText: { type: String, default: '确认' },
  cancelText: { type: String, default: '取消' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue', 'ok', 'cancel', 'close'])

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function onMaskClick() {
  if (props.maskClosable && props.closable) close()
}

function onKeydown(e) {
  if (e.key === 'Escape' && props.modelValue && props.closable) close()
}

function onOk() {
  emit('ok')
}

function onCancel() {
  emit('cancel')
  close()
}

watch(() => props.modelValue, v => {
  document.body.classList.toggle('ff-modal-open', v)
})

// 焦点管理：打开聚焦首个控件、Tab 锁定在弹窗内、关闭归还焦点
const overlayRef = ref(null)
useFocusTrap(() => props.modelValue, () => overlayRef.value)

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  document.body.classList.remove('ff-modal-open')
})
</script>

<template>
  <Teleport to="body">
    <Transition name="ff-modal">
      <div v-show="modelValue" ref="overlayRef" class="ff-overlay" role="presentation" @click.self="onMaskClick">
        <div class="ff-modal" :class="`ff-modal--${size}`" role="dialog" aria-modal="true" :aria-labelledby="title ? 'ff-modal-title' : undefined">
          <div v-if="title || closable" class="ff-modal__header">
            <h3 v-if="title" id="ff-modal-title" class="ff-modal__title">{{ title }}</h3>
            <button v-if="closable" type="button" class="ff-modal__close" aria-label="关闭" @click="close">
              <AppIcon name="x" size="sm" />
            </button>
          </div>
          <div class="ff-modal__body">
            <slot />
          </div>
          <div v-if="$slots.footer || showCancel || showOk" class="ff-modal__footer">
            <slot name="footer">
              <AppButton v-if="showCancel" variant="secondary" @click="onCancel">{{ cancelText }}</AppButton>
              <AppButton v-if="showOk" variant="primary" :loading="loading" @click="onOk">{{ okText }}</AppButton>
            </slot>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
