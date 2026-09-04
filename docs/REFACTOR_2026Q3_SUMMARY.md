# FinFeed 架构重构 2026Q3 —— 执行总结

> 分支 `refactor/architecture-2026q3`（自 main 切出），13 个提交，全程门禁绿灯。
> 依据：`docs/ARCHITECTURE_REVIEW.md`（评估报告）
> 日期：2026-09-04

## 执行结果总览

| # | 任务 | 状态 | 提交 |
|---|------|------|------|
| 1 | 安全网（分支+测试基线 134 全过） | ✅ | — |
| 2 | 阶段1-a CI 门禁（ruff/契约/pytest/前端构建+类型检查 双 job） | ✅ | df9dba4, 8380068 |
| 3 | 阶段1-b Import Linter 分层契约 | ✅ | （含于依赖倒置提交） |
| 4 | 阶段1-c 索引瘦身与孤儿表清理（已对生产库执行） | ✅ | b8ffcd1 |
| 5 | 阶段1-d 统一 SQLite 连接出口 | ✅ | 2cb418c |
| 6 | 阶段1-e CORS 收窄 + DEV proxy 修复 + DATA_DIR 外移 | ✅ | 8380068 |
| 7 | 阶段2-a 依赖倒置切断 storage 反向依赖 | ✅ | c37bdc6 前置提交 |
| 8 | 阶段2-b schema 版本化迁移框架（user_version，现 v3） | ✅ | a01561f + v3 |
| 9 | 阶段2-c 新闻链路 10 端点响应契约 + openapi-typescript | ✅ | d440aaf |
| 10 | 阶段2-d 前端 API 层 TS 化（6 模块 + tsconfig + typecheck 门禁） | ✅ | c37bdc6 |
| 11 | 阶段3-a 调度器收敛（甄别 12 处 while True，收编真轮询） | ✅ | c52e4b8 |
| 12 | 阶段3-b 巨石视图拆分 | ◐ 示范完成 | 最新提交 |
| 13 | 阶段3-c Repository 收敛裸 SQL | ◐ 实测修复完成 | 最新提交 |
| 14 | 阶段3-d 配置收口 + 临时脚本/日志清理 | ✅ | 8d59f73 |

## 关键成果数字

- **依赖环：15 → 0**。四处分层倒置修复后，Import Linter 契约 `cli > ui > application > domain > storage > shared` 全绿，白名单为零。每条依赖边受 CI 保护，新环无法静默进入。
- **news 表索引：22 → 10**（12 个冗余：3 组逐字重复、4 个前缀冗余、4 个零查询引用）；board_snapshots 330 万行从零索引到 (ts,code) 索引；margin_detail 7 万行个股档案查询从全表扫描到索引查找（EXPLAIN 验证）。
- **连接路径：5 → 1**。`storage/connect.py` 统一出口，修复 `llm/cleanup.py` CWD 敏感硬编码路径与 `capital_dashboard/persist.py` 相对路径错库隐患。
- **契约：0 → 10 端点强类型** + 123 路径全量 OpenAPI 类型文件 `web/src/api/schema.d.ts`，`npm run gen:api` 一键再生成。
- **ruff 基线：41 → 0**；测试 134 → 138（新增调度原语 4 个行为测试）。
- **磁盘：finfeed_web.log 37MB → 657KB 压缩归档**；根目录 4 个诊断脚本删除；迁移前自动备份约 1GB（`*.pre_migrate.bak`，已 gitignore）。

## 关键设计决策（带理由）

1. **依赖倒置而非删调用**：`storage/database.py` 对 `analysis.importance` 的依赖改为 `storage/ports.py` 的 `ImportanceScorer` Protocol 注入（`core/pipeline.py` 启动时接线）；对 `market.store` 的代理壳直接删除，调用方 `stock_monitor` 改同层直连。两个环的解法不同：前者是真实抽象需求，后者是历史兼容壳。
2. **CORS 默认关闭而非白名单**：生产同源托管 + 开发 vite proxy 转发，两个场景都不需要跨域；`FINFEED_CORS_ORIGINS` 留作显式逃生门。
3. **迁移框架用 PRAGMA user_version 而非 Alembic**：SQLite 单文件、无 ORM，user_version 零依赖且与库同生命周期。规则：只追加、必须幂等、已发布不修改。v1 冻结存量 47 处 CREATE TABLE 为基线，v2 登记索引瘦身，v3 margin_detail 索引。
4. **领域 config 不合并进全局 settings**：4 个领域 config 内聚且注释完备，合并会让领域包反向依赖全局配置树，边界更糟。以 `config/__init__.py` 配置地图收口约定。
5. **调度器只收编真全局轮询**：12 处 `while True` 甄别后仅 1 处是全局周期任务（content_backfill）；4 处 SSE/WS 连接生命周期轮询保留原位（收敛反而制造生命周期错配）；7 处批处理/排空/收包属正常控制流。甄别结论记录在 `finfeed/scheduling/__init__.py`。
6. **响应契约不动运行时**：10 个端点直接返回 JSONResponse，`response_model` 仅影响 OpenAPI 文档——零行为变化换来类型生成能力，这是低风险高收益的第一步。
7. **前端渐进 TS**：strict 关闭、未覆盖面标 `unknown`，先 API 层（6 模块全转）后 store/composable，遵循评估报告"不要全量 TS 化"的反面建议。

## 修复过程中发现并处理的缺陷

- `finfeed/sector_minute/` 缺 `__init__.py`：PEP 420 命名空间包能跑，但 `setuptools.packages.find` 不收录——**打包部署会整个丢失**。已补。
- `storage/database.py` 静态方法内误引用 `self`（F821，重构中间态引入，ruff 门禁当场捕获并修复）。
- DEV 模式 `runtime.js` 绝对 URL 直连 8866，使 vite proxy 针对 Windows IPv6/uvicorn 半关闭的全部防护失效。已改相对路径。
- `get_stock_profile` 实测并非 N+1（10 次单行查询单事务）；真问题是 margin_detail 索引最左列错位，已按迁移 v3 修复。

## 遗留事项（按优先级）

1. **任务 12 余量**：MarketView(1620)/SectorMinuteView(1415)/StockMonitorView(1389)/EasyTdxView(1299)/ThsLimitUp(1350) 按 ScreenerView 模式渐进拆分（composable 抽取 → 模板零改动的等价重构）。
2. **任务 13 余量**：671 处裸 SQL 的 Repository 收敛是长期工作；market/store.py(1803 行) 拆分前先补集成测试锁行为。
3. **llm.py 42 端点契约**：新闻链路模式已验证，可批量复制。
4. **运行中服务需重启**方可加载全部后端改动（当前 8866 端口服务仍为旧代码）；建议低峰期重启并跑一遍 `python -m finfeed.storage.schema_migrations` 确认版本。
5. **VACUUM 回收空间**：索引删除后 news_monitor.db 文件未缩（页复用），离线时执行 `python scripts/migrate_2026q3_01_index_slim.py --vacuum` 可回收约 300MB。
6. **CI 上线**：推送分支到 GitHub 后 Actions 自动生效；建议合入 main 前跑一个 PR 全量门禁。

## 验证状态（每次提交前全跑）

- `ruff check .`：All checks passed（基线 0 错误）
- `lint-imports`：Contracts 1 kept, 0 broken
- `pytest`：138 passed
- `npm run typecheck`：tsc 零错误
- `npm run build`：4-5s 通过
- 生产库在线迁移无中断，EXPLAIN QUERY PLAN 验证核心查询全部命中索引
