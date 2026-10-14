from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import unittest

from toss_fractional import Settings, FractionalTradeService
from toss_fractional.registration import CredentialRegistration
from toss_fractional.vault import encode_record, WindowsVault
from test_orders import FakeBroker


class MemoryVault:
    supported = True
    def __init__(self):
        self.record = None
        self.fail = False
    def write(self, client_id, client_secret, revision):
        raw = encode_record(client_id, client_secret, revision)
        if self.fail:
            raise OSError(client_secret)
        self.record = json.loads(raw)
    def read(self):
        return self.record


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = Settings(data_dir=Path(self.temp.name), execution_enabled=True)
        self.old = FakeBroker()
        self.new = FakeBroker()
        self.service = FractionalTradeService(self.old, self.settings, interval=0)
        self.vault = MemoryVault()
        self.registration = CredentialRegistration(self.service, self.vault, lambda *_: self.new)

    def save(self):
        return self.registration.save('synthetic-client', 'synthetic-secret', self.registration.status()['revision'])

    def test_save_invalidates_previews_disables_execution_and_hides_keys(self):
        preview = self.service.preview_batch('AAPL', '9')
        single = self.service.preview('AAPL', '5')
        result = self.save()
        self.assertTrue(result['saved'])
        self.assertFalse(self.service.execution_mode()['executionEnabled'])
        self.assertIsNone(self.service.settings.token_cache)
        self.assertIs(self.service.broker, self.new)
        self.assertEqual(self.service.settings.account_seq, '')
        self.assertEqual(self.old.calls+self.new.calls, [])
        with self.service.store.connect() as db:
            self.assertEqual(db.execute('SELECT expires FROM batches WHERE id=?', (preview['batchId'],)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT expires FROM orders WHERE preview_id=?', (single['previewId'],)).fetchone()[0], 0)
        for value in [json.dumps(result), json.dumps(self.registration.status()), repr(self.service.settings)]:
            self.assertNotIn('synthetic-secret', value)
        for file in Path(self.temp.name).iterdir():
            self.assertNotIn(b'synthetic-secret', file.read_bytes())

    def test_stale_service_cannot_use_old_keys_even_after_mode_reenabled(self):
        stale = FractionalTradeService(FakeBroker(), self.settings)
        self.save()
        mode = self.service.execution_mode()
        self.service.set_execution_mode(True, mode['modeRevision'])
        with self.assertRaises(ValueError): stale.preview_batch('AAPL', '9')
        with self.assertRaises(ValueError): stale.set_execution_mode(True, self.service.execution_mode()['modeRevision'])

    def test_failed_validation_preserves_keys_but_leaves_execution_off(self):
        def bad(*_): raise ValueError('synthetic-secret')
        self.registration.broker_factory = bad
        with self.assertRaises(ValueError) as raised: self.save()
        self.assertNotIn('synthetic-secret', str(raised.exception))
        self.assertIsNone(self.vault.record)
        self.assertFalse(self.service.execution_mode()['executionEnabled'])
        self.assertFalse(self.registration.status()['needsRecovery'])
        self.assertIs(self.service.broker, self.old)

    def test_failed_atomic_storage_blocks_trading_until_explicit_recovery(self):
        self.vault.fail = True
        with self.assertRaises(ValueError) as raised: self.save()
        self.assertNotIn('synthetic-secret', str(raised.exception))
        self.assertTrue(self.registration.status()['needsRecovery'])
        self.assertIsNone(self.vault.record)
        self.assertFalse(self.service.execution_mode()['executionEnabled'])
        with self.assertRaises(ValueError): self.service.preview_batch('AAPL', '9')
        self.vault.fail = False
        self.save()
        self.assertFalse(self.registration.status()['needsRecovery'])
        self.assertIsNotNone(self.service.preview_batch('AAPL', '9'))

    def test_active_and_uncertain_orders_block_before_validation(self):
        for state in ['RUNNING', 'STOPPING', 'UNKNOWN', 'INTERRUPTED']:
            with self.subTest(state=state):
                p = self.service.preview_batch('AAPL', '9')
                with self.service.store.connect(write=True) as db:
                    db.execute('UPDATE batches SET state=? WHERE id=?', (state, p['batchId']))
                with self.assertRaises(ValueError): self.save()
                with self.service.store.connect(write=True) as db:
                    db.execute("UPDATE batches SET state='STOPPED'")
        for state in ['SUBMITTING', 'UNKNOWN']:
            p = self.service.preview('AAPL', '5')
            with self.service.store.connect(write=True) as db:
                db.execute('UPDATE orders SET state=? WHERE preview_id=?', (state, p['previewId']))
            with self.assertRaises(ValueError): self.save()
            with self.service.store.connect(write=True) as db:
                db.execute("UPDATE orders SET state='REJECTED'")
        self.assertIsNone(self.vault.record)

    def test_start_during_key_validation_is_blocked(self):
        p = self.service.preview_batch('AAPL', '9')
        def race(*_):
            with self.assertRaises(PermissionError):
                self.service.start_batch(p['batchId'], acknowledged=True, background=False)
            with self.assertRaises(ValueError):
                self.service.preview_batch('AAPL', '9')
            return self.new
        self.registration.broker_factory = race
        self.save()
        self.assertIsNotNone(self.vault.record)
        self.assertEqual(self.old.calls+self.new.calls, [])

    def test_stale_settings_form_cannot_overwrite_new_keys(self):
        self.save()
        original = dict(self.vault.record)
        with self.assertRaises(ValueError): self.registration.save('another-client', 'another-secret', '')
        self.assertEqual(self.vault.record, original)

    def test_restart_prefers_moa_pair_and_ignores_legacy_token_cache(self):
        self.save()
        with patch('toss_fractional.config.WindowsVault', return_value=self.vault):
            settings = Settings.from_env({'TOSS_CLIENT_ID':'old', 'TOSS_CLIENT_SECRET':'old', 'TOSS_TOKEN_CACHE_PATH':'old.json', 'TOSS_DATA_DIR':self.temp.name})
        self.assertEqual(settings.client_id, 'synthetic-client')
        self.assertEqual(settings.credential_revision, self.vault.record['revision'])
        self.assertIsNone(settings.token_cache)
        self.assertEqual(FractionalTradeService(self.new, settings).setup()['configured'], True)

    def test_corrupted_vault_still_allows_local_registration_ui(self):
        with patch('toss_fractional.config.WindowsVault.read', side_effect=ValueError('bad')):
            settings = Settings.from_env({'TOSS_DATA_DIR':self.temp.name})
        self.assertFalse(settings.configured)

    def test_bounds_unsupported_os_and_no_account(self):
        for value in ['', None, 1, 'x'*1025, 'x\ny', ' x', '가']:
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(ValueError): self.registration.save(value, 'synthetic-secret', '')
        self.vault.supported = False
        with self.assertRaises(ValueError): self.save()
        self.vault.supported = True
        self.new.list_accounts = lambda: []
        with self.assertRaises(ValueError): self.save()
        self.assertIsNone(self.vault.record)


if __name__ == '__main__': unittest.main()
