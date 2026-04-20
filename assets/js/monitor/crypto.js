(function () {
  const Monitor = window.Monitor;
  const { app, charts, constants, el, renderers } = Monitor;

  Monitor.updateCryptoPriceCards = function (data) {
    const btc = data.btc;

    renderers.renderMarketCard({
      priceId: "btcPrice",
      changeId: "btcChange",
      subId: "btcSub",
      sourceId: "btcMeta",
      market: btc,
      decimals: 2,
      subHtmlBuilder: market => {
        const cny = market.priceCny ? market.priceCny.toFixed(2) : "--";
        return `<span>≈¥${cny}</span><span>开 ${(market.open || 0).toFixed(2)}</span><span>高 ${(market.high || 0).toFixed(2)}</span><span>低 ${(market.low || 0).toFixed(2)}</span>`;
      },
    });
  };

  Monitor.updateCryptoCharts = function (data) {
    if (!app.isCryptoChartsInitialized) return;

    const btcHist = (data.btc && data.btc.history) || [];
    const btcVol = (data.hvSeries && data.hvSeries.btc) || [];

    charts.btcChart.data.datasets[0].data = btcHist.map(d => ({ x: d.t, y: d.y }));
    charts.btcVolatilityChart.data.datasets[0].data = btcVol.map(d => ({ x: d.t, y: d.y }));
    charts.btcChart.update("none");
    charts.btcVolatilityChart.update("none");

    const btcAtr = Monitor.calculateAtr(btcHist, 14);
    renderers.renderAtrMetric({ valueId: "btcATR", barId: "btcATRBar", atrValue: btcAtr, decimals: 2, unit: "$", maxScale: 5000 });
  };

  Monitor.updateCryptoRtCharts = function () {
    if (!app.isCryptoChartsInitialized) return;
    charts.btcRealtimeChart.data.datasets[0].data = app.btcRealtimePoints.map(p => ({ x: p.x, y: p.y }));
    charts.btcRealtimeChart.update("none");
    var countEl = el("btcRtCount");
    if (countEl) countEl.textContent = app.btcRealtimePoints.length + " pts";
  };

  Monitor.recordCryptoTicks = function (data) {
    const now = Date.now();
    const btc = data.btc;

    if (btc && !btc.error && !btc.closed && btc.price > 0) {
      const pct = app.lastBtcPrice && app.lastBtcPrice > 0 ? ((btc.price - app.lastBtcPrice) / app.lastBtcPrice) * 100 : 0;
      app.btcTicks.unshift({ ts: now, price: btc.price, pct, source: btc.source || "--" });
      if (app.btcTicks.length > 20) app.btcTicks.length = 20;
      app.lastBtcPrice = btc.price;
      app.btcRealtimePoints.push({ x: now, y: btc.price });
      if (app.btcRealtimePoints.length > constants.maxRealtimePoints) app.btcRealtimePoints.shift();
    }
  };

  Monitor.renderCryptoTickTables = function () {
    renderers.renderTickTable({ countId: "btcTickCount", bodyId: "btcTickBody", rows: app.btcTicks.slice(0, 20), priceDecimals: 2 });
  };
})();
