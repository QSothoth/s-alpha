"""RB1 (notes/PREREG_RB1.md): the breakeven step of the registered P1B on the fixed engine, compare.one metrics.

    nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.qullamaggie.rb1
"""
import gc
import json
from pathlib import Path

from studies.trader_replication import compare as C, systems as SY

CANDS = {'B0': {}, 'B1': {'trim_day_breakeven': True, 'breakeven_r': 0.0}, 'B2': {'breakeven_r': 0.0},
         'B3': {'breakeven_r': 1.0}}
OUT = Path(__file__).resolve().parent / 'reports' / 'rb1.json'


def main():
    x = SY.get('qullamaggie')
    st, cfg = x.study, x.config
    res = {'prereg': 'notes/PREREG_RB1.md', 'base': x.version, 'configs': {}, 'results': {}}
    for k, ch in CANDS.items():
        c = dict(cfg, rule_opts={**cfg['rule_opts'], **ch})
        res['configs'][k] = c
        for m in ('us', 'hk', 'cn'):
            r = C.one('qullamaggie', st, c, m, f'RB1 {k}')
            res['results'].setdefault(k, {})[m] = {q: r[q] for q in ('total', 'by_year', 'maxdd', 'trades', 'win', 'payoff',
                                                                   'pnl_top10', 'median_days_win', 'placebo', 'gate')}
            gc.collect()
    us = {k: v['us'] for k, v in res['results'].items()}
    ok = [k for k, v in us.items() if v['gate']['ok'] and v['total'] > v['placebo']['median']]
    best = max(ok, key=lambda k: us[k]['total']) if ok else None
    res['chosen'] = best if best and us[best]['total'] > us['B0']['total'] else 'B0'
    OUT.write_text(json.dumps(res, indent=1, default=float, ensure_ascii=False), encoding='utf-8')
    print('CHOSEN', res['chosen'])


if __name__ == '__main__':
    main()
