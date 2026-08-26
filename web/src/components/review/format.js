/**
 * 盘面复盘卡片公共格式化工具。
 * 红涨绿跌：up = 红（--ff-text-up），down = 绿（--ff-down-text）。
 */

// 金额/数量 → 万/亿 缩写（单位：元）
export function fmtAmount(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  const abs = Math.abs(n)
  const sign = n < 0 ? '-' : ''
  if (abs >= 1e8) return sign + (abs / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return sign + (abs / 1e4).toFixed(2) + '万'
  return sign + abs.toFixed(0)
}

// 带符号金额（主力净流入等）
export function fmtSignedAmount(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  if (n > 0) return '+' + fmtAmount(n)
  if (n < 0) return fmtAmount(n)
  return '0'
}

// 涨跌幅：带符号百分比
export function fmtChg(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  const n = Number(v)
  return (n > 0 ? '+' : '') + n.toFixed(2) + '%'
}

// 涨跌方向 class：is-up / is-down / is-flat
export function chgClass(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return 'is-flat'
  const n = Number(v)
  return n > 0 ? 'is-up' : n < 0 ? 'is-down' : 'is-flat'
}

// 价格：保留 2 位小数
export function fmtPrice(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  return Number(v).toFixed(2)
}

// 比率（换手率等）：保留 1 位小数（不带符号）
export function fmtRatio(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  return Number(v).toFixed(1)
}

// 千分位整数
export function fmtInt(v) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '—'
  return Number(v).toLocaleString('en-US')
}
