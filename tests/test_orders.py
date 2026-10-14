from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import json
import unittest

from toss_fractional import Settings, FractionalBuyService, ApiError, UnknownOrderError
from toss_fractional.errors import NetworkError


class FakeBroker:
    """Test-only broker. This is never available to the production UI or CLI."""
    def __init__(self):
        self.accounts = [{"accountSeq": "1", "accountType": "BROKERAGE", "accountNo": "12345678"}]
        self.stock = {"symbol": "AAPL", "name": "애플", "currency": "USD", "status": "ACTIVE"}
        self.cash = "100.00"
        self.price = "200.00"
        self.sellable = "100"
        self.holdings_data = {"items":[{"symbol":"AAPL", "name":"애플", "marketCountry":"US", "currency":"USD", "quantity":"0.1", "lastPrice":"200", "averagePurchasePrice":"210", "marketValue":{"purchaseAmount":"21", "amount":"20"}, "profitLoss":{"amount":"-1", "rate":"0.99"}}]}
        self.calls = []
        self.failure = None
        self.lock = Lock()

    def list_accounts(self): return self.accounts
    def get_stocks(self, symbols): return [self.stock]
    def get_prices(self, symbols): return [{"symbol": "AAPL", "lastPrice": self.price}]
    def get_buying_power(self, account, currency="USD"): return {"cashBuyingPower": self.cash}
    def get_stock_warnings(self, symbol): return []
    def get_sellable_quantity(self, account, symbol): return {"sellableQuantity": self.sellable}
    def get_holdings(self, account): return self.holdings_data
    def get_commissions(self, account): return [{"marketCountry": "US", "commissionRate": "0.001"}]
    def list_orders(self, account, status="OPEN"): return {"orders": []}

    def create_order(self, account, payload):
        with self.lock:
            self.calls.append((account, payload))
        if self.failure:
            raise self.failure
        return {"orderId": "test-order", "clientOrderId": payload["clientOrderId"]}


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(data_dir=Path(self.temp.name), execution_enabled=True)
        self.broker = FakeBroker()
        self.now = 1800000000.0
        self.service = FractionalBuyService(self.broker, self.settings, clock=lambda: self.now)

    def preview(self, amount="5.00"):
        return self.service.preview("aapl", amount)

    def submit(self, preview, service=None):
        return (service or self.service).submit(preview["previewId"], preview["confirmationText"], acknowledged=True)

    def test_exact_fractional_wire_payload_and_receipt(self):
        p = self.preview()
        self.assertEqual(p["estimatedQuantity"], "0.025000")
        self.assertEqual(self.broker.calls, [])
        result = self.submit(p)
        self.assertEqual(result["state"], "SUBMITTED")
        self.assertEqual(self.broker.calls[0], ("1", {"clientOrderId":p["clientOrderId"], "symbol":"AAPL",
                         "side":"BUY", "orderType":"MARKET", "orderAmount":"5.00", "confirmHighValueOrder":False}))
        self.assertLessEqual(len(p["clientOrderId"]), 36)

    def test_disabled_execution_never_calls_broker(self):
        service = FractionalBuyService(self.broker, replace(self.settings, execution_enabled=False))
        p = service.preview("AAPL", "1")
        with self.assertRaises(PermissionError): self.submit(p, service)
        self.assertEqual(self.broker.calls, [])

    def test_invalid_amounts_never_create_orders(self):
        for amount in ["NaN", "Infinity", "-1", "0", "0.001", "5.555", "10", "abc", None, True]:
            with self.subTest(amount=amount), self.assertRaises(ValueError): self.preview(amount)
        self.assertEqual(self.broker.calls, [])

    def test_accepts_minimum_and_maximum_without_rounding(self):
        self.assertEqual(self.preview("0.01")["orderAmount"], "0.01")
        self.assertEqual(self.preview("9.99")["orderAmount"], "9.99")

    def test_invalid_symbol_and_stock(self):
        for symbol in ["AAPL/../", "", None, "애플"]:
            with self.assertRaises(ValueError): self.service.preview(symbol, "1")
        for key, value in [("currency", "KRW"), ("status", "INACTIVE")]:
            previous = self.broker.stock[key]
            self.broker.stock[key] = value
            with self.assertRaises(ValueError): self.preview()
            self.broker.stock[key] = previous

    def test_confirmation_and_strict_acknowledgement(self):
        p = self.preview()
        with self.assertRaises(ValueError): self.service.submit(p["previewId"], "wrong", acknowledged=True)
        for value in [False, "false", "true", 1]:
            with self.assertRaises(ValueError): self.service.submit(p["previewId"], p["confirmationText"], acknowledged=value)
        self.assertEqual(self.broker.calls, [])

    def test_expired_preview_never_sends(self):
        p = self.preview(); self.now += 121
        with self.assertRaises(ValueError): self.submit(p)
        self.assertEqual(self.broker.calls, [])

    def test_insufficient_cash_is_rechecked(self):
        p = self.preview(); self.broker.cash = "1.00"
        with self.assertRaises(ValueError): self.submit(p)
        self.assertEqual(self.broker.calls, [])

    def test_repeated_submit_survives_service_restart(self):
        p = self.preview(); original = self.submit(p)
        restarted = FractionalBuyService(self.broker, self.settings, clock=lambda: self.now)
        self.assertEqual(self.submit(p, restarted), original)
        self.assertEqual(len(self.broker.calls), 1)

    def test_concurrent_same_preview_sends_at_most_once(self):
        p = self.preview()
        def send():
            try: return self.submit(p)
            except UnknownOrderError: return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda _: send(), range(6)))
        self.assertEqual(len(self.broker.calls), 1)

    def test_repeated_orders_have_no_daily_cap(self):
        for _ in range(21):
            self.submit(self.preview("5"))
        self.assertEqual(len(self.broker.calls), 21)
        self.assertNotIn("dailyOrderLimitUSD", self.service.setup())

    def test_timeout_blocks_retries_and_fresh_previews_after_restart(self):
        p = self.preview(); self.broker.failure = NetworkError("timeout")
        with self.assertRaises(UnknownOrderError): self.submit(p)
        restarted = FractionalBuyService(self.broker, self.settings, clock=lambda: self.now)
        with self.assertRaises(UnknownOrderError): self.submit(p, restarted)
        second = restarted.preview("AAPL", "5")
        with self.assertRaises(UnknownOrderError): self.submit(second, restarted)
        self.assertEqual(len(self.broker.calls), 1)
        self.assertEqual(restarted.balances()["submittedTodayUSD"], "5.00")

    def test_http_500_is_unknown_and_not_retried(self):
        self.broker.failure = ApiError(500)
        with self.assertRaises(UnknownOrderError): self.submit(self.preview())
        self.assertEqual(self.service.store.history()[0]["state"], "UNKNOWN")
        self.assertEqual(len(self.broker.calls), 1)

    def test_explicit_rejection_releases_daily_reservation(self):
        self.broker.failure = ApiError(422, "amount-order-outside-regular-hours")
        with self.assertRaises(ApiError): self.submit(self.preview())
        self.assertEqual(self.service.store.history()[0]["state"], "REJECTED")
        self.assertEqual(self.service.balances()["submittedTodayUSD"], "0.00")

    def test_crash_reservation_blocks_later_order(self):
        p = self.preview()
        with self.service.store.connect(write=True) as db:
            db.execute("UPDATE orders SET state='SUBMITTING' WHERE preview_id=?", (p["previewId"],))
        with self.assertRaises(UnknownOrderError): self.submit(self.preview())
        self.assertEqual(self.broker.calls, [])

    def test_account_must_be_explicit_if_multiple(self):
        self.broker.accounts.append({"accountSeq":"2", "accountType":"BROKERAGE"})
        with self.assertRaises(ValueError): self.preview()
        self.assertEqual(self.service.preview("AAPL", "5", "2")["accountSeq"], "2")
        with self.assertRaises(ValueError): self.service.preview("AAPL", "5", "other")

    def test_no_account_fallback_to_non_brokerage(self):
        self.broker.accounts[0]["accountType"] = "PENSION"
        with self.assertRaises(ValueError): self.preview()

    def test_stricter_limit_after_restart_applies_to_old_preview(self):
        p = self.preview()
        service = FractionalBuyService(self.broker, replace(self.settings, max_order_usd=Decimal("1")))
        with self.assertRaises(ValueError): self.submit(p, service)

    def test_configuration_does_not_leak_credentials(self):
        settings = replace(self.settings, client_id="test-secret-id", client_secret="test-secret-value")
        self.assertNotIn("test-secret", repr(settings))
        self.assertNotIn("test-secret", json.dumps(FractionalBuyService(self.broker, settings).setup()))

    def test_mode_change_persists_and_invalidates_previous_preview(self):
        p = self.preview()
        self.service.set_execution_mode(False, 0)
        restarted = FractionalBuyService(self.broker, self.settings, clock=lambda: self.now)
        self.assertFalse(restarted.setup()["executionEnabled"])
        with self.assertRaises(PermissionError): self.submit(p, restarted)
        restarted.set_execution_mode(True, 1)
        with self.assertRaises(ValueError): self.submit(p, restarted)
        fresh = restarted.preview("AAPL", "5")
        self.submit(fresh, restarted)
        self.assertEqual(len(self.broker.calls), 1)

    def test_mode_off_during_balance_check_blocks_order_reservation(self):
        p = self.preview()
        original = self.broker.get_buying_power
        def change_mode(account, currency="USD"):
            self.service.set_execution_mode(False, 0)
            return original(account, currency)
        self.broker.get_buying_power = change_mode
        with self.assertRaises(PermissionError): self.submit(p)
        self.assertEqual(self.broker.calls, [])

    def test_stale_mode_change_and_non_boolean_rejected(self):
        self.service.set_execution_mode(False, 0)
        with self.assertRaises(ValueError): self.service.set_execution_mode(True, 0)
        for value in ("false", 1, None):
            with self.assertRaises(ValueError): self.service.set_execution_mode(value, 1)
        self.assertFalse(self.service.execution_mode()["executionEnabled"])

    def test_mode_changed_during_preview_requires_new_preview(self):
        original = self.broker.get_commissions
        def change_mode(account):
            self.service.set_execution_mode(False, 0)
            return original(account)
        self.broker.get_commissions = change_mode
        with self.assertRaises(ValueError): self.preview()
        self.assertEqual(self.broker.calls, [])


if __name__ == "__main__": unittest.main()
