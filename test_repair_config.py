import copy
import importlib.util
import tempfile
import tomllib
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('repair', Path(__file__).with_name('repair_config.py'))
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)

def config(selected='custom', url='http://127.0.0.1:15721/v1', alias=None):
    text = f'model_provider = "{selected}"\nmodel = "unchanged"\n[model_providers.{selected}]\nname = "Active"\nbase_url = "{url}"\nwire_api = "responses"\nrequires_openai_auth = true\n'
    if alias is not None:
        target = 'custom' if selected == 'cc-switch-official' else 'cc-switch-official'
        text += f'\n[model_providers.{target}]\nname = "Old"\nbase_url = "{alias}"\nwire_api = "responses"\n'
    return (text + '\n[other]\nkeep = "yes"\n').encode()

class CompatibilityTests(unittest.TestCase):
    def check_mirror(self, raw):
        before = tomllib.loads(raw.decode('utf-8-sig'))
        candidate, status = repair.proposal(raw)
        self.assertIn(status, ('repaired', 'alias_synchronized'))
        result = tomllib.loads(candidate.decode('utf-8-sig'))
        expected = copy.deepcopy(before)
        target = 'custom' if before['model_provider'] == 'cc-switch-official' else 'cc-switch-official'
        expected['model_providers'][target] = copy.deepcopy(before['model_providers'][before['model_provider']])
        self.assertEqual(result, expected)
        self.assertEqual(repair.proposal(candidate), (None, 'alias_present'))

    def test_both_directions_local_and_direct(self):
        for selected in ('custom', 'cc-switch-official'):
            for url in ('http://127.0.0.1:15721/v1', 'https://example.test/v1'):
                with self.subTest(selected=selected, url=url):
                    self.check_mirror(config(selected, url))

    def test_stale_alias_tracks_selected_not_old_provider(self):
        for selected in ('custom', 'cc-switch-official'):
            with self.subTest(selected=selected):
                self.check_mirror(config(selected, alias='https://old.invalid/v1'))

    def test_missing_selected_never_uses_stale_alias(self):
        raw = config().replace(b'model_provider = "custom"', b'model_provider = "cc-switch-official"')
        self.assertEqual(repair.proposal(raw), (None, 'blocked_provider'))

    def test_unrelated_selection_untouched(self):
        self.assertEqual(repair.proposal(config('unrelated')), (None, 'blocked_provider'))

    def test_nested_table_fails_closed(self):
        raw = config().replace(b'[other]', b'[model_providers.custom.http_headers]\nx = "y"\n[other]')
        self.assertEqual(repair.proposal(raw), (None, 'blocked_table_shape'))

    def test_quoted_header_and_bom(self):
        raw = b'\xef\xbb\xbf' + config().replace(b'[model_providers.custom]', b'[model_providers."custom"]').replace(b'\n', b'\r\n')
        self.check_mirror(raw)
        self.assertTrue(repair.proposal(raw)[0].startswith(b'\xef\xbb\xbf'))

    def test_file_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.toml'
            raw = config()
            path.write_bytes(raw)
            self.assertEqual(repair.repair(path), 'repaired')
            backups = list(Path(folder).glob('*.bak'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), raw)
            self.assertEqual(repair.repair(path), 'alias_present')
            self.assertEqual(len(list(Path(folder).glob('*.bak'))), 1)

if __name__ == '__main__':
    unittest.main(verbosity=2)
