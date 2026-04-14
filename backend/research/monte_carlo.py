"""沪银短时价格变化蒙特卡洛（GBM 缩放近似与历史 Bootstrap）。"""

from __future__ import annotations

import math
import statistics
import time
from typing import Any, Literal

DriftMode = Literal["zero", "estimated"]
ModelName = Literal["gbm", "bootstrap"]


def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    return float(statistics.median(xs))


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    idx = p * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_vals[lo]
    w = idx - lo
    return sorted_vals[lo] * (1 - w) + sorted_vals[hi] * w


def _filter_window(samples: list[dict[str, Any]], window_minutes: int, now_ms: int) -> list[dict[str, Any]]:
    if window_minutes <= 0:
        window_minutes = 60
    cutoff = now_ms - window_minutes * 60 * 1000
    return [s for s in samples if int(s.get("ts", 0)) >= cutoff and float(s.get("price", 0)) > 0]


def _log_returns_and_dt(
    ordered: list[dict[str, Any]],
) -> tuple[list[float], list[float], list[str]]:
    warnings: list[str] = []
    dts: list[float] = []
    log_rets: list[float] = []
    for i in range(1, len(ordered)):
        t0 = int(ordered[i - 1]["ts"])
        t1 = int(ordered[i]["ts"])
        p0 = float(ordered[i - 1]["price"])
        p1 = float(ordered[i]["price"])
        if p0 <= 0 or p1 <= 0:
            continue
        dt_sec = (t1 - t0) / 1000.0
        if dt_sec <= 0:
            warnings.append("non_positive_dt_skipped")
            continue
        dts.append(dt_sec)
        log_rets.append(math.log(p1 / p0))
    return log_rets, dts, warnings


def _histogram(sorted_vals: list[float], bins: int) -> dict[str, Any]:
    if not sorted_vals or bins < 1:
        return {"bins": bins, "counts": [], "edges": []}
    lo = sorted_vals[0]
    hi = sorted_vals[-1]
    if lo == hi:
        return {
            "bins": bins,
            "counts": [len(sorted_vals)] + [0] * (bins - 1),
            "edges": [lo - 1e-9 + (2e-9) * i / bins for i in range(bins + 1)],
        }
    edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]
    counts = [0] * bins
    for v in sorted_vals:
        if v >= hi:
            counts[-1] += 1
            continue
        k = int((v - lo) / (hi - lo) * bins)
        k = min(max(k, 0), bins - 1)
        counts[k] += 1
    return {"bins": bins, "counts": counts, "edges": [round(e, 6) for e in edges]}


def _path_preview_chart(
    *,
    s0: float,
    h: float,
    path_steps: int,
    preview_n: int,
    model: ModelName,
    mu_per_sec: float,
    var_per_sec: float,
    log_rets: list[float],
    dt_median: float,
    rng: Any,
) -> dict[str, Any]:
    """在 [0, h] 上均分 path_steps 段，生成若干条独立模拟价路径（用于可视化）。"""
    path_steps = max(4, min(60, int(path_steps)))
    preview_n = max(1, min(60, int(preview_n)))
    dt_step = h / path_steps if path_steps > 0 else h
    time_sec = [round(i * dt_step, 6) for i in range(path_steps + 1)]
    paths_out: list[list[float]] = []
    inv_dt = 1.0 / dt_median if dt_median > 1e-9 else 0.0
    for _ in range(preview_n):
        s = s0
        series = [round(s, 4)]
        for __ in range(path_steps):
            if model == "gbm":
                sig = math.sqrt(max(0.0, var_per_sec * dt_step))
                r = rng.gauss(mu_per_sec * dt_step, sig)
            else:
                r = rng.choice(log_rets) * (dt_step * inv_dt)
            s = s * math.exp(r)
            series.append(round(s, 4))
        paths_out.append(series)
    return {
        "timeSec": time_sec,
        "paths": paths_out,
        "pathCount": preview_n,
        "steps": path_steps,
    }


def run_huyin_monte_carlo(
    samples: list[dict[str, Any]],
    *,
    horizon_sec: int,
    paths: int,
    model: ModelName,
    drift: DriftMode,
    window_minutes: int,
    min_returns: int,
    max_paths: int,
    histogram_bins: int,
    rng: Any,
    path_preview_count: int = 40,
    path_steps: int = 28,
) -> tuple[dict[str, Any] | None, list[str]]:
    """
    返回 (payload, warnings)。样本不足等致命问题返回 (None, warnings)。
    """
    warnings: list[str] = []
    now_ms = int(time.time() * 1000)
    if horizon_sec not in (1, 5):
        return None, ["horizon_must_be_1_or_5"]

    paths = max(100, min(int(paths), int(max_paths)))

    filtered = _filter_window(samples, window_minutes, now_ms)
    if len(filtered) < 2:
        return None, ["not_enough_samples_in_window"]

    ordered = sorted(filtered, key=lambda s: int(s["ts"]))
    s0 = float(ordered[-1]["price"])
    if s0 <= 0:
        return None, ["invalid_last_price"]

    log_rets, dts, w2 = _log_returns_and_dt(ordered)
    warnings.extend(w2)

    if len(log_rets) < min_returns:
        return None, [f"need_at_least_{min_returns}_log_returns", f"got_{len(log_rets)}"]

    dt_median = _median(dts)
    if dt_median <= 1e-6:
        return None, ["median_dt_too_small"]

    var_r = statistics.pvariance(log_rets) if len(log_rets) > 1 else 0.0
    mean_r = statistics.mean(log_rets)
    var_per_sec = var_r / dt_median
    mu_per_sec = mean_r / dt_median if drift == "estimated" else 0.0

    h = float(horizon_sec)
    mu_H = mu_per_sec * h
    var_H = max(0.0, var_per_sec * h)
    std_H = math.sqrt(var_H)

    n_boot_steps = max(1, math.ceil(h / dt_median))

    deltas: list[float] = []
    for _ in range(paths):
        if model == "gbm":
            log_r = rng.gauss(mu_H, std_H)
        else:
            s_log = 0.0
            for _s in range(n_boot_steps):
                s_log += rng.choice(log_rets)
            log_r = s_log
        delta_pct = (math.exp(log_r) - 1.0) * 100.0
        deltas.append(delta_pct)

    deltas.sort()
    mean_d = statistics.mean(deltas)
    stdev_d = statistics.pstdev(deltas) if len(deltas) > 1 else 0.0
    p_up = sum(1 for d in deltas if d > 0) / len(deltas)

    pct = {
        "p5": round(_percentile(deltas, 0.05), 6),
        "p25": round(_percentile(deltas, 0.25), 6),
        "p50": round(_percentile(deltas, 0.50), 6),
        "p75": round(_percentile(deltas, 0.75), 6),
        "p95": round(_percentile(deltas, 0.95), 6),
    }

    def _price_from_delta_pct(dpc: float) -> float:
        return round(s0 * (1.0 + dpc / 100.0), 4)

    prices_pct = {k: _price_from_delta_pct(float(v)) for k, v in pct.items()}
    price_mean = _price_from_delta_pct(mean_d)
    price_stdev_lin = round(abs(s0 * stdev_d / 100.0), 4) if stdev_d else 0.0

    hist = _histogram(deltas, histogram_bins)

    path_chart: dict[str, Any] | None = None
    if path_preview_count > 0:
        path_chart = _path_preview_chart(
            s0=s0,
            h=h,
            path_steps=path_steps,
            preview_n=path_preview_count,
            model=model,
            mu_per_sec=mu_per_sec,
            var_per_sec=var_per_sec,
            log_rets=log_rets,
            dt_median=dt_median,
            rng=rng,
        )

    if drift == "zero":
        warnings.append("drift_forced_zero")
    if horizon_sec < dt_median:
        warnings.append("horizon_shorter_than_median_sample_interval_calendar_extrapolation")

    payload = {
        "ok": True,
        "symbol": "huyin",
        "S0": round(s0, 4),
        "horizonSec": horizon_sec,
        "paths": paths,
        "model": model,
        "drift": drift,
        "windowMinutes": window_minutes,
        "dtMedianSec": round(dt_median, 6),
        "windowSamplePoints": len(ordered),
        "logReturnsUsed": len(log_rets),
        "meanLogReturn": round(mean_r, 8),
        "varLogReturnPerStep": round(var_r, 10),
        "probUp": round(p_up, 6),
        "deltaPctMean": round(mean_d, 6),
        "deltaPctStdev": round(stdev_d, 6),
        "percentiles": pct,
        "pricesPercentiles": prices_pct,
        "priceMean": price_mean,
        "priceStdevLinApprox": price_stdev_lin,
        "histogram": hist,
        "warnings": warnings,
    }
    if path_chart is not None:
        payload["pathChart"] = path_chart
    return payload, warnings
