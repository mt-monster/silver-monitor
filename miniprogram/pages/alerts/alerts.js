// pages/alerts/alerts.js
const app = getApp();

Page({
  data: {
    alerts: [],
    tickBuffer: [],
    currentPrice: '--',
    currentPct: '--',
    stats: { upCount: 0, dnCount: 0, maxPct: 0, totalChecks: 0 },
    threshold: 1.0,
    soundOn: true,
    connected: false,
  },

  onLoad() {
    this.fetchAlerts();
    this._timer = setInterval(() => this.fetchAlerts(), 5000);
  },

  onUnload() {
    if (this._timer) clearInterval(this._timer);
  },

  fetchAlerts() {
    const serverUrl = app.globalData.serverUrl;
    if (!serverUrl || serverUrl === 'https://your-server.com') {
      this.useDemoAlerts();
      return;
    }

    wx.request({
      url: `${serverUrl}/api/alerts`,
      method: 'GET',
      timeout: 8000,
      success: (res) => {
        if (res.statusCode === 200 && res.data) {
          this.processAlerts(res.data);
        }
      },
      fail: () => {
        this.useDemoAlerts();
      }
    });
  },

  processAlerts(data) {
    const alerts = (data.alerts || []).map(a => ({
      ...a,
      time: this.fmtTime(a.ts || a.timestamp),
      pctStr: (a.pct || a.change_pct || 0).toFixed(2) + '%',
      level: this.getLevel(a.pct || a.change_pct || 0),
      direction: (a.pct || a.change_pct || 0) >= 0 ? 'up' : 'dn',
      dirIcon: (a.pct || a.change_pct || 0) >= 0 ? '🔺' : '🔻',
    }));

    const stats = data.stats || {};
    this.setData({
      alerts,
      connected: true,
      currentPrice: data.currentPrice ? this.fmtPrice(data.currentPrice) : '--',
      stats: {
        upCount: stats.up_count || stats.upCount || 0,
        dnCount: stats.dn_count || stats.dnCount || 0,
        maxPct: stats.max_pct || stats.maxPct || 0,
        totalChecks: stats.total_checks || stats.totalChecks || 0,
      }
    });

    // 检查最新预警并播放声音
    if (alerts.length > 0 && this.data.soundOn) {
      const latest = alerts[0];
      if (latest.isNew) {
        this.playAlertSound(latest.direction);
      }
    }
  },

  useDemoAlerts() {
    this.setData({
      connected: false,
      currentPrice: '32.150',
      stats: { upCount: 2, dnCount: 1, maxPct: 1.35, totalChecks: 142 },
      alerts: [
        { time: '13:08:25', dirIcon: '🔺', pctStr: '+1.35%', level: 'MEDIUM', direction: 'up', price: '32.45', source: 'Stooq' },
        { time: '12:52:10', dirIcon: '🔻', pctStr: '-1.02%', level: 'LOW', direction: 'dn', price: '31.80', source: 'Stooq' },
        { time: '11:30:45', dirIcon: '🔺', pctStr: '+1.18%', level: 'LOW', direction: 'up', price: '32.20', source: 'Stooq' },
      ]
    });
  },

  getLevel(pct) {
    const abs = Math.abs(pct);
    if (abs >= 3) return 'HIGH';
    if (abs >= 2) return 'MEDIUM';
    return 'LOW';
  },

  fmtTime(ts) {
    if (!ts) return '--';
    const d = new Date(ts);
    return d.toLocaleTimeString('zh-CN', { hour12: false });
  },

  fmtPrice(v) {
    return Number(v).toFixed(3);
  },

  // 播放预警声音
  playAlertSound(direction) {
    try {
      const ctx = wx.createInnerAudioContext();
      // 使用系统提示音
      if (direction === 'up') {
        // 急涨
      } else {
        // 急跌
      }
      ctx.destroy();
    } catch (e) {
      // 忽略音频错误
    }
  },

  // 切换声音
  toggleSound() {
    this.setData({ soundOn: !this.data.soundOn });
    wx.vibrateShort(this.data.soundOn ? 'heavy' : 'light');
  },

  // 清空预警
  clearAlerts() {
    wx.showModal({
      title: '确认清空',
      content: '确定要清空所有预警记录吗？',
      success: (res) => {
        if (res.confirm) {
          this.setData({ alerts: [] });
        }
      }
    });
  },

  // 手动刷新
  onRefresh() {
    this.fetchAlerts();
    wx.vibrateShort('light');
  },
});
