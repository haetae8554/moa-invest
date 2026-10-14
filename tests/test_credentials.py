from unittest.mock import patch
import unittest

from toss_fractional.credentials import resolve_credentials, windows_secret


class CredentialTests(unittest.TestCase):
    @patch('toss_fractional.credentials.windows_secret')
    @patch('toss_fractional.credentials.windows_environment')
    def test_explicit_credentials_take_precedence_without_vault_read(self, registry, vault):
        values, source = resolve_credentials({'TOSS_CLIENT_ID':'id', 'TOSS_CLIENT_SECRET':'secret'})
        self.assertEqual(values['TOSS_CLIENT_ID'], 'id')
        registry.assert_not_called(); vault.assert_not_called()

    @patch('toss_fractional.credentials.windows_secret', side_effect=lambda name, service: 'test-value')
    @patch('toss_fractional.credentials.windows_environment', return_value='')
    def test_reads_only_two_toss_entries_in_existing_namespace(self, registry, vault):
        values, source = resolve_credentials({})
        self.assertEqual(set(values), {'TOSS_CLIENT_ID','TOSS_CLIENT_SECRET'})
        self.assertEqual(vault.call_count, 2)
        self.assertEqual({c.args[1] for c in vault.call_args_list}, {'stock_llm_alert_project'})
        self.assertEqual(source, 'Windows 자격 증명 관리자')

    def test_unrelated_secret_cannot_be_requested(self):
        with self.assertRaises(ValueError): windows_secret('SMTP_PASSWORD')

    @patch('toss_fractional.credentials.windows_secret', side_effect=PermissionError('denied'))
    @patch('toss_fractional.credentials.windows_environment', return_value='')
    def test_access_denied_is_not_silently_hidden(self, registry, vault):
        with self.assertRaises(PermissionError): resolve_credentials({})


if __name__ == '__main__': unittest.main()
