"""动量策略核心与前端 momentum.js 数值对齐（固定序列）。"""

import unittest

from backend.strategies.momentum import MomentumParams, calc_momentum, ema_series


class MomentumCoreTestCase(unittest.TestCase):
    def test_ema_matches_manual_two_steps(self):
        values = [100.0, 110.0]
        period = 10
        k = 2.0 / (period + 1)
        ema = ema_series(values, period)
        self.assertEqual(len(ema), 2)
        self.assertEqual(ema[0], 100.0)
        self.assertAlmostEqual(ema[1], 110.0 * k + 100.0 * (1 - k))

    def test_calc_momentum_insufficient_length_returns_none(self):
        vals = [100.0] * 21
        self.assertIsNone(calc_momentum(vals))

    def test_flat_series_neutral(self):
        vals = [100.0] * 50
        info = calc_momentum(vals)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "neutral")
        self.assertAlmostEqual(info["spreadPct"], 0.0, places=6)

    def test_golden_last_bar_strong_uptrend(self):
        """单调大幅上涨：快慢线多头、张口与短线斜率同向应触发强多。"""
        base = 10000.0
        vals = [base + i * 80.0 for i in range(50)]
        info = calc_momentum(vals)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "strong_buy")
        self.assertGreater(info["spreadPct"], 0.35)
        self.assertGreater(info["slopePct"], 0.02)

    def test_custom_thresholds_weaker_entry(self):
        """缓涨：默认张口/斜率不足；放宽后应出现多仓信号。"""
        base = 10000.0
        vals = [base + i * 0.45 for i in range(50)]
        default = calc_momentum(vals)
        self.assertIsNotNone(default)
        self.assertEqual(default["signal"], "neutral")
        loose = calc_momentum(
            vals,
            MomentumParams(spread_entry=0.01, spread_strong=0.05, slope_entry=0.001),
        )
        self.assertIsNotNone(loose)
        self.assertIn(loose["signal"], ("buy", "strong_buy"))


if __name__ == "__main__":
    unittest.main()
