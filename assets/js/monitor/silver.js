(function () {
  const Monitor = window.Monitor;
  const { app, charts, constants, el } = Monitor;

  Monitor.updatePriceCards = function (data) {
    const hu = data.huyin;
    const co = data.comex;
    const sp = data.spread;

    if (hu && !hu.error) {
      const huEl = el("huPrice");
      if (hu.closed) {
        huEl.textContent = "—";
        huEl.className = "price-main";
        el("huChange").textContent = hu.status_desc || "休盘中";
        el("huChange").className = "price-change";
        el("huSub").innerHTML = "";
        el("huSource").textContent = "休市";
      } else {
        const dir = (hu.change || 0) >= 0 ? "up" : "down";
        huEl.textContent = hu.price.toFixed(1);
        huEl.className = "price-main " + dir;
        const sign = hu.change >= 0 ? "+" : "";
        el("huChange").innerHTML = `${sign}${(hu.change || 0).toFixed(1)} (${sign}${(hu.changePercent || 0).toFixed(2)}%)`;
        el("huChange").className = "price-change " + dir;
        el("huSub").innerHTML =
          `<span>开 ${(hu.open || 0).toFixed(1)}</span><span>高 ${(hu.high || 0).toFixed(1)}</span><span>低 ${(hu.low || 0).toFixed(1)}</span><span>昨收 ${(hu.prevClose || 0).toFixed(1)}</span>`;
        el("huSource").textContent = hu.source || "--";
      }
    }

    if (co && !co.error) {
      const coEl = el("coPrice");
      if (co.closed) {
        coEl.textContent = "—";
        coEl.className = "price-main";
        el("coChange").textContent = co.status_desc || "休盘中";
        el("coChange").className = "price-change";
        el("coSub").innerHTML = "";
        el("coSource").textContent = "休市";
      } else {
        const dir = (co.change || 0) >= 0 ? "up" : "down";
        coEl.textContent = co.price.toFixed(3);
        coEl.className = "price-main " + dir;
        const sign = co.change >= 0 ? "+" : "";
        el("coChange").innerHTML = `${sign}${(co.change || 0).toFixed(3)} (${sign}${(co.changePercent || 0).toFixed(2)}%)`;
        el("coChange").className = "price-change " + dir;
        el("coSub").innerHTML =
          `<span>≈${(co.priceCny || 0).toFixed(1)}元/kg</span><span>开 ${(co.open || 0).toFixed(3)}</span><span>高 ${(co.high || 0).toFixed(3)}</span><span>低 ${(co.low || 0).toFixed(3)}</span>`;
        el("coSource").textContent = co.source || "--";
      }
    }

    if (sp && sp.ratio) {
      el("spreadRatio").textContent = sp.ratio.toFixed(4);
      const statusEl = el("spreadStatus");
      statusEl.textContent = sp.status || "N/A";
      statusEl.className =
        "spread-status " +
        ((sp.status || "").includes("溢价") ? "premium" : (sp.status || "").includes("折价") ? "discount" : "balanced");
      el("spreadDetail").textContent = `价差 ${(sp.cnySpread || 0).toFixed(1)} 元/kg | 汇率 ${(sp.usdCNY || 0).toFixed(4)} | 因子 ${(sp.convFactor || 0).toFixed(2)}`;
    }
  };

  Monitor.updateCharts = function (data) {
    const huHist = (data.huyin && data.huyin.history) || [];
    const coHist = (data.comex && data.comex.history) || [];
    const huVol = (data.hvSeries && data.hvSeries.hu) || [];
    const coVol = (data.hvSeries && data.hvSeries.comex) || [];

    charts.silverChart.data.datasets[0].data = huHist.map(d => ({ x: d.t, y: d.y }));
    charts.comexSilverChart.data.datasets[0].data = coHist.map(d => ({ x: d.t, y: d.y }));
    charts.silverVolatilityChart.data.datasets[0].data = huVol.map(d => ({ x: d.t, y: d.y }));
    charts.comexSilverVolatilityChart.data.datasets[0].data = coVol.map(d => ({ x: d.t, y: d.y }));
    charts.silverChart.update("none");
    charts.comexSilverChart.update("none");
    charts.silverVolatilityChart.update("none");
    charts.comexSilverVolatilityChart.update("none");

    const huAtr = Monitor.calculateAtr(huHist, 14);
    const coAtr = Monitor.calculateAtr(coHist, 14);
    el("huATR").textContent = huAtr ? huAtr.toFixed(1) + " 元/kg" : "--";
    el("coATR").textContent = coAtr ? coAtr.toFixed(3) + " $/oz" : "--";
    el("huATRBar").style.width = Math.min(100, (huAtr / 300) * 100) + "%";
    el("coATRBar").style.width = Math.min(100, (coAtr / 1.5) * 100) + "%";
  };

  Monitor.updateRtCharts = function () {
    charts.silverRealtimeChart.data.datasets[0].data = app.silverRealtimePoints.map(p => ({ x: p.x, y: p.y }));
    charts.comexSilverRealtimeChart.data.datasets[0].data = app.comexSilverRealtimePoints.map(p => ({ x: p.x, y: p.y }));
    charts.silverRealtimeChart.update("none");
    charts.comexSilverRealtimeChart.update("none");
    el("huRtCount").textContent = app.silverRealtimePoints.length + " pts";
    el("coRtCount").textContent = app.comexSilverRealtimePoints.length + " pts";
  };

  Monitor.recordTicks = function (data) {
    const now = Date.now();
    const hu = data.huyin;
    const co = data.comex;

    if (hu && !hu.error && !hu.closed && hu.price > 0) {
      const pct = app.lastSilverPrice && app.lastSilverPrice > 0 ? ((hu.price - app.lastSilverPrice) / app.lastSilverPrice) * 100 : 0;
      app.silverTicks.unshift({ ts: now, price: hu.price, pct, source: hu.source || "--" });
      if (app.silverTicks.length > constants.maxTickRecords) app.silverTicks.pop();
      app.lastSilverPrice = hu.price;
      app.silverRealtimePoints.push({ x: now, y: hu.price });
      if (app.silverRealtimePoints.length > constants.maxRealtimePoints) app.silverRealtimePoints.shift();
    }

    if (co && !co.error && !co.closed && co.price > 0) {
      const pct = app.lastComexSilverPrice && app.lastComexSilverPrice > 0 ? ((co.price - app.lastComexSilverPrice) / app.lastComexSilverPrice) * 100 : 0;
      app.comexSilverTicks.unshift({ ts: now, price: co.price, pct, source: co.source || "--" });
      if (app.comexSilverTicks.length > constants.maxTickRecords) app.comexSilverTicks.pop();
      app.lastComexSilverPrice = co.price;
      app.comexSilverRealtimePoints.push({ x: now, y: co.price });
      if (app.comexSilverRealtimePoints.length > constants.maxRealtimePoints) app.comexSilverRealtimePoints.shift();
    }
  };

  Monitor.renderTickTables = function () {
    const formatTime = ts => new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
    const pctCell = v => (v > 0 ? `<span class="pct up">+${v.toFixed(3)}%</span>` : v < 0 ? `<span class="pct down">${v.toFixed(3)}%</span>` : `<span class="pct">0.000%</span>`);
    el("huTickCount").textContent = app.silverTicks.length + " ticks";
    el("coTickCount").textContent = app.comexSilverTicks.length + " ticks";
    el("huTickBody").innerHTML = app.silverTicks.map(row => `<tr><td>${formatTime(row.ts)}</td><td>${row.price.toFixed(1)}</td><td class="pct ${row.pct > 0 ? "up" : row.pct < 0 ? "down" : ""}">${row.pct > 0 ? "+" : ""}${row.pct.toFixed(3)}%</td><td>${row.source}</td></tr>`).join("");
    el("coTickBody").innerHTML = app.comexSilverTicks.map(row => `<tr><td>${formatTime(row.ts)}</td><td>${row.price.toFixed(3)}</td><td class="pct ${row.pct > 0 ? "up" : row.pct < 0 ? "down" : ""}">${row.pct > 0 ? "+" : ""}${row.pct.toFixed(3)}%</td><td>${row.source}</td></tr>`).join("");
  };
})();
