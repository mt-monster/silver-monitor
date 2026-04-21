"""告警模块（alerts.py）单元测试。

覆盖 tick jump 检测、severity 判定、环形缓冲区、阈值切换、边界条件。
"""

import unittest

from backend.alerts import check_tick_jump
from backend.state import state


class TickJumpAlertTestCase(unittest.TestCase):
    """Tick 异动告警核心逻辑测试。"""

    def setUp(self):
        """每个测试前清理告警状态。"""
        state.silver_tick_ring = []
        state.comex_silver_tick_ring = []
        state.gold_tick_ring = []
        state.comex_gold_tick_ring = []
        state.btc_tick_ring = []
        state.alert_history = []
        state.alert_stats = {
            "hu": {"surge": 0, "drop": 0, "maxJump": 0.0},
            "comex": {"surge": 0, "drop": 0, "maxJump": 0.0},
            "hujin": {"surge": 0, "drop": 0, "maxJump": 0.0},
            "comex_gold": {"surge": 0, "drop": 0, "maxJump": 0.0},
            "btc": {"surge": 0, "drop": 0, "maxJump": 0.0},
        }
        state.tick_jump_threshold = 0.15
        state.tick_jump_thresholds = {
            "hu": 0.15,
            "comex": 0.10,
            "hujin": 0.12,
            "comex_gold": 0.10,
            "btc": 0.30,
        }
        state.alert_max_history = 200

    def test_no_alert_when_change_below_threshold(self):
        """变化率低于阈值时不应触发告警。"""
        # 沪银阈值 0.15%，价格变化 0.05% 不应触发
        check_tick_jump("hu", 5000.0)
        check_tick_jump("hu", 5002.0)
        result = check_tick_jump("hu", 5002.5)
        self.assertIsNone(result)

    def test_alert_when_change_exceeds_threshold(self):
        """变化率超过阈值时应触发告警。"""
        # 沪银阈值 0.15%，价格从 5000 → 5008（0.16%）应触发
        check_tick_jump("hu", 5000.0)
        check_tick_jump("hu", 5004.0)
        result = check_tick_jump("hu", 5008.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["market"], "hu")
        self.assertEqual(result["direction"], "急涨")

    def test_drop_alert(self):
        """价格下跌超过阈值时应触发急跌告警。"""
        check_tick_jump("hu", 5000.0)
        check_tick_jump("hu", 4996.0)
        result = check_tick_jump("hu", 4992.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "急跌")

    def test_per_market_threshold(self):
        """不同品种应使用各自独立的阈值。"""
        # COMEX 银阈值 0.10%，BTC 阈值 0.30%
        base_comex = 30.0
        base_btc = 60000.0

        # COMEX：0.15% > 0.10%，应触发
        check_tick_jump("comex", base_comex)
        check_tick_jump("comex", base_comex * 1.001)
        r_comex = check_tick_jump("comex", base_comex * 1.0015)
        self.assertIsNotNone(r_comex)

        # BTC：0.15% < 0.30%，不应触发
        check_tick_jump("btc", base_btc)
        check_tick_jump("btc", base_btc * 1.001)
        r_btc = check_tick_jump("btc", base_btc * 1.0015)
        self.assertIsNone(r_btc)

    def test_severity_low(self):
        """变化率在 1~2 倍阈值之间应为 LOW。"""
        base = 5000.0
        threshold = 0.15
        # 1.5 倍阈值
        target = base * (1 + threshold * 1.5 / 100)
        check_tick_jump("hu", base)
        check_tick_jump("hu", base * 1.001)
        result = check_tick_jump("hu", target)
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "LOW")

    def test_severity_medium(self):
        """变化率在 2~3 倍阈值之间应为 MEDIUM。"""
        base = 5000.0
        threshold = 0.15
        target = base * (1 + threshold * 2.5 / 100)
        check_tick_jump("hu", base)
        check_tick_jump("hu", base * 1.001)
        result = check_tick_jump("hu", target)
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "MEDIUM")

    def test_severity_high(self):
        """变化率超过 3 倍阈值应为 HIGH。"""
        base = 5000.0
        threshold = 0.15
        target = base * (1 + threshold * 3.5 / 100)
        check_tick_jump("hu", base)
        check_tick_jump("hu", base * 1.001)
        result = check_tick_jump("hu", target)
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "HIGH")

    def test_ring_buffer_size_limit(self):
        """环形缓冲区不应超过 5 个元素。"""
        for i in range(10):
            check_tick_jump("hu", 5000.0 + i)
        self.assertLessEqual(len(state.silver_tick_ring), 5)

    def test_alert_history_inserted(self):
        """告警应被插入 alert_history。"""
        base = 5000.0
        check_tick_jump("hu", base)
        check_tick_jump("hu", base * 1.001)
        check_tick_jump("hu", base * 1.003)
        self.assertGreaterEqual(len(state.alert_history), 1)
        self.assertEqual(state.alert_history[0]["market"], "hu")

    def test_alert_stats_updated(self):
        """告警统计应正确更新。"""
        base = 5000.0
        check_tick_jump("hu", base)
        check_tick_jump("hu", base * 1.001)
        check_tick_jump("hu", base * 1.003)
        self.assertEqual(state.alert_stats["hu"]["surge"], 1)
        self.assertGreater(state.alert_stats["hu"]["maxJump"], 0)

    def test_alert_fields_complete(self):
        """告警对象应包含所有必需字段。"""
        base = 5000.0
        check_tick_jump("hu", base)
        check_tick_jump("hu", base * 1.001)
        result = check_tick_jump("hu", base * 1.003)
        self.assertIsNotNone(result)
        required = [
            "id", "market", "marketName", "type", "direction",
            "threshold", "changePercent", "changeAbs", "fromPrice",
            "toPrice", "fromTime", "toTime", "oneTickPct", "twoTickPct",
            "tickCount", "source", "timestamp", "datetime", "severity", "unit",
        ]
        for field in required:
            self.assertIn(field, result, f"缺失字段: {field}")

    def test_zero_price_returns_none(self):
        """首价格为 0 时不应计算变化率。"""
        check_tick_jump("hu", 0.0)
        check_tick_jump("hu", 5000.0)
        result = check_tick_jump("hu", 5008.0)
        self.assertIsNone(result)

    def test_negative_price_returns_none(self):
        """负价格不应触发告警。"""
        check_tick_jump("hu", -100.0)
        check_tick_jump("hu", 5000.0)
        result = check_tick_jump("hu", 5008.0)
        self.assertIsNone(result)

    def test_unknown_market_fallback(self):
        """未知品种应回退到 silver_tick_ring。"""
        result = check_tick_jump("unknown", 100.0)
        self.assertIsNone(result)  # 只有 1 个 tick，不足 3 个


if __name__ == "__main__":
    unittest.main()
