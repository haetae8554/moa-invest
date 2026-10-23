"""Reviewed indicator relationships, independent of order symbol selection.

Source: https://www.roundhillinvestments.com/etf/ (reviewed 2026-10-24).
Only unambiguous single-stock relationships are listed. Never infer a ticker
from an ETF suffix or substitute a stock ETF for a futures/index benchmark.
"""
from types import MappingProxyType


UNDERLYINGS = MappingProxyType({
    "GOOW": ("GOOGL", "알파벳 A"),
    "AVGW": ("AVGO", "브로드컴"),
    "NVDW": ("NVDA", "엔비디아"),
    "TSLW": ("TSLA", "테슬라"),
    "AAPW": ("AAPL", "애플"),
    "COIW": ("COIN", "코인베이스"),
    "PLTW": ("PLTR", "팔란티어"),
    "AMZW": ("AMZN", "아마존"),
    "HOOW": ("HOOD", "로빈후드"),
    "METW": ("META", "메타"),
    "NFLW": ("NFLX", "넷플릭스"),
    "AMDW": ("AMD", "AMD"),
    "MSFW": ("MSFT", "마이크로소프트"),
    "MSTW": ("MSTR", "스트래티지"),
    "ARMW": ("ARM", "Arm"),
    "BABW": ("BABA", "알리바바"),
    "COSW": ("COST", "코스트코"),
    "UBEW": ("UBER", "우버"),
    "UNHW": ("UNH", "유나이티드헬스"),
})
SOURCE_URL = "https://www.roundhillinvestments.com/etf/"


def chart_target(symbol, basis):
    if basis not in ("underlying", "self"):
        raise ValueError("지표 기준은 원본 종목 또는 선택 종목이어야 합니다.")
    pair = UNDERLYINGS.get(symbol)
    underlying = {"symbol": pair[0], "name": pair[1], "sourceUrl": SOURCE_URL} if pair else None
    return (pair[0] if pair and basis == "underlying" else symbol), underlying
