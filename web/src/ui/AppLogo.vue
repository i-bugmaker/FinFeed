<script setup>
/**
 * AppLogo — 品牌标识组件
 *
 * 提供 mark / wordmark / combined 三种布局，支持主题自动反色与尺寸缩放。
 * 使用内联 SVG 几何（与 public/logo.svg 保持一致），可直接跟随当前色彩模式。
 */
import { computed } from 'vue'
import { useAppStore } from '../store/app'

const props = defineProps({
  mode: { type: String, default: 'combined' }, // 'mark' | 'wordmark' | 'combined'
  size: { type: [Number, String], default: 32 }, // mark height px
  width: { type: [Number, String], default: null }, // combined/lockup width px
  variant: { type: String, default: 'color' }, // 'color' | 'mono' | 'dark'
})

const store = useAppStore()

const isDark = computed(() => store.theme === 'dark')
const isColor = computed(() => props.variant === 'color')

const markSize = computed(() => Number(props.size || 32))
const markClasses = computed(() => [
  'ff-logo__mark',
  isColor.value && 'ff-logo__mark--color',
])

const wordColor = computed(() => {
  if (isColor.value) return null
  return isDark.value ? '#f4f6f9' : '#0f172a'
})

// v4.3 品牌色定蓝（与 public/logo.svg / gen_brand_assets.py 保持一致）。
// 3.0 森林绿 #2f7d5b 因与 A 股「跌 = 绿」语义撞车被否决，详见 DESIGN_SYSTEM.md §3.1。
const brandColor = '#2563eb'
const wordSize = computed(() => Math.round(markSize.value * 0.48))
const wordGap = computed(() => Math.round(markSize.value * 0.28))
</script>

<template>
  <div class="ff-logo" :class="[`ff-logo--${mode}`, `ff-logo--${variant}`]">
    <svg
      v-if="mode !== 'wordmark'"
      :class="markClasses"
      :width="markSize"
      :height="markSize"
      viewBox="0 0 48 48"
      fill="none"
      role="img"
      aria-label="FinFeed"
    >
      <title>FinFeed</title>
      <defs v-if="isColor">
        <linearGradient id="ffLogoGrad" x1="4" y1="2" x2="44" y2="46" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#4f8dff" />
          <stop offset="0.55" stop-color="#2563eb" />
          <stop offset="1" stop-color="#1b3fb8" />
        </linearGradient>
        <linearGradient id="ffLogoGloss" x1="24" y1="0" x2="24" y2="30" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#ffffff" stop-opacity="0.22" />
          <stop offset="1" stop-color="#ffffff" stop-opacity="0" />
        </linearGradient>
      </defs>

      <rect x="0" y="0" width="48" height="48" rx="11.5" :fill="isColor ? 'url(#ffLogoGrad)' : 'currentColor'" />
      <rect
        v-if="isColor"
        x="0" y="0" width="48" height="48" rx="11.5"
        fill="url(#ffLogoGloss)"
      />
      <rect
        x="0.6" y="0.6" width="46.8" height="46.8" rx="10.9"
        fill="none"
        :stroke="isColor ? '#ffffff' : 'currentColor'"
        :stroke-opacity="isColor ? 0.18 : 0.25"
        stroke-width="1.2"
      />

      <path d="M11 35.4H34" stroke="currentColor" stroke-opacity="0.4" stroke-width="2.4" stroke-linecap="round" />
      <path d="M11 30L18.5 22.5L25 27.5L34 15" fill="none" stroke="currentColor" stroke-width="3.8" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="34" cy="15" r="3.6" fill="currentColor" />
    </svg>

    <span v-if="mode !== 'mark'" class="ff-logo__wordmark" :style="{ fontSize: `${wordSize}px`, marginLeft: `${wordGap}px` }">
      <span class="ff-logo__fin" :style="{ color: wordColor || (isDark ? '#f4f6f9' : '#0f172a') }">Fin</span>
      <span class="ff-logo__feed" :style="{ color: brandColor }">Feed</span>
    </span>
  </div>
</template>

<style scoped>
.ff-logo {
  display: inline-flex;
  align-items: center;
  color: var(--ff-icon-inverse);
  user-select: none;
}

.ff-logo__mark--color {
  color: #ffffff;
}

.ff-logo__wordmark {
  font-family: var(--ff-font-sans);
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1;
  white-space: nowrap;
}

.ff-logo__fin,
.ff-logo__feed {
  transition: color var(--ff-dur-fast) var(--ff-ease-out);
}
</style>
