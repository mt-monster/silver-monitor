// combined_backtest.js — 组合策略回测绩效卡片渲染
(function () {
  const Monitor = window.Monitor = window.Monitor || {};

  let _isFetching = false;
  let _chart = null;

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

  function _initOrUpdateChart(canvasId, equityData) {
    const ctx = _el(canvasId);
    if (!ctx) return;

    const points = (equityData || []).map(function (p) {
      return { x: p.t, y: p.equity };
    });

    const color = 'rgb(210,153,34)';

    if (_chart) {
      _chart.data.datasets[0].data = points;
      _chart.update('none');
      return;
    }

    _chart = new Chart(ctx, {
      type: 'line',
      data: {
        datasets: [{
          label: '组合权益',
          data: points,
          borderColor: color,
          backgroundColor: 'rgba(210,153,34,0.1)',
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

  function _fetchCombinedBacktest(symbol) {
    const body = {
      symbol: symbol,
      strategy: 'combined',
      mode: 'long_only',
      data_source: 'realtime',
      lookback_minutes: 5,
      combined_params: {
        enable_mtf: true,
        require_strong_to_trade: true,
        conflict_preference: 'reversal',
      },
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

  Monitor.fetchAndRenderCombinedBacktest = function () {
    const symbolSel = _el('cmbBacktestSymbol');
    const symbol = symbolSel ? symbolSel.value : 'comex';

    if (_isFetching) return;
    _isFetching = true;

    const metricsEl = _el('cmbBacktestMetrics');
    if (metricsEl) metricsEl.innerHTML = '<div class="bt-loading">加载中...</div>';

    _fetchCombinedBacktest(symbol).then(function (data) {
      _isFetching = false;

      if (metricsEl) {
        metricsEl.innerHTML = data ? _buildMetricRows(data) : '<div class="bt-error">数据不足或回测失败</div>';
      }
      const metaEl = _el('cmbBacktestMeta');
      if (metaEl) metaEl.textContent = _buildMetaLabel(data);
      const footEl = _el('cmbBacktestFoot');
      if (footEl) footEl.innerHTML = _buildFoot(data);

      _initOrUpdateChart('cmbBacktestChart', data ? data.equity : []);
    });
  };

  Monitor.initCombinedBacktestCard = function () {
    const symbolSel = _el('cmbBacktestSymbol');
    const refreshBtn = _el('cmbBacktestRefresh');

    if (symbolSel) symbolSel.onchange = Monitor.fetchAndRenderCombinedBacktest;
    if (refreshBtn) refreshBtn.onclick = Monitor.fetchAndRenderCombinedBacktest;

    Monitor.fetchAndRenderCombinedBacktest();
  };
})();
