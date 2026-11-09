"""EG: demonstrate post-adjustment slicing versus an as-of raw dataset."""
import json
from pathlib import Path

from studies.trader_data import panel
from studies.trader_data.dataset import Dataset
from studies.trader_replication.martin_continue_dq import ROOT, sha
from studies.trader_replication.martin_continue_ea import LimitedDataset


class SplitExample(Dataset):
    market = 'us'

    @property
    def id(self):
        return 'synthetic-two-day-split'

    def stocks(self):
        return [{'code': 'US.TEST', 'name': 'test'}]

    def rule(self):
        return {'purpose': 'unit-test'}

    def rows(self):
        yield 'US.TEST', '2024-01-02', [100., 100., 100., 100., 10., 1000.]
        yield 'US.TEST', '2024-01-03', [50., 50., 50., 50., 20., 1000.]

    def actions(self):
        return {'US.TEST': [('2024-01-03', .5, 0.)]}

    def digest(self):
        return 'synthetic-split-data'


def compare_panels():
    ds = SplitExample()
    sliced = panel.build(ds, upto='2024-01-02', cache=False, write_cache=False)
    asof = panel.build(LimitedDataset(ds, '2024-01-02'), cache=False, write_cache=False)
    return {'sliced_days': list(map(str, sliced['days'])), 'asof_days': list(map(str, asof['days'])),
            'sliced_close': float(sliced['close'][0, 0]), 'asof_close': float(asof['close'][0, 0])}


def main():
    result = compare_panels()
    if result != {'sliced_days': ['2024-01-02'], 'asof_days': ['2024-01-02'],
                  'sliced_close': 50., 'asof_close': 100.}:
        raise AssertionError('panel cutoff behavior changed')
    paths = ['studies/trader_data/panel.py', 'studies/trader_data/dataset.py', 'studies/trader_replication/gate.py',
             'studies/trader_replication/martin_continue_bb.py', 'studies/trader_replication/martin_continue_bc.py']
    out = {'synthetic_example': result, 'source_sha256': {p: sha(ROOT / p) for p in paths},
           'script_sha256': sha(Path(__file__))}
    target = ROOT / 'studies/trader_replication/reports/gap_review/strong_continue_eg.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
