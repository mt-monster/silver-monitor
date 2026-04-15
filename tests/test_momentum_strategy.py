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

    def test_ema_sma_seed_reduces_initial_bias(self):
        """SMA seed: 前 period 个值取平均作为种子，种子期之前为 None。"""
        values = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0]
        period = 5
        ema = ema_series(values, period)
        self.assertEqual(len(ema), 6)
        for i in range(period - 1):
            self.assertIsNone(ema[i])
        expected_seed = sum(values[:period]) / period
        self.assertAlmostEqual(ema[period - 1], expected_seed)
        k = 2.0 / (period + 1)
        self.assertAlmostEqual(ema[5], values[5] * k + expected_seed * (1 - k))

    def test_strength_multiplier_configurable(self):
        """strength_multiplier 影响信号强度条。"""
        base = 10000.0
        vals = [base + i * 3.0 for i in range(50)]
        hi_info = calc_momentum(vals, MomentumParams(spread_entry=0.001, slope_entry=0.001, strength_multiplier=200.0))
        lo_info = calc_momentum(vals, MomentumParams(spread_entry=0.001, slope_entry=0.001, strength_multiplier=50.0))
        self.assertIsNotNone(hi_info)
        self.assertIsNotNone(lo_info)
        self.assertGreater(hi_info["strength"], lo_info["strength"])

    def test_downtrend_sell_signal(self):
        """单调下跌应触发 strong_sell。"""
        base = 10000.0
        vals = [base - i * 80.0 for i in range(50)]
        info = calc_momentum(vals)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "strong_sell")
        self.assertLess(info["spreadPct"], -0.35)
        self.assertLess(info["slopePct"], -0.02)


if __name__ == "__main__":
    unittest.main()
