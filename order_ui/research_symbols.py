"""Reviewed research relationships, independent of order symbol selection.

Source: https://www.roundhillinvestments.com/etf/ (reviewed 2026-10-24).
Stock underlyings and index reference ETFs are explicitly distinguished.
Never infer a ticker from an ETF suffix.
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
INDEX_UNDERLYINGS = MappingProxyType({
    "QDTE": ("NDX", "나스닥100", "QQQ", "https://www.invesco.com/qqq-etf/en/home.html"),
    "XDTE": ("SPX", "S&P 500", "SPY", "https://www.ssga.com/us/en/individual/etfs/state-street-spdr-sp-500-etf-trust-spy"),
    "RDTE": ("RUT", "러셀2000", "IWM", "https://www.ishares.com/us/literature/fact-sheet/iwm-ishares-russell-2000-etf-fund-fact-sheet-en-us.pdf"),
})


def symbol_relations():
    """Public metadata only. Also consumed by news UI, with no broker required."""
    rows = {symbol: {"symbol": pair[0], "name": pair[1], "kind": "stock",
                     "newsQuery": pair[0], "chartSymbol": pair[0], "chartProxy": False,
                     "sourceUrl": SOURCE_URL} for symbol, pair in UNDERLYINGS.items()}
    rows.update({symbol: {"symbol": index, "name": name, "kind": "index",
                          "newsQuery": name, "chartSymbol": proxy, "chartProxy": True,
                          "sourceUrl": f"https://www.roundhillinvestments.com/etf/{symbol.lower()}/",
                          "proxySourceUrl": source}
                 for symbol, (index, name, proxy, source) in INDEX_UNDERLYINGS.items()})
    return rows


def chart_target(symbol, basis):
    if basis not in ("underlying", "self"):
        raise ValueError("지표 기준은 원본 종목 또는 선택 종목이어야 합니다.")
    underlying = symbol_relations().get(symbol)
    return (underlying["chartSymbol"] if underlying and basis == "underlying" else symbol), underlying
