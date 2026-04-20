(function () {
  const Monitor = window.Monitor;
  const { app, el } = Monitor;

  Monitor.updateDebugInfo = function (data) {
    const sources = (data.activeSources || []).join(" + ");
    const mode = Monitor.sse.connected ? "SSE" : "poll";
    el("debugInfo").textContent = `${new Date().toLocaleTimeString("zh-CN", { hour12: false })} | ${sources || "no-source"} [${mode}]`;
  };

  Monitor.fetchData = async function () {
    const refreshButton = el("refreshBtn");
    try {
      if (refreshButton) refreshButton.classList.add("spinning");
      const resp = await fetch(`${Monitor.apiBase}/api/all?t=${Date.now()}`, { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      Monitor._applyAllData(data);
    } catch (err) {
      console.error(err);
      el("liveDot").style.background = "#f85149";
      el("debugInfo").textContent = "连接失败";
    } finally {
      if (refreshButton) refreshButton.classList.remove("spinning");
    }
  };

  /** 统一处理 /api/all 返回或 SSE push 的数据 */
  Monitor._applyAllData = function (data) {
    Monitor.updatePriceCards(data);
    Monitor.updateCharts(data);
    Monitor.recordTicks(data);
    Monitor.renderTickTables();
    Monitor.updateRtCharts();
    Monitor.updateMomentumSignals(data);
    Monitor.updateReversalSignals(data);

    Monitor.updateGoldPriceCards(data);
    Monitor.recordGoldTicks(data);
    Monitor.renderGoldTickTables();
    Monitor.updateGoldRtCharts();
    Monitor.updateGoldMomentumSignals(data);
    if (app.isGoldChartsInitialized) Monitor.updateGoldCharts(data);

    Monitor.updateCryptoPriceCards(data);
    Monitor.recordCryptoTicks(data);
    Monitor.renderCryptoTickTables();
    Monitor.updateCryptoRtCharts();
    Monitor.updateCryptoMomentumSignals(data);
    if (app.isCryptoChartsInitialized) Monitor.updateCryptoCharts(data);

    Monitor.updateDebugInfo(data);
    el("liveDot").style.background = "#3fb950";
  };

  /** SSE "data" 事件处理：接收精简快照，适配到已有渲染管线 */
  function _onSseData(payload) {
    // SSE 推送精简格式 → 适配 /api/all 格式
    const data = {
      huyin: payload.huyin || {},
      comex: payload.comex || {},
      hujin: payload.hujin || {},
      comexGold: payload.comexGold || {},
      btc: payload.btc || {},
      signals: payload.signals || {},
      activeSources: ["SSE"],
    };

    Monitor.updatePriceCards(data);
    Monitor.recordTicks(data);
    Monitor.renderTickTables();
    Monitor.updateRtCharts();
    Monitor.updateMomentumSignals(data);
    Monitor.updateReversalSignals(data);

    Monitor.updateGoldPriceCards(data);
    Monitor.recordGoldTicks(data);
    Monitor.renderGoldTickTables();
    Monitor.updateGoldRtCharts();
    Monitor.updateGoldMomentumSignals(data);

    Monitor.updateCryptoPriceCards(data);
    Monitor.recordCryptoTicks(data);
    Monitor.renderCryptoTickTables();
    Monitor.updateCryptoRtCharts();
    Monitor.updateCryptoMomentumSignals(data);

    Monitor.updateDebugInfo(data);
    el("liveDot").style.background = "#3fb950";
  }

  Monitor.switchTab = function (tab) {
    var valid = ["dashboard", "silver", "gold", "crypto", "detail"];
    if (valid.indexOf(tab) === -1) return;

    // 离开 detail 时清理轮询和图表
    if (app.activeTab === "detail" && tab !== "detail" && Monitor.closeDetail) {
      Monitor.closeDetail();
    }

    if (tab === "gold") Monitor.initializeGoldCharts();
    if (tab === "crypto") Monitor.initializeCryptoCharts();
    app.activeTab = tab;

    var dashEl = document.getElementById("dashboardTab");
    var detailEl = document.getElementById("detailTab");
    var cryptoEl = document.getElementById("cryptoTab");
    if (dashEl) dashEl.classList.toggle("active", tab === "dashboard");
    if (detailEl) detailEl.classList.toggle("active", tab === "detail");
    if (cryptoEl) cryptoEl.classList.toggle("active", tab === "crypto");
    el("silverTab").classList.toggle("active", tab === "silver");
    el("goldTab").classList.toggle("active", tab === "gold");

    var tabDash = document.getElementById("tabDashboard");
    var tabCrypto = document.getElementById("tabCrypto");
    if (tabDash) tabDash.className = "tab-btn" + (tab === "dashboard" || tab === "detail" ? " active-dashboard" : "");
    el("tabSilver").className = "tab-btn" + (tab === "silver" ? " active-silver" : "");
    el("tabGold").className = "tab-btn" + (tab === "gold" ? " active-gold" : "");
    if (tabCrypto) tabCrypto.className = "tab-btn" + (tab === "crypto" ? " active-crypto" : "");

    if (tab === "dashboard" && Monitor.fetchDashboard) Monitor.fetchDashboard();
    setTimeout(Monitor.resizeVisibleCharts, 40);
  };

  Monitor.manualRefresh = function () {
    Monitor.fetchData();
    Monitor.fetchAlerts();
  };

  // Polling 定时器句柄（SSE 连接成功后可停止）
  var _dataTimer = null;
  var _dashTimer = null;

  function _startPolling() {
    if (!_dataTimer) _dataTimer = setInterval(Monitor.fetchData, Monitor.constants.POLL_MS);
    if (!_dashTimer && Monitor.fetchDashboard) _dashTimer = setInterval(Monitor.fetchDashboard, Monitor.constants.POLL_MS);
  }

  function _stopPolling() {
    if (_dataTimer) { clearInterval(_dataTimer); _dataTimer = null; }
    if (_dashTimer) { clearInterval(_dashTimer); _dashTimer = null; }
  }

  Monitor.init = function () {
    return Monitor.loadRuntimeConfig().then(() => {
      Monitor.buildThresholdMenu();

      // 先做一次完整拉取确保 UI 有数据
      Monitor.fetchData();
      Monitor.fetchAlerts();
      if (Monitor.fetchDashboard) Monitor.fetchDashboard();

      // 尝试 SSE 连接
      Monitor.sse.on("data", _onSseData);
      Monitor.sse.connect(function onConnect() {
        // SSE 成功：停止高频数据轮询，仅保留 alert 轮询和 dashboard 轮询（dashboard 含完整数据）
        _stopPolling();
        // Dashboard 仍用低频轮询（含完整字段、图表 history 等），SSE 只推精简快照
        if (Monitor.fetchDashboard) _dashTimer = setInterval(Monitor.fetchDashboard, 5000);
      });

      // SSE 失败自动回退到轮询
      var _sseCheck = setInterval(function () {
        if (!Monitor.sse.connected && !_dataTimer) _startPolling();
      }, 3000);

      // Alert 轮询独立
      setInterval(Monitor.fetchAlerts, Monitor.constants.ALERT_POLL_MS);

      // 首次 SSE 未就绪时启动轮询
      _startPolling();
    });
  };

  window.switchTab = Monitor.switchTab;
  window.manualRefresh = Monitor.manualRefresh;

  Monitor.init();
})();
