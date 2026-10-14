from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread, Event
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import unittest

from order_ui.server import make_server
from toss_fractional import FractionalTradeService, Settings
from test_orders import FakeBroker


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.broker = FakeBroker()
        self.service = FractionalTradeService(self.broker, Settings(data_dir=Path(self.temp.name), execution_enabled=True), interval=0)
        self.server = make_server(self.service, 0)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        values = {"X-Requested-With":"fractional-buy"}
        values.update(headers or {})
        if body is not None: values["Content-Type"] = "application/json"
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None, headers=values)
        try: response = urlopen(request, timeout=5)
        except HTTPError as exc: response = exc
        with response:
            data = response.read()
            return response.status, json.loads(data) if "json" in response.headers.get("Content-Type", "") else data

    def test_full_http_flow_and_duplicate_submit(self):
        status, setup = self.request('/api/setup')
        headers = {"X-CSRF-Token":setup["csrfToken"], "Origin":self.url}
        status, preview = self.request('/api/preview', {"symbol":"AAPL", "amount":"5.00", "accountSeq":"1"}, headers)
        self.assertEqual(status, 200)
        body = {"previewId":preview["previewId"], "confirmation":preview["confirmationText"], "acknowledged":True}
        for _ in range(2):
            status, receipt = self.request('/api/submit', body, headers)
            self.assertEqual(status, 200)
            self.assertEqual(receipt["state"], "SUBMITTED")
        self.assertEqual(len(self.broker.calls), 1)

    def test_csrf_origin_and_host_rejected(self):
        _, setup = self.request('/api/setup')
        body = {"symbol":"AAPL", "amount":"5"}
        for headers in [{}, {"X-CSRF-Token":setup["csrfToken"],"Origin":"https://evil.example"},
                        {"X-CSRF-Token":setup["csrfToken"],"Host":"evil.example"}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request('/api/preview', body, headers)[0], 403)
        self.assertEqual(self.broker.calls, [])

    def test_batch_routes_start_stop_and_persist_progress(self):
        _, setup = self.request('/api/setup')
        headers = {"X-CSRF-Token":setup["csrfToken"], "Origin":self.url}
        status, preview = self.request('/api/batches/preview', {"symbol":"AAPL", "value":"28", "side":"SELL", "basis":"AMOUNT"}, headers)
        self.assertEqual(status, 200)
        body = {"batchId":preview["batchId"], "acknowledged":True}
        self.assertEqual(self.request('/api/batches/start',body)[0],403)
        entered, release, finished = Event(), Event(), Event()
        def pause(_): entered.set(); release.wait(5)
        self.service.sleeper = pause
        original = self.service._run_batch
        def run(*args):
            try: original(*args)
            finally: finished.set()
        self.service._run_batch = run
        try:
            self.assertEqual(self.request('/api/batches/start',body,headers)[0],200)
            self.assertTrue(entered.wait(5))
            status, running = self.request('/api/batches/status?id='+preview['batchId'])
            self.assertEqual(running['submittedOrderCount'],1)
            self.assertEqual(self.request('/api/batches/stop',body)[0],403)
            self.assertEqual(self.request('/api/batches/stop',body,headers)[1]['state'],'STOPPING')
        finally:
            release.set(); self.assertTrue(finished.wait(5))
        self.assertEqual(self.request('/api/batches/history')[1]['items'][0]['state'],'STOPPED')
        self.assertEqual(self.request('/api/batches/start',body,headers)[1]['state'],'STOPPED')
        self.assertEqual(len(self.broker.calls),1)
        self.assertEqual(self.request('/theme.js')[0],200)

    def test_holdings_endpoint_is_read_only_and_confirmation_input_removed(self):
        status, result = self.request('/api/holdings?account=1')
        self.assertEqual(status,200)
        self.assertEqual(result['items'][0]['symbol'],'AAPL')
        self.assertEqual(self.request('/api/holdings?account=other')[0],400)
        html=self.request('/')[1]
        self.assertNotIn(b'id="confirmation"',html)
        self.assertIn(b'id="holdings-list"',html)
        self.assertEqual(self.broker.calls,[])

    def test_static_allowlist_hides_env_and_database(self):
        for path in ('/.env', '/data/orders.sqlite3', '/../.env', '/server.py'):
            self.assertEqual(self.request(path)[0], 404)
        status, html = self.request('/')
        self.assertEqual(status, 200)
        self.assertIn(b'order-form', html)

    def test_invalid_json_shape_is_reported(self):
        _, setup = self.request('/api/setup')
        status, error = self.request('/api/preview', ["bad"], {"X-CSRF-Token":setup["csrfToken"]})
        self.assertEqual(status, 400)

    def test_execution_toggle_enforced_and_protected(self):
        _, setup = self.request('/api/setup')
        body = {"enabled":False, "expectedRevision":setup["modeRevision"]}
        self.assertEqual(self.request('/api/execution-mode', body)[0], 403)
        headers = {"X-CSRF-Token":setup["csrfToken"], "Origin":self.url}
        status, mode = self.request('/api/execution-mode', body, headers)
        self.assertEqual(status, 200)
        self.assertFalse(mode["executionEnabled"])
        self.assertFalse(self.request('/api/setup')[1]["executionEnabled"])
        self.assertEqual(self.request('/api/execution-mode')[1], mode)
        self.assertEqual(self.request('/api/execution-mode', {"enabled":"true", "expectedRevision":1}, headers)[0], 400)
        self.assertEqual(self.request('/api/execution-mode', {"enabled":True, "expectedRevision":1}, headers)[0], 200)
        self.assertEqual(self.broker.calls, [])


if __name__ == "__main__": unittest.main()
