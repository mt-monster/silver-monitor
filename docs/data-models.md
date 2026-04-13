# 数据模型与字段说明

本文档定义网页端、小程序端与后端 API 共用的核心数据结构，作为字段级约定。

## 1. 市场快照 `MarketSnapshot`

用于表示单个市场的最新快照，适用于：

- 沪银 `huyin`
- COMEX 银 `comex`
- 沪金 `hujin`
- COMEX 金 `comexGold`

### 基础字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `source` | `string` | 数据来源标识 |
| `symbol` | `string` | 交易标的代码 |
| `name` | `string` | 展示名称 |
| `exchange` | `string` | 交易所或市场 |
| `currency` | `string` | 报价币种 |
| `unit` | `string` | 价格单位 |
| `timestamp` | `number` | 毫秒时间戳 |
| `datetime_cst` | `string` | CST 时间字符串 |

### 价格字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `price` | `number` | 最新价 |
| `prevClose` | `number` | 昨收 |
| `change` | `number` | 涨跌额 |
| `changePercent` | `number` | 涨跌幅 |
| `open` | `number` | 开盘价 |
| `high` | `number` | 最高价 |
| `low` | `number` | 最低价 |
| `volume` | `number` | 成交量 |
| `oi` | `number` | 持仓量，可选 |

### 换算字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `priceCny` | `number` | 银价换算人民币价格 |
| `priceCnyG` | `number` | 金价换算人民币克价 |
| `usdCny` | `number` | 汇率 |
| `convFactor` | `number` | 汇率换算因子 |

### 状态字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `closed` | `boolean` | 是否休市 |
| `status_desc` | `string` | 交易状态说明 |
| `error` | `string` | 错误标识 |

### 历史字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `history` | `TimeSeriesPoint[]` | 历史时间序列 |
| `historyCount` | `number` | 历史数据点数量 |

## 2. 时序点 `TimeSeriesPoint`

用于图表、历史走势与波动率序列。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `t` | `number` | 毫秒时间戳 |
| `y` | `number` | 数值 |

## 3. 价差对象 `SpreadSnapshot`

适用于：

- `spread`
- `goldSpread`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ratio` | `number` | 内外盘比价 |
| `cnySpread` | `number` | 人民币价差 |
| `status` | `string` | 状态文案，如“轻度溢价” |
| `deviation` | `number` | 偏离 1 的百分比 |
| `usdCNY` | `number` | 汇率 |
| `convFactor` | `number` | 换算因子 |
| `comexInCNY` | `number` | 银价换算人民币结果 |
| `comexInCNYG` | `number` | 金价换算人民币克价结果 |

## 4. 聚合接口 `CombinedApiResponse`

接口：

- `GET /api/all`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `comex` | `MarketSnapshot` | COMEX 银 |
| `huyin` | `MarketSnapshot` | 沪银 |
| `comexGold` | `MarketSnapshot` | COMEX 金 |
| `hujin` | `MarketSnapshot` | 沪金 |
| `spread` | `SpreadSnapshot` | 白银价差 |
| `goldSpread` | `SpreadSnapshot` | 黄金价差 |
| `goldSilverRatio` | `number \| null` | 金银比 |
| `hvSeries` | `Record<string, TimeSeriesPoint[]>` | 波动率序列 |
| `timestamp` | `number` | 聚合数据时间戳 |
| `datetime_utc` | `string` | UTC 时间 |
| `datetime_cst` | `string` | CST 时间 |
| `activeSources` | `string[]` | 当前参与聚合的数据源 |

### `hvSeries` 的 key

| key | 说明 |
| --- | --- |
| `hu` | 沪银 HV20 |
| `comex` | COMEX 银 HV20 |
| `hujin` | 沪金 HV20 |
| `comex_gold` | COMEX 金 HV20 |

## 5. 预警事件 `AlertEvent`

接口：

- `GET /api/alerts`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `string` | 告警唯一标识 |
| `market` | `string` | 市场代码 |
| `marketName` | `string` | 市场名称 |
| `type` | `string` | 告警类型 |
| `direction` | `string` | `急涨` 或 `急跌` |
| `threshold` | `number` | 触发阈值 |
| `changePercent` | `number` | 变动百分比 |
| `changeAbs` | `number` | 绝对价差 |
| `fromPrice` | `number` | 起始价格 |
| `toPrice` | `number` | 结束价格 |
| `fromTime` | `string` | 起始时间 |
| `toTime` | `string` | 结束时间 |
| `oneTickPct` | `number` | 单 tick 变动 |
| `twoTickPct` | `number` | 三 tick 总变动 |
| `tickCount` | `number` | 当前参与判断的 tick 数 |
| `source` | `string` | 数据源 |
| `timestamp` | `number` | 时间戳 |
| `datetime` | `string` | 可读时间 |
| `severity` | `string` | `LOW/MEDIUM/HIGH` |
| `unit` | `string` | 单位 |

## 6. 预警接口 `AlertsApiResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `alerts` | `AlertEvent[]` | 告警历史 |
| `count` | `number` | 告警数量 |
| `threshold` | `number` | 当前阈值 |
| `stats` | `Record<string, AlertStats>` | 统计信息 |
| `huTickRing` | `object[]` | 沪银 ring |
| `comexTickRing` | `object[]` | COMEX 银 ring |
| `hujinTickRing` | `object[]` | 沪金 ring |
| `comexGoldTickRing` | `object[]` | COMEX 金 ring |

## 7. 约定原则

- 后端内部命名可以演进，但对外字段尽量保持稳定。
- 页面渲染字段以 `/api/all` 和 `/api/alerts` 为准。
- 小程序与网页端应尽量共用同一字段含义。
- 新增字段时优先补充到 `backend/models.py` 和本文档。
