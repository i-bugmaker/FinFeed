<script setup>
/**
 * ReportSummaryCard — 报告摘要卡
 * 从报告正文提取「摘要」段落生成 10 秒可读的结论卡（前端规则提取，LLM 提炼为后续增强）。
 */
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  report: { type: Object, default: null },
})

const summary = computed(() => {
  const c = props.report?.content || ''
  // 优先取「摘要/结论」章节，其次取正文前 2 段
  const m = c.match(/(?:摘要|核心结论|结论)[：:]\s*\n?([^\n]+(?:\n[^\n]+){0,4})/i)
  if (m) return m[1].trim()
  const first = c.split(/\n{2,}/).filter((p) => p.trim()).slice(0, 2).join(' ')
  return first.slice(0, 160)
})

const tags = computed(() => {
  const c = props.report?.content || ''
  const found = []
  const re = /(半导体|新能源|消费电子|医药|人工智能|机器人|低空经济|军工|地产|券商|白酒|汽车|光伏|储能|算力|AI|机器人|芯片)/g
  const m = c.match(re)
  if (m) found.push(...[...new Set(m)].slice(0, 4))
  return found
})
</script>

<template>
  <div v-if="report" class="rsc">
    <div class="rsc__label"><AppIcon name="sparkles" size="xs" /> 摘要结论</div>
    <p class="rsc__text">{{ summary || '（暂无摘要内容）' }}</p>
    <div v-if="tags.length" class="rsc__tags">
      <span v-for="t in tags" :key="t" class="rsc__tag">{{ t }}</span>
    </div>
  </div>
</template>

<style scoped>
.rsc { background: var(--ff-bg-brand-subtle); border: 1px solid var(--ff-border-brand); border-radius: 12px; padding: 14px 16px; }
.rsc__label { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 700; color: var(--ff-brand-dark); letter-spacing: .05em; margin-bottom: 7px; }
.rsc__text { font-size: 13.5px; line-height: 1.7; color: var(--ff-text-primary); margin: 0; }
.rsc__tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.rsc__tag { font-size: 11px; font-weight: 600; color: var(--ff-brand-dark); background: var(--ff-bg-surface); border: 1px solid var(--ff-border-brand); padding: 2px 9px; border-radius: 10px; }
</style>
