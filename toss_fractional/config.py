from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Mapping
import os

from .credentials import resolve_credentials
from .vault import WindowsVault


def money(value, label="금액") -> Decimal:
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > Decimal("1000000000"):
            raise ValueError
        if number != number.quantize(Decimal("0.01")):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label}은 양수이며 소수점 둘째 자리까지 입력해야 합니다.") from None
    return number.quantize(Decimal("0.01"))


def read_env(path: Path | None = None) -> dict[str, str]:
    """Read a simple KEY=value file without mutating the process environment."""
    values = {}
    if path and path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep or not key.strip().startswith("TOSS_"):
                raise ValueError(".env에는 TOSS_로 시작하는 KEY=value 항목만 입력해 주세요.")
            values[key.strip()] = value.strip().strip("\"'")
    values.update(os.environ)
    return values


@dataclass(frozen=True)
class Settings:
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)
    account_seq: str = ""
    execution_enabled: bool = False
    max_order_usd: Decimal = Decimal("9.99")
    data_dir: Path = Path("data")
    token_cache: Path | None = None
    credential_source: str = "직접 설정"
    credential_revision: str = ""

    def __post_init__(self):
        maximum = money(self.max_order_usd, "1회 한도")
        if maximum > Decimal("9.99"):
            raise ValueError("이 모듈의 1회 주문 한도는 최대 $9.99입니다.")
        object.__setattr__(self, "max_order_usd", maximum)
        if not isinstance(self.execution_enabled, bool):
            raise ValueError("execution_enabled must be bool")
        object.__setattr__(self, "data_dir", Path(self.data_dir).resolve())

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        flag = env.get("TOSS_ORDER_EXECUTION_ENABLED", "false").lower().strip()
        if flag not in {"true", "false"}:
            raise ValueError("TOSS_ORDER_EXECUTION_ENABLED는 true 또는 false여야 합니다.")
        try:
            saved = WindowsVault().read()
        except (ValueError, PermissionError):
            return cls(data_dir=Path(env.get("TOSS_DATA_DIR", "data")), credential_source="저장소 확인·키 재등록 필요")
        credentials, source = ({"TOSS_CLIENT_ID": saved["clientId"], "TOSS_CLIENT_SECRET": saved["clientSecret"]}, "모아 Windows 자격 증명 관리자") if saved else resolve_credentials(env)
        return cls(
            client_id=credentials["TOSS_CLIENT_ID"],
            client_secret=credentials["TOSS_CLIENT_SECRET"],
            account_seq="" if saved else env.get("TOSS_ACCOUNT_SEQ", "").strip(),
            credential_revision=saved["revision"] if saved else "",
            execution_enabled=flag == "true",
            max_order_usd=money(env.get("TOSS_FRACTIONAL_ORDER_MAX_USD", "9.99")),
            data_dir=Path(env.get("TOSS_DATA_DIR", "data")),
            token_cache=Path(env["TOSS_TOKEN_CACHE_PATH"]) if not saved and env.get("TOSS_TOKEN_CACHE_PATH") else None,
            credential_source=source,
        )
