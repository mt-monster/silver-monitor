"""动量策略核心与前端 momentum.js 数值对齐（固定序列）。"""

import math
import unittest

from backend.strategies.momentum import (
    MomentumParams,
    _apply_signal_cooldown,
    _fuse_with_bb,
    _fuse_with_volume,
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


class SignalCooldownTestCase(unittest.TestCase):
    """测试实时信号 cooldown 逻辑。"""

    def test_neutral_to_buy_triggers_cooldown(self):
        sig, cd, updated = _apply_signal_cooldown("buy", "neutral", 0, 2)
        self.assertEqual(sig, "buy")
        self.assertEqual(cd, 2)
        self.assertTrue(updated)

    def test_sustained_buy_during_cooldown(self):
        sig, cd, updated = _apply_signal_cooldown("buy", "buy", 2, 2)
        self.assertEqual(sig, "buy")
        self.assertEqual(cd, 1)
        self.assertTrue(updated)

    def test_strong_buy_same_direction_during_cooldown(self):
        sig, cd, updated = _apply_signal_cooldown("strong_buy", "buy", 2, 2)
        self.assertEqual(sig, "strong_buy")
        self.assertEqual(cd, 1)
        self.assertTrue(updated)

    def test_reversal_during_cooldown_suppressed(self):
        sig, cd, updated = _apply_signal_cooldown("sell", "buy", 2, 2)
        self.assertEqual(sig, "neutral")
        self.assertEqual(cd, 1)
        self.assertFalse(updated)

    def test_neutral_after_buy_during_cooldown_allowed(self):
        sig, cd, updated = _apply_signal_cooldown("neutral", "buy", 2, 2)
        self.assertEqual(sig, "neutral")
        self.assertEqual(cd, 1)
        self.assertFalse(updated)

    def test_cooldown_expires_then_reverse_allowed(self):
        sig, cd, updated = _apply_signal_cooldown("sell", "buy", 0, 2)
        self.assertEqual(sig, "sell")
        self.assertEqual(cd, 2)
        self.assertTrue(updated)

    def test_continuous_neutral_no_cooldown(self):
        sig, cd, updated = _apply_signal_cooldown("neutral", "neutral", 0, 2)
        self.assertEqual(sig, "neutral")
        self.assertEqual(cd, 0)
        self.assertFalse(updated)

    def test_cooldown_counts_down_each_bar(self):
        _, cd1, _ = _apply_signal_cooldown("buy", "buy", 3, 2)
        self.assertEqual(cd1, 2)
        _, cd2, _ = _apply_signal_cooldown("buy", "buy", 2, 2)
        self.assertEqual(cd2, 1)
        _, cd3, _ = _apply_signal_cooldown("buy", "buy", 1, 2)
        self.assertEqual(cd3, 0)


class VolumeFusionTestCase(unittest.TestCase):
    """测试成交量确认/降级逻辑。"""

    def test_fuse_volume_strong_buy_shrinks_to_buy(self):
        """强多 + 缩量 → 降级为 buy。"""
        self.assertEqual(_fuse_with_volume("strong_buy", 0.4, 1.5, 0.6), "buy")

    def test_fuse_volume_buy_shrinks_to_neutral(self):
        """buy + 缩量 → 降级为 neutral。"""
        self.assertEqual(_fuse_with_volume("buy", 0.4, 1.5, 0.6), "neutral")

    def test_fuse_volume_buy_expands_to_strong_buy(self):
        """buy + 放量 → 升级为 strong_buy。"""
        self.assertEqual(_fuse_with_volume("buy", 2.0, 1.5, 0.6), "strong_buy")

    def test_fuse_volume_strong_sell_shrinks_to_sell(self):
        """强空 + 缩量 → 降级为 sell。"""
        self.assertEqual(_fuse_with_volume("strong_sell", 0.4, 1.5, 0.6), "sell")

    def test_fuse_volume_sell_shrinks_to_neutral(self):
        """sell + 缩量 → 降级为 neutral。"""
        self.assertEqual(_fuse_with_volume("sell", 0.4, 1.5, 0.6), "neutral")

    def test_fuse_volume_sell_expands_to_strong_sell(self):
        """sell + 放量 → 升级为 strong_sell。"""
        self.assertEqual(_fuse_with_volume("sell", 2.0, 1.5, 0.6), "strong_sell")

    def test_fuse_volume_neutral_unchanged(self):
        """neutral 不受成交量影响。"""
        self.assertEqual(_fuse_with_volume("neutral", 2.0, 1.5, 0.6), "neutral")

    def test_calc_momentum_with_volume_confirm(self):
        """提供放量成交量序列，buy 应升级为 strong_buy。"""
        base = 10000.0
        vals = [base + i * 80.0 for i in range(50)]
        volumes = [100.0] * 49 + [300.0]  # 最后一根放量 3 倍
        info = calc_momentum(vals, MomentumParams(
            volume_period=10, volume_confirm_ratio=1.5, volume_weaken_ratio=0.6
        ), volumes=volumes)
        self.assertIsNotNone(info)
        self.assertIn("volumeRatio", info)
        self.assertGreater(info["volumeRatio"], 1.5)
        self.assertEqual(info["signal"], "strong_buy")

    def test_calc_momentum_with_volume_weaken(self):
        """提供缩量成交量序列，strong_buy 应降级为 buy。"""
        base = 10000.0
        vals = [base + i * 80.0 for i in range(50)]
        volumes = [100.0] * 49 + [10.0]  # 最后一根大幅缩量
        info = calc_momentum(vals, MomentumParams(
            volume_period=10, volume_confirm_ratio=1.5, volume_weaken_ratio=0.6
        ), volumes=volumes)
        self.assertIsNotNone(info)
        self.assertIn("volumeRatio", info)
        self.assertLess(info["volumeRatio"], 0.6)
        self.assertEqual(info["signal"], "buy")


class SqueezeBreakoutTestCase(unittest.TestCase):
    """测试 Squeeze Breakout 突破逻辑。"""

    def test_squeeze_breakout_upgrades_buy_to_strong_buy(self):
        """前一根缩口 + 当前扩张 + buy 信号 → strong_buy。"""
        # 60 根横盘（制造缩口），然后 1 根突破
        vals = [100.0] * 60 + [105.0]
        info = calc_momentum(vals, MomentumParams(
            short_p=10, long_p=20, spread_entry=0.05, slope_entry=0.01,
            bb_period=20, bb_mult=2.0
        ))
        self.assertIsNotNone(info)
        self.assertIn("bb", info)
        self.assertTrue(info["bb"]["squeezeBreak"])
        self.assertEqual(info["signal"], "strong_buy")

    def test_squeeze_breakout_no_signal_when_not_expanding(self):
        """前一根缩口但不扩张 → 无 breakout。"""
        # 61 根横盘（持续缩口）
        vals = [100.0] * 61
        info = calc_momentum(vals, MomentumParams(
            short_p=10, long_p=20, bb_period=20, bb_mult=2.0
        ))
        self.assertIsNotNone(info)
        self.assertIn("bb", info)
        self.assertFalse(info["bb"]["squeezeBreak"])

    def test_squeeze_breakout_field_present(self):
        """BB 启用时结果应包含 squeezeBreak 字段。"""
        vals = [100.0 + i * 2.0 for i in range(50)]
        info = calc_momentum(vals, MomentumParams(bb_period=20, bb_mult=2.0))
        self.assertIsNotNone(info)
        self.assertIn("bb", info)
        self.assertIn("squeezeBreak", info["bb"])


class VolatilityFilterTestCase(unittest.TestCase):
    """测试波动率过滤逻辑。"""

    def test_high_volatility_signal_preserved(self):
        base = 10000.0
        # 50 根 bar，每根波动约 0.5%，CV 足够高
        vals = [base + i * 50.0 + (i % 3) * 30.0 for i in range(50)]
        info = calc_momentum(vals, MomentumParams(
            spread_entry=0.001, slope_entry=0.001,
            min_volatility_pct=0.02, bb_period=10
        ))
        self.assertIsNotNone(info)
        self.assertIn("volatilityPct", info)
        self.assertGreater(info["volatilityPct"], 0.02)
        self.assertIn(info["signal"], ("buy", "strong_buy"))

    def test_low_volatility_signal_suppressed(self):
        base = 10000.0
        # 前 40 根横盘，后 10 根急涨：能产生 strong_buy 但整体 CV 很低（约 0.25%）
        vals = [base] * 40 + [base + i * 10 for i in range(1, 11)]

        # 无过滤时应产生 strong_buy
        info_no_filter = calc_momentum(vals, MomentumParams(
            spread_entry=0.001, slope_entry=0.001,
            min_volatility_pct=0.0, bb_period=10
        ))
        self.assertIsNotNone(info_no_filter)
        self.assertIn(info_no_filter["signal"], ("buy", "strong_buy"))

        # 开启波动率过滤后应被降级为 neutral
        info_filtered = calc_momentum(vals, MomentumParams(
            spread_entry=0.001, slope_entry=0.001,
            min_volatility_pct=0.30, bb_period=10
        ))
        self.assertIsNotNone(info_filtered)
        self.assertIn("volatilityPct", info_filtered)
        self.assertLess(info_filtered["volatilityPct"], 0.30)
        self.assertEqual(info_filtered["signal"], "neutral")

    def test_volatility_filter_disabled_by_default(self):
        base = 10000.0
        vals = [base + i * 0.01 for i in range(50)]
        info = calc_momentum(vals, MomentumParams(
            spread_entry=0.001, slope_entry=0.001
        ))
        self.assertIsNotNone(info)
        self.assertNotIn("volatilityPct", info)


if __name__ == "__main__":
    unittest.main()
