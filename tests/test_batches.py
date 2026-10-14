from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from toss_fractional import Settings, FractionalTradeService, ApiError, UnknownOrderError
from toss_fractional.errors import NetworkError
from test_orders import FakeBroker


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.settings = Settings(data_dir=Path(self.temp.name), execution_enabled=True)
        self.broker = FakeBroker(); self.broker.cash = '100000'
        self.now = 1800000000.0
        self.service = FractionalTradeService(self.broker, self.settings, clock=lambda:self.now, interval=0)

    def plan(self, value='28', **kwargs):
        return self.service.preview_batch('AAPL', value, **kwargs)

    def start(self, p, service=None):
        return (service or self.service).start_batch(p['batchId'], p['confirmationText'], acknowledged=True, background=False)

    def test_buy_and_sell_amount_exact_remainder(self):
        for side in ('BUY', 'SELL'):
            with self.subTest(side=side):
                self.broker.calls.clear(); p = self.plan(side=side)
                self.assertEqual(p['split']['orderCount'], 4)
                self.assertFalse(self.broker.calls)
                result = self.start(p)
                payloads = [p for _,p in self.broker.calls]
                self.assertEqual([p['orderAmount'] for p in payloads], ['9.00','9.00','9.00','1.00'])
                self.assertTrue(all(p['side'] == side and 'quantity' not in p for p in payloads))
                self.assertEqual(len({p['clientOrderId'] for p in payloads}), 4)
                self.assertTrue(all(len(p['clientOrderId']) <= 36 for p in payloads))
                self.assertEqual(result['state'], 'SUBMITTED')
                self.assertEqual(Decimal(result['submittedAmount']), Decimal(28))

    def test_buy_quantity_converts_to_fixed_budget(self):
        p = self.plan('0.1', basis='QUANTITY')
        self.assertEqual(Decimal(p['totalOrderAmount']), Decimal(20))
        self.assertFalse(p['exactQuantity'])
        self.broker.price = '250'  # Budget remains what the user confirmed.
        self.start(p)
        self.assertEqual([r['orderAmount'] for _,r in self.broker.calls], ['9.00','9.00','2.00'])
        self.assertTrue(all('quantity' not in r for _,r in self.broker.calls))

    def test_sell_quantity_requotes_without_overselling(self):
        p = self.plan('0.1', side='SELL', basis='QUANTITY')
        prices = iter(['200','250','300'])
        used_prices = []
        def next_price(_):
            self.broker.price = next(prices, '300')
        self.service.sleeper = next_price
        original = self.broker.create_order
        def send(account, payload):
            used_prices.append(Decimal(self.broker.price))
            return original(account, payload)
        self.broker.create_order = send
        result = self.start(p)
        quantities = [Decimal(r['quantity']) for _,r in self.broker.calls]
        self.assertEqual(sum(quantities), Decimal('0.1'))
        self.assertTrue(all(q*price <= 9 for q,price in zip(quantities,used_prices)))
        self.assertTrue(all('orderAmount' not in r for _,r in self.broker.calls))
        self.assertEqual(Decimal(result['submittedQuantity']), Decimal('0.1'))

    def test_sell_quantity_rounds_each_child_down_to_six_places(self):
        self.broker.price = '317.13'
        p = self.plan('0.123456', side='SELL', basis='QUANTITY')
        self.start(p)
        qtys = [Decimal(r['quantity']) for _,r in self.broker.calls]
        self.assertEqual(sum(qtys), Decimal('0.123456'))
        self.assertTrue(all(q*Decimal('317.13') <= 9 and q.as_tuple().exponent >= -6 for q in qtys))

    def test_more_than_old_daily_cap_and_no_max_order_count(self):
        p = self.plan('2000')
        self.assertEqual(p['split']['orderCount'], 223)
        result = self.start(p)
        self.assertEqual(result['submittedOrderCount'], 223)
        self.assertEqual(Decimal(result['submittedAmount']), Decimal(2000))

    def test_compact_large_preview(self):
        self.broker.cash = '1000000000'
        p = self.plan('1000000000')
        self.assertEqual(p['split']['orderCount'], 111111112)
        self.assertNotIn('orders', p)

    def test_invalid_inputs(self):
        for value in ['0', '-1', 'NaN', 'Infinity', True, None, '0.001']:
            with self.subTest(value=value), self.assertRaises(ValueError): self.plan(value)
        for value in ['0', '-1', 'NaN', '0.0000001']:
            with self.assertRaises(ValueError): self.plan(value,basis='QUANTITY')
        for kwargs in ({'side':[]}, {'basis':{}}, {'side':'OTHER'}, {'basis':'OTHER'}):
            with self.assertRaises(ValueError): self.plan(**kwargs)
        self.assertFalse(self.broker.calls)

    def test_sellable_and_balance_rechecked(self):
        p = self.plan(); self.broker.cash = '1'
        with self.assertRaises(ValueError): self.start(p)
        self.broker.sellable = '0.001'
        with self.assertRaises(ValueError): self.plan(side='SELL')
        self.broker.sellable = '1'; p = self.plan('0.1',side='SELL',basis='QUANTITY')
        self.broker.sellable = '0.05'
        with self.assertRaises(ValueError): self.start(p)
        self.assertFalse(self.broker.calls)

    def test_duplicate_start_across_instances_survives_restart(self):
        p = self.plan()
        restarted = FractionalTradeService(self.broker,self.settings,interval=0,clock=lambda:self.now)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _:self.start(p,restarted),range(4)))
        self.assertEqual(len(self.broker.calls), 4)
        self.assertEqual(self.start(p)['state'], 'SUBMITTED')
        self.assertEqual(len(self.broker.calls), 4)

    def test_partial_timeout_never_retries_and_blocks_account(self):
        p = self.plan()
        def after_first(_): self.broker.failure = NetworkError('timeout')
        self.service.sleeper = after_first
        result = self.start(p)
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertEqual(result['submittedOrderCount'], 1)
        self.assertEqual(len(self.broker.calls), 2)
        self.start(p); self.assertEqual(len(self.broker.calls), 2)
        with self.assertRaises(ValueError): self.start(self.plan())
        legacy = self.service.preview('AAPL','5')
        with self.assertRaises(ValueError): self.service.submit(legacy['previewId'],legacy['confirmationText'],acknowledged=True)

    def test_rejection_stops_rest_of_batch(self):
        self.broker.failure = ApiError(422, 'outside-hours')
        result = self.start(self.plan())
        self.assertEqual(result['state'], 'REJECTED')
        self.assertEqual(len(self.broker.calls), 1)

    def test_explicit_stop_and_mode_off_stop_after_first(self):
        for stop_mode in (False, True):
            self.broker.calls.clear()
            if not self.service.execution_mode()['executionEnabled']:
                self.service.set_execution_mode(True,self.service.execution_mode()['modeRevision'])
            p = self.plan()
            def stop(_):
                if stop_mode: self.service.set_execution_mode(False,self.service.execution_mode()['modeRevision'])
                else: self.service.stop_batch(p['batchId'])
            self.service.sleeper = stop
            result = self.start(p)
            self.assertEqual(result['state'], 'STOPPED')
            self.assertEqual(len(self.broker.calls), 1)

    def test_expired_and_changed_mode_previews_do_not_start(self):
        p = self.plan(); self.now += 121
        with self.assertRaises(ValueError): self.start(p)
        p = self.plan(); self.service.set_execution_mode(False,0)
        with self.assertRaises(PermissionError): self.start(p)
        self.service.set_execution_mode(True,1)
        with self.assertRaises(ValueError): self.start(p)
        self.assertFalse(self.broker.calls)

    def test_typed_confirmation_is_optional_but_ack_is_mandatory(self):
        p = self.plan()
        with self.assertRaises(ValueError): self.service.start_batch(p['batchId'], 'wrong', acknowledged=True)
        for ack in (False, 1, 'true'):
            with self.assertRaises(ValueError): self.service.start_batch(p['batchId'],p['confirmationText'],acknowledged=ack)
        self.assertFalse(self.broker.calls)
        result = self.service.start_batch(p['batchId'],acknowledged=True,background=False)
        self.assertEqual(result['state'],'SUBMITTED')

    def test_crash_is_interrupted_and_never_resumed(self):
        p = self.plan()
        with self.service.store.connect(write=True) as db:
            db.execute("UPDATE batches SET state='RUNNING',owner='dead',heartbeat=? WHERE id=?",(self.now-181,p['batchId']))
        self.assertEqual(self.start(p)['state'], 'INTERRUPTED')
        with self.assertRaises(ValueError): self.start(self.plan())
        self.assertFalse(self.broker.calls)

    def test_unresolved_legacy_order_blocks_batch(self):
        p = self.service.preview('AAPL','5')
        with self.service.store.connect(write=True) as db:
            db.execute("UPDATE orders SET state='SUBMITTING' WHERE preview_id=?",(p['previewId'],))
        with self.assertRaises(UnknownOrderError): self.start(self.plan())
        self.assertFalse(self.broker.calls)

    def test_mode_off_during_child_resource_check_never_sends(self):
        p = self.plan()
        original = self.broker.get_buying_power; count = 0
        def balance(account, currency='USD'):
            nonlocal count
            count += 1
            if count == 2: self.service.set_execution_mode(False,0)
            return original(account,currency)
        self.broker.get_buying_power = balance
        self.assertEqual(self.start(p)['state'], 'STOPPED')
        self.assertFalse(self.broker.calls)

    def test_distinct_batch_cannot_overlap_inflight_order(self):
        p, second = self.plan(), self.plan()
        entered, release = Event(), Event()
        original = self.broker.create_order
        def send(account,payload):
            entered.set(); release.wait(5)
            return original(account,payload)
        self.broker.create_order = send
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.start,p)
            try:
                self.assertTrue(entered.wait(5))
                with self.assertRaises(ValueError): self.start(second)
            finally: release.set()
            self.assertEqual(future.result()['state'], 'SUBMITTED')


if __name__ == '__main__': unittest.main()
