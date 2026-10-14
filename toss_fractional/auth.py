# Extracted from PYTON_FINAL_EXAM/clients/toss_auth_client.py.
# Stdlib HTTP adapter; original shared-cache locking and 401 recovery preserved.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os

from .http import HttpSession, HttpResponse
from .errors import ApiError, TradingError
import time


TOSS_BASE_URL = "https://openapi.tossinvest.com"


class _TokenFileLock:
    """
    Small cross-process file lock used only for Toss OAuth issuance.

    This prevents the backend and market-data worker from issuing
    different access tokens for the same Toss client at the same time.
    """

    def __init__(self, path: Path | None, timeout_seconds: float = 20.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.stream = None

    def __enter__(self) -> "_TokenFileLock":
        if self.path is None:
            return self

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")

        self.stream.seek(0, os.SEEK_END)

        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()

        self.stream.seek(0)

        if os.name == "nt":
            import msvcrt

            deadline = time.monotonic() + self.timeout_seconds

            while True:
                try:
                    msvcrt.locking(
                        self.stream.fileno(),
                        msvcrt.LK_NBLCK,
                        1,
                    )
                    break

                except OSError:
                    if time.monotonic() >= deadline:
                        self.stream.close()
                        self.stream = None
                        raise TimeoutError(
                            f"Timed out waiting for Toss token lock: {self.path}"
                        )

                    time.sleep(0.05)

        else:
            import fcntl

            fcntl.flock(
                self.stream.fileno(),
                fcntl.LOCK_EX,
            )

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.stream is None:
            return

        try:
            self.stream.seek(0)

            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(
                        self.stream.fileno(),
                        msvcrt.LK_UNLCK,
                        1,
                    )
                except OSError:
                    pass

            else:
                import fcntl

                try:
                    fcntl.flock(
                        self.stream.fileno(),
                        fcntl.LOCK_UN,
                    )
                except OSError:
                    pass

        finally:
            self.stream.close()
            self.stream = None



@dataclass
class TossToken:
    access_token: str = field(repr=False)
    token_type: str
    expires_at: datetime

    @property
    def is_valid(self) -> bool:
        return bool(self.access_token) and datetime.now(timezone.utc) < self.expires_at - timedelta(seconds=60)


class TossAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = TOSS_BASE_URL,
        cache_path: Path | None = None,
        session: HttpSession | None = None,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.base_url = base_url.rstrip("/")
        self.cache_path = cache_path
        self.lock_path = (
            cache_path.with_suffix(cache_path.suffix + ".lock")
            if cache_path
            else None
        )
        self.session = session or HttpSession()
        self._token: TossToken | None = None

    def get_access_token(self, force_refresh: bool = False) -> str:
        # Fast path for the normal case.
        if not force_refresh:
            token = self._token or self._load_cached_token()

            if token and token.is_valid:
                self._token = token
                return token.access_token

        if not self.client_id or not self.client_secret:
            raise TradingError(
                "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET must be configured."
            )

        # Only one process may decide to issue a new Toss token at a time.
        #
        # After obtaining the lock, re-read the shared cache because
        # another process may have refreshed it while we were waiting.
        with _TokenFileLock(self.lock_path):
            cached = self._load_cached_token()

            if cached and cached.is_valid:
                self._token = cached
                return cached.access_token

            token = self._request_token()
            self._save_cached_token(token)
            self._token = token

            return token.access_token

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.get_access_token()}"}

    def recover_access_token(self, rejected_token: str | None = None) -> str:
        """
        Recover after an HTTP 401 without immediately issuing a new token.

        Another process may already have replaced the Toss token. First
        reload the shared cache. Only issue a new token under the shared
        lock when the cached token is still the token that was rejected.
        """
        self._token = None

        cached = self._load_cached_token()

        if (
            cached
            and cached.is_valid
            and cached.access_token != rejected_token
        ):
            self._token = cached
            return cached.access_token

        if not self.client_id or not self.client_secret:
            raise TradingError(
                "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET must be configured."
            )

        with _TokenFileLock(self.lock_path):
            # Re-read after acquiring the lock. Another process may have
            # refreshed the token while this process was waiting.
            cached = self._load_cached_token()

            if (
                cached
                and cached.is_valid
                and cached.access_token != rejected_token
            ):
                self._token = cached
                return cached.access_token

            token = self._request_token()
            self._save_cached_token(token)
            self._token = token

            return token.access_token

    def _request_token(self) -> TossToken:
        response = self.session.post(
            f"{self.base_url}/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        if int(getattr(response, "status_code", 200)) >= 400:
            raise ApiError(response.status_code, "oauth-token-error")

        payload = response.json()
        expires_in = int(payload.get("expires_in") or 0)
        if not payload.get("access_token") or expires_in <= 0:
            raise TradingError("Toss OAuth 응답에 access_token 또는 expires_in이 없습니다.")
        return TossToken(
            access_token=str(payload["access_token"]),
            token_type=str(payload.get("token_type") or "Bearer"),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )

    def _load_cached_token(self) -> TossToken | None:
        if not self.cache_path or not self.cache_path.exists():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return TossToken(
                access_token=str(payload["access_token"]),
                token_type=str(payload.get("token_type") or "Bearer"),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            )
        except Exception:
            return None

    def _save_cached_token(self, token: TossToken) -> None:
        if not self.cache_path:
            return

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(
            {
                "access_token": token.access_token,
                "token_type": token.token_type,
                "expires_at": token.expires_at.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )

        temporary = self.cache_path.parent / (
            f".{self.cache_path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )

        old_umask = os.umask(0o077)

        try:
            temporary.write_text(
                payload,
                encoding="utf-8",
            )

            last_error: OSError | None = None

            for attempt in range(6):
                try:
                    os.replace(
                        temporary,
                        self.cache_path,
                    )
                    return

                except (PermissionError, OSError) as exc:
                    last_error = exc

                    if attempt >= 5:
                        break

                    time.sleep(0.05 * (attempt + 1))

            if last_error is not None:
                raise last_error

        finally:
            os.umask(old_umask)

            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
