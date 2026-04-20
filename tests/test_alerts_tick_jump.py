"""3-Tick 跳动预警：固定价格路径回归测试（与 check_tick_jump 行为一致）。"""

import unittest

from backend.alerts import check_tick_jump
from backend.state import state


class TickJumpAlertTestCase(unittest.TestCase):
    def setUp(self):
        self._saved_threshold = state.tick_jump_threshold
        self._saved_thresholds = dict(state.tick_jump_thresholds)
        self._saved_ring = list(state.silver_tick_ring)
        self._saved_history = list(state.alert_history)
        self._saved_hu_stats = dict(state.alert_stats["hu"])
        state.tick_jump_threshold = 0.5
        state.tick_jump_thresholds["hu"] = 0.5
        state.silver_tick_ring = []
        state.alert_history = []
        state.alert_stats["hu"] = {"surge": 0, "drop": 0, "maxJump": 0}

    def tearDown(self):
        state.tick_jump_threshold = self._saved_threshold
        state.tick_jump_thresholds.update(self._saved_thresholds)
        state.silver_tick_ring = self._saved_ring
        state.alert_history = self._saved_history
        state.alert_stats["hu"] = self._saved_hu_stats

    def test_no_alert_when_three_tick_move_below_threshold(self):
        for price in (10000.0, 10000.0, 10049.0):
            check_tick_jump("hu", price, "test")
        self.assertEqual(len(state.alert_history), 0)
        self.assertEqual(state.alert_stats["hu"]["surge"], 0)
        self.assertEqual(state.alert_stats["hu"]["drop"], 0)

    def test_alert_when_three_tick_move_reaches_threshold(self):
        last = None
        for price in (10000.0, 10000.0, 10050.0):
            last = check_tick_jump("hu", price, "test")
        self.assertIsNotNone(last)
        self.assertEqual(len(state.alert_history), 1)
        self.assertEqual(state.alert_history[0]["direction"], "急涨")
        self.assertAlmostEqual(state.alert_history[0]["changePercent"], 0.5, places=3)
        self.assertEqual(state.alert_stats["hu"]["surge"], 1)
        self.assertEqual(state.alert_stats["hu"]["drop"], 0)
        self.assertAlmostEqual(state.alert_stats["hu"]["maxJump"], 0.5, places=3)

    def test_drop_alert_when_three_tick_fall_exceeds_threshold(self):
        last = None
        for price in (10000.0, 10000.0, 9900.0):
            last = check_tick_jump("hu", price, "test")
        self.assertIsNotNone(last)
        self.assertEqual(len(state.alert_history), 1)
        self.assertEqual(state.alert_history[0]["direction"], "急跌")
        self.assertAlmostEqual(state.alert_history[0]["changePercent"], -1.0, places=3)
        self.assertEqual(state.alert_stats["hu"]["surge"], 0)
        self.assertEqual(state.alert_stats["hu"]["drop"], 1)
        self.assertAlmostEqual(state.alert_stats["hu"]["maxJump"], 1.0, places=3)


if __name__ == "__main__":
    unittest.main()
