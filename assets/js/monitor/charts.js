(function () {
  const Monitor = window.Monitor;
  const { app, constants, el } = Monitor;

  Monitor.chartDefaults = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: "#1c2330",
        borderColor: "#30363d",
        borderWidth: 1,
        titleFont: { size: 10 },
        bodyFont: { size: 11 },
      },
    },
    scales: {
      x: {
        type: "time",
        time: { displayFormats: { minute: "HH:mm", hour: "MM/dd HH:mm", day: "MM/dd" } },
        grid: { color: "rgba(48,54,61,0.3)" },
        ticks: { maxTicksLimit: 6, font: { size: 9 }, color: "#484f58" },
      },
      y: {
        grid: { color: "rgba(48,54,61,0.3)" },
        ticks: { font: { size: 10 }, color: "#8b949e" },
      },
    },
  };

  Monitor.realtimeChartOptions = {
    ...Monitor.chartDefaults,
    scales: {
      x: {
        type: "time",
        time: { displayFormats: { second: "HH:mm:ss", minute: "HH:mm" } },
        grid: { color: "rgba(48,54,61,0.3)" },
        ticks: { maxTicksLimit: 8, font: { size: 9 }, color: "#484f58" },
      },
      y: {
        grid: { color: "rgba(48,54,61,0.3)" },
        ticks: { font: { size: 10 }, color: "#8b949e" },
      },
    },
  };

  Monitor.charts = {
    silverChart: new Chart(el("huChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "沪银", data: [], borderColor: "#f85149", backgroundColor: "rgba(248,81,73,0.06)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: { ...Monitor.chartDefaults },
    }),
    comexSilverChart: new Chart(el("coChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "COMEX", data: [], borderColor: "#39d2c0", backgroundColor: "rgba(57,210,192,0.06)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: { ...Monitor.chartDefaults },
    }),
    silverVolatilityChart: new Chart(el("huVolChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "HV20", data: [], borderColor: "#f85149", backgroundColor: "rgba(248,81,73,0.08)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: {
        ...Monitor.chartDefaults,
        scales: {
          ...Monitor.chartDefaults.scales,
          y: { ...Monitor.chartDefaults.scales.y, ticks: { ...Monitor.chartDefaults.scales.y.ticks, callback: v => v.toFixed(1) + "%" } },
        },
      },
    }),
    silverRealtimeChart: new Chart(el("huRtChart").getContext("2d"), {
      type: "line",
      data: { datasets: [
        { label: "沪银实时", data: [], borderColor: "#f85149", backgroundColor: "rgba(248,81,73,0.08)", borderWidth: 2, pointRadius: 0, tension: 0.2, fill: true },
        { label: "压力", data: [], borderColor: "rgba(248,81,73,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
        { label: "支撑", data: [], borderColor: "rgba(63,185,80,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
      ] },
      options: {
        ...Monitor.realtimeChartOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1c2330",
            borderColor: "#30363d",
            borderWidth: 1,
            titleFont: { size: 10 },
            bodyFont: { size: 11 },
            filter: item => item.datasetIndex === 0,
            callbacks: {
              label: ctx => "沪银: " + ctx.parsed.y.toFixed(1) + " 元/kg",
              title: items => new Date(items[0].parsed.x).toLocaleTimeString("zh-CN", { hour12: false }),
            },
          },
        },
      },
    }),
    comexSilverRealtimeChart: new Chart(el("coRtChart").getContext("2d"), {
      type: "line",
      data: { datasets: [
        { label: "COMEX实时", data: [], borderColor: "#39d2c0", backgroundColor: "rgba(57,210,192,0.08)", borderWidth: 2, pointRadius: 0, tension: 0.2, fill: true },
        { label: "压力", data: [], borderColor: "rgba(248,81,73,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
        { label: "支撑", data: [], borderColor: "rgba(63,185,80,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
      ] },
      options: {
        ...Monitor.realtimeChartOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1c2330",
            borderColor: "#30363d",
            borderWidth: 1,
            titleFont: { size: 10 },
            bodyFont: { size: 11 },
            filter: item => item.datasetIndex === 0,
            callbacks: {
              label: ctx => "COMEX: $" + ctx.parsed.y.toFixed(3) + "/oz",
              title: items => new Date(items[0].parsed.x).toLocaleTimeString("zh-CN", { hour12: false }),
            },
          },
        },
      },
    }),
    comexSilverVolatilityChart: new Chart(el("coVolChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "HV20", data: [], borderColor: "#39d2c0", backgroundColor: "rgba(57,210,192,0.08)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: {
        ...Monitor.chartDefaults,
        scales: {
          ...Monitor.chartDefaults.scales,
          y: { ...Monitor.chartDefaults.scales.y, ticks: { ...Monitor.chartDefaults.scales.y.ticks, callback: v => v.toFixed(1) + "%" } },
        },
      },
    }),
    goldChart: null,
    comexGoldChart: null,
    goldVolatilityChart: null,
    comexGoldVolatilityChart: null,
    goldRealtimeChart: null,
    comexGoldRealtimeChart: null,
  };

  Monitor.calculateAtr = function (history, period) {
    if (history.length < period + 1) return 0;
    const trs = [];
    for (let i = 1; i < history.length; i++) {
      const current = history[i].y;
      const prevClose = history[i - 1].y;
      trs.push(Math.abs(current - prevClose));
    }
    const recent = trs.slice(-period);
    return recent.reduce((sum, val) => sum + val, 0) / recent.length;
  };

  Monitor.initializeGoldCharts = function () {
    if (app.isGoldChartsInitialized) return;

    Monitor.charts.goldChart = new Chart(el("auChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "沪金", data: [], borderColor: "#d29922", backgroundColor: "rgba(210,153,34,0.08)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: { ...Monitor.chartDefaults },
    });

    Monitor.charts.comexGoldChart = new Chart(el("cgChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "COMEX Gold", data: [], borderColor: "#f0883e", backgroundColor: "rgba(240,136,62,0.08)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: { ...Monitor.chartDefaults },
    });

    Monitor.charts.goldVolatilityChart = new Chart(el("auVolChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "HV20", data: [], borderColor: "#d29922", backgroundColor: "rgba(210,153,34,0.10)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: {
        ...Monitor.chartDefaults,
        scales: {
          ...Monitor.chartDefaults.scales,
          y: { ...Monitor.chartDefaults.scales.y, ticks: { ...Monitor.chartDefaults.scales.y.ticks, callback: v => v.toFixed(1) + "%" } },
        },
      },
    });

    Monitor.charts.comexGoldVolatilityChart = new Chart(el("cgVolChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "HV20", data: [], borderColor: "#f0883e", backgroundColor: "rgba(240,136,62,0.10)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: {
        ...Monitor.chartDefaults,
        scales: {
          ...Monitor.chartDefaults.scales,
          y: { ...Monitor.chartDefaults.scales.y, ticks: { ...Monitor.chartDefaults.scales.y.ticks, callback: v => v.toFixed(1) + "%" } },
        },
      },
    });

    Monitor.charts.goldRealtimeChart = new Chart(el("auRtChart").getContext("2d"), {
      type: "line",
      data: { datasets: [
        { label: "沪金实时", data: [], borderColor: "#d29922", backgroundColor: "rgba(210,153,34,0.10)", borderWidth: 2, pointRadius: 0, tension: 0.2, fill: true },
        { label: "压力", data: [], borderColor: "rgba(248,81,73,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
        { label: "支撑", data: [], borderColor: "rgba(63,185,80,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
      ] },
      options: {
        ...Monitor.realtimeChartOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1c2330",
            borderColor: "#30363d",
            borderWidth: 1,
            titleFont: { size: 10 },
            bodyFont: { size: 11 },
            filter: item => item.datasetIndex === 0,
            callbacks: {
              label: ctx => "沪金: " + ctx.parsed.y.toFixed(2) + " 元/克",
              title: items => new Date(items[0].parsed.x).toLocaleTimeString("zh-CN", { hour12: false }),
            },
          },
        },
      },
    });

    Monitor.charts.comexGoldRealtimeChart = new Chart(el("cgRtChart").getContext("2d"), {
      type: "line",
      data: { datasets: [
        { label: "COMEX Gold 实时", data: [], borderColor: "#f0883e", backgroundColor: "rgba(240,136,62,0.10)", borderWidth: 2, pointRadius: 0, tension: 0.2, fill: true },
        { label: "压力", data: [], borderColor: "rgba(248,81,73,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
        { label: "支撑", data: [], borderColor: "rgba(63,185,80,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
      ] },
      options: {
        ...Monitor.realtimeChartOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1c2330",
            borderColor: "#30363d",
            borderWidth: 1,
            titleFont: { size: 10 },
            bodyFont: { size: 11 },
            filter: item => item.datasetIndex === 0,
            callbacks: {
              label: ctx => "COMEX Gold: $" + ctx.parsed.y.toFixed(2) + "/oz",
              title: items => new Date(items[0].parsed.x).toLocaleTimeString("zh-CN", { hour12: false }),
            },
          },
        },
      },
    });

    app.isGoldChartsInitialized = true;
  };

  Monitor.initializeCryptoCharts = function () {
    if (app.isCryptoChartsInitialized) return;

    Monitor.charts.btcChart = new Chart(el("btcChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "BTC", data: [], borderColor: "#f7931a", backgroundColor: "rgba(247,147,26,0.08)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: { ...Monitor.chartDefaults },
    });

    Monitor.charts.btcVolatilityChart = new Chart(el("btcVolChart").getContext("2d"), {
      type: "line",
      data: { datasets: [{ label: "HV20", data: [], borderColor: "#f7931a", backgroundColor: "rgba(247,147,26,0.10)", borderWidth: 1.5, pointRadius: 0, tension: 0.3, fill: true }] },
      options: {
        ...Monitor.chartDefaults,
        scales: {
          ...Monitor.chartDefaults.scales,
          y: { ...Monitor.chartDefaults.scales.y, ticks: { ...Monitor.chartDefaults.scales.y.ticks, callback: v => v.toFixed(1) + "%" } },
        },
      },
    });

    Monitor.charts.btcRealtimeChart = new Chart(el("btcRtChart").getContext("2d"), {
      type: "line",
      data: { datasets: [
        { label: "BTC 实时", data: [], borderColor: "#f7931a", backgroundColor: "rgba(247,147,26,0.10)", borderWidth: 2, pointRadius: 0, tension: 0.2, fill: true },
        { label: "压力", data: [], borderColor: "rgba(248,81,73,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
        { label: "支撑", data: [], borderColor: "rgba(63,185,80,0.7)", borderWidth: 1.5, pointRadius: 0, borderDash: [6, 3], fill: false, order: 1 },
      ] },
      options: {
        ...Monitor.realtimeChartOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#1c2330",
            borderColor: "#30363d",
            borderWidth: 1,
            titleFont: { size: 10 },
            bodyFont: { size: 11 },
            filter: item => item.datasetIndex === 0,
            callbacks: {
              label: ctx => "BTC: $" + ctx.parsed.y.toFixed(2),
              title: items => new Date(items[0].parsed.x).toLocaleTimeString("zh-CN", { hour12: false }),
            },
          },
        },
      },
    });

    app.isCryptoChartsInitialized = true;
  };

  Monitor.resizeVisibleCharts = function () {
    const charts = [
      Monitor.charts.silverChart,
      Monitor.charts.comexSilverChart,
      Monitor.charts.silverVolatilityChart,
      Monitor.charts.comexSilverVolatilityChart,
      Monitor.charts.silverRealtimeChart,
      Monitor.charts.comexSilverRealtimeChart,
    ];
    if (app.isGoldChartsInitialized) {
      charts.push(
        Monitor.charts.goldChart,
        Monitor.charts.comexGoldChart,
        Monitor.charts.goldVolatilityChart,
        Monitor.charts.comexGoldVolatilityChart,
        Monitor.charts.goldRealtimeChart,
        Monitor.charts.comexGoldRealtimeChart
      );
    }
    if (app.isCryptoChartsInitialized) {
      charts.push(
        Monitor.charts.btcChart,
        Monitor.charts.btcVolatilityChart,
        Monitor.charts.btcRealtimeChart
      );
    }
    charts.filter(Boolean).forEach(chart => chart.resize());
  };
})();
