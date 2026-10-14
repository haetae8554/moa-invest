"""Read only the two Toss keys from the existing Windows credential namespace.

Uses the same target selection as python-keyring's WinVaultKeyring. No credential
enumeration, copying, export, or writes; no optional Python dependency required.
"""
import os

KEYS = {"TOSS_CLIENT_ID", "TOSS_CLIENT_SECRET"}
DEFAULT_SERVICE = "stock_llm_alert_project"


def windows_environment(name):
    if name not in KEYS or os.name != "nt":
        return ""
    import winreg
    for root, subkey in [(winreg.HKEY_CURRENT_USER, "Environment"),
                         (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")]:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return os.path.expandvars(str(value)).strip()
        except FileNotFoundError:
            continue
    return ""


def windows_secret(name, service=DEFAULT_SERVICE):
    if name not in KEYS:
        raise ValueError("Only Toss API credentials can be read.")
    if os.name != "nt":
        return ""
    import ctypes
    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    pointer = ctypes.POINTER(Credential)
    read = advapi.CredReadW
    read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(pointer)]
    read.restype = wintypes.BOOL
    free = advapi.CredFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = None
    for target in (service, f"{name}@{service}"):
        credential = pointer()
        if not read(target, 1, 0, ctypes.byref(credential)):
            error = ctypes.get_last_error()
            if error == 1168:  # ERROR_NOT_FOUND
                continue
            raise PermissionError(f"Windows 자격 증명 조회 실패 (오류 {error}). 같은 Windows 사용자로 실행해 주세요.")
        try:
            record = credential.contents
            if record.UserName != name:
                continue
            raw = ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
            return raw.decode("utf-16-le").strip()
        finally:
            free(credential)
    return ""


def resolve_credentials(env):
    values = {}
    sources = set()
    for name in sorted(KEYS):
        value = env.get(name, "").strip()
        source = "환경 설정"
        if not value:
            value = windows_environment(name)
            source = "Windows 환경 변수"
        if not value:
            value = windows_secret(name, env.get("TOSS_KEYRING_SERVICE", DEFAULT_SERVICE))
            source = "Windows 자격 증명 관리자"
        values[name] = value
        if value:
            sources.add(source)
    return values, " + ".join(sorted(sources)) if all(values.values()) else "설정 필요"
