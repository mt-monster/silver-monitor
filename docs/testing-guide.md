# 测试指导

> 更新日期：2026-04-21

## 一、文档目标

本文用于指导 silver-monitor 的日常测试、联调和回归验证，覆盖：

- 本地启动前检查
- 自动化测试执行方式
- 数据源联通性验证脚本
- 前端人工验收清单
- 常见问题与已知限制

适用对象：开发人员、联调人员、功能验收人员。

---

## 二、测试前准备

### 2.1 基础环境

- Windows 本地环境
- Python 3
- 已创建虚拟环境 `.venv`
- 已安装项目依赖

建议先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2.2 配置检查

重点检查根目录 `monitor.config.json`：

- `server.host` / `server.port`
- `polling.fast_seconds` / `polling.slow_seconds`
- `ifind.enabled`
- `ifind.account` / `ifind.password` 或 `refresh_token`
- `infoway_ws.enabled` / `api_key`
- `infoway_ws_crypto.enabled` / `api_key`

注意：

- 文档或日志中不要扩散账号、密码、API Key
- 如果只跑单元测试，通常不要求所有外部数据源可用
- 如果跑联通性测试脚本，必须保证网络和认证信息可用

### 2.3 端口检查

默认端口为 `8765`。

如果启动时端口占用，可执行：

```powershell
netstat -ano | findstr :8765
```

---

## 三、测试分层说明

### 3.1 单元测试

目标：验证纯函数、算法和局部业务逻辑。

典型覆盖：

- 动量策略计算
- 布林带融合逻辑
- 交易时段判断
- 聚合分析逻辑
- 告警阈值与 Tick 处理

对应文件：

- `tests/test_momentum_strategy.py`
- `tests/test_market_hours.py`
- `tests/test_analytics.py`
- `tests/test_alerts_tick_jump.py`
- `tests/test_monte_carlo.py`
- `tests/test_backtest.py`

### 3.2 API 测试

目标：验证 HTTP 接口行为、输入校验和响应结构。

这类测试通常会在测试进程内临时起一个本地 HTTP Server，不依赖手工先启动 `server.py`。

对应文件：

- `tests/test_smoke.py`
- `tests/test_backtest_api.py`
- `tests/test_threshold_api.py`
- `tests/test_source_switch.py`（数据源切换 API）

### 3.3 数据源联调测试

目标：验证真实外部数据源是否可登录、可连接、可返回实时数据。

对应脚本：

- `tests/verify_ifind.py`
- `tests/verify_ifind_btc.py`
- `tests/verify_infoway_btc.py`

这类脚本不是稳定单元测试，而是联调工具。

### 3.4 人工功能验收

目标：验证页面交互、实时刷新、后台管理热切换等端到端行为。

主要页面：

- `index.html`
- `strategy.html`
- `admin.html`
- 微信小程序页面

---

## 四、常用测试命令

### 4.1 执行全部自动化测试

```powershell
python -m pytest tests/ -q
```

需要在首个失败处停止时：

```powershell
python -m pytest tests/ -x -q --tb=short
```

### 4.2 执行单个测试文件

```powershell
python -m pytest tests/test_smoke.py -q
python -m pytest tests/test_backtest_api.py -q
python -m pytest tests/test_threshold_api.py -q
python -m pytest tests/test_momentum_strategy.py -q
```

### 4.3 执行单个测试用例

```powershell
python -m pytest tests/test_momentum_strategy.py -k weaker_entry -q
python -m pytest tests/test_threshold_api.py -k invalid_step -q
```

### 4.4 运行服务做人工联调

```powershell
python server.py
```

浏览器访问：

- `http://127.0.0.1:8765/`
- `http://127.0.0.1:8765/strategy.html`
- `http://127.0.0.1:8765/admin.html`

---

## 五、数据源联通性验证

### 5.1 验证 iFinD 登录与贵金属行情

```powershell
python tests/verify_ifind.py
```

脚本内容：

- 检查 `iFinDPy` SDK 是否安装
- 检查 `requests` 库是否可用
- 验证 iFinD 登录
- 拉取 `XAGUSD.FX` 与 `XAUUSD.FX` 实时行情

适用场景：

- 刚配置 iFinD 账号后
- 怀疑 iFinD 登录态失效时
- 切换 iFinD 接入模式后

### 5.2 验证 iFinD 是否支持 BTC

```powershell
python tests/verify_ifind_btc.py
```

用途：

- 批量测试多个可能的 BTC 合约代码
- 验证 iFinD 是否覆盖加密货币行情

当前结论：

- 项目已验证 iFinD 不提供当前所需的 BTC 行情
- BTC 仍然依赖 Infoway crypto WebSocket

### 5.3 验证 Infoway BTC WebSocket

```powershell
python tests/verify_infoway_btc.py
```

脚本用途：

- 建立真实 WebSocket 连接
- 订阅 `BTCUSDT`
- 打印前 N 条 trade 推送

适用场景：

- 新 API Key 验证
- 排查 BTC 页面无行情
- 排查订阅协议字段变化

---

## 六、人工验收清单

### 6.1 首页行情页

验收目标：核心行情与商品总览显示正常。

检查项：

1. 首页可以正常打开，无白屏、无明显 JS 报错。
2. 沪银、COMEX 银、沪金、COMEX 金、BTC 卡片均能渲染。
3. 涨跌、涨跌幅、来源、时间戳字段存在。
4. 图表可以正常初始化，不出现空 canvas 或尺寸异常。
5. SSE 连接后，价格和时间戳可随数据刷新。
6. 商品列表可以正常展示价格和动量信号。

### 6.2 策略管理页

验收目标：研究与回测接口可用。

检查项：

1. 可以发起回测并返回结果。
2. 网格搜索和 Walk-Forward 有有效响应。
3. 蒙特卡洛请求返回路径、分布和摘要信息。
4. 页面异常输入时能收到错误提示，而不是静默失败。

### 6.3 后台管理页

验收目标：运行态控制功能可靠。

检查项：

1. “数据源连通性测试”能返回 Sina、iFinD、Infoway 贵金属、Infoway 加密货币状态。
2. “清除所有缓存”成功后，下一轮轮询能自动恢复数据。
3. “数据源优先级配置”矩阵能正确加载。
4. 点击矩阵单元后，优先级数字会立即重排。
5. 保存后提示成功，且无需重启服务即可生效。
6. 切换 XAG / XAU 数据源后，可通过页面或接口观察 `source` 字段变化。

### 6.4 小程序

验收目标：轻量端数据读取正常。

检查项：

1. 首页、告警、设置页可以打开。
2. 行情字段与 Web 端核心接口保持一致。
3. 基础刷新和设置保存正常。

---

## 七、推荐回归流程

每次改动后建议按影响范围选择回归层级。

### 7.1 只改纯算法或工具函数

建议执行：

1. 相关单元测试
2. 全量自动化测试

### 7.2 改 API、缓存、轮询或状态管理

建议执行：

1. 全量自动化测试
2. 启动 `server.py`
3. 人工验证 `/api/status`、`/api/all`、`/api/alerts`
4. 打开首页与后台页做基本联调

### 7.3 改数据源接入或配置切换逻辑

建议执行：

1. 全量自动化测试
2. 联通性脚本验证
3. Admin 页切换数据源并观察实际 `source` 字段
4. 检查服务日志是否有连续报错或回退异常

### 7.4 改前端页面布局或交互

建议执行：

1. 打开对应页面人工验证
2. 检查桌面宽屏与窄屏布局
3. 检查首屏加载、按钮、图表、表格滚动
4. 检查接口异常时的错误提示是否可见

---

## 八、常见观察点

### 8.1 看 `source` 字段

当需要判断当前数据到底来自哪个上游时，优先检查接口返回中的 `source` 字段，例如：

- `Sina-AG0`
- `Sina-XAG`
- `iFinD-XAG`
- `Infoway-XAG`
- `Infoway-BTC`

这是验证回退逻辑和后台热切换是否生效的最快方式。

### 8.2 看缓存恢复速度

执行“清空缓存”后，下一轮轮询应能恢复核心数据：

- 快轮询默认 1 秒
- 慢轮询默认 60 秒

因此：

- 实时价格通常几秒内恢复
- 历史图表和汇率可能要等待慢轮询周期

### 8.3 看交易时段影响

非交易时段会影响测试结果：

- COMEX 周末休市时，XAG/XAU 可能无新行情
- iFinD 某些字段在休市时可能返回空
- BTC 为 24/7，更适合验证实时推送链路

---

## 九、当前已知问题与限制

### 9.1 当前自动化测试存在已知失败

现状：

- `tests/test_momentum_strategy.py::MomentumCoreTestCase::test_custom_thresholds_weaker_entry` 当前失败
- `tests/test_source_switch.py` 全部用例当前失败（数据源切换 API 尚未实现）

现象：

- `test_custom_thresholds_weaker_entry`：断言预期 `buy` / `strong_buy`，实际返回 `neutral`
- `test_source_switch.py`：接口未实现，返回 404

说明：

- 这是当前仓库已存在问题，不是最近更改导致的新回归
- 在全量回归时，需要将其视为已知基线问题，而不是新回归

### 9.2 数据源切换当前仅对运行态生效

Admin 页面保存数据源矩阵后：

- 当前进程内立即生效
- 服务重启后回到代码默认值

如果未来需要持久化，应增加写回配置文件或数据库的机制。

### 9.3 外部数据源测试具有环境依赖

联通性脚本受以下因素影响：

- 网络可达性
- 账号有效性
- API Key 有效性
- 市场交易时段
- 第三方接口限流或临时异常

因此这类测试更适合作为联调验证，不适合作为 CI 稳定门禁。

---

## 十、建议的日常测试组合

### 开发自测最小集

```powershell
python -m pytest tests/test_smoke.py -q
python -m pytest tests/test_threshold_api.py -q
python server.py
```

### 涉及策略或研究改动

```powershell
python -m pytest tests/test_momentum_strategy.py -q
python -m pytest tests/test_backtest.py -q
python -m pytest tests/test_monte_carlo.py -q
```

### 涉及真实数据源改动

```powershell
python tests/verify_ifind.py
python tests/verify_infoway_btc.py
python server.py
```

本文重点是“怎么测、测什么、看到什么算正常”，用于降低回归遗漏和联调成本。