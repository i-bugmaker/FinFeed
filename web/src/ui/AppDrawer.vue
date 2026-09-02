<script setup>
/**
 * AppDrawer — 自定义抽屉
 */
import { watch, onUnmounted } from 'vue'
import AppIcon from './AppIcon.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  placement: { type: String, default: 'left' }, // left / right
  size: { type: String, default: 'md' }, // sm / md / lg
  closable: { type: Boolean, default: true },
  maskClosable: { type: Boolean, default: true },
})

const emit = defineEmits(['update:modelValue', 'close'])

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function onMaskClick() {
  if (props.maskClosable) close()
}

watch(() => props.modelValue, v => {
  document.body.classList.toggle('ff-drawer-open', v)
})

onUnmounted(() => {
  document.body.classList.remove('ff-drawer-open')
})
</script>

<template>
  <Teleport to="body">
    <Transition name="ff-overlay">
      <div v-show="modelValue" class="ff-overlay ff-overlay--drawer" role="presentation" @click.self="onMaskClick">
        <Transition :name="placement === 'right' ? 'ff-drawer-right' : 'ff-drawer'">
          <div
            v-show="modelValue"
            class="ff-drawer"
            :class="[`ff-drawer--${placement}`, `ff-drawer--${size}`]"
            role="dialog"
            aria-modal="true"
            :aria-labelledby="title ? 'ff-drawer-title' : undefined"
          >
            <div v-if="title || closable" class="ff-drawer__header">
              <h3 v-if="title" id="ff-drawer-title" class="ff-drawer__title">{{ title }}</h3>
              <button v-if="closable" type="button" class="ff-drawer__close" aria-label="关闭" @click="close">
                <AppIcon name="x" size="sm" />
              </button>
            </div>
            <div class="ff-drawer__body">
              <slot />
            </div>
            <div v-if="$slots.footer" class="ff-drawer__footer">
              <slot name="footer" />
            </div>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>
