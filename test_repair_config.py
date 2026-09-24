import tempfile
from pathlib import Path
import unittest
from repair_config import proposal, repair

BASE = b'''model_provider = "cc-switch-official"
[model_providers.cc-switch-official]
name = "OpenAI"
requires_openai_auth = true
wire_api = "responses"
base_url = "http://127.0.0.1:15721/v1"
[desktop]
foo = true
'''

class RepairTests(unittest.TestCase):
    def test_repair_and_idempotence(self):
        candidate, status = proposal(BASE)
        self.assertEqual(status, 'repaired')
        self.assertTrue(candidate.startswith(BASE))
        self.assertEqual(proposal(candidate), (None, 'alias_present'))

    def test_existing_alias_preserved(self):
        raw = BASE + b'\n[model_providers.custom]\nname = "Other"\n'
        self.assertEqual(proposal(raw), (None, 'alias_present'))

    def test_reject_remote_and_unknown_routes(self):
        for old, new in [(b'127.0.0.1', b'example.com'), (b'15721', b'9999'),
                         (b'cc-switch-official', b'other'), (b'/v1', b'/v1?token=secret')]:
            self.assertIsNone(proposal(BASE.replace(old, new))[0])

    def test_bom_crlf(self):
        raw = b'\xef\xbb\xbf' + BASE.replace(b'\n', b'\r\n')
        self.assertEqual(proposal(raw)[1], 'repaired')

    def test_nested_provider_blocked(self):
        raw = BASE.replace(b'[desktop]', b'[model_providers.cc-switch-official.http_headers]\nx="y"\n[desktop]')
        self.assertEqual(proposal(raw), (None, 'blocked_table_shape'))

    def test_invalid_toml(self):
        with self.assertRaises(ValueError):
            proposal(BASE + b'broken = [')

    def test_disk_backup_and_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_bytes(BASE)
            self.assertEqual(repair(path), 'repaired')
            backups = list(Path(directory).glob('*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), BASE)
            self.assertEqual(repair(path), 'alias_present')
            self.assertEqual(len(list(Path(directory).glob('*.bak'))), 1)

if __name__ == '__main__':
    unittest.main()
