# 商品行情监控（silver-monitor）

一个本地运行的行情监控与策略分析项目，当前覆盖：

- 贵金属：沪银、COMEX 银、沪金、COMEX 金
- 加密货币：BTCUSDT
- 商品全景：6 大板块、62 个商品品种
- 分析能力：动量信号、波动率、回测、Walk-Forward、蒙特卡洛研究
- 运维能力：缓存清理、数据源连通性测试、数据源矩阵热切换
- 客户端形态：Web 行情页、策略页、研究页、后台页、微信小程序

## 1. 项目概览

项目目标是提供一个低依赖、可本地部署、可扩展的数据监控工作台，适合以下场景：

- 跟踪核心品种的实时价格变化
- 对比内外盘价格关系与换算结果
- 观察短周期动量信号和历史波动
- 进行回测、参数搜索和研究分析
- 在不停机的情况下调整运行态参数与数据源优先级

## 2. 技术栈

### 后端

- Python 3
- 标准库 HTTP Server
- 多线程轮询 + 共享内存态缓存
- SSE 实时推送
- 数据源接入：Sina、iFinD、Infoway WebSocket
- 可选依赖：`requests`、`websockets`、`iFinDAPI`

### 前端

- 原生 HTML / CSS / JavaScript
- [Chart.js](https://www.chartjs.org/)
- `luxon`
- `chartjs-adapter-luxon`

### 测试

- `pytest`
- `unittest.mock`
- 真实数据源联调脚本

### 小程序

- 微信小程序原生框架

## 3. 目录结构

```text
silver-monitor/
├─ admin.html
├─ index.html
├─ research.html
├─ strategy.html
├─ assets/
│  ├─ css/
│  │  └─ monitor.css
│  └─ js/
│     └─ monitor/
│        ├─ alerts.js
│        ├─ app.js
│        ├─ charts.js
│        ├─ core.js
│        ├─ crypto.js
│        ├─ dashboard.js
│        ├─ detail.js
│        ├─ dom.js
│        ├─ gold.js
│        ├─ momentum.js
│        ├─ renderers.js
│        ├─ research.js
│        ├─ silver.js
│        └─ strategy.js
├─ backend/
│  ├─ alerts.py
│  ├─ analytics.py
│  ├─ backtest.py
│  ├─ bootstrap.py
│  ├─ config.py
│  ├─ http_server.py
│  ├─ ifind.py
│  ├─ infoway.py
│  ├─ instruments.py
│  ├─ market_hours.py
│  ├─ models.py
│  ├─ pollers.py
│  ├─ sources.py
│  ├─ state.py
│  ├─ utils.py
│  ├─ research/
│  │  ├─ monte_carlo.py
│  │  └─ samples.py
│  └─ strategies/
│     └─ momentum.py
├─ docs/
│  ├─ business-architecture.md
│  ├─ data-integration.md
│  ├─ data-models.md
│  ├─ momentum-strategy.md
│  ├─ research-monte-carlo.md
│  ├─ strategy-backtest.md
│  └─ testing-guide.md
├─ miniprogram/
├─ tests/
│  ├─ test_*.py
│  ├─ verify_ifind.py
│  ├─ verify_ifind_btc.py
│  └─ verify_infoway_btc.py
├─ monitor.config.json
├─ server.py
└─ README.md
```

说明：

- `assets/js/monitor/` 负责 Web 端页面逻辑、图表和渲染
- `backend/` 负责数据接入、轮询、缓存、策略、API 和研究
- `docs/` 负责架构、数据、策略和测试文档
- `tests/` 同时包含自动化测试和真实数据源联调脚本

## 4. 主要模块

### 4.1 后端

#### `server.py`

服务启动入口，负责：

- 打印启动信息
- 启动 Infoway WebSocket
- 预热缓存
- 启动 `FastDataPoller`、`SlowDataPoller`、`CommodityPoller`
- 启动 HTTP 服务

#### `backend/config.py`

负责运行配置与全局常量：

- 服务监听地址与端口
- 快慢轮询周期
- 动量参数与研究参数
- iFinD / Infoway 配置读取
- 日志初始化

#### `backend/state.py`

负责全局共享状态：

- 贵金属与 BTC 缓存
- 全量商品缓存
- Tick 环形缓冲
- 告警历史与统计
- 预计算动量信号
- SSE 队列
- 数据源优先级矩阵 `source_priority`

#### `backend/pollers.py`

负责后台轮询与运行态更新：

- `FastDataPoller`：核心品种实时刷新
- `SlowDataPoller`：历史 K 线与 USD/CNY 汇率
- `CommodityPoller`：全量商品刷新
- 动态数据源优先级分发与回退

#### `backend/http_server.py`

负责：

- 静态资源服务
- 行情 API 与策略 API
- SSE 实时推送
- 后台管理接口

#### `backend/sources.py` / `backend/ifind.py` / `backend/infoway.py`

负责三类数据源接入：

- Sina HTTP 实时与历史接口
- iFinD SDK / HTTP 双模式接入
- Infoway WebSocket 贵金属与 BTC 推送

#### `backend/analytics.py` / `backend/alerts.py`

负责：

- 价差、换算、波动率、聚合快照
- 3-tick 异动检测、告警历史、统计输出

#### `backend/backtest.py` / `backend/strategies/momentum.py` / `backend/research/`

负责：

- 动量策略计算
- 回测、网格搜索、Walk-Forward
- 蒙特卡洛研究与样本管理

### 4.2 前端

#### 页面入口

- `index.html`：主行情监控页
- `strategy.html`：策略管理页
- `research.html`：研究分析页
- `admin.html`：后台管理页

#### 主要脚本

- `core.js`：运行时状态、API 地址、全局常量
- `charts.js`：图表初始化与更新
- `renderers.js`：卡片、表格、ATR、信号等渲染
- `silver.js` / `gold.js` / `crypto.js`：各监控页逻辑
- `strategy.js` / `research.js`：策略与研究页面逻辑
- `alerts.js`：预警展示与阈值交互
- `app.js`：页面初始化、数据刷新、SSE 联动

## 5. 文档索引

- `docs/business-architecture.md`：业务功能架构、模块协作、运行链路
- `docs/data-integration.md`：数据源覆盖、优先级、接口和接入现状
- `docs/data-models.md`：核心响应结构与字段模型
- `docs/momentum-strategy.md`：动量策略逻辑与参数说明
- `docs/strategy-backtest.md`：回测能力、接口与输出说明
- `docs/research-monte-carlo.md`：蒙特卡洛研究与接口说明
- `docs/testing-guide.md`：自动化测试、联调脚本、人工验收清单

## 6. 运行方式

### 6.1 环境准备

建议环境：

- Python 3.10+
- Windows PowerShell

常见依赖安装：

```bash
pip install pytest requests websockets
```

如需启用 iFinD SDK：

```bash
pip install iFinDAPI
```

### 6.2 启动服务

在项目根目录执行：

```bash
python server.py
```

启动后可访问：

- 行情监控：`http://127.0.0.1:8765/`
- 策略管理：`http://127.0.0.1:8765/strategy.html`
- 研究分析：`http://127.0.0.1:8765/research.html`
- 后台管理：`http://127.0.0.1:8765/admin.html`

### 6.3 配置说明

统一配置文件：`monitor.config.json`

当前主要配置包括：

- `server`：监听地址与端口
- `polling`：快慢轮询周期
- `alerts`：Tick 告警阈值与最大历史数
- `frontend`：前端默认 API 地址与刷新周期
- `momentum`：各品种动量参数
- `research`：蒙特卡洛研究参数
- `ifind`：iFinD 账号与合约代码
- `infoway_ws`：贵金属 WebSocket
- `infoway_ws_crypto`：加密货币 WebSocket

说明：

- 修改 `monitor.config.json` 后，需要重启服务或调用 `POST /api/config/reload`
- 后台页中的“数据源优先级配置”只对当前进程热生效，不会自动写回配置文件

### 6.4 小程序运行

小程序目录位于 `miniprogram/`，使用微信开发者工具打开该目录即可运行。

## 7. 核心接口

### 7.1 行情接口

- `GET /api/all`：核心品种聚合快照与信号
- `GET /api/huyin`：沪银实时数据
- `GET /api/comex`：COMEX 银实时数据
- `GET /api/hujin`：沪金实时数据
- `GET /api/comex_gold`：COMEX 金实时数据
- `GET /api/btc`：BTC 实时数据
- `GET /api/instruments`：全量商品列表
- `GET /api/instrument/{id}`：单品种数据
- `GET /api/instruments/registry`：品种注册表

### 7.2 状态与告警

- `GET /api/status`：服务状态与缓存年龄
- `GET /api/alerts`：告警历史、阈值、Tick 环
- `GET /api/sources`：数据源可用性概览
- `GET /api/stream`：SSE 实时推送流

### 7.3 策略与研究

- `POST /api/backtest`
- `POST /api/backtest/grid-search`
- `POST /api/backtest/walk-forward`
- `POST /api/research/monte-carlo`
- `GET /api/research/huyin`

### 7.4 后台管理

- `POST /api/threshold`
- `POST /api/config/reload`
- `POST /api/admin/clear-cache`
- `POST /api/admin/test-sources`
- `GET /api/admin/source-config`
- `POST /api/admin/source-config`

## 8. 数据流

项目整体数据流如下：

1. `server.py` 启动 WebSocket 与轮询线程
2. `bootstrap.py` 预热核心缓存
3. `pollers.py` 按数据源矩阵拉取实时与历史数据
4. `state.py` 维护共享缓存、信号和运行态
5. `analytics.py` 重建聚合结果，`alerts.py` 更新告警
6. `http_server.py` 通过 API 与 SSE 向前端提供数据
7. 页面脚本消费 `/api/*` 与 `/api/stream` 完成渲染

更详细的业务链路见 `docs/business-architecture.md`，字段说明见 `docs/data-models.md`。

## 9. 测试

自动化测试与联调脚本位于 `tests/`。

执行全量自动化测试：

```bash
python -m pytest tests/ -q
```

在首个失败处停止：

```bash
python -m pytest tests/ -x -q --tb=short
```

常用联调脚本：

```bash
python tests/verify_ifind.py
python tests/verify_ifind_btc.py
python tests/verify_infoway_btc.py
```

详细测试流程、人工验收清单和已知问题见 `docs/testing-guide.md`。

## 10. 开发约定

### 10.1 后端修改边界

- 数据源接入优先放在 `sources.py`、`ifind.py`、`infoway.py`
- 聚合计算放在 `analytics.py`
- 告警逻辑放在 `alerts.py`
- 轮询与运行态调度放在 `pollers.py`
- API 处理放在 `http_server.py`

不要把具体业务重新塞回 `server.py`。

### 10.2 前端修改边界

- 样式统一放在 `assets/css/monitor.css`
- 页面级业务写在对应页面脚本中
- 通用渲染放在 `renderers.js`
- 图表逻辑放在 `charts.js`
- 公共运行态和 API 地址推导放在 `core.js`

### 10.3 对外兼容原则

以下内容优先保持稳定：

- HTTP API 路径
- API 返回 JSON 字段
- 页面 DOM id 和基础结构
- 小程序页面路径与页面数据结构

## 11. 常见排障

### 11.1 端口占用

```bash
netstat -ano | findstr :8765
```

### 11.2 iFinD 无法登录

优先检查：

- `monitor.config.json` 中的 `ifind.account` / `ifind.password`
- `iFinDAPI` SDK 是否已安装
- 是否存在有效 `refresh_token`

可用脚本：

```bash
python tests/verify_ifind.py
```

### 11.3 BTC 无实时数据

优先检查：

- `infoway_ws_crypto.enabled` 是否为 `true`
- API Key 是否有效
- WebSocket 连接是否建立

可用脚本：

```bash
python tests/verify_infoway_btc.py
```

### 11.4 后台切换数据源后似乎未生效

优先检查接口返回中的 `source` 字段是否变化。

说明：

- 切换结果从下一轮轮询开始生效
- 该功能只影响当前运行进程，不自动持久化

## 12. 维护建议

- 先抽象模块边界，再叠加功能
- 新增业务优先补文档和测试
- 外部接口优先兼容
- 运行态开关优先通过 API 和状态层实现

如果需要更完整的业务、数据和测试说明，请直接从第 5 节文档索引进入对应文档。
