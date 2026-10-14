"""Persistent, sequential $9 market-order batches. No daily budget policy.

BUY quantity is converted into an explicit fixed USD budget at preview time.
SELL quantity uses exact six-decimal shares, recalculated against a fresh quote
for each child. Accepted orders are not described as fills.
"""
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP
from datetime import datetime
from threading import Thread
import json
import re
import time
import uuid

from .config import money
from .errors import ApiError, TradingError, UnknownOrderError
from .service import FractionalBuyService, positive_decimal, KST

CHUNK = Decimal("9.00")
SHARE_STEP = Decimal("0.000001")


def shares(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value <= 0 or value > Decimal("1000000000") or value != value.quantize(SHARE_STEP):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("총수량은 양수이며 소수점 6자리까지 입력해 주세요.") from None
    return value


def decimal_text(value):
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')


def split_summary(total, unit):
    full = int(total // unit)
    remainder = total - unit * full
    return {"fullOrderCount": full, "remainder": str(remainder),
            "orderCount": full + (1 if remainder else 0), "perOrder": str(unit)}


class FractionalTradeService(FractionalBuyService):
    def __init__(self, *args, interval=0.5, sleeper=time.sleep, **kwargs):
        super().__init__(*args, **kwargs)
        self.interval = max(0.0, interval)
        self.sleeper = sleeper

    def _price(self, symbol):
        rows = self._broker().get_prices([symbol])
        return positive_decimal(next((r.get("lastPrice") for r in rows if r.get("symbol") == symbol), None), "현재가")

    def _sellable(self, account, symbol):
        try:
            value = Decimal(str(self._broker().get_sellable_quantity(account, symbol).get("sellableQuantity")))
            if not value.is_finite() or value < 0:
                raise ValueError
            return value
        except (InvalidOperation, ValueError, TypeError):
            raise TradingError("매도 가능 수량을 확인할 수 없습니다.") from None

    def _resource_check(self, p, amount=None, quantity=None, price=None):
        if p["side"] == "BUY":
            cash = Decimal(self.balances(p["accountSeq"])["buyingPowerUSD"])
            if cash < amount:
                raise ValueError("달러 주문 가능 금액이 부족합니다.")
            return {"cashBuyingPower": str(cash)}
        available = self._sellable(p["accountSeq"], p["symbol"])
        needed = quantity if quantity is not None else (amount / price).quantize(SHARE_STEP, rounding=ROUND_UP)
        if needed > available:
            raise ValueError(f"매도 가능 수량이 부족합니다. 현재 {decimal_text(available)}주")
        return {"sellableQuantity": str(available)}

    def preview_batch(self, symbol, value, account_seq=None, *, side="BUY", basis="AMOUNT"):
        mode = self.execution_mode()
        if not isinstance(side, str) or not isinstance(basis, str) or side not in {"BUY", "SELL"} or basis not in {"AMOUNT", "QUANTITY"}:
            raise ValueError("매수·매도와 총금액·총수량을 선택해 주세요.")
        if not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,19}", symbol.strip().upper()):
            raise ValueError("미국 종목의 영문 티커를 입력해 주세요.")
        symbol = symbol.strip().upper()
        entered = money(value, "총주문금액") if basis == "AMOUNT" else shares(value)
        account = self._account(account_seq)
        stock = next((s for s in self._broker().get_stocks([symbol]) if s.get("symbol") == symbol), None)
        if not stock or stock.get("currency") != "USD" or stock.get("status") != "ACTIVE":
            raise ValueError("거래 가능한 미국 USD 종목이 아닙니다.")
        price = self._price(symbol)
        exact_quantity = side == "SELL" and basis == "QUANTITY"
        total = entered if basis == "AMOUNT" else (entered * price).quantize(Decimal("0.01"), rounding=ROUND_UP)
        total = money(total, "예상 총주문금액")
        unit = (CHUNK / price).quantize(SHARE_STEP, rounding=ROUND_DOWN) if exact_quantity else CHUNK
        if unit <= 0:
            raise ValueError("현재가에서 $9 이하로 주문할 수 있는 소수점 수량이 없습니다.")
        split = split_summary(entered if exact_quantity else total, unit)
        label = "매수" if side == "BUY" else "매도"
        target = f"${total:.2f}" if basis == "AMOUNT" else f"{decimal_text(entered)}주"
        if basis == "QUANTITY" and side == "BUY":
            target += f" 예상 ${total:.2f}"
        p = {"batchId": uuid.uuid4().hex, "accountSeq": str(account["accountSeq"]),
             "accountLabel": "종합매매 · " + str(account.get("accountNo", "----"))[-4:],
             "symbol": symbol, "stockName": stock.get("name") or stock.get("englishName") or symbol,
             "side": side, "basis": basis, "inputValue": str(entered), "exactQuantity": exact_quantity,
             "totalOrderAmount": str(total), "targetQuantity": str(entered) if basis == "QUANTITY" else None,
             "estimatedQuantity": str((total / price).quantize(SHARE_STEP, rounding=ROUND_DOWN)),
             "lastPrice": str(price), "splitAmountUSD": str(CHUNK), "split": split,
             "confirmationText": f"{symbol} {target} 분할 {label}", **mode,
             "expiresTimestamp": self.clock() + 120,
             "createdAt": datetime.fromtimestamp(self.clock(), KST).isoformat(),
             "quantityNotice": ("매수 수량은 현재가로 환산한 예상치이며 실제 체결 수량과 다를 수 있습니다." if side == "BUY" else
                                "매도 수량 주문은 각 전송 직전 현재가로 $9에 해당하는 수량을 다시 계산합니다." if exact_quantity else
                                "확인한 총금액을 나눠 매도합니다. 실제 매도 수량은 체결 시점 가격에 따라 달라집니다."),
             "feeNotice": "수수료 면제는 주문 건당 실제 체결금액 $10 이하 기준입니다. 수량 주문은 시세 변동으로 초과할 수 있으며 세금·제비용은 별도입니다."}
        p.update(self._resource_check(p, amount=total, quantity=entered if exact_quantity else None, price=price))
        p["warnings"] = self._broker().get_stock_warnings(symbol)
        p["commissions"] = self._broker().get_commissions(p["accountSeq"])
        with self.store.connect(write=True) as db:
            if self.store.mode(db)["modeRevision"] != mode["modeRevision"]:
                raise ValueError("주문 모드가 변경되었습니다. 다시 미리보기해 주세요.")
            db.execute("INSERT INTO batches (id,account,state,expires,preview) VALUES (?,?,'PREVIEW',?,?)",
                       (p["batchId"], p["accountSeq"], p["expiresTimestamp"], json.dumps(p)))
        return p

    def _row(self, batch_id):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
        if row is None:
            raise ValueError("분할 주문을 찾을 수 없습니다.")
        return row

    def batch_status(self, batch_id):
        # A dead process is never resumed automatically. An uncertain child is retained.
        with self.store.connect(write=True) as db:
            db.execute("UPDATE batches SET state='INTERRUPTED',message=? WHERE id=? AND state IN ('RUNNING','STOPPING') AND heartbeat<?",
                       ("실행 프로세스가 중단되었습니다. 토스증권 주문 내역을 대조해 주세요. 자동 재전송하지 않습니다.", batch_id, self.clock()-180))
        row = self._row(batch_id)
        with self.store.connect() as db:
            children = db.execute("SELECT * FROM batch_children WHERE batch_id=? ORDER BY sequence DESC LIMIT 20", (batch_id,)).fetchall()
        return {"batchId": batch_id, "state": row["state"], "preview": json.loads(row["preview"]),
                "submittedOrderCount": row["completed_count"], "submittedAmount": row["submitted_amount"],
                "submittedQuantity": row["submitted_quantity"], "message": row["message"],
                "orders": [{"sequence": c["sequence"], "state": c["state"], "payload": json.loads(c["payload"]),
                            "result": json.loads(c["result"]) if c["result"] else None} for c in reversed(children)]}

    def batch_history(self):
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM batches WHERE state!='PREVIEW' ORDER BY rowid DESC LIMIT 30")]
        return [self.batch_status(batch_id) for batch_id in ids]

    def start_batch(self, batch_id, confirmation=None, *, acknowledged=False, background=True):
        if acknowledged is not True:
            raise ValueError("시장가·다건 주문·수수료 안내를 확인해 주세요.")
        row = self._row(batch_id)
        p = json.loads(row["preview"])
        if confirmation is not None and confirmation != p["confirmationText"]:
            raise ValueError("최종 확인 문구가 일치하지 않습니다.")
        if row["state"] != "PREVIEW":
            return self.batch_status(batch_id)  # Idempotent start, even after restart.
        if not self.execution_mode()["executionEnabled"]:
            raise PermissionError("미리보기 전용입니다. 실주문 모드를 켜 주세요.")
        price = self._price(p["symbol"])
        self._resource_check(p, amount=Decimal(p["totalOrderAmount"]),
                             quantity=Decimal(p["targetQuantity"]) if p["exactQuantity"] else None, price=price)
        owner = uuid.uuid4().hex
        claimed = False
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT state,expires FROM batches WHERE id=?", (batch_id,)).fetchone()
            if current["state"] == "PREVIEW":
                mode = self.store.mode(db, self.settings.execution_enabled)
                if not mode["executionEnabled"]:
                    raise PermissionError("실주문이 꺼졌습니다.")
                if mode["modeRevision"] != p["modeRevision"] or current["expires"] <= self.clock():
                    raise ValueError("미리보기가 만료되었거나 모드가 변경되었습니다. 다시 확인해 주세요.")
                self.store.assert_no_active_batch(db, row["account"])
                if db.execute("SELECT 1 FROM orders WHERE account=? AND state IN ('SUBMITTING','UNKNOWN')", (row["account"],)).fetchone():
                    raise UnknownOrderError("확인되지 않은 이전 주문이 있습니다. 주문 내역을 대조해 주세요.")
                db.execute("UPDATE batches SET state='RUNNING',owner=?,heartbeat=?,message=? WHERE id=?",
                           (owner, self.clock(), "분할 주문을 순서대로 전송합니다.", batch_id))
                claimed = True
        if claimed:
            if background:
                try:
                    Thread(target=self._run_batch, args=(batch_id, owner), daemon=True, name=f"batch-{batch_id[:8]}").start()
                except Exception:
                    self._finish_batch(batch_id, owner, "STOPPED", "실행 작업을 시작하지 못했습니다. 주문은 전송하지 않았습니다.")
                    raise
            else:
                self._run_batch(batch_id, owner)
        return self.batch_status(batch_id)

    def stop_batch(self, batch_id):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE batches SET stop=1,state='STOPPING',message=? WHERE id=? AND state='RUNNING'",
                       ("남은 주문 중단 요청. 이미 전송한 주문은 취소하지 않습니다.", batch_id))
        return self.batch_status(batch_id)

    def _finish_batch(self, batch_id, owner, state, message):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE batches SET state=?,message=?,heartbeat=? WHERE id=? AND owner=?", (state, message, self.clock(), batch_id, owner))

    def _run_batch(self, batch_id, owner):
        try:
            self._run_loop(batch_id, owner)
        except Exception as exc:
            # If a child was reserved but its result not committed, preserve uncertainty.
            with self.store.connect() as db:
                uncertain = db.execute("SELECT 1 FROM batch_children WHERE batch_id=? AND state IN ('SUBMITTING','UNKNOWN')", (batch_id,)).fetchone()
            message = str(exc) if isinstance(exc, (TradingError, ValueError, PermissionError)) else "처리 오류가 발생했습니다. 주문 내역을 확인해 주세요."
            self._finish_batch(batch_id, owner, "UNKNOWN" if uncertain else "STOPPED", message)

    def _run_loop(self, batch_id, owner):
        while True:
            row = self._row(batch_id)
            if row["owner"] != owner or row["state"] not in {"RUNNING", "STOPPING"}:
                return
            p = json.loads(row["preview"])
            qty_mode = p["exactQuantity"]
            remaining = (Decimal(p["targetQuantity"]) - Decimal(row["submitted_quantity"])) if qty_mode else (Decimal(p["totalOrderAmount"]) - Decimal(row["submitted_amount"]))
            if remaining <= 0:
                self._finish_batch(batch_id, owner, "SUBMITTED", "모든 분할 주문을 접수했습니다. 체결 완료 여부는 토스증권 주문 내역에서 확인해 주세요.")
                return
            mode = self.execution_mode()
            if row["stop"] or not mode["executionEnabled"] or mode["modeRevision"] != p["modeRevision"]:
                self._finish_batch(batch_id, owner, "STOPPED", "남은 주문을 중단했습니다. 이미 접수된 주문은 유지됩니다.")
                return
            with self.store.connect(write=True) as db:
                db.execute("UPDATE batches SET heartbeat=? WHERE id=? AND owner=?", (self.clock(), batch_id, owner))
            price = self._price(p["symbol"]) if p["side"] == "SELL" else None
            quantity = min(remaining, (CHUNK/price).quantize(SHARE_STEP, rounding=ROUND_DOWN)) if qty_mode else None
            if qty_mode and quantity <= 0:
                raise ValueError("현재가에서 $9 이하의 최소 소수점 수량을 주문할 수 없습니다.")
            amount = (quantity * price) if qty_mode else min(remaining, CHUNK)
            self._resource_check(p, amount=amount, quantity=quantity, price=price)
            sequence = row["completed_count"] + 1
            payload = {"clientOrderId": "bt-" + uuid.uuid5(uuid.UUID(batch_id), str(sequence)).hex,
                       "symbol": p["symbol"], "side": p["side"], "orderType": "MARKET", "confirmHighValueOrder": False}
            payload.update({"quantity": format(quantity, 'f')} if qty_mode else {"orderAmount": f"{amount:.2f}"})
            # The mode/stop gate and child reservation are one transaction.
            with self.store.connect(write=True) as db:
                current = db.execute("SELECT state,stop,owner FROM batches WHERE id=?", (batch_id,)).fetchone()
                mode = self.store.mode(db, self.settings.execution_enabled)
                if current["owner"] != owner or current["state"] not in {"RUNNING", "STOPPING"}:
                    return
                if current["stop"] or not mode["executionEnabled"] or mode["modeRevision"] != p["modeRevision"]:
                    db.execute("UPDATE batches SET state='STOPPED',message=? WHERE id=?", ("남은 주문을 중단했습니다.", batch_id))
                    return
                db.execute("INSERT INTO batch_children VALUES (?,?,'SUBMITTING',?,NULL)", (batch_id, sequence, json.dumps(payload)))
                db.execute("UPDATE batches SET heartbeat=? WHERE id=?", (self.clock(), batch_id))
            try:
                result = self._broker().create_order(p["accountSeq"], payload)
                if not isinstance(result, dict) or not isinstance(result.get("orderId"), str) or not result["orderId"]:
                    raise TradingError("주문 번호가 응답에 없습니다.")
            except Exception as exc:
                rejected = isinstance(exc, ApiError) and 400 <= exc.status < 500 and exc.status not in {408,409}
                message = str(exc) if isinstance(exc, TradingError) else "주문 응답을 확인하지 못했습니다. 자동 재전송하지 않습니다."
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE batch_children SET state=?,result=? WHERE batch_id=? AND sequence=?",
                               ("REJECTED" if rejected else "UNKNOWN", json.dumps({"message": message}), batch_id, sequence))
                    db.execute("UPDATE batches SET state=?,message=?,heartbeat=? WHERE id=?",
                               ("REJECTED" if rejected else "UNKNOWN", message, self.clock(), batch_id))
                return
            with self.store.connect(write=True) as db:
                db.execute("UPDATE batch_children SET state='SUBMITTED',result=? WHERE batch_id=? AND sequence=?", (json.dumps(result), batch_id, sequence))
                db.execute("UPDATE batches SET completed_count=?,submitted_amount=?,submitted_quantity=?,heartbeat=? WHERE id=? AND owner=?",
                           (sequence, str(Decimal(row["submitted_amount"])+amount),
                            str(Decimal(row["submitted_quantity"])+(quantity or Decimal(0))), self.clock(), batch_id, owner))
            self.sleeper(self.interval)
