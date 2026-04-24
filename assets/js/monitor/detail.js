/**
 * detail.js — 品种详情页
 * 点击全品类看板卡片后展开：价格卡片 + 动量信号 + 实时走势图 + Tick 记录
 * 复用 Monitor.ema / Monitor.calcMomentum / Monitor.renderSignal
 */
(function () {
  var Monitor = window.Monitor;
  if (!Monitor) return;

  var _inst = null;        // 当前查看的品种元数据
  var _livePoints = [];    // 实时价格序列 [{t, y}]
  var _ticks = [];         // tick 记录
  var _chart = null;       // Chart.js 实例
  var _pollTimer = null;   // 定时器
  var _prevBandwidth = null; // 上一次 BB 带宽
  var _signalHistory = [];    // signal history for timeline
  var MAX_POINTS = 600;
  var MAX_TICKS = 200;
  var MAX_SIG_HIST = 100;

  function $(id) { return document.getElementById(id); }

  /* ── 打开品种详情 ── */
  Monitor.openDetail = function (instMeta) {
    _inst = instMeta;
    _livePoints = [];
    _ticks = [];
    _prevBandwidth = null;

    // 更新静态 UI
    $("detailTitle").textContent = instMeta.name + " (" + instMeta.exchange + ")";
    $("dtLabel").innerHTML = '<span style="color:' + (instMeta.color || '#888') + '">●</span> ' +
      instMeta.name + ' <span class="badge">' + instMeta.id.toUpperCase() + '</span>';
    $("dtSigLabel").innerHTML = instMeta.name + ' 动量信号 <span class="ema-tag">EMA5/20+Boll</span>';
    $("dtChartLabel").textContent = instMeta.name + " 实时走势 (" + (instMeta.unit || "") + ")";
    $("dtChartDot").style.background = instMeta.color || "#888";
    $("dtTickTitle").textContent = instMeta.name + " 刷新记录";
    $("dtExchange").textContent = instMeta.exchange || "--";
    $("dtCurrency").textContent = instMeta.currency || "--";
    $("dtUnit").textContent = instMeta.unit || "--";

    // 清空动态内容
    $("dtPrice").textContent = "--";
    $("dtPrice").className = "price-main";
    $("dtChange").textContent = "--";
    $("dtChange").className = "price-change";
    $("dtSub").textContent = "";
    $("dtSource").textContent = "--";
    $("dtOpen").textContent = "--";
    $("dtHigh").textContent = "--";
    $("dtLow").textContent = "--";
    $("dtTickBody").innerHTML = "";
    $("dtTickCount").textContent = "0 条";
    $("dtRtCount").textContent = "0点";

    // reset momentum
    Monitor.renderSignal("dt", null, instMeta.decimals || 2);

    _signalHistory = [];

    // 初始化图表
    _initChart(instMeta);

    // 切换 tab
    Monitor.switchTab("detail");

    // 立即拉一次 + 开始轮询
    _fetchDetail();
    _startPoll();
  };

  /* ── 初始化/重建实时图 ── */
  function _initChart(inst) {
    if (_chart) { _chart.destroy(); _chart = null; }
    var canvas = $("dtRtChart");
    if (!canvas) return;
    var ctx = canvas.getContext("2d");
    _chart = new Chart(ctx, {
      type: "line",
      data: {
        datasets: [
          {
            label: inst.name,
            data: [],
            borderColor: inst.color || "#58a6ff",
            backgroundColor: _hexToRgba(inst.color || "#58a6ff", 0.08),
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.2,
            fill: true,
            order: 1,
          },
          {
            label: "BB Upper",
            data: [],
            borderColor: "rgba(255,200,50,0.3)",
            borderWidth: 1,
            borderDash: [4, 2],
            pointRadius: 0,
            fill: false,
            order: 2,
          },
          {
            label: "BB Lower",
            data: [],
            borderColor: "rgba(255,200,50,0.3)",
            borderWidth: 1,
            borderDash: [4, 2],
            pointRadius: 0,
            fill: "-1",
            backgroundColor: "rgba(255,200,50,0.04)",
            order: 2,
          },
          {
            label: "EMA Short",
            data: [],
            borderColor: "rgba(0,200,100,0.5)",
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            order: 3,
          },
          {
            label: "EMA Long",
            data: [],
            borderColor: "rgba(200,100,0,0.5)",
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
            order: 3,
          },
        ]
      },
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
            callbacks: {
              label: function (ctx) { return ctx.parsed.y.toFixed(inst.decimals || 2); }
            }
          }
        }
      }
    });
  }

  function _hexToRgba(hex, alpha) {
    hex = hex.replace("#", "");
    if (hex.length === 3) hex = hex[0]+hex[0]+hex[1]+hex[1]+hex[2]+hex[2];
    var r = parseInt(hex.substring(0,2),16);
    var g = parseInt(hex.substring(2,4),16);
    var b = parseInt(hex.substring(4,6),16);
    return "rgba("+r+","+g+","+b+","+alpha+")";
  }

  /* ── 轮询 ── */
  function _startPoll() {
    _stopPoll();
    var ms = (Monitor.constants && Monitor.constants.POLL_MS) || 3000;
    _pollTimer = setInterval(_fetchDetail, ms);
  }

  function _stopPoll() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  /* ── 数据获取 + 渲染 ── */
  function _fetchDetail() {
    if (!_inst) return;
    fetch(Monitor.apiBase + "/api/instrument/" + _inst.id + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || d.error || !d.price) return;
        _renderPrice(d);
        _addLivePoint(d);
        _updateChart();
        _updateMomentum();
        _addTick(d);
        _renderTicks();
      })
      .catch(function (err) { console.error("[detail]", err); });
  }

  /* ── 价格卡片 ── */
  function _renderPrice(d) {
    var dec = (_inst && _inst.decimals) || 2;
    var dir = (d.changePercent > 0) ? "up" : (d.changePercent < 0) ? "down" : "";

    $("dtPrice").textContent = d.price.toFixed(dec);
    $("dtPrice").className = "price-main " + dir;

    var chgStr = d.change != null ? (d.change >= 0 ? "+" : "") + d.change.toFixed(dec) : "--";
    var pctStr = d.changePercent != null ? (d.changePercent >= 0 ? "+" : "") + d.changePercent.toFixed(2) + "%" : "--";
    $("dtChange").textContent = chgStr + " (" + pctStr + ")";
    $("dtChange").className = "price-change " + dir;

    $("dtSub").textContent = d.datetime_cst || "";
    $("dtSource").textContent = d.source || "--";

    if (d.open != null) $("dtOpen").textContent = d.open.toFixed(dec);
    if (d.high != null) $("dtHigh").textContent = d.high.toFixed(dec);
    if (d.low != null) $("dtLow").textContent = d.low.toFixed(dec);
  }

  /* ── 实时数据点（去重） ── */
  function _addLivePoint(d) {
    var price = d.price;
    var ts = d.timestamp || Date.now();
    if (_livePoints.length > 0 && _livePoints[_livePoints.length - 1].y === price) return;
    _livePoints.push({ t: ts, y: price });
    while (_livePoints.length > MAX_POINTS) _livePoints.shift();
  }

  /* ── 更新走势图（含 EMA/BB overlay） ── */
  function _updateChart() {
    if (!_chart) return;
    var pts = _livePoints.map(function (p) { return { x: p.t, y: p.y }; });
    _chart.data.datasets[0].data = pts;

    // Compute EMA/BB overlays
    var vals = _livePoints.map(function (p) { return p.y; });
    var th = _getThresholds();
    var per = _getPeriods();
    var emaS = Monitor.ema(vals, per.shortP);
    var emaL = Monitor.ema(vals, per.longP);

    _chart.data.datasets[3].data = emaS.map(function (v, i) {
      return v != null ? { x: _livePoints[i].t, y: v } : null;
    }).filter(Boolean);
    _chart.data.datasets[4].data = emaL.map(function (v, i) {
      return v != null ? { x: _livePoints[i].t, y: v } : null;
    }).filter(Boolean);

    // BB overlay
    var bbP = th.bbPeriod || 0;
    var bbM = th.bbMult || 2.0;
    var bbUpper = [], bbLower = [];
    if (bbP > 0) {
      for (var i = bbP - 1; i < vals.length; i++) {
        var slice = vals.slice(0, i + 1);
        var bb = Monitor.bollingerAt(slice, bbP, bbM);
        if (bb) {
          bbUpper.push({ x: _livePoints[i].t, y: bb.upper });
          bbLower.push({ x: _livePoints[i].t, y: bb.lower });
        }
      }
    }
    _chart.data.datasets[1].data = bbUpper;
    _chart.data.datasets[2].data = bbLower;

    _chart.update("none");
    $("dtRtCount").textContent = _livePoints.length + "点";
  }

  /* ── 参数继承：品种 → 品类 → default ── */
  function _getThresholds() {
    return Monitor.getMomentumThresholds(_inst.id, _inst.category);
  }
  function _getPeriods() {
    return Monitor.getMomentumPeriods(_inst.id, _inst.category);
  }

  /* ── 动量计算 + 渲染 + 信号历史 ── */
  function _updateMomentum() {
    var per = _getPeriods();
    var th = _getThresholds();
    var minLen = per.longP + 2;
    if (_livePoints.length < minLen) {
      Monitor.renderSignal("dt", null, (_inst && _inst.decimals) || 2);
      return;
    }

    var dtVolumes = _livePoints.map(p => p.v).filter(v => v != null);
    var info = Monitor.calcMomentum(_livePoints, per.shortP, per.longP, th, dtVolumes);
    Monitor.renderSignal("dt", info, (_inst && _inst.decimals) || 2);

    // Track signal history
    if (info) {
      var last = _signalHistory.length > 0 ? _signalHistory[_signalHistory.length - 1] : null;
      if (!last || last.signal !== info.signal) {
        _signalHistory.push({
          t: Date.now(),
          signal: info.signal,
          price: _livePoints[_livePoints.length - 1].y,
          rsi: info.rsi,
        });
        if (_signalHistory.length > MAX_SIG_HIST) _signalHistory.shift();
        _renderSignalHistory();
      }
    }
  }

  /* ── 信号变化历史 ── */
  function _renderSignalHistory() {
    var el = $("dtSigHistory");
    if (!el) return;
    var labels = { strong_buy: "强多", buy: "多", neutral: "观望", sell: "空", strong_sell: "强空" };
    var html = "";
    var len = Math.min(_signalHistory.length, 20);
    for (var i = _signalHistory.length - 1; i >= _signalHistory.length - len && i >= 0; i--) {
      var s = _signalHistory[i];
      var t = new Date(s.t).toLocaleTimeString("zh-CN", { hour12: false });
      var cls = s.signal.replace("_", "-");
      var rsiStr = s.rsi != null ? " RSI:" + s.rsi.toFixed(0) : "";
      html += '<div class="sig-hist-item ' + cls + '">' +
              '<span class="sig-hist-time">' + t + '</span>' +
              '<span class="signal-badge ' + cls + '">' + (labels[s.signal] || s.signal) + '</span>' +
              '<span class="sig-hist-price">' + s.price.toFixed((_inst && _inst.decimals) || 2) + rsiStr + '</span></div>';
    }
    el.innerHTML = html || '<div class="text-muted">暂无信号变化</div>';
  }

  /* ── Tick 记录 ── */
  function _addTick(d) {
    var now = new Date();
    var timeStr = now.toLocaleTimeString("zh-CN", { hour12: false });
    var dec = (_inst && _inst.decimals) || 2;
    var pctStr = d.changePercent != null ? (d.changePercent >= 0 ? "+" : "") + d.changePercent.toFixed(2) + "%" : "--";
    // 避免相邻重复
    if (_ticks.length > 0 && _ticks[0].price === d.price) return;
    _ticks.unshift({ time: timeStr, price: d.price, pct: pctStr, dec: dec });
    while (_ticks.length > MAX_TICKS) _ticks.pop();
  }

  function _renderTicks() {
    var body = $("dtTickBody");
    if (!body) return;
    var html = "";
    var len = Math.min(_ticks.length, 50);
    for (var i = 0; i < len; i++) {
      var t = _ticks[i];
      var cls = t.pct.startsWith("+") ? "up" : t.pct.startsWith("-") ? "down" : "";
      html += '<tr><td>' + t.time + '</td><td>' + t.price.toFixed(t.dec) +
              '</td><td class="pct ' + cls + '">' + t.pct + '</td></tr>';
    }
    body.innerHTML = html;
    $("dtTickCount").textContent = _ticks.length + " 条";
  }

  /* ── 清理（切走时停止轮询） ── */
  Monitor.closeDetail = function () {
    _stopPoll();
    if (_chart) { _chart.destroy(); _chart = null; }
    _inst = null;
    _livePoints = [];
    _ticks = [];
  };
})();
