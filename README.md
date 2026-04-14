# 贵金属行情监控

一个面向白银与黄金的本地监控项目，包含：

- 网页监控面板
- Python 本地数据服务
- 微信小程序前端

项目当前支持以下核心能力：

- 沪银、COMEX 银、沪金、COMEX 金的实时与准实时展示
- 白银/黄金双 TAB 切换
- 价差、波动率、实时曲线、动量信号展示
- 3-tick 预警与阈值调整
- 网页端和小程序端共存

## 1. 项目目标

本项目的目标是提供一个本地运行、低依赖、可快速扩展的贵金属监控工具，重点服务以下场景：

- 跟踪白银和黄金的实时价格变化
- 对比内盘与外盘价格关系
- 快速观察波动率与短周期动量
- 触发并查看短时异动预警
- 以较低成本接入多个公开数据源

## 2. 技术栈

### 后端

- Python 3
- 标准库 HTTP Server
- `akshare`
- 多线程轮询

### 前端

- 原生 HTML / CSS / JavaScript
- [Chart.js](https://www.chartjs.org/)
- `luxon`
- `chartjs-adapter-luxon`

### 小程序

- 微信小程序原生框架

## 3. 目录结构

```text
silver-monitor/
├─ assets/
│  ├─ css/
│  │  └─ monitor.css
│  └─ js/
│     └─ monitor/
│        ├─ dom.js
│        ├─ renderers.js
│        ├─ alerts.js
│        ├─ app.js
│        ├─ charts.js
│        ├─ core.js
│        ├─ gold.js
│        ├─ momentum.js
│        ├─ silver.js
│        └─ strategy.js
├─ backend/
│  ├─ __init__.py
│  ├─ alerts.py
│  ├─ analytics.py
│  ├─ backtest.py
│  ├─ bootstrap.py
│  ├─ config.py
│  ├─ http_server.py
│  ├─ market_hours.py
│  ├─ models.py
│  ├─ pollers.py
│  ├─ sources.py
│  ├─ state.py
│  ├─ utils.py
│  └─ strategies/
│     ├─ __init__.py
│     └─ momentum.py
├─ docs/
│  ├─ data-models.md
│  ├─ momentum-strategy.md
│  └─ strategy-backtest.md
├─ tests/
├─ miniprogram/
├─ index.html
├─ strategy.html
├─ monitor.config.json
├─ server.py
└─ README.md
```

## 4. 模块说明

### 4.1 后端模块

#### `server.py`

项目启动入口，只负责：

- 打印启动信息
- 预热缓存
- 启动快慢轮询线程
- 启动 HTTP 服务

不承载具体业务逻辑。

#### `backend/config.py`

集中维护运行配置和全局常量：

- 端口
- 快慢轮询周期
- 汇率换算常量
- 时区
- 日志
- `akshare` 初始化
- 配置文件加载

配置默认从根目录 `monitor.config.json` 读取。

#### `backend/state.py`

维护全局共享状态，主要包括：

- 白银缓存
- COMEX 银缓存
- 黄金缓存
- COMEX 金缓存
- 聚合缓存
- 美元兑人民币汇率缓存
- tick 环形缓存
- 预警历史

这是后端各模块共享数据的唯一状态入口。

#### `backend/market_hours.py`

负责交易时段判断：

- 沪银/沪金交易时间
- COMEX 活跃交易时间
- 市场当前状态描述

#### `backend/sources.py`

负责所有数据源抓取，包含：

- 新浪沪银
- 新浪沪金
- 新浪 XAG
- 新浪 XAU
- 新浪 USD/CNY
- `akshare` 历史数据
- `akshare` 备用实时数据

#### `backend/alerts.py`

负责 3-tick 异动检测与预警记录：

- 价格环形缓存更新
- 百分比变化计算
- 告警等级判断
- 预警历史写入

#### `backend/analytics.py`

负责聚合分析逻辑：

- 白银价差
- 黄金价差
- 金银比
- 历史波动率 HV20
- 聚合缓存生成

#### `backend/pollers.py`

负责后台轮询线程：

- `FastDataPoller`: 快轮询，拉取实时价格与预警相关数据
- `SlowDataPoller`: 慢轮询，拉取历史数据与汇率

#### `backend/http_server.py`

负责 HTTP 服务与 API：

- 静态文件服务
- `/api/all`
- `/api/huyin`
- `/api/comex`
- `/api/hujin`
- `/api/comex_gold`
- `/api/alerts`
- `/api/status`
- `/api/sources`
- `/api/threshold`

#### `backend/models.py`

维护统一的数据模型定义与类型约定，便于：

- 统一接口字段语义
- 统一聚合对象结构
- 为文档与测试提供公共参照

#### `backend/bootstrap.py`

服务启动时的缓存预热逻辑：

- 首次拉取四类主要价格
- 将初始数据写入缓存
- 触发一次聚合缓存重建

### 4.2 前端模块

#### `index.html`

只保留：

- 页面 DOM 结构
- CDN 依赖引用
- 本地 CSS / JS 资源引用

#### `assets/css/monitor.css`

统一维护网页监控面板样式，包括：

- 页面布局
- 卡片样式
- 图表容器
- TAB 样式
- 预警区域
- 响应式布局

#### `assets/js/monitor/core.js`

维护前端共享基础能力：

- 全局命名空间 `Monitor`
- 全局常量
- 页面运行时状态
- DOM 查询工具
- API 基础地址推导
- 运行时配置加载

#### `assets/js/monitor/dom.js`

维护前端安全 DOM 操作助手：

- 安全设置文本
- 安全设置 HTML
- 安全设置 class
- 安全设置样式

#### `assets/js/monitor/renderers.js`

维护可复用 UI 渲染器：

- 市场卡片渲染
- 价差卡片渲染
- ATR 指标渲染
- tick 表格渲染

#### `assets/js/monitor/charts.js`

负责图表相关能力：

- 图表默认配置
- 白银图表初始化
- 黄金图表延迟初始化
- ATR 计算
- 可见图表 resize

#### `assets/js/monitor/silver.js`

负责白银监控页的数据渲染：

- 白银价格卡片
- 白银历史图表
- 白银实时图表
- 白银 tick 记录

#### `assets/js/monitor/gold.js`

负责黄金监控页的数据渲染：

- 黄金价格卡片
- 黄金历史图表
- 黄金实时图表
- 黄金 tick 记录

#### `assets/js/monitor/momentum.js`

负责短周期动量信号：

- EMA 计算
- 动量判断
- 信号渲染
- 声音提示

#### `assets/js/monitor/alerts.js`

负责预警展示与阈值交互：

- 预警拉取
- 预警横幅
- 阈值菜单
- 告警声音
- 预警列表和 tick ring 渲染

#### `assets/js/monitor/app.js`

负责前端主流程：

- 主数据轮询
- 预警轮询
- 手动刷新
- TAB 切换
- 首次初始化

## 5. 运行方式

### 5.1 环境准备

建议环境：

- Python 3.10+
- Windows PowerShell

安装依赖：

```bash
pip install akshare
```

如果没有安装 `akshare`，项目仍可启动，但历史数据与备用数据能力会受限。

### 5.2 启动服务

在项目根目录执行：

```bash
python server.py
```

启动后访问：

- 网页端: `http://127.0.0.1:8765/`

### 5.3 修改配置

项目根目录提供统一配置文件：

- `monitor.config.json`

配置项包括：

- 服务监听地址与端口
- 快慢轮询周期
- 预警阈值默认值
- 前端轮询周期与本地文件模式回退端口

示例：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8765
  },
  "polling": {
    "fast_seconds": 3,
    "slow_seconds": 60
  },
  "alerts": {
    "tick_jump_threshold": 1.0,
    "max_history": 200
  },
  "frontend": {
    "default_api_host": "127.0.0.1",
    "fallback_port": 8765,
    "poll_ms": 1000,
    "alert_poll_ms": 2000
  }
}
```

修改配置后重新启动服务即可生效。

### 5.4 小程序运行

小程序目录位于：

- `miniprogram/`

使用微信开发者工具打开该目录后运行。

如需联调本地后端，请确保小程序请求地址已配置为当前本地服务地址。

## 6. 主要接口

### `GET /api/all`

返回聚合后的完整监控数据：

- 白银
- 黄金
- 白银价差
- 黄金价差
- 金银比
- 波动率序列

### `GET /api/huyin`

返回沪银数据。

### `GET /api/comex`

返回 COMEX 银数据。

### `GET /api/hujin`

返回沪金数据。

### `GET /api/comex_gold`

返回 COMEX 金数据。

### `GET /api/alerts`

返回预警历史、阈值与 tick ring。

### `GET /api/status`

返回服务运行状态、缓存年龄、是否加载 `akshare` 等。

### `POST /api/threshold`

设置 3-tick 预警阈值。

请求示例：

```json
{
  "threshold": 1.5
}
```

## 7. 数据流

项目整体数据流如下：

1. `bootstrap.py` 在启动时预热缓存
2. `FastDataPoller` 周期拉取实时价格
3. `SlowDataPoller` 周期拉取历史数据和汇率
4. `analytics.py` 将缓存重建为统一聚合结果
5. `http_server.py` 对外暴露 API
6. 前端通过 `/api/all` 和 `/api/alerts` 轮询渲染页面

详细字段说明见：

- `docs/data-models.md`

## 8. 测试

当前项目已包含基础单元测试与 smoke test，位于：

- `tests/test_analytics.py`
- `tests/test_market_hours.py`
- `tests/test_smoke.py`

执行方式：

```bash
python -m unittest discover -s tests -p "test_*.py"
```

当前覆盖内容：

- 波动率计算
- 聚合缓存构建
- 交易时段判断
- 配置文件可读性
- HTTP 服务最小 smoke 校验

## 9. 命名规范

本项目当前采用以下命名规范。

### 8.1 Python

- 模块名: `snake_case`
- 函数名: `snake_case`
- 变量名: `snake_case`
- 类名: `PascalCase`
- 常量名: `UPPER_SNAKE_CASE`

示例：

- `FastDataPoller`
- `build_startup_banner()`
- `silver_cache`
- `FAST_POLL`

### 8.2 前端 JavaScript

- 普通变量和函数: `lowerCamelCase`
- 对象属性: `lowerCamelCase`
- 构造器或类风格对象: `PascalCase`
- 页面 DOM id: 保持现有结构，不强制整体重命名

示例：

- `Monitor.fetchData()`
- `Monitor.initializeGoldCharts()`
- `app.isGoldChartsInitialized`
- `Monitor.signalLabels`

### 8.3 对外兼容原则

以下内容优先保持兼容，不因内部重构随意变更：

- HTTP API 路径
- API 返回 JSON 字段
- 页面 DOM id
- 小程序页面路径和页面级数据结构

## 10. 开发约定

### 9.1 修改后端时

优先遵守以下边界：

- 数据源抓取写在 `sources.py`
- 聚合计算写在 `analytics.py`
- 预警逻辑写在 `alerts.py`
- 轮询控制写在 `pollers.py`
- API 处理写在 `http_server.py`

不要把业务重新塞回 `server.py`。

### 9.2 修改前端时

优先遵守以下边界：

- 样式只改 `monitor.css`
- 白银渲染逻辑改 `silver.js`
- 黄金渲染逻辑改 `gold.js`
- 图表初始化改 `charts.js`
- 预警逻辑改 `alerts.js`
- 主流程改 `app.js`

不要把大段内联脚本重新写回 `index.html`。

### 9.3 新增功能建议

如果新增一个独立功能，建议按以下方式拆分：

- 新增独立模块文件
- 在入口模块中只做注册与调用
- 复用 `Monitor` 命名空间或 `backend/` 模块边界

## 11. 常见排障

### 10.1 端口占用

如果启动时报端口占用：

```bash
netstat -ano | findstr :8765
```

### 10.2 `akshare` 未安装

日志出现类似提示：

```text
akshare not installed! Run: pip install akshare
```

执行：

```bash
pip install akshare
```

### 10.3 网页没有数据

优先检查：

- 后端是否正常启动
- 浏览器是否访问了 `http://127.0.0.1:8765/`
- 控制台和后端日志是否有请求失败

### 10.4 页面显示异常

优先检查：

- `index.html` 是否正确引用 `assets/css/monitor.css`
- `index.html` 是否正确引用 `assets/js/monitor/*.js`
- 浏览器是否缓存了旧静态资源，可尝试强制刷新

## 12. 后续可继续优化的方向

- 为后端补充基础单元测试与 smoke test
- 为前端补充更细粒度的 UI 模块拆分
- 抽离统一的数据模型与字段说明
- 增加配置文件而不是硬编码轮询周期和端口
- 为小程序补一份独立 README

## 13. 维护建议

如果后续继续演进项目，推荐坚持以下原则：

- 单一文件只负责一个功能域
- 对外接口优先稳定
- 先抽模块，再加功能
- 所有新增命名遵循当前规范

这样可以避免项目再次回到“单文件过大、修改牵一发而动全身”的状态。
