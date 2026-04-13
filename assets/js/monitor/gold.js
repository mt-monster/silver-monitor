(function () {
  const Monitor = window.Monitor;
  const { app, charts, constants, el } = Monitor;

  Monitor.updateGoldPriceCards = function (data) {
    const au = data.hujin;
    const cg = data.comexGold;
    const sp = data.goldSpread;

    if (au && !au.error) {
      const auEl = el("auPrice");
      if (au.closed) {
        auEl.textContent = "—";
        auEl.className = "price-main";
        el("auChange").textContent = au.status_desc || "休盘中";
        el("auChange").className = "price-change";
        el("auSub").innerHTML = "";
        el("auSource").textContent = "休市";
      } else {
        const dir = (au.change || 0) >= 0 ? "up" : "down";
        auEl.textContent = (au.price || 0).toFixed(2);
        auEl.className = "price-main " + dir;
        const sign = au.change >= 0 ? "+" : "";
        el("auChange").innerHTML = `${sign}${(au.change || 0).toFixed(2)} (${sign}${(au.changePercent || 0).toFixed(2)}%)`;
        el("auChange").className = "price-change " + dir;
        el("auSub").innerHTML =
          `<span>开 ${(au.open || 0).toFixed(2)}</span><span>高 ${(au.high || 0).toFixed(2)}</span><span>低 ${(au.low || 0).toFixed(2)}</span><span>昨收 ${(au.prevClose || 0).toFixed(2)}</span>`;
        el("auSource").textContent = au.source || "--";
      }
    }

    if (cg && !cg.error) {
      const cgEl = el("cgPrice");
      if (cg.closed) {
        cgEl.textContent = "—";
        cgEl.className = "price-main";
        el("cgChange").textContent = cg.status_desc || "休盘中";
        el("cgChange").className = "price-change";
        el("cgSub").innerHTML = "";
        el("cgSource").textContent = "休市";
      } else {
        const dir = (cg.change || 0) >= 0 ? "up" : "down";
        cgEl.textContent = (cg.price || 0).toFixed(2);
        cgEl.className = "price-main " + dir;
        const sign = cg.change >= 0 ? "+" : "";
        el("cgChange").innerHTML = `${sign}${(cg.change || 0).toFixed(2)} (${sign}${(cg.changePercent || 0).toFixed(2)}%)`;
        el("cgChange").className = "price-change " + dir;
        const cnyG = cg.priceCnyG ? cg.priceCnyG.toFixed(2) : "--";
        el("cgSub").innerHTML = `<span>≈${cnyG}元/克</span><span>开 ${(cg.open || 0).toFixed(2)}</span><span>高 ${(cg.high || 0).toFixed(2)}</span><span>低 ${(cg.low || 0).toFixed(2)}</span>`;
        el("cgSource").textContent = cg.source || "--";
      }
    }

    if (sp && sp.ratio) {
      el("goldSpreadRatio").textContent = sp.ratio.toFixed(4);
      const statusEl = el("goldSpreadStatus");
      statusEl.textContent = sp.status || "N/A";
      statusEl.className =
        "spread-status " +
        ((sp.status || "").includes("溢价") ? "premium" : (sp.status || "").includes("折价") ? "discount" : "balanced");
      el("goldSpreadDetail").textContent = `价差 ${(sp.cnySpread || 0).toFixed(2)} 元/克 | 汇率 ${(sp.usdCNY || 0).toFixed(4)} | 因子 ${(sp.convFactor || 0).toFixed(2)}`;
    }

    if (data.goldSilverRatio) {
      el("goldSilverRatio").textContent = data.goldSilverRatio.toFixed(2);
    }
  };

  Monitor.updateGoldCharts = function (data) {
    if (!app.isGoldChartsInitialized) return;

    const auHist = (data.hujin && data.hujin.history) || [];
    const cgHist = (data.comexGold && data.comexGold.history) || [];
    const auVol = (data.hvSeries && data.hvSeries.hujin) || [];
    const cgVol = (data.hvSeries && data.hvSeries.comex_gold) || [];

    charts.goldChart.data.datasets[0].data = auHist.map(d => ({ x: d.t, y: d.y }));
    charts.comexGoldChart.data.datasets[0].data = cgHist.map(d => ({ x: d.t, y: d.y }));
    charts.goldVolatilityChart.data.datasets[0].data = auVol.map(d => ({ x: d.t, y: d.y }));
    charts.comexGoldVolatilityChart.data.datasets[0].data = cgVol.map(d => ({ x: d.t, y: d.y }));
    charts.goldChart.update("none");
    charts.comexGoldChart.update("none");
    charts.goldVolatilityChart.update("none");
    charts.comexGoldVolatilityChart.update("none");

    const auAtr = Monitor.calculateAtr(auHist, 14);
    const cgAtr = Monitor.calculateAtr(cgHist, 14);
    el("auATR").textContent = auAtr ? auAtr.toFixed(2) + " 元/克" : "--";
    el("cgATR").textContent = cgAtr ? cgAtr.toFixed(2) + " $/oz" : "--";
    el("auATRBar").style.width = Math.min(100, (auAtr / 10) * 100) + "%";
    el("cgATRBar").style.width = Math.min(100, (cgAtr / 50) * 100) + "%";
  };

  Monitor.updateGoldRtCharts = function () {
    if (!app.isGoldChartsInitialized) return;
    charts.goldRealtimeChart.data.datasets[0].data = app.goldRealtimePoints.map(p => ({ x: p.x, y: p.y }));
    charts.comexGoldRealtimeChart.data.datasets[0].data = app.comexGoldRealtimePoints.map(p => ({ x: p.x, y: p.y }));
    charts.goldRealtimeChart.update("none");
    charts.comexGoldRealtimeChart.update("none");
    el("auRtCount").textContent = app.goldRealtimePoints.length + " pts";
    el("cgRtCount").textContent = app.comexGoldRealtimePoints.length + " pts";
  };

  Monitor.recordGoldTicks = function (data) {
    const now = Date.now();
    const au = data.hujin;
    const cg = data.comexGold;

    if (au && !au.error && !au.closed && au.price > 0) {
      const pct = app.lastGoldPrice && app.lastGoldPrice > 0 ? ((au.price - app.lastGoldPrice) / app.lastGoldPrice) * 100 : 0;
      app.goldTicks.unshift({ ts: now, price: au.price, pct, source: au.source || "--" });
      if (app.goldTicks.length > constants.maxTickRecords) app.goldTicks.pop();
      app.lastGoldPrice = au.price;
      app.goldRealtimePoints.push({ x: now, y: au.price });
      if (app.goldRealtimePoints.length > constants.maxRealtimePoints) app.goldRealtimePoints.shift();
    }

    if (cg && !cg.error && !cg.closed && cg.price > 0) {
      const pct = app.lastComexGoldPrice && app.lastComexGoldPrice > 0 ? ((cg.price - app.lastComexGoldPrice) / app.lastComexGoldPrice) * 100 : 0;
      app.comexGoldTicks.unshift({ ts: now, price: cg.price, pct, source: cg.source || "--" });
      if (app.comexGoldTicks.length > constants.maxTickRecords) app.comexGoldTicks.pop();
      app.lastComexGoldPrice = cg.price;
      app.comexGoldRealtimePoints.push({ x: now, y: cg.price });
      if (app.comexGoldRealtimePoints.length > constants.maxRealtimePoints) app.comexGoldRealtimePoints.shift();
    }
  };

  Monitor.renderGoldTickTables = function () {
    const formatTime = ts => new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
    el("auTickCount").textContent = app.goldTicks.length + " ticks";
    el("cgTickCount").textContent = app.comexGoldTicks.length + " ticks";
    el("auTickBody").innerHTML = app.goldTicks.map(row => `<tr><td>${formatTime(row.ts)}</td><td>${row.price.toFixed(2)}</td><td class="pct ${row.pct > 0 ? "up" : row.pct < 0 ? "down" : ""}">${row.pct > 0 ? "+" : ""}${row.pct.toFixed(3)}%</td><td>${row.source}</td></tr>`).join("");
    el("cgTickBody").innerHTML = app.comexGoldTicks.map(row => `<tr><td>${formatTime(row.ts)}</td><td>${row.price.toFixed(2)}</td><td class="pct ${row.pct > 0 ? "up" : row.pct < 0 ? "down" : ""}">${row.pct > 0 ? "+" : ""}${row.pct.toFixed(3)}%</td><td>${row.source}</td></tr>`).join("");
  };
})();
