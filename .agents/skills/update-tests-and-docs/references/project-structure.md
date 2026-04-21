# 项目结构参考：测试与文档映射

## 目录结构

```
silver-monitor/
├── backend/                 # Python 后端
│   ├── strategies/          # 策略算法
│   │   ├── momentum.py      # 动量策略
│   │   ├── reversal.py      # 反转策略
│   │   └── indicators.py    # 通用指标
│   ├── http_server.py       # HTTP API
│   ├── pollers.py           # 数据轮询
│   ├── state.py             # 全局状态
│   ├── backtest.py          # 回测引擎
│   ├── analytics.py         # 绩效分析
│   └── alerts.py            # 告警系统
├── assets/js/monitor/       # 前端 JS
│   ├── core.js              # 配置加载
│   ├── momentum.js          # 动量信号渲染
│   ├── reversal.js          # 反转信号渲染
│   └── strategy.js          # 策略页面逻辑
├── tests/                   # 测试目录
├── docs/                    # 文档目录
└── monitor.config.json      # 运行时配置
```

## 测试与源码映射表

| 源码文件 | 对应测试文件 | 测试重点 |
|---------|------------|---------|
| `backend/strategies/momentum.py` | `tests/test_momentum_strategy.py` | EMA计算、信号判定、BB融合、参数覆盖 |
| `backend/strategies/reversal.py` | （暂无） | RSI计算、超买超卖判定、信号生成 |
| `backend/backtest.py` | `tests/test_backtest.py` | 回测引擎、权益曲线、绩效指标 |
| `backend/http_server.py` | `tests/test_backtest_api.py`、`tests/test_smoke.py` | API响应、错误码、SSE格式 |
| `backend/pollers.py` | `tests/test_market_hours.py` | 市场时间判定、数据源切换 |
| `backend/analytics.py` | `tests/test_analytics.py` | 绩效指标计算 |
| `backend/alerts.py` | `tests/test_alerts_tick_jump.py` | 告警触发条件 |
| `backend/state.py` | 集成测试覆盖 | 状态一致性、缓存机制 |
| `assets/js/monitor/*.js` | （暂无系统前端测试） | 关键计算函数可考虑补充 |

## 文档与源码映射表

| 源码/功能模块 | 对应文档 | 文档重点 |
|-------------|---------|---------|
| 动量策略算法 | `docs/momentum-strategy.md` | EMA公式、信号判定、BB融合、参数说明 |
| 反转策略算法 | `docs/momentum-strategy.md`（共享） | RSI公式、超买超卖阈值 |
| 回测引擎 + API | `docs/strategy-backtest.md` | API接口、请求/响应、绩效指标说明 |
| 数据模型 | `docs/data-models.md` | MarketSnapshot字段、换算逻辑 |
| 数据集成 | `docs/data-integration.md` | 数据源配置、API Key、轮询逻辑 |
| 业务架构 | `docs/business-architecture.md` | 系统架构、配置系统、部署说明 |
| 测试流程 | `docs/testing-guide.md` | 环境准备、执行方式、常见问题 |
| 蒙特卡洛分析 | `docs/research-monte-carlo.md` | 随机模拟、参数敏感性 |

## 配置文件关联

`monitor.config.json` 变更时，以下文档可能需要同步：

- `docs/momentum-strategy.md` —— 参数默认值
- `docs/strategy-backtest.md` —— 回测参数说明
- `docs/business-architecture.md` —— 配置架构说明
- `docs/testing-guide.md` —— 测试相关配置
