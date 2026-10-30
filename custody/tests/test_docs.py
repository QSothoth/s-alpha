import json
import subprocess
import unittest
from pathlib import Path

from custody import evaluate as ev
from custody.registry import Registry

ROOT = Path(__file__).resolve().parents[2]


class DocsTests(unittest.TestCase):
    def test_claude_references_agents(self):
        """Layered rules: the root and every capability directory carry an
        AGENTS.md, and each CLAUDE.md is the one-line pointer to its sibling."""
        for folder in (ROOT, ROOT / 'custody', ROOT / 'watch', ROOT / 'studies'):
            self.assertTrue((folder / 'AGENTS.md').is_file(), folder)
            self.assertEqual((folder / 'CLAUDE.md').read_text(encoding='utf-8'), '@AGENTS.md\n', folder)
        root = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        for sub in ('custody/AGENTS.md', 'watch/AGENTS.md', 'studies/AGENTS.md'):
            self.assertIn('(%s)' % sub, root, sub)

    def test_commands_use_the_project_venv(self):
        """Only the project .venv exists; reports and notes keep the commands they ran."""
        old = '/opt/futu-opend/' + 'venv'
        tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True, text=True, check=True)
        for name in tracked.stdout.split('\0'):
            parts = Path(name).parts
            path = ROOT / name
            if 'reports' in parts or 'notes' in parts or path.suffix not in ('.py', '.md') or not path.is_file():
                continue
            self.assertNotIn(old, path.read_text(encoding='utf-8'), name)

    def test_standard_document_matches_the_code_constants(self):
        text = (ROOT / 'docs' / 'STANDARD.md').read_text(encoding='utf-8')
        for needle in ('%d%%' % round(100 * ev.PRIMARY_FILL.slippage_fraction), '$%.2f' % ev.PRIMARY_FILL.fee_per_contract,
                       '%g' % ev.MIN_PAYOFF_RATIO, str(ev.MIN_OOS_SESSIONS), str(ev.MIN_CASES_PER_SCENARIO),
                       str(ev.SPLIT_MINUTE), str(ev.LABEL_BAND), str(ev.NULL_DRAWS),
                       '%d%%' % round(100 * ev.NEIGHBOR_SCALE), 'G7', 'G8', 'G9', 'G10', 'settled_at_expiry'):
            self.assertIn(needle, text)
        for key, (name, scale, _) in ev.SCORE_TEXT.items():   # return score: same items, scales and internal weights
            self.assertIn('| %s | %s | %d |' % (name, scale, ev.SCORE_WEIGHTS[key]), text)
        self.assertIn('综合分 = %d%% × 收益分 + %d%% × 完成分' %
                      (round(100 * (1 - ev.COMPLETION_SCORE_WEIGHT)), round(100 * ev.COMPLETION_SCORE_WEIGHT)), text)
        self.assertIn('方向正确时参与率', text)
        self.assertIn('同一标的 CALL 和 PUT 合起来看', text)
        self.assertIn('亏掉超过一半（%d%%）' % round(-100 * ev.PAIR_BIG_LOSS), text)
        self.assertIn('| G12 |', text)
        self.assertIn('不超过 %d%%' % round(100 * ev.PAIR_MAX_BIG_LOSS_SHARE), text)
        self.assertIn('16 分', text)
        self.assertIn('| G13 |', text)
        self.assertIn('重复 %d 次' % ev.RANDOM_ENTRY_DRAWS, text)
        self.assertIn('p ≤ %.2f' % ev.RANDOM_ENTRY_MAX_P, text)
        self.assertIn('固定 %.0f 美元权利金' % ev.ACCOUNT_BUDGET_USD, text)
        self.assertIn('`%s`' % ev.REGIME_SYMBOL, text)
        self.assertIn('G3–G13', text)

    def test_both_sides_rule_is_written_everywhere_it_applies(self):
        for name in ('custody/AGENTS.md', 'docs/DATA.md', 'docs/STANDARD.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            self.assertIn('CALL 和 PUT', text, name)
            self.assertIn('custody check', text, name)

    def test_every_registered_strategy_has_a_committed_report(self):
        for item in Registry().list():
            reports = list((ROOT / 'reports' / item['strategy_id']).glob('*/report.json'))
            self.assertTrue(reports, item['strategy_id'])
            for path in reports:
                report = json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(report['strategy']['sha256'], item['sha256'], path)
                self.assertIn('completion_score', report['summary'], path)
                self.assertIn('with_direction_participation', report['summary'], path)
                self.assertEqual(set(report['pairs']), {'strategy', 'benchmark'}, path)
                for side in ('strategy', 'benchmark', 'strategy_hit_0.6', 'benchmark_hit_0.6'):
                    self.assertEqual(report['score'][side]['completion_weight'], ev.COMPLETION_SCORE_WEIGHT, path)
                    self.assertIn('return_score', report['score'][side], path)
                self.assertNotIn('G1_completion_100pct', report['gates_in_sample'], path)
                self.assertIn('G12_call_put_pairs_tolerate_the_wrong_side', report['gates_in_sample'], path)
                self.assertEqual(report['guaranteed_entry'], ev.guaranteed_entry(Registry().get(item['strategy_id'])), path)
                self.assertEqual('G13_entry_beats_random_entry' in report['gates_in_sample'], not report['guaranteed_entry'], path)
                self.assertIn('random_entry', report, path)
                self.assertEqual(set(report['account']), {'strategy', 'benchmark'}, path)
                self.assertIn('market_regimes', report, path)


if __name__ == '__main__':
    unittest.main()
