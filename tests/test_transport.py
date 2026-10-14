import json
import unittest
from unittest.mock import patch

from toss_fractional.client import TossClient
from toss_fractional.errors import ApiError, NetworkError
from toss_fractional.http import HttpResponse


class FakeAuth:
    def __init__(self): self.recoveries = 0
    def get_access_token(self): return "test-token"
    def recover_access_token(self, rejected_token=None):
        self.recoveries += 1
        return "recovered-test-token"


class Session:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return response


def response(status, data=None):
    return HttpResponse(status, json.dumps(data or {"result":{"orderId":"test-order"}}), {})


class TransportTests(unittest.TestCase):
    def test_holdings_endpoint_uses_selected_account(self):
        session = Session([response(200, {"result":{"items":[]}})])
        result = TossClient(FakeAuth(),session).get_holdings("7")
        args, kwargs = session.calls[0]
        self.assertEqual(args[0], "GET")
        self.assertTrue(args[1].endswith('/api/v1/holdings'))
        self.assertEqual(kwargs['headers']['X-Tossinvest-Account'],'7')
        self.assertEqual(result,{'items':[]})

    def test_sellable_quantity_endpoint_and_account(self):
        session = Session([response(200, {"result":{"sellableQuantity":"0.123456"}})])
        result = TossClient(FakeAuth(),session).get_sellable_quantity("7","AAPL")
        args, kwargs = session.calls[0]
        self.assertEqual(args[0], "GET")
        self.assertTrue(args[1].endswith('/api/v1/sellable-quantity'))
        self.assertEqual(kwargs['params'], {'symbol':'AAPL'})
        self.assertEqual(kwargs['headers']['X-Tossinvest-Account'],'7')
        self.assertEqual(result['sellableQuantity'],'0.123456')

    def test_order_post_not_retried_for_429_or_500(self):
        for status in (429, 500):
            session = Session([response(status)])
            client = TossClient(FakeAuth(), session)
            with self.assertRaises(ApiError): client.create_order("1", {})
            self.assertEqual(len(session.calls), 1)

    def test_order_post_not_retried_on_network_error(self):
        session = Session([NetworkError("timeout")])
        with self.assertRaises(NetworkError): TossClient(FakeAuth(), session).create_order("1", {})
        self.assertEqual(len(session.calls), 1)

    def test_explicit_401_recovers_once_and_preserves_order(self):
        auth = FakeAuth(); session = Session([response(401), response(200)])
        payload = {"clientOrderId":"fixed-id", "orderAmount":"5.00"}
        TossClient(auth, session).create_order("7", payload)
        self.assertEqual(auth.recoveries, 1)
        self.assertEqual(session.calls[0][1]["json"], session.calls[1][1]["json"])
        self.assertEqual(session.calls[1][1]["headers"]["X-Tossinvest-Account"], "7")

    def test_repeated_401_does_not_loop(self):
        auth = FakeAuth(); session = Session([response(401), response(401)])
        with self.assertRaises(ApiError): TossClient(auth, session).create_order("1", {})
        self.assertEqual(auth.recoveries, 1)

    @patch("toss_fractional.client.time.sleep")
    def test_read_429_retries_are_bounded(self, sleep):
        session = Session([response(429), response(429), response(429)])
        with self.assertRaises(ApiError): TossClient(FakeAuth(), session).get_prices(["AAPL"])
        self.assertEqual(len(session.calls), 3)

    def test_error_response_does_not_expose_raw_secret(self):
        session = Session([response(500, {"error":{"message":"test-private-token", "code":"server-error"}})])
        with self.assertRaises(ApiError) as error: TossClient(FakeAuth(), session).get_prices(["AAPL"])
        self.assertNotIn("test-private-token", str(error.exception))


if __name__ == "__main__": unittest.main()
