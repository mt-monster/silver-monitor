from typing import Literal, NotRequired, TypedDict


MarketCode = Literal["hu", "comex", "hujin", "comex_gold"]
AlertDirection = Literal["急涨", "急跌"]
Severity = Literal["LOW", "MEDIUM", "HIGH"]


class TimeSeriesPoint(TypedDict):
    t: int
    y: float


class MarketSnapshot(TypedDict):
    source: str
    symbol: str
    name: str
    exchange: str
    currency: str
    unit: str
    timestamp: int
    datetime_cst: str
    price: NotRequired[float]
    prevClose: NotRequired[float]
    change: NotRequired[float]
    changePercent: NotRequired[float]
    open: NotRequired[float]
    high: NotRequired[float]
    low: NotRequired[float]
    volume: NotRequired[int]
    oi: NotRequired[int]
    priceCny: NotRequired[float]
    priceCnyG: NotRequired[float]
    usdCny: NotRequired[float]
    convFactor: NotRequired[float]
    closed: NotRequired[bool]
    status_desc: NotRequired[str]
    history: NotRequired[list[TimeSeriesPoint]]
    historyCount: NotRequired[int]
    error: NotRequired[str]


class SpreadSnapshot(TypedDict):
    ratio: float
    cnySpread: float
    status: str
    deviation: float
    usdCNY: NotRequired[float]
    convFactor: NotRequired[float]
    comexInCNY: NotRequired[float]
    comexInCNYG: NotRequired[float]


class AlertEvent(TypedDict):
    id: str
    market: MarketCode
    marketName: str
    type: str
    direction: AlertDirection
    threshold: float
    changePercent: float
    changeAbs: float
    fromPrice: float
    toPrice: float
    fromTime: str
    toTime: str
    oneTickPct: float
    twoTickPct: float
    tickCount: int
    source: str
    timestamp: int
    datetime: str
    severity: Severity
    unit: str


class AlertStats(TypedDict):
    surge: int
    drop: int
    maxJump: float


class CombinedApiResponse(TypedDict):
    comex: MarketSnapshot | dict
    huyin: MarketSnapshot | dict
    comexGold: MarketSnapshot | dict
    hujin: MarketSnapshot | dict
    signals: NotRequired[dict[str, dict]]
    spread: SpreadSnapshot | dict
    goldSpread: SpreadSnapshot | dict
    goldSilverRatio: float | None
    hvSeries: dict[str, list[TimeSeriesPoint]]
    timestamp: int
    datetime_utc: str
    datetime_cst: str
    activeSources: list[str]


class AlertsApiResponse(TypedDict):
    alerts: list[AlertEvent]
    count: int
    threshold: float
    stats: dict[str, AlertStats]
    huTickRing: list[dict]
    comexTickRing: list[dict]
    hujinTickRing: list[dict]
    comexGoldTickRing: list[dict]
