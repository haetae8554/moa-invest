from datetime import datetime, timezone
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory

from scripts.check_public_tree import violations
from toss_fractional import Settings, create_service
from toss_fractional.auth import TossToken


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data_dir = Path(temp.name)

    def test_private_paths_are_rejected_even_if_force_added(self):
        for path in ['.env', '.env.production', 'nested/.env.local', 'data/state.db', 'artifacts/capture.png', 'secrets/key.txt', 'backup/token.json', 'design-qa.md']:
            self.assertIn('private-file', violations(path, b''), path)

    def test_template_is_blank_and_secret_findings_do_not_echo_values(self):
        self.assertEqual(violations('.env.example', b'TOSS_CLIENT_ID=\nTOSS_CLIENT_SECRET=\nTOSS_ACCOUNT_SEQ=\n'), [])
        self.assertIn('populated-toss-env', violations('config.txt', b'TOSS_CLIENT_SECRET=synthetic-test-value\n'))
        self.assertIn('private-key', violations('source.txt', b'-----BEGIN ' + b'PRIVATE KEY-----'))

    def test_oauth_token_is_hidden_from_repr(self):
        token = TossToken('synthetic-sensitive-value', 'Bearer', datetime.now(timezone.utc))
        self.assertNotIn('synthetic-sensitive-value', repr(token))

    def test_default_service_does_not_create_a_disk_token_cache(self):
        service = create_service(Settings(client_id='test-client', client_secret='test-secret', data_dir=self.data_dir))
        self.assertIsNone(service.broker.auth.cache_path)

    def test_explicit_legacy_cache_path_is_preserved(self):
        service = create_service(Settings(client_id='test-client', client_secret='test-secret', data_dir=self.data_dir, token_cache=Path('legacy-token.json')))
        self.assertEqual(service.broker.auth.cache_path, Path('legacy-token.json'))
