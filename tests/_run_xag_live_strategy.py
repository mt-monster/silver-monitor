"""读取 data/ticks.db 中的 COMEX 银 tick，运行实盘验证策略报告。

运行：
    python tests/_run_xag_live_strategy.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.strategies.xag_live import (  # noqa: E402
    XAGLiveParams,
    load_available_xag_dates,
    load_xag_ticks_for_date,
    simulate_xag_live_strategy,
    walk_forward_xag_validation,
)


def main() -> None:
    dates = load_available_xag_dates()
    print(f"COMEX 银有效 tick 日期：{dates}")
    for date_str in dates:
        ticks = load_xag_ticks_for_date(date_str)
        result = simulate_xag_live_strategy(ticks, XAGLiveParams(), signal_step=5)
        print(
            f"{date_str}: ticks={len(ticks):>5} "
            f"trades={result['metrics']['tradeCount']:>3} "
            f"ret={result['metrics']['totalReturnPct']:>8.4f}% "
            f"win={result['metrics']['winRatePct']:>6.2f}% "
            f"pf={result['metrics']['profitFactor']:>6}"
        )

    wf = walk_forward_xag_validation(dates)
    print("\nWalk-forward OOS 汇总：")
    print(json.dumps(wf["oosOverall"], ensure_ascii=False, indent=2))

    out_path = Path(__file__).resolve().parent.parent / "backtest_xag_live_strategy.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告已保存：{out_path}")


if __name__ == "__main__":
    main()
