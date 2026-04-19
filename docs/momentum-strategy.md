# 动量策略：计算说明、使用方法与优化空间

> 最后更新：2026-04-16 — 已覆盖全品类商品（49 品种）

---

## 1. 策略概览

本系统的核心信号模型为 **EMA 短/长张口 + 短 EMA 一步斜率 + Bollinger Band 带融合**，用于判断单一品种的短期多空方向和强度。

**五档输出信号**：

| 信号 key | 中文 | 含义 |
|---|---|---|
| `strong_buy` | 强多 | EMA 张口大 + 斜率正 + BB 位置确认 |
| `buy` | 做多 | EMA 金叉且张口 + 斜率正 |
| `neutral` | 观望 | 条件不满足 / BB 否决 |
| `sell` | 做空 | EMA 死叉且张口 + 斜率负 |
| `strong_sell` | 强空 | EMA 张口大 + 斜率负 + BB 位置确认 |

---

## 2. 核心算法

### 2.1 EMA（指数移动平均）

```
平滑系数  k = 2 / (N + 1)
种子      SMA = mean(price[0..N-1])       // 前 N 个值的简单平均
递推      EMA[i] = price[i] * k + EMA[i-1] * (1-k)   (i >= N)
```

- 数据不足一个周期时退化为首值种子 EMA。
- 计算短 EMA（默认 N=5）和长 EMA（默认 N=20）两条线。

### 2.2 指标计算

**动量差 spreadPct**（快慢线相对张口）：

```
spreadPct = (EMA_short - EMA_long) / EMA_long × 100  (%)
```

**短线斜率 slopePct**（短 EMA 一步变化率）：

```
slopePct = (EMA_short[末] - EMA_short[末-1]) / EMA_short[末-1] × 100  (%)
```

**强度 strength**（进度条，0～100）：

```
strength = min(100, |spreadPct| × strength_multiplier)
```

### 2.3 EMA 基础信号判定

```
IF EMA_short > EMA_long
   AND spreadPct > spread_entry
   AND slopePct  > slope_entry:
      signal = spreadPct > spread_strong ? "strong_buy" : "buy"

ELIF EMA_short < EMA_long
   AND spreadPct < -spread_entry
   AND slopePct  < -slope_entry:
      signal = spreadPct < -spread_strong ? "strong_sell" : "sell"

ELSE:
      signal = "neutral"
```

### 2.4 Bollinger Band 融合修正

在 EMA 基础信号之上，若启用 BB（`bb_period > 0`），计算 `%B`（价格在布林带中的位置）和带宽变化方向，对信号做二次修正：

```
%B = (price - lower) / (upper - lower)
bandwidth = (upper - lower) / middle × 100 (%)
bwExpanding = 当前 bandwidth > 前一根 bandwidth
```

**融合规则**（`_fuse_with_bb`）：

| 原始信号 | 条件 | 修正为 | 理由 |
|---|---|---|---|
| `buy` | `%B < 0.3` | `neutral` | 价格位于带下方，位置与多头方向矛盾 |
| `buy` | `%B > 0.5` + 带宽扩张 | `strong_buy` | 趋势 + 位置 + 波动率三确认 |
| `strong_buy` | `%B > 1.0` | `buy` | 过度延伸/超买，降级 |
| `sell` | `%B > 0.7` | `neutral` | 位置与空头方向矛盾 |
| `sell` | `%B < 0.5` + 带宽扩张 | `strong_sell` | 三确认 |
| `strong_sell` | `%B < 0.0` | `sell` | 超卖反弹风险，降级 |

### 2.5 最少样本数

```
minLen = long_p + 2
```

默认 `long_p = 20` → 需至少 **22 个有效价格点**。不足时返回 null，界面显示「等待」。

---

## 3. 使用场景

本策略在系统中有 **三个使用场景**，算法公式一致，但数据源和执行方式不同：

### 3.1 实时监控页（银/金 Tab）

| 项目 | 说明 |
|---|---|
| **代码** | `assets/js/monitor/momentum.js` — 前端 JS 计算 |
| **触发** | `fetchData()` 每 1s 轮询 `/api/all` 后调用 |
| **数据** | 实时 tick 序列（去重后追加），上限 180 点 |
| **品种** | 沪银(hu) / COMEX银(co) / 沪金(au) / COMEX金(cg) |
| **参数来源** | `monitor.config.json` → `core.js` → `Monitor.momentumThresholds` / `momentumPeriods` |
| **特殊功能** | 信号变化时对 `strong_buy`/`strong_sell` 播放提示音 |

**采样规则**：仅在 `price > 0 && !closed && !error` 时入队，且与上一点价格相同时跳过（去重防 EMA 张口被淹没）。

### 3.2 品种详情页（全品类 Detail）

| 项目 | 说明 |
|---|---|
| **代码** | `assets/js/monitor/detail.js` — `_updateMomentum()` |
| **触发** | 从全品类看板点击任一品种卡片后，独立 3s 轮询 `/api/instrument/{id}` |
| **数据** | 实时 tick 序列（去重后追加），上限 600 点 |
| **品种** | 注册表中全部 49 个品种 |
| **参数来源** | 优先 `Monitor.momentumThresholds[inst.id]`，回退 default |

### 3.3 策略回测页

| 项目 | 说明 |
|---|---|
| **代码** | `backend/strategies/momentum.py` + `backend/backtest.py` — Python 服务端 |
| **触发** | `POST /api/backtest`，strategy.html 页面手动触发 |
| **数据** | 国内品种：akshare 60 分钟 K 线（约 200 根）；国际品种：akshare 日线（约 60 根） |
| **品种** | 注册表中全部品种（前端从 `/api/instruments/registry` 动态加载下拉） |
| **参数来源** | 请求体 `params` > `monitor.config.json` 品种特定 > 默认值 |
| **执行模式** | Long-only、收盘调仓、不计手续费 |
| **冷却机制** | `cooldown_bars`：开/平仓后跳过 N 根 bar（默认 0，可配置） |
| **Squeeze 检测** | 后端额外计算 BB 缩口（当前带宽 ≤ 近 N 根最小带宽），实时监控不包含此逻辑 |

---

## 4. 参数配置

所有参数集中在 `monitor.config.json` 的 `momentum` 段：

```json
{
  "momentum": {
    "default": {
      "short_p": 5,        // EMA 短周期
      "long_p": 20,        // EMA 长周期
      "spread_entry": 0.10, // 张口入场阈值 (%)
      "spread_strong": 0.35,// 强信号张口阈值 (%)
      "slope_entry": 0.02,  // 短线斜率入场阈值 (%)
      "strength_multiplier": 120, // 强度条放大系数
      "cooldown_bars": 0,   // 回测冷却 bar 数
      "bb_period": 20,      // Bollinger 周期
      "bb_mult": 2.0        // Bollinger 标准差乘数
    },
    "huyin": { ... },       // 沪银品种专属覆盖
    "comex": { ... }        // COMEX银品种专属覆盖
  }
}
```

### 品种特定参数（已配置的例子）

| 品种 | short_p | long_p | spread_entry | spread_strong | slope_entry | strength_mul | cooldown | bb_period |
|---|---|---|---|---|---|---|---|---|
| **default** | 5 | 20 | 0.10 | 0.35 | 0.02 | 120 | 0 | 20 |
| **huyin** (沪银) | 8 | 21 | 0.15 | 0.50 | 0.03 | 100 | 3 | 20 |
| **comex** (COMEX银) | 3 | 10 | 0.03 | 0.12 | 0.008 | 300 | 2 | 10 |
| **hujin** (沪金) | 8 | 21 | 0.12 | 0.40 | 0.025 | 100 | 3 | 20 |
| **comex_gold** (COMEX金) | 3 | 10 | 0.03 | 0.12 | 0.008 | 300 | 2 | 10 |

**参数优先级**（回测）：请求体 `params` > 配置文件品种特定 > 配置文件 `default`。

### 参数含义速查

| 参数 | 作用 | 调大效果 | 调小效果 |
|---|---|---|---|
| `short_p` | 短 EMA 周期 | 更平滑、延迟更大 | 更灵敏、噪音更多 |
| `long_p` | 长 EMA 周期 | 基准线更稳、信号更少 | 信号更多、假信号增加 |
| `spread_entry` | 张口入场门槛 | 过滤弱趋势 | 捕捉更小趋势 |
| `spread_strong` | 强信号门槛 | 减少强信号频率 | 更容易触发强多/强空 |
| `slope_entry` | 斜率确认门槛 | 需要更大动能才进场 | 微动即触发 |
| `strength_multiplier` | 强度条缩放 | 进度条更快拉满 | 需要更大张口才显满 |
| `cooldown_bars` | 回测冷却期 | 避免频繁反手 | 允许快速重新入场 |
| `bb_period` | BB 周期 | 更宽的波动参考 | 更短期的波动参考 |
| `bb_mult` | BB 标准差乘数 | 带更宽、%B 更集中 | 带更窄、超买超卖更敏感 |

---

## 5. 实现一致性

前端和后端的动量计算是 **同源公式的独立实现**：

| 对比项 | 前端 (JS) | 后端 (Python) |
|---|---|---|
| EMA | `Monitor.ema()` (momentum.js) | `ema_series()` / `_incremental_ema()` |
| Bollinger | `Monitor.bollingerAt()` | `bollinger_at()` / `_incremental_bb()` |
| BB 融合 | `_fuseWithBB()` | `_fuse_with_bb()` |
| 信号计算 | `Monitor.calcMomentum()` | `calc_momentum()` |
| 信号渲染 | `Monitor.renderSignal(prefix, info, decimals)` | — (前端专属) |

**注意**：后端 `calc_momentum` 额外计算 Squeeze（缩口检测），前端 `calcMomentum` 不含此功能。

---

## 6. 界面元素对应

以信号卡片为例（prefix 为品种标识如 `hu`、`co`、`dt` 等）：

| UI 元素 | 数据来源 | 说明 |
|---|---|---|
| 信号徽章 | `signal` → 中文映射 | 类名控制颜色 |
| 短线斜率 | `slopePct` | 红/绿色标注方向 |
| EMA短 | `shortEMA` | 末值，小数位按品种 |
| EMA长 | `longEMA` | 末值 |
| Boll %B | `bb.percentB` | >0.8 红，<0.2 绿 |
| 带宽 | `bb.bandwidth` | 百分比 |
| 强度条 | `strength` | 0-100%，bull/bear/flat 配色 |
| 备注行 | `spreadPct` + BB 状态 | "动量差 ±x.xxx%" + "超买/超卖/带宽扩张" |
| 提示音 | 信号变化时 | 仅 strong_buy / strong_sell 触发 |

---

## 7. 优化空间

### 7.1 信号质量

| 方向 | 现状 | 建议 |
|---|---|---|
| **自适应参数** | 当前 EMA 周期和阈值为静态配置，需人工调优 | 引入 ATR 自适应：`spread_entry = f(ATR%)`，高波动品种自动放宽阈值，低波动品种收紧 |
| **多时间框架确认** | 仅使用单一频率数据 | 增加 MTF（Multi-Timeframe）：如用日线趋势方向过滤 60min 信号，减少逆势交易 |
| **成交量确认** | 当前完全不使用成交量 | 国内品种 Sina 数据含 volume 字段，可加入「量价齐升」确认：有量的突破权重更高 |
| **Squeeze 前端补齐** | 后端 backtest 计算 Squeeze（BB 缩口），前端实时监控未实现 | 前端 `calcMomentum` 补充 Squeeze 检测，缩口后首次扩张可作为额外入场信号 |
| **信号冷却** | 实时监控无 cooldown 机制，信号可能频繁翻转 | 加入前端 cooldown 计数器（类比回测的 `cooldown_bars`） |
| **RSI / MACD 扩展** | 仅 EMA+BB 两个维度 | 增加 RSI 超买超卖区间作为第三维度融合，构成更完整的多因子模型 |

### 7.2 参数管理

| 方向 | 现状 | 建议 |
|---|---|---|
| **全品种配置覆盖** | 仅 4 个贵金属有品种特定参数，其余 45 品种用 default | 按品种波动率特征分组（如高波动能化/低波动农产品），每组一套默认参数 |
| **参数热更新** | 前端改配置需刷新页面，后端需重启 | 添加 `/api/config/reload` 接口 + 前端定期拉取配置变更 |
| **自动参数搜索** | 人工设定阈值 | 回测页增加 Grid Search / Walk-forward 优化：自动遍历参数组合，输出最优夏普比 |

### 7.3 回测引擎

| 方向 | 现状 | 建议 |
|---|---|---|
| **成本模型** | 不计手续费和滑点 | 添加可配置的手续费率（如万分之 0.5）和滑点（1 tick），回测结果更接近实盘 |
| **多策略支持** | 仅 momentum long-only | 扩展为策略插件架构：均线交叉、通道突破、统计套利等可注册为不同 strategy |
| **双向交易** | 仅 Long-only | 增加 Long-Short 模式，sell 信号开空，buy 信号平空开多 |
| **Walk-forward** | 无 | 分段回测：用前 N 根 bar 优化参数，后 M 根 bar 验证，避免过拟合 |
| **数据深度** | 国内 ~200 根 60min（约 2 周）；国际 ~60 根日线（约 2 月） | 本地缓存历史 K 线（SQLite/CSV），积累更长窗口供统计检验 |

### 7.4 工程质量

| 方向 | 现状 | 建议 |
|---|---|---|
| **前后端一致性** | 同源公式独立实现，存在漂移风险 | 编写对齐单测：给定相同输入，断言前端 JS 和后端 Python 输出一致 |
| **实时序列持久化** | 页面刷新后 tick 序列清零，需重新积累 22+ 点 | 后端为每品种维护一个环形缓冲（最近 N 点），初次加载时回灌 |
| **品种详情页参数继承** | detail.js 中对新品种用 hardcoded default，未从 config 动态获取 | config 支持按 instrument id（如 cu0、rb0）设置品种参数，detail.js 统一走 `getMomentumThresholds(id)` |
| **单元测试** | 后端有 `test_momentum_strategy.py`，前端无 | 用 Node.js 或 jest 为前端 `calcMomentum`/`bollingerAt` 补充单测 |

### 7.5 UI/UX

| 方向 | 现状 | 建议 |
|---|---|---|
| **信号历史** | 仅展示当前信号，无历史记录 | 增加信号变化日志/时间线，便于复盘 |
| **多品种信号仪表盘** | 需逐个点入详情页查看 | 在全品类看板上直接显示每个品种的当前信号徽章 |
| **图表叠加均线** | 实时走势图仅显示价格线 | 在走势图上叠加 EMA 短/长线和 BB 上下轨，直观展示策略视角 |
| **回测参数联动** | 策略页参数与监控页独立 | 从监控页信号卡片可一键跳转回测页，自动填入当前品种和参数 |

---

## 8. 文件索引

| 文件 | 职责 |
|---|---|
| `backend/strategies/momentum.py` | 核心算法：`MomentumParams`、`ema_series`、`bollinger_at`、`_fuse_with_bb`、`calc_momentum` |
| `backend/backtest.py` | 回测引擎：历史加载、增量 EMA/BB、long-only 回测循环、绩效计算 |
| `backend/sources.py` | 历史数据获取：专用 + 通用（`fetch_generic_domestic_history` / `fetch_generic_intl_history`） |
| `assets/js/monitor/momentum.js` | 前端动量：`ema`、`bollingerAt`、`calcMomentum`、`renderSignal`、提示音 |
| `assets/js/monitor/detail.js` | 品种详情页：`_updateMomentum()` — 复用 `calcMomentum` + `renderSignal` |
| `assets/js/monitor/core.js` | 配置加载：`applyRuntimeConfig` → `momentumThresholds` / `momentumPeriods` |
| `assets/js/monitor/strategy.js` | 回测页前端：参数收集、品种选择、结果渲染 |
| `monitor.config.json` | 统一配置：品种参数、EMA 周期、BB 参数 |
| `tests/test_momentum_strategy.py` | 后端单测：EMA、信号判定、BB 融合 |

---

## 9. 维护检查清单

修改动量策略时，确保同步以下位置：

- [ ] `monitor.config.json` → `momentum` 段
- [ ] `backend/strategies/momentum.py` → `MomentumParams` 默认值
- [ ] `assets/js/monitor/core.js` → `defaultConfig.momentum` 硬编码兜底
- [ ] `assets/js/monitor/momentum.js` → 如改公式需同步
- [ ] `assets/js/monitor/detail.js` → `_updateMomentum()` 中的 hardcoded defaults
- [ ] `backend/backtest.py` → `momentum_params_from_body()` 参数解析
- [ ] `tests/test_momentum_strategy.py` → 单测断言
- [ ] 本文档
