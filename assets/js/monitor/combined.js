(function () {
  const Monitor = window.Monitor;
  const { app, el } = Monitor;

  Monitor.combined = {
    hu: { last: "neutral", strength: 0 },
    co: { last: "neutral", strength: 0 },
  };

  Monitor.combinedLabels = {
    up: "偏多",
    down: "偏空",
    sideways: "横盘",
  };

  /**
   * 渲染组合信号到 DOM
   * @param {string} prefix  "hu" 或 "co"
   * @param {Object|null} info  后端 combinedSignals 返回值
   */
  Monitor.renderCombinedSignal = function (prefix, info) {
    const badge = el(prefix + "CmbBadge");
    const mtfEl = el(prefix + "CmbMtf");
    const sourceEl = el(prefix + "CmbSource");
    const posEl = el(prefix + "CmbPos");
    const reasonEl = el(prefix + "CmbReason");
    const bar = el(prefix + "CmbBar");
    const noteEl = el(prefix + "CmbNote");
    const ptsEl = el(prefix + "CmbPts");

    if (!badge || !bar) return;

    if (!info) {
      badge.className = "signal-badge neutral";
      badge.textContent = "等待";
      if (mtfEl) mtfEl.textContent = "--";
      if (sourceEl) sourceEl.textContent = "--";
      if (posEl) posEl.textContent = "--";
      if (reasonEl) reasonEl.textContent = "--";
      bar.style.width = "50%";
      bar.className = "signal-bar-inner flat";
      if (noteEl) noteEl.textContent = "等待数据...";
      if (ptsEl) ptsEl.textContent = "--";
      return;
    }

    const sig = info.signal || "neutral";
    const trend = info.mtfTrend || "sideways";
    const source = info.source || "none";
    const posPct = info.positionPct != null ? info.positionPct : 0;
    const strength = info.strength != null ? info.strength : 0;
    const reason = info.reason || "";

    badge.className = "signal-badge " + sig.replace("_", "-");
    badge.textContent = Monitor.signalLabels[sig] || "观望";

    if (mtfEl) {
      const tlabel = Monitor.combinedLabels[trend] || trend;
      const tcls = trend === "up" ? "up" : trend === "down" ? "down" : "";
      mtfEl.innerHTML = `<span class="val ${tcls}">${tlabel}</span>`;
    }

    if (sourceEl) {
      const srcMap = { momentum: "动量", reversal: "反转", combined: "共振", none: "无" };
      sourceEl.textContent = srcMap[source] || source;
    }

    if (posEl) {
      posEl.innerHTML = `<span class="val ${posPct > 0 ? (sig.includes('buy') ? 'up' : 'down') : ''}">${posPct.toFixed(1)}%</span>`;
    }

    if (reasonEl) {
      reasonEl.textContent = reason;
      reasonEl.title = reason;
    }

    bar.style.width = strength.toFixed(0) + "%";
    bar.className = "signal-bar-inner " + (sig.includes("buy") ? "bull" : sig.includes("sell") ? "bear" : "flat");

    if (ptsEl) ptsEl.textContent = "实时";

    if (noteEl) {
      let note = `组合: ${Monitor.signalLabels[sig] || '观望'}`;
      if (info.momentum && info.momentum.signal) {
        note += ` | 动量:${Monitor.signalLabels[info.momentum.signal] || info.momentum.signal}`;
      }
      if (info.reversal && info.reversal.signal) {
        note += ` | 反转:${Monitor.signalLabels[info.reversal.signal] || info.reversal.signal}`;
      }
      if (info.reversal && info.reversal.mtfFiltered) {
        note += " [MTF过滤]";
      }
      noteEl.textContent = note;
    }

    // 播放提示音（仅 strong 信号，且 source 非 none）
    if (Monitor.combined[prefix === "hu" ? "hu" : "co"].last !== sig && source !== "none") {
      Monitor.playSignalTone(sig);
      Monitor.combined[prefix === "hu" ? "hu" : "co"] = { last: sig, strength: strength };
    }
  };

  Monitor.updateCombinedSignals = function (data) {
    const backendCmb = data.combinedSignals || {};
    const backendMtf = data.mtfTrends || {};

    // 沪银 (ag0)
    const huCmb = backendCmb.ag0;
    if (huCmb) {
      Monitor.renderCombinedSignal("hu", huCmb);
    } else {
      Monitor.renderCombinedSignal("hu", null);
    }

    // COMEX银 (xag)
    const coCmb = backendCmb.xag;
    if (coCmb) {
      Monitor.renderCombinedSignal("co", coCmb);
    } else {
      Monitor.renderCombinedSignal("co", null);
    }
  };
})();
