(function () {
  const Monitor = window.Monitor;
  let equityChart = null;

  function el(id) {
    return document.getElementById(id);
  }

  function showError(msg) {
    const box = el("strategyError");
    if (!msg) {
      box.style.display = "none";
      box.textContent = "";
      return;
    }
    box.style.display = "block";
    box.textContent = msg;
  }

  function collectBody() {
    return {
      strategy: el("strategySelect").value,
      symbol: el("symbolSelect").value,
      mode: "long_only",
      params: {
        short_p: Number(el("shortP").value),
        long_p: Number(el("longP").value),
        spread_entry: Number(el("spreadEntry").value),
        spread_strong: Number(el("spreadStrong").value),
        slope_entry: Number(el("slopeEntry").value),
      },
    };
  }

  function renderMetrics(meta, metrics) {
    const grid = el("metricGrid");
    grid.style.display = "grid";
    const cells = [
      ["总收益率 %", metrics.totalReturnPct],
      ["最大回撤 %", metrics.maxDrawdownPct],
      ["夏普比率", metrics.sharpeRatio != null ? metrics.sharpeRatio : "—"],
      ["卖出次数", metrics.sellCount],
      ["完整回合", metrics.roundTripCount],
      ["胜率 %", metrics.winRatePct != null ? metrics.winRatePct : "—"],
      ["年化收益 %", metrics.annualizedReturnPct != null ? metrics.annualizedReturnPct : "—"],
    ];
    grid.innerHTML = cells
      .map(
        ([label, val]) =>
          `<div class="metric-card"><div class="label">${label}</div><div class="value">${val}</div></div>`
      )
      .join("");
    el("strategyMeta").textContent = `${meta.symbol} | ${meta.interval} | ${meta.from} → ${meta.to} | K线 ${meta.bars} | ${metrics.note || ""}`;
  }

  function renderTrades(trades) {
    const wrap = el("tradesWrap");
    const body = el("tradesBody");
    if (!trades || !trades.length) {
      wrap.style.display = "none";
      return;
    }
    wrap.style.display = "block";
    body.innerHTML = trades
      .map(
        tr =>
          `<tr><td class="${tr.action}">${tr.action}</td><td>${tr.t}</td><td>${tr.price}</td><td>${tr.signal}</td></tr>`
      )
      .join("");
  }

  function renderChart(equity) {
    const wrap = el("chartWrap");
    wrap.style.display = "block";
    const ctx = el("equityChart");
    if (equityChart) equityChart.destroy();
    equityChart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [
          {
            label: "权益曲线",
            data: equity.map(row => ({ x: row.t, y: row.equity })),
            borderColor: "#58a6ff",
            backgroundColor: "rgba(88,166,255,.1)",
            fill: true,
            tension: 0.1,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        scales: {
          x: {
            type: "time",
            time: { unit: "day" },
            grid: { color: "rgba(48,54,61,.6)" },
            ticks: { color: "#8b949e", maxRotation: 0 },
          },
          y: {
            grid: { color: "rgba(48,54,61,.6)" },
            ticks: { color: "#8b949e" },
          },
        },
        plugins: {
          legend: { labels: { color: "#c9d1d9" } },
        },
      },
    });
  }

  async function runBacktest() {
    showError("");
    const btn = el("runBacktestBtn");
    btn.disabled = true;
    try {
      await Monitor.loadRuntimeConfig();
      Monitor.apiBase = Monitor.getApiBase();
      const resp = await fetch(`${Monitor.apiBase}/api/backtest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collectBody()),
      });
      const text = await resp.text();
      let payload;
      try {
        payload = JSON.parse(text);
      } catch (_) {
        throw new Error("服务器返回非 JSON");
      }
      if (!resp.ok) {
        throw new Error(payload.error || `HTTP ${resp.status}`);
      }
      if (!payload.ok) {
        throw new Error(payload.error || "回测失败");
      }
      renderMetrics(payload.meta, payload.metrics);
      renderChart(payload.equity);
      renderTrades(payload.trades);
    } catch (err) {
      showError(err.message || String(err));
      el("metricGrid").style.display = "none";
      el("chartWrap").style.display = "none";
      el("tradesWrap").style.display = "none";
      el("strategyMeta").textContent = "";
    } finally {
      btn.disabled = false;
    }
  }

  function applyMomentumFormFromConfig() {
    const m = Monitor.momentumConfig;
    if (!m) return;
    const set = (id, v) => {
      const node = el(id);
      if (node != null) node.value = v;
    };
    set("shortP", m.short_p);
    set("longP", m.long_p);
    set("spreadEntry", m.spread_entry);
    set("spreadStrong", m.spread_strong);
    set("slopeEntry", m.slope_entry != null ? m.slope_entry : 0.02);
  }

  async function init() {
    await Monitor.loadRuntimeConfig();
    Monitor.apiBase = Monitor.getApiBase();
    applyMomentumFormFromConfig();
    el("runBacktestBtn").addEventListener("click", runBacktest);
  }

  init();
})();
