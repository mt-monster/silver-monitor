(function () {
  const Monitor = (window.Monitor = window.Monitor || {});

  Monitor.constants = {
    POLL_MS: 1000,
    ALERT_POLL_MS: 2000,
    maxTickRecords: 50,
    maxChartPoints: 200,
    maxRealtimePoints: 300,
  };

  Monitor.app = {
    silverTicks: [],
    comexSilverTicks: [],
    lastSilverPrice: null,
    lastComexSilverPrice: null,
    silverLivePoints: [],
    comexSilverLivePoints: [],
    silverRealtimePoints: [],
    comexSilverRealtimePoints: [],
    lastAlertId: null,
    audioCtx: null,
    goldTicks: [],
    comexGoldTicks: [],
    lastGoldPrice: null,
    lastComexGoldPrice: null,
    goldLivePoints: [],
    comexGoldLivePoints: [],
    goldRealtimePoints: [],
    comexGoldRealtimePoints: [],
    activeTab: "silver",
    isGoldChartsInitialized: false,
  };

  Monitor.el = function (id) {
    return document.getElementById(id);
  };

  Monitor.getApiBase = function () {
    const host = window.location.hostname;
    if (!host || window.location.protocol === "file:") {
      return "http://127.0.0.1:8765";
    }
    if (host === "localhost" || host === "127.0.0.1" || host === "[::1]") {
      return window.location.protocol + "//127.0.0.1:" + window.location.port;
    }
    return "";
  };

  Monitor.apiBase = Monitor.getApiBase();
})();
