(function () {
  const Monitor = window.Monitor;
  const { app, el } = Monitor;

  // ══════════════════════════════════════════════════════════════
  // 反转策略（均值回归）—— 前端实时计算
  // ══════════════════════════════════════════════════════════════

  Monitor.reversal = {
    hu: { last: "neutral", strength: 0 },
    co: { last: "neutral", strength: 0 },
  };

  /**
   * 前端反转信号计算（与 backend/strategies/reversal.py calc_reversal 对齐）
   * @param {Array} series  [{x, y}, ...] 价格序列
   * @param {Object} params  反转参数（来自 monitor.config.json reversal 段）
   * @returns {Object|null}
   */
  Monitor.calcReversal = function (series, params, volumes) {
    const p = params || {};
    const rsiP = p.rsi_period || 14;
    const bbP = p.bb_period || 20;
    const emaP = p.ema_period || 20;
    const minLen = Math.max(rsiP + 1, bbP, emaP) + 2;
    if (!series || series.length < minLen) return null;

    const vals = series.map(v => v.y);

    // RSI 得分
    const rsiVal = Monitor.rsiAt(vals, rsiP);
    let rsiScore = 0;
    if (rsiVal != null) {
      const oversold = p.rsi_oversold || 30;
      const overbought = p.rsi_overbought || 70;
      const extLow = p.rsi_extreme_low || 20;
      const extHigh = p.rsi_extreme_high || 80;
      if (rsiVal <= extLow) rsiScore = 1;
      else if (rsiVal <= oversold) rsiScore = (oversold - rsiVal) / (oversold - extLow);
      else if (rsiVal >= extHigh) rsiScore = -1;
      else if (rsiVal >= overbought) rsiScore = -(rsiVal - overbought) / (extHigh - overbought);
    }

    // Bollinger %B 得分
    const bbMult = p.bb_mult || 2.0;
    const bbNow = Monitor.bollingerAt(vals, bbP, bbMult);
    let bbScore = 0;
    if (bbNow) {
      const pctb = bbNow.percentB;
      const pctbLow = p.pctb_low != null ? p.pctb_low : 0.05;
      const pctbHigh = p.pctb_high != null ? p.pctb_high : 0.95;
      const pctbExtLow = p.pctb_extreme_low != null ? p.pctb_extreme_low : -0.05;
      const pctbExtHigh = p.pctb_extreme_high != null ? p.pctb_extreme_high : 1.05;
      if (pctb <= pctbExtLow) bbScore = 1;
      else if (pctb <= pctbLow) bbScore = (pctbLow - pctb) / (pctbLow - pctbExtLow);
      else if (pctb >= pctbExtHigh) bbScore = -1;
      else if (pctb >= pctbHigh) bbScore = -(pctb - pctbHigh) / (pctbExtHigh - pctbHigh);
    }

    // EMA 偏离度得分
    const emaAll = Monitor.ema(vals, emaP);
    const emaVal = emaAll[emaAll.length - 1];
    const price = vals[vals.length - 1];
    let deviationPct = 0;
    let devScore = 0;
    if (emaVal && emaVal > 0) {
      deviationPct = ((price - emaVal) / emaVal) * 100;
      const devEntry = p.deviation_entry || 1.5;
      const devStrong = p.deviation_strong || 2.5;
      const absDev = Math.abs(deviationPct);
      let raw = 0;
      if (absDev >= devStrong) raw = 1;
      else if (absDev >= devEntry) raw = (absDev - devEntry) / (devStrong - devEntry);
      devScore = deviationPct < 0 ? raw : -raw;
    }

    // 成交量融合
    let volumeRatio = null;
    const volPeriod = p.volume_period || 0;
    if (volPeriod > 0 && volumes && volumes.length >= volPeriod) {
      const volEma = Monitor.ema(volumes, volPeriod);
      if (volEma && volEma.length > 0) {
        const lastVolEma = volEma[volEma.length - 1];
        if (lastVolEma != null && lastVolEma > 0) {
          const vr = volumes[volumes.length - 1] / lastVolEma;
          if (!Number.isFinite(vr) || vr < 0) return;
          volumeRatio = vr;
          let volumeScore = 0;
          const cr = p.volume_confirm_ratio != null ? p.volume_confirm_ratio : 1.5;
          const wr = p.volume_weaken_ratio != null ? p.volume_weaken_ratio : 0.6;
          if (volumeRatio > cr) {
            if (totalScore > 0) volumeScore = Math.min(1.0, (volumeRatio - 1.0) / (cr - 1.0));
            else if (totalScore < 0) volumeScore = -Math.min(1.0, (volumeRatio - 1.0) / (cr - 1.0));
          } else if (volumeRatio < wr) {
            if (totalScore > 0) volumeScore = -0.5;
            else if (totalScore < 0) volumeScore = 0.5;
          }
          totalScore += volumeScore * (p.volume_weight || 0.15);
        }
      }
    }

    // 加权综合得分
    const wRsi = p.rsi_weight || 0.4;
    const wBb = p.bb_weight || 0.35;
    const wDev = p.deviation_weight || 0.25;
    const absScore = Math.abs(totalScore);
    const minScore = p.min_score || 0.5;
    const strongScore = p.strong_score || 0.8;

    let signal = "neutral";
    if (absScore >= strongScore) signal = totalScore > 0 ? "strong_buy" : "strong_sell";
    else if (absScore >= minScore) signal = totalScore > 0 ? "buy" : "sell";

    return {
      signal,
      score: totalScore,
      rsiScore,
      bbScore,
      devScore,
      deviationPct,
      strength: Math.min(100, absScore * 100),
      rsi: rsiVal,
      bb: bbNow,
      volumeRatio,
    };
  };

  /**
   * 渲染反转信号到 DOM
   * @param {string} prefix  "hu" 或 "co"
   * @param {Object|null} info  calcReversal 返回值
   */
  Monitor.renderReversalSignal = function (prefix, info) {
    const badge = el(prefix + "RvBadge");
    const scoreEl = el(prefix + "RvScore");
    const rsiScoreEl = el(prefix + "RvRsiScore");
    const bbScoreEl = el(prefix + "RvBbScore");
    const devScoreEl = el(prefix + "RvDevScore");
    const rsiEl = el(prefix + "RvRSI");
    const devEl = el(prefix + "RvDev");
    const bar = el(prefix + "RvBar");
    const noteEl = el(prefix + "RvNote");
    const ptsEl = el(prefix + "RvPts");

    if (!badge || !bar) return;

    if (!info) {
      badge.className = "signal-badge neutral";
      badge.textContent = "等待";
      if (scoreEl) scoreEl.textContent = "--";
      if (rsiScoreEl) rsiScoreEl.textContent = "--";
      if (bbScoreEl) bbScoreEl.textContent = "--";
      if (devScoreEl) devScoreEl.textContent = "--";
      if (rsiEl) rsiEl.textContent = "--";
      if (devEl) devEl.textContent = "--";
      bar.style.width = "50%";
      bar.className = "signal-bar-inner flat";
      if (noteEl) {
        const symbol = prefix === "hu" ? "huyin" : "comex";
        const p = Monitor.getReversalParams ? Monitor.getReversalParams(symbol) : {};
        const rsiP = p.rsi_period || 14;
        const bbP = p.bb_period || 20;
        const emaP = p.ema_period || 20;
        const minLen = Math.max(rsiP + 1, bbP, emaP) + 2;
        noteEl.textContent = `需至少 ${minLen} 个有效价格点后计算`;
      }
      if (ptsEl) ptsEl.textContent = "--";
      return;
    }

    badge.className = "signal-badge " + info.signal.replace("_", "-");
    badge.textContent = Monitor.signalLabels[info.signal];

    const fmtScore = (v) => {
      const cls = v > 0 ? "up" : v < 0 ? "down" : "";
      return `<span class="val ${cls}">${v >= 0 ? "+" : ""}${v.toFixed(3)}</span>`;
    };

    if (scoreEl) scoreEl.innerHTML = fmtScore(info.score);
    if (rsiScoreEl) rsiScoreEl.innerHTML = fmtScore(info.rsiScore);
    if (bbScoreEl) bbScoreEl.innerHTML = fmtScore(info.bbScore);
    if (devScoreEl) devScoreEl.innerHTML = fmtScore(info.devScore);

    if (rsiEl && info.rsi != null) {
      const r = info.rsi;
      const cls = r > 70 ? "up" : r < 30 ? "down" : "";
      rsiEl.innerHTML = `<span class="val ${cls}">${r.toFixed(1)}</span>`;
    } else if (rsiEl) {
      rsiEl.textContent = "--";
    }

    if (devEl) {
      const d = info.deviationPct;
      const cls = d > 0 ? "up" : d < 0 ? "down" : "";
      devEl.innerHTML = `<span class="val ${cls}">${d >= 0 ? "+" : ""}${d.toFixed(3)}%</span>`;
    }

    // 成交量比率渲染
    const volEl = el(prefix + "RvVolRatio");
    if (volEl && info.volumeRatio != null) {
      const vr = info.volumeRatio;
      const vcls = vr > 1.5 ? "up" : vr < 0.6 ? "down" : "";
      volEl.innerHTML = `<span class="val ${vcls}">${vr.toFixed(2)}x</span>`;
    } else if (volEl) {
      volEl.textContent = "--";
    }

    bar.style.width = info.strength.toFixed(0) + "%";
    bar.className = "signal-bar-inner " + (info.signal.includes("buy") ? "bull" : info.signal.includes("sell") ? "bear" : "flat");

    if (ptsEl) ptsEl.textContent = "实时";

    if (noteEl) {
      let note = `综合 ${info.score >= 0 ? "+" : ""}${info.score.toFixed(3)}`;
      if (info.rsi != null) {
        if (info.rsi < 30) note += " | RSI超卖";
        else if (info.rsi > 70) note += " | RSI超买";
      }
      if (info.bb) {
        if (info.bb.percentB < 0) note += " | 跌破下轨";
        else if (info.bb.percentB > 1) note += " | 突破上轨";
      }
      if (Math.abs(info.deviationPct) > 1.5) note += " | 偏离均值";
      noteEl.textContent = note;
    }
  };

  Monitor.updateReversalSignals = function (data) {
    // 后端可能通过 /api/all 返回或 SSE 推送 precomputed reversal signals
    const backendRv = data.reversalSignals || data.reversal_signals || Monitor.instrumentReversalSignals || {};
    const rtBuffers = data.realtimeBacktestBuffers || {};

    // fallback 时也优先使用后端 realtimeBacktestBuffers（1秒采样），确保前后端使用同一序列
    const _rtSeries = (buf) => (buf && buf.length >= 2) ? buf.map(p => ({ x: p.t, y: p.y })) : null;
    const _rtVolumes = (buf) => (buf && buf.length >= 2) ? buf.map(p => p.v).filter(v => v != null) : [];
    const huSeries = _rtSeries(rtBuffers.ag0) || app.silverLivePoints.map(p => ({ x: p.t, y: p.y }));
    const huVolumes = _rtVolumes(rtBuffers.ag0).length > 0 ? _rtVolumes(rtBuffers.ag0) : app.silverLivePoints.map(p => p.v).filter(v => v != null);
    const coSeries = _rtSeries(rtBuffers.xag) || app.comexSilverLivePoints.map(p => ({ x: p.t, y: p.y }));
    const coVolumes = _rtVolumes(rtBuffers.xag).length > 0 ? _rtVolumes(rtBuffers.xag) : app.comexSilverLivePoints.map(p => p.v).filter(v => v != null);

    const huParams = Monitor.getReversalParams("huyin");
    const coParams = Monitor.getReversalParams("comex");

    // 有效性检查：后端信号需包含至少 signal 或 rsi 等字段
    const _valid = s => s && (s.signal != null || s.score != null || s.rsi != null);

    const huSig = _valid(backendRv.ag0) ? backendRv.ag0 : Monitor.calcReversal(huSeries, huParams, huVolumes);
    const coSig = _valid(backendRv.xag) ? backendRv.xag : Monitor.calcReversal(coSeries, coParams, coVolumes);

    if (huSig && Monitor.reversal.hu.last !== huSig.signal) {
      Monitor.playSignalTone(huSig.signal);
      Monitor.reversal.hu = { last: huSig.signal, strength: huSig.strength };
    }
    if (coSig && Monitor.reversal.co.last !== coSig.signal) {
      Monitor.playSignalTone(coSig.signal);
      Monitor.reversal.co = { last: coSig.signal, strength: coSig.strength };
    }

    Monitor.renderReversalSignal("hu", huSig);
    Monitor.renderReversalSignal("co", coSig);
  };

})();
