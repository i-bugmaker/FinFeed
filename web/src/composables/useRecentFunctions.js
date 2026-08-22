// 本地记忆工具：收藏功能 / 最近使用功能 / 最近标的
// 统一 localStorage 封装，key 前缀 ff:etdx:，版本化便于未来迁移。

const PREFIX = 'ff:etdx:v1:'
const MAX_RECENT_FUNCS = 8
const MAX_RECENT_STOCKS = 5
const MAX_FAVORITES = 30

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    if (!raw) return fallback
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : fallback
  } catch {
    return fallback
  }
}

function write(key, value) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    /* 存储不可用时静默降级 */
  }
}

// ---------------- 收藏功能 ----------------
export function loadFavorites() {
  return read('favorites', [])
}

export function saveFavorites(list) {
  write('favorites', list.slice(0, MAX_FAVORITES))
}

// 返回 { list, added }：added=true 表示本次为新增（用于 toast 撤销）
export function toggleFavorite(list, id) {
  const idx = list.indexOf(id)
  if (idx >= 0) {
    const next = list.slice()
    next.splice(idx, 1)
    return { list: next, added: false }
  }
  return { list: [id, ...list].slice(0, MAX_FAVORITES), added: true }
}

// ---------------- 最近使用功能 ----------------
export function loadRecentFuncs() {
  return read('recentFuncs', []) // [{ id, ts }]
}

export function saveRecentFuncs(list) {
  write('recentFuncs', list.slice(0, MAX_RECENT_FUNCS))
}

export function pushRecentFunc(list, id) {
  const next = [{ id, ts: Date.now() }, ...list.filter((r) => r.id !== id)]
  return next.slice(0, MAX_RECENT_FUNCS)
}

// ---------------- 最近标的 ----------------
export function loadRecentStocks() {
  return read('recentStocks', []) // [{ market, code, name }]
}

export function saveRecentStocks(list) {
  write('recentStocks', list.slice(0, MAX_RECENT_STOCKS))
}

export function pushRecentStock(list, stock) {
  if (!stock || !stock.code) return list
  const next = [stock, ...list.filter((s) => s.code !== stock.code)]
  return next.slice(0, MAX_RECENT_STOCKS)
}
