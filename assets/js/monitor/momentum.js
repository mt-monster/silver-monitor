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

  // Cooldown tracking per symbol: { symbol: remainingBars }
  Monitor._cooldowns = {};

  /**
   * 按时间窗口入队：同一窗口内覆写末条价格（取最新值），跨窗口时追加新 bar。
   * windowMs 读取 Monitor.constants.BAR_WINDOW_MS（由 monitor.config.json frontend.bar_window_ms 设置），缺省 30000ms。
   */
  Monitor._pushByTimeWindow = function (arr, price, ts, cap) {
    const windowMs = (Monitor.constants && Monitor.constants.BAR_WINDOW_MS) || 30000;
    if (arr.length > 0 && ts - arr[arr.length - 1].t < windowMs) {
      arr[arr.length - 1].y = price;
    } else {
      arr.push({ t: ts, y: price });
      while (arr.length > cap) arr.shift();
    }
  };

  /** RSI 超买/超卖修正信号（与后端 _fuse_with_rsi 对齐） */
  function _fuseWithRSI(sig, rsi) {
    if (sig === "buy" && rsi > 70) return "neutral";
    if (sig === "sell" && rsi < 30) return "neutral";
    return sig;
  }

  /** BB 融合修正 EMA 动量信号（与后端 _fuse_with_bb 对齐） */

  function _fuseWithBB(baseSig, pctB, bwExpanding, buyKill, sellKill) {

    const bk = buyKill != null ? buyKill : 0.3;

    const sk = sellKill != null ? sellKill : 0.7;

    let sig = baseSig;

    if (sig === "buy") {

      if (pctB < bk) sig = "neutral";

      else if (pctB > 0.5 && bwExpanding) sig = "strong_buy";

    } else if (sig === "strong_buy") {

      if (pctB > 1.0) sig = "buy";

    } else if (sig === "sell") {

      if (pctB > sk) sig = "neutral";

      else if (pctB < 0.5 && bwExpanding) sig = "strong_sell";

    } else if (sig === "strong_sell") {

      if (pctB < 0.0) sig = "sell";

    }

    return sig;

  }



  /** EMA 短/长 张口 + 短 EMA 斜率 + Bollinger 带融合 */

  Monitor.calcMomentum = function (series, shortP, longP, thresholds) {

    if (!series || series.length < longP * 2) return null;

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

    const bbBuyKill = th.bbBuyKill != null ? th.bbBuyKill : 0.3;

    const bbSellKill = th.bbSellKill != null ? th.bbSellKill : 0.7;



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

        signal = _fuseWithBB(signal, bbNow.percentB, bwExpanding, bbBuyKill, bbSellKill);

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
      btc: "btc",
    };

    // 更新 EMA 周期标签（始终更新，即使 info 为 null）
    const symbol = symbolByPrefix[prefix];
    if (symbol && Monitor.getMomentumPeriods) {
      const periods = Monitor.getMomentumPeriods(symbol);
      if (periods) {
        const badgeNode = document.getElementById(prefix + "SignalBadge");
        let tagEl = null;
        if (badgeNode) {
          const card = badgeNode.closest(".signal-card");
          if (card) tagEl = card.querySelector(".ema-tag");
        }
        if (!tagEl) {
          const label = document.getElementById(prefix + "SigLabel");
          if (label) tagEl = label.querySelector(".ema-tag");
        }
        if (tagEl) {
          const current = tagEl.textContent;
          let suffix = "";
          if (current.includes("（")) suffix = current.slice(current.indexOf("（"));
          else if (current.includes("+Boll")) suffix = current.slice(current.indexOf("+Boll"));
          tagEl.textContent = `EMA${periods.shortP}/${periods.longP}${suffix}`;
        }
      }
    }

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

        const minPts = lp * 2;

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

    // 标签已由 renderSignal 根据品种特定周期动态更新，此处无需全局统一刷新。
    // 保留该函数以防止 core.js 调用时报错。

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

