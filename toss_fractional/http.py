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
    def request(self, method, url, *, headers=None, params=None, data=None, json=None, timeout=20,
                max_response_bytes=None):
        if max_response_bytes is not None and (type(max_response_bytes) is not int or max_response_bytes <= 0):
            raise ValueError("응답 크기 제한이 올바르지 않습니다.")

        def read(response):
            raw = response.read() if max_response_bytes is None else response.read(max_response_bytes + 1)
            if max_response_bytes is not None and len(raw) > max_response_bytes:
                raise NetworkError("외부 응답이 허용된 크기를 초과했습니다.")
            return raw

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
                return HttpResponse(response.status, read(response).decode("utf-8"), dict(response.headers))
        except HTTPError as exc:
            with exc:
                return HttpResponse(exc.code, read(exc).decode("utf-8", errors="replace"), dict(exc.headers))
        except (URLError, OSError, TimeoutError):
            raise NetworkError("Toss API 연결이 끊겼거나 응답 시간이 초과되었습니다.") from None

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)
