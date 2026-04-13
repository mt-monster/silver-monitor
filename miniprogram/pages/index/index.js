// pages/index/index.js
const app = getApp();

// 行情数据缓存
let pollTimer = null;
const POLL_MS = 5000; // 5秒轮询

Page({
  data: {
    activeTab: 'silver',
    // 沪银
    hu: { price: '--', change: '--', changePct: '--', open: '--', high: '--', low: '--', volume: '--', source: '' },
    // COMEX
    comex: { price: '--', change: '--', changePct: '--', open: '--', high: '--', low: '--', volume: '--', source: '' },
    // 沪金
    au: { price: '--', change: '--', changePct: '--', open: '--', high: '--', low: '--', volume: '--', source: '' },
    // COMEX 金
    comexGold: { price: '--', change: '--', changePct: '--', open: '--', high: '--', low: '--', volume: '--', source: '' },
    // 价差
    spread: { ratio: '--', cnySpread: '--', status: '--', statusType: 'neutral', usdCny: 7.26 },
    goldSpread: { ratio: '--', cnySpread: '--', status: '--', statusType: 'neutral', usdCny: 7.26 },
    // 波动率
    hv: { hu: '--', comex: '--', au: '--', comexGold: '--' },
    atr: { hu: '--', comex: '--' },
    // 走势图
    chartData: {},
    // 数据源状态
    activeSources: [],
    sourceSummary: '',
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

  switchTab(e) {
    const { tab } = e.currentTarget.dataset;
    if (tab && tab !== this.data.activeTab) {
      this.setData({ activeTab: tab });
    }
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
    const au = data.hujin || {};
    const cg = data.comexGold || {};
    const goldSp = data.goldSpread || {};
    const hvData = data.hvSeries || {};
    const nextData = {};

    // 沪银
    if (hu && !hu.error) {
      nextData['hu.price'] = hu.closed ? '休市' : this.fmtPrice(hu.price);
      nextData['hu.change'] = hu.closed ? (hu.status_desc || '休盘中') : this.fmtChg(hu.change);
      nextData['hu.changePct'] = hu.closed ? '--' : this.fmtPct(hu.changePercent);
      nextData['hu.open'] = this.fmtPrice(hu.open);
      nextData['hu.high'] = this.fmtPrice(hu.high);
      nextData['hu.low'] = this.fmtPrice(hu.low);
      nextData['hu.volume'] = hu.volume ? this.fmtVol(hu.volume) : '--';
      nextData['hu.source'] = hu.source || (hu.closed ? '休市' : '');
    }

    // COMEX
    if (co && !co.error) {
      nextData['comex.price'] = co.closed ? '休市' : this.fmtPrice(co.price, 3);
      nextData['comex.change'] = co.closed ? (co.status_desc || '休盘中') : this.fmtChg(co.change, 3);
      nextData['comex.changePct'] = co.closed ? '--' : this.fmtPct(co.changePercent);
      nextData['comex.open'] = this.fmtPrice(co.open, 3);
      nextData['comex.high'] = this.fmtPrice(co.high, 3);
      nextData['comex.low'] = this.fmtPrice(co.low, 3);
      nextData['comex.volume'] = co.volume ? this.fmtVol(co.volume) : '--';
      nextData['comex.source'] = co.source || (co.closed ? '休市' : '');
    }

    // 沪金
    if (au && !au.error) {
      nextData['au.price'] = au.closed ? '休市' : this.fmtPrice(au.price, 2);
      nextData['au.change'] = au.closed ? (au.status_desc || '休盘中') : this.fmtChg(au.change, 2);
      nextData['au.changePct'] = au.closed ? '--' : this.fmtPct(au.changePercent);
      nextData['au.open'] = this.fmtPrice(au.open, 2);
      nextData['au.high'] = this.fmtPrice(au.high, 2);
      nextData['au.low'] = this.fmtPrice(au.low, 2);
      nextData['au.volume'] = au.volume ? this.fmtVol(au.volume) : '--';
      nextData['au.source'] = au.source || (au.closed ? '休市' : '');
    }

    // COMEX 金
    if (cg && !cg.error) {
      nextData['comexGold.price'] = cg.closed ? '休市' : this.fmtPrice(cg.price, 2);
      nextData['comexGold.change'] = cg.closed ? (cg.status_desc || '休盘中') : this.fmtChg(cg.change, 2);
      nextData['comexGold.changePct'] = cg.closed ? '--' : this.fmtPct(cg.changePercent);
      nextData['comexGold.open'] = this.fmtPrice(cg.open, 2);
      nextData['comexGold.high'] = this.fmtPrice(cg.high, 2);
      nextData['comexGold.low'] = this.fmtPrice(cg.low, 2);
      nextData['comexGold.volume'] = cg.volume ? this.fmtVol(cg.volume) : '--';
      nextData['comexGold.source'] = cg.source || (cg.closed ? '休市' : '');
    }

    // 价差
    if (sp && sp.ratio) {
      const st = sp.status || '均衡';
      const stType = st.includes('溢价') ? 'up' : st.includes('折价') ? 'dn' : 'neutral';
      nextData['spread.ratio'] = sp.ratio.toFixed(4);
      nextData['spread.cnySpread'] = sp.cnySpread != null ? (sp.cnySpread >= 0 ? '+' : '') + sp.cnySpread.toFixed(0) : '--';
      nextData['spread.status'] = st;
      nextData['spread.statusType'] = stType;
      nextData['spread.usdCny'] = (sp.usdCNY || 7.26).toFixed(2);
    }

    if (goldSp && goldSp.ratio) {
      const st = goldSp.status || '均衡';
      const stType = st.includes('溢价') ? 'up' : st.includes('折价') ? 'dn' : 'neutral';
      nextData['goldSpread.ratio'] = goldSp.ratio.toFixed(4);
      nextData['goldSpread.cnySpread'] = goldSp.cnySpread != null ? (goldSp.cnySpread >= 0 ? '+' : '') + goldSp.cnySpread.toFixed(2) : '--';
      nextData['goldSpread.status'] = st;
      nextData['goldSpread.statusType'] = stType;
      nextData['goldSpread.usdCny'] = (goldSp.usdCNY || 7.26).toFixed(2);
    }

    // 波动率指标
    if (hvData.hu && hvData.hu.length > 0) {
      const huHV = hvData.hu[hvData.hu.length - 1].y;
      nextData['hv.hu'] = huHV.toFixed(1) + '%';
    }
    if (hvData.comex && hvData.comex.length > 0) {
      const coHV = hvData.comex[hvData.comex.length - 1].y;
      nextData['hv.comex'] = coHV.toFixed(1) + '%';
    }
    if (hvData.hujin && hvData.hujin.length > 0) {
      const auHV = hvData.hujin[hvData.hujin.length - 1].y;
      nextData['hv.au'] = auHV.toFixed(1) + '%';
    }
    if (hvData.comex_gold && hvData.comex_gold.length > 0) {
      const cgHV = hvData.comex_gold[hvData.comex_gold.length - 1].y;
      nextData['hv.comexGold'] = cgHV.toFixed(1) + '%';
    }

    nextData.activeSources = data.activeSources || [];
    nextData.sourceSummary = (data.activeSources || []).join(' + ');
    nextData.lastUpdate = new Date().toLocaleTimeString('zh-CN', { hour12: false });
    this.setData(nextData);
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
      'comex.source': 'Sina-XAG',
      'au.price': '782.36',
      'au.change': '+4.28',
      'au.changePct': '+0.55%',
      'au.open': '778.10',
      'au.high': '783.42',
      'au.low': '776.88',
      'au.volume': '8.6万',
      'au.source': 'Sina-AU0',
      'comexGold.price': '3,218.52',
      'comexGold.change': '+18.26',
      'comexGold.changePct': '+0.57%',
      'comexGold.open': '3,205.10',
      'comexGold.high': '3,223.44',
      'comexGold.low': '3,198.20',
      'comexGold.volume': '--',
      'comexGold.source': 'Sina-XAU',
      'spread.ratio': '1.0581',
      'spread.cnySpread': '+986',
      'spread.status': '轻度溢价',
      'spread.statusType': 'up',
      'goldSpread.ratio': '1.0126',
      'goldSpread.cnySpread': '+9.82',
      'goldSpread.status': '基本均衡',
      'goldSpread.statusType': 'neutral',
      'hv.hu': '15.3%',
      'hv.comex': '24.7%',
      'hv.au': '11.8%',
      'hv.comexGold': '16.4%',
      activeSources: ['Sina-AG0', 'Sina-XAG', 'Sina-AU0', 'Sina-XAU', 'akshare'],
      sourceSummary: 'Sina-AG0 + Sina-XAG + Sina-AU0 + Sina-XAU + akshare',
      lastUpdate: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    });
  },

  // 格式化工具
  fmtPrice(v, dec = 1) {
    if (v == null || v === '--') return '--';
    return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  },
  fmtChg(v, dec = 1) {
    if (v == null) return '--';
    const sign = v >= 0 ? '+' : '';
    return sign + Number(v).toFixed(dec);
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
