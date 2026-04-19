import unittest

from backend.analytics import compute_rolling_hv, rebuild_all_cache
from backend.state import state


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        state.silver_cache = {"data": None, "ts": 0}
        state.comex_silver_cache = {"data": None, "ts": 0}
        state.gold_cache = {"data": None, "ts": 0}
        state.comex_gold_cache = {"data": None, "ts": 0}
        state.combined_cache = {"data": None, "ts": 0}
        state.instrument_signals = {}
        state.usd_cny_cache = {"rate": 7.0, "ts": 0}

    def test_compute_rolling_hv_returns_series(self):
        history = [{"t": i * 1000, "y": 100 + i} for i in range(30)]
        result = compute_rolling_hv(history, window=5)
        self.assertTrue(result)
        self.assertIn("t", result[0])
        self.assertIn("y", result[0])

    def test_rebuild_all_cache_contains_spreads_and_ratio(self):
        state.silver_cache["data"] = {
            "price": 1000.0,
            "source": "test-silver",
            "history": [{"t": i * 1000, "y": 900 + i} for i in range(30)],
        }
        state.comex_silver_cache["data"] = {
            "price": 5.0,
            "priceCny": 950.0,
            "source": "test-comex",
            "history": [{"t": i * 1000, "y": 4.5 + i * 0.1} for i in range(30)],
        }
        state.gold_cache["data"] = {
            "price": 700.0,
            "source": "test-gold",
            "history": [{"t": i * 1000, "y": 680 + i} for i in range(30)],
        }
        state.comex_gold_cache["data"] = {
            "price": 100.0,
            "priceCnyG": 680.0,
            "source": "test-comex-gold",
            "history": [{"t": i * 1000, "y": 90 + i * 0.5} for i in range(30)],
        }

        combined = rebuild_all_cache()

        self.assertEqual(combined["spread"]["ratio"], round(1000.0 / 950.0, 4))
        self.assertEqual(combined["goldSpread"]["ratio"], round(700.0 / 680.0, 4))
        self.assertEqual(combined["goldSilverRatio"], 20.0)
        self.assertIn("hu", combined["hvSeries"])
        self.assertIn("comex", combined["hvSeries"])

    def test_rebuild_all_cache_includes_precomputed_signals(self):
        state.silver_cache["data"] = {"price": 1000.0, "source": "test-silver"}
        state.instrument_signals = {
            "ag0": {"signal": "buy", "strength": 42.0, "spreadPct": 0.12},
            "xag": None,
        }

        combined = rebuild_all_cache()

        self.assertIn("signals", combined)
        self.assertEqual(combined["signals"]["ag0"]["signal"], "buy")
        self.assertNotIn("xag", combined["signals"])


if __name__ == "__main__":
    unittest.main()
