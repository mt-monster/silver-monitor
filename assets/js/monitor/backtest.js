// backtest.js — Silver Monitor 回测绩效卡片渲染与API
(function () {
  const Monitor = window.Monitor = window.Monitor || {};

  // 内部状态
  let _isFetching = false;
  let _refreshTimer = null;
  let _charts = {};

  // ── 工具函数 ──
  function _el(id) { return document.getElementById(id); }

  function _fmtPct(v) {
    if (v == null || isNaN(v)) return '--';
    const sign = v > 0 ? '+' : '';
    return sign + v.toFixed(2) + '%';
  }

  function _fmtNum(v, digits) {
    if (v == null || isNaN(v)) return '--';
    return v.toFixed(digits != null ? digits : 2);
  }

  function _clsForPct(v) {
    if (v == null || isNaN(v)) return '';
    return v > 0 ? 'up' : v < 0 ? 'down' : '';
  }

  // ── 构建指标行 HTML ──
  function _buildMetricRows(data) {
    if (!data || !data.metrics) {
      return '<div class="bt-empty">暂无数据</div>';
    }
    const m = data.metrics;
    const hasAnn = m.annualizedReturnPct != null;
    const annRow = hasAnn
      ? `<div class="bt-row"><span class="bt-label">年化收益</span><span class="bt-val ${_clsForPct(m.annualizedReturnPct)}">${_fmtPct(m.annualizedReturnPct)}</span></div>
         <div class="bt-row"><span class="bt-label">夏普比率</span><span class="bt-val">${_fmtNum(m.sharpeRatio, 2)}</span></div>`
      : '<div class="bt-row" style="font-size:9px;color:#6e7681;justify-content:center;border-bottom:none"><span>年化/夏普不适用于短周期回测</span></div>';
    return `
      <div class="bt-row">
        <span class="bt-label">总收益率</span>
        <span class="bt-val bt-main ${_clsForPct(m.totalReturnPct)}">${_fmtPct(m.totalReturnPct)}</span>
      </div>
      <div class="bt-row">
        <span class="bt-label">最大回撤</span>
        <span class="bt-val ${_clsForPct(-Math.abs(m.maxDrawdownPct || 0))}">${_fmtPct(-Math.abs(m.maxDrawdownPct || 0))}</span>
      </div>
      <div class="bt-row">
        <span class="bt-label">完整回合</span>
        <span class="bt-val">${_fmtNum(m.roundTripCount, 0)}</span>
      </div>
      <div class="bt-row">
        <span class="bt-label">胜率</span>
        <span class="bt-val">${m.winRatePct != null ? m.winRatePct.toFixed(1) + '%' : '--'}</span>
      </div>
      <div class="bt-row">
        <span class="bt-label">盈亏比</span>
        <span class="bt-val">${m.profitFactor === '∞' ? '∞' : (m.profitFactor != null ? m.profitFactor.toFixed(2) : '--')}</span>
      </div>
      <div class="bt-row">
        <span class="bt-label">每笔平均</span>
        <span class="bt-val ${_clsForPct(m.avgTradeReturnPct)}">${_fmtPct(m.avgTradeReturnPct)}</span>
      </div>
      <div class="bt-row">
        <span class="bt-label">平均持仓</span>
        <span class="bt-val">${m.avgHoldingBars != null ? m.avgHoldingBars.toFixed(1) + 's' : '--'}</span>
      </div>
    `;
  }

  function _buildFoot(data) {
    if (!data || !data.meta) return '';
    const meta = data.meta;
    const interval = meta.interval || '--';
    const bars = meta.bars != null ? meta.bars : '--';
    const from = meta.from || '';
    const to = meta.to || '';
    const sourceLabel = meta.dataSource === 'realtime' ? `实时(${meta.lookbackMinutes}min)` : interval;
    return `<span>来源: ${sourceLabel}</span><span>样本: ${bars}条</span><span>${from} ~ ${to}</span>`;
  }

  function _buildMetaLabel(data) {
    if (!data || !data.meta) return 'Long-Only · 实时5min';
    const meta = data.meta;
    return meta.dataSource === 'realtime' ? `Long-Only · 实时${meta.lookbackMinutes}min` : 'Long-Only · 实时';
  }

  // ── Chart.js 权益曲线绘制 ──
  function _initOrUpdateChart(canvasId, equityData, label, color) {
    const ctx = _el(canvasId);
    if (!ctx) return;

    const points = (equityData || []).map(function (p) {
      return { x: p.t, y: p.equity };
    });

    if (_charts[canvasId]) {
      _charts[canvasId].data.datasets[0].data = points;
      _charts[canvasId].data.datasets[0].label = label;
      _charts[canvasId].data.datasets[0].borderColor = color;
      _charts[canvasId].update('none');
      return;
    }

    _charts[canvasId] = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: [{
          label: label,
          data: points,
          borderColor: color,
          backgroundColor: color.replace(')', ',0.1)').replace('rgb', 'rgba'),
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 3,
          fill: true,
          tension: 0.2,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: true,
            callbacks: {
              title: function (items) {
                const d = new Date(items[0].parsed.x);
                return d.toLocaleTimeString('zh-CN', { hour12: false });
              },
              label: function (item) {
                return '权益: ' + item.parsed.y.toFixed(4);
              }
            }
          }
        },
        scales: {
          x: {
            type: 'linear',
            display: false,
            ticks: { display: false }
          },
          y: {
            display: true,
            position: 'right',
            grid: { color: 'rgba(48,54,61,0.5)' },
            ticks: {
              color: '#484f58',
              font: { size: 9, family: "'JetBrains Mono',monospace" },
              callback: function (value) { return value.toFixed(2); }
            }
          }
        }
      }
    });
  }

  // ── API 请求 ──
  function _fetchBacktest(symbol, strategy) {
    const body = {
      symbol: symbol,
      strategy: strategy,
      mode: 'long_only',
      data_source: 'realtime',
      lookback_minutes: 5,
    };

    return fetch(Monitor.apiBase + '/api/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      if (!r.ok) return null;
      return r.json();
    }).then(function (j) {
      if (j && j.ok && j.metrics) {
        return {
          metrics: j.metrics,
          meta: j.meta || {},
          trades: j.trades || [],
          equity: j.equity || [],
        };
      }
      return null;
    }).catch(function () {
      return null;
    });
  }

  // ── 主加载入口 ──
  Monitor.fetchAndRenderBacktest = function () {
    const symbolSel = _el('backtestSymbol');
    const symbol = symbolSel ? symbolSel.value : 'comex';

    if (_isFetching) return;
    _isFetching = true;

    // 显示加载中
    const momEl = _el('btMomentumMetrics');
    const revEl = _el('btReversalMetrics');
    if (momEl) momEl.innerHTML = '<div class="bt-loading">加载中...</div>';
    if (revEl) revEl.innerHTML = '<div class="bt-loading">加载中...</div>';

    Promise.all([
      _fetchBacktest(symbol, 'momentum'),
      _fetchBacktest(symbol, 'reversal'),
    ]).then(function (results) {
      _isFetching = false;
      const momentum = results[0];
      const reversal = results[1];

      // 渲染动量指标
      if (momEl) {
        momEl.innerHTML = momentum ? _buildMetricRows(momentum) : '<div class="bt-error">数据不足或回测失败</div>';
      }
      const momMeta = _el('btMomentumMeta');
      if (momMeta) momMeta.textContent = _buildMetaLabel(momentum);
      const momFoot = _el('btMomentumFoot');
      if (momFoot) momFoot.innerHTML = _buildFoot(momentum);

      // 渲染反转指标
      if (revEl) {
        revEl.innerHTML = reversal ? _buildMetricRows(reversal) : '<div class="bt-error">数据不足或回测失败</div>';
      }
      const revMeta = _el('btReversalMeta');
      if (revMeta) revMeta.textContent = _buildMetaLabel(reversal);
      const revFoot = _el('btReversalFoot');
      if (revFoot) revFoot.innerHTML = _buildFoot(reversal);

      // 绘制权益曲线
      _initOrUpdateChart('btMomentumChart', momentum ? momentum.equity : [], '动量权益', 'rgb(57,210,192)');
      _initOrUpdateChart('btReversalChart', reversal ? reversal.equity : [], '反转权益', 'rgb(163,113,247)');
    });
  };

  // ── 初始化绑定 ──
  Monitor.initBacktestCard = function () {
    const symbolSel = _el('backtestSymbol');
    const refreshBtn = _el('backtestRefresh');

    if (symbolSel) symbolSel.onchange = Monitor.fetchAndRenderBacktest;
    if (refreshBtn) refreshBtn.onclick = Monitor.fetchAndRenderBacktest;

    // 立即加载一次
    Monitor.fetchAndRenderBacktest();

    // 不设置自动刷新，仅保留手动刷新按钮
  };

  // 清理定时器
  Monitor.stopBacktestRefresh = function () {
    if (_refreshTimer) {
      clearInterval(_refreshTimer);
      _refreshTimer = null;
    }
  };
})();
