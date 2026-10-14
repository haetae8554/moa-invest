"""Credential registration without exposing keys to UI responses or order storage."""
from dataclasses import replace
import uuid

from .auth import TossAuthClient, _TokenFileLock
from .client import TossClient
from .vault import WindowsVault, validate_pair


def broker_for(client_id, client_secret):
    return TossClient(TossAuthClient(client_id, client_secret, cache_path=None))


class CredentialRegistration:
    def __init__(self, service, vault=None, broker_factory=broker_for):
        self.service = service
        self.vault = vault if vault is not None else WindowsVault()
        self.broker_factory = broker_factory

    def status(self):
        with self.service.store.connect() as db:
            state = dict(db.execute("SELECT * FROM credential_state WHERE id=1").fetchone())
        return {"supported": self.vault.supported, "configured": self.service.settings.configured,
                "source": self.service.settings.credential_source, "revision": state["revision"],
                "needsRecovery": bool(state["pending"])}

    @staticmethod
    def idle(db):
        if db.execute("SELECT 1 FROM batches WHERE state IN ('RUNNING','STOPPING','UNKNOWN','INTERRUPTED')").fetchone() or db.execute("SELECT 1 FROM orders WHERE state IN ('SUBMITTING','UNKNOWN')").fetchone():
            raise ValueError("실행 중이거나 결과 확인이 필요한 주문이 있어 키를 변경할 수 없습니다. 주문 기록을 확인해 주세요.")

    def save(self, client_id, client_secret, expected_revision):
        with _TokenFileLock(self.service.settings.data_dir / "credential-registration.lock"):
            return self._save(client_id, client_secret, expected_revision)

    def _save(self, client_id, client_secret, expected_revision):
        if not self.vault.supported:
            raise ValueError("API 키 저장은 Windows에서 지원합니다.")
        validate_pair(client_id, client_secret)
        if not isinstance(expected_revision, str):
            raise ValueError("키 설정을 다시 열어 주세요.")
        revision = uuid.uuid4().hex
        # Gate execution BEFORE even validating a key: OAuth issuance can affect
        # an existing token. All updated processes share this durable gate.
        with self.service.store.connect(write=True) as db:
            self.idle(db)
            previous = dict(db.execute("SELECT revision,pending FROM credential_state WHERE id=1").fetchone())
            if previous["revision"] != expected_revision:
                raise ValueError("다른 화면에서 키 설정이 변경되었습니다. 다시 열어 주세요.")
            db.execute("UPDATE credential_state SET revision=?,pending=1 WHERE id=1", (revision,))
            mode = self.service.store.mode(db, self.service.settings.execution_enabled)
            db.execute("INSERT OR REPLACE INTO execution_mode VALUES (1,0,?)", (mode["modeRevision"]+1,))
            db.execute("UPDATE orders SET expires=0 WHERE state='PREVIEW'")
            db.execute("UPDATE batches SET expires=0 WHERE state='PREVIEW'")
        # Validate only by reading accounts; no order APIs or token files.
        try:
            broker = self.broker_factory(client_id, client_secret)
            accounts = broker.list_accounts()
            if not isinstance(accounts, list) or not any(isinstance(a, dict) and a.get("accountType") == "BROKERAGE" for a in accounts):
                raise ValueError
        except Exception:
            with self.service.store.connect(write=True) as db:
                db.execute("UPDATE credential_state SET revision=?,pending=? WHERE id=1 AND revision=?",
                           (previous["revision"], previous["pending"], revision))
            # Old credentials remain intact, but do not silently re-enable trading.
            raise ValueError("키를 확인할 수 없습니다. 키 값·API 권한·네트워크와 종합매매 계좌를 확인해 주세요. 기존 키는 유지하며 실주문은 꺼졌습니다.") from None
        with self.service.store.connect(write=True) as db:
            self.idle(db)
        try:
            self.vault.write(client_id, client_secret, revision)
        except Exception:
            raise ValueError("키 저장에 실패해 실주문을 차단했습니다. Windows 저장소를 확인하고 키를 다시 등록해 주세요.") from None
        settings = replace(self.service.settings, client_id=client_id, client_secret=client_secret,
                           credential_revision=revision, credential_source="모아 Windows 자격 증명 관리자",
                           account_seq="", token_cache=None, execution_enabled=False)
        with self.service.store.connect(write=True) as db:
            state = db.execute("SELECT revision FROM credential_state WHERE id=1").fetchone()
            if state["revision"] != revision:
                raise ValueError("다른 화면에서 키가 변경되었습니다. 모아를 다시 실행해 주세요.")
            db.execute("UPDATE credential_state SET pending=0 WHERE id=1")
        self.service.settings = settings
        self.service.broker = broker
        return {"saved": True, "executionEnabled": False}
