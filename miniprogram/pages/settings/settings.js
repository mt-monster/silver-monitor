// pages/settings/settings.js
const app = getApp();

Page({
  data: {
    serverUrl: '',
    threshold: 1.0,
    thresholdIndex: 0,
    thresholdOptions: [0.5, 0.8, 1.0, 1.5, 2.0, 3.0],
    soundOn: true,
    vibrateOn: true,
    pollInterval: 5,
    pollIndex: 2,
    pollOptions: [1, 2, 5, 10, 15, 30],
    serverStatus: '未检测',
    serverSources: [],
  },

  onLoad() {
    this.loadSettings();
  },

  loadSettings() {
    try {
      const saved = wx.getStorageSync('silverMonitorSettings');
      if (saved) {
        const s = JSON.parse(saved);
        this.setData({
          serverUrl: s.serverUrl || '',
          threshold: s.threshold || 1.0,
          thresholdIndex: this.data.thresholdOptions.indexOf(s.threshold || 1.0),
          soundOn: s.soundOn !== false,
          vibrateOn: s.vibrateOn !== false,
          pollInterval: s.pollInterval || 5,
          pollIndex: this.data.pollOptions.indexOf(s.pollInterval || 5),
        });
        app.globalData.serverUrl = s.serverUrl || '';
        app.globalData.threshold = s.threshold || 1.0;
      }
    } catch (e) {}
  },

  saveSettings() {
    try {
      const s = {
        serverUrl: this.data.serverUrl,
        threshold: this.data.threshold,
        soundOn: this.data.soundOn,
        vibrateOn: this.data.vibrateOn,
        pollInterval: this.data.pollInterval,
      };
      wx.setStorageSync('silverMonitorSettings', JSON.stringify(s));
      app.globalData.serverUrl = s.serverUrl;
      app.globalData.threshold = s.threshold;
    } catch (e) {}
  },

  // 服务器地址输入
  onServerInput(e) {
    this.setData({ serverUrl: e.detail.value.trim() });
  },

  // 测试连接
  testConnection() {
    const url = this.data.serverUrl;
    if (!url) {
      wx.showToast({ title: '请输入服务器地址', icon: 'none' });
      return;
    }

    this.setData({ serverStatus: '检测中...' });

    wx.request({
      url: `${url}/api/status`,
      method: 'GET',
      timeout: 8000,
      success: (res) => {
        if (res.statusCode === 200) {
          this.setData({ serverStatus: '✅ 已连接' });
          wx.showToast({ title: '连接成功！', icon: 'success' });
        } else {
          this.setData({ serverStatus: '❌ 连接失败' });
        }
      },
      fail: () => {
        this.setData({ serverStatus: '❌ 无法连接' });
        wx.showToast({ title: '连接失败', icon: 'error' });
      }
    });

    // 获取数据源信息
    wx.request({
      url: `${url}/api/sources`,
      method: 'GET',
      timeout: 8000,
      success: (res) => {
        if (res.statusCode === 200 && res.data.available) {
          this.setData({ serverSources: res.data.available });
        }
      },
      fail: () => {}
    });
  },

  // 保存服务器配置
  saveServer() {
    this.saveSettings();
    wx.showToast({ title: '已保存', icon: 'success' });
  },

  // 阈值选择
  onThresholdChange(e) {
    const idx = e.detail.value;
    const val = this.data.thresholdOptions[idx];
    this.setData({ thresholdIndex: idx, threshold: val });
    this.saveSettings();
  },

  // 轮询间隔选择
  onPollChange(e) {
    const idx = e.detail.value;
    const val = this.data.pollOptions[idx];
    this.setData({ pollIndex: idx, pollInterval: val });
    this.saveSettings();
  },

  // 声音开关
  toggleSound() {
    this.setData({ soundOn: !this.data.soundOn });
    this.saveSettings();
  },

  // 震动开关
  toggleVibrate() {
    this.setData({ vibrateOn: !this.data.vibrateOn });
    this.saveSettings();
  },

  // 复制本地启动命令
  copyStartCmd() {
    wx.setClipboardData({
      data: 'cd silver-monitor && python server.py',
      success: () => {
        wx.showToast({ title: '已复制启动命令', icon: 'success' });
      }
    });
  },
});
