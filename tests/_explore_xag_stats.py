"""COMEX 银 tick 统计特性探索：寻找可利用的微观结构/动量/回归效应。"""
from __future__ import annotations
import io, sys, math, statistics
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.tick_storage import get_available_dates, get_ticks_for_date

OUT = 1_500_000_000_000
def clean(ts): return [t for t in ts if t.get("t",0)>=OUT and t.get("y")]

def autocorr(xs, lag):
    n = len(xs) - lag
    if n < 10: return None
    m = sum(xs)/len(xs)
    num = sum((xs[i]-m)*(xs[i+lag]-m) for i in range(n))
    den = sum((x-m)**2 for x in xs)
    return num/den if den>0 else None

def run_length_stats(rets):
    """连涨/连跌 run-length 分布"""
    signs = [1 if r>0 else (-1 if r<0 else 0) for r in rets]
    runs = []
    cur_sign, cur_len = 0, 0
    for s in signs:
        if s == 0: continue
        if s == cur_sign:
            cur_len += 1
        else:
            if cur_len: runs.append(cur_sign*cur_len)
            cur_sign, cur_len = s, 1
    if cur_len: runs.append(cur_sign*cur_len)
    pos_runs = [abs(r) for r in runs if r>0]
    neg_runs = [abs(r) for r in runs if r<0]
    return pos_runs, neg_runs

def variance_ratio(rets, q):
    """VR(q): Var(q-period returns) / (q * Var(1-period returns))
    VR>1 动量，VR<1 回归。"""
    if len(rets) < q*10: return None
    r1_var = statistics.variance(rets)
    q_rets = [sum(rets[i:i+q]) for i in range(0, len(rets)-q+1)]
    if len(q_rets) < 2: return None
    rq_var = statistics.variance(q_rets)
    return rq_var / (q * r1_var) if r1_var>0 else None

def main():
    for d in get_available_dates("xag"):
        ts = clean(get_ticks_for_date("xag", d))
        if len(ts) < 500: continue
        ys = [t["y"] for t in ts]
        rets = [(ys[i+1]-ys[i])/ys[i]*100 for i in range(len(ys)-1) if ys[i]>0]
        # 仅保留非零变动
        rets_nz = [r for r in rets if abs(r) > 1e-6]
        zero_frac = 1 - len(rets_nz)/len(rets) if rets else 0
        std = statistics.stdev(rets_nz) if len(rets_nz)>1 else 0
        mean = statistics.mean(rets_nz) if rets_nz else 0
        # 分位
        sr = sorted(rets_nz)
        p = lambda q: sr[int(len(sr)*q)] if sr else 0
        # autocorr
        ac1 = autocorr(rets_nz, 1)
        ac2 = autocorr(rets_nz, 2)
        ac5 = autocorr(rets_nz, 5)
        # VR
        vr2 = variance_ratio(rets, 2)
        vr5 = variance_ratio(rets, 5)
        vr15 = variance_ratio(rets, 15)
        # run-length
        pos_runs, neg_runs = run_length_stats(rets_nz)
        mean_run = (sum(pos_runs)+sum(neg_runs))/max(1,len(pos_runs)+len(neg_runs))
        max_run = max(max(pos_runs, default=0), max(neg_runs, default=0))

        print(f"\n{d}: N={len(ts)} nz_rets={len(rets_nz)} zero%={zero_frac*100:.1f}")
        print(f"  ret mean={mean:.5f}% std={std:.5f}% p1={p(.01):.4f} p5={p(.05):.4f} "
              f"p50={p(.5):.5f} p95={p(.95):.4f} p99={p(.99):.4f}")
        print(f"  AC(1)={ac1:.4f} AC(2)={ac2:.4f} AC(5)={ac5:.4f}")
        print(f"  VR(2)={vr2:.3f} VR(5)={vr5:.3f} VR(15)={vr15:.3f}  "
              f"(<1=mean-rev >1=momentum)")
        print(f"  run-len: mean={mean_run:.2f} max={max_run} pos_runs={len(pos_runs)} neg_runs={len(neg_runs)}")

if __name__ == "__main__":
    main()
