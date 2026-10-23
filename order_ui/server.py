from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import argparse
import json
import secrets
import webbrowser
from threading import RLock
from toss_fractional.registration import CredentialRegistration
from .extension import EXTENSION_ORIGIN
from .research import ResearchData
from .research_symbols import symbol_relations

from toss_fractional import Settings, TradingError, UnknownOrderError, create_service
from toss_fractional.config import read_env

STATIC = Path(__file__).parent / "static"


def make_server(service, port=8765, registration=None, research=None):
    csrf = secrets.token_urlsafe(32)
    request_lock = RLock()
    registration = registration or CredentialRegistration(service)
    research = research or ResearchData()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # No financial data or request bodies in access logs.

        def respond(self, status, data, content_type="application/json; charset=utf-8"):
            raw = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            embedded = urlsplit(self.path).path == "/panel"
            if not embedded:
                self.send_header("X-Frame-Options", "DENY")
            ancestors = EXTENSION_ORIGIN if embedded else "'none'"
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", f"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors {ancestors}; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def trusted(self, mutation=False):
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                raise PermissionError("허용되지 않은 호스트입니다.")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                raise PermissionError("동일한 로컬 화면에서 요청해 주세요.")
            if self.path.startswith("/api/") and self.headers.get("X-Requested-With") != "fractional-buy":
                raise PermissionError("로컬 앱 요청 헤더가 필요합니다.")
            if mutation and not secrets.compare_digest(self.headers.get("X-CSRF-Token", ""), csrf):
                raise PermissionError("화면을 새로고침한 뒤 다시 시도해 주세요.")

        def dispatch(self, mutation=False):
            self.trusted(mutation)
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            if mutation:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("JSON 요청이 필요합니다.")
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 8192:
                    raise ValueError("요청 크기가 올바르지 않습니다.")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("JSON 객체가 필요합니다.")
                if url.path == "/api/credentials":
                    if url.query or self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                        raise PermissionError("같은 로컬 화면에서 키를 등록해 주세요.")
                    if set(body) != {"clientId", "clientSecret", "expectedRevision"}:
                        raise ValueError("키 등록 요청 형식을 확인해 주세요.")
                    return registration.save(body["clientId"], body["clientSecret"], body["expectedRevision"])
                if url.path == "/api/execution-mode":
                    return service.set_execution_mode(body.get("enabled"), body.get("expectedRevision"))
                if url.path == "/api/batches/preview":
                    return service.preview_batch(body.get("symbol"), body.get("value"), body.get("accountSeq"), side=body.get("side", "BUY"), basis=body.get("basis", "AMOUNT"))
                if url.path in {"/api/batches/start", "/api/batches/stop"}:
                    if not isinstance(body.get("batchId"), str):
                        raise ValueError("분할 주문 번호가 필요합니다.")
                    if url.path.endswith("/stop"):
                        return service.stop_batch(body["batchId"])
                    return service.start_batch(body["batchId"], body.get("confirmation"), acknowledged=body.get("acknowledged") is True)
                if url.path == "/api/preview":
                    return service.preview(body.get("symbol"), body.get("amount"), body.get("accountSeq"))
                if url.path == "/api/submit":
                    if not isinstance(body.get("previewId"), str) or not isinstance(body.get("confirmation"), str):
                        raise ValueError("미리보기와 확인 문구가 필요합니다.")
                    return service.submit(body["previewId"], body["confirmation"], acknowledged=body.get("acknowledged") is True)
                raise FileNotFoundError
            if url.path == "/api/credentials":
                return {**registration.status(), "csrfToken": csrf}
            if url.path == "/api/launcher-status":
                return {"app": "moa-invest", "launcherProtocol": 1}
            if url.path == "/api/setup":
                return {**service.setup(), "csrfToken": csrf}
            if url.path == "/api/execution-mode":
                return service.execution_mode()
            if url.path == "/api/balances":
                return service.balances(query.get("account", [None])[0])
            if url.path == "/api/holdings":
                return service.holdings(query.get("account", [None])[0])
            if url.path == "/api/research/fear-greed":
                return research.fear(query.get("source", ["auto"])[0])
            if url.path == "/api/research/symbols":
                return symbol_relations()
            if url.path == "/api/research/chart":
                return research.chart(service._broker(), query.get("symbol", [""])[0],
                                      query.get("basis", ["underlying"])[0])
            if url.path == "/api/history":
                return {"items": service.store.history()}
            if url.path == "/api/batches/history":
                return {"items": service.batch_history()}
            if url.path == "/api/batches/status":
                return service.batch_status(query.get("id", [""])[0])
            if url.path == "/api/orders":
                return {"orders": service.orders(query.get("account", [None])[0], query.get("status", ["OPEN"])[0])}
            files = {"/panel": ("index.html", "text/html"), "/panel-bridge.js": ("panel-bridge.js", "text/javascript"), "/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/theme.js": ("theme.js", "text/javascript"), "/styles.css": ("styles.css", "text/css")}
            files["/research.js"] = ("research.js", "text/javascript")
            files["/research.css"] = ("research.css", "text/css")
            if url.path not in files:
                raise FileNotFoundError
            filename, mime = files[url.path]
            self.respond(200, (STATIC / filename).read_bytes(), mime + "; charset=utf-8")
            return None

        def handle_request(self, mutation=False):
            try:
                # A slow holdings/auth request must not delay a user's stop.
                if urlsplit(self.path).path in {"/api/batches/stop", "/api/execution-mode", "/api/launcher-status", "/api/research/fear-greed", "/api/research/chart", "/api/research/symbols"}:
                    data = self.dispatch(mutation)
                else:
                    with request_lock:
                        data = self.dispatch(mutation)
                if data is not None:
                    self.respond(200, data)
            except FileNotFoundError:
                self.respond(404, {"error": "찾을 수 없는 경로입니다."})
            except PermissionError as exc:
                self.respond(403, {"error": str(exc)})
            except UnknownOrderError as exc:
                self.respond(409, {"error": str(exc), "outcomeUnknown": True})
            except (ValueError, TradingError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception:
                self.respond(500, {"error": "처리 중 오류가 발생했습니다. 주문 전송 중이었다면 기록을 먼저 확인해 주세요."})

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request(True)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local fractional buy desk")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    service = create_service(Settings.from_env(read_env(args.env)))
    server = make_server(service, args.port)
    address = f"http://127.0.0.1:{server.server_port}"
    print(f"Fractional Buy Desk: {address}", flush=True)
    if args.open:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
