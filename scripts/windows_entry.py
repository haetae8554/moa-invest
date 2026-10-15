"""Frozen Windows helper entry point. Native stdio stays free of console output."""
import http.client
import json
import os
from pathlib import Path
import sys
from threading import Thread

from order_ui import native_host
from order_ui.server import make_server, main as serve, STATIC
from scripts.install_native_host import install


def self_test():
    # No Settings, vault, .env, database or broker: exercise only packaged assets/HTTP.
    for name in ('index.html', 'app.js', 'styles.css', 'theme.js', 'panel-bridge.js'):
        if not (STATIC / name).is_file():
            raise RuntimeError('Missing bundled UI')
    server = make_server(None, 0, registration=object())
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
    try:
        connection.request('GET', '/api/launcher-status', headers={'X-Requested-With': 'fractional-buy'})
        response = connection.getresponse()
        if response.status != 200 or json.loads(response.read()) != native_host.IDENTITY:
            raise RuntimeError('Health check failed')
        connection.request('GET', '/')
        response = connection.getresponse()
        if response.status != 200 or b'order-form' not in response.read():
            raise RuntimeError('Bundled UI failed')
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join()
    print(json.dumps({'ok': True, 'bundledAssets': True, 'loopbackHTTP': True, 'brokerCalls': 0}))


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if args and args[0].startswith('chrome-extension://'):
        return native_host.main(args)
    if args == ['--self-test']:
        self_test()
        return 0
    if args in (['--install'], ['--uninstall']):
        install(uninstall=args == ['--uninstall'], root=native_host.ROOT,
                executable=sys.executable, frozen=bool(getattr(sys, 'frozen', False)))
        return 0
    if args == ['--serve']:
        os.chdir(native_host.ROOT)
        serve(['--env', str(native_host.ROOT / '.env')])
        return 0
    print('Moa Windows helper: --install | --uninstall | --self-test')
    return 0 if not args else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        print('Moa helper failed. Check the installation and available local port.', file=sys.stderr)
        raise SystemExit(1)
