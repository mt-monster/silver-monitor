(function () {
  const Monitor = window.Monitor;
  let histChart = null;
  let pathChart = null;

  function el(id) {
    return document.getElementById(id);
  }

  function showError(msg) {
    const box = el("researchError");
    if (!msg) {
      box.style.display = "none";
      box.textContent = "";
      return;
    }
    box.style.display = "block";
    box.textContent = msg;
  }

  function renderMetrics(payload) {
    const grid = el("researchMetrics");
    grid.style.display = "grid";
    const p = payload.percentiles || {};
    const pp = payload.pricesPercentiles || {};
    const cells = [
      ["当前价 S0（元/kg）", payload.S0],
      ["预测价均值（元/kg）", payload.priceMean != null ? payload.priceMean : "—"],
      ["预测价 p5 / p50 / p95（元/kg）", [pp.p5, pp.p50, pp.p95].every(x => x != null) ? [pp.p5, pp.p50, pp.p95].join(" / ") : "—"],
      ["预测价区间（p25–p75）", pp.p25 != null && pp.p75 != null ? `${pp.p25} – ${pp.p75}` : "—"],
      ["Δ% 标准差（价近似波动±）", payload.priceStdevLinApprox != null ? `Δ% ${payload.deltaPctStdev} · 约 ±${payload.priceStdevLinApprox}` : payload.deltaPctStdev],
      ["P(Δ&gt;0)", payload.probUp],
      ["中位采样间隔 s", payload.dtMedianSec],
      ["窗口内点数 / 对数收益条数", `${payload.windowSamplePoints} / ${payload.logReturnsUsed}`],
      ["Δ% 分位 p5 / p50 / p95", [p.p5, p.p50, p.p95].join(" / ")],
    ];
    grid.innerHTML = cells
      .map(
        ([label, val]) =>
          `<div class="metric-card"><div class="label">${label}</div><div class="value">${val}</div></div>`
      )
      .join("");
    const hint = el("researchPriceHint");
    if (hint) {
      hint.style.display = "block";
      hint.textContent = `预测价均为所选 horizon（${payload.horizonSec}s）后相对当前价的模拟终点，单位元/kg；非单一「点预测」。`;
    }
  }

  function renderHistogram(payload) {
    const histogram = payload.histogram || {};
    const s0 = Number(payload.S0) || 0;
    const wrap = el("researchChartWrap");
    wrap.style.display = "block";
    const ctx = el("mcHistChart");
    const counts = histogram.counts || [];
    const edges = histogram.edges || [];
    const labels = [];
    for (let i = 0; i < counts.length; i++) {
      if (edges.length > i + 1 && s0 > 0) {
        const midPct = (edges[i] + edges[i + 1]) / 2;
        const midPrice = s0 * (1 + midPct / 100);
        labels.push(midPrice.toFixed(1));
      } else if (edges.length > i + 1) {
        labels.push(((edges[i] + edges[i + 1]) / 2).toFixed(4) + "%");
      } else labels.push(String(i));
    }
    if (histChart) histChart.destroy();
    histChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "频数",
            data: counts,
            backgroundColor: "rgba(88,166,255,.35)",
            borderColor: "rgba(88,166,255,.8)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#8b949e" } },
          title: {
            display: true,
            text: "预测终点价分布（按 Δ% 分箱换算箱内中点价，元/kg）",
            color: "#c9d1d9",
            font: { size: 12 },
          },
        },
        scales: {
          x: {
            title: { display: true, text: "价格（元/kg）", color: "#8b949e" },
            ticks: { color: "#8b949e", maxRotation: 45, autoSkip: true, maxTicksLimit: 12 },
          },
          y: { ticks: { color: "#8b949e" }, grid: { color: "rgba(48,54,61,.6)" } },
        },
      },
    });
  }

  function renderPathChart(payload) {
    const pc = payload.pathChart;
    const wrap = el("researchPathWrap");
    if (!pc || !pc.paths || !pc.paths.length) {
      if (wrap) wrap.style.display = "none";
      return;
    }
    wrap.style.display = "block";
    const ctx = el("mcPathChart");
    const t = pc.timeSec || [];
    const base = "88,166,255";
    const datasets = pc.paths.map(() => ({
      borderColor: `rgba(${base},0.22)`,
      backgroundColor: "transparent",
      pointRadius: 0,
      borderWidth: 1.2,
      tension: 0.05,
    }));
    pc.paths.forEach((series, i) => {
      datasets[i].data = series.map((y, j) => ({ x: t[j] != null ? t[j] : j, y }));
    });
    if (pathChart) pathChart.destroy();
    pathChart = new Chart(ctx, {
      type: "line",
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { display: false },
          title: {
            display: true,
            text: `模拟价格路径（${pc.pathCount} 条，0–${payload.horizonSec}s，${pc.steps} 步；元/kg）`,
            color: "#c9d1d9",
            font: { size: 12 },
          },
        },
        scales: {
          x: {
            type: "linear",
            title: { display: true, text: "时间（秒）", color: "#8b949e" },
            ticks: { color: "#8b949e" },
            grid: { color: "rgba(48,54,61,.6)" },
          },
          y: {
            title: { display: true, text: "价格（元/kg）", color: "#8b949e" },
            ticks: { color: "#8b949e" },
            grid: { color: "rgba(48,54,61,.6)" },
          },
        },
      },
    });
  }

  async function loadContext() {
    await Monitor.loadRuntimeConfig();
    Monitor.apiBase = Monitor.getApiBase();
    const resp = await fetch(`${Monitor.apiBase}/api/research/huyin?t=${Date.now()}`, { cache: "no-store" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    const d = data.monteCarloDefaults || {};
    const pathInput = el("mcPaths");
    if (pathInput && d.paths) pathInput.value = String(d.paths);
    if (d.maxPaths) pathInput.setAttribute("max", String(d.maxPaths));
    const closed = data.closed ? "休市/无盘" : "交易时段";
    const minR = (data.monteCarloDefaults && data.monteCarloDefaults.minReturns) || 15;
    const needPts = minR + 1;
    const okHint =
      data.sampleCount >= needPts
        ? ""
        : ` · <span style="color:var(--orange)">模拟至少需要约 <strong>${needPts}</strong> 个有效采样点（当前 ${data.sampleCount}），请稍等快轮询累积</span>`;
    el("researchContextLine").innerHTML = `样本 <strong>${data.sampleCount}</strong> / 上限 ${data.maxSamples}（对数收益需 ≥${minR} 条） · ${closed} · 最新价 <strong>${data.lastPrice || "—"}</strong> · ${data.datetimeCst || ""}${okHint}`;
    return data;
  }

  async function runMonteCarlo() {
    showError("");
    el("researchMetrics").style.display = "none";
    const ph = el("researchPriceHint");
    if (ph) ph.style.display = "none";
    el("researchChartWrap").style.display = "none";
    el("researchPathWrap").style.display = "none";
    if (pathChart) {
      pathChart.destroy();
      pathChart = null;
    }
    el("researchWarnings").style.display = "none";
    const btn = el("runMcBtn");
    btn.disabled = true;
    try {
      await Monitor.loadRuntimeConfig();
      Monitor.apiBase = Monitor.getApiBase();
      const body = {
        horizon_sec: Number(el("mcHorizon").value),
        model: el("mcModel").value,
        drift: el("mcDrift").value,
        window_minutes: Number(el("mcWindow").value),
        paths: Number(el("mcPaths").value),
      };
      const resp = await fetch(`${Monitor.apiBase}/api/research/monte-carlo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const text = await resp.text();
      let payload;
      try {
        payload = JSON.parse(text);
      } catch (_) {
        throw new Error("服务器返回非 JSON");
      }
      if (!resp.ok || !payload.ok) {
        throw new Error(payload.error || `HTTP ${resp.status}`);
      }
      renderMetrics(payload);
      if (payload.histogram) renderHistogram(payload);
      renderPathChart(payload);
      const warns = payload.warnings || [];
      if (warns.length) {
        const w = el("researchWarnings");
        w.style.display = "block";
        w.textContent = "提示：" + warns.join("；");
      }
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      btn.disabled = false;
    }
  }

  async function init() {
    try {
      await loadContext();
    } catch (e) {
      el("researchContextLine").textContent = "无法加载上下文：" + (e.message || e);
    }
    el("runMcBtn").addEventListener("click", runMonteCarlo);
  }

  init();
})();
