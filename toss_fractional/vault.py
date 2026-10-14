"""One atomic, versioned credential pair in Moa's own Windows vault target.

No enumeration, plaintext fallback, or modification of legacy credential targets.
Win32 layout: https://learn.microsoft.com/windows/win32/api/wincred/ns-wincred-credentialw
"""
import json
import os
import re

TARGET = "moa-invest/toss-api/v1"


def validate_pair(client_id, client_secret):
    for value in (client_id, client_secret):
        if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Client ID와 Client Secret을 공백 없이 입력해 주세요. 각 값은 최대 1,024자입니다.")


def encode_record(client_id, client_secret, revision):
    validate_pair(client_id, client_secret)
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{32}", revision):
        raise ValueError("자격 증명 버전이 올바르지 않습니다.")
    raw = json.dumps({"version": 1, "clientId": client_id, "clientSecret": client_secret,
                      "revision": revision}, separators=(",", ":")).encode("utf-8")
    if len(raw) > 2560:
        raise ValueError("자격 증명 저장 크기를 초과했습니다.")
    return raw


def _api():
    if os.name != "nt":
        raise ValueError("화면에서 키 저장은 Windows에서 지원합니다. 이 환경에서는 프로세스 환경 변수를 사용해 주세요.")
    import ctypes
    from ctypes import wintypes
    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return ctypes, Credential, api


class WindowsVault:
    @property
    def supported(self):
        return os.name == "nt"

    def read(self):
        if not self.supported:
            return None
        ctypes, Credential, api = _api()
        pointer = ctypes.POINTER(Credential)()
        if not api.CredReadW(TARGET, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise PermissionError("모아 자격 증명 저장소를 읽을 수 없습니다.")
        try:
            raw = ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize)
            record = json.loads(raw.decode("utf-8"))
            if record.get("version") != 1:
                raise ValueError
            encode_record(record["clientId"], record["clientSecret"], record["revision"])
            return record
        except Exception:
            raise ValueError("모아의 저장된 키 형식을 확인할 수 없습니다. 키를 다시 등록해 주세요.") from None
        finally:
            api.CredFree(pointer)

    def write(self, client_id, client_secret, revision):
        raw = encode_record(client_id, client_secret, revision)
        ctypes, Credential, api = _api()
        blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        record = Credential(Type=1, TargetName=TARGET, UserName="Moa", Persist=2,
                            CredentialBlobSize=len(raw), CredentialBlob=blob)
        try:
            if not api.CredWriteW(ctypes.byref(record), 0):
                raise PermissionError("Windows 자격 증명 저장에 실패했습니다. 키를 다시 등록해 주세요.")
        finally:
            ctypes.memset(blob, 0, len(raw))
