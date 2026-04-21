"""反转策略（reversal.py）单元测试。

覆盖 RSI 得分、BB 得分、EMA 偏离度、综合评分、信号阈值、边界条件。
"""

import unittest

from backend.strategies.reversal import (
    ReversalParams,
    calc_reversal,
)


class ReversalSignalTestCase(unittest.TestCase):
    """基础信号判定测试。"""

    def test_insufficient_length_returns_none(self):
        """数据不足时应返回 None。"""
        vals = [100.0] * 5
        self.assertIsNone(calc_reversal(vals))

    def test_flat_series_neutral(self):
        """近乎恒定的价格序列应返回 neutral。"""
        # 使用极小震荡序列（模拟无趋势市场），使 RSI 接近 50
        vals = [100.0 + (i % 2) * 0.01 for i in range(50)]
        info = calc_reversal(vals)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "neutral")
        # 得分应接近 0（无明确反转信号）
        self.assertAlmostEqual(abs(info["score"]), 0.0, places=1)

    def test_rsi_oversold_generates_buy(self):
        """RSI 超卖应产生反弹买入信号。"""
        base = 100.0
        # 连续下跌使 RSI 降至超卖区
        vals = [base] * 10
        for i in range(1, 30):
            vals.append(vals[-1] - 0.8)
        info = calc_reversal(vals, ReversalParams(rsi_period=7))
        self.assertIsNotNone(info)
        self.assertIn(info["signal"], ("buy", "strong_buy"))
        self.assertLessEqual(info["rsi"], 30)

    def test_rsi_overbought_generates_sell(self):
        """RSI 超买应产生回落卖出信号。"""
        base = 100.0
        vals = [base] * 10
        for i in range(1, 30):
            vals.append(vals[-1] + 0.8)
        info = calc_reversal(vals, ReversalParams(rsi_period=7))
        self.assertIsNotNone(info)
        self.assertIn(info["signal"], ("sell", "strong_sell"))
        self.assertGreaterEqual(info["rsi"], 70)

    def test_v_shape_reversal_buy(self):
        """V 型下跌后反弹：价格低于 EMA 且 RSI 超卖，应触发反弹买入。"""
        base = 10000.0
        # 先上涨再急跌
        vals = [base + i * 5.0 for i in range(20)]
        for i in range(20):
            vals.append(vals[-1] - 15.0)
        # 再小幅反弹
        for i in range(10):
            vals.append(vals[-1] + 2.0)
        info = calc_reversal(vals)
        self.assertIsNotNone(info)
        # 价格低于 EMA → 看多反转
        self.assertLess(info["deviationPct"], 0)

    def test_inverse_v_shape_reversal_sell(self):
        """倒 V 型上涨后回落：价格高于 EMA 且 RSI 超买，应触发回落卖出。"""
        base = 10000.0
        vals = [base - i * 5.0 for i in range(20)]
        for i in range(20):
            vals.append(vals[-1] + 15.0)
        for i in range(10):
            vals.append(vals[-1] - 2.0)
        info = calc_reversal(vals)
        self.assertIsNotNone(info)
        self.assertGreater(info["deviationPct"], 0)


class ReversalScoreTestCase(unittest.TestCase):
    """综合评分计算测试。"""

    def test_all_scores_present(self):
        """正常情况应返回所有得分字段。"""
        vals = [10000.0 + i * 2.0 for i in range(50)]
        info = calc_reversal(vals)
        self.assertIsNotNone(info)
        self.assertIn("score", info)
        self.assertIn("rsiScore", info)
        self.assertIn("bbScore", info)
        self.assertIn("devScore", info)
        self.assertIn("strength", info)

    def test_score_range(self):
        """综合得分应在 [-1, 1] 范围内。"""
        base = 10000.0
        import random
        random.seed(42)
        for _ in range(10):
            vals = [base + random.uniform(-50, 50) for _ in range(50)]
            info = calc_reversal(vals)
            if info:
                self.assertGreaterEqual(info["score"], -1.0)
                self.assertLessEqual(info["score"], 1.0)

    def test_weights_sum_to_one(self):
        """权重之和应为 1.0，确保评分归一化。"""
        p = ReversalParams()
        self.assertAlmostEqual(p.rsi_weight + p.bb_weight + p.deviation_weight, 1.0, places=6)

    def test_strong_signal_requires_high_score(self):
        """强信号需要综合得分超过 strong_score。"""
        p = ReversalParams(strong_score=0.8, min_score=0.5)
        # 用极端下跌序列确保高分
        base = 10000.0
        vals = [base]
        for i in range(1, 50):
            vals.append(vals[-1] - 20.0)
        info = calc_reversal(vals, p)
        self.assertIsNotNone(info)
        if info["signal"] in ("strong_buy", "strong_sell"):
            self.assertGreaterEqual(abs(info["score"]), p.strong_score)

    def test_neutral_when_score_below_min(self):
        """得分低于 min_score 时应返回 neutral。"""
        p = ReversalParams(min_score=0.9)  # 极高的门槛
        vals = [10000.0 + i * 0.1 for i in range(50)]
        info = calc_reversal(vals, p)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "neutral")


class ReversalBoundaryTestCase(unittest.TestCase):
    """边界条件测试。"""

    def test_empty_list(self):
        """空列表应返回 None。"""
        self.assertIsNone(calc_reversal([]))

    def test_single_element(self):
        """单元素列表应返回 None。"""
        self.assertIsNone(calc_reversal([100.0]))

    def test_two_elements(self):
        """两个元素应返回 None（不足 rsi_period+1）。"""
        self.assertIsNone(calc_reversal([100.0, 101.0]))

    def test_extreme_rsi_100(self):
        """RSI=100（全部上涨）时，反转策略看空。"""
        vals = [100.0]
        for i in range(1, 30):
            vals.append(vals[-1] + 5.0)
        info = calc_reversal(vals, ReversalParams(rsi_period=7))
        self.assertIsNotNone(info)
        self.assertEqual(info["rsi"], 100.0)
        self.assertLessEqual(info["score"], 0)

    def test_extreme_rsi_0(self):
        """RSI=0（全部下跌）时，反转策略看多。"""
        vals = [200.0]
        for i in range(1, 30):
            vals.append(vals[-1] - 5.0)
        info = calc_reversal(vals, ReversalParams(rsi_period=7))
        self.assertIsNotNone(info)
        self.assertEqual(info["rsi"], 0.0)
        self.assertGreaterEqual(info["score"], 0)

    def test_zero_price_handling(self):
        """价格为 0 时偏差计算应安全。"""
        vals = [0.0] * 10 + [100.0] * 40
        info = calc_reversal(vals)
        self.assertIsNotNone(info)

    def test_constant_zero(self):
        """全零序列应返回 neutral。"""
        vals = [0.0] * 50
        info = calc_reversal(vals)
        self.assertIsNotNone(info)
        self.assertEqual(info["signal"], "neutral")


class ReversalParamsTestCase(unittest.TestCase):
    """参数配置测试。"""

    def test_default_params(self):
        """默认参数应在合理范围内。"""
        p = ReversalParams()
        self.assertGreaterEqual(p.rsi_period, 5)
        self.assertGreater(p.rsi_overbought, p.rsi_oversold)
        self.assertGreater(p.deviation_strong, p.deviation_entry)
        self.assertGreater(p.strong_score, p.min_score)
        self.assertGreater(p.cooldown_bars, 0)

    def test_custom_params_override(self):
        """自定义参数应影响信号结果。"""
        base = 10000.0
        vals = [base + i * 0.5 for i in range(50)]
        # 高门槛：几乎不触发
        strict = calc_reversal(vals, ReversalParams(min_score=0.99))
        # 低门槛：容易触发
        loose = calc_reversal(vals, ReversalParams(min_score=0.01))
        self.assertIsNotNone(strict)
        self.assertIsNotNone(loose)
        self.assertEqual(strict["signal"], "neutral")
        self.assertIn(loose["signal"], ("buy", "sell", "strong_buy", "strong_sell"))


if __name__ == "__main__":
    unittest.main()
