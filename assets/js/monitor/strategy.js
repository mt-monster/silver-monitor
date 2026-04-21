/** 策略回测页逻辑：动量/反转策略回测、Walk-Forward、Grid Search。
 *
 * 负责：参数收集、品种加载、回测执行、结果渲染（Chart.js 权益曲线 + 绩效卡片 + 成交表）。
 */
(function () {
  const Monitor = window.Monitor;
  let equityChart = null;
  let currentStrategy = "momentum";

  // 暴露给 HTML onclick
  window.switchStrategy = function (name) {
    currentStrategy = name;
    document.querySelectorAll(".strategy-tab").forEach(function (t) {
      t.classList.toggle("active", t.dataset.strategy === name);
    });
    // 策略说明面板
    el("momentumExplain").style.display = name === "momentum" ? "" : "none";
    el("reversalExplain").style.display = name === "reversal" ? "" : "none";
    // 参数面板
    el("momentumParams").style.display = name === "momentum" ? "" : "none";
    el("reversalParams").style.display = name === "reversal" ? "" : "none";
    // Grid Search 只对动量策略可用
    el("gsPanel").style.display = name === "momentum" ? "" : "none";
    // 标题
    el("backtestLabel").textContent = name === "momentum"
      ? "动量策略回测（EMA + Boll + RSI 融合信号）"
      : "反转策略回测（RSI + Boll%B + EMA偏离 加权评分）";
    // 清除结果
    el("metricGrid").style.display = "none";
    el("chartWrap").style.display = "none";
    el("tradesWrap").style.display = "none";
    el("strategyMeta").textContent = "";
    showError("");
    el("wfPanel").style.display = "none";
  };

  function el(id) {
    return document.getElementById(id);
  }

  function showError(msg, boxId) {
    const box = el(boxId || "strategyError");
    if (!box) return;
    if (!msg) { box.style.display = "none"; box.textContent = ""; return; }
    box.style.display = "block";
    box.textContent = msg;
  }

  // 旧 symbol 名到注册表 id 的映射
  const _ALIASES = { huyin: "ag0", comex: "xag", hujin: "au0", comex_gold: "xau" };

  function collectBody() {
    const rawSym = el("symbolSelect").value;
    const symbol = _ALIASES[rawSym] || rawSym;
    var base = {
      strategy: currentStrategy,
      symbol: symbol,
      mode: el("modeSelect").value,
      commission_rate: Number(el("commissionRate").value) / 100,
      slippage_pct: Number(el("slippagePct").value) / 100,
    };
    if (currentStrategy === "reversal") {
      base.params = {
        rsi_period: Number(el("rvRsiPeriod").value),
        rsi_oversold: Number(el("rvRsiOversold").value),
        rsi_overbought: Number(el("rvRsiOverbought").value),
        rsi_extreme_low: Number(el("rvRsiExtremeLow").value),
        rsi_extreme_high: Number(el("rvRsiExtremeHigh").value),
        bb_period: Number(el("rvBbPeriod").value),
        bb_mult: Number(el("rvBbMult").value),
        pctb_low: Number(el("rvPctbLow").value),
        pctb_high: Number(el("rvPctbHigh").value),
        ema_period: Number(el("rvEmaPeriod").value),
        deviation_entry: Number(el("rvDeviationEntry").value),
        deviation_strong: Number(el("rvDeviationStrong").value),
        min_score: Number(el("rvMinScore").value),
        strong_score: Number(el("rvStrongScore").value),
        cooldown_bars: Number(el("rvCooldownBars").value),
      };
    } else {
      base.params = {
        short_p: Number(el("shortP").value),
        long_p: Number(el("longP").value),
        spread_entry: Number(el("spreadEntry").value),
        spread_strong: Number(el("spreadStrong").value),
        slope_entry: Number(el("slopeEntry").value),
        bb_period: Number(el("bbPeriod").value),
        bb_mult: Number(el("bbMult").value),
        rsi_period: Number(el("rsiPeriod").value),
        cooldown_bars: Number(el("cooldownBars").value),
      };
    }
    return base;
  }

  const _CAT_ORDER = {
    precious_metals: { name: "贵金属", order: 0 },
    base_metals:     { name: "有色金属", order: 1 },
    ferrous:         { name: "黑色系", order: 2 },
    energy:          { name: "能源化工", order: 3 },
    agriculture:     { name: "农产品", order: 4 },
    international:   { name: "国际", order: 5 },
  };

  async function populateSymbols() {
    try {
      await Monitor.loadRuntimeConfig();
      Monitor.apiBase = Monitor.getApiBase();
      const resp = await fetch(`${Monitor.apiBase}/api/instruments/registry?t=${Date.now()}`);
      const data = await resp.json();
      const registry = data.registry || [];
      const categories = data.categories || {};
      const sel = el("symbolSelect");
      sel.innerHTML = "";

      // group by category
      const grouped = {};
      registry.forEach(function (inst) {
        if (!grouped[inst.category]) grouped[inst.category] = [];
        grouped[inst.category].push(inst);
      });

      // sort categories
      const cats = Object.keys(grouped);
      cats.sort(function (a, b) {
        return ((_CAT_ORDER[a] || {}).order || 99) - ((_CAT_ORDER[b] || {}).order || 99);
      });

      cats.forEach(function (cat) {
        const meta = categories[cat] || _CAT_ORDER[cat] || {};
        const grp = document.createElement("optgroup");
        grp.label = (meta.icon || "") + " " + (meta.name || cat);
        grouped[cat].forEach(function (inst) {
          const opt = document.createElement("option");
          opt.value = inst.id;
          opt.textContent = inst.name + " (" + inst.exchange + ")";
          opt.dataset.category = inst.category;
          grp.appendChild(opt);
        });
        sel.appendChild(grp);
      });

      // default to ag0
      if (sel.querySelector('option[value="ag0"]')) sel.value = "ag0";

      // Auto-fill params on symbol change
      sel.addEventListener("change", applySymbolDefaults);
    } catch (err) {
      console.error("[strategy] populate symbols failed:", err);
      const sel = el("symbolSelect");
      sel.innerHTML = '<option value="ag0">沪银 (SHFE)</option><option value="au0">沪金 (SHFE)</option><option value="xag">伦敦银 (COMEX)</option><option value="xau">伦敦金 (COMEX)</option>';
    }
  }

  function applySymbolDefaults() {
    const sel = el("symbolSelect");
    const opt = sel.options[sel.selectedIndex];
    const sym = sel.value;
    const cat = opt ? opt.dataset.category : null;
    const th = Monitor.getMomentumThresholds ? Monitor.getMomentumThresholds(sym, cat) : {};
    const per = Monitor.getMomentumPeriods ? Monitor.getMomentumPeriods(sym, cat) : {};
    const set = (id, v) => { const n = el(id); if (n && v != null) n.value = v; };
    set("shortP", per.shortP);
    set("longP", per.longP);
    set("spreadEntry", th.spreadEntry);
    set("spreadStrong", th.spreadStrong);
    set("slopeEntry", th.slopeEntry);
    set("bbPeriod", th.bbPeriod);
    set("bbMult", th.bbMult);
    set("rsiPeriod", th.rsiPeriod);
    set("cooldownBars", th.cooldownBars);
  }

  function renderMetrics(meta, metrics, gridId, metaId) {
    const grid = el(gridId || "metricGrid");
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
    if (metaId && meta) {
      el(metaId).textContent = `${meta.symbol || ""} | ${meta.interval || ""} | ${meta.from || ""} → ${meta.to || ""} | K线 ${meta.bars || ""} | ${metrics.note || ""}`;
    }
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
      renderMetrics(payload.meta, payload.metrics, "metricGrid", "strategyMeta");
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

  // ── Walk-Forward ────────────────────────────────────────────────────
  async function runWalkForward() {
    showError("", "wfError");
    const panel = el("wfPanel");
    panel.style.display = "block";
    el("wfGrid").innerHTML = "";
    el("wfMeta").textContent = "运行中...";
    const btn = el("runWalkForwardBtn");
    btn.disabled = true;
    try {
      Monitor.apiBase = Monitor.getApiBase();
      const body = collectBody();
      body.train_ratio = 0.7;
      const resp = await fetch(`${Monitor.apiBase}/api/backtest/walk-forward`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await resp.json();
      if (!resp.ok || !payload.ok) throw new Error(payload.error || "walk-forward 失败");

      const is = payload.in_sample;
      const os = payload.out_of_sample;
      const isM = is.metrics;
      const osM = os.metrics;
      const rows = [
        ["", "In-Sample", "Out-of-Sample"],
        ["K线数", is.bars, os.bars],
        ["总收益%", isM.totalReturnPct, osM.totalReturnPct],
        ["最大回撤%", isM.maxDrawdownPct, osM.maxDrawdownPct],
        ["夏普", isM.sharpeRatio ?? "—", osM.sharpeRatio ?? "—"],
        ["年化%", isM.annualizedReturnPct ?? "—", osM.annualizedReturnPct ?? "—"],
        ["胜率%", isM.winRatePct ?? "—", osM.winRatePct ?? "—"],
      ];
      const grid = el("wfGrid");
      grid.innerHTML = rows.map(r =>
        `<div class="metric-card"><div class="label">${r[0]}</div></div>` +
        `<div class="metric-card"><div class="value">${r[1]}</div></div>` +
        `<div class="metric-card"><div class="value">${r[2]}</div></div>`
      ).join("");
      grid.style.gridTemplateColumns = "1fr 1fr 1fr";
      el("wfMeta").textContent = `${payload.symbol} | ${payload.interval} | 训练70% / 测试30%`;
    } catch (err) {
      showError(err.message || String(err), "wfError");
      el("wfMeta").textContent = "";
    } finally {
      btn.disabled = false;
    }
  }

  // ── Grid Search ─────────────────────────────────────────────────────
  function parseCSV(s) {
    return s.split(",").map(v => Number(v.trim())).filter(v => !isNaN(v));
  }

  async function runGridSearch() {
    showError("", "gsError");
    const btn = el("runGridSearchBtn");
    btn.disabled = true;
    el("gsResultsWrap").style.display = "none";
    try {
      Monitor.apiBase = Monitor.getApiBase();
      const grid = {};
      const sp = parseCSV(el("gsShortP").value);
      const lp = parseCSV(el("gsLongP").value);
      const se = parseCSV(el("gsSpreadEntry").value);
      if (sp.length) grid.short_p = sp;
      if (lp.length) grid.long_p = lp;
      if (se.length) grid.spread_entry = se;
      if (!Object.keys(grid).length) throw new Error("至少指定一个参数范围");

      const body = collectBody();
      const payload_body = {
        symbol: body.symbol,
        mode: body.mode,
        commission_rate: body.commission_rate,
        slippage_pct: body.slippage_pct,
        grid: grid,
        base_params: body.params,
        top_n: Number(el("gsTopN").value) || 10,
      };

      const resp = await fetch(`${Monitor.apiBase}/api/backtest/grid-search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload_body),
      });
      const payload = await resp.json();
      if (!resp.ok || !payload.ok) throw new Error(payload.error || "grid search 失败");

      const results = payload.results || [];
      if (!results.length) throw new Error("无结果");
      const tbody = el("gsResultsBody");
      tbody.innerHTML = results.map((r, i) => {
        const p = r.params;
        const m = r.metrics;
        return `<tr>
          <td>${i + 1}</td>
          <td>${p.short_p}</td><td>${p.long_p}</td><td>${p.spread_entry}</td>
          <td>${m.sharpeRatio ?? "—"}</td><td>${m.totalReturnPct ?? "—"}</td>
          <td>${m.maxDrawdownPct ?? "—"}</td><td>${m.winRatePct ?? "—"}</td>
          <td>${m.roundTripCount ?? 0}</td>
        </tr>`;
      }).join("");
      el("gsResultsWrap").style.display = "block";
    } catch (err) {
      showError(err.message || String(err), "gsError");
    } finally {
      btn.disabled = false;
    }
  }

  function applyMomentumFormFromConfig() {
    const m = Monitor.momentumConfig;
    if (!m) return;
    const d = m.default || m;
    const set = (id, v) => {
      const node = el(id);
      if (node != null && v != null) node.value = v;
    };
    set("shortP", d.short_p);
    set("longP", d.long_p);
    set("spreadEntry", d.spread_entry);
    set("spreadStrong", d.spread_strong);
    set("slopeEntry", d.slope_entry != null ? d.slope_entry : 0.02);
    set("bbPeriod", d.bb_period != null ? d.bb_period : 20);
    set("bbMult", d.bb_mult != null ? d.bb_mult : 2.0);
    set("rsiPeriod", d.rsi_period != null ? d.rsi_period : 14);
    set("cooldownBars", d.cooldown_bars != null ? d.cooldown_bars : 0);
  }

  async function init() {
    await populateSymbols();
    applyMomentumFormFromConfig();
    applySymbolDefaults();
    el("runBacktestBtn").addEventListener("click", runBacktest);
    el("runWalkForwardBtn").addEventListener("click", runWalkForward);
    el("runGridSearchBtn").addEventListener("click", runGridSearch);
  }

  init();
})();
