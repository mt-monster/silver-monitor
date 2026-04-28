# COMEX 银（XAG）动量 + 反转策略分析与实盘优化方案

> 撰写时间：2026-04-27  
> 分析对象：`backend/strategies/momentum.py`、`reversal.py`、`combined.py`、`mtf.py`、`adaptive.py`、`backtest.py`、`backtest_runner.py`、`paper_trading.py`  
> 聚焦品种：COMEX 银（XAG/USD），配置 key = `comex`  
> **回测目标频率**：秒级 tick → 分钟级 → 最高小时级（不使用日线回测）

---

## 一、策略架构总览

### 1.1 三层结构

```
Layer 1 — 单策略信号
  ├─ 动量 (momentum.py)：EMA 双均线 spread/slope → BB 融合 → RSI 融合 → 成交量融合 → 波动率过滤
  └─ 反转 (reversal.py)：RSI 超买超卖分 + BB %B 分 + EMA 偏离度分 → 加权综合评分 → 成交量修正

Layer 2 — 组合决策
  combined.py：MTF 趋势过滤 → 加权融合（动量 0.6 + 反转 0.4） → 分数→信号

Layer 3 — 风控执行
  paper_trading.py：止损 0.15% / 止盈 0.30% / 移动止盈 / 时间止损 60s
```

### 1.2 实际数据流（小时级以内）

```
Sina hf_XAG / Infoway WebSocket
  → 1-3s tick（FastDataPoller 每秒采样）
  → realtime_backtest_buffers：1s 点，最多 300 个（约 5 分钟）
  → instrument_price_buffers：30s bar，最多 200 个（约 100 分钟）
  → SQLite ticks.db：持久化 tick，按日期/时间段查询
  → backtest_runner.py：5 分钟滑动窗口扫描
```

**关键结论**：项目的实际回测数据链是 **tick → 秒级 → 分钟级 → 小时级**。`fetch_comex_history()` 返回的 60 根日线数据仅用于 `index.html` 历史图表展示，**不是策略的核心回测数据源**。因此，日线数据的不足不是真正的问题。

---

## 二、COMEX 银相关参数配置盘点

策略的运行态参数有两套，需要区分适用场景：

### 2.1 `momentum.realtime.comex` — 实时信号 & 短周期回测（**主力配置**）

```json
{
    "short_p": 10, "long_p": 20,
    "spread_entry": 0.012, "spread_strong": 0.08,
    "slope_entry": 0.012,
    "strength_multiplier": 250,
    "cooldown_bars": 5,
    "bb_period": 20, "bb_mult": 2.0,
    "rsi_period": 10,
    "bb_buy_kill": 0.3, "bb_sell_kill": 0.7,
    "min_volatility_pct": 0.03,
    "volume_period": 10, "volume_confirm_ratio": 1.5, "volume_weaken_ratio": 0.6,
    "rsi_buy_kill": 75.0, "rsi_sell_kill": 25.0
}
```

此配置用于 `pollers.py._recompute_signals()` 的实时信号计算（data_source=realtime），
也用于 `backtest_runner.py` 的 5 分钟窗口扫描回测（通过 `momentum_params_from_body({data_source:"realtime"}, "comex")`）。

### 2.2 `momentum.comex` — 历史日线回测（**非核心**）

```json
{
    "short_p": 10, "long_p": 20,
    "spread_entry": 0.05, "spread_strong": 0.18,
    "slope_entry": 0.010,
    "cooldown_bars": 2,
    "bb_buy_kill": 0.25, "bb_sell_kill": 0.75,
    "volume_period": 10
}
```

此配置用于 `/api/backtest` 接口的历史回测（data_source=history），作用于 60 根日线 bar。
**在只做小时级以内回测的场景下，这套参数基本不会被使用**。

### 2.3 `reversal.realtime.comex` — 实时反转信号（**主力配置**）

```json
{
    "rsi_period": 8,
    "rsi_oversold": 35, "rsi_overbought": 65,
    "rsi_extreme_low": 20, "rsi_extreme_high": 80,
    "deviation_entry": 0.12, "deviation_strong": 0.25,
    "min_score": 0.65, "strong_score": 0.80,
    "cooldown_bars": 20,
    "volume_period": 10, "volume_confirm_ratio": 1.5, "volume_weaken_ratio": 0.6, "volume_weight": 0.15
}
```

### 2.4 `reversal.comex` — 历史日线反转（**非核心**）

```json
{
    "rsi_period": 8,
    "deviation_entry": 0.12, "deviation_strong": 0.25,
    "min_score": 0.35, "cooldown_bars": 1
}
```

**注意**：`reversal.comex` 的 `min_score=0.35` 和 `cooldown_bars=1` 明显是为高频场景设计的，
但它挂在历史回测段而非 realtime 段——如果有人对 COMEX 银做历史日线反转回测，这些参数会导致信号泛滥。
不过，既然我们明确了只做小时级以内回测，这个问题的影响降为**低**。

---

## 三、信号逻辑正确性审查

### 3.1 动量策略 — 核心逻辑正确

#### ✅ 正确的部分

| 模块 | 评价 |
|------|------|
| EMA 计算 (`ema_series`) | SMA 种子 + 标准 EMA 递推，与经典实现一致 |
| RSI 计算 (`rsi_series`) | Wilder's smoothed MA，首轮 SMA 种子，递推正确 |
| Bollinger Band (`bollinger_at`) | 总体标准差公式正确，%B 和带宽定义正确 |
| 信号分级逻辑 | spread > entry → buy，spread > strong → strong_buy，对称 sell |

#### ⚠️ 隐患 1：RSI 融合阈值硬编码 70/30

```python
# momentum.py _fuse_with_rsi()
if sig in ("buy", "strong_buy") and rsi > 70:
    sig = "neutral"
if sig in ("sell", "strong_sell") and rsi < 30:
    sig = "neutral"
```

RSI 压制阈值 70/30 **硬编码**在函数内，不受 `MomentumParams` 配置控制。

**对秒级/分钟级数据的影响**：比日线轻很多。短周期 RSI（period=10，作用在 1s bar 上）波动快、极端值停留时间短。但在 COMEX 银快速拉升行情中（如突发地缘事件），RSI 会在短时间内飙升到 80+，此时 buy 信号被压制可能错失关键入场窗口。

**严重程度**：中低。建议将阈值参数化（添加 `rsi_buy_kill` / `rsi_sell_kill` 到 `MomentumParams`），但不是紧急问题。

#### ⚠️ 隐患 2：BB 融合与 RSI 融合串联导致多重压制

```python
# momentum.py
signal = _fuse_with_bb(signal, ...)     # 第一道过滤
signal = _fuse_with_rsi(signal, ...)    # 第二道过滤
```

两道过滤串联，每一道都可以独立将信号压制为 neutral。当 BB %B < buy_kill **且** RSI > 70 同时满足时（实际上不可能同时发生——%B 低意味着价格偏低，RSI 高意味着价格偏高），不会有问题。但当 BB 升级了信号（buy → strong_buy）后被 RSI 压制回 neutral，升级就白做了。

**实际影响**：在 1s bar 数据上，RSI 10 和 BB 20 的时间窗口差异很大（10 秒 vs 20 秒），两者的信号状态经常不同步。这种不同步在大多数时间里是额外的噪声过滤（好事），但在快速行情翻转时可能导致信号滞后。

#### ⚠️ 隐患 3：Squeeze 检测计算量 O(n²)

每次调用 `calc_momentum` 时，squeeze 检测需要对最近 `bb_period` 根 bar 逐个调用 `bollinger_at`，每次内部遍历 `bb_period` 个值。

**对实时场景的影响**：`calc_momentum` 被 `_recompute_signals` 每 1 秒调用一次，输入最多 300 个点。bb_period=20 时，squeeze 检测的额外计算约 20×20=400 次浮点运算——**绝对值很小，不构成性能瓶颈**。

#### ⚠️ 隐患 4：`_fuse_with_bb` 的 strong 降级不对称

- **升级条件**（buy → strong_buy）：%B > 0.5 **且**带宽扩张 → 门槛较高
- **降级条件**（strong_buy → buy）：%B > 1.0 → 门槛很高（需要价格突破上轨）

这意味着 strong 信号一旦产生就不容易降级。在 1s bar 的 5 分钟窗口内，这种"粘性"可能导致持仓信号维持时间偏长。对短周期交易（paper_trading max_hold=60s），影响较小。

### 3.2 反转策略 — 逻辑正确，参数适配度良好

#### ✅ 正确的部分

| 模块 | 评价 |
|------|------|
| RSI 分数映射 | 线性插值 oversold→extreme_low 映射到 0→1，连续平滑 |
| BB %B 分数 | 对称处理，极端区域得分更高 |
| EMA 偏离度 | 方向正确：价格低于 EMA → 正分（看多反转） |
| 加权评分 | 三因子 + 可选成交量修正 |

#### ✅ `deviation_entry=0.12%` 在秒级数据上是合理的

COMEX 银 1 秒级价格变动通常 0.01-0.05%，5 分钟窗口的累计偏移一般 0.05-0.3%。`deviation_entry=0.12%` 作为 EMA 偏离触发线，在这个频率上能有效筛出有意义的均值回归机会。

#### ⚠️ 隐患 5：`cooldown_bars=20` 在 realtime 段偏保守

realtime.comex 段 `cooldown_bars=20` 意味着 20 秒冷却（1s bar × 20）。对 5 分钟窗口（300s）而言，一次信号触发后需要 6.7% 的窗口时间冷却。在波动较大的行情中，这可能错过二次进场机会。

**建议**：可考虑降至 10-15，但需要回测验证。

#### ⚠️ 隐患 6：成交量融合方向性的争议

放量确认反转信号的逻辑在经典技术分析中有争议：
- **当前逻辑**：放量 + 反转看多 → 加分（赌底部放量反弹）
- **另一种观点**：放量下跌 + RSI 超卖 = 恐慌抛售，应等缩量企稳

在 COMEX 银的秒级数据中，"放量"的含义与日线不同——秒级放量更多是流动性事件（大单成交），而非情绪指标。当前逻辑用于秒级场景是**基本可接受**的。

### 3.3 组合策略 — 框架完备

#### ⚠️ 隐患 7：`_signal_score` 忽略 strength

```python
def _signal_score(sig: str, strength: float = 50.0) -> float:
    return _SIGNAL_SCORES.get(sig, 0.0)  # 完全忽略 strength
```

strength=95 的 buy 和 strength=51 的 buy 在组合中得分完全相同。这丢失了信号置信度信息。

#### ⚠️ 隐患 8：MTF 趋势在短周期回测中的有效性存疑

MTF 使用 `instrument_price_buffers`（30s bar）计算 5min/15min EMA 趋势。但在 `backtest_runner.py` 的 5 分钟窗口回测中，`run_combined_backtest` 试图在 300 个 1s bar 上模拟 MTF：

```python
# backtest.py L907
for j in range(0, i + 1, 30):
    chunk = prices[j: j + 30]
    agg.append(chunk[-1])
```

将 1s bar 每 30 个聚合为 1 个伪 "30s bar"，然后计算趋势。问题是 5 分钟 = 300 个 1s bar = 只有 10 个聚合 bar，而 MTF 需要 `slow_period_bars + 5 = 35` 个聚合 bar。**MTF 在 5 分钟窗口中几乎永远无法启用**（需要至少 35 × 30 = 1050 个 1s bar = 17.5 分钟数据）。

**影响**：组合回测中 `mtf_trend` 始终为 `"sideways"`，MTF 过滤形同虚设。

---

## 四、数据层分析

### 4.1 数据分层与覆盖度

| 层级 | 数据源 | 频率 | 深度 | 用途 |
|------|--------|------|------|------|
| L0 实时信号 | `realtime_backtest_buffers` | 1s | 300 点 ≈ 5 分钟 | `_recompute_signals`, `_recompute_reversal_signals` |
| L1 中期信号 | `instrument_price_buffers` | 30s | 200 条 ≈ 100 分钟 | MTF 趋势计算 |
| L2 短周期回测 | SQLite `ticks.db` | 1s tick | 按日积累 | `backtest_runner.py` 5 分钟窗口扫描 |
| L3 历史图表 | Sina 日线 | 1d | 60 根 ≈ 3 个月 | 前端 `index.html` 展示（**非回测用**） |

### 4.2 ✅ 秒级→分钟级数据链条完整

- **L0 → L2** 的数据链（tick → SQLite → 5min 窗口扫描）是完整且正确的
- `backtest_runner.py` 的滑动窗口设计（5 分钟窗口，30s 步长）是合理的短周期回测框架
- tick 持久化到 SQLite 后可跨日累积，理论上可支撑更长回测

### 4.3 ⚠️ 缺口：分钟级→小时级的聚合回测

当前系统有两个回测通道：
1. **5 分钟窗口**（`backtest_runner.py`）— 从 SQLite tick 构建，频率正确
2. **历史回测**（`backtest.py` + `load_history`）— 从 Sina 日线拉取，对 COMEX 银是日线

**缺少中间层**：无法用 SQLite 中积累的 tick 聚合为 1min/5min/15min/60min K 线，然后对这些中频 K 线做回测。

- `load_realtime_bars()` 只取最近 N 分钟的内存 buffer，且深度有限（300 点）
- SQLite `get_ticks_for_date()` 返回原始 tick，没有 K 线聚合功能

要实现**小时级回测**（如"最近 3 天的 15 分钟 K 线回测"），需要：
1. 从 SQLite 查询多日 tick → 聚合为目标频率 K 线
2. 用聚合后的 K 线调用 `run_momentum_backtest` / `run_reversal_backtest`

### 4.4 日线数据的定位

既然回测只到小时级，`fetch_comex_history()` 的 60 根日线数据：
- **不影响策略信号计算**（信号用 L0/L1 数据）
- **不影响核心回测**（回测用 L2 数据）
- **仅影响前端历史图表展示**

可以保留现状，但也可以考虑改为从 SQLite 积累的 tick 聚合出日线，这样历史图表会随着运行时间逐步增长。

---

## 五、回测引擎分析

### 5.1 `backtest_runner.py` — 短周期回测（主力）

#### ✅ 设计合理的部分

- **5 分钟滑动窗口 + 30s 步长**：对秒级数据是合适的回测粒度
- **参数网格扫描**：`DEFAULT_PARAM_GRID` 只扫 `spread_entry` 和 `slope_entry` 两个参数，4×4=16 个组合，过拟合风险可控
- **综合评分** `_score_for_ranking`：收益率 0.6 + 夏普 0.3 - 回撤 0.1，偏重收益率在短周期是合理的
- **tick 质量评估** `_compute_tick_quality`：检查数据点数、间隔、变异系数，可过滤无效窗口

#### ⚠️ 隐患 9：5 分钟窗口内信号数量极少

5 分钟 = 300 个 1s bar，去掉 long_p+2=22 根预热，有效区间 278 根。
动量策略 cooldown_bars=5 意味着每次信号后 5s 冷却。
典型场景：一个 5 分钟窗口可能产生 **2-6 笔交易**。

这个样本量对单窗口评估是不够的。但 `scan_5min_windows` 会扫描一整天的所有窗口（如交易时段 6 小时 = 约 700 个窗口），**汇总后的统计量是有意义的**。

**建议**：评估指标应更多关注**跨窗口的一致性**（如正收益窗口占比），而非单窗口的夏普比率。

#### ⚠️ 隐患 10：`backtest_runner.py` 只回测动量策略

`_run_momentum_for_window` 是默认的回测路径。虽然支持 `strategy="combined"` 和 `strategy="reversal"`，但：
- `combined` 路径的参数构建较简陋（`MomentumParams` 只取少数字段）
- `reversal` 路径直接用 `ReversalParams()` 默认值，忽略品种配置

要真正验证 COMEX 银的反转和组合策略，需要在窗口回测中正确加载品种级参数。

### 5.2 `backtest.py` — 历史回测

#### ⚠️ 隐患 11：回测引擎缺少止损/止盈

`run_momentum_long_only_backtest` 和 `run_momentum_long_short_backtest` 中**没有止损/止盈逻辑**。退出完全依赖信号翻转。

但 `paper_trading.py` 在实盘中提供了完整的止损/止盈/移动止盈/时间止损。

**后果**：回测结果（无止损）与实盘行为（有止损）不一致。可能出现回测显示 +5% 但实盘因 0.15% 止损已经出场的情况。

#### ⚠️ 隐患 12：反转策略回测 O(n²) 复杂度

```python
# backtest.py L681
window = [float(b["y"]) for b in bars[: i + 1]]
result = calc_reversal(window, params)
```

每根 bar 重建完整价格序列并重算 RSI/BB/EMA。在 300 个 1s bar 的窗口内：
- 300 次调用，每次传入 1~300 个点
- 总计算量约 300 × 150 / 2 ≈ 22,500 次均值运算

**实际影响**：在 5 分钟窗口内计算时间约几十毫秒，不是瓶颈。但如果未来扩展到小时级窗口（3600 个点），会显著变慢。动量回测已经用预计算方式（O(n)），反转回测应对齐。

#### ⚠️ 隐患 13：Long-Short 做空模型简化

```python
eq = capital * max(0.0, 2.0 - px / entry_p)
```

假设无杠杆做空。在秒级/分钟级的小幅波动中（±0.5%），这个近似足够精确。
但如果价格在窗口内波动超过 ±5%（COMEX 银闪崩场景），公式偏差会放大。

### 5.3 Walk-Forward 验证

```python
# backtest.py L628
split = int(n * train_ratio)  # 单次 70/30 切分
```

单次切分对 5 分钟窗口（300 个点）：训练 210 点、测试 90 点。测试集只有 90 秒，统计意义弱。

**但结合 `backtest_runner.py` 的滑动窗口扫描**，跨窗口的参数稳定性本身就是一种 walk-forward 验证——如果最佳参数在连续多个窗口中都表现良好，说明参数具有泛化能力。

---

## 六、实盘风控分析

### 6.1 Paper Trading — 与秒级策略对齐良好

```json
"paper_trading": {
    "stop_loss_pct": 0.15,
    "take_profit_pct": 0.30,
    "trailing_trigger_pct": 0.10,
    "trailing_retracement_pct": 0.05,
    "max_hold_seconds": 60
}
```

在秒级/分钟级交易场景下：
- **止损 0.15%**：COMEX 银 1 分钟波动约 0.05-0.15%，0.15% 止损约等于 1-3 分钟的反向波动，合理
- **止盈 0.30%**：盈亏比 2:1，经典设置
- **持仓 60s**：适合 5 分钟窗口中的微趋势交易
- **移动止盈触发 0.10%**：约 1 分钟的有利波动后开始跟踪，合理

#### ⚠️ 隐患 14：Paper Trading 没有品种差异化

所有品种（ag0, xag, au0, xau, btc）共用同一套 paper_trading 参数。但：
- BTC 的秒级波动远大于 XAG（约 5-10 倍）
- 0.15% 止损对 BTC 太紧，容易被噪声触发

对 COMEX 银单品种分析来说，当前参数基本合适。

### 6.2 回测与实盘的风控差距

| 风控机制 | 回测引擎 | Paper Trading | 差距 |
|----------|----------|---------------|------|
| 止损 | ❌ 无 | ✅ 0.15% | **严重脱节** |
| 止盈 | ❌ 无 | ✅ 0.30% | **严重脱节** |
| 移动止盈 | ❌ 无 | ✅ 有 | **严重脱节** |
| 时间止损 | ❌ 无 | ✅ 60s | **严重脱节** |
| 仓位管理 | ❌ 满仓进出 | ❌ 无 | 一致（但都缺） |

这是**最大的结构性问题**：回测结果和实盘行为由于风控差异而不可比较。

### 6.3 缺失的风控机制

- **单日最大亏损限制**：连续止损后应缩减仓位或暂停交易
- **波动率自适应仓位**：`adaptive.py` 只调阈值不调仓位
- **连续亏损保护**：paper_trading 中无此逻辑
- **品种级止损差异**：所有品种共用一套止损参数

---

## 七、过拟合风险评估

### 7.1 5 分钟窗口内的过拟合

单窗口内 300 个 1s bar，参数网格 4×4=16 个组合，选最优。
16 次试验在 2-6 笔交易上选最优——**单窗口结果的随机性很大**。

**缓解措施**（已有）：
- `backtest_runner.py` 扫描一整天的所有窗口，汇总 top-10
- `_score_for_ranking` 综合考虑收益、夏普和回撤
- `_compute_tick_quality` 过滤数据质量差的窗口

**缓解措施**（建议补充）：
- 对 top-10 窗口的最佳参数做**一致性检查**：如果最优 spread_entry 在不同窗口分散在 0.01-0.05 之间，说明参数不稳定
- 统计**全部窗口的胜率分布**而非只看 top-N

### 7.2 Grid Search 的过拟合风险可控

`backtest_runner.py` 的默认网格只有 2 个参数 × 4 个值 = 16 组合，维度很低。
而 `backtest.py` 的 `run_grid_search` 最多 500 组合、11 个参数，过拟合风险高得多。

**结论**：在小时级以内回测中，使用 `backtest_runner.py` 的轻量网格是合理的选择。避免使用 `run_grid_search` 的大网格做短周期优化。

---

## 八、优化方案（按优先级排列）

### P0 — 回测引擎：加入止损/止盈对齐实盘

**问题**：回测无止损，结果与 paper_trading 实盘行为脱节  
**方案**：

在 `BacktestConfig` 中新增止损/止盈参数：

```python
@dataclass
class BacktestConfig:
    mode: str = "long_only"
    commission_rate: float = 0.0
    slippage_pct: float = 0.0
    stop_loss_pct: float = 0.0        # 0 = 禁用
    take_profit_pct: float = 0.0      # 0 = 禁用
    trailing_trigger_pct: float = 0.0
    trailing_retracement_pct: float = 0.0
    max_hold_bars: int = 0            # 0 = 禁用
```

回测循环中逐 bar 检查持仓盈亏，触发止损/止盈时立即平仓。默认值配合 paper_trading 配置：
- `stop_loss_pct = 0.15`，`take_profit_pct = 0.30`
- `max_hold_bars = 60`（对 1s bar 等于 60 秒）

**优先级最高**：不对齐风控就不知道回测结果能不能信。

### P1 — 数据层：SQLite tick 聚合为中频 K 线

**问题**：无法在分钟/小时级做回测  
**方案**：

在 `tick_storage.py` 新增聚合查询：

```python
def get_klines(instrument_id: str, start_date: str, end_date: str,
               interval_minutes: int = 5) -> list[dict]:
    """从 tick 聚合为指定频率的 OHLCV K 线。"""
    ticks = get_ticks_range(instrument_id, start_ms, end_ms)
    # 按 interval_minutes 分组，计算 open/high/low/close
    ...
```

然后在 `backtest.py` 中新增 `load_kline_history()` 函数，支持从 SQLite 加载中频 K 线回测：
- 1 分钟 K 线 × 1 天 ≈ 360 根（COMEX 银交易时段约 6 小时）
- 5 分钟 K 线 × 5 天 ≈ 360 根
- 15 分钟 K 线 × 10 天 ≈ 240 根

这些数量级的样本对于回测来说是足够的。

### P2 — 信号层：RSI 融合阈值参数化（已实现）

**问题**：`_fuse_with_rsi` 中 70/30 硬编码  
**方案**：

```python
# 在 MomentumParams 中新增
rsi_buy_kill: float = 70.0    # RSI 高于此值压制 buy
rsi_sell_kill: float = 30.0   # RSI 低于此值压制 sell
```

对 COMEX 银秒级数据，首轮实测后已放宽到 75/25（RSI period=10 的波动更极端）。

### P3 — 回测层：`backtest_runner.py` 支持反转和组合策略的品种级参数

**问题**：`strategy="reversal"` 使用默认参数，`strategy="combined"` 参数构建不完整  
**方案**：

在 `_run_momentum_for_window` 旁边添加 `_run_reversal_for_window` 和 `_run_combined_for_window`，
从 `reversal_params_from_body` / `momentum_params_from_body` 获取品种级配置。

### P4 — 信号层：减少串联过滤深度

**问题**：BB → RSI → 成交量 → 波动率四重串联，信号丢失概率高  
**方案**：

将四个过滤器改为**并联评分修正**：

```
base_score = ema_spread_score        # 基础 EMA 信号得分
bb_modifier = f(percentB)            # [-0.2, +0.2]
rsi_modifier = f(rsi)               # [-0.2, +0.2]
vol_modifier = f(volume_ratio)       # [-0.1, +0.1]
volatility_gate = g(cv)             # [0.0, 1.0] 乘法门控

final_score = (base_score + bb_modifier + rsi_modifier + vol_modifier) × volatility_gate
```

好处：
- 不再有单因子"一票否决"
- 信号强度连续可分（0-100），便于仓位管理
- 多因子共振时信号增强，单因子异常时仅轻度削弱

### P5 — 组合层：利用 strength 做精细化决策

**问题**：`_signal_score` 忽略 strength  
**方案**：

```python
def _signal_score(sig: str, strength: float = 50.0) -> float:
    base = _SIGNAL_SCORES.get(sig, 0.0)
    scale = 0.5 + strength / 100.0   # 0→0.5, 100→1.5
    return base * scale
```

### P6 — 验证层：跨窗口参数一致性检验

**问题**：单窗口最优参数的随机性大  
**方案**：

在 `scan_5min_windows` 的输出中新增：

```python
"param_stability": {
    "spread_entry": {"mean": 0.025, "std": 0.01, "cv": 0.4},
    "slope_entry": {"mean": 0.012, "std": 0.003, "cv": 0.25},
}
```

CV < 0.3 的参数可信度高，CV > 0.5 的参数说明对该因子不敏感或不稳定。

### P7 — 风控层：品种级 Paper Trading 参数

**问题**：所有品种共用一套止损  
**方案**：

```json
"paper_trading": {
    "default": { "stop_loss_pct": 0.15, "take_profit_pct": 0.30, "max_hold_seconds": 60 },
    "xag": { "stop_loss_pct": 0.12, "take_profit_pct": 0.25, "max_hold_seconds": 90 },
    "btc": { "stop_loss_pct": 0.50, "take_profit_pct": 1.00, "max_hold_seconds": 120 }
}
```

### P8 — 数据层：MTF 在组合回测中的修复

**问题**：5 分钟窗口内 MTF 数据不足，始终返回 sideways  
**方案**：

组合回测时，如果窗口长度不足以计算 MTF，应该：
1. 从 SQLite 取该窗口之前的 15-30 分钟数据作为 MTF 预热
2. 或者在组合信号中显式标记 `mtf_available: false`，降低 MTF 权重为 0

---

## 九、实装优化与 5 分钟级别回测结果（2026-04-27）

### 9.1 已实装内容

- **回测风控对齐**：`BacktestConfig` 新增 `stop_loss_pct`、`take_profit_pct`、`trailing_trigger_pct`、`trailing_retracement_pct`、`max_hold_bars`，动量 long-only / long-short 回测会逐 bar 检查风险退出。
- **RSI 阈值参数化**：`MomentumParams` 新增 `rsi_buy_kill` / `rsi_sell_kill`，`calc_momentum()`、`backtest.py`、`backtest_runner.py`、`pollers.py` 均已透传。
- **COMEX 银实时参数更新**：`monitor.config.json` 的 `momentum.realtime.comex` 已设置为 `rsi_buy_kill=75.0`、`rsi_sell_kill=25.0`。
- **前端观望原因展示**：动量信号面板会按实时配置显示 EMA 周期、RSI 阈值，并在 `neutral` 时提示 EMA 张口、短线斜率、RSI、量比等观望原因。
- **5 分钟级别回测脚本**：`tests/_run_xag_5min_compare.py` 对 SQLite tick 数据执行非重叠 5 分钟窗口扫描。

### 9.2 回测设置

| 项目 | 设置 |
|------|------|
| 品种 | COMEX 银 `xag` |
| 数据 | SQLite tick 数据 |
| 日期 | 2026-04-23、2026-04-24、2026-04-25、2026-04-27 |
| 窗口 | 非重叠 5 分钟窗口 |
| 有效窗口 | 580 个 |
| 参数网格 | `spread_entry=[0.008,0.012,0.020]` × `slope_entry=[0.008,0.012,0.018]` |
| 手续费/滑点 | 暂未计入 |

### 9.3 迭代绩效对比

| 版本 | 策略调整 | 有交易窗口 | 正收益窗口 | 平均收益/窗 | 窗口复利 | 平均回撤 | 胜率 | PF | 风控触发/窗 |
|------|----------|------------|------------|-------------|----------|----------|------|----|-------------|
| baseline | 无 SL/TP，RSI 70/30 | 28.97% | 28.79% | 0.0165% | 10.050% | 0.0084% | 89.96% | 5.54 | 0.000 |
| v1 | SL0.15/TP0.30/移动止盈/60bar，RSI 70/30 | 28.97% | 28.79% | 0.0157% | 9.520% | 0.0082% | 90.16% | 5.58 | 0.016 |
| v2 | v1 + RSI 75/25 | 29.14% | 28.79% | 0.0159% | 9.634% | 0.0082% | 90.32% | 5.90 | 0.016 |
| v3 | 更紧 SL0.10/TP0.25/90bar + RSI 75/25 | 29.14% | 28.79% | 0.0155% | 9.369% | 0.0080% | 90.22% | 6.36 | 0.029 |
| v4 | 更宽 SL0.20/TP0.50/120bar + RSI 75/25 | 29.14% | 28.79% | 0.0161% | 9.761% | 0.0083% | 90.12% | 5.86 | 0.005 |
| v5 | 仅时间止损 90bar + RSI 75/25 | 29.14% | 28.79% | 0.0167% | 10.165% | 0.0084% | 90.12% | 5.86 | 0.000 |
| v6 | SL0.20 only/120bar + RSI 75/25 | 29.14% | 28.79% | 0.0167% | 10.165% | 0.0084% | 90.12% | 5.86 | 0.000 |
| v7 | 无 SL/TP，RSI 80/20 | 29.14% | 28.79% | **0.0169%** | **10.279%** | 0.0084% | 89.21% | 5.16 | 0.000 |

### 9.4 结论

- **硬止盈会截断趋势收益**：`0.15/0.30` 与 `0.10/0.25` 均降低窗口复利，说明当前 5 分钟窗口内的盈利主要来自少数趋势延伸段，过早止盈会损害收益。
- **RSI 75/25 是较稳健改进**：相比 70/30，交易覆盖率略升，PF 和胜率改善，不明显增加回撤。
- **RSI 80/20 收益最高但质量变差**：平均收益与复利最高，但胜率和 PF 下降，说明信号更激进，适合作为后续待验证版本，不建议直接作为实盘默认。
- **当前推荐实盘参数**：保持 `momentum.realtime.comex` 的 `rsi_buy_kill=75.0`、`rsi_sell_kill=25.0`；paper trading 不宜使用过紧硬止盈，优先验证 `max_hold_seconds=90` 或 `120` 的品种级配置。

### 9.5 后续迭代建议

1. **下一轮加入交易成本**：至少加入 0.01%-0.03% 单边滑点/手续费，重新比较 v5/v7。
2. **扩大样本日期**：当前只有 4 天 tick 数据，结论偏短样本，应积累 2-4 周后再确定最终实盘参数。
3. **实现品种级 paper_trading 配置**：将 XAG 的 `max_hold_seconds` 从全局 60 独立出来，测试 90/120 秒。
4. **补中频 K 线回测**：用 SQLite tick 聚合 1m/5m/15m bar，验证小时级以内的参数稳定性。

---

## 十、总结

### 逻辑正确性
- **核心算法（EMA/RSI/BB/加权评分）数学上正确**
- 主要问题不在计算错误，而在设计层面：串联过滤、回测-实盘风控不对齐、短样本参数稳定性不足

### 数据层现状
- **秒级→5 分钟的数据链完整且正确**，是策略的主力数据通道
- 日线数据仅用于前端图表展示，不影响策略和回测
- **缺口**：分钟级→小时级的 K 线聚合回测通道尚未建立

### 最大风险（按严重程度）

| 序号 | 风险 | 严重程度 | 影响 |
|------|------|----------|------|
| 1 | **中频 K 线回测尚未建立** | 🟡 中 | 限制了策略验证的时间跨度 |
| 2 | **交易成本尚未计入本轮 5 分钟回测** | 🟡 中 | 高频策略绩效可能被高估 |
| 3 | **样本天数偏少** | 🟡 中 | 5 分钟级别结论存在短样本风险 |
| 4 | **MTF 在短周期回测中失效** | 🟡 中 | 组合回测的趋势过滤形同虚设 |
| 5 | **串联过滤过深** | 🟢 低 | 有效信号偶尔被多重压制 |

### 建议实施顺序

```
P0 回测止损对齐 → P1 SQLite K 线聚合 → P2 RSI 参数化 → P3 窗口回测品种参数
→ P4 并联评分 → P5 strength 利用 → P6 参数一致性检验 → P7 品种级风控 → P8 MTF 修复
```

P0 是**基础对齐**：不解决回测-实盘风控差异，一切策略优化都无法被验证。  
P1 打开**中频回测能力**：让策略可以在更长时间跨度上被验证。  
P2-P3 是**信号质量**的低成本改进。
