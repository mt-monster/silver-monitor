(function () {
  const Monitor = window.Monitor;
  const { app, charts, constants, el, renderers } = Monitor;

  // ── 初始化组合策略回测卡片（由 app.js 在切到 silver tab 时调用）
  Monitor.initBacktestCard = function () {
    if (typeof Monitor.fetchAndRenderCombinedBacktest === 'function' && document.getElementById('cmbBacktestWrap')) {
      Monitor.fetchAndRenderCombinedBacktest();
    }
  };

  Monitor.updatePriceCards = function (data) {
    const hu = data.huyin;
    const co = data.comex;
    const sp = data.spread;

    renderers.renderMarketCard({
      priceId: "huPrice",
      changeId: "huChange",
      subId: "huSub",
      sourceId: "huSource",
      market: hu,
      decimals: 1,
      subHtmlBuilder: market =>
        `<span>开 ${(market.open || 0).toFixed(1)}</span><span>高 ${(market.high || 0).toFixed(1)}</span><span>低 ${(market.low || 0).toFixed(1)}</span><span>昨收 ${(market.prevClose || 0).toFixed(1)}</span>`,
    });

    renderers.renderMarketCard({
      priceId: "coPrice",
      changeId: "coChange",
      subId: "coSub",
      sourceId: "coSource",
      market: co,
      decimals: 3,
      subHtmlBuilder: market =>
        `<span>≈${(market.priceCny || 0).toFixed(1)}元/kg</span><span>开 ${(market.open || 0).toFixed(3)}</span><span>高 ${(market.high || 0).toFixed(3)}</span><span>低 ${(market.low || 0).toFixed(3)}</span>`,
    });

    renderers.renderSpreadCard({
      ratioId: "spreadRatio",
      statusId: "spreadStatus",
      detailId: "spreadDetail",
      spread: sp,
      detailTextBuilder: spread => `价差 ${(spread.cnySpread || 0).toFixed(1)} 元/kg | 汇率 ${(spread.usdCNY || 0).toFixed(4)} | 因子 ${(spread.convFactor || 0).toFixed(2)}`,
    });
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
    renderers.renderAtrMetric({ valueId: "huATR", barId: "huATRBar", atrValue: huAtr, decimals: 1, unit: "元/kg", maxScale: 300 });
    renderers.renderAtrMetric({ valueId: "coATR", barId: "coATRBar", atrValue: coAtr, decimals: 3, unit: "$/oz", maxScale: 1.5 });
  };

  // 共享工具：计算最近 windowMs 内的压力/支撑并更新 chart datasets[1/2] 和标签
  Monitor._applyChartSR = function (datasets, points, labelElId, decimals, windowMs) {
    const SR_MS = windowMs || 20000;
    if (points.length >= 2) {
      const cutoff = points[points.length - 1].x - SR_MS;
      let hi = -Infinity, lo = Infinity;
      for (let i = points.length - 1; i >= 0 && points[i].x >= cutoff; i--) {
        if (points[i].y > hi) hi = points[i].y;
        if (points[i].y < lo) lo = points[i].y;
      }
      if (isFinite(hi) && hi !== lo) {
        const xMin = points[0].x, xMax = points[points.length - 1].x;
        datasets[1].data = [{ x: xMin, y: hi }, { x: xMax, y: hi }];
        datasets[2].data = [{ x: xMin, y: lo }, { x: xMax, y: lo }];
        const srEl = el(labelElId);
        if (srEl) srEl.innerHTML = '<span style="color:#f85149">R\u00a0' + hi.toFixed(decimals) + '</span> / <span style="color:#3fb950">S\u00a0' + lo.toFixed(decimals) + '</span>';
        return;
      }
    }
    datasets[1].data = [];
    datasets[2].data = [];
    const srEl = el(labelElId);
    if (srEl) srEl.textContent = "";
  };

  Monitor.updateRtCharts = function () {
    const huData = app.silverRealtimePoints;
    const coData = app.comexSilverRealtimePoints;
    charts.silverRealtimeChart.data.datasets[0].data = huData.map(p => ({ x: p.x, y: p.y }));
    charts.comexSilverRealtimeChart.data.datasets[0].data = coData.map(p => ({ x: p.x, y: p.y }));

    Monitor._applyChartSR(charts.silverRealtimeChart.data.datasets, huData, "huSrLabel", 1);
    Monitor._applyChartSR(charts.comexSilverRealtimeChart.data.datasets, coData, "coSrLabel", 3);

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
    renderers.renderTickTable({ countId: "huTickCount", bodyId: "huTickBody", rows: app.silverTicks, priceDecimals: 1 });
    renderers.renderTickTable({ countId: "coTickCount", bodyId: "coTickBody", rows: app.comexSilverTicks, priceDecimals: 3 });
  };
})();
