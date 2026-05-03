# COMEX 银 Tick 实盘验证策略

本文记录 `backend/strategies/xag_live.py` 新增的 COMEX 银 tick 策略。它读取 `data/ticks.db` 中 `instrument_id = "xag"` 的行情，用于实盘纸交易验证和 walk-forward 回测。

## 数据清洗

策略会先过滤两类异常 tick：

| 规则 | 说明 |
|------|------|
| `timestamp_ms >= 1_500_000_000_000` | 排除测试写入的 `1000000` 时间戳脏点 |
| `50 <= price <= 100` | 排除 `30.0` 等明显非当前 XAG 区间的测试价格 |

## 信号逻辑

策略每次只使用当前 tick 之前已经发生的数据，不使用未来数据。

| 模式 | 条件 | 动作 |
|------|------|------|
| 均值回归 | 方差比 `VR <= mean_reversion_vr`，且价格 z-score 超过 `z_entry` | 高位做空，低位做多 |
| 趋势突破 | `VR >= breakout_vr`，短趋势收益超过阈值，且突破最近通道 | 向突破方向开仓 |

开仓后由风控状态机平仓：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `stop_loss_pct` | `0.10` | 单笔止损百分比 |
| `take_profit_pct` | `0.18` | 单笔止盈百分比 |
| `trailing_trigger_pct` | `0.08` | 移动止盈启动阈值 |
| `trailing_retrace_pct` | `0.035` | 从最大浮盈回撤后的移动止盈阈值 |
| `max_hold_ticks` | `90` | 最长持仓 tick 数 |
| `cooldown_ticks` | `12` | 平仓后的冷却 tick 数 |

## 验证方式

运行：

```powershell
python tests/_run_xag_live_strategy.py
```

脚本会输出：

- 每个有效日期的固定参数纸交易结果；
- `day[t]` 训练、`day[t+1]` 验证的 walk-forward OOS 汇总；
- 详细 JSON 报告 `backtest_xag_live_strategy.json`。

批量验证为了控制耗时，使用 `signal_step=5`，即每 5 个 tick 评估一次新开仓信号；持仓后的止损、止盈、移动止盈仍按每个 tick 检查。实盘接入时可使用默认 `signal_step=1` 做逐 tick 信号判断。

截至当前 `data/ticks.db` 样本，脚本验证结果为：

| 项目 | 结果 |
|------|------|
| 有效日期 | `2026-04-23`、`2026-04-24`、`2026-04-25`、`2026-04-27`、`2026-04-28` |
| Walk-forward OOS 交易数 | `472` |
| Walk-forward OOS 胜率 | `46.82%` |
| Walk-forward OOS Profit Factor | `0.80` |
| Walk-forward OOS 总收益 | `-4.2852%` |

结论：当前样本不支持“高收益策略”结论，该策略应先作为实盘纸交易验证框架继续观察。

## 使用边界

该策略用于实盘纸交易验证，不承诺稳定收益。当前 tick 样本只有少数交易日，任何高收益结果都必须优先视为待验证假设。实盘前至少应满足：

- 连续 2-4 周 OOS `totalReturnPct > 0`；
- OOS `profitFactor >= 1.2`；
- 单日最大回撤低于可承受阈值；
- 扣除真实手续费、滑点后仍为正。
