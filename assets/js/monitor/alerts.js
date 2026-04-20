(function () {
  const Monitor = window.Monitor;
  const { app, el } = Monitor;
  const thresholdBadgeId = "alertThresholdBadge";

  function formatThresholdLabel(value) {
    return `阈值: ≥${value.toFixed(2)}%`;
  }

  function setThresholdUi(value) {
    const badge = el(thresholdBadgeId);
    if (badge && badge.childNodes[0]) {
      badge.childNodes[0].textContent = formatThresholdLabel(value);
    }
    if (el("thCurVal")) {
      el("thCurVal").textContent = value.toFixed(2);
    }
    const menu = el("thresholdMenu");
    if (menu) {
      [...menu.querySelectorAll(".th-item")].forEach(node => {
        node.classList.toggle("active", Math.abs(parseFloat(node.dataset.th) - value) < 1e-9);
      });
    }
    app.currentThreshold = value;
  }

  Monitor.playAlertSound = function (severity, direction) {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      app.audioCtx = app.audioCtx || new Ctx();
      if (app.audioCtx.state === "suspended") app.audioCtx.resume();

      const ctx = app.audioCtx;
      const baseFreq = direction === "急涨" ? 880 : 440;
      const gain = ctx.createGain();
      gain.connect(ctx.destination);
      gain.gain.setValueAtTime(0.0001, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.05, ctx.currentTime + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.4);

      const osc1 = ctx.createOscillator();
      osc1.type = "triangle";
      osc1.frequency.value = baseFreq;
      osc1.connect(gain);

      const osc2 = ctx.createOscillator();
      osc2.type = "triangle";
      osc2.frequency.value = severity === "HIGH" ? baseFreq * 1.5 : baseFreq * 1.25;
      osc2.connect(gain);

      osc1.start(ctx.currentTime);
      osc2.start(ctx.currentTime + 0.08);
      osc1.stop(ctx.currentTime + 0.2);
      osc2.stop(ctx.currentTime + 0.32);
    } catch (_) {}
  };

  Monitor.showAlertBanner = function (alert) {
    const banner = el("alertBanner");
    const text = el("alertBannerText");
    banner.className = "alert-banner " + (alert.direction === "急涨" ? "surge" : "drop");
    text.textContent = `${alert.marketName} ${alert.direction} ${alert.changePercent > 0 ? "+" : ""}${alert.changePercent.toFixed(3)}% | ${alert.fromPrice} → ${alert.toPrice} ${alert.unit}`;
    banner.style.display = "block";
    clearTimeout(Monitor._bannerTimer);
    Monitor._bannerTimer = setTimeout(() => {
      banner.style.display = "none";
    }, 5000);
  };

  Monitor.closeAlertBanner = function () {
    el("alertBanner").style.display = "none";
    clearTimeout(Monitor._bannerTimer);
  };

  Monitor.renderTickRing = function (list, isComex, isGold) {
    if (!Array.isArray(list) || !list.length) return '<div class="no-alerts">暂无 tick</div>';
    return list
      .slice(-5)
      .reverse()
      .map((row, idx, arr) => {
        const prev = idx < arr.length - 1 ? arr[idx + 1].price : row.price;
        const pct = prev > 0 ? ((row.price - prev) / prev) * 100 : 0;
        return `<div class="tick-item">
          <span class="t">${new Date(row.ts).toLocaleTimeString("zh-CN", { hour12: false })}</span>
          <span class="p">${row.price.toFixed(isComex ? (isGold ? 2 : 3) : isGold ? 2 : 1)}</span>
          <span class="pct ${pct > 0 ? "up" : pct < 0 ? "down" : ""}">${pct > 0 ? "+" : ""}${pct.toFixed(3)}%</span>
        </div>`;
      })
      .join("");
  };

  Monitor.updateAlerts = function (payload) {
    setThresholdUi(Number(payload.threshold || 0));

    // 展示分品种阈值
    const thresholds = payload.thresholds || {};
    const thMap = { hu: "huTh", comex: "coTh", hujin: "hujinTh", comex_gold: "comexGoldTh", btc: "btcTh" };
    for (const [market, elId] of Object.entries(thMap)) {
      const node = el(elId);
      if (node) node.textContent = (thresholds[market] != null ? thresholds[market].toFixed(2) : "--") + "%";
    }

    const huStats = payload.stats.hu || { surge: 0, drop: 0, maxJump: 0 };
    const coStats = payload.stats.comex || { surge: 0, drop: 0, maxJump: 0 };
    el("huSurge").textContent = huStats.surge;
    el("huDrop").textContent = huStats.drop;
    el("huMaxJump").textContent = huStats.maxJump.toFixed(3) + "%";
    el("coSurge").textContent = coStats.surge;
    el("coDrop").textContent = coStats.drop;
    el("coMaxJump").textContent = coStats.maxJump.toFixed(3) + "%";

    el("huTickRing").innerHTML = Monitor.renderTickRing(payload.huTickRing || [], false, false);
    el("coTickRing").innerHTML = Monitor.renderTickRing(payload.comexTickRing || [], true, false);

    const alerts = payload.alerts || [];
    if (!alerts.length) {
      el("alertList").innerHTML = '<div class="no-alerts">暂无预警</div>';
    } else {
      el("alertList").innerHTML = alerts
        .slice(0, 30)
        .map(a => {
          const esc = Monitor.dom.escapeHtml;
          return `<div class="alert-row">
            <span class="time">${new Date(a.timestamp).toLocaleTimeString("zh-CN", { hour12: false })}</span>
            <span class="market-dot ${esc(a.market)}"></span>
            <span>${esc(a.marketName)}</span>
            <span class="dir ${a.direction === "急涨" ? "up" : "down"}">${esc(a.direction)}</span>
            <span class="pct">${a.changePercent > 0 ? "+" : ""}${a.changePercent.toFixed(3)}%</span>
            <span class="prices">${a.fromPrice}→${a.toPrice}</span>
            <span class="sev ${esc(a.severity)}">${esc(a.severity)}</span>
          </div>`;
        })
        .join("");
    }

    if (alerts.length && alerts[0].id !== app.lastAlertId) {
      const newest = alerts[0];
      app.lastAlertId = newest.id;
      Monitor.showAlertBanner(newest);
      Monitor.playAlertSound(newest.severity, newest.direction);
    }
  };

  Monitor.fetchAlerts = async function () {
    try {
      const resp = await fetch(`${Monitor.apiBase}/api/alerts?t=${Date.now()}`, { cache: "no-store" });
      const payload = await resp.json();
      Monitor.updateAlerts(payload);
    } catch (err) {
      console.warn("alerts fetch failed", err);
    }
  };

  Monitor.buildThresholdMenu = function () {
    const vals = [0];
    for (let v = 0.05; v <= 1.005; v += 0.05) vals.push(Math.round(v * 100) / 100);
    el("thresholdMenu").innerHTML = vals.map(v => `<div class="th-item ${Math.abs(v - 0.15) < 0.001 ? "active" : ""}" data-th="${v}">${v === 0 ? "OFF" : v.toFixed(2) + "%"}</div>`).join("");
    el("thresholdMenu").addEventListener("click", async event => {
      const item = event.target.closest(".th-item");
      if (!item) return;
      const th = parseFloat(item.dataset.th);
      try {
        const response = await fetch(`${Monitor.apiBase}/api/threshold`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ threshold: th }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.error || `HTTP ${response.status}`);
        }
        const appliedThreshold = Number(payload.threshold);
        setThresholdUi(appliedThreshold);
        await Monitor.fetchAlerts();
      } catch (err) {
        console.warn("set threshold failed", err);
      }
      el("thresholdMenu").classList.remove("open");
    });
  };

  Monitor.toggleThresholdMenu = function (event) {
    if (event) event.stopPropagation();
    el("thresholdMenu").classList.toggle("open");
  };

  document.addEventListener("click", event => {
    if (!event.target.closest("#" + thresholdBadgeId) && !event.target.closest("#thresholdMenu")) {
      const menu = el("thresholdMenu");
      if (menu) menu.classList.remove("open");
    }
  });

  window.closeAlertBanner = Monitor.closeAlertBanner;
  window.toggleThresholdMenu = Monitor.toggleThresholdMenu;
})();
