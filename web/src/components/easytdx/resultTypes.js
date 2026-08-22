// 结果渲染注册表：按 (type, func.chart, 数据特征) 决定渲染策略
// 供 EasyTdxResultPanel 分发，新增结果类型只需在此注册

// 判定：结果是否命中「K线/走势类」渲染（图表优先）
export function isChartFirst(result, func) {
  if (!result || result.type !== 'table' || !func?.chart) return false
  return ['candle', 'line'].includes(func.chart)
}

// 判定：KPI 卡 + 表格（排行/资金流/报价类）
export function isKpiTable(result) {
  if (!result || result.type !== 'table') return false
  const cols = (result.columns || []).map((c) => String(c).toLowerCase())
  return cols.some((c) => /(pct_chg|change_pct|涨跌幅|main_net|main_net_amount)/.test(c))
}

// 判定：股票列表（code + name 列）
export function isStockList(result) {
  if (!result || result.type !== 'table') return false
  const cols = result.columns || []
  return cols.includes('code') && cols.includes('name')
}

// 判定：回测 JSON（含 performance 或 equity/trades）
export function isBacktestJson(result) {
  if (!result || result.type !== 'json') return false
  const d = result.data || {}
  return !!(d.performance || d.equity || d.trades)
}

// 判定：普通键值 JSON
export function isPlainJson(result) {
  return !!result && result.type === 'json'
}
