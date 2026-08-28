<script setup>
// Zone B · 功能导航栏：全部 / 收藏 / 最近 + 搜索 + 折叠 + 收藏拖拽排序
import { computed } from 'vue'
import AppIcon from '../../ui/AppIcon.vue'
import { useEasytdxStore } from '../../store/easytdx'
import { clientLabel } from './format'
import { toast } from '../../composables/useToast'

const store = useEasytdxStore()

const TABS = [
  { value: 'all', label: '全部', icon: 'list' },
  { value: 'fav', label: '收藏', icon: 'star' },
  { value: 'recent', label: '最近', icon: 'clock' },
]

const q = computed(() => store.ui.query.trim().toLowerCase())

const filteredGroups = computed(() => {
  if (!q.value) return store.navGroups
  return store.navGroups
    .map((g) => ({
      ...g,
      items: g.items.filter(
        (f) => f.label.toLowerCase().includes(q.value) || f.id.toLowerCase().includes(q.value),
      ),
    }))
    .filter((g) => g.items.length > 0)
})

const favItems = computed(() =>
  store.favorites
    .map((id) => store.meta?.functions.find((f) => f.id === id))
    .filter(Boolean)
    .map((f) => ({ id: f.id, label: f.label, tag: store.groupLabels[f.group], client: f.client })),
)

const recentItems = computed(() =>
  store.recentFuncs
    .map((r) => store.meta?.functions.find((f) => f.id === r.id))
    .filter(Boolean)
    .map((f) => ({ id: f.id, label: f.label, tag: store.groupLabels[f.group], client: f.client })),
)

function select(id) {
  store.selectFunc(id)
}

// 收藏拖拽排序（HTML5 DnD）
let dragId = null
function onDragStart(id) {
  dragId = id
}
function onDragOver(e, id) {
  if (!dragId || dragId === id) return
  e.preventDefault()
}
function onDrop(e, id) {
  e.preventDefault()
  if (!dragId || dragId === id) return
  const from = store.favorites.indexOf(dragId)
  const to = store.favorites.indexOf(id)
  store.moveFavorite(from, to)
  dragId = null
}

function onFavClick(id) {
  const added = store.toggleFav(id)
  const func = store.meta?.functions.find((f) => f.id === id)
  toast({
    type: 'info',
    message: added ? `已收藏「${func?.label || id}」` : `已取消收藏「${func?.label || id}」`,
    action: added ? '撤销' : '',
    onAction: () => store.toggleFav(id),
  })
}
</script>

<template>
  <nav class="etdx-rail" :class="{ 'is-collapsed': store.ui.railCollapsed }" aria-label="easy-tdx 功能导航">
    <div class="etdx-rail__head">
      <button
        type="button"
        class="etdx-rail__collapse"
        :title="store.ui.railCollapsed ? '展开导航' : '收起导航'"
        @click="store.toggleRailCollapsed()"
      >
        <AppIcon :name="store.ui.railCollapsed ? 'chevrons-right' : 'chevrons-left'" size="sm" />
      </button>
      <span v-if="!store.ui.railCollapsed" class="etdx-rail__title">功能导航</span>
    </div>

    <template v-if="!store.ui.railCollapsed">
      <div class="etdx-rail__tabs" role="tablist">
        <button
          v-for="t in TABS"
          :key="t.value"
          type="button"
          class="etdx-rail__tab"
          :class="{ 'is-active': store.ui.railTab === t.value }"
          role="tab"
          :aria-selected="store.ui.railTab === t.value"
          @click="store.setRailTab(t.value)"
        >
          <AppIcon :name="t.icon" size="xs" />
          {{ t.label }}
          <span v-if="t.value === 'fav' && store.favorites.length" class="etdx-rail__tab-badge">
            {{ store.favorites.length }}
          </span>
        </button>
      </div>

      <div v-if="store.ui.railTab === 'all'" class="etdx-rail__search">
        <AppIcon name="search" size="sm" class="etdx-rail__search-icon" />
        <input
          :value="store.ui.query"
          class="etdx-rail__search-input"
          placeholder="搜索功能…"
          @input="store.setQuery($event.target.value)"
        />
      </div>

      <div class="etdx-rail__body">
        <!-- 全部：按场景分组 -->
        <template v-if="store.ui.railTab === 'all'">
          <div v-for="g in filteredGroups" :key="g.id" class="etdx-rail__group">
            <div class="etdx-rail__group-head">
              <AppIcon :name="g.icon" size="sm" class="etdx-rail__group-icon" />
              <span>{{ g.label }}</span>
              <span class="etdx-rail__group-badge">{{ g.items.length }}</span>
            </div>
            <ul class="etdx-rail__list">
              <li v-for="f in g.items" :key="f.id">
                <button
                  type="button"
                  class="etdx-rail__item"
                  :class="{ 'is-active': store.selectedFuncId === f.id }"
                  :aria-current="store.selectedFuncId === f.id"
                  @click="select(f.id)"
                >
                  <span class="etdx-rail__item-label">{{ f.label }}</span>
                  <span v-if="f.tag" class="etdx-rail__item-tag">{{ f.tag }}</span>
                  <span
                    class="etdx-rail__item-star"
                    :class="{ 'is-fav': store.isFavorite(f.id) }"
                    title="收藏"
                    @click.stop="onFavClick(f.id)"
                  >
                    <AppIcon :name="store.isFavorite(f.id) ? 'star-filled' : 'star'" size="xs" />
                  </span>
                </button>
              </li>
            </ul>
          </div>
          <p v-if="!filteredGroups.length" class="etdx-rail__empty">无匹配功能</p>
        </template>

        <!-- 收藏：支持拖拽排序 -->
        <template v-else-if="store.ui.railTab === 'fav'">
          <ul v-if="favItems.length" class="etdx-rail__list">
            <li
              v-for="f in favItems"
              :key="f.id"
              draggable="true"
              @dragstart="onDragStart(f.id)"
              @dragover="onDragOver($event, f.id)"
              @drop="onDrop($event, f.id)"
            >
              <button
                type="button"
                class="etdx-rail__item"
                :class="{ 'is-active': store.selectedFuncId === f.id }"
                :aria-current="store.selectedFuncId === f.id"
                @click="select(f.id)"
              >
                <AppIcon name="star-filled" size="xs" class="etdx-rail__item-favicon" />
                <span class="etdx-rail__item-label">{{ f.label }}</span>
                <span class="etdx-rail__item-tag">{{ clientLabel(f.client) }}</span>
                <span
                  class="etdx-rail__item-star is-fav"
                  title="取消收藏"
                  @click.stop="onFavClick(f.id)"
                >
                  <AppIcon name="x" size="xs" />
                </span>
              </button>
            </li>
          </ul>
          <div v-else class="etdx-rail__empty">
            <AppIcon name="star" size="md" />
            <p>暂无收藏</p>
            <span>在功能上点击 ★ 即可收藏</span>
          </div>
        </template>

        <!-- 最近 -->
        <template v-else>
          <ul v-if="recentItems.length" class="etdx-rail__list">
            <li v-for="f in recentItems" :key="f.id">
              <button
                type="button"
                class="etdx-rail__item"
                :class="{ 'is-active': store.selectedFuncId === f.id }"
                :aria-current="store.selectedFuncId === f.id"
                @click="select(f.id)"
              >
                <AppIcon name="clock" size="xs" class="etdx-rail__item-favicon" />
                <span class="etdx-rail__item-label">{{ f.label }}</span>
                <span class="etdx-rail__item-tag">{{ clientLabel(f.client) }}</span>
              </button>
            </li>
          </ul>
          <div v-else class="etdx-rail__empty">
            <AppIcon name="clock" size="md" />
            <p>暂无使用记录</p>
          </div>
        </template>
      </div>
    </template>
  </nav>
</template>

<style scoped>
.etdx-rail {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--ff-bg-surface);
  border: 1px solid var(--ff-border-subtle);
  border-radius: var(--ff-radius-lg);
  overflow: hidden;
  transition: width 200ms var(--ff-ease-spring);
}
.etdx-rail__head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-2-5) var(--ff-space-3);
  border-bottom: 1px solid var(--ff-border-subtle);
}
.etdx-rail__collapse {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-icon-muted);
  cursor: pointer;
}
.etdx-rail__collapse:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-rail__title {
  font-size: var(--ff-fs-body-sm);
  font-weight: 700;
  color: var(--ff-text-secondary);
}
.etdx-rail__tabs {
  display: flex;
  gap: 4px;
  padding: var(--ff-space-2) var(--ff-space-3) 0;
}
.etdx-rail__tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: none;
  border-radius: var(--ff-radius-pill);
  background: transparent;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  cursor: pointer;
  position: relative;
}
.etdx-rail__tab:hover {
  background: var(--ff-bg-hover);
}
.etdx-rail__tab.is-active {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
  font-weight: 600;
}
.etdx-rail__tab-badge {
  font-size: var(--ff-fs-caption);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 0 6px;
  color: var(--ff-text-tertiary);
}
.etdx-rail__search {
  position: relative;
  display: flex;
  align-items: center;
  padding: var(--ff-space-2) var(--ff-space-3);
}
.etdx-rail__search-icon {
  position: absolute;
  left: calc(var(--ff-space-3) + 10px);
  color: var(--ff-icon-muted);
  pointer-events: none;
}
.etdx-rail__search-input {
  width: 100%;
  height: 34px;
  padding: 0 var(--ff-space-3) 0 34px;
  border: 1px solid var(--ff-border);
  border-radius: var(--ff-radius-md);
  background: var(--ff-bg-surface);
  color: var(--ff-text-primary);
  font-size: var(--ff-fs-body-sm);
  outline: none;
  transition: border-color var(--ff-dur-fast);
}
.etdx-rail__search-input:focus {
  border-color: var(--ff-border-brand);
}
.etdx-rail__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--ff-space-1) var(--ff-space-3) var(--ff-space-3);
  display: flex;
  flex-direction: column;
  gap: var(--ff-space-2);
}
.etdx-rail__group-head {
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  padding: var(--ff-space-2) var(--ff-space-1);
  font-size: var(--ff-fs-caption);
  font-weight: 700;
  color: var(--ff-text-secondary);
  letter-spacing: 0.04em;
}
.etdx-rail__group-icon {
  color: var(--ff-icon-muted);
}
.etdx-rail__group-badge {
  margin-left: auto;
  background: var(--ff-bg-subtle);
  color: var(--ff-text-tertiary);
  border-radius: var(--ff-radius-pill);
  padding: 0 8px;
  font-size: var(--ff-fs-caption);
}
.etdx-rail__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.etdx-rail__item {
  width: 100%;
  display: flex;
  align-items: center;
  gap: var(--ff-space-2);
  text-align: left;
  padding: 8px var(--ff-space-2-5);
  border: 1px solid transparent;
  border-radius: var(--ff-radius-sm);
  background: transparent;
  color: var(--ff-text-secondary);
  font-size: var(--ff-fs-body-sm);
  cursor: pointer;
  transition: background var(--ff-dur-fast), color var(--ff-dur-fast), border-color var(--ff-dur-fast);
}
.etdx-rail__item:hover {
  background: var(--ff-bg-hover);
  color: var(--ff-text-primary);
}
.etdx-rail__item.is-active {
  background: var(--ff-bg-brand-subtle);
  color: var(--ff-text-brand);
  font-weight: 600;
  border-color: var(--ff-border-brand-subtle);
}
.etdx-rail__item-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.etdx-rail__item-tag {
  flex-shrink: 0;
  font-size: var(--ff-fs-caption);
  color: var(--ff-text-tertiary);
  background: var(--ff-bg-subtle);
  border-radius: var(--ff-radius-pill);
  padding: 0 6px;
}
.etdx-rail__item-star {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: var(--ff-radius-xs);
  color: var(--ff-icon-muted);
  opacity: 0;
  transition: opacity var(--ff-dur-fast), color var(--ff-dur-fast);
  flex-shrink: 0;
}
.etdx-rail__item:hover .etdx-rail__item-star,
.etdx-rail__item-star.is-fav {
  opacity: 1;
}
.etdx-rail__item-star:hover {
  color: var(--ff-star);
}
.etdx-rail__item-star.is-fav {
  color: var(--ff-star);
}
.etdx-rail__item-favicon {
  color: var(--ff-star);
  flex-shrink: 0;
}
.etdx-rail__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: var(--ff-text-tertiary);
  font-size: var(--ff-fs-body-sm);
  text-align: center;
  padding: var(--ff-space-6) var(--ff-space-4);
}
.etdx-rail__empty p {
  margin: 4px 0 0;
  font-weight: 600;
  color: var(--ff-text-secondary);
}
.etdx-rail__empty span {
  font-size: var(--ff-fs-caption);
}
/* 折叠态 */
.etdx-rail.is-collapsed .etdx-rail__head {
  justify-content: center;
  padding: var(--ff-space-2-5) var(--ff-space-1);
}
</style>
