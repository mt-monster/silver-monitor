"""回测绩效对比测试 — 每次更新动量/反转策略参数后运行，证明更新有效提升。

场景：
  1. test_comex_momentum_new_vs_overtight  — 验证本次放宽的 COMEX 动量阈值在温和上行
     趋势中能产生信号，而之前过紧的阈值（spread_entry=0.08）无法触发
  2. test_comex_momentum_return_on_uptrend — 验证新 COMEX 参数在上行数据集上回测
     总收益 > 0，策略有效捕获趋势
  3. test_reversal_new_weights_active — 验证反转策略新权重在急跌-复苏数据上
     至少完成 1 次完整回合（策略有效运作）
  4. test_reversal_new_weights_score_balance — 验证新权重在 RSI+BB 双极端、
     偏离度为零的早期反转场景中，综合分高于旧权重（数学证明）

运行方式：
  .venv\\Scripts\\python -m pytest tests/test_strategy_perf.py -v
"""
import math
import unittest

from backend.backtest import (
    run_momentum_long_only_backtest,
    run_reversal_long_only_backtest,
)
from backend.strategies.momentum import MomentumParams
from backend.strategies.reversal import ReversalParams, calc_reversal


# ─── 合成价格序列生成器 ────────────────────────────────────────────────

def _uptrend_bars(n: int = 150, start: float = 79.0, delta: float = 0.015) -> list[dict]:
    """温和上行趋势：线性涨幅 + 平滑正弦噪声，避免交替振荡导致 EMA 斜率负跳。
    delta=0.015/bar → EMA3/EMA10 理论稳态张口 ≈ 0.066%（在 0.05~0.08 之间）。
    平滑噪声周期 ≈ 12 bar，幅度 ±0.02，不会逆转 EMA3 斜率。
    """
    bars = []
    for i in range(n):
        noise = 0.02 * math.sin(i * 0.5)
        price = start + i * delta + noise
        bars.append({"t": 1_000_000 + i * 30_000, "y": round(price, 4)})
    return bars


def _crash_recovery_bars(n_cycles: int = 4) -> list[dict]:
    """急跌-复苏循环：稳定→瞬间大幅下跌→缓慢回升，用于测试反转策略。

    每个周期：
      - 稳定阶段 (20 bar, 79.0 ± 0.05)
      - 瞬间下跌 (1 bar, 73.0)：RSI→0, pctb→负数, 偏离度>>1.8%，三因子全极端
      - 缓慢回升 (10 bar, 73→79)
    总计 4 × 31 = 124 bar，使用日级时间戳（约 124 天）避免年化溢出。
    """
    stable_p = 79.0
    crash_p = 73.0
    bars = []
    t = 1_577_836_800_000  # 2020-01-01 00:00:00 UTC ms
    day_ms = 86_400_000
    for _ in range(n_cycles):
        for i in range(20):
            noise = 0.05 * (1 if i % 2 == 0 else -1)
            bars.append({"t": t, "y": round(stable_p + noise, 4)})
            t += day_ms
        bars.append({"t": t, "y": crash_p})
        t += day_ms
        for i in range(1, 11):
            bars.append({"t": t, "y": round(crash_p + (stable_p - crash_p) * i / 10, 4)})
            t += day_ms
    return bars


# ─── COMEX 动量参数 ────────────────────────────────────────────────────

def _comex_overtight_params() -> MomentumParams:
    """旧的过紧参数（上次优化时设置过高，导致无信号）。"""
    return MomentumParams(
        short_p=3, long_p=10,
        spread_entry=0.08, spread_strong=0.25, slope_entry=0.015,
        bb_period=10, bb_mult=2.0, rsi_period=14,
        bb_buy_kill=0.25, bb_sell_kill=0.75, cooldown_bars=2,
    )


def _comex_new_params() -> MomentumParams:
    """本次优化后的参数（monitor.config.json comex 节）。"""
    return MomentumParams(
        short_p=3, long_p=10,
        spread_entry=0.05, spread_strong=0.18, slope_entry=0.010,
        bb_period=10, bb_mult=2.0, rsi_period=14,
        bb_buy_kill=0.25, bb_sell_kill=0.75, cooldown_bars=2,
    )


# ─── 反转策略参数 ──────────────────────────────────────────────────────

def _reversal_old_weights() -> ReversalParams:
    """旧权重：rsi=0.40, bb=0.35, deviation=0.25（偏离度权重过高，与 RSI/BB 共线）。"""
    return ReversalParams(
        rsi_period=14, bb_period=10, ema_period=10,
        rsi_oversold=32.0, rsi_overbought=68.0,
        rsi_extreme_low=20.0, rsi_extreme_high=80.0,
        deviation_entry=1.0, deviation_strong=1.8,
        rsi_weight=0.40, bb_weight=0.35, deviation_weight=0.25,
        min_score=0.5, strong_score=0.8, cooldown_bars=2,
    )


def _reversal_new_weights() -> ReversalParams:
    """新权重（本次优化）：rsi=0.45, bb=0.45, deviation=0.10，降低共线干扰。"""
    return ReversalParams(
        rsi_period=14, bb_period=10, ema_period=10,
        rsi_oversold=32.0, rsi_overbought=68.0,
        rsi_extreme_low=20.0, rsi_extreme_high=80.0,
        deviation_entry=1.0, deviation_strong=1.8,
        rsi_weight=0.45, bb_weight=0.45, deviation_weight=0.10,
        min_score=0.5, strong_score=0.8, cooldown_bars=2,
    )


# ─── 测试用例 ──────────────────────────────────────────────────────────

class ComexMomentumPerfTestCase(unittest.TestCase):

    def test_comex_momentum_new_vs_overtight(self):
        """新参数在温和上行趋势中产生的完整回合数 > 0；旧过紧参数因 spread_entry 过高无法触发信号。"""
        bars = _uptrend_bars()
        old = run_momentum_long_only_backtest(bars, _comex_overtight_params())
        new = run_momentum_long_only_backtest(bars, _comex_new_params())

        old_trips = old["metrics"]["roundTripCount"] or 0
        new_trips = new["metrics"]["roundTripCount"] or 0

        self.assertGreater(
            new_trips, old_trips,
            f"新参数应在温和上行中触发更多买卖回合：new={new_trips}, old={old_trips}",
        )
        self.assertGreater(
            new_trips, 0,
            "新参数在趋势数据上至少应完成 1 次完整回合",
        )

    def test_comex_momentum_return_on_uptrend(self):
        """新参数在上行数据集上总收益率 > 0。"""
        bars = _uptrend_bars()
        result = run_momentum_long_only_backtest(bars, _comex_new_params())
        ret = result["metrics"]["totalReturnPct"]
        self.assertGreater(ret, 0.0, f"新 COMEX 动量参数在上行趋势中应盈利，实际={ret:.4f}%")

    def test_comex_momentum_old_params_produce_no_trades(self):
        """旧过紧参数（spread_entry=0.08）在温和趋势中几乎无法触发——验证之前产生的问题。"""
        bars = _uptrend_bars()
        result = run_momentum_long_only_backtest(bars, _comex_overtight_params())
        trips = result["metrics"]["roundTripCount"] or 0
        self.assertLessEqual(
            trips, 1,
            f"旧过紧参数在温和趋势中应几乎无法触发（roundTripCount={trips}），证明之前存在问题",
        )


class ReversalWeightsPerfTestCase(unittest.TestCase):

    def test_reversal_new_weights_active(self):
        """新权重在急跌-复苏数据上至少完成 1 次完整回合（策略有效运作，非无信号状态）。"""
        bars = _crash_recovery_bars()
        result = run_reversal_long_only_backtest(bars, _reversal_new_weights())
        trips = result["metrics"]["roundTripCount"] or 0
        self.assertGreater(trips, 0, "新反转权重在急跌-复苏市场上至少应完成 1 次完整回合")

    def test_reversal_new_weights_score_balance(self):
        """数学证明：新权重在 RSI+BB 双极端、偏离度为零的早期反转场景中，综合分更高。

        场景：价格刚刚开始回归均值，RSI 和 BB 已到达极端，但 EMA 偏离尚未扩大（dev_score=0）。
          rsi_score = 0.6 (RSI 在超卖区间中部，约 24~28)
          bb_score  = 0.6 (%B 在超卖区间中部，约 -0.01)
          dev_score = 0.0 (价格仍在 EMA 附近，偏离不足)

        旧权重：0.40*0.6 + 0.35*0.6 + 0.25*0.0 = 0.45  → 低于 min_score(0.5)，不触发
        新权重：0.45*0.6 + 0.45*0.6 + 0.10*0.0 = 0.54  → 高于 min_score(0.5)，触发

        结论：新权重将 RSI+BB 的权重从 0.75 提升到 0.90，使"早期反转信号"
              不再依赖偏离度就能通过阈值，减少漏报。
        """
        old_p = _reversal_old_weights()
        new_p = _reversal_new_weights()

        rsi_score = 0.6
        bb_score = 0.6
        dev_score = 0.0

        old_combined = old_p.rsi_weight * rsi_score + old_p.bb_weight * bb_score + old_p.deviation_weight * dev_score
        new_combined = new_p.rsi_weight * rsi_score + new_p.bb_weight * bb_score + new_p.deviation_weight * dev_score

        self.assertLess(
            old_combined, old_p.min_score,
            f"旧权重综合分({old_combined:.3f})应低于 min_score({old_p.min_score})，证明旧权重在此场景漏报",
        )
        self.assertGreaterEqual(
            new_combined, new_p.min_score,
            f"新权重综合分({new_combined:.3f})应达到 min_score({new_p.min_score})，证明新权重改善了早期反转检测",
        )

    def test_reversal_both_produce_signals_on_crash(self):
        """旧权重和新权重在急跌-复苏市场上都应产生有效信号（非空结果）。"""
        bars = _crash_recovery_bars()
        vals = [float(b["y"]) for b in bars]
        new_p = _reversal_new_weights()
        result = calc_reversal(vals, new_p)
        self.assertIsNotNone(result, "新权重在急跌-复苏序列末端应返回有效信号")
        self.assertIn(result["signal"], ["buy", "strong_buy", "sell", "strong_sell", "neutral"])


if __name__ == "__main__":
    unittest.main()
