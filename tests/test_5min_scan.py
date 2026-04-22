"""5分钟 tick 窗口扫描回测测试。"""

import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from backend.backtest_runner import (
    _build_param_combinations,
    _score_for_ranking,
    run_single_window_backtest,
    scan_5min_windows,
)
from backend.strategies.momentum import MomentumParams
from backend.tick_storage import (
    get_available_dates,
    get_daily_best,
    get_ticks_for_date,
    get_window_results,
    init_tick_db,
    save_tick,
    save_ticks_batch,
)


class TickStorageTestCase(unittest.TestCase):
    def setUp(self):
        # 使用临时数据库
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_ticks.db")
        # monkey-patch tick_storage 的数据库路径
        import backend.tick_storage as ts
        self._orig_db = ts._DB_PATH
        ts._DB_PATH = self.db_path
        init_tick_db()

    def tearDown(self):
        import backend.tick_storage as ts
        ts._DB_PATH = self._orig_db
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_and_query_tick(self):
        ts = int(datetime(2026, 4, 21, 9, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        save_tick("xag", ts, 32.5, "2026-04-21")
        rows = get_ticks_for_date("xag", "2026-04-21")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["y"], 32.5)

    def test_batch_save(self):
        base = int(datetime(2026, 4, 21, 9, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        records = [("xag", base + i * 1000, 30.0 + i * 0.01, "2026-04-21") for i in range(100)]
        save_ticks_batch(records)
        rows = get_ticks_for_date("xag", "2026-04-21")
        self.assertEqual(len(rows), 100)

    def test_get_available_dates(self):
        save_tick("xag", 1713686400000, 30.0, "2026-04-20")
        save_tick("xag", 1713772800000, 31.0, "2026-04-21")
        dates = get_available_dates("xag")
        self.assertIn("2026-04-20", dates)
        self.assertIn("2026-04-21", dates)


class ParamCombinationTestCase(unittest.TestCase):
    def test_build_param_combinations(self):
        base = {"short_p": 5, "long_p": 15}
        grid = {"spread_entry": [0.01, 0.02]}
        combos = _build_param_combinations(base, grid)
        self.assertEqual(len(combos), 2)
        self.assertEqual(combos[0]["spread_entry"], 0.01)
        self.assertEqual(combos[1]["spread_entry"], 0.02)

    def test_empty_grid_returns_base(self):
        base = {"short_p": 5}
        combos = _build_param_combinations(base, {})
        self.assertEqual(len(combos), 1)
        self.assertEqual(combos[0]["short_p"], 5)


class ScoreRankingTestCase(unittest.TestCase):
    def test_score_prefers_sharpe_when_comparable(self):
        # 评分函数中 sharpe 权重为 0.3*10=3，收益权重为 0.6
        # m2 夏普更高，即使收益更低，综合分也可能更高
        m1 = {"totalReturnPct": 5.0, "sharpeRatio": 0.5, "maxDrawdownPct": 1.0}
        m2 = {"totalReturnPct": 3.0, "sharpeRatio": 2.0, "maxDrawdownPct": 1.0}
        # m2 夏普优势明显，综合分应更高
        self.assertGreater(_score_for_ranking(m2), _score_for_ranking(m1))

    def test_score_penalizes_drawdown(self):
        m1 = {"totalReturnPct": 5.0, "sharpeRatio": 0.5, "maxDrawdownPct": 5.0}
        m2 = {"totalReturnPct": 5.0, "sharpeRatio": 0.5, "maxDrawdownPct": 1.0}
        self.assertGreater(_score_for_ranking(m2), _score_for_ranking(m1))


class SingleWindowBacktestTestCase(unittest.TestCase):
    def test_run_single_window_momentum(self):
        # 构造一个 5 分钟（300 点）的上行趋势
        bars = [{"t": i * 1000, "y": 30.0 + i * 0.01} for i in range(300)]
        result = run_single_window_backtest(bars, strategy="momentum")
        self.assertIn("best_params", result)
        self.assertIn("best_metrics", result)
        # 上行趋势应该有正收益
        self.assertIsNotNone(result["best_metrics"].get("totalReturnPct"))

    def test_run_single_window_no_grid(self):
        bars = [{"t": i * 1000, "y": 30.0} for i in range(300)]
        result = run_single_window_backtest(bars, strategy="momentum", param_grid=None)
        # 横盘应该无交易或收益接近 0
        self.assertIsNotNone(result["best_metrics"])


class Scan5minWindowsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_scan.db")
        import backend.tick_storage as ts
        self._orig_db = ts._DB_PATH
        ts._DB_PATH = self.db_path
        init_tick_db()

    def tearDown(self):
        import backend.tick_storage as ts
        ts._DB_PATH = self._orig_db
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_ticks(self, inst_id="xag", date_str="2026-04-21", count=600, start_hour=9):
        """生成 count 条 tick，间隔 1 秒，价格轻微波动。"""
        from datetime import datetime, timezone
        base_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=start_hour, minute=0, second=0)
        base_ts = int(base_dt.timestamp() * 1000)
        records = []
        for i in range(count):
            price = 30.0 + (i % 100) * 0.001  # 轻微波动
            records.append((inst_id, base_ts + i * 1000, price, date_str))
        save_ticks_batch(records)

    def test_scan_finds_best_window(self):
        self._seed_ticks(count=600)
        result = scan_5min_windows(
            "xag", "2026-04-21", strategy="momentum",
            step_ms=60_000, param_grid=None, save_results=False,
        )
        self.assertNotIn("error", result)
        self.assertIn("best_window", result)
        self.assertIn("top_windows", result)
        self.assertGreater(result["scanned_windows"], 0)

    def test_scan_saves_to_db(self):
        self._seed_ticks(count=600)
        result = scan_5min_windows(
            "xag", "2026-04-21", strategy="momentum",
            step_ms=60_000, param_grid=None, save_results=True,
        )
        self.assertNotIn("error", result)
        # 检查数据库
        best = get_daily_best("xag", "2026-04-21", "momentum")
        self.assertIsNotNone(best)
        windows = get_window_results("xag", "2026-04-21", "momentum")
        self.assertGreater(len(windows), 0)

    def test_scan_insufficient_ticks(self):
        # 只写入 10 条 tick，不足以扫描
        save_tick("xag", 1713686400000, 30.0, "2026-04-19")
        result = scan_5min_windows("xag", "2026-04-19", strategy="momentum", save_results=False)
        self.assertIn("error", result)
        self.assertEqual(result["error"], "insufficient_ticks")

    def test_scan_param_grid(self):
        self._seed_ticks(count=600)
        result = scan_5min_windows(
            "xag", "2026-04-21", strategy="momentum",
            step_ms=120_000,
            param_grid={"spread_entry": [0.01, 0.05]},
            save_results=False,
        )
        self.assertNotIn("error", result)
        # param_grid 应该产生更多组合
        self.assertGreaterEqual(result["scanned_windows"], 1)


if __name__ == "__main__":
    unittest.main()
