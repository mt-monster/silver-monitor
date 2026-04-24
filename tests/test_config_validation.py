"""验证 monitor.config.json 参数配置的经济学合理性。

本测试确保 realtime 段参数不会过于激进，避免信号被噪声驱动。
"""

import json
import unittest
from pathlib import Path


class ConfigValidationTestCase(unittest.TestCase):
    """加载 monitor.config.json 并校验关键参数范围。"""

    @classmethod
    def setUpClass(cls):
        cfg_path = Path(__file__).resolve().parent.parent / "monitor.config.json"
        with open(cfg_path, "r", encoding="utf-8") as f:
            cls.cfg = json.load(f)

    # ── 动量策略参数校验 ──────────────────────────────────────

    def test_momentum_realtime_spread_entry_not_too_small(self):
        """realtime spread_entry 不应低于 0.01%，否则对银价而言完全是噪声。"""
        rt = self.cfg["momentum"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                val = rt[key].get("spread_entry", rt["default"]["spread_entry"])
                self.assertGreaterEqual(
                    val, 0.01,
                    f"momentum.realtime.{key}.spread_entry={val} 过小，会被噪声驱动"
                )

    def test_momentum_realtime_slope_entry_not_too_small(self):
        """realtime slope_entry 不应低于 0.005%，否则无统计意义。"""
        rt = self.cfg["momentum"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                val = rt[key].get("slope_entry", rt["default"]["slope_entry"])
                self.assertGreaterEqual(
                    val, 0.005,
                    f"momentum.realtime.{key}.slope_entry={val} 过小"
                )

    def test_momentum_realtime_ema_periods_reasonable(self):
        """EMA 短周期不应小于 2，长周期不应小于 4（bar_window_ms=2s 时 EMA3/5=6~10s 窗口）。"""
        rt = self.cfg["momentum"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                short_p = rt[key].get("short_p", rt["default"]["short_p"])
                long_p = rt[key].get("long_p", rt["default"]["long_p"])
                self.assertGreaterEqual(short_p, 2, f"short_p={short_p} 过小")
                self.assertGreaterEqual(long_p, 4, f"long_p={long_p} 过小")
                self.assertLess(short_p, long_p, "short_p 应小于 long_p")

    def test_momentum_realtime_rsi_period_standard(self):
        """realtime RSI 周期应 ≥ 5（1s bar × 5 = 5s 窗口），避免纯噪声驱动。"""
        rt = self.cfg["momentum"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                val = rt[key].get("rsi_period", rt["default"]["rsi_period"])
                self.assertGreaterEqual(val, 5, f"rsi_period={val} 过于敏感")

    def test_momentum_realtime_bb_mult_not_too_low(self):
        """BB 倍数不应低于 1.5，避免假突破。"""
        rt = self.cfg["momentum"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                val = rt[key].get("bb_mult", rt["default"]["bb_mult"])
                self.assertGreaterEqual(val, 1.5, f"bb_mult={val} 过低")

    # ── 反转策略参数校验 ──────────────────────────────────────

    def test_reversal_realtime_rsi_thresholds_standard(self):
        """realtime RSI 超买超卖阈值应接近标准 28/72（1s bar 下 RSI(5) 略宽于标准）。"""
        rt = self.cfg["reversal"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                oversold = rt[key].get("rsi_oversold", rt["default"]["rsi_oversold"])
                overbought = rt[key].get("rsi_overbought", rt["default"]["rsi_overbought"])
                self.assertLessEqual(oversold, 35, f"rsi_oversold={oversold} 过高")
                self.assertGreaterEqual(overbought, 65, f"rsi_overbought={overbought} 过低")

    def test_reversal_realtime_deviation_not_too_small(self):
        """EMA 偏离度触发阈值不应低于 0.10%（1s bar × 5 = 5s 窗口需有统计意义）。"""
        rt = self.cfg["reversal"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                val = rt[key].get("deviation_entry", rt["default"]["deviation_entry"])
                self.assertGreaterEqual(
                    val, 0.10,
                    f"reversal.realtime.{key}.deviation_entry={val} 过小"
                )

    def test_reversal_realtime_min_score_not_too_low(self):
        """min_score 不应低于 0.3，避免过多假信号。"""
        rt = self.cfg["reversal"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                val = rt[key].get("min_score", rt["default"]["min_score"])
                self.assertGreaterEqual(val, 0.3, f"min_score={val} 过低")

    def test_reversal_realtime_strong_score_not_too_low(self):
        """strong_score 应显著高于 min_score。"""
        rt = self.cfg["reversal"]["realtime"]
        for key in ("default", "comex", "huyin"):
            with self.subTest(symbol=key):
                min_s = rt[key].get("min_score", rt["default"]["min_score"])
                strong_s = rt[key].get("strong_score", rt["default"]["strong_score"])
                self.assertGreater(
                    strong_s, min_s,
                    f"strong_score ({strong_s}) 应大于 min_score ({min_s})"
                )

    # ── 配置一致性校验 ──────────────────────────────────────

    def test_momentum_realtime_comex_not_more_aggressive_than_default(self):
        """comex realtime 不应比 default 更激进（阈值更低）。"""
        rt = self.cfg["momentum"]["realtime"]
        # 阈值：越低越激进
        self.assertGreaterEqual(
            rt["comex"]["spread_entry"], rt["default"]["spread_entry"],
            "comex spread_entry 不应低于 default"
        )
        self.assertGreaterEqual(
            rt["comex"]["slope_entry"], rt["default"]["slope_entry"],
            "comex slope_entry 不应低于 default"
        )

    def test_reversal_realtime_comex_params_valid(self):
        """comex realtime 反转参数应在合理范围内。"""
        rt = self.cfg["reversal"]["realtime"]
        # COMEX 白银高波动，deviation_entry 可低于 default
        self.assertGreater(rt["comex"]["deviation_entry"], 0.05,
            "comex deviation_entry 不应过低")
        self.assertLess(rt["comex"]["deviation_entry"], 0.5,
            "comex deviation_entry 不应过高")


if __name__ == "__main__":
    unittest.main()
