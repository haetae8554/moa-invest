from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Protocol
import json
import re
import time
import uuid

from .config import Settings, money
from .store import OrderStore
from .errors import ApiError, TradingError, UnknownOrderError

KST = timezone(timedelta(hours=9))


class Broker(Protocol):
    """Inject a compatible broker for another host application or offline tests."""
    def list_accounts(self) -> list[dict]: ...
    def get_stocks(self, symbols: list[str]) -> list[dict]: ...
    def get_prices(self, symbols: list[str]) -> list[dict]: ...
    def get_buying_power(self, account: str, currency: str = "USD") -> dict: ...
    def get_sellable_quantity(self, account: str, symbol: str) -> dict: ...
    def get_holdings(self, account: str) -> dict: ...
    def get_stock_warnings(self, symbol: str) -> list[dict]: ...
    def get_commissions(self, account: str) -> list[dict]: ...
    def create_order(self, account: str, payload: dict) -> dict: ...
    def list_orders(self, account: str, status: str = "OPEN") -> dict: ...


def positive_decimal(value, label):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0:
            raise ValueError
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise TradingError(f"{label}을 확인할 수 없습니다.") from None


class FractionalBuyService:
    def __init__(self, broker: Broker | None, settings: Settings, store: OrderStore | None = None, clock=time.time):
        self.broker = broker
        self.settings = settings
        self.store = store or OrderStore(settings.data_dir / "orders.sqlite3")
        self.clock = clock

    def _broker(self):
        if self.broker is None:
            raise TradingError("API 키가 없습니다. .env에 TOSS_CLIENT_ID와 TOSS_CLIENT_SECRET을 설정해 주세요.")
        return self.broker

    def _account(self, account_seq=None):
        rows = [a for a in self._broker().list_accounts() if a.get("accountType") == "BROKERAGE"]
        requested = str(account_seq or self.settings.account_seq or "")
        if requested:
            account = next((a for a in rows if str(a.get("accountSeq")) == requested), None)
        else:
            account = rows[0] if len(rows) == 1 else None
        if account is None:
            raise ValueError("주문에 사용할 종합매매 계좌를 선택해 주세요.")
        return account

    def _day(self):
        return datetime.fromtimestamp(self.clock(), KST).date().isoformat()

    def execution_mode(self):
        with self.store.connect() as db:
            return self.store.mode(db, self.settings.execution_enabled)

    def set_execution_mode(self, enabled: bool, expected_revision: int):
        if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("주문 모드와 현재 설정 버전을 확인해 주세요.")
        with self.store.connect(write=True) as db:
            mode = self.store.mode(db, self.settings.execution_enabled)
            if mode["modeRevision"] != expected_revision:
                raise ValueError("다른 화면에서 주문 모드가 변경되었습니다. 새로고침해 주세요.")
            revision = mode["modeRevision"] + 1
            db.execute("INSERT OR REPLACE INTO execution_mode VALUES (1, ?, ?)", (int(enabled), revision))
            db.execute("UPDATE orders SET expires=0 WHERE state='PREVIEW'")
            db.execute("UPDATE batches SET expires=0 WHERE state='PREVIEW'")
        return {"executionEnabled": enabled, "modeRevision": revision}

    def setup(self):
        result = {"configured": self.broker is not None, **self.execution_mode(),
                  "credentialSource": self.settings.credential_source,
                  "maxOrderAmountUSD": str(self.settings.max_order_usd),
                  "splitAmountUSD": "9.00", "accounts": [], "selectedAccountSeq": ""}
        if self.broker is None:
            return result
        accounts = [a for a in self.broker.list_accounts() if a.get("accountType") == "BROKERAGE"]
        result["accounts"] = [{"accountSeq": str(a["accountSeq"]),
                               "label": "종합매매 · " + str(a.get("accountNo", "----"))[-4:]} for a in accounts]
        if self.settings.account_seq:
            result["selectedAccountSeq"] = str(self._account()["accountSeq"])
        elif len(accounts) == 1:
            result["selectedAccountSeq"] = str(accounts[0]["accountSeq"])
        return result

    def balances(self, account_seq=None):
        seq = str(self._account(account_seq)["accountSeq"])
        data = self._broker().get_buying_power(seq)
        value = data.get("cashBuyingPower")
        try:
            cash = Decimal(str(value))
            if not cash.is_finite() or cash < 0:
                raise ValueError
        except (ValueError, InvalidOperation):
            raise TradingError("주문 가능 금액을 확인할 수 없습니다.") from None
        with self.store.connect() as db:
            used = self.store.spent(db, self._day(), seq)
        return {"accountSeq": seq, "buyingPowerUSD": str(cash), "submittedTodayUSD": f"{Decimal(used)/100:.2f}"}

    def holdings(self, account_seq=None):
        """Read-only portfolio snapshot. Never mix currencies or invent missing values."""
        seq = str(self._account(account_seq)["accountSeq"])
        data = self._broker().get_holdings(seq)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise TradingError("보유 종목 응답 형식을 확인할 수 없습니다.")
        def number(value, nonnegative=False):
            if value is None:
                return None
            try:
                value = Decimal(str(value))
                if not value.is_finite() or (nonnegative and value < 0):
                    raise ValueError
                return format(value, 'f')
            except (InvalidOperation, ValueError, TypeError):
                raise TradingError("보유 종목의 금액·수량을 확인할 수 없습니다.") from None
        rows = []
        for item in data["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
                raise TradingError("보유 종목 정보가 올바르지 않습니다.")
            market, pnl = item.get("marketValue") or {}, item.get("profitLoss") or {}
            if not isinstance(market, dict) or not isinstance(pnl, dict):
                raise TradingError("보유 종목 평가 정보가 올바르지 않습니다.")
            purchase = number(market.get("purchaseAmount"), True)
            profit = number(pnl.get("amount"))
            rate = str(Decimal(profit)/Decimal(purchase)) if purchase and Decimal(purchase)>0 and profit is not None else None
            rows.append({"symbol":item["symbol"], "name":item.get("name") or item["symbol"],
                         "currency":item.get("currency"), "marketCountry":item.get("marketCountry"),
                         "quantity":number(item.get("quantity"), True), "lastPrice":number(item.get("lastPrice"), True),
                         "averagePurchasePrice":number(item.get("averagePurchasePrice"), True),
                         "marketValue":number(market.get("amount"), True), "purchaseAmount":purchase,
                         "profitLoss":profit, "profitLossRate":rate,
                         "orderable":item.get("currency")=="USD" and item.get("marketCountry")=="US"})
        summaries = {}
        for currency in {row["currency"] for row in rows if row["currency"] in {"USD","KRW"}} | {"USD","KRW"}:
            group = [row for row in rows if row["currency"] == currency]
            def total(key):
                return str(sum((Decimal(row[key]) for row in group), Decimal(0))) if all(row[key] is not None for row in group) else None
            purchase, profit = total("purchaseAmount"), total("profitLoss")
            summaries[currency] = {"marketValue":total("marketValue"), "profitLoss":profit,
                                   "profitLossRate":str(Decimal(profit)/Decimal(purchase)) if purchase and Decimal(purchase)>0 and profit is not None else None,
                                   "count":len(group)}
        return {"accountSeq":seq, "items":rows, "summary":summaries,
                "asOf":datetime.fromtimestamp(self.clock(), KST).isoformat(), "costBasis":"BEFORE_COST"}

    def preview(self, symbol: str, amount_usd, account_seq=None):
        mode = self.execution_mode()
        if not isinstance(symbol, str):
            raise ValueError("티커를 입력해 주세요.")
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", symbol):
            raise ValueError("미국 종목의 영문 티커를 입력해 주세요.")
        amount = money(amount_usd, "주문 금액")
        if amount > self.settings.max_order_usd:
            raise ValueError(f"1회 주문 한도는 ${self.settings.max_order_usd}입니다.")
        broker = self._broker()
        account = self._account(account_seq)
        seq = str(account["accountSeq"])
        stocks = broker.get_stocks([symbol])
        stock = next((s for s in stocks if s.get("symbol") == symbol), None)
        if not stock or stock.get("currency") != "USD" or stock.get("status") != "ACTIVE":
            raise ValueError("거래 가능한 미국 USD 종목이 아닙니다.")
        prices = broker.get_prices([symbol])
        price_row = next((p for p in prices if p.get("symbol") == symbol), {})
        price = positive_decimal(price_row.get("lastPrice"), "현재가")
        balance = self.balances(seq)
        if Decimal(balance["buyingPowerUSD"]) < amount:
            raise ValueError("달러 주문 가능 금액이 부족합니다.")
        warnings = broker.get_stock_warnings(symbol)
        commissions = broker.get_commissions(seq)
        now = self.clock()
        preview = {
            "previewId": uuid.uuid4().hex, "clientOrderId": "fb-" + uuid.uuid4().hex,
            "accountSeq": seq, "accountLabel": "종합매매 · " + str(account.get("accountNo", "----"))[-4:],
            "symbol": symbol, "stockName": stock.get("name") or stock.get("englishName") or symbol,
            "orderAmount": str(amount), "amountCents": int(amount * 100),
            "lastPrice": str(price), "estimatedQuantity": str((amount / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)),
            "cashBuyingPower": balance["buyingPowerUSD"], "warnings": warnings, "commissions": commissions,
            "confirmationText": f"{symbol} ${amount:.2f} 매수", "expiresTimestamp": now + 120,
            "expiresAt": datetime.fromtimestamp(now + 120, KST).isoformat(),
            **mode,
        }
        self.store.save(preview)
        return preview

    def submit(self, preview_id: str, confirmation: str, *, acknowledged: bool = False):
        if not self.execution_mode()["executionEnabled"]:
            raise PermissionError("미리보기 전용입니다. 화면 위의 실주문 켜기로 변경해 주세요.")
        if acknowledged is not True:
            raise ValueError("시장가 변동과 소수점 접수 시간을 확인해 주세요.")
        broker = self._broker()
        # Read data first, then reserve atomically. No network calls inside the DB transaction.
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM orders WHERE preview_id=?", (preview_id,)).fetchone()
        if row is None:
            raise ValueError("주문 미리보기를 다시 만들어 주세요.")
        preview = json.loads(row["preview"])
        if confirmation != preview["confirmationText"]:
            raise ValueError("최종 확인 문구가 일치하지 않습니다.")
        if row["state"] == "SUBMITTED":
            return json.loads(row["result"])
        if row["state"] != "PREVIEW":
            raise UnknownOrderError("이미 시도된 주문입니다. 주문 기록에서 결과를 확인해 주세요.")
        amount = money(preview["orderAmount"])
        if amount > self.settings.max_order_usd:
            raise ValueError("현재 1회 주문 한도를 초과합니다. 다시 미리보기해 주세요.")
        balance = self.balances(row["account"])
        if Decimal(balance["buyingPowerUSD"]) < amount:
            raise ValueError("주문 가능 금액이 변경되었습니다. 다시 미리보기해 주세요.")
        with self.store.connect(write=True) as db:
            mode = self.store.mode(db, self.settings.execution_enabled)
            if not mode["executionEnabled"]:
                raise PermissionError("실주문이 꺼졌습니다. 주문을 전송하지 않았습니다.")
            if preview.get("modeRevision", 0) != mode["modeRevision"]:
                raise ValueError("주문 모드가 변경되었습니다. 다시 미리보기해 주세요.")
            current = db.execute("SELECT * FROM orders WHERE preview_id=?", (preview_id,)).fetchone()
            if current["state"] == "SUBMITTED":
                return json.loads(current["result"])
            if current["state"] != "PREVIEW":
                raise UnknownOrderError("이 주문은 이미 전송 중이거나 결과 확인이 필요합니다.")
            if current["expires"] <= self.clock():
                raise ValueError("미리보기가 만료되었습니다. 다시 확인해 주세요.")
            unresolved = db.execute("SELECT 1 FROM orders WHERE account=? AND state IN ('SUBMITTING','UNKNOWN')", (row["account"],)).fetchone()
            if unresolved:
                raise UnknownOrderError("확인되지 않은 주문이 있습니다. 토스증권 주문 내역을 먼저 확인해 주세요.")
            self.store.assert_no_active_batch(db, row["account"])
            db.execute("UPDATE orders SET state='SUBMITTING',submitted_day=? WHERE preview_id=?", (self._day(), preview_id))
        payload = {"clientOrderId": preview["clientOrderId"], "symbol": preview["symbol"],
                   "side": "BUY", "orderType": "MARKET", "orderAmount": str(amount), "confirmHighValueOrder": False}
        try:
            result = broker.create_order(row["account"], payload)
            if not isinstance(result, dict) or not isinstance(result.get("orderId"), str) or not result["orderId"]:
                raise TradingError("주문 번호가 응답에 없습니다.")
        except Exception as exc:
            rejected = isinstance(exc, ApiError) and 400 <= exc.status < 500 and exc.status not in {408, 409}
            self.store.finish(preview_id, "REJECTED" if rejected else "UNKNOWN", {"message": str(exc) if isinstance(exc, TradingError) else "주문 응답 확인 필요"})
            if rejected:
                raise
            raise UnknownOrderError("주문 결과를 확인하지 못했습니다. 재전송하지 말고 토스증권 주문 내역을 확인해 주세요.") from None
        receipt = {"orderId": result["orderId"], "clientOrderId": preview["clientOrderId"],
                   "symbol": preview["symbol"], "orderAmount": str(amount), "state": "SUBMITTED",
                   "message": "주문을 접수했습니다. 실제 체결 여부는 토스증권 주문 내역에서 확인해 주세요."}
        self.store.finish(preview_id, "SUBMITTED", receipt)
        return receipt

    def orders(self, account_seq=None, status="OPEN"):
        account = str(self._account(account_seq)["accountSeq"])
        return self._broker().list_orders(account, status)
