<script setup>
/**
 * HighlightText — 关键词高亮（安全、非 v-html）
 *
 * 将关键词（支持空格分隔的多关键词）在文本中匹配并以 <mark> 高亮。
 * 采用「切分为文本片段 + <mark> 节点」方式渲染，绝不拼接 HTML，避免 XSS。
 */
import { computed } from 'vue'

const props = defineProps({
  text: { type: String, default: '' },
  keyword: { type: String, default: '' },
})

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const parts = computed(() => {
  const kw = (props.keyword || '').trim()
  const t = props.text || ''
  if (!kw || !t) return [{ text: t, hit: false }]

  const kws = kw
    .split(/\s+/)
    .filter(Boolean)
    .map(escapeRegExp)
  if (!kws.length) return [{ text: t, hit: false }]

  const re = new RegExp(`(${kws.join('|')})`, 'gi')
  const out = []
  let last = 0
  let m
  while ((m = re.exec(t)) !== null) {
    if (m.index > last) out.push({ text: t.slice(last, m.index), hit: false })
    out.push({ text: m[0], hit: true })
    last = m.index + m[0].length
    if (m.index === re.lastIndex) re.lastIndex++ // 防零宽匹配死循环
  }
  if (last < t.length) out.push({ text: t.slice(last), hit: false })
  return out
})
</script>

<template>
  <span class="ff-hl">
    <template v-for="(p, i) in parts" :key="i">
      <mark v-if="p.hit" class="ff-hl__mark">{{ p.text }}</mark>
      <template v-else>{{ p.text }}</template>
    </template>
  </span>
</template>

<style scoped>
.ff-hl {
  /* 继承父级字体设置 */
}

.ff-hl__mark {
  background: var(--ff-brand-subtle);
  color: var(--ff-brand-text);
  border-radius: 3px;
  padding: 0 2px;
  font-weight: 600;
  /* 不破坏原有换行/省略规则 */
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
</style>
