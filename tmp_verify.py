from backend.strategies.momentum import calc_momentum, MomentumParams

# 测试1: 超低波动 (CV < 0.005) -> 阈值应为 0.0，信号不被压制
low_vol = [100.0 + i * 0.0001 for i in range(50)]
p = MomentumParams(min_volatility_pct=0.03)
result = calc_momentum(low_vol, p)
print('Test 1 - Ultra low vol (CV<0.005):')
print(f'  volatilityPct: {result.get("volatilityPct")}%')
print(f'  adaptiveThreshold: {result.get("adaptiveVolThreshold")}%')
print(f'  signal: {result["signal"]}')

# 测试2: 低波动 (CV ~ 0.01) -> 阈值应为 CV*0.3
mid_vol = [100.0 + (i % 10) * 0.01 for i in range(50)]
result2 = calc_momentum(mid_vol, p)
print('\nTest 2 - Low vol (CV~0.01):')
print(f'  volatilityPct: {result2.get("volatilityPct")}%')
print(f'  adaptiveThreshold: {result2.get("adaptiveVolThreshold")}%')

# 测试3: 正常波动 (CV > 0.03) -> 阈值应为 0.03
high_vol = [100.0 + (i % 10) * 0.05 for i in range(50)]
result3 = calc_momentum(high_vol, p)
print('\nTest 3 - Normal vol (CV>0.03):')
print(f'  volatilityPct: {result3.get("volatilityPct")}%')
print(f'  adaptiveThreshold: {result3.get("adaptiveVolThreshold")}%')

# 测试4: 用实际COMEX银最近5分钟数据回测（数据库）
print('\n=== Test 4 - Real COMEX 5min backtest with adaptive vol ===')
import sqlite3, time
now = int(time.time() * 1000)
cutoff = now - 5 * 60 * 1000
conn = sqlite3.connect('d:/coding/silver-monitor/data/ticks.db')
cur = conn.execute('SELECT timestamp_ms, price FROM ticks WHERE instrument_id=? AND timestamp_ms >= ? ORDER BY timestamp_ms', ('xag', cutoff))
rows = cur.fetchall()
conn.close()

bars = [{'t': r[0], 'y': r[1]} for r in rows]
print(f'Tick count: {len(bars)}')

from backend.backtest import run_momentum_backtest, BacktestConfig
from backend.strategies.momentum import MomentumParams

bt_cfg = BacktestConfig(mode='long_only', commission_rate=0.0, slippage_pct=0.0)

# 默认参数（带自适应波动率）
p1 = MomentumParams(
    short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
    slope_entry=0.015, strength_multiplier=250, cooldown_bars=2,
    bb_period=10, bb_mult=2.0, rsi_period=10,
    bb_buy_kill=0.3, bb_sell_kill=0.7, min_volatility_pct=0.03
)
r1 = run_momentum_backtest(bars, p1, bt_cfg)
m1 = r1['metrics']
print(f'\nDefault adaptive vol:')
print(f'  Rounds: {m1["roundTripCount"]} | Return: {m1["totalReturnPct"]}% | MDD: {m1["maxDrawdownPct"]}%')
print(f'  Sells: {m1["sellCount"]} | WinRate: {m1["winRatePct"]}%')

# 关闭波动率过滤（对比）
p2 = MomentumParams(
    short_p=5, long_p=15, spread_entry=0.03, spread_strong=0.08,
    slope_entry=0.015, strength_multiplier=250, cooldown_bars=2,
    bb_period=10, bb_mult=2.0, rsi_period=10,
    bb_buy_kill=0.3, bb_sell_kill=0.7, min_volatility_pct=0.0
)
r2 = run_momentum_backtest(bars, p2, bt_cfg)
m2 = r2['metrics']
print(f'\nNo vol filter (baseline):')
print(f'  Rounds: {m2["roundTripCount"]} | Return: {m2["totalReturnPct"]}% | MDD: {m2["maxDrawdownPct"]}%')
print(f'  Sells: {m2["sellCount"]} | WinRate: {m2["winRatePct"]}%')

# 超灵敏参数
p3 = MomentumParams(
    short_p=3, long_p=8, spread_entry=0.005, spread_strong=0.015,
    slope_entry=0.003, strength_multiplier=250, cooldown_bars=0,
    bb_period=5, bb_mult=1.5, rsi_period=5,
    bb_buy_kill=0.1, bb_sell_kill=0.9, min_volatility_pct=0.0
)
r3 = run_momentum_backtest(bars, p3, bt_cfg)
m3 = r3['metrics']
print(f'\nUltra-sensitive:')
print(f'  Rounds: {m3["roundTripCount"]} | Return: {m3["totalReturnPct"]}% | MDD: {m3["maxDrawdownPct"]}%')
print(f'  Sells: {m3["sellCount"]} | WinRate: {m3["winRatePct"]}%')

# 测试5: Tick质量指标
print('\n=== Test 5 - Tick Quality ===')
from backend.backtest_runner import _compute_tick_quality
q = _compute_tick_quality(bars)
print(f'Tick quality: {q}')

# 测试6: 实时缓冲区扫描（如果缓冲区有数据）
print('\n=== Test 6 - Realtime Buffer Scan ===')
from backend.backtest_runner import scan_5min_from_buffer
result = scan_5min_from_buffer('xag', strategy='momentum', lookback_minutes=5, param_grid=None)
if 'error' in result:
    print(f'Buffer scan error: {result["error"]} - {result.get("message", "")}')
else:
    print(f'Buffer scan OK: {result["scanned_windows"]} windows scanned')
    print(f'Tick quality: {result.get("tick_quality")}')
    best = result.get('best_window')
    if best:
        print(f'Best window: {best["start_time"]}~{best["end_time"]}')
        print(f'Best metrics: {best["best_metrics"]}')
