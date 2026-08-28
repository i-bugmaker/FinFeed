<script setup>
/**
 * SessionList — 分析师会话列表
 * 分组（今天/本周/更早）展示持久化会话，支持新建/选中/重命名/删除。
 */
import { computed, ref } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: Number, default: null },
})
const emit = defineEmits(['select', 'create', 'rename', 'delete'])

const renaming = ref(null)
const renameText = ref('')

function groupTitle(ts) {
  if (!ts) return '更早'
  const d = new Date(ts * 1000)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay) return '今天'
  if (d.toDateString() === yesterday.toDateString()) return '昨天'
  if (now.getTime() - d.getTime() < 7 * 864e5) return '本周'
  return '更早'
}

const groups = computed(() => {
  const map = new Map()
  for (const s of props.sessions) {
    const g = groupTitle(s.created_ts || s.updated_ts)
    if (!map.has(g)) map.set(g, [])
    map.get(g).push(s)
  }
  return [...map.entries()]
})

function startRename(s) {
  renaming.value = s.id
  renameText.value = s.title || ''
}
function commitRename() {
  const t = renameText.value.trim()
  if (renaming.value && t) emit('rename', renaming.value, t)
  renaming.value = null
}
function onDelete(s) {
  if (window.confirm(`删除会话「${s.title || '新会话'}」？消息将一并删除。`)) emit('delete', s.id)
}
</script>

<template>
  <div class="sl">
    <button class="sl__new" @click="emit('create')">
      <AppIcon name="plus" size="sm" />
      <span>新建会话</span>
    </button>
    <div class="sl__scroll">
      <template v-for="[g, items] in groups" :key="g">
        <div class="sl__group">{{ g }}</div>
        <div
          v-for="s in items"
          :key="s.id"
          class="sl__item"
          :class="{ on: s.id === activeId }"
          @click="emit('select', s.id)"
        >
          <template v-if="renaming === s.id">
            <input
              v-model="renameText"
              class="sl__rename"
              autofocus
              @keyup.enter="commitRename"
              @keyup.esc="renaming = null"
              @click.stop
            />
          </template>
          <template v-else>
            <AppIcon name="chatter" size="sm" class="sl__ic" />
            <span class="sl__title">{{ s.title || '新会话' }}</span>
            <span class="sl__meta">{{ s.msg_count || 0 }}</span>
            <button class="sl__ops" title="重命名" @click.stop="startRename(s)">
              <AppIcon name="edit" size="xs" />
            </button>
            <button class="sl__ops sl__ops--del" title="删除" @click.stop="onDelete(s)">
              <AppIcon name="trash" size="xs" />
            </button>
          </template>
        </div>
      </template>
      <div v-if="!sessions.length" class="sl__empty">暂无会话<br>点击「新建会话」开始</div>
    </div>
  </div>
</template>

<style scoped>
.sl { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.sl__new {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  width: 100%; padding: 8px 0; margin-bottom: 10px;
  border: 1.5px dashed var(--ff-border, #c3cdc8); border-radius: 9px;
  background: var(--ff-bg-surface, #fff); color: var(--ff-text-secondary, #6b7280);
  font-size: 13px; font-weight: 600; cursor: pointer; transition: background-color var(--ff-dur-fast) var(--ff-ease-standard), border-color var(--ff-dur-fast) var(--ff-ease-standard), color var(--ff-dur-fast) var(--ff-ease-standard), box-shadow var(--ff-dur-fast) var(--ff-ease-standard), transform var(--ff-dur-fast) var(--ff-ease-standard);
}
.sl__new:hover { border-color: var(--ff-brand, #2f7d5b); color: var(--ff-brand, #2f7d5b); background: var(--ff-bg-brand-subtle, #eaf4ef); }
.sl__scroll { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.sl__group { font-size: 11px; font-weight: 700; color: var(--ff-text-3, #9ca3af); letter-spacing: .05em; padding: 10px 6px 4px; }
.sl__item {
  display: flex; align-items: center; gap: 7px; padding: 7px 8px;
  border-radius: 8px; cursor: pointer; transition: background 120ms;
  border: 1px solid transparent;
}
.sl__item:hover { background: var(--ff-bg-hover, #f3f6f4); }
.sl__item.on { background: var(--ff-bg-brand-subtle, #eaf4ef); border-color: var(--ff-border-brand, #9fc3b1); }
.sl__ic { color: var(--ff-text-3, #9ca3af); flex-shrink: 0; }
.sl__item.on .sl__ic { color: var(--ff-brand, #2f7d5b); }
.sl__title { flex: 1; font-size: 12.5px; color: var(--ff-text-primary, #1f2937); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sl__meta { font-size: 10px; color: var(--ff-text-3, #9ca3af); flex-shrink: 0; }
.sl__ops {
  display: none; align-items: center; justify-content: center; width: 20px; height: 20px;
  border: none; background: none; color: var(--ff-text-3, #9ca3af); border-radius: 5px; cursor: pointer; padding: 0; flex-shrink: 0;
}
.sl__ops--del:hover { color: var(--ff-down, #e5484d); }
.sl__item:hover .sl__ops { display: inline-flex; }
.sl__rename { flex: 1; font-size: 12.5px; border: 1px solid var(--ff-border-focus, #4f9e76); border-radius: 6px; padding: 3px 6px; outline: none; min-width: 0; }
.sl__empty { text-align: center; color: var(--ff-text-3, #9ca3af); font-size: 12px; padding: 28px 0; line-height: 1.8; }
</style>
