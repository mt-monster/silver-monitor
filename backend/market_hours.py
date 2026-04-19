from datetime import datetime

from backend.config import CST

# ── SHFE 交易时段（分钟表示） ────────────────────────────────────────
# (start_minutes, end_minutes, description)
_SHFE_DAY_SESSIONS = [
    (9 * 60,       11 * 60 + 30, "早盘交易"),     # 09:00 - 11:30
    (13 * 60 + 30, 15 * 60,      "午盘交易"),     # 13:30 - 15:00
]
_SHFE_NIGHT_START = 21 * 60       # 21:00
_SHFE_NIGHT_END   = 2 * 60 + 30  # 次日 02:30


def _to_minutes(hour, minute):
    return hour * 60 + minute


def is_huyin_trading():
    now = datetime.now(CST)
    if now.weekday() >= 5:
        return False
    t = _to_minutes(now.hour, now.minute)
    for start, end, _ in _SHFE_DAY_SESSIONS:
        if start <= t <= end:
            return True
    # 夜盘跨零点
    if t >= _SHFE_NIGHT_START or t <= _SHFE_NIGHT_END:
        return True
    return False


def is_comex_trading():
    now = datetime.now(CST)
    weekday = now.weekday()
    hour = now.hour

    if weekday < 5:
        return True

    if weekday == 5:
        if hour < 6:
            return True
        if hour >= 7:
            return False
        return True

    if weekday == 6:
        if hour >= 18:
            return True
        return False

    return False


def get_trading_status(market):
    now = datetime.now(CST)
    weekday = now.weekday()
    t = _to_minutes(now.hour, now.minute)

    if market == "huyin":
        if weekday >= 5:
            return ("closed", "周末休市")

        for start, end, desc in _SHFE_DAY_SESSIONS:
            if start <= t <= end:
                return ("open", desc)
        if t >= _SHFE_NIGHT_START or t <= _SHFE_NIGHT_END:
            return ("open", "夜盘交易")

        # 休市期间提示下一个交易时段
        if t < _SHFE_DAY_SESSIONS[0][0]:
            return ("closed", "待早盘开盘 09:00")
        if t < _SHFE_DAY_SESSIONS[1][0]:
            return ("closed", "午盘 13:30 开盘")
        return ("closed", "夜盘 21:00 开盘")

    if market == "comex":
        hour = now.hour
        if weekday < 5:
            return ("open", "SI=F 活跃交易")
        if weekday == 5:
            if hour < 6:
                return ("open", "SI=F 交易中")
            if hour >= 7:
                return ("closed", "下周一开盘")
            return ("open", "SI=F 交易中")
        if weekday == 6:
            if hour >= 18:
                return ("open", "SI=F 开市")
            return ("closed", "待周日晚开市")

    return ("unknown", "Unknown status")
