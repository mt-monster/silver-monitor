(function () {
  const Monitor = window.Monitor;
  const { app, el } = Monitor;

  Monitor.updateDebugInfo = function (data) {
    const sources = (data.activeSources || []).join(" + ");
    el("debugInfo").textContent = `${new Date().toLocaleTimeString("zh-CN", { hour12: false })} | ${sources || "no-source"}`;
  };

  Monitor.fetchData = async function () {
    const refreshButton = el("refreshBtn");
    try {
      if (refreshButton) refreshButton.classList.add("spinning");
      const resp = await fetch(`${Monitor.apiBase}/api/all?t=${Date.now()}`, { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();

      Monitor.updatePriceCards(data);
      Monitor.updateCharts(data);
      Monitor.recordTicks(data);
      Monitor.renderTickTables();
      Monitor.updateRtCharts();
      Monitor.updateMomentumSignals(data);

      Monitor.updateGoldPriceCards(data);
      Monitor.recordGoldTicks(data);
      Monitor.renderGoldTickTables();
      Monitor.updateGoldRtCharts();
      Monitor.updateGoldMomentumSignals(data);
      if (app.isGoldChartsInitialized) Monitor.updateGoldCharts(data);

      Monitor.updateDebugInfo(data);
      el("liveDot").style.background = "#3fb950";
    } catch (err) {
      console.error(err);
      el("liveDot").style.background = "#f85149";
      el("debugInfo").textContent = "连接失败";
    } finally {
      if (refreshButton) refreshButton.classList.remove("spinning");
    }
  };

  Monitor.switchTab = function (tab) {
    if (tab !== "silver" && tab !== "gold") return;
    if (tab === "gold") Monitor.initializeGoldCharts();
    app.activeTab = tab;

    const isSilver = tab === "silver";
    el("silverTab").classList.toggle("active", isSilver);
    el("goldTab").classList.toggle("active", !isSilver);
    el("tabSilver").className = "tab-btn" + (isSilver ? " active-silver" : "");
    el("tabGold").className = "tab-btn" + (!isSilver ? " active-gold" : "");

    setTimeout(Monitor.resizeVisibleCharts, 40);
  };

  Monitor.manualRefresh = function () {
    Monitor.fetchData();
    Monitor.fetchAlerts();
  };

  Monitor.init = function () {
    return Monitor.loadRuntimeConfig().then(() => {
      Monitor.buildThresholdMenu();
      Monitor.fetchData();
      Monitor.fetchAlerts();
      setInterval(Monitor.fetchData, Monitor.constants.POLL_MS);
      setInterval(Monitor.fetchAlerts, Monitor.constants.ALERT_POLL_MS);
    });
  };

  window.switchTab = Monitor.switchTab;
  window.manualRefresh = Monitor.manualRefresh;

  Monitor.init();
})();
