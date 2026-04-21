(function () {
  const Monitor = window.Monitor;

  /** EMA with SMA seed（与后端 ema_series 对齐） */
  Monitor.ema = function (values, period) {
    if (!values.length) return [];
    const k = 2 / (period + 1);
    if (values.length >= period) {
      let sum = 0;
      for (let i = 0; i < period; i++) sum += values[i];
      const seed = sum / period;
      const out = new Array(period);
      for (let i = 0; i < period - 1; i++) out[i] = null;
      out[period - 1] = seed;
      for (let i = period; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
      return out;
    }
    const out = [values[0]];
    for (let i = 1; i < values.length; i++) out.push(values[i] * k + out[i - 1] * (1 - k));
    return out;
  };

  /** 计算最后一根 bar 的 Bollinger Band（与后端 bollinger_at 对齐） */
  Monitor.bollingerAt = function (values, period, mult) {
    const n = values.length;
    if (n < period || period < 2) return null;
    let sum = 0;
    for (let i = n - period; i < n; i++) sum += values[i];
    const sma = sum / period;
    let varSum = 0;
    for (let i = n - period; i < n; i++) varSum += (values[i] - sma) ** 2;
    const std = Math.sqrt(varSum / period);
    const upper = sma + mult * std;
    const lower = sma - mult * std;
    const bw = upper - lower;
    const pctB = bw > 1e-12 ? (values[n - 1] - lower) / bw : 0.5;
    const bandwidth = sma > 0 ? (bw / sma) * 100 : 0;
    return { upper, middle: sma, lower, percentB: pctB, bandwidth };
  };

  /** RSI via Wilder's smoothing（与后端 rsi_series 对齐） */
  Monitor.rsiAt = function (values, period) {
    const n = values.length;
    if (n < period + 1) return null;
    let ag = 0, al = 0;
    for (let i = 1; i <= period; i++) {
      const d = values[i] - values[i - 1];
      ag += Math.max(d, 0);
      al += Math.max(-d, 0);
    }
    ag /= period; al /= period;
    let rsi = al < 1e-12 ? 100 : 100 - 100 / (1 + ag / al);
    for (let i = period + 1; i < n; i++) {
      const d = values[i] - values[i - 1];
      ag = (ag * (period - 1) + Math.max(d, 0)) / period;
      al = (al * (period - 1) + Math.max(-d, 0)) / period;
      rsi = al < 1e-12 ? 100 : 100 - 100 / (1 + ag / al);
    }
    return rsi;
  };

})();
