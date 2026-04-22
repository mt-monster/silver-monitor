import sqlite3, time, math
from datetime import datetime

# ── 1. 加载最近5分钟 tick 数据 ──
now = int(time.time() * 1000)
cutoff = now - 5 * 60 * 1000

db_path = 'd:/coding/silver-monitor/data/ticks.db'
conn = sqlite3.connect(db_path)
cur = conn.execute(
    'SELECT timestamp_ms, price FROM ticks WHERE instrument_id=? AND timestamp_ms >= ? ORDER BY timestamp_ms',
    ('xag', cutoff)
)
rows = cur.fetchall()
conn.close()

bars = [{"t": r[0], "y": r[1]} for r in rows]
prices = [r[1] for r in rows]

print("=" * 60)
print("COMEX 银 (XAG) 过去5分钟 Tick 数据概况")
print("=" * 60)
print(f"  数据点数: {len(bars)}")
print(f"  时间范围: {datetime.fromtimestamp(rows[0][0]/1000).strftime('%H:%M:%S')} -> {datetime.fromtimestamp(rows[-1][0]/1000).strftime('%H:%M:%S')}")
print(f"  价格范围: {min(prices):.3f} -> {max(prices):.3f}")
print(f"  价格变化: {((max(prices)-min(prices))/min(prices)*100):.4f}%")
print(f"  标准差:   {math.sqrt(sum((p-sum(prices)/len(prices))**2 for p in prices)/len(prices)):.4f}")
mean = sum(prices)/len(prices)
cv = math.sqrt(sum((p-mean)**2 for p in prices)/len(prices))/mean * 100
print(f"  CV:       {cv:.4f}%")
print()

# ── 2. 动量策略回测 ──
from backend.backtest import run_momentum_backtest, BacktestConfig
from backend.strategies.momentum import MomentumParams

print("=" * 60)
print("【A】动量策略回测")
print("=" * 60)

momentum_configs = [
    ("默认 realtime 参数 (strict)", MomentumParams(
        short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
        slope_entry=0.015, strength_multiplier=250, cooldown_bars=2,
        bb_period=10, bb_mult=2.0, rsi_period=10,
        bb_buy_kill=0.3, bb_sell_kill=0.7, min_volatility_pct=0.03)),
    ("关闭波动率过滤", MomentumParams(
        short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
        slope_entry=0.015, strength_multiplier=250, cooldown_bars=2,
        bb_period=10, bb_mult=2.0, rsi_period=10,
        bb_buy_kill=0.3, bb_sell_kill=0.7, min_volatility_pct=0.0)),
    ("降低阈值 + 无波动过滤", MomentumParams(
        short_p=3, long_p=10, spread_entry=0.01, spread_strong=0.03,
        slope_entry=0.005, strength_multiplier=250, cooldown_bars=1,
        bb_period=8, bb_mult=2.0, rsi_period=8,
        bb_buy_kill=0.2, bb_sell_kill=0.8, min_volatility_pct=0.0)),
    ("超灵敏 (spread=0.005)", MomentumParams(
        short_p=3, long_p=8, spread_entry=0.005, spread_strong=0.015,
        slope_entry=0.003, strength_multiplier=250, cooldown_bars=0,
        bb_period=5, bb_mult=1.5, rsi_period=5,
        bb_buy_kill=0.1, bb_sell_kill=0.9, min_volatility_pct=0.0)),
]

bt_cfg = BacktestConfig(mode="long_only", commission_rate=0.0, slippage_pct=0.0)

for name, params in momentum_configs:
    result = run_momentum_backtest(bars, params, bt_cfg)
    m = result["metrics"]
    trades = result["trades"]
    print(f"\n  {name}")
    print(f"    交易: {m['roundTripCount']} 回合 | 收益: {m['totalReturnPct']}% | 回撤: {m['maxDrawdownPct']}%")
    print(f"    卖出: {m['sellCount']} | 胜率: {m['winRatePct']}% | 夏普: {m['sharpeRatio']}")
    if trades:
        for t in trades[:4]:
            ts = datetime.fromtimestamp(t['t']/1000).strftime('%H:%M:%S')
            print(f"      {t['action'].upper()} @ {t['price']:.3f} ({t['signal']}) [{ts}]")

# ── 3. 反转策略回测 ──
from backend.backtest import run_reversal_backtest
from backend.strategies.reversal import ReversalParams

print("\n" + "=" * 60)
print("【B】反转策略回测")
print("=" * 60)

reversal_configs = [
    ("默认参数", ReversalParams(
        rsi_period=10, rsi_oversold=30, rsi_overbought=70,
        rsi_extreme_low=20, rsi_extreme_high=80,
        bb_period=10, bb_mult=2.0, pctb_low=0.05, pctb_high=0.95,
        ema_period=10, deviation_entry=1.5, deviation_strong=2.5,
        rsi_weight=0.4, bb_weight=0.35, deviation_weight=0.25,
        min_score=0.5, strong_score=0.8, cooldown_bars=2)),
    ("更敏感 (min_score=0.3)", ReversalParams(
        rsi_period=8, rsi_oversold=35, rsi_overbought=65,
        rsi_extreme_low=15, rsi_extreme_high=85,
        bb_period=8, bb_mult=1.5, pctb_low=0.1, pctb_high=0.9,
        ema_period=8, deviation_entry=0.8, deviation_strong=1.5,
        rsi_weight=0.4, bb_weight=0.35, deviation_weight=0.25,
        min_score=0.3, strong_score=0.6, cooldown_bars=1)),
]

for name, params in reversal_configs:
    result = run_reversal_backtest(bars, params, bt_cfg)
    m = result["metrics"]
    trades = result["trades"]
    print(f"\n  {name}")
    print(f"    交易: {m['roundTripCount']} 回合 | 收益: {m['totalReturnPct']}% | 回撤: {m['maxDrawdownPct']}%")
    print(f"    卖出: {m['sellCount']} | 胜率: {m['winRatePct']}% | 夏普: {m['sharpeRatio']}")
    if trades:
        for t in trades[:4]:
            ts = datetime.fromtimestamp(t['t']/1000).strftime('%H:%M:%S')
            print(f"      {t['action'].upper()} @ {t['price']:.3f} ({t['signal']}) [{ts}]")

# ── 4. 逐 bar 信号分析 ──
print("\n" + "=" * 60)
print("【C】逐 bar 信号分析 (默认动量参数)")
print("=" * 60)

from backend.strategies.momentum import calc_momentum

p = momentum_configs[0][1]
signal_counts = {"buy": 0, "strong_buy": 0, "sell": 0, "strong_sell": 0, "neutral": 0}
for i in range(len(prices)):
    if i < p.long_p + 2:
        continue
    window = prices[:i+1]
    sig = calc_momentum(window, p)
    if sig:
        signal_counts[sig["signal"]] += 1

print(f"  信号分布: {signal_counts}")
total = sum(signal_counts.values())
non_neutral = signal_counts['buy']+signal_counts['strong_buy']+signal_counts['sell']+signal_counts['strong_sell']
print(f"  非 neutral 占比: {non_neutral/total*100:.1f}%")
print(f"  关键: 波动率 CV={cv:.4f}% < min_volatility_pct={p.min_volatility_pct}% -> 所有方向信号被压制为 neutral")
