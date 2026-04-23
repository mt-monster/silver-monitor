#!/usr/bin/env python3
"""验证 MTF + Combined 信号功能的完整测试脚本。"""

import sqlite3
import sys
sys.path.insert(0, '.')

from backend.backtest import (
    run_momentum_backtest, run_reversal_backtest, run_combined_backtest, BacktestConfig
)
from backend.strategies.momentum import MomentumParams
from backend.strategies.reversal import ReversalParams
from backend.strategies.combined import CombinedSignalParams
from backend.strategies.mtf import calc_trend_direction


def load_latest_bars(instrument_id: str = "xag", minutes: int = 5) -> list[dict]:
    conn = sqlite3.connect("data/ticks.db")
    cur = conn.execute("SELECT MAX(timestamp_ms) FROM ticks WHERE instrument_id = ?", (instrument_id,))
    max_ts = cur.fetchone()[0]
    start_ms = max_ts - minutes * 60 * 1000
    cur = conn.execute(
        "SELECT timestamp_ms, price FROM ticks WHERE instrument_id = ? AND timestamp_ms >= ? AND timestamp_ms <= ? ORDER BY timestamp_ms",
        (instrument_id, start_ms, max_ts),
    )
    rows = cur.fetchall()
    conn.close()
    bars = [{"t": int(r[0]), "y": float(r[1])} for r in rows]
    # 1s aggregate
    grouped = {}
    for b in bars:
        sec = b["t"] // 1000
        grouped[sec] = b
    return [{"t": sec * 1000, "y": b["y"]} for sec, b in sorted(grouped.items())]


def test_mtf_logic():
    print("=" * 60)
    print("TEST 1: MTF 趋势判断逻辑")
    print("=" * 60)

    # 明显上升趋势
    up_closes = [78.0 + i * 0.02 for i in range(50)]
    r = calc_trend_direction(up_closes)
    assert r["trend"] == "up", f"Expected up, got {r['trend']}"
    print(f"  [PASS] 上升趋势识别: {r['trend']} (spread={r['spreadPct']}%, conf={r['confidence']})")

    # 明显下降趋势
    down_closes = [78.0 - i * 0.015 for i in range(50)]
    r = calc_trend_direction(down_closes)
    assert r["trend"] == "down", f"Expected down, got {r['trend']}"
    print(f"  [PASS] 下降趋势识别: {r['trend']} (spread={r['spreadPct']}%, conf={r['confidence']})")

    # 横盘
    flat_closes = [78.0 + (i % 3 - 1) * 0.001 for i in range(50)]
    r = calc_trend_direction(flat_closes)
    assert r["trend"] == "sideways", f"Expected sideways, got {r['trend']}"
    print(f"  [PASS] 横盘趋势识别: {r['trend']} (spread={r['spreadPct']}%)")


def test_mtf_filter():
    print("\n" + "=" * 60)
    print("TEST 2: MTF 反转信号过滤")
    print("=" * 60)

    from backend.strategies.mtf import apply_mtf_to_reversal

    # 大局跌时，反转 buy 应被过滤
    rev_buy = {"signal": "buy", "strength": 60}
    filtered = apply_mtf_to_reversal(rev_buy, "down")
    assert filtered["signal"] == "neutral", f"Expected neutral, got {filtered['signal']}"
    assert filtered.get("mtfFiltered") is True
    print(f"  [PASS] 大局跌 + 反转buy → neutral (filtered)")

    # 大局跌时，反转 sell 应保持
    rev_sell = {"signal": "sell", "strength": 60}
    filtered = apply_mtf_to_reversal(rev_sell, "down")
    assert filtered["signal"] == "sell"
    print(f"  [PASS] 大局跌 + 反转sell → sell (保留)")

    # 大局涨时，反转 sell 应被过滤
    rev_sell = {"signal": "sell", "strength": 60}
    filtered = apply_mtf_to_reversal(rev_sell, "up")
    assert filtered["signal"] == "neutral"
    print(f"  [PASS] 大局涨 + 反转sell → neutral (filtered)")

    # 大局涨时，反转 buy 应保持
    rev_buy = {"signal": "buy", "strength": 60}
    filtered = apply_mtf_to_reversal(rev_buy, "up")
    assert filtered["signal"] == "buy"
    print(f"  [PASS] 大局涨 + 反转buy → buy (保留)")


def test_combined_logic():
    print("\n" + "=" * 60)
    print("TEST 3: 组合信号开关逻辑")
    print("=" * 60)

    from backend.strategies.combined import calc_combined_signal

    cp = CombinedSignalParams(require_strong_to_trade=True, conflict_preference="reversal")

    # Case A: 双 neutral
    c = calc_combined_signal({"signal": "neutral"}, {"signal": "neutral"}, "sideways", cp)
    assert c["signal"] == "neutral"
    assert c["reason"] == "双策略均观望"
    print(f"  [PASS] 双neutral → neutral (空仓观望)")

    # Case B: 动量 strong_buy, 反转 neutral
    c = calc_combined_signal({"signal": "strong_buy", "strength": 90}, {"signal": "neutral"}, "sideways", cp)
    assert c["signal"] == "strong_buy"
    assert c["source"] == "momentum"
    print(f"  [PASS] 动量强多 + 反转观望 → strong_buy (来源: 动量)")

    # Case C: 动量 neutral, 反转 strong_sell
    c = calc_combined_signal({"signal": "neutral"}, {"signal": "strong_sell", "strength": 85}, "sideways", cp)
    assert c["signal"] == "strong_sell"
    assert c["source"] == "reversal"
    print(f"  [PASS] 动量观望 + 反转强空 → strong_sell (来源: 反转)")

    # Case D: 方向冲突，优先反转（需 strong 信号）
    cp_weak = CombinedSignalParams(require_strong_to_trade=False, conflict_preference="reversal")
    c = calc_combined_signal({"signal": "buy", "strength": 50}, {"signal": "sell", "strength": 60}, "sideways", cp_weak)
    assert c["signal"] == "sell"
    assert c["source"] == "reversal"
    print(f"  [PASS] 动量buy + 反转sell → sell (冲突优先反转)")

    # Case D2: 强信号冲突，优先反转
    c = calc_combined_signal({"signal": "strong_buy", "strength": 80}, {"signal": "strong_sell", "strength": 90}, "sideways", cp)
    assert c["signal"] == "strong_sell"
    assert c["source"] == "reversal"
    print(f"  [PASS] 动量强买 + 反转强卖 → strong_sell (强冲突优先反转)")

    # Case E: 双 strong 同向
    c = calc_combined_signal({"signal": "strong_buy", "strength": 80}, {"signal": "strong_buy", "strength": 90}, "up", cp)
    assert c["signal"] == "strong_buy"
    assert c["source"] == "combined"
    assert "共振" in c["reason"]
    print(f"  [PASS] 双策略强多共振 → strong_buy (来源: 共振)")

    # Case F: MTF 过滤生效
    c = calc_combined_signal(
        {"signal": "neutral"},
        {"signal": "buy", "strength": 60},  # 反转想抄底
        "down",  # 但大局跌
        cp
    )
    assert c["signal"] == "neutral"
    print(f"  [PASS] 反转buy被MTF下跌过滤 → neutral")


def test_backtest():
    print("\n" + "=" * 60)
    print("TEST 4: 组合信号回测引擎")
    print("=" * 60)

    bars = load_latest_bars("xag", 5)
    print(f"  数据: {len(bars)} 根 1s bar, 价格 {bars[0]['y']} -> {bars[-1]['y']}")

    mom_p = MomentumParams(short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
                           slope_entry=0.015, cooldown_bars=2, bb_period=10, rsi_period=10)
    rev_p = ReversalParams(rsi_period=5, rsi_oversold=28, rsi_overbought=72,
                           deviation_entry=0.15, deviation_strong=0.4,
                           bb_period=5, ema_period=5, min_score=0.35, strong_score=0.65, cooldown_bars=1)

    # 动量
    r_mom = run_momentum_backtest(bars, mom_p, BacktestConfig(mode="long_only"))
    print(f"  动量 LO: 收益={r_mom['metrics']['totalReturnPct']}% 交易={r_mom['metrics']['roundTripCount']}")

    # 反转
    r_rev = run_reversal_backtest(bars, rev_p, BacktestConfig(mode="long_only"))
    print(f"  反转 LO: 收益={r_rev['metrics']['totalReturnPct']}% 交易={r_rev['metrics']['roundTripCount']} 胜率={r_rev['metrics'].get('winRatePct')}")

    # 组合（强信号门槛）
    r_comb = run_combined_backtest(bars, mom_p, rev_p, CombinedSignalParams(require_strong_to_trade=True), config=BacktestConfig(mode="long_only"))
    print(f"  组合 LO(强门槛): 收益={r_comb['metrics']['totalReturnPct']}% 交易={r_comb['metrics']['roundTripCount']}")

    # 组合（无强信号门槛）
    r_comb2 = run_combined_backtest(bars, mom_p, rev_p, CombinedSignalParams(require_strong_to_trade=False), config=BacktestConfig(mode="long_only"))
    print(f"  组合 LO(无门槛): 收益={r_comb2['metrics']['totalReturnPct']}% 交易={r_comb2['metrics']['roundTripCount']}")

    # 组合 Long-Short
    r_comb3 = run_combined_backtest(bars, mom_p, rev_p, CombinedSignalParams(require_strong_to_trade=False), config=BacktestConfig(mode="long_short"))
    print(f"  组合 LS(无门槛): 收益={r_comb3['metrics']['totalReturnPct']}% 交易={r_comb3['metrics']['roundTripCount']} 胜率={r_comb3['metrics'].get('winRatePct')}")


def main():
    test_mtf_logic()
    test_mtf_filter()
    test_combined_logic()
    test_backtest()
    print("\n" + "=" * 60)
    print("所有测试通过！")
    print("=" * 60)


if __name__ == "__main__":
    main()
