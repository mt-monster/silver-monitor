"""COMEX 银 tick 实盘验证策略测试。"""

import unittest

from backend.strategies.xag_live import (
    XAGLiveParams,
    calc_xag_live_signal,
    clean_xag_ticks,
    simulate_xag_live_strategy,
)


def _ticks_from_prices(prices, start=1_777_000_000_000):
    return [{"t": start + i * 1000, "y": float(p)} for i, p in enumerate(prices)]


class XAGLiveStrategyTestCase(unittest.TestCase):

    def test_clean_xag_ticks_filters_dirty_seed_rows(self):
        """过滤测试脏点：时间戳过早、价格异常、无法转数值。"""
        ticks = [
            {"t": 1_000_000, "y": 30.0},
            {"t": 1_777_000_000_000, "y": 76.1},
            {"t": 1_777_000_001_000, "y": 5.0},
            {"t": 1_777_000_002_000, "y": "bad"},
        ]
        clean = clean_xag_ticks(ticks)
        self.assertEqual(len(clean), 1)
        self.assertEqual(clean[0]["y"], 76.1)

    def test_mean_reversion_signal_after_upper_extreme(self):
        """横盘均值回归状态下，价格上偏离应触发做空信号。"""
        prices = [76.0 + (0.01 if i % 2 else -0.01) for i in range(180)]
        prices.extend([76.02, 76.04, 76.20])
        params = XAGLiveParams(
            min_ticks=120,
            mean_window=60,
            channel_window=100,
            vr_window=100,
            z_entry=1.8,
            mean_reversion_vr=1.2,
            breakout_vr=2.0,
        )
        signal = calc_xag_live_signal(_ticks_from_prices(prices), params)
        self.assertEqual(signal["signal"], "sell")
        self.assertEqual(signal["direction"], "short")
        self.assertEqual(signal["regime"], "mean_reversion")

    def test_simulation_closes_with_risk_rule(self):
        """纸交易模拟应在止盈/止损/时间止损之一触发时平仓。"""
        prices = [76.0 + (0.01 if i % 2 else -0.01) for i in range(180)]
        prices.extend([76.2, 76.16, 76.12, 76.06, 76.0, 75.98])
        params = XAGLiveParams(
            min_ticks=120,
            mean_window=60,
            channel_window=100,
            vr_window=100,
            z_entry=1.8,
            mean_reversion_vr=1.2,
            breakout_vr=2.0,
            take_profit_pct=0.08,
            stop_loss_pct=0.08,
            max_hold_ticks=20,
        )
        result = simulate_xag_live_strategy(_ticks_from_prices(prices), params, round_trip_cost_pct=0.0)
        self.assertGreaterEqual(result["metrics"]["tradeCount"], 1)
        self.assertIn(result["trades"][0]["reason"], {"take_profit", "stop_loss", "time_stop", "close"})


if __name__ == "__main__":
    unittest.main()
