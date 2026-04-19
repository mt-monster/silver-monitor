(function () {

  const Monitor = window.Monitor;

  const { app, el } = Monitor;



  Monitor.signalLabels = {

    strong_buy: "强多",

    buy: "做多",

    neutral: "观望",

    sell: "做空",

    strong_sell: "强空",

  };



  Monitor.momentum = {

    hu: { last: "neutral", strength: 0 },

    co: { last: "neutral", strength: 0 },

    au: { last: "neutral", strength: 0 },

    cg: { last: "neutral", strength: 0 },

    btc: { last: "neutral", strength: 0 },

  };



  /** 去重入队：价格未变时跳过，避免重复 tick 淹没 EMA 张口。cap 为最大长度。 */

  function _pushIfChanged(arr, price, ts, cap) {

    if (arr.length > 0 && arr[arr.length - 1].y === price) return;

    arr.push({ t: ts, y: price });

    while (arr.length > cap) arr.shift();

  }



  Monitor.ema = function (values, period) {

    if (!values.length) return [];

    const k = 2 / (period + 1);

    // SMA 种子：前 period 个值取平均作为 EMA 起点，减少冷启动偏差

    if (values.length >= period) {

      let sum = 0;

      for (let i = 0; i < period; i++) sum += values[i];

      const seed = sum / period;

      const out = new Array(period);

      // 种子期用 SMA 线性填充（保持数组长度一致）

      for (let i = 0; i < period - 1; i++) out[i] = null;

      out[period - 1] = seed;

      for (let i = period; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));

      return out;

    }

    // 数据不足一个周期，退化为简单 EMA（首值种子）

    const out = [values[0]];

    for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));

    return out;

  };



  /** 计算最后一根 bar 的 Bollinger Band */

  Monitor.bollingerAt = function (values, period, mult) {

    const n = values.length;

    if (n < period || period < 2) return null;

    let sum = 0;

    for (let i = n - period; i < n; i++) sum += values[i];

    const sma = sum / period;

    let varSum = 0;

    for (let i = n - period; i < n; i++) varSum += (values[i] - sma) ** 2;

    const std = Math.sqrt(varSum / period);

    const upper = sma + mult * std;

    const lower = sma - mult * std;

    const bw = upper - lower;

    const pctB = bw > 1e-12 ? (values[n - 1] - lower) / bw : 0.5;

    const bandwidth = sma > 0 ? (bw / sma) * 100 : 0;

    return { upper, middle: sma, lower, percentB: pctB, bandwidth };

  };



  /** RSI via Wilder's smoothing（与后端 rsi_series 对齐） */
  Monitor.rsiAt = function (values, period) {
    const n = values.length;
    if (n < period + 1) return null;
    let ag = 0, al = 0;
    for (let i = 1; i <= period; i++) {
      const d = values[i] - values[i - 1];
      ag += Math.max(d, 0);
      al += Math.max(-d, 0);
    }
    ag /= period; al /= period;
    let rsi = al < 1e-12 ? 100 : 100 - 100 / (1 + ag / al);
    for (let i = period + 1; i < n; i++) {
      const d = values[i] - values[i - 1];
      ag = (ag * (period - 1) + Math.max(d, 0)) / period;
      al = (al * (period - 1) + Math.max(-d, 0)) / period;
      rsi = al < 1e-12 ? 100 : 100 - 100 / (1 + ag / al);
    }
    return rsi;
  };

  /** RSI 超买/超卖修正信号（与后端 _fuse_with_rsi 对齐） */
  function _fuseWithRSI(sig, rsi) {
    if (sig === "buy" && rsi > 75) return "neutral";
    if (sig === "strong_buy" && rsi > 85) return "buy";
    if (sig === "sell" && rsi < 25) return "neutral";
    if (sig === "strong_sell" && rsi < 15) return "sell";
    return sig;
  }

  // Cooldown tracking per symbol: { symbol: remainingBars }
  Monitor._cooldowns = {};

  /** BB 融合修正 EMA 动量信号（与后端 _fuse_with_bb 对齐） */

  function _fuseWithBB(baseSig, pctB, bwExpanding) {

    let sig = baseSig;

    if (sig === "buy") {

      if (pctB < 0.3) sig = "neutral";

      else if (pctB > 0.5 && bwExpanding) sig = "strong_buy";

    } else if (sig === "strong_buy") {

      if (pctB > 1.0) sig = "buy";

    } else if (sig === "sell") {

      if (pctB > 0.7) sig = "neutral";

      else if (pctB < 0.5 && bwExpanding) sig = "strong_sell";

    } else if (sig === "strong_sell") {

      if (pctB < 0.0) sig = "sell";

    }

    return sig;

  }



  /** EMA 短/长 张口 + 短 EMA 斜率 + Bollinger 带融合 */

  Monitor.calcMomentum = function (series, shortP, longP, thresholds) {

    if (!series || series.length < longP + 2) return null;

    const vals = series.map(p => p.y);

    const emaS = Monitor.ema(vals, shortP);

    const emaL = Monitor.ema(vals, longP);

    const lastS = emaS[emaS.length - 1];

    const lastL = emaL[emaL.length - 1];

    const prevS = emaS[emaS.length - 2];

    if (lastS == null || lastL == null || prevS == null) return null;

    const spreadPct = lastL !== 0 ? ((lastS - lastL) / lastL) * 100 : 0;

    const slopePct = prevS !== 0 ? ((lastS - prevS) / prevS) * 100 : 0;



    const th = thresholds || Monitor.getMomentumThresholds();

    const se = th.spreadEntry;

    const ss = th.spreadStrong;

    const sl = th.slopeEntry != null ? th.slopeEntry : 0.02;

    const sm = th.strengthMul != null ? th.strengthMul : 120;

    const bbP = th.bbPeriod || 0;

    const bbM = th.bbMult || 2.0;



    let signal = "neutral";

    if (lastS > lastL && spreadPct > se && slopePct > sl) {

      signal = spreadPct > ss ? "strong_buy" : "buy";

    } else if (lastS < lastL && spreadPct < -se && slopePct < -sl) {

      signal = spreadPct < -ss ? "strong_sell" : "sell";

    }



    // Bollinger 带融合

    let bb = null;

    if (bbP > 0 && vals.length >= bbP) {

      const bbNow = Monitor.bollingerAt(vals, bbP, bbM);

      const bbPrev = vals.length > bbP ? Monitor.bollingerAt(vals.slice(0, -1), bbP, bbM) : null;

      if (bbNow) {

        const bwExpanding = bbPrev != null && bbNow.bandwidth > bbPrev.bandwidth;

        signal = _fuseWithBB(signal, bbNow.percentB, bwExpanding);

        // Squeeze detection: bandwidth <= bb_period-bar min
        let squeeze = false;
        if (vals.length >= bbP * 2) {
          let minBW = Infinity;
          for (let j = Math.max(0, vals.length - bbP - 1); j < vals.length - 1; j++) {
            const bj = Monitor.bollingerAt(vals.slice(0, j + 1), bbP, bbM);
            if (bj) minBW = Math.min(minBW, bj.bandwidth);
          }
          if (bbNow.bandwidth <= minBW) squeeze = true;
        }

        bb = { ...bbNow, bwExpanding, squeeze };

      }

    }



    // RSI fusion
    const rsiP = th.rsiPeriod || 0;
    let rsi = null;
    if (rsiP > 0 && vals.length >= rsiP + 1) {
      rsi = Monitor.rsiAt(vals, rsiP);
      if (rsi != null) signal = _fuseWithRSI(signal, rsi);
    }

    return {

      signal,

      spreadPct,

      slopePct,

      shortEMA: lastS,

      longEMA: lastL,

      strength: Math.min(100, Math.abs(spreadPct) * sm),

      bb,

      rsi,

    };

  };



  Monitor.renderSignal = function (prefix, info, decimals) {

    const symbolByPrefix = {
      hu: "huyin",
      co: "comex",
      au: "hujin",
      cg: "comex_gold",
    };

    const findEl = (...ids) => ids.map(id => el(id)).find(Boolean);

    const badge = findEl(prefix + "SignalBadge", prefix + "SigBadge");

    const slopeEl = findEl(prefix + "ROC", prefix + "SigSlope");

    const emaFastEl = findEl(prefix + "EmaF", prefix + "SigEmaS");

    const emaSlowEl = findEl(prefix + "EmaS", prefix + "SigEmaL");

    const pointsEl = findEl(prefix + "SigPts");

    const noteEl = findEl(prefix + "SigNote");

    const bar = findEl(prefix + "SigBar");



    if (!badge || !slopeEl || !emaFastEl || !emaSlowEl || !bar) return;



    if (!info) {

      badge.className = "signal-badge neutral";

      badge.textContent = "等待";

      slopeEl.textContent = "--";

      emaFastEl.textContent = "--";

      emaSlowEl.textContent = "--";

      bar.style.width = "50%";

      bar.className = "signal-bar-inner flat";

      if (pointsEl) pointsEl.textContent = "--";

      if (noteEl) {

        const symbol = symbolByPrefix[prefix];

        const lp = Monitor.getMomentumPeriods(symbol).longP ?? 20;

        const minPts = lp + 2;

        noteEl.textContent = `需至少 ${minPts} 个有效价格点后计算`;

      }

      return;

    }



    badge.className = "signal-badge " + info.signal.replace("_", "-");

    badge.textContent = Monitor.signalLabels[info.signal];

    const sl = info.slopePct;

    slopeEl.innerHTML = `<span class="val ${sl >= 0 ? "up" : "down"}">${sl >= 0 ? "+" : ""}${sl.toFixed(3)}%</span>`;

    emaFastEl.textContent = info.shortEMA.toFixed(decimals);

    emaSlowEl.textContent = info.longEMA.toFixed(decimals);

    bar.style.width = info.strength.toFixed(0) + "%";

    bar.className = "signal-bar-inner " + (info.signal.includes("buy") ? "bull" : info.signal.includes("sell") ? "bear" : "flat");

    if (pointsEl) pointsEl.textContent = "实时";

    // BB 指标渲染

    const bollBEl = findEl(prefix + "BollB");

    const bollBWEl = findEl(prefix + "BollBW");

    if (bollBEl && info.bb) {

      const b = info.bb.percentB;

      const cls = b > 0.8 ? "up" : b < 0.2 ? "down" : "";

      bollBEl.innerHTML = `<span class="val ${cls}">${b.toFixed(2)}</span>`;

    } else if (bollBEl) {

      bollBEl.textContent = "--";

    }

    if (bollBWEl && info.bb) {

      bollBWEl.textContent = info.bb.bandwidth.toFixed(2) + "%";

    } else if (bollBWEl) {

      bollBWEl.textContent = "--";

    }



    if (noteEl) {

      let note = `动量差 ${info.spreadPct >= 0 ? "+" : ""}${info.spreadPct.toFixed(3)}%`;

      if (info.bb) {

        const b = info.bb.percentB;

        if (info.bb.squeeze) note += " | Boll缩口";

        else if (b > 1.0) note += " | 超买";

        else if (b < 0.0) note += " | 超卖";

        else if (info.bb.bwExpanding) note += " | 带宽扩张";

      }

      noteEl.textContent = note;

    }

    // RSI 指标渲染
    const rsiEl = findEl(prefix + "RSI");
    if (rsiEl && info.rsi != null) {
      const r = info.rsi;
      const rcls = r > 70 ? "up" : r < 30 ? "down" : "";
      rsiEl.innerHTML = `<span class="val ${rcls}">${r.toFixed(1)}</span>`;
    } else if (rsiEl) {
      rsiEl.textContent = "--";
    }

  };



  Monitor.refreshMomentumLabels = function () {

    const { shortP, longP } = Monitor.momentumPeriods?.default || { shortP: 5, longP: 20 };

    const tag = `EMA${shortP}/${longP}+Boll（动量+带融合）`;

    document.querySelectorAll(".signal-card .ema-tag").forEach(node => {

      node.textContent = tag;

    });

    document.querySelectorAll(".momentum-roc-label").forEach(node => {

      node.textContent = "短线斜率";

    });

  };



  Monitor.playSignalTone = function (signal) {

    try {

      const enabled = localStorage.getItem("signalSound") !== "off";

      if (!enabled || !["strong_buy", "strong_sell"].includes(signal)) return;



      const Ctx = window.AudioContext || window.webkitAudioContext;

      if (!Ctx) return;

      app.audioCtx = app.audioCtx || new Ctx();

      if (app.audioCtx.state === "suspended") app.audioCtx.resume();



      const ctx = app.audioCtx;

      const osc = ctx.createOscillator();

      const gain = ctx.createGain();

      osc.connect(gain);

      gain.connect(ctx.destination);

      osc.type = signal === "strong_buy" ? "triangle" : "sawtooth";

      osc.frequency.value = signal === "strong_buy" ? 880 : 440;

      gain.gain.setValueAtTime(0.0001, ctx.currentTime);

      gain.gain.exponentialRampToValueAtTime(0.04, ctx.currentTime + 0.01);

      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);

      osc.start(ctx.currentTime);

      osc.stop(ctx.currentTime + 0.2);

    } catch (_) {}

  };



  Monitor.updateMomentumSignals = function (data) {

    const backendSignals = data.signals || data._signals || Monitor.instrumentSignals || {};

    const hu = data.huyin;

    const co = data.comex;

    if (hu && !hu.error && !hu.closed && hu.price > 0) _pushIfChanged(app.silverLivePoints, hu.price, hu.timestamp || Date.now(), 180);

    if (co && !co.error && !co.closed && co.price > 0) _pushIfChanged(app.comexSilverLivePoints, co.price, co.timestamp || Date.now(), 180);



    const huSeries = app.silverLivePoints.map(p => ({ x: p.t, y: p.y }));

    const coSeries = app.comexSilverLivePoints.map(p => ({ x: p.t, y: p.y }));

    // 使用品种特定的周期和阈值参数
    const huP = Monitor.getMomentumPeriods("huyin");

    const coP = Monitor.getMomentumPeriods("comex");

    const _valid = s => s && s.slopePct != null && s.shortEMA != null && s.longEMA != null;
    const huSig = _valid(backendSignals.ag0) ? backendSignals.ag0 : Monitor.calcMomentum(huSeries, huP.shortP, huP.longP, Monitor.getMomentumThresholds("huyin"));

    const coSig = _valid(backendSignals.xag) ? backendSignals.xag : Monitor.calcMomentum(coSeries, coP.shortP, coP.longP, Monitor.getMomentumThresholds("comex"));



    if (huSig && Monitor.momentum.hu.last !== huSig.signal) {

      Monitor.playSignalTone(huSig.signal);

      Monitor.momentum.hu = { last: huSig.signal, strength: huSig.strength };

    }

    if (coSig && Monitor.momentum.co.last !== coSig.signal) {

      Monitor.playSignalTone(coSig.signal);

      Monitor.momentum.co = { last: coSig.signal, strength: coSig.strength };

    }



    Monitor.renderSignal("hu", huSig, 1);

    Monitor.renderSignal("co", coSig, 3);

  };



  Monitor.updateGoldMomentumSignals = function (data) {

    const backendSignals = data.signals || data._signals || Monitor.instrumentSignals || {};

    const au = data.hujin;

    const cg = data.comexGold;

    app.goldLivePoints = app.goldLivePoints || [];

    app.comexGoldLivePoints = app.comexGoldLivePoints || [];

    if (au && !au.error && !au.closed && au.price > 0) _pushIfChanged(app.goldLivePoints, au.price, au.timestamp || Date.now(), 180);

    if (cg && !cg.error && !cg.closed && cg.price > 0) _pushIfChanged(app.comexGoldLivePoints, cg.price, cg.timestamp || Date.now(), 180);



    const auSeries = (app.goldLivePoints || []).map(p => ({ x: p.t, y: p.y }));

    const cgSeries = (app.comexGoldLivePoints || []).map(p => ({ x: p.t, y: p.y }));

    // 使用品种特定的周期和阈值参数
    const auP = Monitor.getMomentumPeriods("hujin");

    const cgP = Monitor.getMomentumPeriods("comex_gold");

    const _valid2 = s => s && s.slopePct != null && s.shortEMA != null && s.longEMA != null;
    const auSig = _valid2(backendSignals.au0) ? backendSignals.au0 : Monitor.calcMomentum(auSeries, auP.shortP, auP.longP, Monitor.getMomentumThresholds("hujin"));

    const cgSig = _valid2(backendSignals.xau) ? backendSignals.xau : Monitor.calcMomentum(cgSeries, cgP.shortP, cgP.longP, Monitor.getMomentumThresholds("comex_gold"));



    if (auSig && Monitor.momentum.au.last !== auSig.signal) {

      Monitor.playSignalTone(auSig.signal);

      Monitor.momentum.au = { last: auSig.signal, strength: auSig.strength };

    }

    if (cgSig && Monitor.momentum.cg.last !== cgSig.signal) {

      Monitor.playSignalTone(cgSig.signal);

      Monitor.momentum.cg = { last: cgSig.signal, strength: cgSig.strength };

    }



    Monitor.renderSignal("au", auSig, 2);

    Monitor.renderSignal("cg", cgSig, 2);

  };

  Monitor.updateCryptoMomentumSignals = function (data) {
    const backendSignals = data.signals || data._signals || Monitor.instrumentSignals || {};
    const btc = data.btc;
    app.btcLivePoints = app.btcLivePoints || [];
    if (btc && !btc.error && !btc.closed && btc.price > 0) _pushIfChanged(app.btcLivePoints, btc.price, btc.timestamp || Date.now(), 180);

    const btcSeries = (app.btcLivePoints || []).map(p => ({ x: p.t, y: p.y }));
    const btcP = Monitor.getMomentumPeriods("btc");
    const _valid3 = s => s && s.slopePct != null && s.shortEMA != null && s.longEMA != null;
    const btcSig = _valid3(backendSignals.btc) ? backendSignals.btc : Monitor.calcMomentum(btcSeries, btcP.shortP, btcP.longP, Monitor.getMomentumThresholds("btc"));

    if (btcSig && Monitor.momentum.btc.last !== btcSig.signal) {
      Monitor.playSignalTone(btcSig.signal);
      Monitor.momentum.btc = { last: btcSig.signal, strength: btcSig.strength };
    }

    Monitor.renderSignal("btc", btcSig, 2);
  };


  Monitor.refreshMomentumLabels();

})();

