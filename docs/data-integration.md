# 数据对接现状

> 更新日期：2026-04-20

## 一、数据源总览

| 数据源 | 类型 | 认证方式 | 覆盖品种 | 状态 |
|--------|------|----------|----------|------|
| **Sina 财经** | HTTP 轮询 | 无需认证 | 沪银、沪金、COMEX 银/金、USD/CNY、62 种期货 | ✅ 正常 |
| **iFinD (同花顺)** | SDK / HTTP REST | 账号密码 / refresh_token | COMEX 银 (XAGUSD.FX)、COMEX 金 (XAUUSD.FX)、沪银主力 (AG00.SHF) | ✅ 正常 |
| **Infoway WS (贵金属)** | WebSocket 推送 | API Key | COMEX 银 (XAGUSD)、COMEX 金 (XAUUSD) | ✅ 正常 |
| **Infoway WS (加密货币)** | WebSocket 推送 | API Key | BTC (BTCUSDT) | ✅ 正常 |

---

## 二、各品种数据来源与优先级

### 核心品种（FastDataPoller，1 秒轮询）

| 品种 | 代码 | 优先级 1 | 优先级 2 | 优先级 3 | 交易时段 |
|------|------|----------|----------|----------|----------|
| 沪银 | AG0 | iFinD `AG00.SHF` | Sina `nf_AG0` | — | 国内期货时段 |
| COMEX 银 | XAG | iFinD `XAGUSD.FX` | Infoway WS `XAGUSD` | Sina `hf_XAG` | COMEX 时段 |
| 沪金 | AU0 | Sina `nf_AU0` | — | — | 国内期货时段 |
| COMEX 金 | XAU | iFinD `XAUUSD.FX` | Infoway WS `XAUUSD` | Sina `hf_XAU` | COMEX 时段 |
| BTC | BTCUSDT | Infoway WS (crypto) | — | — | 24/7 全天候 |

### 辅助数据（SlowDataPoller，60 秒轮询）

| 数据 | 来源 | 说明 |
|------|------|------|
| USD/CNY 汇率 | Sina `fx_susdcny` | 用于美元→人民币换算 |
| 沪银 K 线 | Sina 60 分钟线（最多 200 根） | 历史图表 |
| COMEX 银 K 线 | Sina 日线（最多 60 根） | 历史图表 |
| 沪金 K 线 | Sina 60 分钟线（最多 200 根） | 历史图表 |
| COMEX 金 K 线 | Sina 日线（最多 60 根） | 历史图表 |

### 其他期货品种（CommodityPoller，1 秒轮询）

62 个品种通过 Sina 通用接口轮询，涵盖 6 大板块：

| 板块 | 品种数 | 代表品种 |
|------|--------|----------|
| 贵金属 | 4 | ag0, au0, xag, xau |
| 有色金属 | 7 | cu0 (铜), al0 (铝), zn0 (锌), ni0 (镍)… |
| 黑色系 | 8 | rb0 (螺纹), hc0 (热卷), i0 (铁矿)… |
| 能源化工 | 14 | sc0 (原油), fu0 (燃油), ta0 (PTA)… |
| 农产品 | 13 | m0 (豆粕), y0 (豆油), sr0 (白糖)… |
| 国际 | 3 | cl (WTI原油), ng (天然气), hg (COMEX铜) |

---

## 三、数据源详情

### 3.1 Sina 财经

- **协议**：HTTP GET，无认证
- **实时行情 URL**：
  - 国内期货：`https://hq.sinajs.cn/list=nf_{symbol}`
  - 国际期货：`https://hq.sinajs.cn/list=hf_{symbol}`
  - 外汇：`https://hq.sinajs.cn/list=fx_susdcny`
- **K 线 URL**：
  - 国内 60 分钟：`stock2.finance.sina.com.cn/.../InnerFuturesNewService.getFewMinLine?symbol={}&type=60`
  - 国际日线：`stock2.finance.sina.com.cn/.../GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={}`
- **特点**：免费、无频率限制、覆盖面广；国内品种数据稳定，国际品种偶有延迟

### 3.2 iFinD (同花顺量化)

- **协议**：iFinDPy SDK（优先） / HTTP REST（备用）
- **SDK 认证**：`THS_iFinDLogin(account, password)` → 返回 0 或 -201 表示成功
- **HTTP 认证**：`POST quantapi.51ifind.com/api/v1/get_access_token`，Header 携带 `refresh_token`
  - Token 有效期 7 天，6 天时自动刷新
- **当前配置**：
  - 账号：`zhzqsf001`（SDK 模式）
  - `refresh_token`：未配置（仅用 SDK 模式）
- **合约代码**：`XAGUSD.FX`（白银）、`XAUUSD.FX`（黄金）、`AG00.SHF`（沪银主力）
- **查询指标**：`latest;open;high;low;preClose;vol;amount;changeRatio;change;datetime`
- **特点**：数据质量高、延迟低；需要付费账号；不支持加密货币

### 3.3 Infoway WebSocket

- **协议**：WebSocket 持久连接，实时推送
- **URL**：`wss://data.infoway.io/ws?business={business}&apikey={api_key}`
- **认证**：URL 参数携带 API Key
- **消息协议**（JSON）：
  | code | 含义 |
  |------|------|
  | 10000 | 订阅请求（客户端→服务端） |
  | 10001 | 订阅确认 |
  | 10002 | 行情推送（Trade） |
  | 10004 | 深度推送（Depth） |
  | 10010 | 心跳（30 秒间隔） |
- **行情推送字段**（code=10002）：`s`(symbol), `p`(price), `t`(timestamp_ms), `v`(volume), `vw`(VWAP)
- **两条连接**：
  | 连接 | business | 订阅品种 | 线程名 |
  |------|----------|----------|--------|
  | 贵金属 | `common` | XAGUSD, XAUUSD | `infoway-ws` |
  | 加密货币 | `crypto` | BTCUSDT | `infoway-crypto-ws` |
- **过期检测**：common 60 秒无数据判定过期，crypto 120 秒
- **特点**：推送延迟极低（毫秒级）；作为 iFinD 的第二优先备份

---

## 四、后端缓存结构

所有实时数据存储在 `AppState` 单例中：

| 缓存字段 | 品种 | 格式 |
|----------|------|------|
| `silver_cache` | 沪银 AG0 | `{"data": MarketSnapshot, "ts": epoch}` |
| `comex_silver_cache` | COMEX 银 XAG | 同上 |
| `gold_cache` | 沪金 AU0 | 同上 |
| `comex_gold_cache` | COMEX 金 XAU | 同上 |
| `btc_cache` | BTC | 同上 |
| `usd_cny_cache` | USD/CNY 汇率 | `{"rate": float, "ts": epoch}` |
| `combined_cache` | 合并快照 | `/api/all` 响应缓存 |
| `instrument_caches` | 62 个期货品种 | `dict[inst_id → {"data", "ts"}]` |

Tick 环形缓冲区（用于异常跳动告警）：

| 字段 | 品种 |
|------|------|
| `silver_tick_ring` | AG0 |
| `comex_silver_tick_ring` | XAG |
| `gold_tick_ring` | AU0 |
| `comex_gold_tick_ring` | XAU |
| `btc_tick_ring` | BTC |

---

## 五、API 路由

### GET 接口

| 路由 | 说明 |
|------|------|
| `/api/all` | 所有核心品种合并快照 + 动量信号 |
| `/api/comex` | COMEX 银实时 |
| `/api/huyin`（别名 `/api/ag`, `/api/silver`） | 沪银实时 |
| `/api/hujin` | 沪金实时 |
| `/api/comex_gold` | COMEX 金实时 |
| `/api/btc` | BTC 实时 |
| `/api/status` | 服务器状态、缓存时间戳、数据源连接状态 |
| `/api/alerts` | 告警历史与统计 |
| `/api/sources` | 数据源可用性 |
| `/api/instruments` | 全品种列表（含价格与信号） |
| `/api/instruments/registry` | 品种注册表元数据 |
| `/api/instrument/{id}` | 单品种查询 |
| `/api/stream` | SSE 实时推送流 |
| `/api/research/huyin` | 蒙特卡洛研究上下文 |

### POST 接口

| 路由 | 说明 |
|------|------|
| `/api/threshold` | 设置跳动告警阈值 |
| `/api/backtest` | 动量策略回测 |
| `/api/backtest/grid-search` | 参数网格搜索 |
| `/api/backtest/walk-forward` | 滚动前推分析 |
| `/api/research/monte-carlo` | 蒙特卡洛模拟 |
| `/api/config/reload` | 热重载配置文件 |

---

## 六、连通性测试结果（2026-04-20）

### iFinD SDK

| 品种 | 代码 | 状态 | 备注 |
|------|------|------|------|
| USD/CNY | USDCNY.FX | ✅ 6.8174 | |
| USD/CNH | USDCNH.FX | ✅ 6.8163 | |
| EUR/USD | EURUSD.FX | ✅ 1.1764 | |
| GBP/USD | GBPUSD.FX | ✅ 1.3518 | |
| USD/JPY | USDJPY.FX | ✅ 158.62 | |
| AUD/USD | AUDUSD.FX | ✅ 0.7169 | |
| USD/CHF | USDCHF.FX | ✅ 0.7817 | |
| NZD/USD | NZDUSD.FX | ✅ 0.5882 | |
| USD/CAD | USDCAD.FX | ✅ 1.3692 | |
| USD/HKD | USDHKD.FX | ✅ 7.8320 | |
| XAU/USD | XAUUSD.FX | ✅ 4837.49 | |
| XAG/USD | XAGUSD.FX | ❌ 无数据 | 周末 COMEX 休市 |
| BTC | 多个代码 | ❌ 不支持 | iFinD 不覆盖加密货币 |

### Infoway WebSocket

| 连接 | 品种 | 状态 |
|------|------|------|
| common | XAGUSD, XAUUSD | ✅ 连接正常（周末无推送属正常） |
| crypto | BTCUSDT | ✅ 连接正常，24/7 推送 |

### Sina 财经

| 品种 | 状态 | 备注 |
|------|------|------|
| 国内期货 (nf_*) | ✅ | 交易时段正常 |
| 国际期货 (hf_*) | ✅ | COMEX 时段正常 |
| 外汇 (fx_*) | ✅ | |
