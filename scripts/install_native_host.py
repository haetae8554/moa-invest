"""Register only this user's Moa launcher; no administrator or startup task needed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from order_ui.extension import EXTENSION_ORIGIN
from order_ui.native_host import HOST_NAME

REGISTRY_KEY = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"


def batch_path(path):
    value = str(path)
    if any(c in value for c in '\r\n"'):
        raise ValueError("Unsupported installation path")
    return '"' + value.replace('%', '%%') + '"'


def build_files(root, python, frozen=False):
    folder = root / "data" / "native-host"
    launcher = folder / "launch.cmd"
    manifest = folder / (HOST_NAME + ".json")
    # Switch cmd to UTF-8 before it reads the Unicode installation paths.
    command = ("@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\n"
               f"cd /d {batch_path(root)}\r\n"
               "if errorlevel 1 exit /b 1\r\n"
               f"{batch_path(python)} -u -m order_ui.native_host %*\r\n")
    content = {"name": HOST_NAME, "description": "Moa local desk launcher",
               "path": str(python if frozen else launcher), "type": "stdio", "allowed_origins": [EXTENSION_ORIGIN + "/"]}
    return folder, launcher, manifest, command, content


def install(uninstall=False, root=None, executable=None, frozen=False):
    if os.name != "nt" or sys.version_info < (3, 11):
        raise RuntimeError("Windows and Python 3.11+ are required.")
    import winreg
    folder, launcher, manifest, command, content = build_files(root or ROOT, Path(executable or sys.executable).resolve(), frozen)
    if uninstall:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
                registered, _ = winreg.QueryValueEx(key, None)
            if Path(registered).resolve() != manifest.resolve():
                raise RuntimeError("Another installation owns this registration; nothing changed.")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY)
        except FileNotFoundError:
            pass
        print("Moa Chrome launcher unregistered. Keys, orders and running server are unchanged.")
        return
    folder.mkdir(parents=True, exist_ok=True)
    if not frozen:
        launcher.write_bytes(command.encode("utf-8"))
    manifest.write_text(json.dumps(content, ensure_ascii=True, indent=2), encoding="utf-8")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_KEY) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest))
    print("Moa Chrome launcher registered for this Windows user.")
    print("Reload the Moa extension, then open its side panel. No run.bat needed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true")
    try:
        install(parser.parse_args().uninstall)
    except Exception:
        print("Launcher setup failed. Check Python 3.11+, folder permissions and installation ownership.", file=sys.stderr)
        raise SystemExit(1)
