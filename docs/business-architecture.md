# 业务功能架构

> 更新日期：2026-04-20

## 一、项目定位

silver-monitor 是一个本地运行的行情监控与策略分析工具，当前覆盖三类核心业务：

- 实时行情监控：贵金属、BTC、全量商品品种的价格与状态展示
- 信号分析与研究：动量信号、历史波动、蒙特卡洛研究、策略回测
- 运维管理：缓存清理、数据源连通性测试、数据源优先级动态切换

系统同时提供三类前端入口：

- Web 监控页：主行情监控页面，面向日常盯盘
- Web 策略页：策略回测、参数搜索、研究分析
- Web 后台页：运行态管理与数据源控制

另有一个微信小程序端，用于轻量查看行情、告警和设置。

---

## 二、业务能力分层

### 2.1 展示层

#### 行情监控页

入口页面：`index.html`

主要功能：

- 沪银 / COMEX 银实时监控
- 沪金 / COMEX 金实时监控
- BTC 实时监控
- 全量商品列表与动量信号概览
- 实时曲线、历史曲线、波动率、ATR、最近 Tick
- SSE 驱动的实时刷新

前端脚本职责：

- `assets/js/monitor/app.js`：页面入口与初始化
- `assets/js/monitor/core.js`：全局状态、轮询与流控
- `assets/js/monitor/silver.js` / `gold.js` / `research.js` / `strategy.js`：各页面业务逻辑
- `assets/js/monitor/charts.js`：Chart.js 图表初始化与更新
- `assets/js/monitor/renderers.js`：行情卡片、表格、信号等渲染
- `assets/js/monitor/alerts.js`：告警展示
- `assets/js/monitor/momentum.js`：前端动量辅助逻辑
- `assets/js/monitor/dom.js`：DOM 节点缓存与工具函数

#### 策略管理页

入口页面：`strategy.html`

主要功能：

- 动量策略回测
- 网格搜索
- Walk-Forward 滚动前推分析
- 蒙特卡洛研究结果展示

#### 后台管理页

入口页面：`admin.html`

主要功能：

- 实时测试 Sina / iFinD / Infoway 的连通性
- 一键清空运行期缓存、Tick 环、告警历史、研究样本
- 数据源矩阵配置与运行态切换

这里的数据源切换为热生效：保存后直接修改服务内存态，不需要重启应用。

### 2.2 服务层

服务入口：`server.py`

启动顺序：

1. 启动 Infoway 贵金属 WebSocket
2. 启动 Infoway 加密货币 WebSocket
3. 执行 `prime_caches()` 预热核心缓存
4. 启动 `FastDataPoller`
5. 启动 `SlowDataPoller`
6. 启动 `CommodityPoller`
7. 对外提供 HTTP API 与静态页面服务

核心后端模块：

- `backend/http_server.py`：API 路由、静态资源、SSE、后台管理接口
- `backend/pollers.py`：快慢轮询与品种级更新分发
- `backend/bootstrap.py`：启动时缓存预热
- `backend/state.py`：全局共享运行态
- `backend/analytics.py`：聚合指标、组合缓存、衍生分析
- `backend/alerts.py`：3-tick 异动检测与告警历史
- `backend/backtest.py`：策略回测、网格搜索、Walk-Forward
- `backend/research/monte_carlo.py`：蒙特卡洛模拟
- `backend/strategies/momentum.py`：动量信号核心算法

### 2.3 数据接入层

当前支持三套数据源：

- Sina：HTTP 轮询，覆盖国内期货、国际期货、汇率、商品全量报价、历史 K 线
- iFinD：SDK / HTTP 双模式，主要用于 COMEX 银、COMEX 金实时数据
- Infoway WebSocket：实时推送，覆盖贵金属与 BTC

数据抓取模块：

- `backend/sources.py`：Sina 实时与历史接口
- `backend/ifind.py`：iFinD 登录、请求、失败回退
- `backend/infoway.py`：WebSocket 连接、订阅、缓存与过期检测

---

## 三、业务域划分

### 3.1 核心行情域

核心监控标的：

- 沪银 AG0
- COMEX 银 XAG
- 沪金 AU0
- COMEX 金 XAU
- BTCUSDT

业务职责：

- 实时价格更新
- 昨收 / 涨跌 / 涨跌幅计算
- 人民币换算
- Tick 级缓冲
- 动量信号更新
- 页面实时广播

### 3.2 商品全景域

由 `CommodityPoller` 每个快轮询周期更新全量商品品种。

当前覆盖 6 大板块：

- 贵金属
- 有色金属
- 黑色系
- 能源化工
- 农产品
- 国际

业务目标：

- 为首页商品总览提供统一接口
- 为品种级动量信号提供价格缓冲
- 统一注册表管理与扩展能力

### 3.3 分析研究域

核心能力：

- EMA 动量信号
- Bollinger Band 融合信号
- 价差与换算指标
- 历史波动率 HV20
- 策略回测
- 网格搜索与 Walk-Forward
- 蒙特卡洛路径模拟

该域主要用于策略管理页和研究接口，不直接依赖前端页面状态。

### 3.4 运维管理域

核心能力：

- 服务健康状态查看
- 缓存清理
- 数据源连通性测试
- 数据源优先级热切换

管理域的目标不是替代配置文件，而是提供运行时干预能力：

- 配置文件负责默认值
- Admin 页面负责当前进程内即时切换

---

## 四、关键运行链路

### 4.1 实时行情更新链路

```text
数据源 → Poller → AppState 缓存 → Analytics 聚合/信号 → SSE/API → Web 页面 / 小程序
```

说明：

- `FastDataPoller` 负责贵金属、BTC 与核心实时字段刷新
- `CommodityPoller` 负责全量商品池刷新
- `SlowDataPoller` 负责历史 K 线和 USD/CNY 汇率
- 更新完成后重建聚合缓存，并将快照推送给前端

### 4.2 核心品种数据源矩阵

当前运行态支持按品种配置数据源优先级。默认矩阵如下：

| 品种 | 默认优先级 1 | 默认优先级 2 | 默认优先级 3 |
|------|--------------|--------------|--------------|
| AG0 | Sina | — | — |
| XAG | iFinD | Infoway | Sina |
| AU0 | Sina | — | — |
| XAU | iFinD | Infoway | Sina |
| BTC | Infoway Crypto | — | — |

实现位置：

- 运行态存储：`backend/state.py` → `state.source_priority`
- 动态分发：`backend/pollers.py` → `_SOURCE_DISPATCH` / `_fetch_by_priority()`
- Admin API：`/api/admin/source-config`

### 4.3 后台热切换链路

```text
Admin 页面操作 → POST /api/admin/source-config → 更新 state.source_priority → 下一轮 FastDataPoller 生效
```

特点：

- 不依赖进程重启
- 不写回 `monitor.config.json`
- 只影响当前运行实例

如果服务重启，会回到代码默认矩阵，除非后续将该能力持久化到配置文件。

### 4.4 策略分析链路

```text
历史数据加载 → 动量参数解析 → 回测/研究计算 → 指标输出 → Strategy 页展示
```

主要 API：

- `POST /api/backtest`
- `POST /api/backtest/grid-search`
- `POST /api/backtest/walk-forward`
- `POST /api/research/monte-carlo`

---

## 五、运行态状态模型

全局状态集中在 `AppState`：

### 5.1 核心缓存

- `silver_cache`
- `comex_silver_cache`
- `gold_cache`
- `comex_gold_cache`
- `btc_cache`
- `combined_cache`
- `usd_cny_cache`

### 5.2 告警与研究态

- `silver_tick_ring`
- `comex_silver_tick_ring`
- `gold_tick_ring`
- `comex_gold_tick_ring`
- `btc_tick_ring`
- `alert_history`
- `alert_stats`
- `huyin_research_samples`

### 5.3 全量品种与信号态

- `instrument_caches`
- `instrument_price_buffers`
- `instrument_signals`

### 5.4 服务广播与版本态

- `sse_queues`
- `data_version`

### 5.5 运行期控制态

- `tick_jump_threshold`
- `source_priority`

---

## 六、API 能力分组

### 6.1 行情查询

- `GET /api/all`
- `GET /api/huyin`
- `GET /api/comex`
- `GET /api/hujin`
- `GET /api/comex_gold`
- `GET /api/btc`
- `GET /api/instruments`
- `GET /api/instrument/{id}`
- `GET /api/instruments/registry`

### 6.2 状态与告警

- `GET /api/status`
- `GET /api/alerts`
- `GET /api/sources`
- `GET /api/stream`

### 6.3 策略与研究

- `POST /api/backtest`
- `POST /api/backtest/grid-search`
- `POST /api/backtest/walk-forward`
- `POST /api/research/monte-carlo`
- `GET /api/research/huyin`

### 6.4 运维管理

- `POST /api/threshold`
- `POST /api/config/reload`
- `POST /api/admin/clear-cache`
- `POST /api/admin/test-sources`
- `GET /api/admin/source-config`
- `POST /api/admin/source-config`

---

## 七、扩展原则

后续新增品种或业务时，建议遵循以下边界：

1. 新增数据源接入，优先落在 `sources.py` / `ifind.py` / `infoway.py` 这类接入层模块，不把抓取逻辑写进 API 层。
2. 新增核心品种时，先补注册表和缓存结构，再补 Poller、Analytics、前端面板与 API。
3. 新增策略能力时，先在 `backend/strategies` 或 `backend/research` 内闭环，再决定是否开放到页面。
4. 运行态开关与后台控制，应优先通过 `AppState` 和 Admin API 实现，避免直接在前端拼业务逻辑。

---

## 八、与现有文档的关系

- `docs/data-integration.md`：说明数据源覆盖、接口与优先级
- `docs/data-models.md`：说明字段模型与响应结构
- `docs/momentum-strategy.md`：说明动量策略逻辑
- `docs/strategy-backtest.md`：说明回测设计与接口
- `docs/research-monte-carlo.md`：说明蒙特卡洛研究能力

本文关注的是“系统做什么、模块怎么协作、业务链路如何流转”，用于产品、开发和联调时快速建立整体认知。