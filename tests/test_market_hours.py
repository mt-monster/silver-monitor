import unittest
from datetime import datetime
from unittest.mock import patch

import backend.market_hours as market_hours
from backend.config import CST


class FakeDateTime:
    fixed_now = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixed_now.astimezone(tz or CST)


class MarketHoursTestCase(unittest.TestCase):
    def test_huyin_open_in_morning_session(self):
        with patch.object(market_hours, "datetime", FakeDateTime):
            FakeDateTime.fixed_now = datetime(2026, 4, 13, 9, 30, tzinfo=CST)
            self.assertTrue(market_hours.is_huyin_trading())
            status, desc = market_hours.get_trading_status("huyin")
            self.assertEqual(status, "open")
            self.assertIn("早盘", desc)

    def test_huyin_closed_on_weekend(self):
        with patch.object(market_hours, "datetime", FakeDateTime):
            FakeDateTime.fixed_now = datetime(2026, 4, 12, 10, 0, tzinfo=CST)
            self.assertFalse(market_hours.is_huyin_trading())
            status, desc = market_hours.get_trading_status("huyin")
            self.assertEqual(status, "closed")
            self.assertIn("周末", desc)


if __name__ == "__main__":
    unittest.main()
