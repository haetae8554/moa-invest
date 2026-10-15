"""Create reviewed local archives only. Never upload, register or publish anything."""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.check_public_tree import violations
from order_ui.extension import EXTENSION_ORIGIN

EXTENSION_FILES = '''manifest.json background.js protocol.js resolver.js toss.js moa.js
popup.html popup.js popup.css sidepanel.html sidepanel.js sidepanel.css launcher.js
launch.html launch.js options.html guide.css demo.html demo.js
icons/moa-16.png icons/moa-32.png icons/moa-48.png icons/moa-128.png'''.split()


def extension_id(public_key):
    digest = hashlib.sha256(base64.b64decode(public_key, validate=True)).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(c, 16)) for c in digest)


def checked_extension(root):
    folder = root / 'browser_extension'
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    origin = 'chrome-extension://' + extension_id(manifest['key'])
    if origin != EXTENSION_ORIGIN or origin not in (root / 'order_ui/static/panel-bridge.js').read_text(encoding='utf-8'):
        raise ValueError('Extension/server/bridge identity mismatch')
    if set(manifest['permissions']) != {'storage', 'sidePanel', 'nativeMessaging'}:
        raise ValueError('Review changed permissions before packaging')
    expected = {'https://tossinvest.com/*', 'https://www.tossinvest.com/*', 'https://wts-info-api.tossinvest.com/*', 'http://127.0.0.1:8765/*', 'http://localhost:8765/*'}
    if set(manifest['host_permissions']) != expected or manifest.get('externally_connectable') or manifest.get('web_accessible_resources'):
        raise ValueError('Review changed host/message permissions before packaging')
    result = {}
    for name in EXTENSION_FILES:
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked extension asset: ' + name)
        blob = path.read_bytes()
        if violations('browser_extension/' + name, blob):
            raise ValueError('Publication guard rejected extension asset: ' + name)
        result[name] = blob
    return manifest['version'], result


def zip_bytes(path, files):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, blob in sorted(files.items()):
            # Stable metadata; archives contain only explicitly selected bytes.
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, blob)


def build_windows(output, version):
    if os.name != 'nt':
        raise RuntimeError('Build Windows helper on Windows')
    import PyInstaller
    if PyInstaller.__version__ != '6.22.3':
        raise RuntimeError('Use the pinned build dependency: PyInstaller==6.22.3')
    build_root = ROOT / 'build'
    build_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='release-', dir=build_root) as temporary:
        stage = Path(temporary).resolve()
        if not stage.is_relative_to(build_root.resolve()):
            raise RuntimeError('Build path escaped workspace')
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--onedir', '--console', '--noupx',
                        '--name', 'MoaHelper', '--distpath', str(stage / 'dist'),
                        '--workpath', str(stage / 'work'), '--specpath', str(stage),
                        '--paths', str(ROOT), '--add-data', str(ROOT / 'order_ui/static') + ':order_ui/static',
                        str(ROOT / 'scripts/windows_entry.py')], check=True, cwd=ROOT)
        bundle = stage / 'dist/MoaHelper'
        environment = dict(os.environ)
        environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
        environment.pop('PYTHONPATH', None)
        environment.pop('PYTHONHOME', None)
        checked = subprocess.run([str(bundle / 'MoaHelper.exe'), '--self-test'], check=True, timeout=30,
                                 capture_output=True, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
        if json.loads(checked.stdout) != {'ok': True, 'bundledAssets': True, 'loopbackHTTP': True, 'brokerCalls': 0}:
            raise RuntimeError('Bundled self-test did not confirm isolated operation')
        print('Bundled UI/HTTP self-test passed with Python removed from PATH; no broker calls.')
        files = {str(p.relative_to(bundle)).replace('\\', '/'): p.read_bytes() for p in bundle.rglob('*') if p.is_file()}
        for action in ('Install', 'Uninstall'):
            files[action + '.cmd'] = ('@echo off\r\n"%~dp0MoaHelper.exe" --' + action.lower() + '\r\npause\r\n').encode('ascii')
        for name in ('PRIVACY.md', 'SECURITY.md'):
            files[name] = (ROOT / name).read_bytes()
        files['THIRD_PARTY/PYTHON-LICENSE.txt'] = (Path(sys.base_prefix) / 'LICENSE.txt').read_bytes()
        distribution = importlib.metadata.distribution('PyInstaller')
        license_path = next(p for p in distribution.files if str(p).endswith('/licenses/COPYING.txt'))
        files['THIRD_PARTY/PYINSTALLER-COPYING.txt'] = Path(distribution.locate_file(license_path)).read_bytes()
        files['README.txt'] = (ROOT / 'docs/store/WINDOWS-PACKAGE.txt').read_bytes()
        path = output / f'moa-windows-{version}-unsigned.zip'
        zip_bytes(path, files)
        return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true', help='Also build a Python-included unsigned Windows helper')
    args = parser.parse_args()
    version, files = checked_extension(ROOT)
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    path = output / f'moa-chrome-{version}.zip'
    zip_bytes(path, files)
    paths = [path]
    if args.windows:
        app_version = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
        paths.append(build_windows(output, app_version))
    checksums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in paths)
    (output / 'SHA256SUMS.txt').write_text(checksums, encoding='ascii')
    print(checksums, end='')
    print('Local build only. Nothing uploaded or registered. Windows bundle, if built, is UNSIGNED.')


if __name__ == '__main__':
    main()
