"""Inspect backtest_xag_scalping.json top-window stats for passing variants."""
import io, json, sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
d = json.load(open(Path(__file__).resolve().parent.parent / "backtest_xag_scalping.json",
                   "r", encoding="utf-8"))
for r in d["results"]:
    name = r["variant"]
    if not name.startswith(("V6", "V7", "V8", "V9")):
        continue
    print(f"\n=== {name} ===")
    top = r["top_windows"][:10]
    for w in top:
        bp = w["best_params"]
        m = w["best_metrics"]
        print(f"  date={w['date']} ticks={w['tick_count']:4d} "
              f"sp={bp.get('spread_entry'):.3f} sl={bp.get('slope_entry'):.3f} "
              f"sP={bp.get('short_p')} ret={m.get('totalReturnPct'):.3f}% "
              f"wr={m.get('winRatePct')} rt={m.get('roundTripCount')} "
              f"pf={m.get('profitFactor')} score={w['score']}")
    counts = Counter((w["best_params"].get("short_p"),
                      w["best_params"].get("spread_entry"),
                      w["best_params"].get("slope_entry")) for w in r["top_windows"])
    print(f"  top-20 (sP,spread,slope) dist: {counts.most_common(5)}")
    s = r["summary"]
    print(f"  summary: pos_rate={s['pos_rate_pct']}% win={s['avg_win_rate_pct']}% "
          f"pf={s['avg_profit_factor']} sharpe={s['avg_sharpe']} "
          f"compound={s['compound_return_pct']}% daily={s['daily_compound_pct']}")
