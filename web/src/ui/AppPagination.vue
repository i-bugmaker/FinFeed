<script setup>
/**
 * AppPagination — 自定义分页
 */
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import AppSelect from './AppSelect.vue'

const props = defineProps({
  modelValue: { type: Number, default: 1 },
  total: { type: Number, default: 0 },
  pageSize: { type: Number, default: 20 },
  pageSizes: { type: Array, default: () => [10, 20, 50, 100] },
  showSizeChanger: { type: Boolean, default: false },
  showTotal: { type: Boolean, default: true },
  size: { type: String, default: 'md' },
})

const emit = defineEmits(['update:modelValue', 'update:pageSize', 'change'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const start = computed(() => (props.total === 0 ? 0 : (props.modelValue - 1) * props.pageSize + 1))
const end = computed(() => Math.min(props.total, props.modelValue * props.pageSize))

const pages = computed(() => {
  const total = totalPages.value
  const current = props.modelValue
  const list = []
  if (total <= 7) {
    for (let i = 1; i <= total; i++) list.push(i)
  } else {
    if (current <= 4) {
      list.push(1, 2, 3, 4, 5, '...', total)
    } else if (current >= total - 3) {
      list.push(1, '...', total - 4, total - 3, total - 2, total - 1, total)
    } else {
      list.push(1, '...', current - 1, current, current + 1, '...', total)
    }
  }
  return list
})

const canPrev = computed(() => props.modelValue > 1)
const canNext = computed(() => props.modelValue < totalPages.value)

function go(page) {
  if (page === '...' || page < 1 || page > totalPages.value || page === props.modelValue) return
  emit('update:modelValue', page)
  emit('change', { page, pageSize: props.pageSize })
}

function prev() {
  if (canPrev.value) go(props.modelValue - 1)
}

function next() {
  if (canNext.value) go(props.modelValue + 1)
}

function onSizeChange(v) {
  emit('update:pageSize', v)
  emit('update:modelValue', 1)
  emit('change', { page: 1, pageSize: v })
}

const sizeOptions = computed(() =>
  props.pageSizes.map(s => ({ label: `${s} 条/页`, value: s }))
)
</script>

<template>
  <div class="ff-pagination" :class="`ff-pagination--${size}`">
    <div v-if="showTotal" class="ff-pagination__total">
      共 <strong>{{ total }}</strong> 条，{{ start }}–{{ end }}
    </div>
    <div class="ff-pagination__list">
      <button type="button" class="ff-pagination__btn" :disabled="!canPrev" @click="prev">
        <AppIcon name="chevron-left" size="xs" />
      </button>
      <button
        v-for="(p, idx) in pages"
        :key="`pg-${p}-${idx}`"
        type="button"
        class="ff-pagination__btn"
        :class="p === modelValue && 'ff-pagination__btn--active'"
        :disabled="p === '...'"
        @click="go(p)"
      >
        {{ p }}
      </button>
      <button type="button" class="ff-pagination__btn" :disabled="!canNext" @click="next">
        <AppIcon name="chevron-right" size="xs" />
      </button>
    </div>
    <AppSelect
      v-if="showSizeChanger"
      :model-value="pageSize"
      :options="sizeOptions"
      size="sm"
      class="ff-pagination__size"
      @update:model-value="onSizeChange"
    />
  </div>
</template>

<style scoped>
.ff-pagination__size {
  width: 110px;
}
</style>
