# FinFeed 信息源梳理与新闻流模块重构方案

> 生成时间：2026-08-15 ｜ 状态：**已实施并验证** ｜ 适用范围：全部 43 个启用数据源

---

## 一、信息源归纳总表

所有来源定义于 `finfeed/config/` 下三个模块。抓取方式统一为 **httpx GET/POST 请求 + 对应 Parser 解析**（`core/fetcher.py` → `core/parsers/factory.py`），更新频率由主循环间隔（默认 5s）与分级调度 `SOURCE_TIERS` 共同决定（tier=N 表示每 N 轮抓取一次）。

### 1.1 快讯类来源（7×24 实时滚动短消息）— 16 个

**分类依据**：接口形态为电报/直播流/推送快讯（`telegraph`、`live`、`flash`、`push`、`express`、`timestream` 等），产出短消息、无正文长文、频繁更新（多数 tier=1 每轮抓取）。

| 来源名称 | 接口/URL | 数据拉取方式 | 更新频率 |
|---|---|---|---|
| 财联社 | `https://www.cls.cn/api/cache?app=CailianpressWeb&name=telegraph&os=web&sv=8.7.9` | GET JSON（cls 解析） | 每轮（5s） |
| 同花顺 | `https://news.10jqka.com.cn/tapp/news/push/stock` | GET JSON（ths 解析） | 每轮（5s） |
| 东方财富 | `https://np-listapi.eastmoney.com/comm/web/getFastNewsList`（biz=web_724） | GET JSON（eastmoney 解析） | 每轮（5s） |
| 雅虎财经 | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY,AAPL,MSFT&region=US&lang=en-US` | GET RSS（rss 解析） | 每轮（5s） |
| 21经济网 | `https://api.21jingji.com/timestream/getListweb?page=1` | GET JSON（jingji21 解析） | 每 12 轮（60s） |
| 金十数据 | `https://www.jin10.com/flash_newest.js` | GET JS/JSON（jin10 解析） | 每轮（5s） |
| 格隆汇快讯 | `https://www.gelonghui.com/api/live-channels/all/lives/v4` | GET JSON（gelonghui_live 解析） | 每轮（5s） |
| 法布财经 | `https://api.fastbull.cn/fastbull-news-service/api/getNewsPageByTagIds` | GET JSON（fastbull 解析） | 每 6 轮（30s） |
| 企查查 | `https://www.qcc.com/api/home/getNewsFlash?...` | GET JSON（qcc 解析） | 每轮（5s） |
| 每经网 | `https://live.nbd.com.cn/` | GET HTML（nbd 解析） | 每轮（5s） |
| 第一财经 | `https://www.yicai.com/api/ajax/getbrieflist` | GET JSON（yicai 解析） | 每 6 轮（30s） |
| 中证快讯 | `https://www.cs.com.cn/sylm/jsbd/list.html` | GET HTML（zhongzheng 解析） | 每 6 轮（30s） |
| 上海证券报 | `https://www.cnstock.com/fastNews/10004` | GET HTML（cnstock 解析） | 每轮（5s） |
| 爱股票 | `https://apis.aigupiao.com/Express/express_list/` | GET JSON（aigupiao 解析） | 每轮（5s） |
| 新华财经 | `https://www.cnfin.com/news/index.html` | GET HTML（xinhuacaijing 解析） | 每轮（5s） |
| 金融界 | `https://gateway.jrj.com/jrj-news/news/queryNewsFlash` | POST JSON（jrj 解析） | 每轮（5s） |

### 1.2 文章类来源（长文/深度内容）— 13 个

**分类依据**：接口/页面形态为栏目图文、深度报道、公告、研报聚合（`roll`、`channel`、`article`、`announcement`、栏目列表页等），产出长文、更新频率低（多为 tier=6/12 轮抓取）。

| 来源名称 | 接口/URL | 数据拉取方式 | 更新频率 |
|---|---|---|---|
| 新浪财经 | `https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=15` | GET JSON（sina 解析） | 每轮（5s） |
| 同花顺原创 | `https://yuanchuang.10jqka.com.cn`（9 个栏目） | GET HTML（ths_yc 解析） | 每轮（5s） |
| 同花顺财经 | `https://news.10jqka.com.cn/today_list/`（9 个栏目） | GET HTML（ths_finance 解析） | 每轮（5s） |
| 华尔街见闻 | `https://api-one.wallstcn.com/apiv1/content/information-flow?channel=global-channel&accept=article&limit=30` | GET JSON（wallstreetcn 解析） | 每轮（5s） |
| 格隆汇文章 | `https://www.gelonghui.com/news/` | GET HTML（gelonghui_article 解析） | 每 6 轮（30s） |
| 巨潮公告 | `https://www.cninfo.com.cn/new/hisAnnouncement/query` | POST 表单（cninfo 解析） | 每轮（5s） |
| cnBeta | `https://rss.cnbeta.com.tw/` | GET RSS（rss 解析，verify_ssl=False） | 每轮（5s） |
| 凤凰财经 | `https://finance.ifeng.com/` | GET HTML（ifeng 解析） | 每轮（5s） |
| 界面新闻 | `https://www.jiemian.com/` | GET HTML（jiemian 解析） | 每轮（5s） |
| 澎湃新闻 | `https://www.thepaper.cn/` | GET HTML（thepaper 解析） | 每轮（5s） |
| 和讯网 | `https://stock.hexun.com/` | GET HTML（hexun 解析） | 每轮（5s） |
| 韭研公社 | `https://www.jiuyangongshe.com` | GET HTML（jiuyan 解析） | 每轮（5s） |
| 萝卜投研 | `https://robo.datayes.com/` | GET HTML（luobo 解析） | 每轮（5s） |

### 1.3 舆情论坛类来源（UGC）— 14 个（不属于本次拆分范围）

东财人气榜、热门股吧、东财股吧热帖、同花顺论股堂、微博财经热搜、新浪股吧、雪球、同花顺股吧、同花顺股吧热帖、同花顺热股榜、百度财经热搜、知乎财经热榜、淘股吧、集思录。独立承载于「舆情」模块（`category=forum`），本次不改动。

### 1.4 来源分类映射关系（分类标签 → 模块 → 页面）

| 分类标签 (category) | 模块 | 前端页面/路由 | 后端端点 | 来源数 |
|---|---|---|---|---|
| `flash` | 快讯 | 快讯 `/flash` | `/api/flash` | 16 |
| `article` | 财经 | 财经 `/articles` | `/api/articles` | 13 |
| `forum` | 舆情 | 舆情 `/sentiment` | `/api/sentiment` | 14 |

> 说明：`config/sources.py` 中历史 `FINANCE_NEWS_SOURCES`（29 个）已完整拆分为 `flash_sources.py`（16 个）+ `article_sources.py`（13 个），并集一致、零重叠，原列表保留作参考但不再参与抓取。

---

## 二、模块拆分：新闻流 → 快讯 + 财经

### 2.1 数据层（分类打标）

| 文件 | 改动 |
|---|---|
| `finfeed/config/sources.py` | 新增分类核心：`get_flash_sources()` / `get_article_sources()` / `get_flash_source_names()` / `get_article_source_names()` / `get_flash_display_names()` / `get_article_display_names()` / `get_source_category()`；`get_enabled_sources()` 改为「快讯 + 文章 + 舆情」三合一；`get_source_by_name()` 覆盖三类 |
| `finfeed/core/parsers/base.py` | `_make_news()` 分类由硬编码 `"finance"` 改为 `get_source_category(self.source.name)`（快讯源→flash、文章来源→article） |
| `finfeed/core/parsers/json_parsers/thsyc.py` | 同花顺原创条目 `category` 由栏目名改为固定 `"article"`（栏目名保留在 intro 的【栏目名】前缀） |
| `finfeed/core/parsers/json_parsers/thsfinance.py` | 同花顺财经条目同上改为固定 `"article"` |
| `finfeed/core/pipeline.py` | 分类兜底由 `"finance"` 改为按来源展示名归属（flash/article/forum） |
| `finfeed/core/monitor.py` | `_process_fetched()` 由「forum/非forum」二分改为「flash/article/forum」三分桶处理 |

### 2.2 API 层

| 文件 | 改动 |
|---|---|
| `finfeed/ui/web_fastapi/app.py` | **移除 `/api/news`**，新增 `/api/flash`、`/api/articles`（共用 `_api_category_news()`，按 `category` 精确取数，来源筛选按对应展示名集合校验） |
| `finfeed/ui/web/server.py`（legacy 兼容层） | 路由注册表移除 `/api/news`，新增 `/api/flash`、`/api/articles`（`_serve_flash`/`_serve_articles` → 共用 `_serve_category_news()`）；`_get_cached_sources()` 内部初始化 flash/article 展示名缓存并新增 `_get_flash_article_display_names()`（5 元组签名保持不变，兼容 FastAPI 调用方） |
| `BROADCAST_CATEGORIES` | `("finance","forum")` → **`("flash","article","forum")`**，SSE 增量推送按三条独立水位线分类隔离 |

### 2.3 前端

| 文件 | 改动 |
|---|---|
| `web/src/router/index.js` | 删除 `/news`（NewsView），新增 `/flash`（快讯）、`/articles`（财经）；`/` 重定向 `/flash` |
| `web/src/components/Sidebar.vue` | 导航「新闻流」→「快讯」(zap) +「财经」(newspaper) |
| `web/src/api/client.js` | `api.news()` → `api.flash()` / `api.articles()` |
| `web/src/store/app.js` | `pendingTruncated` 由 `{finance, forum}` → `{flash, article, forum}` |
| `web/src/views/FlashView.vue` | **承接原新闻流页全部功能**：SSE 增量实时合并、顶部自动已读、关键词结果提示、收藏筛选；数据源切换为 `api.flash` |
| `web/src/components/NewNewsBadge.vue` | 未读角标统计口径 `finance` → `flash` |
| `web/src/App.vue` | 角标显示条件 `name === 'news'` → `name === 'flash'` |
| `web/src/views/DashboardView.vue` | 3 处 `to="/news"` → `to="/flash"` |
| `web/src/views/FavoritesView.vue` | 空态文案与跳转更新为「快讯」 |
| **删除** `web/src/views/NewsView.vue`、`web/src/components/NewsRow.vue` | 「新闻流」模块彻底移除 |

### 2.4 历史数据迁移（已执行）

`scripts/migrate_news_categories.py`（可重复执行，`--dry-run` 预演；执行前自动备份 `news_monitor.db.bak`）：

| 迁移规则 | 影响行数 |
|---|---|
| `finance` + 快讯来源 → `flash` | 36,039 |
| `finance` + 文章来源（含交集「格隆汇」）→ `article` | 32,824 |
| 栏目名分类历史记录（同花顺栏目，来源为同花顺/同花顺财经/同花顺原创）→ `article` | 24,607 + 1,516 |
| 残留 `finance` 兜底 → `article` | 18 |

迁移后分布：`flash` 36,039 ｜ `article` 58,965 ｜ `forum` 81,896。

> **已知权衡**：「格隆汇快讯」与「格隆汇文章」在数据层共享展示名「格隆汇」（`SOURCE_DISPLAY_NAMES`），历史数据无法细分，统一归入 `article`；新抓取数据已由解析器按内部名正确打标，不受影响。

---

## 三、来源标签同步

「标签」在项目中的落点为三层：**分类标签（category）**、**调度分级（SOURCE_TIERS）**、**展示名（SOURCE_DISPLAY_NAMES）**。本次同步的核心是分类标签，映射关系如下：

| 来源（内部名） | 展示名 | 原分类标签 | 新分类标签 | 归属模块 |
|---|---|---|---|---|
| 财联社 | 财联社 | finance | **flash** | 快讯 |
| 同花顺 | 同花顺 | finance | **flash** | 快讯 |
| 东方财富 | 东方财富 | finance | **flash** | 快讯 |
| 雅虎财经 | 雅虎财经 | finance | **flash** | 快讯 |
| 21经济网 | 21经济网 | finance | **flash** | 快讯 |
| 金十数据 | 金十数据 | finance | **flash** | 快讯 |
| 格隆汇快讯 | 格隆汇 | finance | **flash** | 快讯 |
| 法布财经 | 法布财经 | finance | **flash** | 快讯 |
| 企查查 | 企查查 | finance | **flash** | 快讯 |
| 每经网 | 每经网 | finance | **flash** | 快讯 |
| 第一财经 | 第一财经 | finance | **flash** | 快讯 |
| 中证快讯 | 中证快讯 | finance | **flash** | 快讯 |
| 上海证券报 | 上海证券报 | finance | **flash** | 快讯 |
| 爱股票 | 爱股票 | finance | **flash** | 快讯 |
| 新华财经 | 新华财经 | finance | **flash** | 快讯 |
| 金融界 | 金融界 | finance | **flash** | 快讯 |
| 新浪财经 | 新浪财经 | finance | **article** | 财经 |
| 同花顺原创 | 同花顺原创 | 栏目名 | **article** | 财经 |
| 同花顺财经 | 同花顺财经 | 栏目名 | **article** | 财经 |
| 华尔街见闻 | 华尔街见闻 | finance | **article** | 财经 |
| 格隆汇文章 | 格隆汇 | finance | **article** | 财经 |
| 巨潮公告 | 巨潮公告 | finance | **article** | 财经 |
| cnBeta | cnBeta | finance | **article** | 财经 |
| 凤凰财经 | 凤凰财经 | finance | **article** | 财经 |
| 界面新闻 | 界面新闻 | finance | **article** | 财经 |
| 澎湃新闻 | 澎湃新闻 | finance | **article** | 财经 |
| 和讯网 | 和讯网 | finance | **article** | 财经 |
| 韭研公社 | 韭研公社 | finance | **article** | 财经 |
| 萝卜投研 | 萝卜投研 | finance | **article** | 财经 |

舆情论坛 14 个来源分类标签保持 `forum` 不变（展示于「舆情」页）。

---

## 四、TUI 终端改造：仅显示快讯

### 4.1 过滤逻辑实现位置

| 文件 | 改动 |
|---|---|
| `finfeed/ui/terminal.py` | `_filter_forum_content()`（过滤舆情）→ **`_filter_flash_only()`**（仅保留快讯）。条目过滤依据 `NewsItem.category == 'flash'`（与 DB 查询口径一致，避免「格隆汇」共享展示名误保留文章）；统计过滤依据来源展示名 ∈ 快讯展示名集合。调用点：`build_display()` 与 `print_once_result()` |
| `finfeed/cli.py` | TUI 数据源 `db_get_recent_news(limit=200, category="finance")` → **`category="flash"`**（双保险：DB 查询精确取快讯 + 渲染侧再次过滤） |

### 4.2 效果

终端实时监控界面（`python main.py`）仅展示 16 个快讯源内容；文章类（新浪财经/华尔街见闻/巨潮公告等）与舆情论坛类（雪球/淘股吧等）不再进入终端。文章类内容仍可在 Web「财经」页查看。

---

## 五、影响点与上线清单

1. **必须重启运行中的旧实例**（当前检测到 3 个旧代码进程，会持续按旧分类写入新数据，导致快讯/财经页漏数据）：
   - `python main.py --web-only`（PID 12804，12:58 启动）
   - `python -m uvicorn ... --port 8866`（PID 23424，FastAPI 子进程）
   - `python main.py` 完整监控（PID 30584，14:05 启动，**每 5s 写入旧分类**）
   - 重启方式：停止上述进程后重新执行 `python main.py`（FastAPI 单轨 8866）。
2. **SSE 水位线**：`BROADCAST_CATEGORIES` 变更后，Web 启动时 `init_broadcast_watermark()` 会按新分类重建水位线（对齐当前库内最大 id），不会重复推送历史数据，无迁移风险。
3. **前端构建产物**：`web/dist` 已重新构建（vite build 成功），FastAPI 静态托管自动生效。
4. **旧端点兼容**：`/api/news` 已移除（前端无调用方）；如外部脚本仍依赖，需改用 `/api/flash` 或 `/api/articles`。`legacy server.py` 中 `/api/news` 路由亦已移除。
5. **导出功能**：不受影响（导出按时间/收藏过滤，不依赖分类）。
6. **数据库备份**：迁移前自动备份位于 `finfeed/news_monitor.db.bak`；如需回滚可恢复该文件并重启服务。

---

## 六、验证结果

| 验证项 | 结果 |
|---|---|
| 后端 13 个改动文件 `py_compile` | ✅ 全部通过 |
| 来源分类单元验证（财联社→flash / 新浪财经→article / 雪球→forum） | ✅ |
| `get_enabled_sources()` 数量（16+13+14=43） | ✅ |
| FastAPI 路由：`/api/flash`、`/api/articles` 就绪，`/api/news` 移除 | ✅ |
| TestClient 实测：flash 端点 36,039 条全为 `flash` 分类；articles 端点 58,965 条全为 `article` 分类，来源互不串流 | ✅ |
| TUI 过滤：仅保留 `category='flash'`（含格隆汇快讯），文章/舆情全过滤 | ✅ |
| 单次抓取冒烟（`python main.py --once`）：新增入库 2 条，新代码打标 `article` 正确 | ✅ |
| 前端 `npm run build`：709 modules，10.43s 构建成功 | ✅ |
