# 动量信号策略说明

本文档描述 Web 监控页中「沪银 / COMEX 银 / 沪金 / COMEX 金」动量卡片的计算逻辑。实现位于前端 `assets/js/monitor/momentum.js`，**服务端不参与**实时监控的动量计算（回测在服务端使用同源公式，见文末）。

## 数据流与调用时机

1. `Monitor.fetchData()` 成功拉取 `GET /api/all` 后，依次调用：
   - `Monitor.updateMomentumSignals(data)`：沪银（`huyin`）、COMEX 银（`comex`）
   - `Monitor.updateGoldMomentumSignals(data)`：沪金（`hujin`）、COMEX 金（`comexGold`）
2. 若请求失败，本轮不会更新动量序列，界面保持上次状态。

## 价格序列（采样规则）

对每个品种，仅在同时满足以下条件时，向该品种的序列末尾追加一个采样点 `{ t, y }`：

- 行情对象存在且无 `error`
- `closed !== true`（视为交易/可报价时段）
- `price > 0`

- **时间戳 `t`**：优先使用接口返回的 `timestamp`（毫秒），否则为 `Date.now()`。
- **价格 `y`**：使用接口返回的 `price`（各市场自有单位，沪银/沪金与 COMEX 系列分别独立成序列，不做跨市换算）。

序列长度上限为 **180**。超出时丢弃最旧点（银：`push` + `shift`；金：`slice(-180)`）。

## 计算前提：最少样本数

动量计算使用 **EMA 短**、**EMA 长** 与 **短 EMA 一步斜率**（见下），要求序列长度：

\[
\text{minLen} = \text{longP} + 2
\]

默认 `shortP = 5`，`longP = 20`，故 **minLen = 22**。不足时 `calcMomentum` 返回 `null`，界面显示「等待」及提示「需至少 22 个有效价格点后计算」（文案随 `longP` 变化）。

周期与阈值来自 [monitor.config.json](../monitor.config.json) 的 `momentum` 段，经 `core.js` 写入 `Monitor.momentumPeriods` / `Monitor.momentumThresholds`。

## 指数移动平均（EMA）

对价格序列 \(y_0,\ldots,y_{n-1}\)，周期 \(N\) 的 EMA：

- 平滑系数：\(k = \dfrac{2}{N+1}\)
- 初值：\(\text{EMA}_0 = y_0\)
- 递推：\(\text{EMA}_i = y_i \cdot k + \text{EMA}_{i-1} \cdot (1-k)\)

记最后一根短、长均线为 \(\text{EMA}_S,\ \text{EMA}_L\)（默认即 EMA5、EMA20 的末值）。

## 指标定义

### 动量差（spreadPct）

快慢线相对张口（百分比）：

\[
\text{spreadPct} = \frac{\text{EMA}_S - \text{EMA}_L}{\text{EMA}_L} \times 100
\]

（`EMA_L = 0` 时按 0 处理。）

### 短线斜率（slopePct）

**短 EMA** 相邻两个采样点之间的相对涨跌幅（百分比），**参与多空判定**，并在卡片第一行展示：

\[
\text{slopePct} = \frac{\text{EMA}_S^{(\text{末})} - \text{EMA}_S^{(\text{倒数第二})}}{\text{EMA}_S^{(\text{倒数第二})}} \times 100
\]

（分母为 0 时按 0 处理。）

### 强度（strength）

用于进度条宽度（0～100）：

\[
\text{strength} = \min\bigl(100,\ |\text{spreadPct}| \times 120\bigr)
\]

## 多空信号判定

- **多头结构**：\(\text{EMA}_S > \text{EMA}_L\) 且 `spreadPct > spreadEntry` 且 `slopePct > slopeEntry`。
- **空头结构**：\(\text{EMA}_S < \text{EMA}_L\) 且 `spreadPct < -spreadEntry` 且 `slopePct < -slopeEntry`。

**强多 / 强空**仅由张口是否越过 `spread_strong` 决定（与首版逻辑一致），**不再使用 ROC**：

| 结果标签（内部 key） | 中文 | 条件（默认阈值） |
|---------------------|------|------------------|
| `strong_buy` | 强多 | 满足多头结构 + `spreadPct > spread_strong`（0.35） |
| `buy` | 做多 | 满足多头结构 + `spreadPct ≤ spread_strong` |
| `strong_sell` | 强空 | 满足空头结构 + `spreadPct < -spread_strong` |
| `sell` | 做空 | 满足空头结构 + `spreadPct ≥ -spread_strong` |
| `neutral` | 观望 | 其余情况 |

`spread_entry` / `spread_strong` / `slope_entry` 单位为**百分比点**（例如 `0.10` 表示 0.10%）。**默认与周期参数**来自 [monitor.config.json](../monitor.config.json) 的 `momentum` 段：`core.js` 在 `loadRuntimeConfig` 后写入 `Monitor.momentumThresholds` / `Monitor.momentumPeriods`；Python 在进程启动时读入同一文件，`momentum_params_from_body` 以该段为缺省、请求体 `params` 可覆盖（见 [strategy-backtest.md](strategy-backtest.md)）。修改配置后需**刷新监控页**；**重启 HTTP 服务**后回测缺省才会更新。

## 提示音

当某品种计算出的 `signal` 与上一次不同时，若 `localStorage.signalSound !== "off"`，则对 **`strong_buy` / `strong_sell`** 播放短促提示音（浏览器需允许音频上下文）。

## 与界面元素的对应关系

- **徽章**：`signal` → `strong_buy` / `buy` / `neutral` / `sell` / `strong_sell` 对应中文标签。
- **短线斜率**：`slopePct`（首行数值）。
- **EMA短 / EMA 长**：`shortEMA` / `longEMA`（末值），标签为「EMA{shortP}」「EMA{longP}」；小数位按品种：银沪 1、金 2、COMEX 银 3、COMEX 金 2。
- **备注行**：仅展示动量差 `spreadPct`（文案为「动量差 ±x.xxx%」）。
- **强度条**：`strength`。
- **卡片标题小字**：`EMA{shortP}/{longP}（张口+短线斜率）`（由 `refreshMomentumLabels` 更新）。
- **「实时」**：有有效 `info` 时由脚本写入，表示本轮已用最新序列算过。

## 回测与实时差异

- **实现位置**：实时监控在 [assets/js/monitor/momentum.js](assets/js/monitor/momentum.js)；回测使用服务端 [backend/strategies/momentum.py](backend/strategies/momentum.py) 与 [backend/backtest.py](backend/backtest.py)，公式与默认阈值一致，回测请求中可覆盖 `params`（见 [docs/strategy-backtest.md](strategy-backtest.md)）。
- **数据频率**：回测 K 线来自 AkShare（沪银/沪金多为 **60 分钟**最近约 200 根；COMEX 银/金多为 **日线** 最近约 60 根），不是监控页上按 `poll_ms` 累积的 tick 序列。
- **信号时点**：回测在每根 bar **收盘**后，用「从首根到当前根」的收盘价序列计算信号，并按该收盘价执行 long-only 调仓；实时监控则在每次轮询成功时用当前价追加一点后计算。
- **成本模型**：当前回测 **不计手续费与滑点**；绩效中的年化按首尾时间线性外推，仅供参考。
- **COMEX 样本较短**：日线约两个月窗口，仅适合演示策略管线，不宜单独作为实盘依据。

## 维护注意

- 修改 `shortP`、`longP` 或 `minLen` 时，需同步更新页面提示文案中的「最少点数」、回测默认参数与本文档。
- 若调整默认阈值或 EMA 周期，优先改 `monitor.config.json` 的 `momentum`，并同步 `backend/config.py` 内 `DEFAULT_CONFIG["momentum"]`（供无配置文件或测试兜底）、`assets/js/monitor/core.js` 中 `defaultConfig.momentum` 及本文档表格。
