# 同花顺热榜 · 全类目接入计划

> 范围：FinFeed「同花顺热榜」组件（`web/src/components/ThsHotList.vue`）9 个类目（热股 / 板块 / ETF / 热门 / 可转债 / 港美 / 热基 / 期货 / 保险）的数据源接入。
> 目标：消除「XX 榜单接入中」占位，使每个类目具备真实数据（实时 + 历史快照）。
> 制定日期：2026-08-17

---

## 1. 现状（已确认）

- 前端 `ThsHotList.vue` 第 24–34 行定义 9 个类目导航，原 `load()` 函数在 `category !== 'stock'` 时直接 `return`，其余类目渲染 `AppEmpty` 占位（即用户所见「接入中」文案）。
- 后端 `finfeed/ui/web_fastapi/app.py:783` 的 `hotrank` 路由仅调用 `finfeed/market/ths_hotrank.fetch_hotrank()`；原 `ths_hotrank.py` 的 `SUB_LISTS` 仅含热股子榜单。
- 数据层 `ths_hotrank.py` + 落库 `store.py:ths_hotrank` 表 + 调度 `scheduler.py:hotrank` 均围绕「热股」构建。
- **结论（2026-08-17 已修复）：9 类目全部接入且均返回真实数据。**
  - 同花顺免鉴权源（8 类）：热股 / 板块 / ETF / 热门 / 可转债 / 港美-港股 / 热基 / 期货。
  - **东方财富替代源（2 类）**：港美-美股、保险 两类同花顺需登录方可查看，公开免鉴权通道不可达，已改由**东方财富实时行情**补齐（美股为全市场按成交额排序剔除权证/单位；保险为 A 股保险及保险系金控个股池），前端透明标注「数据来源：东方财富」。

---

## 2. 数据源总览（逆向自同花顺热榜前端 `ths_app_tmp.js`）

同花顺热榜 9 个类目由 TAB 键枚举定义（`HOT_LIST_TAB_KEYS`）：

| 类目 | TAB 键 | 官方接口路径 | 免鉴权 | 实测可达 |
|---|---|---|---|---|
| 热股 | `hot-stock` | `out/hot_list/v1/stock` | ✅ | ✅（已上线） |
| 板块 | `plate` | `out/hot_list/v1/plate` | ✅ | ✅ |
| 可转债 | `convert-bond` | `out/hot_list/v1/bond` | ✅ | ✅ |
| 期货 | `futures` | `out/hot_list/v1/future` | ✅ | ✅ |
| 热门 | `hot-topic` | `out/hot_list/v1/topic` | ✅ | ✅ |
| ETF | `etf` | `out/hot_list/v1/etf`（`data.list`） | ✅ | ✅（已上线） |
| 热基 | `fund` | 问财 iwencai `getdata/basic`（tag=同花顺热榜_热基，免登录） | ✅（问财） | ✅（已上线） |
| 港美 | `hk-us` | `stock?stock_type=hk`（港股 ✅）；`stock_type=us` 美股需登录，改由东方财富 `m:105,m:106` 补齐 | ✅(港股)/❌(美股) | ✅(港股) / ✅(美股·东方财富替代) |
| 保险 | `insurance` | amis/Kamis 第三方嵌入（`#insurance`, systemId 171, token），无公开 JSON；改由东方财富实时行情补齐 | ❌ | ✅(东方财富替代·A股保险及保险系金控) |

> 关键发现：前 5 个类目（热股/板块/可转债/期货/热门）同属 `dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/{cat}` 免鉴权家族，仅需 `Referer: eq.10jqka.com.cn` + 标准 UA 即可访问，返回 `status_code:0` 的结构化 JSON。**这 5 个可共用一套通用抓取器。**

---

## 3. 各免鉴权类目实测结果（Tier-1）

### 3.1 板块（plate）— 推荐首批接入
- 请求：`GET .../out/hot_list/v1/plate?type={concept|industry}`
- 子榜单：`concept`（概念）、`industry`（行业）实测 `status=0`；`region` 等返回 `-1`（不可用）。
- 返回键：`plate_list`，字段示例：
  `{"code":"886033","name":"共封装光学(CPO)","rate":"7469.0","rise_and_fall":2.9453,"order":1,"hot_rank_chg":0,"tag":"9家涨停","hot_tag":"连续271天上榜","etf_name":"创业板人工智能ETF","etf_product_id":"159242","etf_rise_and_fall":3.2701,"market_id":48}`
- 与热股字段高度同构（`rate / rise_and_fall / order / name`），额外含 ETF 联动字段。

### 3.2 可转债（bond）
- 请求：`GET .../out/hot_list/v1/bond?type={hour|day|all}`，实测均 `status=0`，返回 100 条。
- **注意：热度字段名为 `hot`（非 `rate`）**，需字段映射兼容。
- 字段示例：`{"market":"35","code":"123277","name":"玉禾转债","hot":1086.5,"rise_and_fall":57.3,"order":1}`

### 3.3 期货（future）
- 请求：`GET .../out/hot_list/v1/future?type={...}`（type 取值待细查，任意值均返回数据），返回键 `futures_list`。
- 字段示例：`{"market":66,"code":"jm2609","name":"焦煤2609","rate":"30664","rise_and_fall":1.6987,"stock_list":[{"name":"盘江股份","code":"600395","rise_and_fall":3.1873}]}`
- **含嵌套 `stock_list`**（关联个股），前端需决定是否展开。

### 3.4 热门（topic）
- 请求：`GET .../out/hot_list/v1/topic?type={hour|day|all}`，返回键 `topic_list` + `more_url`。
- 字段示例：`{"code":"T018w6t","attach_type":"att_sub_title","description":"DeepSeek发布API涨价公告…","ios_jump_url":"…"}`
- **语义为「话题/事件」而非证券**：无 `code/涨跌幅`，有 `description/跳转`。需独立的内容型渲染布局（排名 + 标题 + 热度 + 摘要）。

---

## 4. 可行性分级

| 分级 | 类目 | 数据源特征 | 复用度 | 接入成本 |
|---|---|---|---|---|
| **Tier-1** | 板块、板块/可转债/期货/热门 | `out/hot_list/v1/{cat}` 免鉴权，JSON 同构 | 高（通用抓取器 + 字段映射） | 低 |
| **Tier-2** | ETF、热基、港美 | 独立 API（POST / 结构化查询），需构造请求体、可能需鉴权 | 中（部分适配） | 中–高 |
| **Tier-3** | 保险 | 第三方 amis 嵌入，无公开热榜 JSON | 无 | 极高（**已用东方财富实时行情替代**，非外链） |

**备选数据源**：代码库已有 `EastMoneyHotRankParser`、`ThsHotRankParser`（见 `finfeed/core/parsers/`），东方财富亦提供行业/概念/ETF 热度榜。但因 UI 明确标注「数据来源：同花顺」，主路径以同花顺为准；东方财富可作为 Tier-2 类目的兜底或对账源。

---

## 5. 推荐架构

### 5.1 后端：泛化 `ths_hotrank.py` 为多类目模块
- 将 `SUB_LISTS` 升级为 `CATEGORIES` 配置，每项含：`path`（接口路径）、`types`（子榜单，如 concept/industry）、`list_key`（返回数组键）、`field_map`（源字段→标准字段）、`extra_fields`（类目特有字段）、`renderer`（证券型 / 内容型）。
- 通用 `fetch(category, type, period, limit, date)`：按 `category` 路由到对应源；免鉴权类目走统一 `_get_live` + `_normalize_item`（兼容 `rate`/`hot` 双字段名）。
- 复杂类目（ETF/热基/港美）在 `CATEGORIES` 中以 `mode: "structured"` 标识，调用各自请求构造器。

### 5.2 数据库：扩展 `ths_hotrank` 表
- 新增列 `category TEXT`（区分类目），主键变更为 `(trade_date, category, list_type, period, code)`。
- 新增 `extra_json TEXT`，存储类目特有字段（如板块的 `etf_name/etf_rise_and_fall/hot_tag`、期货的 `stock_list`、热门的 `description`）。
- 历史快照（`get_ths_hotrank` / `get_ths_hotrank_dates`）增加 `category` 过滤参数，支撑按类目回看。

### 5.3 API：扩展路由
- `app.py` 的 `hotrank` 路由增加 `category` 参数（默认 `stock`），转发至泛化 `fetch`。
- `hotrank_dates` 支持按 `category` 返回可用日期清单。

### 5.4 前端：去掉占位守卫，按类目渲染
- 移除 `load()` 中 `if (category !== 'stock') return`。
- 维护与后端对齐的 `CATEGORIES` + 子榜单配置（前端已有 `CATEGORIES`/`SUB_LISTS`）。
- 渲染分两类：
  - **证券型**（热股/板块/可转债/期货/ETF/热基/港美/保险）：沿用现有「排名 + 名称/代码 + 热度条 + 涨跌幅（红涨绿跌）」布局；港美-美股与保险由东方财富提供，隐藏热度列、改展「成交额 / 主力净流入」标签，并标注数据来源。
  - **内容型**（热门）：「排名 + 话题标题 + 热度 + 摘要 + 跳转」。

### 5.5 调度：扩展自动采集
- `collect_all` / `scheduler.py:hotrank` 遍历 `categories × types × periods`，落库为交易日快照。

---

## 6. 实施步骤（分阶段）

### Phase 1 — Tier-1 通用化（推荐先做「板块」）
1. 后端：在 `ths_hotrank.py` 增加 `CATEGORIES` 配置，接入 **板块**（`type=concept|industry`，字段映射 + `extra_json` 存 ETF 联动）。
2. 数据库：加 `category` 列 + 改主键 + 加 `extra_json`（带迁移兼容旧 `stock` 数据）。
3. API：`hotrank` 增加 `category` 参数。
4. 前端：`ThsHotList.vue` 接入「板块」tab，证券型渲染 + ETF 标签。
5. 验证：实时拉取 + 落库 + 历史回看 + 自动化采集。
6. 复制同套模式，依次接入 **可转债**（注意 `hot` 字段）、**期货**（含 `stock_list`）、**热门**（内容型布局）。

### Phase 2 — Tier-2 结构化类目
7. 逆向 `ths_app_tmp.js` 中 ETF / 热基 / 港美 的请求构造器，确定请求体与鉴权需求。
8. 实现 `mode: "structured"` 抓取分支；前端各自布局（ETF 指数/基金、热基基金排行、港美港股美股）。
9. 评估是否需要 App Token / Cookie 鉴权，必要时纳入配置。

### Phase 3 — Tier-3（保险）与收尾
10. 保险：确认无公开 JSON 后，决定「暂缓占位」或「外链跳转同花顺保险页」；不阻塞其他类目。
11. 全量联调、调度覆盖、README/设计文档更新。

---

## 7. 风险与边界

- **频率限制 / robots**：免鉴权接口仍受同花顺频率限制；维持现有 60s 内存 TTL 去抖，遵守 robots，仅限个人学习/技术研究、非商用分发（见 `ths_hotrank.py` 合规底线）。
- **字段差异**：bond 用 `hot`、plate 含 ETF 字段、topic 为内容型——通用映射需逐类目校准，已实测规避。
- **鉴权类目**：ETF/热基/港美 可能需 App Token；若无法免鉴权获取，降级为占位或东方财富兜底。
- **数据时效**：热榜约 5 分钟更新；实时接口不可达时沿用现有「历史快照 / 缓存兜底」机制（需按类目扩展）。
- **保险 / 美股**：同花顺需登录，无可行 JSON 通道；已采用**东方财富实时行情**作为替代源（透明标注来源），非占位、非外链。保险为 A 股保险及保险系金控个股池（12 只），美股为全市场按成交额排序剔除权证/单位（50 只）。

---

## 8. 优先级建议

1. **板块**（用户点名、Tier-1 最易、与热股同构）→ 立即启动。
2. 可转债 / 期货（Tier-1，证券型，成本低）。
3. 热门（Tier-1，但需内容型布局）。
4. ETF / 热基 / 港美（Tier-2，需逆向请求体）。
5. 保险（Tier-3，暂缓/外链）。

---

*附录：本计划的可行性结论均经实测验证（对 `out/hot_list/v1/{plate,bond,future,topic}` 发起真实请求，确认 `status_code:0` 与字段结构）。Tier-2/3 类目的最终可达性将在对应 Phase 实施时通过逆向 `ths_app_tmp.js` 请求构造器逐一确认。*
