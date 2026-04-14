# 策略回测 API 与界面

## 页面

- 静态页 [strategy.html](../strategy.html)（与 [index.html](../index.html) 顶部互相链接）。
- 脚本 [assets/js/monitor/strategy.js](../assets/js/monitor/strategy.js)：`POST /api/backtest` 并渲染权益曲线（Chart.js + 时间轴）、绩效卡片与成交表。

## HTTP

### `POST /api/backtest`

- **Content-Type**: `application/json`
- **Body字段**

| 字段 | 类型 | 说明 |
|------|------|------|
| `strategy` | string | 仅支持 `momentum` |
| `symbol` | string | `huyin` / `comex` / `hujin` / `comex_gold` |
| `mode` | string | 仅支持 `long_only` |
| `params` | object | 可选，见下表 |

**`params`（均可选，缺省与 `MomentumParams` / `monitor.config.json` 的 `momentum` 一致）**

| 键 | 默认 | 含义 |
|----|------|------|
| `short_p` | 5 | 短 EMA 周期 |
| `long_p` | 20 | 长 EMA 周期 |
| `spread_entry` | 0.10 | 张口门槛（%），与多头/空头结构联立 |
| `spread_strong` | 0.35 | 强多/强空张口（%）；强信号仅看张口是否越过本阈值 |
| `slope_entry` | 0.02 | 短 EMA 一步涨跌幅门槛（%），与张口同向确认 |

动量判定为 **EMA 短/长张口 + 短 EMA 斜率**，不使用 ROC。详见 [momentum-strategy.md](momentum-strategy.md)。

上述默认值与 [monitor.config.json](../monitor.config.json) 中 `momentum` 一致；服务端在启动时加载，**改文件后需重启 HTTP 进程**方影响未带 `params` 的回测请求。监控面板从同一 JSON 拉取（无需重启浏览器进程，刷新即可）。

- **成功 `200`**：`{ "ok": true, "meta": { ... }, "equity": [...], "trades": [...], "metrics": { ... } }`
  - `meta`：`symbol`, `strategy`, `mode`, `interval`（`60m` 或 `1d`）, `bars`, `from` / `to`（CST 字符串）, `fromMs` / `toMs`, `costModel`（`none`）
  - `equity`：`\{ t, equity, price \}`，t 为毫秒时间戳
  - `trades`：`action` 为 `buy` / `sell`，含 `t`, `price`, `signal`
  - `metrics`：`totalReturnPct`, `maxDrawdownPct`, `sharpeRatio`（年化夏普，无风险利率=0；权益逐期简单收益，样本方差为 0 时为 null）, `sellCount`, `roundTripCount`, `winRatePct`（可能为 null）, `annualizedReturnPct`（可能为 null）, `bars`, `note`

- **`400`**：`{ "ok": false, "error": "..." }`（未知策略、非法 symbol、不支持 mode 等）

- **`503`**：`{ "ok": false, "error": "akshare_not_available" | "no_history" }`（未安装 AkShare 或拉取历史失败）

## 历史加载逻辑

见 [backend/backtest.py](../backend/backtest.py) 中 `load_history`：优先使用 `state.*_cache["data"]["history"]`（慢轮询已写入且不少于 50 根），否则调用对应 `fetch_*_history()`。

## 扩展

新增策略类型时：实现对应 `run_*_backtest`，在 `http_server._handle_backtest` 中按 `strategy` 分发，并在 `strategy.html` 下拉里增加选项。
