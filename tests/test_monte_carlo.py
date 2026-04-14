"""蒙特卡洛模块单元测试。"""

import math
import random
import time
import unittest

from backend.research.monte_carlo import run_huyin_monte_carlo


class MonteCarloTestCase(unittest.TestCase):
    def _samples_upward(self, n: int = 40) -> list[dict]:
        now_ms = int(time.time() * 1000)
        out = []
        for i in range(n):
            out.append({"ts": now_ms - (n - 1 - i) * 3000, "price": 10000.0 + i * 2.0})
        return out

    def test_insufficient_returns_returns_none(self):
        now_ms = int(time.time() * 1000)
        samples = [
            {"ts": now_ms - 2000, "price": 100.0},
            {"ts": now_ms - 1000, "price": 101.0},
        ]
        rng = random.Random(0)
        payload, warns = run_huyin_monte_carlo(
            samples,
            horizon_sec=5,
            paths=100,
            model="gbm",
            drift="zero",
            window_minutes=60,
            min_returns=30,
            max_paths=10000,
            histogram_bins=10,
            rng=rng,
        )
        self.assertIsNone(payload)
        self.assertTrue(any("need_at_least" in w for w in warns))

    def test_gbm_deterministic_with_seed(self):
        samples = self._samples_upward(45)
        rng = random.Random(0)
        payload, _ = run_huyin_monte_carlo(
            samples,
            horizon_sec=5,
            paths=500,
            model="gbm",
            drift="zero",
            window_minutes=120,
            min_returns=30,
            max_paths=10000,
            histogram_bins=20,
            rng=rng,
        )
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["horizonSec"], 5)
        self.assertAlmostEqual(payload["S0"], 10000.0 + 44 * 2.0, places=2)
        self.assertGreater(payload["probUp"], 0.3)
        self.assertLess(payload["probUp"], 0.95)
        self.assertIn("p50", payload["percentiles"])
        self.assertIn("pricesPercentiles", payload)
        self.assertIn("priceMean", payload)
        s0 = payload["S0"]
        d50 = payload["percentiles"]["p50"]
        self.assertAlmostEqual(payload["pricesPercentiles"]["p50"], s0 * (1 + d50 / 100.0), places=2)
        hist = payload["histogram"]
        self.assertEqual(len(hist["counts"]), 20)
        self.assertEqual(sum(hist["counts"]), 500)
        self.assertIn("pathChart", payload)
        pc = payload["pathChart"]
        self.assertEqual(pc["pathCount"], 40)
        self.assertEqual(len(pc["paths"]), 40)
        self.assertEqual(len(pc["paths"][0]), pc["steps"] + 1)
        self.assertAlmostEqual(pc["paths"][0][0], payload["S0"], places=2)

        rng2 = random.Random(0)
        payload2, _ = run_huyin_monte_carlo(
            samples,
            horizon_sec=5,
            paths=500,
            model="gbm",
            drift="zero",
            window_minutes=120,
            min_returns=30,
            max_paths=10000,
            histogram_bins=20,
            rng=rng2,
        )
        assert payload2 is not None
        self.assertEqual(payload["deltaPctMean"], payload2["deltaPctMean"])
        self.assertEqual(payload["percentiles"]["p50"], payload2["percentiles"]["p50"])

    def test_bootstrap_reasonable_range(self):
        samples = self._samples_upward(50)
        rng = random.Random(42)
        payload, _ = run_huyin_monte_carlo(
            samples,
            horizon_sec=1,
            paths=800,
            model="bootstrap",
            drift="zero",
            window_minutes=120,
            min_returns=30,
            max_paths=20000,
            histogram_bins=15,
            rng=rng,
        )
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn("pathChart", payload)
        p = payload["percentiles"]
        self.assertLess(p["p5"], p["p95"])
        self.assertTrue(all(math.isfinite(float(x)) for x in (p["p5"], p["p50"], p["p95"])))


if __name__ == "__main__":
    unittest.main()
