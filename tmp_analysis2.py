import sqlite3, time, math
from datetime import datetime

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

bars = [{'t': r[0], 'y': r[1]} for r in rows]
prices = [r[1] for r in rows]

print('=== COMEX Silver (XAG) Last 5min Tick Overview ===')
print(f'  Points: {len(bars)}')
if bars:
    t0 = datetime.fromtimestamp(rows[0][0]/1000).strftime('%H:%M:%S')
    t1 = datetime.fromtimestamp(rows[-1][0]/1000).strftime('%H:%M:%S')
    print(f'  Time: {t0} -> {t1}')
    print(f'  Price: {min(prices):.3f} -> {max(prices):.3f}')
    print(f'  Change: {((max(prices)-min(prices))/min(prices)*100):.4f}%')
    mean = sum(prices)/len(prices)
    cv = math.sqrt(sum((p-mean)**2 for p in prices)/len(prices))/mean * 100
    print(f'  CV: {cv:.4f}%')
    intervals = [rows[i+1][0]-rows[i][0] for i in range(len(rows)-1)]
    print(f'  Avg interval: {sum(intervals)/len(intervals)/1000:.1f}s')
    print(f'  Min interval: {min(intervals)/1000:.1f}s')
    print(f'  Max interval: {max(intervals)/1000:.1f}s')
    print(f'  Expected (FAST_POLL=3s): ~100 points, Actual: {len(bars)} points')

# Momentum backtest
from backend.backtest import run_momentum_backtest, BacktestConfig
from backend.strategies.momentum import MomentumParams

print('\n=== [A] Momentum Strategy Backtest ===')

configs = [
    ('Default realtime (strict)', MomentumParams(
        short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
        slope_entry=0.015, strength_multiplier=250, cooldown_bars=2,
        bb_period=10, bb_mult=2.0, rsi_period=10,
        bb_buy_kill=0.3, bb_sell_kill=0.7, min_volatility_pct=0.03)),
    ('No vol filter', MomentumParams(
        short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
        slope_entry=0.015, strength_multiplier=250, cooldown_bars=2,
        bb_period=10, bb_mult=2.0, rsi_period=10,
        bb_buy_kill=0.3, bb_sell_kill=0.7, min_volatility_pct=0.0)),
    ('Loose thresholds', MomentumParams(
        short_p=3, long_p=10, spread_entry=0.01, spread_strong=0.03,
        slope_entry=0.005, strength_multiplier=250, cooldown_bars=1,
        bb_period=8, bb_mult=2.0, rsi_period=8,
        bb_buy_kill=0.2, bb_sell_kill=0.8, min_volatility_pct=0.0)),
    ('Ultra-sensitive', MomentumParams(
        short_p=3, long_p=8, spread_entry=0.005, spread_strong=0.015,
        slope_entry=0.003, strength_multiplier=250, cooldown_bars=0,
        bb_period=5, bb_mult=1.5, rsi_period=5,
        bb_buy_kill=0.1, bb_sell_kill=0.9, min_volatility_pct=0.0)),
]

bt_cfg = BacktestConfig(mode='long_only', commission_rate=0.0, slippage_pct=0.0)

for name, params in configs:
    result = run_momentum_backtest(bars, params, bt_cfg)
    m = result['metrics']
    trades = result['trades']
    print(f"\n  {name}")
    print(f"    Rounds: {m['roundTripCount']} | Return: {m['totalReturnPct']}% | MDD: {m['maxDrawdownPct']}%")
    print(f"    Sells: {m['sellCount']} | WinRate: {m['winRatePct']}% | Sharpe: {m['sharpeRatio']}")
    if trades:
        for t in trades[:4]:
            ts = datetime.fromtimestamp(t['t']/1000).strftime('%H:%M:%S')
            print(f"      {t['action'].upper()} @ {t['price']:.3f} ({t['signal']}) [{ts}]")

# Reversal backtest
from backend.backtest import run_reversal_backtest
from backend.strategies.reversal import ReversalParams

print('\n=== [B] Reversal Strategy Backtest ===')

rev_configs = [
    ('Default', ReversalParams(
        rsi_period=10, rsi_oversold=30, rsi_overbought=70,
        rsi_extreme_low=20, rsi_extreme_high=80,
        bb_period=10, bb_mult=2.0, pctb_low=0.05, pctb_high=0.95,
        ema_period=10, deviation_entry=1.5, deviation_strong=2.5,
        rsi_weight=0.4, bb_weight=0.35, deviation_weight=0.25,
        min_score=0.5, strong_score=0.8, cooldown_bars=2)),
    ('Sensitive (min_score=0.3)', ReversalParams(
        rsi_period=8, rsi_oversold=35, rsi_overbought=65,
        rsi_extreme_low=15, rsi_extreme_high=85,
        bb_period=8, bb_mult=1.5, pctb_low=0.1, pctb_high=0.9,
        ema_period=8, deviation_entry=0.8, deviation_strong=1.5,
        rsi_weight=0.4, bb_weight=0.35, deviation_weight=0.25,
        min_score=0.3, strong_score=0.6, cooldown_bars=1)),
]

for name, params in rev_configs:
    result = run_reversal_backtest(bars, params, bt_cfg)
    m = result['metrics']
    trades = result['trades']
    print(f"\n  {name}")
    print(f"    Rounds: {m['roundTripCount']} | Return: {m['totalReturnPct']}% | MDD: {m['maxDrawdownPct']}%")
    print(f"    Sells: {m['sellCount']} | WinRate: {m['winRatePct']}% | Sharpe: {m['sharpeRatio']}")
    if trades:
        for t in trades[:4]:
            ts = datetime.fromtimestamp(t['t']/1000).strftime('%H:%M:%S')
            print(f"      {t['action'].upper()} @ {t['price']:.3f} ({t['signal']}) [{ts}]")

# Signal analysis
print('\n=== [C] Per-bar Signal Analysis (Default Momentum) ===')
from backend.strategies.momentum import calc_momentum

p = configs[0][1]
counts = {'buy': 0, 'strong_buy': 0, 'sell': 0, 'strong_sell': 0, 'neutral': 0}
for i in range(len(prices)):
    if i < p.long_p + 2:
        continue
    window = prices[:i+1]
    sig = calc_momentum(window, p)
    if sig:
        counts[sig['signal']] += 1

print(f"  Signals: {counts}")
total = sum(counts.values())
non_neutral = counts['buy']+counts['strong_buy']+counts['sell']+counts['strong_sell']
print(f"  Non-neutral: {non_neutral/total*100:.1f}%")
print(f"  KEY: CV={cv:.4f}% < min_volatility_pct={p.min_volatility_pct}% => ALL directional signals suppressed to neutral")
