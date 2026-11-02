import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_runtime

ROOT = Path(__file__).resolve().parents[2]


class RuntimeTests(unittest.TestCase):
    def test_wrong_interpreter_fails_before_loading_dependencies(self):
        with patch.object(check_runtime.sys, 'prefix', '/missing-runtime'):
            with self.assertRaisesRegex(RuntimeError, 'use .*\\.venv/bin/python'):
                check_runtime.check()

    def test_missing_or_changed_locked_dependency_fails(self):
        for actual in ('missing', '0.0.0'):
            with self.subTest(actual=actual), patch.object(check_runtime.sys, 'prefix', str(ROOT / '.venv')):
                error = check_runtime.metadata.PackageNotFoundError('futu-api') if actual == 'missing' else None
                with patch.object(check_runtime.metadata, 'version', return_value=actual, side_effect=error):
                    with self.assertRaises((RuntimeError, check_runtime.metadata.PackageNotFoundError)):
                        check_runtime.check()

    @unittest.skipUnless((ROOT / 'research/trader_board_to_qq.py').is_file()
                         and (ROOT / '.venv/bin/python').is_file(), 'host-only publisher is not installed')
    def test_system_python_publisher_switches_to_project_environment(self):
        result = subprocess.run(['/usr/bin/python3', 'research/trader_board_to_qq.py', '--check-runtime'],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'runtime OK: {ROOT}/.venv/bin/python', result.stdout)

if __name__ == '__main__':
    unittest.main()
