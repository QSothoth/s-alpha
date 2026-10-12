import json
import tempfile
import unittest
from pathlib import Path

from studies.agent_card_eval.code.run import parse_decision, parse_probability
from studies.agent_card_eval.code.score import score


def _write(root, outcomes, votes):
    root = Path(root)
    (root / 'cards').mkdir()
    (root / 'raw').mkdir()
    (root / 'cards' / 'outcomes.jsonl').write_text(''.join(json.dumps(o) + '\n' for o in outcomes), encoding='utf-8')
    for card_id, decisions in votes.items():
        for rep, decision in enumerate(decisions):
            p = decision if isinstance(decision, float) else None
            record = {'card_id': card_id, 'rep': rep, 'decision': None if p is not None else decision, 'p_big_win': p, 'usage': {'input_tokens': 10, 'output_tokens': 2},
                      'cost_usd': None, 'seconds': 1.0}
            (root / 'raw' / ('%s.%d.json' % (card_id, rep))).write_text(json.dumps(record), encoding='utf-8')
    return root / 'cards', root / 'raw'


class ScoreTests(unittest.TestCase):
    def test_parse_decision_accepts_only_take_or_skip_json(self):
        self.assertEqual(parse_decision('{"decision": "TAKE", "confidence": 0.6}'), 'TAKE')
        self.assertEqual(parse_decision('```json\n{"decision": "SKIP"}\n```'), 'SKIP')
        for text in ('TAKE', '{"decision": "BUY"}', '[1]', ''):
            self.assertIsNone(parse_decision(text))

    def test_majority_vote_invalid_as_skip_and_comparison_with_take_all(self):
        outcomes = [{'card_id': c, 'pnl_usd_at_budget': p, 'trade_date': d, 'symbol': 'US.X'}
                    for c, p, d in (('a', 300.0, 'D1'), ('b', -100.0, 'D1'), ('c', -100.0, 'D2'), ('d', -50.0, 'D2'))]
        votes = {'a': ['TAKE', 'TAKE', 'SKIP'], 'b': ['SKIP', 'SKIP', 'SKIP'],
                 'c': ['TAKE', None, None], 'd': ['SKIP', 'TAKE', None]}
        with tempfile.TemporaryDirectory() as tmp:
            result = score(*_write(tmp, outcomes, votes))
        self.assertEqual((result['take_rate'], result['invalid_answers'], result['stable_cards']), (0.25, 3, 1))
        self.assertEqual(result['agent']['total_usd'], 300.0)
        self.assertEqual(result['take_all']['total_usd'], 50.0)
        self.assertEqual(result['agent_minus_take_all_usd'], 250.0)
        # only one card of four is taken; a random single card reaches 300 one time in four
        self.assertAlmostEqual(result['p_vs_random_same_size'], 0.25, delta=0.03)
        self.assertFalse(result['passed'])

    def test_parse_probability_needs_a_number_in_range(self):
        self.assertEqual(parse_probability('{"p_big_win": 0.2, "reason": "x"}'), 0.2)
        for text in ('{"p_big_win": 1.5}', '{"p_big_win": "0.2"}', '{"p_big_win": true}', 'nope'):
            self.assertIsNone(parse_probability(text))

    def test_rank_mode_skips_the_lowest_mean_probability(self):
        outcomes = [{'card_id': c, 'pnl_usd_at_budget': p, 'trade_date': 'D1', 'symbol': 'US.X'}
                    for c, p in (('a', 300.0), ('b', -100.0), ('c', -100.0), ('d', -50.0))]
        votes = {'a': [0.3, 0.3, 0.3], 'b': [0.01, 0.02, 0.0], 'c': [0.2, 0.1, 0.15], 'd': [0.1, 0.1, 0.1]}
        with tempfile.TemporaryDirectory() as tmp:
            result = score(*_write(tmp, outcomes, votes), skip_lowest=0.25)
        self.assertEqual({k for k, v in result['decisions'].items() if not v['take']}, {'b'})
        self.assertEqual(result['agent']['total_usd'], 150.0)

    def test_missing_answers_stop_the_scoring(self):
        outcomes = [{'card_id': 'a', 'pnl_usd_at_budget': 1.0, 'trade_date': 'D1', 'symbol': 'US.X'}]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                score(*_write(tmp, outcomes, {}))


if __name__ == '__main__':
    unittest.main()
