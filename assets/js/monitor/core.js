/** 核心配置加载与全局初始化：Monitor 命名空间、SSE 管理、API 基址、参数解析。
 *
 * 负责：
 * - 从 monitor.config.json 加载运行时配置
 * - 构建 momentumThresholds / momentumPeriods / reversalParams
 * - SSE 连接管理与心跳
 * - 全局常量定义
 */
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
      rsi_period: 14,
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
    btcTicks: [],
    lastBtcPrice: null,
    btcLivePoints: [],
    btcRealtimePoints: [],
    activeTab: "silver",
    isGoldChartsInitialized: false,
    isCryptoChartsInitialized: false,
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
    Monitor.constants.BAR_WINDOW_MS = Number(frontendConfig.bar_window_ms || 30000);
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
        bbPeriod: Number(defaults.bb_period != null ? defaults.bb_period : 20),
        bbMult: Number(defaults.bb_mult != null ? defaults.bb_mult : 2.0),
        rsiPeriod: Number(defaults.rsi_period != null ? defaults.rsi_period : 14),
        cooldownBars: Number(defaults.cooldown_bars != null ? defaults.cooldown_bars : 0),
        bbBuyKill: Number(defaults.bb_buy_kill != null ? defaults.bb_buy_kill : 0.3),
        bbSellKill: Number(defaults.bb_sell_kill != null ? defaults.bb_sell_kill : 0.7),
      },
    };

    // 品类默认参数
    Monitor.categoryDefaults = {};
    const catDefs = momentum.category_defaults || {};
    Object.keys(catDefs).forEach(cat => {
      const c = catDefs[cat];
      Monitor.categoryDefaults[cat] = {
        spreadEntry: Number(c.spread_entry ?? defaults.spread_entry),
        spreadStrong: Number(c.spread_strong ?? defaults.spread_strong),
        slopeEntry: Number(c.slope_entry ?? defaults.slope_entry ?? 0.02),
        strengthMul: Number(c.strength_multiplier ?? defaults.strength_multiplier ?? 120),
        bbPeriod: Number(c.bb_period ?? defaults.bb_period ?? 20),
        bbMult: Number(c.bb_mult ?? defaults.bb_mult ?? 2.0),
        rsiPeriod: Number(c.rsi_period ?? defaults.rsi_period ?? 14),
        cooldownBars: Number(c.cooldown_bars ?? defaults.cooldown_bars ?? 0),
        bbBuyKill: Number(c.bb_buy_kill ?? defaults.bb_buy_kill ?? 0.3),
        bbSellKill: Number(c.bb_sell_kill ?? defaults.bb_sell_kill ?? 0.7),
        shortP: Number(c.short_p ?? defaults.short_p),
        longP: Number(c.long_p ?? defaults.long_p),
      };
    });

    // 加载品种特定阈值（动态发现所有key）
    Object.keys(momentum).forEach(symbol => {
      if (symbol === "default" || symbol === "category_defaults" || symbol === "realtime" || typeof momentum[symbol] !== "object") return;
      const s = momentum[symbol];
      Monitor.momentumThresholds[symbol] = {
        spreadEntry: Number(s.spread_entry ?? defaults.spread_entry),
        spreadStrong: Number(s.spread_strong ?? defaults.spread_strong),
        slopeEntry: Number(s.slope_entry ?? defaults.slope_entry ?? 0.02),
        strengthMul: Number(s.strength_multiplier ?? defaults.strength_multiplier ?? 120),
        bbPeriod: Number(s.bb_period ?? defaults.bb_period ?? 20),
        bbMult: Number(s.bb_mult ?? defaults.bb_mult ?? 2.0),
        rsiPeriod: Number(s.rsi_period ?? defaults.rsi_period ?? 14),
        cooldownBars: Number(s.cooldown_bars ?? defaults.cooldown_bars ?? 0),
        bbBuyKill: Number(s.bb_buy_kill ?? defaults.bb_buy_kill ?? 0.3),
        bbSellKill: Number(s.bb_sell_kill ?? defaults.bb_sell_kill ?? 0.7),
        volumePeriod: Number(s.volume_period ?? defaults.volume_period ?? 0),
        volumeConfirmRatio: Number(s.volume_confirm_ratio ?? defaults.volume_confirm_ratio ?? 1.5),
        volumeWeakenRatio: Number(s.volume_weaken_ratio ?? defaults.volume_weaken_ratio ?? 0.6),
      };
    });

    // 品种级别 EMA 周期配置
    Monitor.momentumPeriods = {
      default: { shortP: Number(defaults.short_p), longP: Number(defaults.long_p) },
    };
    Object.keys(momentum).forEach(symbol => {
      if (symbol === "default" || symbol === "category_defaults" || symbol === "realtime" || typeof momentum[symbol] !== "object") return;
      Monitor.momentumPeriods[symbol] = {
        shortP: Number(momentum[symbol].short_p ?? defaults.short_p),
        longP: Number(momentum[symbol].long_p ?? defaults.long_p),
      };
    });

    // ── 实时数据专用参数覆盖（realtime 段）─────────────────────
    // 使实时信号面板与回测使用同一套微趋势参数
    const rtMomentum = momentum.realtime;
    if (rtMomentum && typeof rtMomentum === "object") {
      const rtDefaults = rtMomentum.default || {};
      Object.keys(rtMomentum).forEach(symbol => {
        if (symbol === "default" || typeof rtMomentum[symbol] !== "object") return;
        const rt = rtMomentum[symbol];
        // 合并到已有的品种阈值配置中
        if (Monitor.momentumThresholds[symbol]) {
          Monitor.momentumThresholds[symbol] = {
            ...Monitor.momentumThresholds[symbol],
            spreadEntry: Number(rt.spread_entry ?? rtDefaults.spread_entry ?? Monitor.momentumThresholds[symbol].spreadEntry),
            spreadStrong: Number(rt.spread_strong ?? rtDefaults.spread_strong ?? Monitor.momentumThresholds[symbol].spreadStrong),
            slopeEntry: Number(rt.slope_entry ?? rtDefaults.slope_entry ?? Monitor.momentumThresholds[symbol].slopeEntry),
            strengthMul: Number(rt.strength_multiplier ?? rtDefaults.strength_multiplier ?? Monitor.momentumThresholds[symbol].strengthMul),
            bbPeriod: Number(rt.bb_period ?? rtDefaults.bb_period ?? Monitor.momentumThresholds[symbol].bbPeriod),
            bbMult: Number(rt.bb_mult ?? rtDefaults.bb_mult ?? Monitor.momentumThresholds[symbol].bbMult),
            rsiPeriod: Number(rt.rsi_period ?? rtDefaults.rsi_period ?? Monitor.momentumThresholds[symbol].rsiPeriod),
            cooldownBars: Number(rt.cooldown_bars ?? rtDefaults.cooldown_bars ?? Monitor.momentumThresholds[symbol].cooldownBars),
            bbBuyKill: Number(rt.bb_buy_kill ?? rtDefaults.bb_buy_kill ?? Monitor.momentumThresholds[symbol].bbBuyKill),
            bbSellKill: Number(rt.bb_sell_kill ?? rtDefaults.bb_sell_kill ?? Monitor.momentumThresholds[symbol].bbSellKill),
            volumePeriod: Number(rt.volume_period ?? rtDefaults.volume_period ?? Monitor.momentumThresholds[symbol].volumePeriod),
            volumeConfirmRatio: Number(rt.volume_confirm_ratio ?? rtDefaults.volume_confirm_ratio ?? Monitor.momentumThresholds[symbol].volumeConfirmRatio),
            volumeWeakenRatio: Number(rt.volume_weaken_ratio ?? rtDefaults.volume_weaken_ratio ?? Monitor.momentumThresholds[symbol].volumeWeakenRatio),
          };
        }
        if (Monitor.momentumPeriods[symbol]) {
          Monitor.momentumPeriods[symbol] = {
            shortP: Number(rt.short_p ?? rtDefaults.short_p ?? Monitor.momentumPeriods[symbol].shortP),
            longP: Number(rt.long_p ?? rtDefaults.long_p ?? Monitor.momentumPeriods[symbol].longP),
          };
        }
      });
    }
    if (typeof Monitor.refreshMomentumLabels === "function") Monitor.refreshMomentumLabels();

    // ── 反转策略参数加载 ──────────────────────────────────────
    const reversal = config?.reversal || {};
    const rvDefaults = reversal.default || {};
    Monitor.reversalConfig = reversal;
    Monitor.reversalParams = { default: { ...rvDefaults } };
    Object.keys(reversal).forEach(symbol => {
      if (symbol === "default" || symbol === "realtime" || typeof reversal[symbol] !== "object") return;
      Monitor.reversalParams[symbol] = { ...rvDefaults, ...reversal[symbol] };
    });

    // ── 反转策略 realtime 段覆盖 ──────────────────────────────
    const rtReversal = reversal.realtime;
    if (rtReversal && typeof rtReversal === "object") {
      const rtDefaults = rtReversal.default || {};
      Object.keys(rtReversal).forEach(symbol => {
        if (symbol === "default" || typeof rtReversal[symbol] !== "object") return;
        const rt = rtReversal[symbol];
        if (Monitor.reversalParams[symbol]) {
          Monitor.reversalParams[symbol] = {
            ...Monitor.reversalParams[symbol],
            ...rtDefaults,
            ...rt,
          };
        }
      });
    }
  };

  // 品种 ID 别名映射（detail 页用 instrument ID，momentum 页/配置用 legacy key）
  const _symbolAliases = {
    ag0: "huyin", xag: "comex", au0: "hujin", xau: "comex_gold",
    huyin: "huyin", comex: "comex", hujin: "hujin", comex_gold: "comex_gold",
  };

  // 获取特定品种的动量参数（合并default和品种特定参数）
  Monitor.getMomentumThresholds = function (symbol, category) {
    const defaults = Monitor.momentumThresholds.default || Monitor.momentumThresholds;
    const key = symbol && _symbolAliases[symbol] || symbol;
    if (key && Monitor.momentumThresholds[key]) {
      return { ...defaults, ...Monitor.momentumThresholds[key] };
    }
    if (category && Monitor.categoryDefaults && Monitor.categoryDefaults[category]) {
      return { ...defaults, ...Monitor.categoryDefaults[category] };
    }
    return defaults;
  };

  // 获取特定品种的 EMA 周期（支持按品种配置）
  Monitor.getMomentumPeriods = function (symbol, category) {
    const d = Monitor.momentumPeriods?.default || { shortP: 5, longP: 20 };
    const key = symbol && _symbolAliases[symbol] || symbol;
    if (key && Monitor.momentumPeriods?.[key]) return { ...d, ...Monitor.momentumPeriods[key] };
    if (category && Monitor.categoryDefaults?.[category]) {
      const c = Monitor.categoryDefaults[category];
      return { shortP: c.shortP || d.shortP, longP: c.longP || d.longP };
    }
    return d;
  };

  // 获取特定品种的反转策略参数
  Monitor.getReversalParams = function (symbol) {
    const d = Monitor.reversalParams?.default || {};
    const key = symbol && _symbolAliases[symbol] || symbol;
    if (key && Monitor.reversalParams?.[key]) return { ...d, ...Monitor.reversalParams[key] };
    return { ...d };
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

  // Config hot-reload (every 60s)
  Monitor._configReloadTimer = null;
  Monitor.startConfigReload = function (intervalMs) {
    if (Monitor._configReloadTimer) clearInterval(Monitor._configReloadTimer);
    Monitor._configReloadTimer = setInterval(async () => {
      try { await Monitor.loadRuntimeConfig(); } catch (_) {}
    }, intervalMs || 60000);
  };

  // ── SSE 实时推送管理 ─────────────────────────────────────────────
  Monitor.sse = {
    /** @type {EventSource|null} */
    _es: null,
    connected: false,
    _reconnectTimer: null,
    _listeners: [],
  };

  /**
   * 注册 SSE 数据回调。每次收到 "data" 事件时调用 fn(payload)。
   */
  Monitor.sse.on = function (eventName, fn) {
    Monitor.sse._listeners.push({ event: eventName, fn });
    if (Monitor.sse._es) {
      Monitor.sse._es.addEventListener(eventName, function (e) {
        try { fn(JSON.parse(e.data)); } catch (_) {}
      });
    }
  };

  /**
   * 建立 SSE 连接。自动重连，连接成功后触发 onConnect 回调。
   */
  Monitor.sse.connect = function (onConnect) {
    if (Monitor.sse._es) {
      Monitor.sse._es.close();
      Monitor.sse._es = null;
    }
    if (Monitor.sse._reconnectTimer) {
      clearTimeout(Monitor.sse._reconnectTimer);
      Monitor.sse._reconnectTimer = null;
    }

    var url = Monitor.apiBase + "/api/stream";
    var es;
    try {
      es = new EventSource(url);
    } catch (_) {
      Monitor.sse.connected = false;
      return;
    }
    Monitor.sse._es = es;

    es.addEventListener("connected", function () {
      Monitor.sse.connected = true;
      if (onConnect) onConnect();
    });

    // 绑定已注册的事件监听器
    Monitor.sse._listeners.forEach(function (l) {
      es.addEventListener(l.event, function (e) {
        try { l.fn(JSON.parse(e.data)); } catch (_) {}
      });
    });

    es.onerror = function () {
      Monitor.sse.connected = false;
      es.close();
      Monitor.sse._es = null;
      // 3 秒后重连
      Monitor.sse._reconnectTimer = setTimeout(function () {
        Monitor.sse.connect(onConnect);
      }, 3000);
    };
  };

  Monitor.sse.close = function () {
    if (Monitor.sse._es) { Monitor.sse._es.close(); Monitor.sse._es = null; }
    if (Monitor.sse._reconnectTimer) { clearTimeout(Monitor.sse._reconnectTimer); Monitor.sse._reconnectTimer = null; }
    Monitor.sse.connected = false;
  };
})();
