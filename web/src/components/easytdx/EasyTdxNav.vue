<script setup>
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'

const props = defineProps({
  groups: { type: Array, default: () => [] }, // [{ id, label, icon, items:[{id,label}] }]
  activeId: { type: String, default: '' },
  query: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const q = computed(() => props.query.trim().toLowerCase())

const filtered = computed(() => {
  if (!q.value) return props.groups
  return props.groups
    .map((g) => ({
      ...g,
      items: g.items.filter(
        (f) => f.label.toLowerCase().includes(q.value) || f.id.toLowerCase().includes(q.value),
      ),
    }))
    .filter((g) => g.items.length > 0)
})

const total = computed(() => props.groups.reduce((n, g) => n + g.items.length, 0))
</script>

<template>
  <nav class="etdx-nav" aria-label="easy-tdx 功能导航">
    <div class="etdx-nav__search">
      <AppIcon name="search" size="sm" class="etdx-nav__search-icon" />
      <input
        :value="query"
        class="etdx-nav__search-input"
        placeholder="搜索功能…"
        @input="emit('update:query', $event.target.value)"
      />
    </div>
    <p class="etdx-nav__count">{{ total }} 项功能</p>

    <div v-for="g in filtered" :key="g.id" class="etdx-nav__group">
      <div class="etdx-nav__group-head">
        <AppIcon v-if="g.icon" :name="g.icon" size="sm" class="etdx-nav__group-icon" />
        <span>{{ g.label }}</span>
        <span class="etdx-nav__group-badge">{{ g.items.length }}</span>
      </div>
      <ul class="etdx-nav__list">
        <li v-for="f in g.items" :key="f.id">
          <button
            type="button"
            class="etdx-nav__item"
            :class="activeId === f.id && 'etdx-nav__item--active'"
            @click="emit('select', f.id)"
          >
            <span class="etdx-nav__item-label">{{ f.label }}</span>
            <span v-if="f.tag" class="etdx-nav__item-tag">{{ f.tag }}</span>
          </button>
        </li>
      </ul>
    </div>

    <p v-if="!filtered.length" class="etdx-nav__empty">无匹配功能</p>
  </nav>
</template>

<style scoped>
.etdx-nav {
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-3);
  padding: var(--ff-space-3);
  height: 100%;
  overflow-y: auto;
}
.etdx-nav__search {
  position: relative;
  display: flex;
  align-items: center;
}
.etdx-nav__search-icon {
  position: absolute;
  left: 10px;
  color: var(--ff-icon-muted);
  pointer-events: none;
}
.etdx-nav__search-input {
  width: 100%;
  height: 36px;
  padding: 0 var(--ff-space-3) 0 32px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-body-sm);
  outline: none;
  transition: border-color var(--ff-dur-fast);
}
.etdx-nav__search-input:focus {
  border-color: var(--ff-border-brand);
}
.etdx-nav__count {
  margin: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
}
.etdx-nav__group {
  margin-bottom: var(--ff-space-2);
}
.etdx-nav__group-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-1) var(--ff-space-2);
  font-size: var(--ff-fs-caption);
  font-weight: 600;
  color: var(--ff-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.etdx-nav__group-icon {
  color: var(--ff-icon-muted);
}
.etdx-nav__group-badge {
  margin-left: auto;
  background: var(--ff-bg-subtle);
  color: var(--ff-text-tertiary);
  border-radius: var(--ff-radius-pill);
  padding: 0 8px;
  font-size: var(--ff-fs-caption);
}
.etdx-nav__list {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.etdx-nav__item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  text-align: left;
  padding: 8px var(--ff-space-3);
  border: 1px solid transparent;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast);
}
.etdx-nav__item:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-nav__item--active {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
  font-weight: 600;
  border-color: var(--ff-border-brand-subtle);
}
.etdx-nav__item-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.etdx-nav__item-tag {
  flex-shrink: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 0 6px;
}
.etdx-nav__empty {
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-sm);
  text-align: center;
  padding: var(--ff-space-4);
}
</style>
