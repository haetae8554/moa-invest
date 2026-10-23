"""Optional, read-only research. Sentiment providers receive no account data."""
from datetime import datetime, timezone
from decimal import Decimal, DecimalException
from threading import RLock
import time
import re

from toss_fractional.errors import TradingError
from toss_fractional.http import HttpSession
from .research_symbols import chart_target

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CNN_PAGE = "https://www.cnn.com/markets/fear-and-greed"
FGC_URL = "https://feargreedchart.com/api/?action=all"
FGC_PAGE = "https://feargreedchart.com/"
RATINGS = {"extreme fear": "극도의 공포", "fear": "공포", "neutral": "중립",
           "greed": "탐욕", "extreme greed": "극도의 탐욕"}


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 80:
        raise ValueError("숫자 정보가 없습니다.")
    try:
        result = Decimal(str(value))
        # Bound precision/exponents before arithmetic and conversion to JSON floats.
        if not result.is_finite() or abs(result.adjusted()) > 100 or abs(result.as_tuple().exponent) > 100:
            raise ValueError("유효하지 않은 숫자입니다.")
        return result
    except DecimalException:
        raise ValueError("유효하지 않은 숫자입니다.") from None


def timestamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("시각의 시간대가 없습니다.")
    return result


def chart_summary(payload, symbol):
    """Use adjusted daily closes, including the latest possibly incomplete bar."""
    rows = payload.get("candles") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows or len(rows) > 200:
        raise ValueError("일봉 데이터가 없습니다.")
    points, seen, currency = [], set(), None
    for row in rows:
        dt = timestamp(row["timestamp"])
        close = number(row["closePrice"])
        if close <= 0 or row["currency"] not in {"USD", "KRW"}:
            raise ValueError("일봉 가격을 확인할 수 없습니다.")
        if currency is not None and row["currency"] != currency:
            raise ValueError("일봉 통화가 일치하지 않습니다.")
        currency = row["currency"]
        if dt in seen:
            raise ValueError("중복된 일봉입니다.")
        seen.add(dt)
        points.append((dt, close))
    points.sort(key=lambda point: point[0])
    last = points[-1][1]
    averages = []
    for period in (20, 60, 120, 200):
        mean = sum((p[1] for p in points[-period:]), Decimal(0)) / period if len(points) >= period else None
        averages.append({"period": period, "value": str(mean) if mean is not None else None,
                         "distancePct": str((last / mean - 1) * 100) if mean else None})
    return {"symbol": symbol, "currency": currency, "lastClose": str(last),
            "barDate": points[-1][0].date().isoformat(), "count": len(points),
            "averages": averages, "adjusted": True,
            "history": [{"date": dt.date().isoformat(), "value": float(close)} for dt, close in points]}


def fear_summary(payload):
    data = payload["fear_and_greed"]
    score = number(data["score"])
    if not 0 <= score <= 100 or data["rating"] not in RATINGS:
        raise ValueError("지수를 확인할 수 없습니다.")
    updated = timestamp(data["timestamp"])
    previous = data.get("previous_close")
    previous = number(previous) if previous is not None else None
    if previous is not None and not 0 <= previous <= 100:
        raise ValueError("이전 지수를 확인할 수 없습니다.")
    history = []
    for row in payload.get("fear_and_greed_historical", {}).get("data", [])[-90:]:
        value = number(row["y"])
        if not 0 <= value <= 100:
            raise ValueError("지수 이력을 확인할 수 없습니다.")
        date = datetime.fromtimestamp(float(number(row["x"])) / 1000, timezone.utc)
        history.append({"date": date.isoformat(), "value": float(value)})
    history.sort(key=lambda row: row["date"])
    return {"score": float(score), "rating": RATINGS[data["rating"]],
            "previousClose": float(previous) if previous is not None else None,
            "asOf": updated.isoformat(), "history": history, "sourceUrl": CNN_PAGE}


def alternative_fear_summary(payload):
    """Independent US stock sentiment model, NOT a mirror of the CNN index."""
    score = number(payload["score"]["score"])
    if not 0 <= score <= 100:
        raise ValueError("지수를 확인할 수 없습니다.")
    updated = datetime.fromtimestamp(float(number(payload["ts"])) / 1000, timezone.utc)
    if updated.year < 2025:
        raise ValueError("제공사 응답 시각을 확인할 수 없습니다.")
    rows = payload["recent"]
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("지수 이력을 확인할 수 없습니다.")
    history, seen = [], set()
    for row in rows:
        day = row["date"]
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("지수 이력 날짜를 확인할 수 없습니다.")
        dt = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        value = number(row["score"])
        if not 0 <= value <= 100 or day in seen or dt.date() > updated.date():
            raise ValueError("지수 이력을 확인할 수 없습니다.")
        seen.add(day)
        history.append({"date": dt.isoformat(), "value": float(value)})
    history.sort(key=lambda row: row["date"])
    rating = "극도의 공포" if score <= 20 else "공포" if score <= 40 else "중립" if score <= 60 else "탐욕" if score <= 80 else "극도의 탐욕"
    return {"score": float(score), "rating": rating, "previousClose": None,
            "asOf": updated.isoformat(), "asOfLabel": "제공사 응답 시각",
            "history": history[-90:], "sourceUrl": FGC_PAGE}


class ResearchData:
    def __init__(self, session=None, clock=time.time):
        self.session = session or HttpSession()
        self.clock = clock
        self._fear_lock = RLock()
        self._chart_lock = RLock()
        self._fear_cache = {}
        self._fear_retry = {}
        self._fear_failures = {}
        self._charts = {}

    def _fear_source(self, source):
        now = self.clock()
        url, page, name, parser = ((CNN_URL, CNN_PAGE, "CNN 공포·탐욕", fear_summary) if source == "cnn"
                                  else (FGC_URL, FGC_PAGE, "FearGreedChart 미국시장 심리", alternative_fear_summary))
        if now >= self._fear_retry.get(source, 0):
            # Independent providers, never alternate URLs/headers to evade a block.
            self._fear_retry[source] = now + 900
            try:
                response = self.session.get(url, timeout=8, max_response_bytes=1024 * 1024,
                                            headers={"Accept": "application/json"})
                if response.status_code != 200:
                    self._fear_failures[source] = {"failureReason": "http", "httpStatus": response.status_code}
                else:
                    result = parser(response.json())
                    if timestamp(result["asOf"]).timestamp() > now + 300:
                        raise ValueError("미래 시각의 지수입니다.")
                    self._fear_cache[source] = {**result, "fetchedAt": now}
                    self._fear_failures.pop(source, None)
            except TradingError:
                self._fear_failures[source] = {"failureReason": "network"}
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
                self._fear_failures[source] = {"failureReason": "invalidData"}
        cached = self._fear_cache.get(source)
        failure = self._fear_failures.get(source, {})
        meta = {"provider": source, "providerName": name, "sourceUrl": page,
                "retryAt": self._fear_retry[source], **failure}
        if not cached:
            return {**meta, "unavailable": True}
        stale = now - timestamp(cached["asOf"]).timestamp() > 36 * 3600
        return {**cached, **meta, "stale": stale or bool(failure), "unavailable": bool(failure)}

    def fear(self, source="auto"):
        if source not in ("auto", "cnn", "feargreedchart"):
            raise ValueError("시장 심리지수 출처를 확인해 주세요.")
        with self._fear_lock:
            primary = self._fear_source("cnn" if source == "auto" else source)
            if source == "auto" and primary["unavailable"]:
                other = self._fear_source("feargreedchart")
                fallback = {"reason": primary.get("failureReason"), "httpStatus": primary.get("httpStatus")}
                if "score" in other:
                    return {**other, "requestedSource": source, "fallback": fallback}
                return {**primary, "requestedSource": source, "fallbackUnavailable": True}
            return {**primary, "requestedSource": source}

    def chart(self, broker, symbol, basis="underlying"):
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}|[0-9]{6}", symbol):
            raise ValueError("종목을 선택해 주세요.")
        target, underlying = chart_target(symbol, basis)
        with self._chart_lock:
            now = self.clock()
            cached = self._charts.get(target)
            if cached and cached[0] is broker and now - cached[1] < 300:
                result = cached[2]
            else:
                try:
                    result = chart_summary(broker.get_daily_candles(target), target)
                except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
                    raise TradingError(f"{target} 일봉 데이터를 확인할 수 없습니다.") from None
                result["fetchedAt"] = now
                if len(self._charts) >= 32:
                    self._charts.pop(next(iter(self._charts)))
                self._charts[target] = (broker, now, result)
            # Cache candles by their actual ticker; selection metadata is per request.
            return {**result, "selectedSymbol": symbol, "basis": basis, "underlying": underlying}
