// pages/index/index.js
const app = getApp();

// 行情数据缓存
let pollTimer = null;
const POLL_MS = 5000; // 5秒轮询

Page({
  data: {
    // 沪银
    hu: { price: '--', change: '--', changePct: '--', open: '--', high: '--', low: '--', volume: '--', source: '' },
    // COMEX
    comex: { price: '--', change: '--', changePct: '--', open: '--', high: '--', low: '--', volume: '--', source: '' },
    // 价差
    spread: { ratio: '--', cnySpread: '--', status: '--', statusType: 'neutral', usdCny: 7.26 },
    // 波动率
    hv: { hu: '--', comex: '--' },
    atr: { hu: '--', comex: '--' },
    // 走势图
    chartData: {},
    // 数据源状态
    activeSources: [],
    lastUpdate: '--',
    loading: false,
    alertCount: 0,
    // 服务器地址
    serverUrl: '',
  },

  onLoad() {
    this.setData({ serverUrl: app.globalData.serverUrl });
    this.fetchData();
    pollTimer = setInterval(() => this.fetchData(), POLL_MS);
  },

  onUnload() {
    if (pollTimer) clearInterval(pollTimer);
  },

  onPullDownRefresh() {
    this.fetchData(() => wx.stopPullDownRefresh());
  },

  // 手动刷新
  onRefresh() {
    this.setData({ loading: true });
    this.fetchData(() => this.setData({ loading: false }));
  },

  // 拉取数据
  fetchData(callback) {
    const serverUrl = this.data.serverUrl;
    if (!serverUrl || serverUrl === 'https://your-server.com') {
      // 演示模式：使用模拟数据
      this.useDemoData();
      if (callback) callback();
      return;
    }

    wx.request({
      url: `${serverUrl}/api/all`,
      method: 'GET',
      timeout: 10000,
      success: (res) => {
        if (res.statusCode === 200 && res.data) {
          this.processData(res.data);
        }
      },
      fail: (err) => {
        console.error('API request failed:', err);
        this.useDemoData();
      },
      complete: () => {
        if (callback) callback();
      }
    });
  },

  // 处理服务端数据
  processData(data) {
    const hu = data.huyin || {};
    const co = data.comex || {};
    const sp = data.spread || {};
    const hvData = data.hvSeries || {};

    // 沪银
    if (hu && !hu.error) {
      this.setData({
        'hu.price': this.fmtPrice(hu.price),
        'hu.change': this.fmtChg(hu.change),
        'hu.changePct': this.fmtPct(hu.changePercent),
        'hu.open': this.fmtPrice(hu.open),
        'hu.high': this.fmtPrice(hu.high),
        'hu.low': this.fmtPrice(hu.low),
        'hu.volume': hu.volume ? this.fmtVol(hu.volume) : '--',
        'hu.source': hu.source || '',
      });
    }

    // COMEX
    if (co && !co.error) {
      this.setData({
        'comex.price': this.fmtPrice(co.price, 3),
        'comex.change': this.fmtChg(co.change),
        'comex.changePct': this.fmtPct(co.changePercent),
        'comex.open': this.fmtPrice(co.open, 3),
        'comex.high': this.fmtPrice(co.high, 3),
        'comex.low': this.fmtPrice(co.low, 3),
        'comex.volume': co.volume ? this.fmtVol(co.volume) : '--',
        'comex.source': co.source || '',
      });
    }

    // 价差
    if (sp && sp.ratio) {
      const st = sp.status || '均衡';
      const stType = st.includes('溢价') ? 'up' : st.includes('折价') ? 'dn' : 'neutral';
      this.setData({
        'spread.ratio': sp.ratio.toFixed(4),
        'spread.cnySpread': sp.cnySpread ? (sp.cnySpread >= 0 ? '+' : '') + sp.cnySpread.toFixed(0) : '--',
        'spread.status': st,
        'spread.statusType': stType,
        'spread.usdCny': (sp.usdCNY || 7.26).toFixed(2),
      });
    }

    // 波动率指标
    if (hvData.hu && hvData.hu.length > 0) {
      const huHV = hvData.hu[hvData.hu.length - 1].y;
      this.setData({ 'hv.hu': huHV.toFixed(1) + '%' });
    }
    if (hvData.comex && hvData.comex.length > 0) {
      const coHV = hvData.comex[hvData.comex.length - 1].y;
      this.setData({ 'hv.comex': coHV.toFixed(1) + '%' });
    }

    this.setData({
      activeSources: data.activeSources || [],
      lastUpdate: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    });
  },

  // 演示数据
  useDemoData() {
    this.setData({
      'hu.price': '18,362.0',
      'hu.change': '+44.0',
      'hu.changePct': '+0.24%',
      'hu.open': '18,318.0',
      'hu.high': '18,395.0',
      'hu.low': '18,295.0',
      'hu.volume': '12.3万',
      'hu.source': 'akshare',
      'comex.price': '32.150',
      'comex.change': '+0.070',
      'comex.changePct': '+0.22%',
      'comex.open': '32.050',
      'comex.high': '32.480',
      'comex.low': '31.920',
      'comex.volume': '16.5K',
      'comex.source': 'Stooq',
      'spread.ratio': '1.0581',
      'spread.cnySpread': '+986',
      'spread.status': '轻度溢价',
      'spread.statusType': 'up',
      'hv.hu': '15.3%',
      'hv.comex': '24.7%',
      activeSources: ['akshare-sina', 'Stooq-COMEX'],
      lastUpdate: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    });
  },

  // 格式化工具
  fmtPrice(v, dec = 1) {
    if (v == null || v === '--') return '--';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  },
  fmtChg(v) {
    if (v == null) return '--';
    const sign = v >= 0 ? '+' : '';
    return sign + Number(v).toFixed(1);
  },
  fmtPct(v) {
    if (v == null) return '--';
    const sign = v >= 0 ? '+' : '';
    return sign + Number(v).toFixed(2) + '%';
  },
  fmtVol(v) {
    if (v >= 10000) return (v / 10000).toFixed(1) + '万';
    if (v >= 1000) return (v / 1000).toFixed(0) + 'K';
    return String(v);
  },

  // 跳转预警页
  goAlerts() {
    wx.switchTab({ url: '/pages/alerts/alerts' });
  },
});
