# 实证研究：沪银蒙特卡洛 API

## 页面

- [research.html](../research.html)：表单与直方图，导航与监控/策略页互通。

## 采样

- 快轮询在沪银有效价写入 [`backend/pollers.py`](../backend/pollers.py) 后调用 [`append_huyin_research_sample`](../backend/research/samples.py)，环形上限见 `monitor.config.json` → `research.huyin_sample_max`。
- 与跳价告警用的 `silver_tick_ring`（长度 5）独立。

## HTTP

### `GET /api/research/huyin`

返回 `sampleCount`、`closed`、`lastPrice`、`monteCarloDefaults`、`recentSamples`（最多 20 点）等。

### `POST /api/research/monte-carlo`

- **Body（JSON）**
  - `horizon_sec`：`1` 或 `5`
  - `model`：`gbm` | `bootstrap`
  - `drift`：`zero` | `estimated`
  - `window_minutes`：`5` … `10080`
  - `paths`：模拟条数（上限见配置 `monte_carlo_max_paths`）
  - `seed`（可选）：整数，便于复现
- **200**：`ok: true`，含 `percentiles`（Δ%）、`pricesPercentiles`、`priceMean`、`priceStdevLinApprox`、`histogram`、`pathChart`（`timeSec`、`paths` 为多条从 S0 到 horizon 的阶梯路径，用于前端折线图）、`probUp`、`warnings` 等。`path_preview_count` 为 0 时不返回 `pathChart`。
- **Body可选**：`path_preview_count`（0–60，0 关闭路径图）、`path_steps`（4–60，时间轴分段数），默认见 `research.path_preview_count` / `path_steps`。
- **400**：`ok: false`，`error` 为中文说明（如样本不足时会提示当前条数、建议等待时长或调低 `research.monte_carlo_min_returns`）。默认最少对数收益条数为 **15**（约 16 个快轮询价，按 `polling.fast_seconds` 估算等待时间）。

## 实现

- 核心逻辑：[`backend/research/monte_carlo.py`](../backend/research/monte_carlo.py)
- 修改默认阈值：配置 `research.*` 后**重启 HTTP 服务**；前端刷新即可读 `GET` 默认值。
