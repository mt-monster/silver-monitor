"""数据轮询模块（pollers.py）单元测试。

覆盖价格缓冲、bar 时间窗口采样、信号预计算、参数加载。
"""

import unittest

from backend.pollers import (
    _momentum_params_for,
    _reversal_params_for,
    _buffer_precious_prices,
)
from backend.state import state
from backend.strategies.momentum import MomentumParams
from backend.strategies.reversal import ReversalParams


class MomentumParamsForTestCase(unittest.TestCase):
    """动量参数加载测试。"""

    def test_comex_returns_params(self):
        """COMEX 银应返回有效的 MomentumParams。"""
        p = _momentum_params_for("xag")
        self.assertIsInstance(p, MomentumParams)
        self.assertGreater(p.short_p, 0)
        self.assertGreater(p.long_p, p.short_p)

    def test_huyin_returns_params(self):
        """沪银应返回有效的 MomentumParams。"""
        p = _momentum_params_for("ag0")
        self.assertIsInstance(p, MomentumParams)
        self.assertGreater(p.short_p, 0)

    def test_unknown_inst_uses_defaults(self):
        """未知品种应回退到 default 参数（含 realtime 覆盖）。"""
        p = _momentum_params_for("unknown")
        self.assertIsInstance(p, MomentumParams)
        # unknown 品种无特定配置，使用 default + realtime.default 覆盖
        self.assertGreater(p.short_p, 0)
        self.assertGreater(p.long_p, p.short_p)

    def test_realtime_override_applied(self):
        """realtime 段参数应覆盖 default。"""
        p = _momentum_params_for("xag")
        # COMEX realtime 配置了特定的 short_p/long_p
        self.assertNotEqual(p.short_p, MomentumParams().short_p)


class ReversalParamsForTestCase(unittest.TestCase):
    """反转参数加载测试。"""

    def test_comex_returns_params(self):
        """COMEX 银应返回有效的 ReversalParams。"""
        p = _reversal_params_for("xag")
        self.assertIsInstance(p, ReversalParams)
        self.assertGreater(p.rsi_period, 0)

    def test_huyin_returns_params(self):
        """沪银应返回有效的 ReversalParams。"""
        p = _reversal_params_for("ag0")
        self.assertIsInstance(p, ReversalParams)

    def test_realtime_override_applied(self):
        """realtime 段参数应覆盖 default。"""
        p = _reversal_params_for("xag")
        self.assertNotEqual(p.rsi_period, ReversalParams().rsi_period)


class BufferPreciousPricesTestCase(unittest.TestCase):
    """价格缓冲与时间窗口采样测试。"""

    def setUp(self):
        """清理缓冲区。"""
        state.instrument_price_buffers = {}
        state.instrument_bar_timestamps = {}
        state.realtime_backtest_buffers = {}
        state.silver_cache = {"data": {"price": 5000.0, "timestamp": 1_000_000}, "ts": 1_000_000}
        state.comex_silver_cache = {"data": {"price": 30.0, "timestamp": 1_000_000}, "ts": 1_000_000}
        state.gold_cache = {"data": {"price": 400.0, "timestamp": 1_000_000}, "ts": 1_000_000}
        state.comex_gold_cache = {"data": {"price": 1800.0, "timestamp": 1_000_000}, "ts": 1_000_000}
        state.btc_cache = {"data": {"price": 60000.0, "timestamp": 1_000_000}, "ts": 1_000_000}

    def test_buffer_created_for_all_instruments(self):
        """应分别为所有品种创建价格缓冲。"""
        _buffer_precious_prices()
        for inst in ("ag0", "xag", "au0", "xau", "btc"):
            self.assertIn(inst, state.instrument_price_buffers)
            self.assertGreater(len(state.instrument_price_buffers[inst]), 0)

    def test_realtime_buffer_created(self):
        """应同时创建高频实时采样缓冲。"""
        _buffer_precious_prices()
        for inst in ("ag0", "xag", "au0", "xau", "btc"):
            self.assertIn(inst, state.realtime_backtest_buffers)
            self.assertGreater(len(state.realtime_backtest_buffers[inst]), 0)

    def test_buffer_not_exceed_200(self):
        """价格缓冲不应超过 200 条。"""
        for i in range(250):
            state.silver_cache["data"]["timestamp"] = 1_000_000 + i * 100
            state.silver_cache["data"]["price"] = 5000.0 + i
            _buffer_precious_prices()
        self.assertLessEqual(len(state.instrument_price_buffers.get("ag0", [])), 200)

    def test_realtime_buffer_not_exceed_300(self):
        """高频缓冲不应超过 300 条。"""
        for i in range(350):
            state.silver_cache["data"]["timestamp"] = 1_000_000 + i * 100
            _buffer_precious_prices()
        self.assertLessEqual(len(state.realtime_backtest_buffers.get("ag0", [])), 300)

    def test_bar_timestamp_updated(self):
        """bar 时间戳应正确更新。"""
        _buffer_precious_prices()
        ts = state.instrument_bar_timestamps.get("ag0", 0)
        self.assertGreater(ts, 0)

    def test_skip_when_no_price(self):
        """价格为 None 或 0 时应跳过。"""
        state.silver_cache = {"data": {"price": None}, "ts": 1_000_000}
        _buffer_precious_prices()
        self.assertEqual(len(state.instrument_price_buffers.get("ag0", [])), 0)


if __name__ == "__main__":
    unittest.main()
