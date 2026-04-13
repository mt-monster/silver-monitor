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
  };

  Monitor.ema = function (values, period) {
    if (!values.length) return [];
    const k = 2 / (period + 1);
    const out = [values[0]];
    for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
    return out;
  };

  Monitor.calcMomentum = function (series, shortP, longP) {
    if (!series || series.length < longP + 2) return null;
    const vals = series.map(p => p.y);
    const emaS = Monitor.ema(vals, shortP);
    const emaL = Monitor.ema(vals, longP);
    const lastS = emaS[emaS.length - 1];
    const lastL = emaL[emaL.length - 1];
    const prevS = emaS[emaS.length - 2];
    const prevL = emaL[emaL.length - 2];
    const spreadPct = lastL !== 0 ? ((lastS - lastL) / lastL) * 100 : 0;
    const slopePct = prevS !== 0 ? ((lastS - prevS) / prevS) * 100 : 0;

    let signal = "neutral";
    if (lastS > lastL && spreadPct > 0.10 && slopePct > 0.02) signal = spreadPct > 0.35 ? "strong_buy" : "buy";
    else if (lastS < lastL && spreadPct < -0.10 && slopePct < -0.02) signal = spreadPct < -0.35 ? "strong_sell" : "sell";

    return {
      signal,
      spreadPct,
      slopePct,
      shortEMA: lastS,
      longEMA: lastL,
      strength: Math.min(100, Math.abs(spreadPct) * 120),
    };
  };

  Monitor.renderSignal = function (prefix, info, decimals) {
    const findEl = (...ids) => ids.map(id => el(id)).find(Boolean);
    const badge = findEl(prefix + "SignalBadge", prefix + "SigBadge");
    const rocEl = findEl(prefix + "ROC", prefix + "SigSlope");
    const emaFastEl = findEl(prefix + "EmaF", prefix + "SigEmaS");
    const emaSlowEl = findEl(prefix + "EmaS", prefix + "SigEmaL");
    const pointsEl = findEl(prefix + "SigPts");
    const noteEl = findEl(prefix + "SigNote");
    const bar = findEl(prefix + "SigBar");

    if (!badge || !rocEl || !emaFastEl || !emaSlowEl || !bar) return;

    if (!info) {
      badge.className = "signal-badge neutral";
      badge.textContent = "等待";
      rocEl.textContent = "--";
      emaFastEl.textContent = "--";
      emaSlowEl.textContent = "--";
      bar.style.width = "50%";
      bar.className = "signal-bar-inner flat";
      if (pointsEl) pointsEl.textContent = "--";
      if (noteEl) noteEl.textContent = "需累积 40+ 个 tick 后产生信号";
      return;
    }

    badge.className = "signal-badge " + info.signal.replace("_", "-");
    badge.textContent = Monitor.signalLabels[info.signal];
    rocEl.innerHTML = `<span class="val ${info.slopePct >= 0 ? "up" : "down"}">${info.slopePct >= 0 ? "+" : ""}${info.slopePct.toFixed(3)}%</span>`;
    emaFastEl.textContent = info.shortEMA.toFixed(decimals);
    emaSlowEl.textContent = info.longEMA.toFixed(decimals);
    bar.style.width = info.strength.toFixed(0) + "%";
    bar.className = "signal-bar-inner " + (info.signal.includes("buy") ? "bull" : info.signal.includes("sell") ? "bear" : "flat");
    if (pointsEl) pointsEl.textContent = "实时";
    if (noteEl) noteEl.textContent = `动量差 ${info.spreadPct >= 0 ? "+" : ""}${info.spreadPct.toFixed(3)}%`;
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
    const hu = data.huyin;
    const co = data.comex;
    if (hu && !hu.error && !hu.closed && hu.price > 0) app.silverLivePoints.push({ t: hu.timestamp || Date.now(), y: hu.price });
    if (co && !co.error && !co.closed && co.price > 0) app.comexSilverLivePoints.push({ t: co.timestamp || Date.now(), y: co.price });
    if (app.silverLivePoints.length > 180) app.silverLivePoints.shift();
    if (app.comexSilverLivePoints.length > 180) app.comexSilverLivePoints.shift();

    const huSeries = app.silverLivePoints.map(p => ({ x: p.t, y: p.y }));
    const coSeries = app.comexSilverLivePoints.map(p => ({ x: p.t, y: p.y }));
    const shortP = 5;
    const longP = 20;
    const huSig = Monitor.calcMomentum(huSeries, shortP, longP);
    const coSig = Monitor.calcMomentum(coSeries, shortP, longP);

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
    const au = data.hujin;
    const cg = data.comexGold;
    if (au && !au.error && !au.closed && au.price > 0) app.goldLivePoints = [...(app.goldLivePoints || []), { t: au.timestamp || Date.now(), y: au.price }].slice(-180);
    if (cg && !cg.error && !cg.closed && cg.price > 0) app.comexGoldLivePoints = [...(app.comexGoldLivePoints || []), { t: cg.timestamp || Date.now(), y: cg.price }].slice(-180);

    const auSeries = (app.goldLivePoints || []).map(p => ({ x: p.t, y: p.y }));
    const cgSeries = (app.comexGoldLivePoints || []).map(p => ({ x: p.t, y: p.y }));
    const shortP = 5;
    const longP = 20;
    const auSig = Monitor.calcMomentum(auSeries, shortP, longP);
    const cgSig = Monitor.calcMomentum(cgSeries, shortP, longP);

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
})();
