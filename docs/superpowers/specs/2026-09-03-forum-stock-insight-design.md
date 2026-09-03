# 个股舆情洞察视图 — 设计文档

日期：2026-09-03

## Context（背景）

舆情（forum）板块经上一轮重构已收敛为 8 个股市/社区权威源，并加大了"热门股吧"抓取深度（单轮 ~100 → 441 条）。但用户指出**问题不只是数据量**，而是"总觉得需要改进"。

经头脑风暴，用户明确了两点诉求：
1. **洞察而非罗列**：把散乱 UGC 帖子流，聚合为以"标的"为单元的洞察视图（每只被热议的股票一张舆情卡）。
2. **与个股/板块联动**：卡片标注所属板块，点击下钻该股舆情，并能一键发起该股 AI 深度分析。

核心目标：把舆情 Tab 从"帖子消息流列表"重构为"个股舆情洞察视图"。

## 现状与可复用能力（已核实）

- 舆情 Tab 当前本质是帖子消息流 + 顶部统计 + AI 面板，数据来自 `/api/stock-monitor/feed`（按 codes 聚合）
- 已有 `forum_sentiment.top_stocks`：按 `news(category=forum).stocks` 聚合出 `{code,name,heat,sentiment_score,mention_count}`（`finfeed/analysis/forum_sentiment.py`）
- 已有股票→板块映射：`sentiment_store.get_sectors_of_stock(code)`（`finfeed/storage/sentiment_store.py`）
- 已有按个股 AI 分析：`POST /api/stock-monitor/analyze/{code}`（`finfeed/stock_monitor/router.py`）
- 前端有现成无限滚动模式（长列表分批加载）

## 设计

### A. 后端：2 个新接口

**① `GET /api/stock-monitor/forum/stocks`** — 个股舆情卡聚合列表（限无滚动）
- 入参：`?sector=`（可选，板块过滤）、`?limit=`（默认120）、`?offset=`（0起）
- 响应每卡：
  ```json
  {
    "code": "601138", "name": "工业富联",
    "heat": 333.6, "index": 0.06, "label": "中性",
    "up": 12, "down": 8, "neutral": 22,
    "mention": 42, "latest_ts": "...", "represent": "代表帖标题/摘要",
    "sectors": ["半导体", "AI算力"]
  }
  ```
- 实现：复用 `forum_sentiment` 的个股聚合逻辑（按 `stocks` 加权），扩展到：情绪计数、最新帖时间、代表帖；板块经 `get_sectors_of_stock(code)` 补齐。按 `offset/limit` 分批返回（上升热度/提及排序）。

**② `GET /api/stock-monitor/forum/stock/{code}`** — 单股舆情明细
- 返回：`{code, name, sectors[], index, up/down/neutral, volume, posts[]}`
- `posts[]` 按时间倒序（分页同无限滚动），含 title/source/publish_time/sentiment 等，供侧滑栏时间线渲染。

### B. 前端（`web/src/views/StockMonitorView.vue` 舆情 Tab）
1. **主体改为"个股舆情卡"列表**（复用现有无限滚动：接近窗口底部自动加载下一页）
2. **卡片**：名称/代码 + 多空指数（多空/中性计数）+ 热度 + 板块 tag（多个）+ 代表帖摘录 + 最新帖时间
3. **侧滑详情栏**（右侧固定面板，点外部空白/关闭按钮收起）：
   - 该股舆情时间线（帖子列表）+ 情绪汇总
   - **"AI 分析该股"**按钮 → 复用 `POST /analyze/{code}`
4. **板块 tag 点击** → 过滤列表仅显示该板块个股舆情卡（触顶重置重新加载）

### C. 明确不做（本轮范围外）
- 话题/事件级聚类
- 情绪时间曲线（走势）
- 顶部板块筛选器（板块联动以 tag 点击 + 过滤实现）
- 行情/K 线联动

## 数据流
```
news(category=forum, stocks) ──聚合──▶ /forum/stocks 个股舆情卡列表(分页, 板块过滤)
                                        └─▶ get_sectors_of_stock 补板块tag
点击卡片 ──▶ /forum/stock/{code} 单股明细 ──▶ 侧滑栏(MV)时间线+情绪
侧滑栏"AI分析该股" ──▶ POST /analyze/{code}（复用）
```

## 验证
1. 后端启动：`GET /forum/stocks` 返回按热度排序的个股卡列表，翻页/板块过滤正确
2. `GET /forum/stock/{code}` 返回该股帖子时间线与情绪汇总
3. 前端：卡片渲染正常、无限滚动加载、点击卡片右侧弹侧滑栏、板块 tag 点击过滤生效、"AI 分析该股"成功调用并展示
4. 回归：`scripts/verify_ths_p0.py` 全绿，其余源不受影响