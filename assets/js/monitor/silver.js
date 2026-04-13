(function () {
  const Monitor = window.Monitor;
  const { app, charts, constants, el, renderers } = Monitor;

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
    renderers.renderTickTable({ countId: "huTickCount", bodyId: "huTickBody", rows: app.silverTicks, priceDecimals: 1 });
    renderers.renderTickTable({ countId: "coTickCount", bodyId: "coTickBody", rows: app.comexSilverTicks, priceDecimals: 3 });
  };
})();
