import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class StdlibImportTest(unittest.TestCase):
    def test_card_modules_import_without_numpy(self):
        # The QQ card publisher runs under /usr/bin/python3, which has no numpy.
        code = ("import sys; sys.modules['numpy'] = None\n"
                "from studies.trader_screens import aggregation, board, context, focus")
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
