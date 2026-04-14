"""回测引擎（合成 K 线，不依赖网络）。"""

import unittest

from backend.backtest import run_momentum_long_only_backtest
from backend.strategies.momentum import MomentumParams


class BacktestEngineTestCase(unittest.TestCase):
    def test_equity_length_matches_bars(self):
        bars = [{"t": 1_000_000 + i * 60_000, "y": 10000.0 + i * 5.0} for i in range(80)]
        out = run_momentum_long_only_backtest(bars, MomentumParams())
        self.assertEqual(len(out["equity"]), 80)
        self.assertIn("metrics", out)
        self.assertEqual(out["metrics"]["bars"], 80)

    def test_flat_market_stays_near_initial_equity(self):
        bars = [{"t": i * 60_000, "y": 10000.0} for i in range(60)]
        out = run_momentum_long_only_backtest(bars, MomentumParams())
        last_eq = out["equity"][-1]["equity"]
        self.assertAlmostEqual(last_eq, 1.0, places=3)
        self.assertIsNone(out["metrics"].get("sharpeRatio"))

    def test_sharpe_present_when_equity_volatile(self):
        bars = [{"t": 1_000_000 + i * 60_000, "y": 10000.0 + i * 5.0} for i in range(80)]
        out = run_momentum_long_only_backtest(bars, MomentumParams())
        sh = out["metrics"].get("sharpeRatio")
        self.assertIsNotNone(sh)
        self.assertIsInstance(sh, (int, float))


if __name__ == "__main__":
    unittest.main()
