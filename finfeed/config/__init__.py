"""配置地图 —— 全部配置表面的唯一索引（2026Q3 架构收口）。

FinFeed 的配置分两层：

  1. 全局配置 ``finfeed.config.settings`` —— 环境变量前缀 FINFEED_
     （DB_PATH / DATA_DIR / WEB_PORT / CORS_ORIGINS / LOG_* / 调度分级等）
  2. 领域配置（内聚在各业务包，修改后重启生效；环境变量名见各模块文档）
     * finfeed.capital_dashboard.config —— 资金流大屏（TDX_*/DASH_*/DETAIL_* 等）
     * finfeed.sector_minute.config     —— 板块分时（SECTOR_MIN_* 前缀）
     * finfeed.llm.config               —— LLM 模型接入
     * finfeed.screener.config          —— 选股器

  3. 信源目录（数据配置，非参数配置）：
     * finfeed.config.sources          —— 快讯+文章信源注册表（get_enabled_sources）
     * finfeed.config.flash_sources    —— 快讯源专属定义
     * finfeed.config.article_sources  —— 文章源专属定义

约定：
  * 新增全局参数 -> settings.py（必须走 _get_env，自动获得 FINFEED_ 前缀）
  * 新增领域参数 -> 对应领域的 config.py（自解释命名 + 注释 + 环境变量）
  * 禁止在业务代码里散落 os.environ.get（统一进上述配置模块）
  * 领域配置保留在领域内是**有意为之**：合并进全局 settings 会让领域包
    反向依赖全局配置树，边界更糟（评估报告 §9 的结论）
"""
