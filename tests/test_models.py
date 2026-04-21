"""数据模型（models.py）单元测试。

覆盖 TypedDict 字段完整性、可选字段、类型约束。
"""

import unittest

from backend.models import (
    AlertEvent,
    AlertStats,
    CombinedApiResponse,
    MarketSnapshot,
    SpreadSnapshot,
    TimeSeriesPoint,
)


class MarketSnapshotTestCase(unittest.TestCase):
    """MarketSnapshot 模型测试。"""

    def test_required_fields(self):
        """必填字段应存在。"""
        snap: MarketSnapshot = {
            "source": "sina",
            "symbol": "AG0",
            "name": "沪银",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/kg",
            "timestamp": 1_000_000,
            "datetime_cst": "2024-01-01 10:00:00",
        }
        self.assertEqual(snap["source"], "sina")

    def test_optional_fields(self):
        """可选字段可省略。"""
        snap: MarketSnapshot = {
            "source": "sina",
            "symbol": "AG0",
            "name": "沪银",
            "exchange": "SHFE",
            "currency": "CNY",
            "unit": "元/kg",
            "timestamp": 1_000_000,
            "datetime_cst": "2024-01-01 10:00:00",
            "price": 5000.0,
            "changePercent": 0.5,
        }
        self.assertEqual(snap["price"], 5000.0)
        # volume 未提供，但类型上允许

    def test_time_series_point(self):
        """TimeSeriesPoint 应包含 t 和 y。"""
        point: TimeSeriesPoint = {"t": 1_000_000, "y": 5000.0}
        self.assertEqual(point["t"], 1_000_000)
        self.assertEqual(point["y"], 5000.0)


class AlertEventTestCase(unittest.TestCase):
    """AlertEvent 模型测试。"""

    def test_all_fields_present(self):
        """完整告警事件应包含所有字段。"""
        event: AlertEvent = {
            "id": "alert_hu_123",
            "market": "hu",
            "marketName": "沪银",
            "type": "沪银_3TICK_JUMP",
            "direction": "急涨",
            "threshold": 0.15,
            "changePercent": 0.5,
            "changeAbs": 25.0,
            "fromPrice": 5000.0,
            "toPrice": 5025.0,
            "fromTime": "2024-01-01 10:00:00",
            "toTime": "2024-01-01 10:00:01",
            "oneTickPct": 0.2,
            "twoTickPct": 0.5,
            "tickCount": 3,
            "source": "sina",
            "timestamp": 1_000_000,
            "datetime": "2024-01-01 10:00:01",
            "severity": "MEDIUM",
            "unit": "元/kg",
        }
        self.assertEqual(event["severity"], "MEDIUM")
        self.assertEqual(event["direction"], "急涨")


class SpreadSnapshotTestCase(unittest.TestCase):
    """SpreadSnapshot 模型测试。"""

    def test_basic_fields(self):
        """基础价差字段。"""
        spread: SpreadSnapshot = {
            "ratio": 0.85,
            "cnySpread": 1200.0,
            "status": "normal",
            "deviation": 0.02,
        }
        self.assertEqual(spread["status"], "normal")


class CombinedApiResponseTestCase(unittest.TestCase):
    """CombinedApiResponse 模型测试。"""

    def test_minimal_response(self):
        """最小响应应包含核心字段。"""
        resp: CombinedApiResponse = {
            "comex": {},
            "huyin": {},
            "comexGold": {},
            "hujin": {},
            "spread": {},
            "goldSpread": {},
            "goldSilverRatio": None,
            "hvSeries": {},
            "timestamp": 1_000_000,
            "datetime_utc": "2024-01-01T02:00:00Z",
            "datetime_cst": "2024-01-01 10:00:00",
            "activeSources": ["sina"],
        }
        self.assertIn("sina", resp["activeSources"])

    def test_with_signals(self):
        """含信号字段的响应。"""
        resp: CombinedApiResponse = {
            "comex": {"price": 30.0},
            "huyin": {"price": 5000.0},
            "comexGold": {"price": 1800.0},
            "hujin": {"price": 400.0},
            "signals": {"xag": {"signal": "buy"}},
            "spread": {"ratio": 0.85},
            "goldSpread": {"ratio": 0.92},
            "goldSilverRatio": 60.0,
            "hvSeries": {"comex": [{"t": 1, "y": 0.15}]},
            "timestamp": 1_000_000,
            "datetime_utc": "2024-01-01T02:00:00Z",
            "datetime_cst": "2024-01-01 10:00:00",
            "activeSources": ["sina"],
        }
        self.assertEqual(resp["signals"]["xag"]["signal"], "buy")


class AlertStatsTestCase(unittest.TestCase):
    """AlertStats 模型测试。"""

    def test_initial_stats(self):
        """初始统计应为零。"""
        stats: AlertStats = {"surge": 0, "drop": 0, "maxJump": 0.0}
        self.assertEqual(stats["surge"], 0)
        self.assertEqual(stats["drop"], 0)


if __name__ == "__main__":
    unittest.main()
