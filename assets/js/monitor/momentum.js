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



  /** EMA 短/长 张口 + 短 EMA 一步涨跌幅（%）；强信号仅由张口超过 spreadStrong 决定（与首版逻辑一致）。 */

  Monitor.calcMomentum = function (series, shortP, longP, thresholds) {

    if (!series || series.length < longP + 2) return null;

    const vals = series.map(p => p.y);

    const emaS = Monitor.ema(vals, shortP);

    const emaL = Monitor.ema(vals, longP);

    const lastS = emaS[emaS.length - 1];

    const lastL = emaL[emaL.length - 1];

    const prevS = emaS[emaS.length - 2];

    // 跳过 SMA 种子期的 null 值

    if (lastS == null || lastL == null || prevS == null) return null;

    const spreadPct = lastL !== 0 ? ((lastS - lastL) / lastL) * 100 : 0;

    const slopePct = prevS !== 0 ? ((lastS - prevS) / prevS) * 100 : 0;



    // 使用传入的阈值或默认值
    const th = thresholds || Monitor.getMomentumThresholds();

    const se = th.spreadEntry;

    const ss = th.spreadStrong;

    const sl = th.slopeEntry != null ? th.slopeEntry : 0.02;

    const sm = th.strengthMul != null ? th.strengthMul : 120;



    let signal = "neutral";

    if (lastS > lastL && spreadPct > se && slopePct > sl) {

      signal = spreadPct > ss ? "strong_buy" : "buy";

    } else if (lastS < lastL && spreadPct < -se && slopePct < -sl) {

      signal = spreadPct < -ss ? "strong_sell" : "sell";

    }



    return {

      signal,

      spreadPct,

      slopePct,

      shortEMA: lastS,

      longEMA: lastL,

      strength: Math.min(100, Math.abs(spreadPct) * sm),

    };

  };



  Monitor.renderSignal = function (prefix, info, decimals) {

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

        const lp = Monitor.momentumPeriods?.longP ?? 20;

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

    if (noteEl)

      noteEl.textContent = `动量差 ${info.spreadPct >= 0 ? "+" : ""}${info.spreadPct.toFixed(3)}%`;

  };



  Monitor.refreshMomentumLabels = function () {

    const { shortP, longP } = Monitor.momentumPeriods?.default || { shortP: 5, longP: 20 };

    const tag = `EMA${shortP}/${longP}（张口+短线斜率）`;

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

    const hu = data.huyin;

    const co = data.comex;

    if (hu && !hu.error && !hu.closed && hu.price > 0) _pushIfChanged(app.silverLivePoints, hu.price, hu.timestamp || Date.now(), 180);

    if (co && !co.error && !co.closed && co.price > 0) _pushIfChanged(app.comexSilverLivePoints, co.price, co.timestamp || Date.now(), 180);



    const huSeries = app.silverLivePoints.map(p => ({ x: p.t, y: p.y }));

    const coSeries = app.comexSilverLivePoints.map(p => ({ x: p.t, y: p.y }));

    // 使用品种特定的周期和阈值参数
    const huP = Monitor.getMomentumPeriods("huyin");

    const coP = Monitor.getMomentumPeriods("comex");

    const huSig = Monitor.calcMomentum(huSeries, huP.shortP, huP.longP, Monitor.getMomentumThresholds("huyin"));

    const coSig = Monitor.calcMomentum(coSeries, coP.shortP, coP.longP, Monitor.getMomentumThresholds("comex"));



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

    app.goldLivePoints = app.goldLivePoints || [];

    app.comexGoldLivePoints = app.comexGoldLivePoints || [];

    if (au && !au.error && !au.closed && au.price > 0) _pushIfChanged(app.goldLivePoints, au.price, au.timestamp || Date.now(), 180);

    if (cg && !cg.error && !cg.closed && cg.price > 0) _pushIfChanged(app.comexGoldLivePoints, cg.price, cg.timestamp || Date.now(), 180);



    const auSeries = (app.goldLivePoints || []).map(p => ({ x: p.t, y: p.y }));

    const cgSeries = (app.comexGoldLivePoints || []).map(p => ({ x: p.t, y: p.y }));

    // 使用品种特定的周期和阈值参数
    const auP = Monitor.getMomentumPeriods("hujin");

    const cgP = Monitor.getMomentumPeriods("comex_gold");

    const auSig = Monitor.calcMomentum(auSeries, auP.shortP, auP.longP, Monitor.getMomentumThresholds("hujin"));

    const cgSig = Monitor.calcMomentum(cgSeries, cgP.shortP, cgP.longP, Monitor.getMomentumThresholds("comex_gold"));



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



  Monitor.refreshMomentumLabels();

})();

