// easy-tdx 结果展示格式化工具：把原生数据（长小数/科学计数法/时间戳/英文列名等）
// 转换为美观、可读的中文界面呈现。仅影响展示，不改变底层数据。

// ---------------- 列名 → 中文映射 ----------------
const COLUMN_LABELS = {
  // 通用
  code: '代码', market: '市场', name: '名称', date: '日期', time: '时间',
  datetime: '时间', count: '数量', index: '序号', total: '总计',
  // K线 / 报价
  open: '开盘', high: '最高', low: '最低', close: '收盘', pre_close: '昨收',
  vol: '成交量', volume: '成交量', amount: '成交额', total_amount: '成交额',
  float_shares: '流通股本', total_shares: '总股本', vol_ratio: '量比',
  turnover: '换手率', turnover_ratio: '换手率', amplitude: '振幅',
  amplitude_pct: '振幅', change: '涨跌额', change_pct: '涨跌幅',
  pct_chg: '涨跌幅', price: '现价', avg: '均价', bid: '买一', ask: '卖一',
  buy_price_limit: '涨停价', sell_price_limit: '跌停价', last_volume: '最新成交量',
  eps: '每股收益', net_assets: '每股净资产', pe_dynamic: '市盈率(动)',
  pe_ttm: '市盈率TTM', pe_static: '市盈率(静)', dividend_yield: '股息率',
  total_market_cap_ab: '总市值', main_net_amount: '主力净流入',
  main_net: '主力净流入', lot_size: '每手股数', lot_size_info: '每手信息',
  speed_pct: '涨速', vol_speed_pct: '量速', short_turnover_pct: '短线换手',
  security_type_price: '证券类型价', decimal_point: '小数位',
  pre_iopv: '参考IOPV', flag_kcb: '科创板标记', stock_tag_flags: '标签',
  circulating_capital_z: '流通市值Z', price_decimal_info: '价格精度',
  // 板块
  board_symbol: '板块代码', board_name: '板块名称', category: '分类',
  codes: '成分股', member_count: '成分股数', up_count: '上涨家数',
  down_count: '下跌家数', main_net_3d: '主力净流入3日', main_net_5d: '主力净流入5日',
  // 回测
  total_return: '总收益率', annual_return: '年化收益', max_drawdown: '最大回撤',
  max_dd_duration: '回撤天数', sharpe: '夏普比率', sortino: '索提诺比率',
  win_rate: '胜率', profit_factor: '盈亏比', trade_count: '交易次数',
  direction: '方向', size: '数量', commission: '手续费', slippage: '滑点',
  pnl: '盈亏', cost_basis: '成本价', rejected: '被拒', cash: '现金',
  position_value: '持仓市值', drawdown: '回撤', drawdown_pct: '回撤比例',
  equity: '资金曲线', performance: '绩效指标', trades: '交易明细',
  strategy: '策略', fast: '快线周期', slow: '慢线周期',
  // 巨潮公告
  title: '标题', type: '类型', url: '链接', pdf_url: 'PDF链接',
  org_id: '机构ID', announcement_id: '公告ID', announcement_time: '公告时间',
  // 主机
  scope: '范围', host: '主机', port: '端口', latency: '延迟(秒)',
  latency_ms: '延迟(ms)', which: '主机类型',
  // 其他
  result: '结果', status: '状态', message: '消息', reason: '原因',
  rows: '行数', columns: '列数', filename: '文件名', size: '大小',
  start: '起始', end: '结束', category_name: '分类',
  // 逐笔 / 分时补充
  time: '时间', num: '笔数', buyorsell: '买卖方向', avg_price: '均价',
  // 财务补充
  report_date: '报告期', bvps: '每股净资产', roe: '净资产收益率',
  net_profit: '净利润', gross_margin: '毛利率', net_assets_ps: '每股净资产',
  // 除权除息补充
  plan_explain: '方案说明', progress: '进度', equity_reg_date: '股权登记日',
  ex_dividend_date: '除权除息日', cash_dividend: '现金分红',
  dividend_ratio: '送转比例', bonus_ratio: '送股比例',
  // 服务器 / 统计补充
  servername: '服务器', serverip: '服务器IP', security_count: '证券数量',
  market_count: '市场数量', instrument_count: '品种数量',
  // 汇总 / 排名补充
  avg_price_now: '现均价', avg_price_close: '收盘均价', rise_count: '上涨数',
  fall_count: '下跌数', flat_count: '平盘数', total_count: '总数',
}

// 客户端 → 中文
export const CLIENT_LABELS = {
  tdx: '通达信',
  mac: 'Mac',
  ex: '扩展行情',
  cninfo: '巨潮资讯',
  chanlun: '缠论',
  backtest: '回测',
  ping: '主机探测',
  host: '主机配置',
}

export function clientLabel(c) {
  if (c == null) return ''
  return CLIENT_LABELS[String(c).toLowerCase()] || String(c)
}

export function columnLabel(col) {
  if (col == null) return ''
  return COLUMN_LABELS[String(col).toLowerCase()] || String(col)
}

// ---------------- 数值工具 ----------------
function thousands(v, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: digits })
}

// 大数 → 万/亿 缩写
function compact(v) {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  const abs = Math.abs(n)
  if (abs >= 1e8) return (n / 1e8).toFixed(2).replace(/\.?0+$/, '') + '亿'
  if (abs >= 1e4) return (n / 1e4).toFixed(2).replace(/\.?0+$/, '') + '万'
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function fmtFixed(v, digits = 2) {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  return n.toFixed(digits)
}

// 时间戳（毫秒/秒）→ 日期时间
function fmtTs(v) {
  let n = Number(v)
  if (!Number.isFinite(n) || n <= 0) return String(v)
  if (n > 1e12) n = Math.floor(n / 1000) // 毫秒 → 秒
  const d = new Date(n * 1000)
  const p = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// 百分比：易 tdx 的 pct/turnover 等已是百分数值（如 3.45 表示 3.45%）
// 回测比例类（total_return 等）多为 0~1 小数，|v|<=1 时 ×100
function fmtPct(v, ratioStyle = false) {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v)
  if (ratioStyle && Math.abs(n) <= 1) return (n * 100).toFixed(2) + '%'
  return n.toFixed(2) + '%'
}

// 市场代码 0/1/2 → SZ/SH/BJ
const MARKET_NAMES = { 0: 'SZ', 1: 'SH', 2: 'BJ' }

// 特殊列的格式化规则（命中即返回格式化后的字符串，未命中返回 null）
const SPECIAL = [
  { re: /^(market|market_type)$/, fn: (v) => MARKET_NAMES[Number(v)] || String(v) },
  { re: /^(total_return|annual_return|max_drawdown|drawdown_pct|win_rate)$/,
    fn: (v) => fmtPct(v, true) },
  { re: /(pct|ratio|percent|turnover|amplitude|speed)$|^rate$|yield/,
    fn: (v) => fmtPct(v, false) },
  { re: /(amount|_mv$|_cap_|market_cap)/, fn: (v) => compact(v) },
  { re: /(^|_)(vol|volume|shares|lot|position_value|drawdown)(_|$)/, fn: (v) => compact(v) },
  { re: /(open|high|low|close|pre_close|price|avg|bid|ask|limit|cost_basis|pnl|cash|total)$|(^|_)(open|high|low|close|price|pnl|cash|total)(_|$)/,
    fn: (v) => fmtFixed(v, 2) },
]

// 主格式化入口：单元格值 → 展示文本
export function cellText(value, col) {
  if (value === null || value === undefined || value === '') return '—'
  const c = String(col || '').toLowerCase()

  // 布尔
  if (typeof value === 'boolean') return value ? '是' : '否'

  // 数字
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '—'
    // 时间戳
    if (/ts$|timestamp/.test(c) || value > 1e12) return fmtTs(value)
    for (const s of SPECIAL) {
      if (s.re.test(c)) return s.fn(value)
    }
    // 通用数字：大数缩写，小数保留 2 位
    if (Math.abs(value) >= 1e6) return compact(value)
    if (Number.isInteger(value)) return thousands(value, 0)
    return fmtFixed(value, 2)
  }

  // 字符串
  if (typeof value === 'string') {
    const s = value.trim()
    // 8 位数字 → 日期
    if (/^\d{8}$/.test(s)) return s.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
    // 'YYYY-MM-DD 00:00:00' → 只留日期
    if (/^\d{4}-\d{2}-\d{2} 00:00:00$/.test(s)) return s.slice(0, 10)
    // 买卖方向
    if (s === 'buy') return '买入'
    if (s === 'sell') return '卖出'
    // Python 列表字符串（板块成分等）
    if (s.startsWith('[') && s.length > 60) {
      const arr = s.slice(1, -1).replace(/'/g, '').split(',').map((x) => x.trim()).filter(Boolean)
      if (arr.length > 12) return arr.slice(0, 12).join(' ') + ` … 等 ${arr.length} 只`
      return arr.join(' ')
    }
    return s
  }

  return String(value)
}

// 单元格是否为链接（渲染为可点击）
export function isLink(value, col) {
  const c = String(col || '').toLowerCase()
  if (/url|link|href|pdf_url/.test(c) && typeof value === 'string' && /^https?:/.test(value)) {
    return true
  }
  return false
}

// 长文本截断（用于 title 提示）
export function fullText(value) {
  return value === null || value === undefined ? '' : String(value)
}
