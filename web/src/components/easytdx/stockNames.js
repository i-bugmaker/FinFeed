// 股票名称工具：加载 FinFeed 全量 A 股名称映射（/api/stock_names），
// 提供代码/名称搜索与市场推断。供股票选择器与结果表格代码列美化使用。

import http from '@/shared/api/client'

let cache = null
let cachePromise = null

// 6 位代码 → 市场（沪深京）
export function inferMarket(code) {
  const c = String(code || '')
  if (/^(60|68|90|5)/.test(c)) return 'SH' // 沪市股票/基金
  if (/^(00|30|15|16)/.test(c)) return 'SZ' // 深市股票/基金
  if (/^(4|8|92)/.test(c)) return 'BJ' // 北交所
  return 'SH'
}

export async function loadStockNames() {
  if (cache) return cache
  if (!cachePromise) {
    cachePromise = http
      .get('/stock_names')
      .then((r) => {
        cache = (r.data && r.data.stock_names) || {}
        return cache
      })
      .catch(() => {
        cache = {}
        return cache
      })
  }
  return cachePromise
}

// 名称/代码搜索 → [{market, code, name}]（按相关性排序）
export async function searchStocks(q, limit = 8) {
  const names = await loadStockNames()
  const query = String(q || '').trim().toUpperCase()
  if (!query) return []
  const isCode = /^\d{1,6}$/.test(query)

  const hits = []
  for (const [code, name] of Object.entries(names)) {
    const nameU = String(name).toUpperCase()
    const codeHit = code.includes(query)
    const nameHit = nameU.includes(query)
    if (!codeHit && !nameHit) continue
    const market = inferMarket(code)
    hits.push({ market, code, name: String(name), score: rank(query, code, nameU, isCode) })
    if (hits.length >= 200) break
  }

  // 兜底：纯代码输入时，即使名称库缺失（后端未启动 / 接口失败）也能直选标的
  // 6 位代码 → 按规则推断市场，name 暂用代码占位
  if (isCode && query.length >= 4) {
    const exact = hits.find((h) => h.code === query)
    if (!exact) {
      hits.push({ market: inferMarket(query), code: query, name: String(query), score: 0.5, fallback: true })
    }
  }

  hits.sort((a, b) => a.score - b.score || a.code.localeCompare(b.code))
  return hits.slice(0, limit)
}

function rank(query, code, nameU, isCode) {
  if (isCode) {
    if (code === query) return 0
    if (code.startsWith(query)) return 1
    return 3
  }
  if (nameU === query) return 0
  if (nameU.startsWith(query)) return 1
  return 2
}

// 显示格式：贵州茅台 600519.SH
export function stockLabel(stock) {
  if (!stock) return ''
  return `${stock.name} ${stock.code}.${stock.market}`
}

// 标记显示：贵州茅台 (600519)
export function codeDisplay(code, name) {
  if (!code) return '—'
  if (name) return `${name} (${code})`
  return String(code)
}
