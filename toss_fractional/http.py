"""Small stdlib transport. No implicit retries or cross-origin redirects."""
from dataclasses import dataclass
import json as json_module
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, build_opener

from .errors import NetworkError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class HttpResponse:
    status_code: int
    text: str
    headers: dict

    def json(self):
        return json_module.loads(self.text)


class HttpSession:
    def request(self, method, url, *, headers=None, params=None, data=None, json=None, timeout=20):
        if params:
            url += "?" + urlencode(params)
        body = None
        if data is not None:
            body = urlencode(data).encode("utf-8")
        if json is not None:
            body = json_module.dumps(json, allow_nan=False).encode("utf-8")
        request = Request(url, data=body, headers=headers or {}, method=method)
        try:
            with build_opener(_NoRedirect).open(request, timeout=timeout) as response:
                return HttpResponse(response.status, response.read().decode("utf-8"), dict(response.headers))
        except HTTPError as exc:
            return HttpResponse(exc.code, exc.read().decode("utf-8", errors="replace"), dict(exc.headers))
        except (URLError, OSError, TimeoutError):
            raise NetworkError("Toss API 연결이 끊겼거나 응답 시간이 초과되었습니다.") from None

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)
