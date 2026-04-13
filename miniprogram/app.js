// app.js
App({
  onLaunch() {
    // 云开发初始化
    if (wx.cloud) {
      wx.cloud.init({
        traceUser: true,
      });
    }
  },
  globalData: {
    // 后端服务器地址（本地或部署后的地址）
    serverUrl: 'https://your-server.com',
    // COMEX 3-Tick 预警阈值（百分比）
    alertThreshold: 1.0,
  }
});
