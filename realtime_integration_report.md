# MTF + 组合信号实时监控集成报告

## 结论

**是的，这个优化已经应用到 COMEX 白银（以及所有品种）的实时监控中。**

回测和实时监控使用的是**同一套信号计算管道**，核心逻辑完全一致。

---

## 实时监控数据流

```
FastDataPoller 每秒轮询
    │
    ├─→ _buffer_precious_prices()
    │       ├─→ instrument_price_buffers (30s bar，最多200根)
    │       └─→ realtime_backtest_buffers (1s bar，最多300根)
    │
    ├─→ _recompute_signals()         【动量信号】使用 1s bar
    ├─→ _recompute_reversal_signals() 【反转信号】使用 1s bar
    ├─→ _recompute_mtf_and_combined() 【← 新增】MTF趋势 + 组合信号
    │       ├─→ calc_mtf_from_buffer(30s bar) → 大局趋势 up/down/sideways
    │       └─→ calc_combined_signal(动量, 反转, MTF) → 最终决策
    │
    ├─→ rebuild_all_cache()
    └─→ SSE 推送 /api/all 返回
```

---

## 前端展示链路

| 数据源 | 组合信号更新 |
|--------|-------------|
| `/api/all` 轮询 | `Monitor._applyAllData()` → `updateCombinedSignals()` |
| SSE 实时推送 | `Monitor.sse.on("data")` → `_onSseData()` → `updateCombinedSignals()` |

---

## 已修复的问题

**修复：SSE 推送数据适配遗漏**

`_onSseData()` 函数中未将 `combinedSignals` 和 `mtfTrends` 从 SSE payload 传递到前端 data 对象，导致 SSE 模式下组合信号面板显示"等待"。

```javascript
// 修复前（缺失）
const data = {
  signals: payload.signals || {},
  reversalSignals: payload.reversalSignals || {},
};

// 修复后
const data = {
  signals: payload.signals || {},
  reversalSignals: payload.reversalSignals || {},
  combinedSignals: payload.combinedSignals || {},
  mtfTrends: payload.mtfTrends || {},
};
```

---

## 使用前提

**MTF 需要约 20 分钟预热时间**

- `instrument_price_buffers` 存储的是 **30s bar**（由 `frontend.bar_window_ms = 30000` 控制）
- MTF 计算需要至少 **40 根 30s bar**（约 20 分钟）
- 服务器重启后的前 20 分钟内，MTF 趋势显示为 `sideways`（数据不足），组合信号仍可用但不包含大局过滤

---

## 前端已新增的面板

在 `index.html` 的"反转信号"卡片下方，已插入**组合信号卡片**：

- 🔴 沪银组合信号 (MTF+动量+反转)
- 🟢 COMEX银组合信号 (MTF+动量+反转)

显示内容：
- 最终信号徽章（强多/做多/观望/做空/强空）
- MTF 大局趋势（偏多/偏空/横盘）
- 信号来源（动量 / 反转 / 共振）
- 建议仓位比例（0~100%）
- 决策理由文字

---

## 验证方法

启动服务器后，打开 `index.html` 监控面板：

1. **观察组合信号卡片**：应显示与动量/反转卡片联动的信号
2. **查看 MTF 趋势**：积累 20 分钟数据后，趋势会从 `sideways` 变为 `up` 或 `down`
3. **验证过滤效果**：在大局 `down` 时，反转策略的 `buy` 信号应被过滤为 `neutral`
4. **Network 面板**：`/api/all` 返回的 JSON 中应包含 `combinedSignals.xag` 和 `mtfTrends.xag`
