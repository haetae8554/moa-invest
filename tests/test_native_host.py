import io
import json
import os
from pathlib import Path
import struct
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from order_ui import native_host as host
from scripts.install_native_host import build_files, batch_path


def frame(value):
    raw = json.dumps(value).encode()
    return struct.pack('<I', len(raw)) + raw


class NativeHostTests(unittest.TestCase):
    def test_only_fixed_command_and_bounded_framing_are_accepted(self):
        self.assertEqual(host.read_message(io.BytesIO(frame({'action': 'ensure-server'}))), {'action': 'ensure-server'})
        for raw in [b'', b'\x00', struct.pack('<I', 2000), struct.pack('<I', 20) + b'{}',
                    frame({'action': 'ensure-server', 'command': 'arbitrary'}),
                    frame({'action': 'order'}), frame([]), frame(None)]:
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                host.read_message(io.BytesIO(raw))

    def test_origin_checked_before_read_or_launch(self):
        with patch.object(host, 'ensure_server') as ensure:
            for args in [[], ['https://tossinvest.com/'], [host.EXTENSION_ORIGIN + '.evil/']]:
                output = io.BytesIO()
                self.assertEqual(host.main(args, io.BytesIO(frame({'action': 'ensure-server'})), output), 1)
                self.assertEqual(output.getvalue(), b'')
            ensure.assert_not_called()

    def test_native_response_has_no_exception_paths_or_secrets(self):
        output = io.BytesIO()
        with patch.object(host, 'ensure_server', side_effect=RuntimeError('synthetic-sensitive-value')):
            host.main([host.EXTENSION_ORIGIN + '/'], io.BytesIO(frame({'action': 'ensure-server'})), output)
        raw = output.getvalue()
        self.assertEqual(struct.unpack('<I', raw[:4])[0], len(raw) - 4)
        self.assertEqual(json.loads(raw[4:]), {'ok': False, 'code': 'launcher-error'})
        self.assertNotIn(b'synthetic-sensitive', raw)

    def test_existing_and_occupied_ports_never_spawn_or_stop_processes(self):
        for state, ok in [('ready', True), ('occupied', False)]:
            with patch.object(host, '_TokenFileLock', return_value=nullcontext()), patch.object(host, 'probe', return_value=state), patch.object(host, 'launch_server') as launch:
                self.assertEqual(host.ensure_server()['ok'], ok)
                launch.assert_not_called()

    def test_start_waits_for_ready_and_does_not_retry_launch(self):
        with patch.object(host, '_TokenFileLock', return_value=nullcontext()), patch.object(host, 'probe', side_effect=['absent', 'ready']), patch.object(host, 'launch_server') as launch:
            self.assertEqual(host.ensure_server(), {'ok': True, 'started': True})
            launch.assert_called_once_with()
            launch.return_value.terminate.assert_not_called()

    def test_failed_start_never_kills_server_or_replays(self):
        child = Mock()
        child.poll.return_value = 1
        with patch.object(host, '_TokenFileLock', return_value=nullcontext()), patch.object(host, 'probe', return_value='absent'), patch.object(host, 'launch_server', return_value=child) as launch:
            self.assertEqual(host.ensure_server()['code'], 'start-failed')
            launch.assert_called_once_with()
            child.kill.assert_not_called()
            child.terminate.assert_not_called()

    def test_health_probe_uses_fixed_loopback_no_account_request(self):
        with patch.object(host.http.client, 'HTTPConnection') as factory:
            connection = factory.return_value
            response = connection.getresponse.return_value
            response.status = 200
            response.read.return_value = json.dumps(host.IDENTITY).encode()
            self.assertEqual(host.probe(), 'ready')
            factory.assert_called_with('127.0.0.1', 8765, timeout=0.6)
            connection.request.assert_called_with('GET', '/api/launcher-status', headers={'X-Requested-With': 'fractional-buy'})
            response.read.return_value = b'{}'
            self.assertEqual(host.probe(), 'occupied')
            connection.request.side_effect = ConnectionRefusedError()
            with patch.object(host, 'port_available', return_value=True):
                self.assertEqual(host.probe(), 'absent')
            connection.request.side_effect = TimeoutError()
            with patch.object(host, 'port_available', return_value=False):
                self.assertEqual(host.probe(), 'occupied')
            with patch.object(host, 'port_available', return_value=True):
                self.assertEqual(host.probe(), 'absent')

    def test_port_availability_requires_an_exclusive_loopback_bind(self):
        with patch.object(host.socket, 'socket') as factory:
            sock = factory.return_value.__enter__.return_value
            self.assertTrue(host.port_available())
            sock.bind.assert_called_with(('127.0.0.1', 8765))
            if os.name == 'nt':
                sock.setsockopt.assert_called_with(host.socket.SOL_SOCKET, host.socket.SO_EXCLUSIVEADDRUSE, 1)
            sock.bind.side_effect = OSError()
            self.assertFalse(host.port_available())

    @unittest.skipUnless(os.name == 'nt', 'Windows process creation flags')
    def test_hidden_child_breaks_away_from_browser_job(self):
        with patch.object(host.subprocess, 'Popen') as popen:
            host.launch_server()
            args, kwargs = popen.call_args
            self.assertEqual(args[0][1:3], ['-m', 'order_ui.server'])
            self.assertEqual(kwargs['cwd'], host.ROOT)
            self.assertTrue(kwargs['creationflags'] & host.subprocess.CREATE_NO_WINDOW)
            self.assertTrue(kwargs['creationflags'] & host.subprocess.CREATE_BREAKAWAY_FROM_JOB)
            self.assertEqual(kwargs['stdout'], host.subprocess.DEVNULL)
            self.assertNotIn('shell', kwargs)

    def test_install_files_pin_origin_and_quote_unicode_space_percent_paths(self):
        root = Path('C:/한글 폴더/100% 모아')
        folder, launcher, manifest, command, content = build_files(root, Path('C:/Python 3/python.exe'))
        self.assertEqual(folder, root / 'data' / 'native-host')
        self.assertEqual(content['path'], str(launcher))
        self.assertEqual(content['allowed_origins'], [host.EXTENSION_ORIGIN + '/'])
        self.assertIn('100%% 모아', command)
        self.assertLess(command.index('chcp 65001'), command.index('한글'))
        self.assertIn('DisableDelayedExpansion', command)
        for path in ['bad\npath', 'bad"path']:
            with self.assertRaises(ValueError):
                batch_path(path)
