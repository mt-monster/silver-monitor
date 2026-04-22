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
  const _REVERSE_ALIASES = { ag0: "huyin", xag: "comex", au0: "hujin", xau: "comex_gold" };

  function collectBody() {
    const rawSym = el("symbolSelect").value;
    const symbol = _ALIASES[rawSym] || rawSym;
    const dataSource = el("dataSourceSelect").value;
    var base = {
      strategy: currentStrategy,
      symbol: symbol,
      mode: el("modeSelect").value,
      commission_rate: Number(el("commissionRate").value) / 100,
      slippage_pct: Number(el("slippagePct").value) / 100,
      data_source: dataSource,
    };
    if (dataSource === "realtime") {
      base.lookback_minutes = Number(el("lookbackMinutes").value);
    }
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

  function _historyParamsFor(sym) {
    const cfg = Monitor.momentumConfig || {};
    const defaults = cfg.default || {};
    const key = _REVERSE_ALIASES[sym] || sym;
    const s = cfg[key] || {};
    return {
      shortP: s.short_p ?? defaults.short_p ?? 5,
      longP: s.long_p ?? defaults.long_p ?? 20,
      spreadEntry: s.spread_entry ?? defaults.spread_entry ?? 0.10,
      spreadStrong: s.spread_strong ?? defaults.spread_strong ?? 0.35,
      slopeEntry: s.slope_entry ?? defaults.slope_entry ?? 0.02,
      bbPeriod: s.bb_period ?? defaults.bb_period ?? 20,
      bbMult: s.bb_mult ?? defaults.bb_mult ?? 2.0,
      rsiPeriod: s.rsi_period ?? defaults.rsi_period ?? 14,
      cooldownBars: s.cooldown_bars ?? defaults.cooldown_bars ?? 0,
    };
  }

  function applySymbolDefaults() {
    const sel = el("symbolSelect");
    const opt = sel.options[sel.selectedIndex];
    const sym = sel.value;
    const cat = opt ? opt.dataset.category : null;
    const dataSource = el("dataSourceSelect").value;

    var th, per;
    if (dataSource === "history") {
      th = _historyParamsFor(sym);
      per = th;
    } else {
      th = Monitor.getMomentumThresholds ? Monitor.getMomentumThresholds(sym, cat) : {};
      per = Monitor.getMomentumPeriods ? Monitor.getMomentumPeriods(sym, cat) : {};
    }

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

  function onDataSourceChange() {
    const dataSource = el("dataSourceSelect").value;
    const lookbackLabel = el("lookbackLabel");
    if (lookbackLabel) {
      lookbackLabel.style.display = dataSource === "realtime" ? "" : "none";
    }
    applySymbolDefaults();
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
      delete body.data_source;
      delete body.lookback_minutes;
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
      delete body.data_source;
      delete body.lookback_minutes;
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

  // ── 5分钟 Tick 窗口扫描 ─────────────────────────────────────────────
  function getTodayDate() {
    return new Date().toISOString().slice(0, 10);
  }

  function showScanError(msg) {
    const box = el("scan5minError");
    if (!msg) { box.style.display = "none"; box.textContent = ""; return; }
    box.style.display = "block";
    box.textContent = msg;
  }

  function updateScanProgress(current, total) {
    const wrap = el("scan5minProgressWrap");
    const bar = el("scan5minProgressBar");
    const txt = el("scan5minProgressText");
    wrap.style.display = "block";
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    bar.style.width = pct + "%";
    bar.textContent = pct + "%";
    txt.textContent = `扫描中... ${current} / ${total} 个窗口`;
  }

  function hideScanProgress() {
    el("scan5minProgressWrap").style.display = "none";
  }

  function renderTickQuality(q) {
    const wrap = el("scan5minQualityWrap");
    const grid = el("scan5minQualityGrid");
    if (!q) { wrap.style.display = "none"; return; }
    wrap.style.display = "block";
    const qualityColor = {
      excellent: "#3fb950", good: "#58a6ff", sparse: "#d29922", insufficient: "#f85149"
    };
    const cells = [
      ["数据点数", q.tickCount],
      ["平均间隔(s)", q.avgIntervalSec != null ? q.avgIntervalSec : "—"],
      ["CV (波动率)", q.cv != null ? q.cv + "%" : "—"],
      ["价格变化", q.priceChangePct != null ? q.priceChangePct + "%" : "—"],
      ["数据质量", `<span style="color:${qualityColor[q.dataQuality] || '#8b949e'}">${q.dataQuality}</span>`],
    ];
    grid.innerHTML = cells.map(
      ([label, val]) => `<div class="metric-card"><div class="label">${label}</div><div class="value">${val}</div></div>`
    ).join("");
  }

  function renderScanBestResult(data) {
    const best = data.best_window;
    if (!best) {
      el("scan5minBestResult").style.display = "none";
      return;
    }
    el("scan5minBestResult").style.display = "block";
    const m = best.best_metrics || {};
    const cells = [
      ["时间段", `${best.start_time} ~ ${best.end_time}`],
      ["总收益率 %", m.totalReturnPct != null ? m.totalReturnPct : "—"],
      ["最大回撤 %", m.maxDrawdownPct != null ? m.maxDrawdownPct : "—"],
      ["夏普比率", m.sharpeRatio != null ? m.sharpeRatio : "—"],
      ["完整回合", m.roundTripCount != null ? m.roundTripCount : "—"],
      ["胜率 %", m.winRatePct != null ? m.winRatePct : "—"],
      ["tick点数", best.tick_count || "—"],
    ];
    el("scan5minBestGrid").innerHTML = cells.map(
      ([label, val]) => `<div class="metric-card"><div class="label">${label}</div><div class="value">${val}</div></div>`
    ).join("");
    el("scanBestTimeRange").value = `${best.start_time} ~ ${best.end_time}`;
    const p = best.best_params || {};
    el("scanBestParams").value = `spread=${p.spread_entry}, slope=${p.slope_entry}, short=${p.short_p}, long=${p.long_p}`;
  }

  function renderScanTopWindows(topWindows) {
    const wrap = el("scan5minTopWrap");
    const body = el("scan5minTopBody");
    if (!topWindows || !topWindows.length) {
      wrap.style.display = "none";
      return;
    }
    wrap.style.display = "block";
    body.innerHTML = topWindows.map((w, i) => {
      const m = w.best_metrics || {};
      return `<tr>
        <td>${i + 1}</td>
        <td>${w.start_time}~${w.end_time}</td>
        <td>${m.totalReturnPct != null ? m.totalReturnPct : "—"}</td>
        <td>${m.maxDrawdownPct != null ? m.maxDrawdownPct : "—"}</td>
        <td>${m.sharpeRatio != null ? m.sharpeRatio : "—"}</td>
        <td>${m.roundTripCount != null ? m.roundTripCount : "—"}</td>
        <td>${w.score != null ? w.score.toFixed(2) : "—"}</td>
      </tr>`;
    }).join("");
  }

  function onScanSourceChange() {
    const source = el("scanSourceSelect").value;
    const dateLabel = el("scanDateLabel");
    const stepLabel = el("scanStepLabel");
    if (source === "realtime_buffer") {
      dateLabel.style.display = "none";
      stepLabel.style.display = "none";
    } else {
      dateLabel.style.display = "";
      stepLabel.style.display = "";
    }
  }

  async function runScan5min() {
    showScanError("");
    const btn = el("runScan5minBtn");
    btn.disabled = true;
    el("scan5minBestResult").style.display = "none";
    el("scan5minTopWrap").style.display = "none";
    el("scan5minQualityWrap").style.display = "none";
    el("scan5minMeta").textContent = "";

    const source = el("scanSourceSelect").value;
    const instId = el("scanSymbolSelect").value;
    const strategy = el("scanStrategySelect").value;
    const gridMode = el("scanParamGrid").value;

    let paramGrid = null;
    if (gridMode === "light") {
      paramGrid = {
        spread_entry: [0.01, 0.02, 0.03, 0.05],
        slope_entry: [0.005, 0.01, 0.015, 0.02],
      };
    }

    try {
      Monitor.apiBase = Monitor.getApiBase();
      let payload;

      if (source === "realtime_buffer") {
        const lookback = Number(el("scanLookbackMin").value);
        const body = {
          instrument_id: instId,
          strategy: strategy,
          lookback_minutes: lookback,
          param_grid: paramGrid,
        };
        const resp = await fetch(`${Monitor.apiBase}/api/backtest/scan-5min/realtime`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        payload = await resp.json();
        if (!resp.ok || !payload.ok) {
          throw new Error(payload.message || payload.error || "实时扫描失败");
        }
        const minStr = payload.window_ms ? Math.round(payload.window_ms / 60000) + "min" : "?";
        el("scan5minMeta").textContent =
          `${payload.instrument_id} | 实时缓冲区 | 回望 ${minStr} | 扫描 ${payload.scanned_windows}/${payload.total_windows} 窗口 | 耗时 ${payload.scan_time_sec}s`;
      } else {
        const dateStr = el("scanDateInput").value;
        const stepSeconds = Number(el("scanStepSeconds").value);
        if (!dateStr) { showScanError("请选择日期"); btn.disabled = false; return; }

        const body = {
          instrument_id: instId,
          date: dateStr,
          strategy: strategy,
          step_seconds: stepSeconds,
          param_grid: paramGrid,
          save_results: true,
        };

        el("scan5minProgressWrap").style.display = "block";
        updateScanProgress(0, 100);

        const resp = await fetch(`${Monitor.apiBase}/api/backtest/scan-5min`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        hideScanProgress();
        payload = await resp.json();
        if (!resp.ok || !payload.ok) {
          let msg = payload.message || payload.error || "扫描失败";
          if (payload.available_dates && payload.available_dates.length) {
            msg += "\n\n有数据的日期: " + payload.available_dates.slice(0, 5).join(", ");
          }
          throw new Error(msg);
        }

        el("scan5minMeta").textContent =
          `${payload.instrument_id} | ${payload.date_str} | 扫描 ${payload.scanned_windows}/${payload.total_windows} 个窗口 | 耗时 ${payload.scan_time_sec}s`;
      }

      renderTickQuality(payload.tick_quality);
      renderScanBestResult(payload);
      renderScanTopWindows(payload.top_windows);
    } catch (err) {
      hideScanProgress();
      showScanError(err.message || String(err));
    } finally {
      btn.disabled = false;
    }
  }

  async function loadScanBest() {
    showScanError("");
    const source = el("scanSourceSelect").value;
    if (source === "realtime_buffer") {
      showScanError("实时缓冲区模式不支持加载历史最佳，请直接点击开始扫描");
      return;
    }
    const instId = el("scanSymbolSelect").value;
    const dateStr = el("scanDateInput").value;
    if (!dateStr) { showScanError("请选择日期"); return; }

    try {
      Monitor.apiBase = Monitor.getApiBase();
      const resp = await fetch(`${Monitor.apiBase}/api/backtest/scan-5min/best?instrument_id=${instId}&date=${dateStr}`);
      const payload = await resp.json();
      if (!resp.ok || !payload.ok) {
        throw new Error(payload.error || payload.message || "无历史数据");
      }
      const r = payload.result || {};
      const mockPayload = {
        instrument_id: instId,
        date_str: dateStr,
        best_window: {
          start_time: r.best_window_start_ms ? new Date(r.best_window_start_ms).toTimeString().slice(0, 8) : "—",
          end_time: r.best_window_end_ms ? new Date(r.best_window_end_ms).toTimeString().slice(0, 8) : "—",
          best_params: r.best_params || {},
          best_metrics: r.best_metrics || {},
        },
        top_windows: (r.all_windows || []).slice(0, 10),
      };
      el("scan5minMeta").textContent = `${instId} | ${dateStr} | 从数据库加载`;
      renderScanBestResult(mockPayload);
      renderScanTopWindows(mockPayload.top_windows);
    } catch (err) {
      showScanError(err.message || String(err));
    }
  }

  async function init() {
    await populateSymbols();
    applyMomentumFormFromConfig();
    applySymbolDefaults();
    el("runBacktestBtn").addEventListener("click", runBacktest);
    el("runWalkForwardBtn").addEventListener("click", runWalkForward);
    el("runGridSearchBtn").addEventListener("click", runGridSearch);
    el("dataSourceSelect").addEventListener("change", onDataSourceChange);

    // 5min scan init
    el("scanDateInput").value = getTodayDate();
    el("runScan5minBtn").addEventListener("click", runScan5min);
    el("loadScanBestBtn").addEventListener("click", loadScanBest);
    el("scanSourceSelect").addEventListener("change", onScanSourceChange);
    onScanSourceChange();
  }

  init();
})();
