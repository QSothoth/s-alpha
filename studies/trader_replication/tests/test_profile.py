import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from studies.trader_replication import profile


def example():
    meta = {'source': 'user decision', 'date': '2026-01-01'}
    cfg = {key: {'value': 'set', **meta} for key in profile.SECTIONS}
    cfg['goal'] = [{'quote': 'follow the trader', **meta}]
    cfg['selection_years'] = ['2024']
    cfg['holdout'] = {'year': '2025'}
    cfg['profile_meta'] = {'selection_years': meta, 'holdout': meta}
    cfg['datasets'] = {'items': [{'name': 'market', 'path': 'frozen', 'schema': {'files': ['bars']}}], **meta}
    cfg['capital'] = {'profiles': {'cash': {'initial': 1}}, 'acceptance_profile': 'cash',
                      'definition': 'close then reduce next open', 'optimizable': 'position size', **meta}
    cfg['regime'] = {key: {'value': 'set', **meta} for key in profile.REGIME_FIELDS}
    cfg['regime'].update(meta, enabled=True, states=['up'],
                         words=[{'text': 'market changes', **meta}],
                         calendar={'version': 'one', 'status': 'frozen'})
    item = {'value': 0, **meta}
    card = {k: copy.deepcopy(item) for k in profile.BEHAVIOUR}
    cfg['behaviour_card'] = {'2024': copy.deepcopy(card), '2025': copy.deepcopy(card),
                             'by_state': {'2024': {'up': copy.deepcopy(card)},
                                          '2025': {'up': copy.deepcopy(card)}}}
    return cfg


class ProfileTest(unittest.TestCase):
    def test_complete_and_render(self):
        cfg = example()
        self.assertEqual(profile.inspect(cfg)[1], [])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            p = subprocess.run([sys.executable, '-m', 'studies.trader_replication.profile',
                                'render', '--config', str(path)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            rendered = (path.parent / 'PROFILE_CN.md').read_text(encoding='utf-8')
            self.assertIn('怎么衡量', rendered)
            self.assertIn('behaviour_card.by_state.2025.up.side', rendered)

    def test_missing_field_exits_nonzero(self):
        cfg = example()
        del cfg['behaviour_card']['by_state']['2024']['up']['side']
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps(cfg), encoding='utf-8')
            p = subprocess.run([sys.executable, '-m', 'studies.trader_replication.profile',
                                'check', '--config', str(path)], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('behaviour_card.by_state.2024.up.side: 缺值', p.stdout)

    def test_missing_source_and_date_are_reported(self):
        cfg = example()
        del cfg['behaviour_card']['2024']['win']['source']
        del cfg['behaviour_card']['2024']['win']['date']
        errors = profile.inspect(cfg)[1]
        self.assertIn('behaviour_card.2024.win: 缺来源', errors)
        self.assertIn('behaviour_card.2024.win: 缺有效来源日期（YYYY-MM-DD）', errors)

    def test_missing_measure_is_reported(self):
        cfg = example()
        with patch.dict(profile.MEASURES, {'win': ('', '')}):
            self.assertIn('behaviour_card.2024.win: 缺衡量列', profile.inspect(cfg)[1])

    def test_unavailable_requires_reason_and_drafts_do_not_pass(self):
        cfg = example()
        cfg['behaviour_card']['2024']['days'] = {'status': '不适用', 'source': 'x', 'date': '2026-01-01'}
        self.assertIn('behaviour_card.2024.days: 不适用 缺理由', profile.inspect(cfg)[1])
        cfg['behaviour_card']['2024']['days']['reason'] = 'not observed'
        self.assertEqual(profile.inspect(cfg)[1], [])
        cfg['behaviour_card']['2024']['days']['status'] = '草稿'
        self.assertIn('behaviour_card.2024.days: 草稿未确认', profile.inspect(cfg)[1])

    def test_metadata_alone_is_not_a_value_and_pending_calendar_fails(self):
        cfg = example()
        cfg['capital'] = {'source': 'user', 'date': '2026-01-01'}
        cfg['regime']['calendar']['status'] = '待重判'
        errors = profile.inspect(cfg)[1]
        self.assertIn('capital: 缺值', errors)
        self.assertIn('capital.profiles: 缺值', errors)
        self.assertIn('regime.calendar: 日历待重判或未冻结', errors)

    def test_render_still_works_with_incomplete_sections(self):
        cfg = example()
        cfg['datasets']['items'] = None
        cfg['capital']['profiles'] = None
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'PROFILE_CN.md'
            errors = profile.render(cfg, output)
            self.assertIn('datasets.items: 缺数据集清单', errors)
            self.assertIn('capital.profiles: 缺值', errors)
            self.assertIn('缺数据集清单', output.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
