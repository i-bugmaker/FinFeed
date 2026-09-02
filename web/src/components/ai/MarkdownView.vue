<script setup>
/**
 * MarkdownView — 轻量安全 Markdown 渲染器
 * 零依赖：仅解析报告/对话中常见的结构化语法（标题/表格/列表/引用/代码块/分隔线/强调），
 * 所有原始文本一律 HTML 转义后输出，杜绝 XSS；不解析任意 HTML。
 */
import { computed } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
  // 紧凑模式：缩小间距（用于对话气泡内）
  compact: { type: Boolean, default: false },
})

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inline(text) {
  let s = escapeHtml(text)
  // 彩色标记 ==色::文本== / ==文本==（安全：纯文本标记，不引入 HTML）
  // 支持色名：红/绿/橙/蓝/灰/紫；无前缀时用品牌强调色
  const COLOR_NAMES = { 红: 'red', 绿: 'green', 橙: 'orange', 蓝: 'blue', 灰: 'gray', 紫: 'purple' }
  s = s.replace(/==(红|绿|橙|蓝|灰|紫)::(.+?)==/g, (m, c, t) => `<span class="c-${COLOR_NAMES[c]}">${t}</span>`)
  s = s.replace(/==(.+?)==/g, '<span class="c-brand">$1</span>')
  // 代码段 `code`
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  // 粗体 **x** 与 __x__
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/__([^_]+)__/g, '<strong>$1</strong>')
  // 链接 [t](u) — 仅允许 http(s) 与 # 内部链接
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
  s = s.replace(/\[([^\]]+)\]\(#([^)\s]+)\)/g, '<a href="#$2">$1</a>')
  return s
}

const html = computed(() => {
  const lines = String(props.content || '').split(/\r?\n/)
  const out = []
  let i = 0
  let listType = null // 'ul' | 'ol'
  let listHtml = []

  function flushList() {
    if (listType) {
      out.push(`<${listType}>${listHtml.join('')}</${listType}>`)
      listType = null
      listHtml = []
    }
  }
  function inTable(cols) {
    flushList()
    out.push(
      '<div class="md-table"><table><thead><tr>' +
        cols.map((c) => `<th>${inline(c.trim())}</th>`).join('') +
        '</tr></thead><tbody>'
    )
    i += 2 // 跳过表头与分隔行
    while (i < lines.length && lines[i].trim().startsWith('|')) {
      const cells = lines[i].trim().slice(1, -1).split('|')
      out.push('<tr>' + cells.map((c) => `<td>${inline(c.trim())}</td>`).join('') + '</tr>')
      i++
    }
    out.push('</tbody></table></div>')
  }

  while (i < lines.length) {
    const raw = lines[i]
    const line = raw.trim()

    // 代码块
    if (line.startsWith('```')) {
      flushList()
      i++
      const buf = []
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        buf.push(escapeHtml(lines[i]))
        i++
      }
      i++ // 跳过闭合
      out.push(`<pre><code>${buf.join('\n')}</code></pre>`)
      continue
    }

    // 表格（表头含 | 且下一行是分隔线）
    if (line.startsWith('|') && i + 1 < lines.length && /^[\s|:-\s]+$/.test(lines[i + 1].trim()) && lines[i + 1].includes('-')) {
      inTable(line.slice(1, -1).split('|'))
      continue
    }

    // 标题
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      flushList()
      // # 与 ## 同级渲染为 h2；## 是报告目录级（带 data-anchor 供 TOC 跳转/高亮），
      // ### / #### 依次降级为 h3 / h4（此前 #### 被错误升级为 h2）
      const n = h[1].length
      const tag = n === 1 ? 2 : n
      const anchor = encodeURIComponent(h[2].trim())
      out.push(
        `<h${tag}${tag === 2 ? ` data-anchor="${anchor}"` : ''}>${inline(h[2])}</h${tag}>`
      )
      i++
      continue
    }

    // 分隔线
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flushList()
      out.push('<hr/>')
      i++
      continue
    }

    // 引用
    if (line.startsWith('>')) {
      flushList()
      const buf = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        buf.push(inline(lines[i].trim().replace(/^>\s?/, '')))
        i++
      }
      out.push(`<blockquote>${buf.join('<br/>')}</blockquote>`)
      continue
    }

    // 列表
    const ul = line.match(/^[-*•]\s+(.*)$/)
    const ol = line.match(/^\d+[.、]\s+(.*)$/)
    if (ul || ol) {
      const type = ul ? 'ul' : 'ol'
      const content = ul ? ul[1] : ol[1]
      if (listType !== type) {
        flushList()
        listType = type
      }
      listHtml.push(`<li>${inline(content)}</li>`)
      i++
      continue
    }
    flushList()

    // 空行
    if (!line) {
      i++
      continue
    }

    // 普通段落
    const buf = [inline(line)]
    i++
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|[-*•]\s|\d+[.、]\s|>\s|-\s*$)/.test(lines[i].trim()) && !lines[i].trim().startsWith('|')) {
      buf.push('<br/>' + inline(lines[i]))
      i++
    }
    out.push(`<p>${buf.join('')}</p>`)
  }
  flushList()
  return out.join('')
})
</script>

<template>
  <div class="mdv" :class="compact && 'mdv--compact'" v-html="html"></div>
</template>

<style scoped>
.mdv { font-size: var(--ff-fs-body-sm); line-height: 1.7; color: var(--ff-text-primary); word-break: break-word; }
.mdv :deep(h2) { font-size: var(--ff-fs-h3); font-weight: 700; margin: 20px 0 10px; padding-left: 10px; border-left: 3px solid var(--ff-brand); }
.mdv :deep(h3) { font-size: var(--ff-fs-body); font-weight: 600; margin: 16px 0 8px; }
.mdv :deep(h4) { font-size: var(--ff-fs-body-sm); font-weight: 600; margin: 14px 0 6px; color: var(--ff-text-secondary); }
.mdv :deep(p) { margin: 8px 0; }
.mdv :deep(ul), .mdv :deep(ol) { margin: 8px 0; padding-left: 22px; }
.mdv :deep(li) { margin: 4px 0; }
.mdv :deep(strong) { font-weight: 700; }
.mdv :deep(.c-brand) { color: var(--ff-brand-text, #ff5f3b); font-weight: 700; }
.mdv :deep(.c-red) { color: var(--ff-up-text); font-weight: 700; }
.mdv :deep(.c-green) { color: var(--ff-down-text); font-weight: 700; }
.mdv :deep(.c-orange) { color: var(--ff-hot-text); font-weight: 700; }
.mdv :deep(.c-blue) { color: var(--ff-text-link); font-weight: 700; }
.mdv :deep(.c-gray) { color: var(--ff-text-secondary); font-weight: 700; }
.mdv :deep(.c-purple) { color: var(--ff-accent-violet); font-weight: 700; }
.mdv :deep(code) { font-family: var(--ff-font-mono, ui-monospace, monospace); font-size: var(--ff-fs-caption); background: var(--ff-bg-subtle); padding: 1px 6px; border-radius: 5px; }
.mdv :deep(pre) { background: var(--ff-bg-subtle); border: 1px solid var(--ff-border); border-radius: 10px; padding: 12px 14px; overflow-x: auto; margin: 10px 0; }
.mdv :deep(pre code) { background: none; padding: 0; font-size: var(--ff-fs-caption); line-height: 1.6; }
.mdv :deep(blockquote) { margin: 10px 0; padding: 8px 14px; border-left: 3px solid var(--ff-border-brand); background: var(--ff-bg-subtle); border-radius: 0 8px 8px 0; color: var(--ff-text-secondary); }
.mdv :deep(hr) { border: none; border-top: 1px dashed var(--ff-border); margin: 16px 0; }
.mdv :deep(a) { color: var(--ff-brand); text-decoration: underline; text-underline-offset: 2px; }
.mdv :deep(table) { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: var(--ff-fs-caption); }
.mdv :deep(th) { background: var(--ff-bg-subtle); font-weight: 600; text-align: left; padding: 7px 10px; border: 1px solid var(--ff-border); color: var(--ff-text-secondary); font-size: var(--ff-fs-xs); }
.mdv :deep(td) { padding: 7px 10px; border: 1px solid var(--ff-border); }
.mdv :deep(.md-table) { overflow-x: auto; }
.mdv--compact { font-size: var(--ff-fs-caption); line-height: 1.6; }
.mdv--compact :deep(h2) { font-size: var(--ff-fs-body); margin: 12px 0 6px; }
.mdv--compact :deep(p) { margin: 6px 0; }
.mdv--compact :deep(table) { font-size: var(--ff-fs-xs); }

/* ── 移动端适配（D4）：代码块横向滚动 ── */
@media (max-width: 768px) {
  :deep(pre) {
    max-width: 100%;
    overflow-x: auto;
  }
  :deep(table) {
    display: block;
    overflow-x: auto;
  }
}
</style>
