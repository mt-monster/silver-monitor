(function () {
  const Monitor = (window.Monitor = window.Monitor || {});
  const defaultConfig = {
    frontend: {
      default_api_host: "127.0.0.1",
      fallback_port: 8765,
      poll_ms: 1000,
      alert_poll_ms: 2000,
    },
    momentum: {
      short_p: 5,
      long_p: 20,
      spread_entry: 0.1,
      spread_strong: 0.35,
      slope_entry: 0.02,
    },
  };

  Monitor.constants = {
    POLL_MS: defaultConfig.frontend.poll_ms,
    ALERT_POLL_MS: defaultConfig.frontend.alert_poll_ms,
    maxTickRecords: 50,
    maxChartPoints: 200,
    maxRealtimePoints: 300,
    defaultApiHost: defaultConfig.frontend.default_api_host,
    fallbackPort: defaultConfig.frontend.fallback_port,
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
    const fallbackHost = Monitor.constants.defaultApiHost;
    const fallbackPort = Monitor.constants.fallbackPort;
    if (!host || window.location.protocol === "file:") {
      return `http://${fallbackHost}:${fallbackPort}`;
    }
    if (host === "localhost" || host === "127.0.0.1" || host === "[::1]") {
      return window.location.protocol + "//127.0.0.1:" + window.location.port;
    }
    return "";
  };

  Monitor.applyRuntimeConfig = function (config) {
    const frontendConfig = { ...defaultConfig.frontend, ...(config?.frontend || {}) };
    Monitor.constants.POLL_MS = Number(frontendConfig.poll_ms);
    Monitor.constants.ALERT_POLL_MS = Number(frontendConfig.alert_poll_ms);
    Monitor.constants.defaultApiHost = frontendConfig.default_api_host;
    Monitor.constants.fallbackPort = Number(frontendConfig.fallback_port);
    Monitor.apiBase = Monitor.getApiBase();

    const momentum = config?.momentum || defaultConfig.momentum;
    Monitor.momentumConfig = momentum;

    // 支持品种级别参数配置
    const defaults = momentum.default || momentum;
    Monitor.momentumThresholds = {
      default: {
        spreadEntry: Number(defaults.spread_entry),
        spreadStrong: Number(defaults.spread_strong),
        slopeEntry: Number(defaults.slope_entry != null ? defaults.slope_entry : 0.02),
        strengthMul: Number(defaults.strength_multiplier != null ? defaults.strength_multiplier : 120),
      },
    };

    // 加载品种特定阈值
    const symbols = ["huyin", "comex", "hujin", "comex_gold"];
    symbols.forEach(symbol => {
      if (momentum[symbol]) {
        Monitor.momentumThresholds[symbol] = {
          spreadEntry: Number(momentum[symbol].spread_entry ?? defaults.spread_entry),
          spreadStrong: Number(momentum[symbol].spread_strong ?? defaults.spread_strong),
          slopeEntry: Number(momentum[symbol].slope_entry ?? defaults.slope_entry ?? 0.02),
          strengthMul: Number(momentum[symbol].strength_multiplier ?? defaults.strength_multiplier ?? 120),
        };
      }
    });

    // 品种级别 EMA 周期配置
    Monitor.momentumPeriods = {
      default: { shortP: Number(defaults.short_p), longP: Number(defaults.long_p) },
    };
    symbols.forEach(symbol => {
      if (momentum[symbol]) {
        Monitor.momentumPeriods[symbol] = {
          shortP: Number(momentum[symbol].short_p ?? defaults.short_p),
          longP: Number(momentum[symbol].long_p ?? defaults.long_p),
        };
      }
    });
    if (typeof Monitor.refreshMomentumLabels === "function") Monitor.refreshMomentumLabels();
  };

  // 获取特定品种的动量参数（合并default和品种特定参数）
  Monitor.getMomentumThresholds = function (symbol) {
    const defaults = Monitor.momentumThresholds.default || Monitor.momentumThresholds;
    if (!symbol || !Monitor.momentumThresholds[symbol]) {
      return defaults;
    }
    return { ...defaults, ...Monitor.momentumThresholds[symbol] };
  };

  // 获取特定品种的 EMA 周期（支持按品种配置）
  Monitor.getMomentumPeriods = function (symbol) {
    const d = Monitor.momentumPeriods?.default || { shortP: 5, longP: 20 };
    if (!symbol || !Monitor.momentumPeriods?.[symbol]) return d;
    return { ...d, ...Monitor.momentumPeriods[symbol] };
  };

  Monitor.loadRuntimeConfig = async function () {
    try {
      const response = await fetch("monitor.config.json?t=" + Date.now(), { cache: "no-store" });
      if (!response.ok) throw new Error("config http " + response.status);
      const config = await response.json();
      Monitor.applyRuntimeConfig(config);
      return config;
    } catch (_) {
      Monitor.applyRuntimeConfig(defaultConfig);
      return defaultConfig;
    }
  };

  Monitor.defaultRuntimeConfig = defaultConfig;
  Monitor.apiBase = Monitor.getApiBase();
  Monitor.applyRuntimeConfig(defaultConfig);
})();
