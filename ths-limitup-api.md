# 同花顺「涨停聚焦」数据接口清单

> 抓取分析日期：2026-08-17 ｜ 数据样例日期：2026-08-14（交易日）
> 目标页面：`https://data.10jqka.com.cn/mobile/limitup/v2/index.html`（移动版）
> PC 版 `https://data.10jqka.com.cn/limitup/` 已改版下线（404），数据全部来自移动版后端接口。

---

## 0. 调用前置条件（重要）

1. **先访问 `https://data.10jqka.com.cn/`** 建立会话 Cookie（`Invoke-WebRequest -WebSession`）。
2. 所有 mobileapi 请求必须带以下请求头：
   - `Source-id: PROGRAM-limt-up-focus`
   - `PlatForm: mobileweb`
   - `Referer: https://data.10jqka.com.cn/mobile/limitup/v2/index.html`
   - `User-Agent: Mozilla/5.0`
3. `date` 参数为交易日期，格式 `yyyyMMdd`（如 `20260814`）；非交易日请求返回空数据。
4. 编码注意：终端输出中文可能显示为 GBK 乱码，但 JSON 响应内容本身为正常 UTF-8。

---

## 1. 四大模块 → 接口映射

| 用户需求 | 推荐接口 |
|---|---|
| **涨停强度** | `dataapi/limit_up/limit_up_pool`（涨停池）、`dataapi/limit_up/open_limit_pool`（炸板池）、`dataapi/limit_up/lower_limit_pool`（跌停池） |
| **强势股 / 连板天梯** | `dataapi/limit_up/continuous_limit_up`（连板天梯）、`stock_pool/v1/get_limit_up_stocks`（连板分层池） |
| **最强风口** | `market_state/v1/get_wind_vane_stock`（风向标股）、`dataapi/tagservice/fetch/v1/tag_data`（涨停原因标签） |
| **市场情绪** | `market_state/v1/overview`（市场情绪总览）、`dataapi/limit_up/trade_status`（交易状态） |
| （辅助/图表） | `stock_pool/v1/get_tab_info`（池配置）、`chart/v1/get_chart`（图表）、`limit_up_compare/v1/*`（涨停对比） |

---

## 2. dataapi 接口（`https://data.10jqka.com.cn/dataapi/`）

> 无需 Source-id 头，建会话后直接可调；返回 `{"status_code":0,"data":{...},"status_msg":"success"}`。

### 2.1 涨停池 —— 涨停强度 ✅ 已验证
```
GET /dataapi/limit_up/limit_up_pool?page=1&limit=50&field=199112,10,9001,330323,330324&filter=HS,GEM2STAR&order_field=330324&order_type=0&_=1755324xxxx
```
- 当日涨停 62 只（total=62），`data.list` 为个股数组。
- `field` 用**数字字段 ID** 逗号分隔（如 `199112`=代码、`10`=名称、`9001`=涨停原因、`330323`=最新价、`330324`=涨跌幅）。
- `filter=HS,GEM2STAR` 表示沪深主板+创业板+科创板。

### 2.2 炸板池 —— 涨停强度 ✅ 已验证
```
GET /dataapi/limit_up/open_limit_pool?page=1&limit=50&field=...&filter=HS,GEM2STAR&order_field=...&order_type=0&_=...
```
- 当日炸板 19 只（total=19），参数结构同涨停池。

### 2.3 跌停池 —— 涨停强度 ✅ 已验证
```
GET /dataapi/limit_up/lower_limit_pool?page=1&limit=50&field=...&filter=HS,GEM2STAR&order_field=...&order_type=0&_=...
```
- 当日跌停 10 只（total=10），参数结构同涨停池。

### 2.4 连板天梯 —— 强势股/连板天梯 ✅ 已验证
```
GET /dataapi/limit_up/continuous_limit_up?date=20260814&page=1&limit=50
```
- 返回 `data` 数组，每项：
```json
{"height":5, "number":1, "code_list":[{"code":"600xxx","name":"XX","market_id":"1","continue_num":5}]}
```
- `height` = 连板高度（当日最高 5 板），`number` = 该高度股票数，`code_list` = 具体个股。
- 无需 field 参数，是最简连板梯队数据源。

### 2.5 交易状态 —— 市场情绪 ✅ 已验证
```
GET /dataapi/limit_up/trade_status
```
- 返回 `{"stat":"未开盘","timestamp":...}`；`stat` 取值如 未开盘/交易中/已收盘，用于判断当前是否为交易日。

### 2.6 标签数据 —— 最强风口（涨停原因）⚠️ JS 中发现，建议实测
```
GET /dataapi/tagservice/fetch/v1/tag_data?date=20260814&code=600xxx&type=1
```
- JS 中引用的涨停原因/概念标签接口，具体参数待实测确认。

### 2.7 已确认 404 的旧端点（勿用）
`strong_pool`、`down_limit_pool`、`limit_up_reason`、`limit_up_days`、`limit_up_statistics`

---

## 3. mobileapi 接口（`https://data.10jqka.com.cn/mobileapi/hotspot_focus/`）

> **必须携带** `Source-id`、`PlatForm`、`Referer` 三个请求头（见第 0 节）。返回 `{"status_code":0,"data":{...},"status_msg":"success"}`。

### 3.1 市场情绪总览 —— 市场情绪 ✅ 已验证
```
GET /mobileapi/hotspot_focus/market_state/v1/overview?date=20260814
```
返回 `data` 字段：
- `turnover`: `{pre, now, flag}` — 两市成交额
- `north_flow`: 北向资金
- `limit_up`: `{pre, now, flag}` — 涨停家数
- `rise_fall`: `{rise:2400, fall:2970, deuce:170, limit_up:64, limit_down:10}` — 涨/跌/平/涨停/跌停家数
- `hgt_market_status`: 港股通状态
- `config_start_date`: 数据起始日（`2021-08-17`）

### 3.2 最强风口 / 风向标股 —— 最强风口 ✅ 已验证
```
GET /mobileapi/hotspot_focus/market_state/v1/get_wind_vane_stock?date=20260814
```
返回 `data.tab_list`（约 52KB）：
```json
{"tab_list":[{
  "tab_name":"高位股", "average_change":2.31, "stock_num":8,
  "stock_list":[{"stock_code":"300120","stock_name":"润泽科技","reason":"专用设备+...","price":"9.26","change":"19.9482","fiveRise":45.2,"tags":"..."}]
}]}
```
- 覆盖高位/低位等分类风口股，含**涨停原因（reason）**与 5 日涨幅（fiveRise）。

### 3.3 股票池标签信息 —— 全池配置 ✅ 已验证
```
GET /mobileapi/hotspot_focus/stock_pool/v1/get_tab_info?date=20260814
```
返回 `data.tabs`，是**所有股票池的官方配置表**（cate 取值从这里拿）：
- `limit_up` 涨停池：`limit_up_all`(62 全部)、`limit_up_one`(51 首板)、`limit_up_two`(5 二板)、`limit_up_three`(5 三板)、`limit_up_four`(0 四板)、`limit_up_high`(1 高位板)
- `new_high` 历史新高：`today`(34 今日突破)、`five_day`(136 五日突破)
- `trend` 趋势强势：`trend_all`(80)、`trend_three`(26 三日)、`trend_five`(4 五日)、`trend_high`(50 高位)
- `draw_down_limit_up` 回落涨停：`limit_up`(14)
- `draw_down_trend` 强势回调：`trend`(8)
- 每项含 `name`(中文名)、`key`(cate 值)、`chart_key`(图表键)、`extra.num/ratio`(数量/占比)

### 3.4 涨停池列表（连板分层） —— 强势股/连板天梯 ✅ 已验证
```
GET /mobileapi/hotspot_focus/stock_pool/v1/get_limit_up_stocks?date=20260814&cate=limit_up_all&sort_field=limit_up_time&sort_dir=desc&page=1&size=50
```
- `cate` 取值：`limit_up_all` / `limit_up_one` / `limit_up_two` / `limit_up_three` / `limit_up_four` / `limit_up_high`
- `sort_field` 合法值：`limit_up_time`（涨停时间）、`continue_day_cnt`（连板数）、`change` 等（传错返回 `sort field not exist`）
- 返回 `data.stock_list[]`，字段丰富：
  - `stock_code/stock_name/market_code/list_board`（代码/名称/市场/板块，list_board 如 `main`/`chinext`）
  - `price/change/amplitude`（现价/涨跌幅/振幅）
  - `continue_day/continue_day_cnt`（几板/连板数，如 首板=1）
  - `limit_up_time`（封板时间）、`limit_up_reason`（涨停原因）
  - `industry_block`（行业）、`main_buy_money/main_sell_money/main_net_amount`（主力买卖净额）
  - `effective_circulation/effective_turnover_ratio`（有效流通市值/换手率）、`volume/volume_money/max_volume_money`
  - `time_preview`（当日分时预览数组）、`is_st/is_new`

### 3.5 历史新高池 —— 强势股 ✅ 已验证
```
GET /mobileapi/hotspot_focus/stock_pool/v1/get_hundred_high_stocks?date=20260814&cate=today&sort_field=change&sort_dir=desc&page=1&size=50
```
- `cate`：`today`（今日突破 34 只）/ `five_day`（五日突破 136 只）
- `sort_field=change` 合法（`limit_up_time` 在此池不可用）。

### 3.6 趋势强势池 —— 强势股 ✅ 已验证
```
GET /mobileapi/hotspot_focus/stock_pool/v1/get_trend_stocks?date=20260814&cate=trend_all&sort_field=change&sort_dir=desc&page=1&size=50
```
- `cate`：`trend_all` / `trend_three` / `trend_five` / `trend_high`
- `sort_field=change` 合法。

### 3.7 回落涨停 / 强势回调池 —— 强势股 ✅ 已验证
```
GET /mobileapi/hotspot_focus/stock_pool/v1/get_drawdown_stocks?date=20260814&cate=limit_up&sort_field=change&sort_dir=desc&page=1&size=50
```
- `cate=limit_up` → 回落涨停（14 只）；`cate=trend` → 强势回调（8 只）
- 注意：JS 中 `get_big_side_stocks`（大单强势）会 404，前端实际重写为 `get_drawdown_stocks` 调用。

### 3.8 图表数据 —— 辅助 ✅ 已验证
```
GET /mobileapi/hotspot_focus/chart/v1/get_chart?chart_key=limit_up_continue_one_day&end_time=20260814&size=30
```
- `chart_key` 取值见 3.3 的 `chart_key` 字段（如 `limit_up_all`、`limit_up_continue_one_day`、`high_hundred_range_one`、`trend_all`、`draw_down_limit_up`、`draw_down_trend` 等）。
- 返回 `data.charts` 数组（连板晋级率曲线等）。

### 3.9 涨停对比 —— 涨停强度 ✅ 已验证
```
GET /mobileapi/hotspot_focus/limit_up_compare/v1/range_compare?date=20260814
GET /mobileapi/hotspot_focus/limit_up_compare/v1/two_days_compare?date=20260814&query_probability=1
```
- `range_compare` → `data.day_values`（30 天序列，区间涨停对比）
- `two_days_compare` → `data.board_list`（5 档板位，两日晋级对比）
- `limit_up_compare/v1/probability_detail` 存在但需更多参数（返回 `获取数据错误`）。

### 3.10 权限类（登录态）⚠️ 未实测
`permission/v1/query`、`permission/v1/start` — 页面提示登录查看更多信息时调用。

---

## 4. 推荐调用组合（四模块全覆盖）

```powershell
# 0) 建会话
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest -Uri "https://data.10jqka.com.cn/" -WebSession $s -UseBasicParsing -UserAgent "Mozilla/5.0"
$h = @{ "Source-id"="PROGRAM-limt-up-focus"; "PlatForm"="mobileweb"; "Referer"="https://data.10jqka.com.cn/mobile/limitup/v2/index.html" }
$d = "20260814"

# 1) 涨停强度：涨停池 + 炸板池 + 跌停池（dataapi，无需 h）
Invoke-RestMethod "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=50&field=199112,10,9001,330323,330324&filter=HS,GEM2STAR&order_field=330324&order_type=0" -WebSession $s -Headers @{"User-Agent"="Mozilla/5.0"}

# 2) 连板天梯
Invoke-RestMethod "https://data.10jqka.com.cn/dataapi/limit_up/continuous_limit_up?date=$d&page=1&limit=50" -WebSession $s -Headers @{"User-Agent"="Mozilla/5.0"}

# 3) 最强风口
Invoke-RestMethod "https://data.10jqka.com.cn/mobileapi/hotspot_focus/market_state/v1/get_wind_vane_stock?date=$d" -WebSession $s -Headers $h

# 4) 市场情绪
Invoke-RestMethod "https://data.10jqka.com.cn/mobileapi/hotspot_focus/market_state/v1/overview?date=$d" -WebSession $s -Headers $h
```

---

## 5. 验证状态汇总

| 接口 | 状态 | 备注 |
|---|---|---|
| dataapi/limit_up/limit_up_pool | ✅ 200 | 涨停 62 |
| dataapi/limit_up/open_limit_pool | ✅ 200 | 炸板 19 |
| dataapi/limit_up/lower_limit_pool | ✅ 200 | 跌停 10 |
| dataapi/limit_up/continuous_limit_up | ✅ 200 | 最高 5 板 |
| dataapi/limit_up/trade_status | ✅ 200 | 未开盘 |
| market_state/v1/overview | ✅ 200 | 涨跌家数齐全 |
| market_state/v1/get_wind_vane_stock | ✅ 200 | 4 组风口股 |
| stock_pool/v1/get_tab_info | ✅ 200 | 全池配置 |
| stock_pool/v1/get_limit_up_stocks | ✅ 200 | cate=limit_up_* |
| stock_pool/v1/get_hundred_high_stocks | ✅ 200 | cate=today/five_day |
| stock_pool/v1/get_trend_stocks | ✅ 200 | cate=trend_* |
| stock_pool/v1/get_drawdown_stocks | ✅ 200 | cate=limit_up/trend |
| chart/v1/get_chart | ✅ 200 | chart_key 驱动 |
| limit_up_compare/v1/range_compare | ✅ 200 | 30 天序列 |
| limit_up_compare/v1/two_days_compare | ✅ 200 | 5 档板位 |
| limit_up_compare/v1/probability_detail | ⚠️ 参数未明 | 需更多参数 |
| permission/v1/* | ⚠️ 未实测 | 登录态 |
| dataapi/tagservice/fetch/v1/tag_data | ⚠️ 未实测 | JS 中发现 |
| stock_pool/v1/get_limit_up_fail_stocks | ⚠️ cate 未明 | 炸板池可用 dataapi 替代 |