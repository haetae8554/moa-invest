"""The order-related subset of the original TossClient, without UI imports."""
from threading import RLock
import re
import time

from .auth import TossAuthClient, TOSS_BASE_URL
from .http import HttpSession
from .errors import ApiError, TradingError


def unwrap(payload):
    if isinstance(payload, dict) and "result" in payload:
        return payload["result"]
    return payload


def items(payload):
    payload = unwrap(payload)
    if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "prices", "stocks", "warnings", "orders"):
            if key in payload:
                return items(payload[key])
    raise TradingError("Toss API 목록 응답 형식을 확인할 수 없습니다.")


class TossClient:
    def __init__(self, auth_client: TossAuthClient, session=None):
        self.auth = auth_client
        self.session = session or HttpSession()
        self._lock = RLock()
        self._accounts_cache = None

    def _request(self, method, path, *, account=None, params=None, payload=None):
        with self._lock:
            token = self.auth.get_access_token()
            recovered = False
            rate_retries = 0
            while True:
                headers = {"Authorization": f"Bearer {token}"}
                if account is not None:
                    headers["X-Tossinvest-Account"] = str(account)
                if payload is not None:
                    headers["Content-Type"] = "application/json"
                response = self.session.request(method, TOSS_BASE_URL + path, headers=headers,
                                                params=params, json=payload, timeout=20)
                if response.status_code == 401 and not recovered:
                    token = self.auth.recover_access_token(rejected_token=token)
                    recovered = True
                    continue
                if response.status_code == 429 and method == "GET" and rate_retries < 2:
                    try:
                        delay = min(max(float(response.headers.get("Retry-After", "1")), 0.2), 5)
                    except ValueError:
                        delay = 1
                    time.sleep(delay)
                    rate_retries += 1
                    continue
                if response.status_code >= 300:
                    # Never log raw response text, headers, or credentials.
                    code = "api-error"
                    try:
                        error = response.json().get("error", {})
                        candidate = error.get("code", "") if isinstance(error, dict) else ""
                        if re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", candidate):
                            code = candidate
                    except (ValueError, AttributeError, TypeError):
                        pass
                    raise ApiError(response.status_code, code)
                try:
                    data = response.json()
                except ValueError:
                    raise TradingError("Toss API 응답이 올바른 JSON이 아닙니다.") from None
                if isinstance(data, dict) and data.get("error"):
                    raise TradingError("Toss API가 오류 응답을 반환했습니다.")
                return unwrap(data)

    def list_accounts(self):
        with self._lock:
            if self._accounts_cache and self._accounts_cache[0] > time.monotonic():
                return self._accounts_cache[1]
            rows = items(self._request("GET", "/api/v1/accounts"))
            self._accounts_cache = (time.monotonic() + 30, rows)
            return rows

    def get_stocks(self, symbols):
        return items(self._request("GET", "/api/v1/stocks", params={"symbols": ",".join(symbols)}))

    def get_prices(self, symbols):
        return items(self._request("GET", "/api/v1/prices", params={"symbols": ",".join(symbols)}))

    def get_daily_candles(self, symbol):
        return self._request("GET", "/api/v1/candles", params={
            "symbol": symbol, "interval": "1d", "count": 200, "adjusted": "true"})

    def get_buying_power(self, account, currency="USD"):
        return self._request("GET", "/api/v1/buying-power", account=account, params={"currency": currency})

    def get_holdings(self, account):
        return self._request("GET", "/api/v1/holdings", account=account)

    def get_sellable_quantity(self, account, symbol):
        return self._request("GET", "/api/v1/sellable-quantity", account=account, params={"symbol": symbol})

    def get_stock_warnings(self, symbol):
        return items(self._request("GET", f"/api/v1/stocks/{symbol}/warnings"))

    def get_commissions(self, account):
        return items(self._request("GET", "/api/v1/commissions", account=account))

    def list_orders(self, account, status="OPEN"):
        if status not in {"OPEN", "CLOSED"}:
            raise ValueError("주문 상태는 OPEN 또는 CLOSED여야 합니다.")
        return self._request("GET", "/api/v1/orders", account=account, params={"status": status, "limit": 20})

    def create_order(self, account, payload):
        # No retries on timeouts, 429 or 5xx. Only explicit 401 gets one recovery.
        return self._request("POST", "/api/v1/orders", account=account, payload=payload)
