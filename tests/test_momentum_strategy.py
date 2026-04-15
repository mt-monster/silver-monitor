"""动量策略核心与前端 momentum.js 数值对齐（固定序列）。"""

import math
import unittest

from backend.strategies.momentum import (
    MomentumParams,
    _fuse_with_bb,
    bollinger_at,
    calc_momentum,
    ema_series,
)


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


class BollingerBandTestCase(unittest.TestCase):
    def test_bollinger_flat_series(self):
        """恒定价格 → 标准差为 0, %B=0.5, bandwidth=0。"""
        vals = [100.0] * 30
        bb = bollinger_at(vals, 20, 2.0)
        self.assertIsNotNone(bb)
        self.assertAlmostEqual(bb["middle"], 100.0)
        self.assertAlmostEqual(bb["upper"], 100.0)
        self.assertAlmostEqual(bb["lower"], 100.0)
        self.assertAlmostEqual(bb["percentB"], 0.5)
        self.assertAlmostEqual(bb["bandwidth"], 0.0)

    def test_bollinger_known_values(self):
        """已知序列验证 BB 计算正确性。"""
        vals = list(range(1, 21))  # 1..20
        bb = bollinger_at([float(v) for v in vals], 20, 2.0)
        self.assertIsNotNone(bb)
        expected_sma = sum(vals) / 20.0
        self.assertAlmostEqual(bb["middle"], expected_sma)
        var = sum((x - expected_sma) ** 2 for x in vals) / 20.0
        expected_std = math.sqrt(var)
        self.assertAlmostEqual(bb["upper"], expected_sma + 2 * expected_std)
        self.assertAlmostEqual(bb["lower"], expected_sma - 2 * expected_std)

    def test_bollinger_insufficient_data(self):
        """数据不足 → 返回 None。"""
        self.assertIsNone(bollinger_at([1.0, 2.0, 3.0], 20, 2.0))

    def test_bollinger_percent_b_above_upper(self):
        """价格远高于上轨 → %B > 1。"""
        vals = [100.0] * 19 + [200.0]
        bb = bollinger_at(vals, 20, 2.0)
        self.assertIsNotNone(bb)
        self.assertGreater(bb["percentB"], 1.0)


class FuseWithBBTestCase(unittest.TestCase):
    def test_buy_near_lower_band_downgraded(self):
        """%B < 0.3 时 buy → neutral。"""
        self.assertEqual(_fuse_with_bb("buy", 0.2, False), "neutral")

    def test_buy_above_mid_expanding_upgraded(self):
        """%B > 0.5 + 扩张 → strong_buy。"""
        self.assertEqual(_fuse_with_bb("buy", 0.7, True), "strong_buy")

    def test_buy_above_mid_not_expanding_stays(self):
        """%B > 0.5 但不扩张 → 保持 buy。"""
        self.assertEqual(_fuse_with_bb("buy", 0.7, False), "buy")

    def test_strong_buy_overbought_downgraded(self):
        """%B > 1.0 → strong_buy 降为 buy。"""
        self.assertEqual(_fuse_with_bb("strong_buy", 1.1, True), "buy")

    def test_sell_near_upper_band_downgraded(self):
        """%B > 0.7 时 sell → neutral。"""
        self.assertEqual(_fuse_with_bb("sell", 0.8, False), "neutral")

    def test_sell_below_mid_expanding_upgraded(self):
        """%B < 0.5 + 扩张 → strong_sell。"""
        self.assertEqual(_fuse_with_bb("sell", 0.3, True), "strong_sell")

    def test_strong_sell_oversold_downgraded(self):
        """%B < 0.0 → strong_sell 降为 sell。"""
        self.assertEqual(_fuse_with_bb("strong_sell", -0.1, True), "sell")

    def test_neutral_unchanged(self):
        """neutral 不受 BB 影响。"""
        self.assertEqual(_fuse_with_bb("neutral", 0.5, True), "neutral")


class CalcMomentumWithBBTestCase(unittest.TestCase):
    def test_result_contains_bb_field(self):
        """启用 BB 时结果应包含 bb 字段。"""
        vals = [100.0 + i * 2.0 for i in range(50)]
        info = calc_momentum(vals, MomentumParams(bb_period=20, bb_mult=2.0))
        self.assertIsNotNone(info)
        self.assertIn("bb", info)
        bb = info["bb"]
        self.assertIn("percentB", bb)
        self.assertIn("bandwidth", bb)
        self.assertIn("bwExpanding", bb)
        self.assertIn("squeeze", bb)

    def test_bb_disabled_no_bb_field(self):
        """bb_period=0 时结果不含 bb 字段。"""
        vals = [100.0 + i * 2.0 for i in range(50)]
        info = calc_momentum(vals, MomentumParams(bb_period=0))
        self.assertIsNotNone(info)
        self.assertNotIn("bb", info)

    def test_bb_fusion_changes_signal(self):
        """BB 融合应能修正原始 EMA 信号。"""
        base = 10000.0
        vals = [base + i * 80.0 for i in range(50)]
        no_bb = calc_momentum(vals, MomentumParams(bb_period=0))
        with_bb = calc_momentum(vals, MomentumParams(bb_period=20, bb_mult=2.0))
        self.assertIsNotNone(no_bb)
        self.assertIsNotNone(with_bb)
        self.assertIn(no_bb["signal"], ("strong_buy", "buy"))
        self.assertIn(with_bb["signal"], ("strong_buy", "buy", "neutral"))


if __name__ == "__main__":
    unittest.main()
