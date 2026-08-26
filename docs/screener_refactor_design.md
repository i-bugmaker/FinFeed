# 智能选股模块重构设计文档（FinFeed）

> 版本：v1.0　|　日期：2026-08-26　|　范围：`finfeed/screener/` 后端算法 + `web/src/views/ScreenerView.vue` 前端
> 定位：以**选股方法（算法/策略）重构为核心**，配套前端布局与交互流程优化。
> 声明：本文档为策略与工程设计方案，所有回测口径、因子与权重均为**样本外验证前假设**，不构成投资建议。

---

## 0. 摘要（TL;DR）

现有选股为"六维经验加权打分"（资本20%/动量25%/估值18%/量价15%/质量12%/情绪10%），权重为人工校准、预测力未经严格验证；前端仅开放"前N/技术面开关/板块开关"三项，用户无法定义选股规则。

本次重构的**核心变更**是将选股引擎从"固定权重线性打分"升级为**「IC 半衰期加权线性层 + 因子正交化 + LightGBM 分类 ML 层」的混合打分框架**，并以"滚动窗口 RankIC / ICIR"作为因子权重的客观依据，取代人工拍脑袋权重。配套：

1. **算法**：八维因子体系（在六维基础上显式补入成长 Growth、反转 Reversal）、统一的标准化流程（Winsorize → 行业/市值中性化 → 截面 z-score）、三阶段流水线（股票池 → 打分 → 组合），引入 walk-forward 评估杜绝未来函数。
2. **I/O**：将配置开放为结构化 `ScreenerRequest`（股票池/策略/输出三大块），输出 `ScreenerResult` 含维度分、ML 概率、因子暴露、可解释 rationale 与诊断指标（IC/ICIR/行业暴露）。
3. **UI/UX**：从"3 项开关 + 单表"升级为"左侧配置面板 + 实时预览 + 图表可视化 + 可排序筛选结果表 + 下钻解读 + 导出/模板/对比"的完整选股工作台。

**预期效果**：复合因子 RankIC ≥ 0.09、ICIR ≥ 2.5（正交后稳定性提升）；ML 混合模式多头端 RankIC 进一步抬升（行业实证中证1000 IC 达 15%+）；用户可配置项由 3 项增至 20+ 项，选股体验从"看结果"转为"定义并解释选股"。

---

## 1. 现状诊断

### 1.1 现状架构速览

| 层 | 位置 | 现状 |
|---|---|---|
| 算法 | `finfeed/screener/scoring.py`、`factors.py`、`config.py`、`vector.py` | 六维加权打分，权重写死在 `config.py` |
| 数据 | `datasource.py` | easy-tdx 直连主源 → 东方财富回退；K 线富化 SQLite 缓存 |
| 评估 | `backtest.py` | 有 IC/分层/权重敏感性，但 K线重建路径下资本/估值因子按缺失给中性分，IC 实际只反映动量/质量 |
| 前端 | `web/src/views/ScreenerView.vue`（~1030 行） | 仅 top N / 技术面 / 板块开关；单一大表，无图表、无排序筛选 |
| 接口 | `integrations/screener/router.py` | `RunRequest{top, technical, top_tech, boards}` |

### 1.2 三大短板（量化）

- **S1 策略科学性不足**：权重为经验校准（代码注释自陈"资金面权重从 0.30 下调至 0.20"因数据可信度存疑），**缺乏基于历史 IC 的客观赋权**；回测存在盲区，六维预测力被高估；无 walk-forward / 行业市值中性化未完整落地。
- **S2 可扩展性差**：`factor_registry.py` 仅声明元数据、**不参与执行**，新增因子需同时改 `factors.py`+`vector.py`+`config`，易漂移；数据源强绑定单连接 + 全局锁，`service.MAX_CONCURRENT=1`，无 UI 调参入口。
- **S3 用户体验弱**：用户只能"看结果"不能"定义选股"；无自定义过滤/权重/行业；结果无图表、无排序筛选、无导出、无"为什么入选"交互下钻。

---

## 2. 设计目标与原则

1. **客观赋权**：因子权重由滚动 RankIC / ICIR 驱动，而非人工设定（原则源自 Grinold & Kahn《Active Portfolio Management》及海通证券 IC 加权实证）。
2. **无未来函数**：所有因子仅用 t−1 及之前数据；前瞻收益用 t+1…t+h；评估必须 walk-forward。
3. **稳健优先**：截面标准化用 rank→[-1,1]（Gu-Kelly-Xiu 2020）替代脆弱的 sigmoid/bell 绝对映射；缺失用截面中位数填充，绝不以 0 冒充真实零（保留现有三态语义）。
4. **可解释**：每只股票输出维度分、因子 z 暴露、贡献最大的正负因子与文字 rationale。
5. **渐进可用**：实时线性模式（无需训练，永远可用）为默认；ML 模式在数据积累 ≥ 阈值后自动启用，不足时降级并提示。
6. **A 股适配**：强制剔除 ST/停牌/次新；处理涨跌停流动性；区分主板/科创板/创业板/北交所；红涨绿跌配色。

---

## 3. 新选股策略与算法逻辑（核心）

### 3.1 总体架构：三阶段流水线

```
┌──────────────────────────────────────────────────────────────────────┐
│ 阶段一  股票池构建 (Universe)                                           │
│   硬性过滤: 板块 / ST / 停牌 / 次新(<60交易日) / 流动性下限 / 涨跌停      │
│   → 候选集 U_t                                                          │
└──────────────────────────────────────────────────────────────────────┘
                │  对 U_t 每只股票 i
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 阶段二  因子处理 + 打分 (Score)                                         │
│   ① 因子计算: 八维因子集 F = {capital,momentum,valuation,              │
│        liquidity,quality,sentiment,growth,reversal}                    │
│   ② 标准化: Winsorize(p1,p99) → 行业+市值中性化(OLS残差) → 截面z/rank   │
│   ③ 线性层: IC半衰期加权 + 维度ICIR加权 → Score_linear_i                │
│        (可选) 正交化去冗余                                              │
│   ④ ML层:   LightGBM 分类(top/bottom 30%标签) → P_i(top)  [Mode B/混合] │
│   ⑤ 混合:   Score_i = α·Score_linear_i + (1−α)·ML_prob_i               │
│   ⑥ 评级+护栏: tier ∈ {strong,watch,observe,none} + guardrail_failures │
└──────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 阶段三  组合构建 + 评估 (Portfolio / Diagnostics)                       │
│   组合: 等权 / 风险优化(行业上限, 单票上限)  [可选]                      │
│   诊断: RankIC, ICIR, 分层收益, 多头超额, 信息比, 换手, 行业暴露         │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 阶段一：股票池构建（硬性过滤）

保留并强化现有 `is_eligible` 逻辑，过滤条件结构化、可配置：

| 过滤项 | 规则 | 可配置 |
|---|---|---|
| 板块白名单 | main / kcb / cyb / bj | ✅ |
| ST / *ST / 退市 | 名称或标记命中即剔除 | ✅ |
| 停牌 | 当日无成交剔除 | ✅ |
| 次新 | 上市 < `exclude_new_days`（默认 60 交易日）剔除 | ✅ |
| 流动性下限 | 日成交额 < `min_amount` 或换手率 < `min_turnover` 剔除 | ✅ |
| 价格 / PE / 流通市值 | 区间过滤 | ✅ |
| 行业 / 概念 | 白名单（空=全部） | ✅ |
| 涨跌停临近 | `|chg| ≥ 涨跌停幅度×0.95` 进入观察而非强选 | ✅ |

### 3.3 因子体系（八维）

在现有六维基础上**显式补入 Growth（成长）与 Reversal（反转）**——二者在 A 股实证中分别由基本面与短期反转效应贡献显著 alpha，原六维未单列。

| 维度 | 代表因子（示例） | 来源 |
|---|---|---|
| 质量 Quality | ROE、毛利率、盈利稳定性(EPS变异)、资产负债率 | 基本面/快照 |
| 价值 Valuation | PE_TTM、PB、PCF、股息率（钟形/分位） | 快照 |
| 成长 Growth | 营收/利润同比、预期增速、加速度 | 快照/公告 |
| 动量 Momentum | 20/60 日动量、多周期有序、动量加速度（含过热衰减） | 快照/K线 |
| 反转 Reversal | 5/10 日反转、换手率异常、短期超买超卖 | 快照/K线 |
| 量价 Liquidity | 成交额(log)、换手率（去规模）、振幅 | 快照 |
| 资金 Capital | 主力净比、5 日主力净流入/流通市值、北向（如有） | 快照/资金流 |
| 情绪 Sentiment | 年内涨停天数、连涨、DDX 大单、量速 | 快照 |

> 每个维度由 1–N 个底层因子构成；维度分 = 维度内因子（IC 加权或等权）合成。

### 3.4 因子处理标准化（统一、稳健）

对每只股票 i、截面 t、因子 f：

1. **Winsorize**：`x' = clip(x, p1, p99)`（截面内，或行业内）。
2. **中性化**（关键，解决规模/行业偏离）：对申万2021二级行业哑变量 + `log(流通市值)` 做横截面 OLS，取残差：
   `r_i = x_i − (β_ind·Industry_i + β_size·logMcap_i)`
3. **截面标准化**（Gu-Kelly-Xiu 做法，抗异常值最优）：
   `z_i = 2·(rank(x_i)/n − 0.5)` → 映射到 [−1, 1]；或 `z = (r_i − μ)/σ`。
4. **缺失处理**：截面中位数填充；若整列缺失则置中性 0（保留"未知≠0"语义，下游如实标注 coverage）。

> 取代现状 `sigmoid`/`bell` 绝对阈值映射：后者对量纲与分布敏感、跨市场不稳定；rank 标准化更稳健且可直接横向比较。

### 3.5 因子组合（核心创新）

#### 3.5.1 线性层 —— IC 半衰期加权 + 维度 ICIR 加权

- 每个底层因子 f，在滚动窗口 T（默认 120 交易日）计算 **RankIC**（与前瞻 h 日收益的 Spearman 相关）。
- **半衰期权重**（近期 IC 影响更大，源自半衰期 IC 加权实证）：
  `w_f = Σ_{k=0}^{T−1} 0.5^{k/h} · IC_{t−k,f}  /  Σ_{k=0}^{T−1} 0.5^{k/h}`
  其中 h = 半衰期（默认 60 交易日）。
- **维度分**：`dim_score_i = Σ_f ŵ_f · z_{i,f}`（维度内因子先归一化权重）。
- **维度权重**（ICIR 加权，稳定性优先）：
  `w_dim = ICIR_dim / Σ_d ICIR_d`，`ICIR_dim = mean(IC_dim)/std(IC_dim)`。
- **线性总分**：`Score_linear_i = Σ_dim w_dim · dim_score_i`（缩放到 0–100）。

#### 3.5.2 正交化（可选，提升 ICIR）

对维度分做回归正交（施密特），剔除维度间冗余信息后再加权。实证（海通）：正交后复合因子 ICIR 由 2.29 升至 3.30，信息比提升。默认关闭，可在配置开启。

#### 3.5.3 ML 层 —— LightGBM 分类（Mode B / 混合）

- **标签**：前瞻 h 日收益分位；前 30% → +1，后 30% → −1，中间 → 0（中金实证：分类 > 回归，过拟合更低、胜率更高）。
- **特征**：八维 z-score + 底层因子；**标签先做行业/市值中性化再喂入**（信达实证：中性化标签显著提升样本外）。
- **训练**：walk-forward 滚动——每次用过去 ~250 交易日训练，验证集取末 20%，预测未来；用 Optuna 调参（东方证券 DFQ-XGB 实证：调参后 RankIC +1pct、多头超额 +4pct）。
- **输出**：`P_i(top)`（前 30% 概率），缩放到 0–100。

#### 3.5.4 混合（Blend）

`Score_i = α · Score_linear_i + (1−α) · ML_prob_i`，`α` 默认 0.5，可由最近窗口 ICIR 自适应（如 `α = ICIR_linear/(ICIR_linear+ICIR_ml)`）。ML 数据不足时 `α=1`（退化为纯线性）。

### 3.6 评分、评级与护栏

- **评级**：按总分分位 + 护栏阈值（保留 strong/watch/observe/none，阈值可配置）。
- **护栏** `guardrail_failures`：资金面下限、接近涨跌停、流动性不足、质量/波动欠佳——任一触发则降级或移出 strong。
- **可解释 rationale**（自动生成）：列出贡献最大的 2–3 个正向与负向因子（基于 `z·权重`），例："动量(+18) 与 质量(+12) 主导；估值偏高(−6) 拖累"。

### 3.7 阶段三：组合构建（可选）

对 top-N 入选股做组合层约束：等权，或风险优化（单票上限 `max_weight`、行业上限 `industry_cap`、中性化偏离控制）。输出权重向量供导出。

### 3.8 评估框架（walk-forward，杜绝未来函数）

| 指标 | 口径 |
|---|---|
| RankIC / IC | 截面 Spearman（因子 vs 前瞻收益），滚动 |
| ICIR | `mean(IC)/std(IC)`，衡量稳定性 |
| 分层收益 | 十分位组合多头−空头年化 |
| 多头超额 | top 组合 vs 中证500/全A 基准 |
| 信息比 IR | 超额收益均值 / 标准差 |
| 换手率 | 相邻调仓期持仓变动 |
| 衰减 | RankIC 随持有期 h 下降曲线 |

> 修复现状回测盲区：利用 `snapshot_store` 真实积累的快照（含资本/估值因子）做样本内/外分离，而非 K 线重建导致的因子缺失。

---

## 4. 输入输出规范（I/O Contract）

### 4.1 输入 `ScreenerRequest`

```json
{
  "universe": {
    "boards": ["main", "kcb", "cyb", "bj"],
    "exclude_st": true,
    "exclude_suspended": true,
    "exclude_new_days": 60,
    "min_amount": 100000000,
    "min_turnover": 0.005,
    "price_range": [null, null],
    "pe_ttm_range": [null, null],
    "float_cap_range": [null, null],
    "industries": [],
    "concepts": []
  },
  "strategy": {
    "mode": "linear | ml | blend",
    "auto_weight": true,
    "dim_weights": {
      "capital": null, "momentum": null, "valuation": null,
      "liquidity": null, "quality": null, "sentiment": null,
      "growth": null, "reversal": null
    },
    "orthogonalize": false,
    "ml": { "horizon": 20, "top_quantile": 0.3, "min_history_days": 120 },
    "blend_alpha": 0.5
  },
  "output": {
    "top": 50,
    "tiers": { "strong": 85, "watch": 70, "observe": 55 },
    "with_technical": true,
    "with_factor_exposure": true,
    "portfolio": { "enabled": false, "method": "equal", "max_weight": 0.05, "industry_cap": 0.3 }
  }
}
```

- `dim_weights` 全部为 `null` 且 `auto_weight=true` → 使用 IC 半衰期加权；任一非 null → 以该权重覆盖对应维度（人工干预）。
- `mode=ml` 但历史不足 → 自动降级 `linear` 并在 `diagnostics` 标注。

### 4.2 输出 `ScreenerResult`

```json
{
  "meta": {
    "generated_at": "ISO8601", "data_source": "easy_tdx|eastmoney",
    "snapshot_time": "ISO8601", "as_of_kind": "realtime|trade_date|local",
    "fallback_chain": [...], "mode": "linear|ml|blend",
    "model_status": "trained|insufficient_history|degraded",
    "coverage": 0.96
  },
  "summary": {
    "universe_size": 5200, "screened_size": 3100, "scored_size": 3100,
    "avg_total_score": 52.3,
    "tier_counts": { "strong": 60, "watch": 180, "observe": 400, "none": 2860 }
  },
  "scores": [
    {
      "code": "600000.SH", "name": "浦发银行", "board": "main",
      "industry": "银行", "price": 10.2, "chg_pct": 1.3, "pe_ttm": 4.8,
      "dim_scores": { "capital": 60, "momentum": 72, "valuation": 81,
                      "liquidity": 55, "quality": 68, "sentiment": 50,
                      "growth": 45, "reversal": 58 },
      "total_score": 78.4, "tier": "strong",
      "ml_prob": 0.71,
      "factor_exposure": { "z_roe": 0.8, "z_mom20": 1.2, "...": 0.0 },
      "rationale": "估值(+81)与动量(+72)主导；成长偏弱(−45)拖累",
      "highlights": ["低估值", "动量上行"], "guardrail_failures": [],
      "technical": { "realized_vol_ann": 0.22, "ma_align": "多头", "drawdown_from_high": 0.06 }
    }
  ],
  "diagnostics": {
    "ic_by_dim": { "momentum": 0.06, "valuation": 0.05, "...": 0.0 },
    "icir_by_dim": { "momentum": 2.8, "...": 0.0 },
    "score_distribution": [0.1, 0.05, "..."],
    "industry_exposure": { "银行": 0.12, "...": 0.0 }
  }
}
```

### 4.3 错误码与降级链

| code | 含义 | 处理 |
|---|---|---|
| `SOURCE_UNAVAILABLE` | 主源+回退均失败 | 返回缓存/最近快照，标注 |
| `TIMEOUT` | 拉取超时 | 退化为上一成功快照 |
| `INSUFFICIENT_HISTORY` | ML 历史不足 | 降级 linear，提示 |
| `PARTIAL_COVERAGE` | 部分因子缺失 | 标注 coverage，缺失维度按中性 |

---

## 5. 约束条件（Constraints）

1. **数据时效**：easy-tdx 全市场约 1.2 万只，单次拉取 + 技术面富化有延迟；需缓存 + 分批，结果异步（后台任务，可取消）。
2. **连接并发**：数据源为单连接 + 全局锁，`MAX_CONCURRENT=1`；**ML 训练移至离线定时任务**，不阻塞实时选股。
3. **最小历史**：ML 模式需 ≥ `min_history_days`（默认 120 交易日）真实快照；不足自动降级。
4. **无未来函数**：因子仅用 t−1 前数据；前瞻收益 t+1…t+h；评估严格样本内/外分离。
5. **中性化依赖**：行业字段依赖申万2021二级，缺失时回退板块分类。
6. **计算资源**：LightGBM 训练后台限并发；实时线性模式为常数级向量化计算（复用现有 `vector.py` 路径）。
7. **合规**：输出须标注"策略基于历史统计，存在失效风险，非投资建议"。

---

## 6. 预期效果（KPI / 目标）

| 维度 | 当前 | 重构目标（基于行业实证设定，需样本外验证） |
|---|---|---|
| 复合因子 RankIC | 未严格验证（六维盲区） | ≥ 0.09（海通 0.087–0.10） |
| 复合因子 ICIR | — | ≥ 2.5（正交后提升稳定性） |
| 分层多头−空头年化超额 | — | 参考中证500指增 11.68% / 中证1000 指增 24%+ |
| 信息比 IR | — | ≥ 2.0（中证500 2.28 / 中证1000 3.04 实证） |
| ML 混合多头端 RankIC | — | 中证1000 实证可达 15.42%（信达） |
| 用户可配置项 | 3 项 | 20+ 项（股票池/权重/行业/组合） |
| 结果呈现 | 单表 | 图表+可排序筛选+下钻+导出+模板+对比 |
| 可解释性 | 静态 rationale | 维度分 + 因子 z 暴露 + 正负贡献自动生成 |

> 注：上述行业数字来自海通证券、中金公司、东方证券、信达证券公开研报及 Gu-Kelly-Xiu(2020)，为**外部基准参照**，FinFeed 实际表现须以自身数据 walk-forward 回测为准。

---

## 7. UI/UX 重构方案

### 7.1 信息架构与布局

```
┌──────────────────────────────────────────────────────────────────┐
│ 顶栏: 标题 | 模式(实时/ML/混合) | 运行 | 保存模板 | 导出        │
├───────────────┬──────────────────────────────────────────────────┤
│ 左: 配置面板   │ 右: 结果区                                        │
│ (可折叠分组)   │  ┌─ 概览卡片行 ─┐                                │
│ · 股票池       │  ├─ 可视化标签页 ─┤ 分布/行业/雷达/散点/分层      │
│   板块/ST/流动性│  ├─ 结果表 ──────┤ 排序/筛选/搜索/行内维度条     │
│   价格/PE/市值  │  │ (点击行展开: rationale+因子暴露+技术面)      │
│   行业/概念     │  └─ 诊断面板 ────┘ IC/ICIR/模型状态/回测摘要     │
│ · 因子权重      │                                                  │
│   自动IC加权开关│                                                  │
│   八维滑块+实时IC│                                                  │
│ · 输出          │                                                  │
│   前N/评级/组合  │                                                  │
│ [实时预览:      │                                                  │
│  预计入选 N 只] │                                                  │
└───────────────┴──────────────────────────────────────────────────┘
```

### 7.2 交互流程

1. 打开 `/screener` → 加载默认策略（自动 IC 加权 / 线性）+ 实时预览候选池规模。
2. 调整左侧配置 → 即时显示"预计入选 N 只 / 覆盖率 X%"。
3. 点「运行」→ 后台任务（进度条，可取消）→ 结果。
4. 结果解读：图表概览 + 表格下钻（"为什么入选"）。
5. 导出 CSV / 加自选 / 保存模板 / 定时预警。
6. 对比：保存多次运行，叠加对比（策略实验闭环）。

### 7.3 关键界面要点

- **因子权重面板**：每个维度旁实时显示近期 RankIC / ICIR（小字），让用户理解决策依据；滑块仅在"手动模式"可拖。
- **结果表**：行内迷你维度条（红涨绿跌配色，高分红）；支持按任意列排序、文本搜索、按行业/评级筛选。
- **下钻**：展开行显示各因子 z 暴露（雷达微图）+ rationale + 技术面；"为什么入选"一键高亮主导因子。
- **可视化**（7.4）：让选股从"黑盒表格"变为"可解释看板"。

### 7.4 可视化方案

| 图 | 类型 | 作用 |
|---|---|---|
| 综合分分布 | 直方图 | 看入选强度集中区（高位红） |
| 行业分布 | 横向柱状 | 看行业集中度，防单一行业过度暴露 |
| 维度雷达 | 八轴雷达 | 单只 vs 全市场平均，直观看风格 |
| 因子散点 | 气泡(规模×动量, 大小=综合分, 色=评级) | 看风格聚类 |
| 分层收益 | 柱状(十分位) | 验证策略单调性 |

---

## 8. 数据层与工程落地建议

1. **解耦因子注册与执行**：将 `factor_registry.py` 升级为**真正参与执行**的插件式因子接口（每个因子一个 `compute(df)→Series` + 元数据），新增因子只需注册，消除 `factors.py`/`vector.py`/`config` 三处漂移。
2. **数据源**：保留 easy-tdx 主源；将已连接的 `tdx-connector` / `westock-mcp` 作为**补充/回退源**（如资金流、基本面），提升覆盖与健壮性。
3. **历史积累即训练数据**：`snapshot_store` 每日落库真实快照（含资本/估值），既修复回测盲区，又是 ML 训练集。
4. **ML 离线化**：LightGBM 训练作为后台定时任务（盘后），产出模型文件；实时选股仅加载推理，零阻塞。
5. **评估常态化**：将 §3.8 指标接入每日运行，长期监控 IC 衰减与因子失效，触发权重再校准。

---

## 9. 实施路线图（分阶段）

| 阶段 | 内容 | 产出 |
|---|---|---|
| P0 诊断 | 现状梳理 + 本文档 | 设计基线 |
| P1 因子标准化 | 实现 Winsorize→中性化→rank 标准化，替换 sigmoid/bell | 统一预处理管线 |
| P2 线性层 | IC 半衰期加权 + 维度 ICIR 加权 + 可选正交化 | 客观赋权引擎 |
| P3 I/O 重构 | `ScreenerRequest`/`ScreenerResult` + 错误码 + 实时预览 | 结构化契约 |
| P4 UI 重构 | 配置面板 + 图表 + 可排序表 + 下钻 + 导出/模板 | 选股工作台 |
| P5 ML 层 | 后台训练 LightGBM + walk-forward + 混合 | 混合打分 |
| P6 评估闭环 | 每日 IC/ICIR 监控 + 因子失效预警 | 持续验证 |

---

## 10. 风险与回退

- **因子失效**：市场风格切换致历史 IC 失真 → ICIR 加权 + 半衰期衰减自动降权失效因子；监控告警。
- **ML 过拟合**：walk-forward + 验证集 + 正则 + 与线性层混合对冲。
- **数据断供**：主源失败回退东财/缓存，标注 `coverage` 与 `fallback_chain`。
- **回退方案**：任一阶段出现问题，可切回现有六维经验加权（`config` 旧权重）保证服务不中断。

---

*附：本设计所有策略口径均以"样本外验证前假设"呈现，落地后须以 FinFeed 自身数据的 walk-forward 回测确认 KPI，严禁将外部研报数字直接宣称已实现。*

---

## 附录 A. 算法核心实现进度（2026-08-26）

> 进展：P1/P2 已完成；**P3（I/O 契约）、P5（ML 层）已完成并单测覆盖**；P4（前端）、P6（评估闭环）进行中。

### A.1 已完成（可用、已单测）

| 模块 | 文件 | 内容 | 风险 |
|------|------|------|------|
| 标准化原语库 | `finfeed/screener/normalize.py` | Winsorize(p1,p99)、行业+市值 OLS 中性化、秩标准化→[-1,1]、z-score、`preprocess_factor`、`orthogonalize_dimensions` | 纯函数，零副作用 |
| IC 加权引擎 | `finfeed/screener/ic_engine.py` | `resolve_weights`（特性开关入口）、`compute_dimension_ic`（滚动 RankIC）、`halflife_weights`（半衰期权重）、`icir_by_dim`、`compute_engine_weights` | 默认 `fixed` 不触数据源 |
| 引擎开关 | `finfeed/screener/config.py` `ScreenerConfig.engine` | `mode`(fixed/ic/auto/ml/blend/degraded)、`min_history_days`、`ml_min_history_days`、`horizon`、`ic_halflife`、`scheme`、`orthogonalize`、`blend_alpha`、`top_quantile`；`from_dict` 已合并 | 默认 fixed=零风险 |
| 评分接入 | `finfeed/screener/scoring.py` `score_frame` | 调用 `resolve_weights` 解析权重→`assemble_vec`；ml/blend 模式叠加 ML 层（训练+混合+重排+重评级）；`meta` 回填 `engine_mode/weights/diagnostics/model_status` | 新增可选参，调用兼容 |
| 正交化接入 | `finfeed/screener/vector.py` `assemble_vec` + `assign_tier` | `orthogonalize` 残差重缩放回 0~100；评级逻辑抽出 `assign_tier`，线性/混合层复用同一套评级 | 仅 engine.orthogonalize=True 时启用 |
| **ML 层（P5）** | `finfeed/screener/ml_engine.py` | walk-forward 二分类：`train_walkforward`/`predict_ml`/`run_ml_layer`；后端 LightGBM（已装则自动用）否则依赖免费 NumPy 逻辑回归（L2+Newton）；特征=六维子分，标签=前 top_quantile 分位；OOS RankIC/AUC 诊断 | 无 sklearn/lightgbm 亦可运行 |
| I/O 契约（P3） | `finfeed/screener/request.py`、`integrations/screener/router.py` | `ScreenerRequest`（股票池/策略/输出）、模板存/取/列/删、策略对比；`/compare`、`/templates`(GET/POST/DELETE)；`strategy.mode` ∈ linear/ic/auto/ml/blend | 不修改默认语义 |
| 结果模型 | `finfeed/screener/models.py` | `StockScore.ml_prob/factor_exposure` 已落地；`ScreenerResult.engine_mode/weights/diagnostics/model_status/methodology_version` | 向后兼容默认值 |
| 调用方透传 | `integrations/screener/service.py`、`screener/cli.py` | 传入 `store=snapshot_store` 与 `meta`，填充 `ScreenerResult` 引擎字段 | — |
| 方法论说明 | `config.explain()` | 新增「选股引擎（权重来源）」章节，说明 IC 客观加权与降级逻辑 | — |
| 单元测试 | `tests/test_normalize.py`、`tests/test_ic_engine.py`、`tests/test_ml_engine.py` | 90 例全绿（含 ML 可分性、walk-forward 学到信号 OOS AUC>0.5、历史不足降级、ml/blend 经 score_frame 填充 ml_prob） | — |

### A.2 关键设计决策

1. **零风险默认路径**：`engine.mode="fixed"` 时 `resolve_weights` 直接返回 `cfg.weights`，**完全不访问快照存储**，与重构前行为逐位一致；`ic`/`auto` 才有数据源依赖，且历史不足自动 `degraded` 回退固定权重并标注原因。
2. **防未来函数**：前瞻收益严格用 `t+1..t+h`；IC 计算与 ML 训练仅用 t 及之前截面，当前截面只做推理（`ic_engine._forward_returns` + `ml_engine._build_training_set` 经 code 对齐）。
3. **ML 后端零依赖**：本环境 `lightgbm`/`sklearn` 均未安装，ML 层默认走 `numpy` 逻辑回归（L2 正则、Newton/IRLS 求解），保证可运行、可单测；`lightgbm` 安装后 `run_ml_layer` 自动切换梯度提升，无需改代码。
4. **修复的隐患**：`compute_dimension_ic` 原按位置索引对齐维度分与前瞻收益（维度分 Series 以行位置为索引、前瞻收益以 code 为索引），会导致 IC 恒为 NaN；已改为经 code 对齐。该 bug 若不修，IC 引擎所有维度权重将退化为等权。

### A.3 里程碑状态（2026-08-26）

**P1~P6 已全部落地并验证**：

- **P1 标准化预处理库**（`normalize.py`）：Winsorize/中性化/秩标准化/正交化，单测覆盖。
- **P2 IC 客观加权**（`ic_engine.py` + `resolve_weights` 特性开关）：`fixed/ic/auto/degraded` 四种状态，默认 fixed 零风险。
- **P3 完整 I/O 契约**（`request.py` + 路由）：`ScreenerRequest`（股票池/策略/输出）、模板 CRUD、策略对比 `/compare`、`/templates` 端点。
- **P4 前端工作台**（`ScreenerView.vue` 全量重构）：左侧配置面板（引擎模式 5 选 1、六维权重滑块、正交化/混合参数、股票池过滤、模板保存/应用/删除、策略对比、评估闭环按钮）；右侧三页签——评分结果（可排序/搜索/评级筛选表 + 行内下钻雷达与因子暴露）、图表（分数分布/板块/评级/散点，ECharts）、评估闭环（复合 RankIC/ICIR、多空 IR、分层收益、分维度 ICIR、失效监控与重算建议）；支持导出 CSV。`vite build` 通过。
- **P5 ML 层**（`ml_engine.py`）：walk-forward 二分类，后端 LightGBM（已装自动用）否则依赖免费 NumPy 逻辑回归；`ml/blend` 模式产出 `ml_prob` 并与线性层混合；OOS RankIC/AUC 诊断。
- **P6 评估闭环**（`evaluation.py` + `/evaluate` 端点）：无未来函数 walk-forward 评估，复合/分维度 RankIC、ICIR、五分位分层收益、多空价差 IR、因子失效监控（ICIR<0.5 标记）与重算触发建议（切 `ic` 客观重赋权 / 启 `blend` 引入 ML）。

**测试**：`tests/` 96 例全绿（含 normalize 14 例、ic_engine、ml_engine 8 例、evaluation 6 例、screener/report 回归）；FastAPI 端点（config/templates/compare/evaluate）冒烟通过。

> 遗留说明：`snapshot_store` 需持续积累 ≥120 交易日快照，IC 加权与 ML 训练方能在真实盘后自动启用（当前空库自动降级 `fixed`，行为与重构前一致）。
