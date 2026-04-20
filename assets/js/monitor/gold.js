(function () {
  const Monitor = window.Monitor;
  const { app, charts, constants, el, renderers } = Monitor;

  Monitor.updateGoldPriceCards = function (data) {
    const au = data.hujin;
    const cg = data.comexGold;
    const sp = data.goldSpread;

    renderers.renderMarketCard({
      priceId: "auPrice",
      changeId: "auChange",
      subId: "auSub",
      sourceId: "auSource",
      market: au,
      decimals: 2,
      subHtmlBuilder: market =>
        `<span>开 ${(market.open || 0).toFixed(2)}</span><span>高 ${(market.high || 0).toFixed(2)}</span><span>低 ${(market.low || 0).toFixed(2)}</span><span>昨收 ${(market.prevClose || 0).toFixed(2)}</span>`,
    });

    renderers.renderMarketCard({
      priceId: "cgPrice",
      changeId: "cgChange",
      subId: "cgSub",
      sourceId: "cgSource",
      market: cg,
      decimals: 2,
      subHtmlBuilder: market => {
        const cnyG = market.priceCnyG ? market.priceCnyG.toFixed(2) : "--";
        return `<span>≈${cnyG}元/克</span><span>开 ${(market.open || 0).toFixed(2)}</span><span>高 ${(market.high || 0).toFixed(2)}</span><span>低 ${(market.low || 0).toFixed(2)}</span>`;
      },
    });

    renderers.renderSpreadCard({
      ratioId: "goldSpreadRatio",
      statusId: "goldSpreadStatus",
      detailId: "goldSpreadDetail",
      spread: sp,
      detailTextBuilder: spread => `价差 ${(spread.cnySpread || 0).toFixed(2)} 元/克 | 汇率 ${(spread.usdCNY || 0).toFixed(4)} | 因子 ${(spread.convFactor || 0).toFixed(2)}`,
    });

    const goldSilverRatioEl = el("goldSilverRatio");
    if (goldSilverRatioEl && data.goldSilverRatio) {
      goldSilverRatioEl.textContent = data.goldSilverRatio.toFixed(2);
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
    renderers.renderAtrMetric({ valueId: "auATR", barId: "auATRBar", atrValue: auAtr, decimals: 2, unit: "元/克", maxScale: 10 });
    renderers.renderAtrMetric({ valueId: "cgATR", barId: "cgATRBar", atrValue: cgAtr, decimals: 2, unit: "$/oz", maxScale: 50 });
  };

  Monitor.updateGoldRtCharts = function () {
    if (!app.isGoldChartsInitialized) return;
    const auData = app.goldRealtimePoints;
    const cgData = app.comexGoldRealtimePoints;
    charts.goldRealtimeChart.data.datasets[0].data = auData.map(p => ({ x: p.x, y: p.y }));
    charts.comexGoldRealtimeChart.data.datasets[0].data = cgData.map(p => ({ x: p.x, y: p.y }));

    Monitor._applyChartSR(charts.goldRealtimeChart.data.datasets, auData, "auSrLabel", 2);
    Monitor._applyChartSR(charts.comexGoldRealtimeChart.data.datasets, cgData, "cgSrLabel", 2);

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
    renderers.renderTickTable({ countId: "auTickCount", bodyId: "auTickBody", rows: app.goldTicks, priceDecimals: 2 });
    renderers.renderTickTable({ countId: "cgTickCount", bodyId: "cgTickBody", rows: app.comexGoldTicks, priceDecimals: 2 });
  };
})();
