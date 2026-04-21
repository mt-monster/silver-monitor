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
  Monitor.calcReversal = function (series, params) {
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

    // 加权综合得分
    const wRsi = p.rsi_weight || 0.4;
    const wBb = p.bb_weight || 0.35;
    const wDev = p.deviation_weight || 0.25;
    const totalScore = rsiScore * wRsi + bbScore * wBb + devScore * wDev;
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
    const huSeries = app.silverLivePoints.map(p => ({ x: p.t, y: p.y }));
    const coSeries = app.comexSilverLivePoints.map(p => ({ x: p.t, y: p.y }));

    const huParams = Monitor.getReversalParams("huyin");
    const coParams = Monitor.getReversalParams("comex");

    const huSig = Monitor.calcReversal(huSeries, huParams);
    const coSig = Monitor.calcReversal(coSeries, coParams);

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
