# AGENTS.md — silver-monitor

> 本文件面向 AI 编程助手。阅读者被假设对该项目一无所知。
> 项目所有注释、文档和日志均以中文为主，因此本文件使用中文撰写。

---

## 1. 项目概述

**silver-monitor**（商品行情监控）是一个本地运行的低依赖行情监控与策略分析工作台。

当前覆盖：
- 贵金属：沪银（AG0）、COMEX 银（XAG）、沪金（AU0）、COMEX 金（XAU）
- 加密货币：BTCUSDT
- 商品全景：6 大板块、62 个商品品种
- 分析能力：动量信号、波动率、回测、Walk-Forward、蒙特卡洛研究
- 运维能力：缓存清理、数据源连通性测试、数据源矩阵热切换
- 客户端形态：Web 行情页、策略页、研究页、后台页、微信小程序

项目目标是提供一个可本地部署、可扩展的数据监控工作台，适合盯盘、对比内外盘价格、观察短周期动量信号和进行量化研究。

---

## 2. 技术栈与运行环境

### 2.1 后端

- **Python 3.10+**（开发环境以 Windows PowerShell 为主）
- **标准库 HTTP Server**（`http.server` + `socketserver.ThreadingMixIn`）
- **多线程轮询** + 共享内存态缓存（无 Redis/数据库）
- **SSE**（Server-Sent Events）实时推送到前端
- **数据源接入**：Sina HTTP、iFinD SDK/HTTP、Infoway WebSocket
- **可选依赖**：`requests`、`websockets`、`iFinDAPI`
- **测试框架**：`pytest`、`unittest.mock`

> 注意：项目**没有** `pyproject.toml`、`setup.py`、`requirements.txt` 或 `package.json`。依赖通过 `pip install pytest requests websockets` 手动安装。

### 2.2 前端

- 原生 HTML / CSS / JavaScript（无构建工具、无框架）
- [Chart.js](https://www.chartjs.org/) 图表
- `luxon` + `chartjs-adapter-luxon` 时间轴适配

### 2.3 小程序

- 微信小程序原生框架（`pages/index`、`pages/alerts`、`pages/settings`）

---

## 3. 目录结构与模块划分

```text
silver-monitor/
├─ server.py                    # 服务启动入口
├─ monitor.config.json          # 统一运行时配置文件
├─ index.html                   # 主行情监控页
├─ strategy.html                # 策略管理页
├─ research.html                # 研究分析页
├─ admin.html                   # 后台管理页
├─ assets/
│  ├─ css/monitor.css           # 全局样式
│  └─ js/monitor/               # 前端页面脚本
│     ├─ core.js                # 全局状态、API 地址、常量
│     ├─ app.js                 # 页面初始化、轮询、SSE 联动
│     ├─ charts.js              # Chart.js 初始化与更新
│     ├─ renderers.js           # 卡片、表格、信号渲染
│     ├─ silver.js / gold.js / crypto.js   # 各品种监控逻辑
│     ├─ strategy.js / research.js         # 策略与研究页面逻辑
│     ├─ alerts.js              # 预警展示与阈值交互
│     ├─ momentum.js / reversal.js         # 前端动量/反转辅助
│     ├─ backtest.js / indicators.js       # 回测与指标前端逻辑
│     ├─ dom.js / drag.js / dashboard.js / detail.js
├─ backend/                     # Python 后端包
│  ├─ __init__.py
│  ├─ config.py                 # 运行配置、全局常量、日志初始化
│  ├─ state.py                  # 全局共享状态（缓存、告警、信号、SSE 队列）
│  ├─ pollers.py                # 后台轮询线程（快/慢/商品轮询）
│  ├─ http_server.py            # HTTP 请求处理、API 路由、SSE、静态资源
│  ├─ sources.py                # Sina 数据源接入
│  ├─ ifind.py                  # iFinD SDK/HTTP 接入
│  ├─ infoway.py                # Infoway WebSocket 接入
│  ├─ instruments.py            # 商品品种注册表与数据获取
│  ├─ analytics.py              # 价差、换算、波动率、聚合快照
│  ├─ alerts.py                 # Tick 异动检测、告警历史、统计
│  ├─ market_hours.py           # 交易时段判断
│  ├─ models.py                 # 数据模型/结构定义
│  ├─ utils.py                  # 通用工具函数
│  ├─ bootstrap.py              # 缓存预热
│  ├─ backtest.py               # 回测、网格搜索、Walk-Forward
│  ├─ strategies/
│  │  └─ momentum.py            # 动量策略计算
│  └─ research/
│     ├─ monte_carlo.py         # 蒙特卡洛研究
│     └─ samples.py             # 研究样本管理
├─ miniprogram/                 # 微信小程序
│  ├─ app.js / app.json / app.wxss
│  └─ pages/index|alerts|settings/   # 行情、预警、设置三页
├─ tests/                       # 自动化测试 + 数据源联调脚本
│  ├─ test_*.py                 # pytest 测试用例
│  ├─ verify_ifind.py           # iFinD 联通性验证
│  ├─ verify_ifind_btc.py       # iFinD BTC 覆盖验证
│  ├─ verify_infoway_btc.py     # Infoway BTC WebSocket 验证
│  └─ _run_comex_backtest.py / _run_full_backtest.py
├─ docs/                        # 架构与业务文档
│  ├─ business-architecture.md
│  ├─ data-integration.md
│  ├─ data-models.md
│  ├─ momentum-strategy.md
│  ├─ strategy-backtest.md
│  ├─ research-monte-carlo.md
│  └─ testing-guide.md
└─ logs/                        # 运行时日志（server.log 等）
```

---

## 4. 启动与运行

### 4.1 启动服务

```powershell
python server.py
```

启动流程：
1. 启动 Infoway 贵金属 WebSocket (`infoway_start`)
2. 启动 Infoway 加密货币 WebSocket (`infoway_crypto_start`)
3. 预热缓存 (`prime_caches`)
4. 启动 `FastDataPoller`（默认 1 秒周期）
5. 启动 `SlowDataPoller`（默认 60 秒周期）
6. 启动 `CommodityPoller`（同快周期）
7. 启动 HTTP 服务（默认 `0.0.0.0:8765`）

访问地址：
- 行情监控：`http://127.0.0.1:8765/`
- 策略管理：`http://127.0.0.1:8765/strategy.html`
- 研究分析：`http://127.0.0.1:8765/research.html`
- 后台管理：`http://127.0.0.1:8765/admin.html`

### 4.2 配置说明

统一配置文件：`monitor.config.json`

主要配置段：
- `server`：监听地址与端口
- `polling`：快慢轮询周期（秒）
- `alerts`：Tick 告警阈值与最大历史数
- `frontend`：前端默认 API 地址、刷新周期、Bar 窗口时长
- `momentum`：各品种动量参数（短周期、长周期、布林带、RSI 等）
- `reversal`：反转策略参数
- `research`：蒙特卡洛研究参数
- `ifind`：iFinD 账号与合约代码
- `infoway_ws` / `infoway_ws_crypto`：Infoway WebSocket 配置

> 修改 `monitor.config.json` 后，可调用 `POST /api/config/reload` 热重载，或重启服务。
> 后台页中的“数据源优先级配置”只对当前进程热生效，不会自动写回配置文件。

---

## 5. 测试策略

### 5.1 运行全部自动化测试

```powershell
python -m pytest tests/ -q
```

在首个失败处停止：
```powershell
python -m pytest tests/ -x -q --tb=short
```

### 5.2 测试分层

| 层级 | 目标 | 典型文件 |
|------|------|----------|
| 单元测试 | 纯函数、算法、局部业务逻辑 | `test_momentum_strategy.py`、`test_market_hours.py`、`test_analytics.py`、`test_alerts_tick_jump.py`、`test_monte_carlo.py`、`test_backtest.py` |
| API 测试 | HTTP 接口行为、输入校验、响应结构 | `test_smoke.py`、`test_backtest_api.py`、`test_threshold_api.py`、`test_source_switch.py` |
| 联通性测试 | 真实外部数据源可连接性 | `verify_ifind.py`、`verify_ifind_btc.py`、`verify_infoway_btc.py` |

### 5.3 已知失败（基线问题，非新回归）

- `tests/test_momentum_strategy.py::MomentumCoreTestCase::test_custom_thresholds_weaker_entry` 当前失败
- `tests/test_source_switch.py` 全部用例当前失败（数据源切换 API 尚未实现）

在全量回归时，应将以上失败视为已知基线问题，而非新引入的回归。

### 5.4 开发自测最小集

```powershell
python -m pytest tests/test_smoke.py -q
python -m pytest tests/test_threshold_api.py -q
python server.py
```

---

## 6. 开发约定与代码边界

### 6.1 后端修改边界

- 数据源接入优先放在 `sources.py`、`ifind.py`、`infoway.py`
- 聚合计算放在 `analytics.py`
- 告警逻辑放在 `alerts.py`
- 轮询与运行态调度放在 `pollers.py`
- API 处理放在 `http_server.py`
- **不要把具体业务重新塞回 `server.py`**，`server.py` 仅作为启动入口

### 6.2 前端修改边界

- 样式统一放在 `assets/css/monitor.css`
- 页面级业务写在对应页面脚本中（如 `silver.js`、`strategy.js`）
- 通用渲染放在 `renderers.js`
- 图表逻辑放在 `charts.js`
- 公共运行态和 API 地址推导放在 `core.js`

### 6.3 对外兼容原则（优先保持稳定）

- HTTP API 路径
- API 返回 JSON 字段
- 页面 DOM id 和基础结构
- 小程序页面路径与页面数据结构

### 6.4 代码风格

- Python 使用 4 空格缩进
- 函数与模块注释使用中文文档字符串
- 日志使用 `backend.config.log`（标准库 `logging` 实例）
- 时间戳统一使用毫秒级 Unix 时间戳（`time.time() * 1000`）或带时区的 `datetime`
- 缓存结构统一为 `{"data": ..., "ts": 毫秒时间戳}`

---

## 7. 核心数据流

1. `server.py` 启动 WebSocket 与轮询线程
2. `bootstrap.py` 预热核心缓存
3. `pollers.py` 按数据源矩阵拉取实时与历史数据
4. `state.py` 维护共享缓存、信号和运行态
5. `analytics.py` 重建聚合结果，`alerts.py` 更新告警
6. `http_server.py` 通过 API 与 SSE 向前端提供数据
7. 页面脚本消费 `/api/*` 与 `/api/stream` 完成渲染

---

## 8. 主要 API 概览

### 行情接口
- `GET /api/all` — 核心品种聚合快照与信号
- `GET /api/huyin` / `/api/comex` / `/api/hujin` / `/api/comex_gold` / `/api/btc`
- `GET /api/instruments` — 全量商品列表
- `GET /api/instrument/{id}` — 单品种数据
- `GET /api/instruments/registry` — 品种注册表

### 状态与告警
- `GET /api/status` — 服务状态与缓存年龄
- `GET /api/alerts` — 告警历史、阈值、Tick 环
- `GET /api/sources` — 数据源可用性概览
- `GET /api/stream` — SSE 实时推送流

### 策略与研究
- `POST /api/backtest`
- `POST /api/backtest/grid-search`
- `POST /api/backtest/walk-forward`
- `POST /api/research/monte-carlo`
- `GET /api/research/huyin`

### 后台管理
- `POST /api/threshold`
- `POST /api/config/reload`
- `POST /api/admin/clear-cache`
- `POST /api/admin/test-sources`
- `GET /api/admin/source-config`
- `POST /api/admin/source-config`

---

## 9. 安全与敏感信息

- `monitor.config.json` 中保存有 `ifind.account`、`ifind.password`、`infoway_ws.api_key` 等敏感凭证。
- **不要在日志、测试输出、文档或提交信息中扩散账号、密码、API Key。**
- `.gitignore` 已排除 `*.log`、虚拟环境目录和 IDE 配置文件。
- 项目使用标准库 HTTP Server，**没有 HTTPS/TLS 支持**，仅在本地或可信内网运行。

---

## 10. 故障排查速查

### 端口占用
```powershell
netstat -ano | findstr :8765
```

### iFinD 无法登录
- 检查 `monitor.config.json` 中的 `ifind.account` / `ifind.password`
- 检查 `iFinDAPI` SDK 是否已安装
- 运行 `python tests/verify_ifind.py`

### BTC 无实时数据
- 检查 `infoway_ws_crypto.enabled` 是否为 `true`
- 检查 API Key 是否有效
- 运行 `python tests/verify_infoway_btc.py`

### 后台切换数据源后未生效
- 检查接口返回中的 `source` 字段是否变化
- 切换结果从下一轮轮询开始生效
- 该功能只影响当前运行进程，不自动持久化

---

## 11. 维护建议

- 先抽象模块边界，再叠加功能
- 新增业务优先补文档和测试
- 外部接口优先兼容
- 运行态开关优先通过 API 和状态层实现，避免频繁修改配置文件
