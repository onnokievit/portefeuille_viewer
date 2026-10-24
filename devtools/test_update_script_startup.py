"""Run update entrypoints exactly as standalone workers, without inherited PYTHONPATH."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UpdateScriptStartupTests(unittest.TestCase):
    def test_standalone_help_without_pythonpath(self):
        with tempfile.TemporaryDirectory(prefix='pv-script-startup-') as folder:
            root = Path(folder)
            config = root / 'settings.ini'
            config.write_text(
                '[databases]\ntest = ' + str(root / 'user.accdb') + ' | black | white | true\n'
                '[stockdata]\ndb_path = ' + str(root / 'stock.accdb') + '\n',
                encoding='utf-8',
            )
            env = os.environ.copy()
            env.pop('PYTHONPATH', None)
            env.pop('PV_PROFILE_DATABASE', None)
            env.pop('PV_STOCKDATA_DATABASE', None)
            env['PV_CONFIG_FILES'] = json.dumps([str(config)])
            env['PYTHONIOENCODING'] = 'utf-8'
            # --help exits before network/database operations. No DB files exist.
            for name in ('fetch_asset_volatility_history_to_db.py', 'build_continuous_fut_close.py'):
                with self.subTest(script=name):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / 'price_update_scripts' / name), '--help'],
                        cwd=root, env=env, capture_output=True, encoding='utf-8', timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('usage:', result.stdout.lower())
            self.assertFalse(list(root.glob('*.accdb')))


if __name__ == '__main__':
    unittest.main()
