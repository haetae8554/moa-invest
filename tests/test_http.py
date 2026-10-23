from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

from toss_fractional.errors import NetworkError
from toss_fractional.http import HttpSession


class HttpLimitTests(TestCase):
    def response(self, raw):
        response = BytesIO(raw)
        response.status = 200
        response.headers = {}
        return response

    def test_size_limit_accepts_boundary_and_rejects_oversize_without_full_read(self):
        for raw, oversized in [(b'1234', False), (b'123456789', True)]:
            response = self.response(raw)
            with patch('toss_fractional.http.build_opener') as opener:
                opener.return_value.open.return_value = response
                with patch.object(response, 'read', wraps=response.read) as read:
                    if oversized:
                        with self.assertRaises(NetworkError):
                            HttpSession().get('https://example.test', max_response_bytes=4)
                    else:
                        self.assertEqual(HttpSession().get('https://example.test', max_response_bytes=4).text, '1234')
                    read.assert_called_once_with(5)
            self.assertTrue(response.closed)

    def test_http_error_body_has_same_limit_and_closes_connection(self):
        body = BytesIO(b'123456789')
        error = HTTPError('https://example.test', 403, 'Forbidden', {}, body)
        with patch('toss_fractional.http.build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(NetworkError):
                HttpSession().get('https://example.test', max_response_bytes=4)
        self.assertTrue(body.closed)

    def test_existing_unbounded_transport_behavior_is_preserved(self):
        response = self.response(b'{"ok":true}')
        with patch('toss_fractional.http.build_opener', return_value=SimpleNamespace(open=lambda *a, **kw: response)):
            self.assertEqual(HttpSession().get('https://example.test').json(), {'ok': True})
