from datetime import datetime

from backend.config import CST


def is_huyin_trading():
    now = datetime.now(CST)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute

    if weekday >= 5:
        return False

    if 9 <= hour < 11:
        return True
    if hour == 11 and minute <= 30:
        return True

    if 13 <= hour < 15:
        return True
    if hour == 13 and minute < 30:
        return False

    if hour >= 21:
        return True
    if 0 <= hour < 2:
        return True
    if hour == 2 and minute <= 30:
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
    hour = now.hour
    minute = now.minute

    if market == "huyin":
        if weekday >= 5:
            return ("closed", "周末休市")

        if (hour == 9 and minute >= 0) or (9 < hour < 11) or (hour == 11 and minute < 31):
            return ("open", "早盘交易")
        if (hour == 13 and minute >= 30) or (13 < hour < 15):
            return ("open", "午盘交易")
        if hour >= 21 or hour < 2 or (hour == 2 and minute < 30):
            return ("open", "夜盘交易")

        if hour < 9:
            return ("closed", "待早盘开盘 09:00")
        if hour < 13 or (hour == 13 and minute < 30):
            return ("closed", "午盘 13:30 开盘")
        return ("closed", "夜盘 21:00 开盘")

    if market == "comex":
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
