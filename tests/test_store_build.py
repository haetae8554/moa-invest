import contextlib
import io
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from scripts.build_release import checked_extension, extension_id, zip_bytes, ROOT, EXTENSION_FILES
from scripts.install_native_host import build_files
from scripts.windows_entry import self_test
from order_ui import native_host


class StoreBuildTests(unittest.TestCase):
    def test_allowlisted_zip_contains_runtime_assets_but_no_extra_private_files(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            shutil.copytree(ROOT/'browser_extension', root/'browser_extension')
            (root/'order_ui/static').mkdir(parents=True)
            shutil.copyfile(ROOT/'order_ui/static/panel-bridge.js', root/'order_ui/static/panel-bridge.js')
            (root/'browser_extension/.env').write_text('not-for-distribution')
            version, blobs=checked_extension(root)
            output=root/'test.zip'
            zip_bytes(output,blobs)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()),set(EXTENSION_FILES))
                self.assertNotIn('.env',archive.namelist())
                self.assertEqual(json.loads(archive.read('manifest.json'))['version'],version)
                self.assertIn('demo.html',archive.namelist())

    def test_identity_drift_fails_closed(self):
        with patch('scripts.build_release.EXTENSION_ORIGIN','chrome-extension://wrong'):
            with self.assertRaisesRegex(ValueError,'identity mismatch'):
                checked_extension(ROOT)

    def test_packaged_manifest_points_to_exe_without_python_or_cmd(self):
        folder, launcher, manifest, command, content=build_files(Path('portable'),Path('portable/MoaHelper.exe'),frozen=True)
        self.assertEqual(content['path'],str(Path('portable/MoaHelper.exe')))
        self.assertEqual(content['allowed_origins'],[native_host.EXTENSION_ORIGIN+'/'])

    @unittest.skipUnless(os.name == 'nt','Windows creation flags')
    def test_frozen_child_uses_serve_instead_of_python_module(self):
        with patch.object(native_host.sys,'frozen',True,create=True), patch.object(native_host.subprocess,'Popen') as popen:
            native_host.launch_server()
            self.assertEqual(popen.call_args.args[0],[native_host.sys.executable,'--serve'])

    def test_bundled_self_check_never_accesses_vault_or_broker(self):
        output=io.StringIO()
        with patch('toss_fractional.vault.WindowsVault.read',side_effect=AssertionError('vault access')) as vault, patch('toss_fractional.client.TossClient._request',side_effect=AssertionError('broker call')) as broker, contextlib.redirect_stdout(output):
            self_test()
        self.assertEqual(json.loads(output.getvalue())['brokerCalls'],0)
        vault.assert_not_called()
        broker.assert_not_called()

    def test_release_archive_metadata_is_stable(self):
        with TemporaryDirectory() as temp:
            a,b=Path(temp)/'a.zip',Path(temp)/'b.zip'
            zip_bytes(a,{'b.txt':b'b','a.txt':b'a'})
            zip_bytes(b,{'a.txt':b'a','b.txt':b'b'})
            self.assertEqual(a.read_bytes(),b.read_bytes())
