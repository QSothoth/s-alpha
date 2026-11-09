"""Independently compare the saved gap-price account and order paths."""
from collections import Counter
import json
from pathlib import Path

from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication import martin_continue_hd as hd
from studies.trader_replication import preopen, system
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import REPORTS


def compare_plans(left, right):
    def index(plans):
        result = {}
        for day in plans:
            for order in day['orders']:
                key = (day['day'], order['type'], order['kind'], order['code'])
                if key in result:
                    raise AssertionError('duplicate plan key')
                result[key] = order
        return result
    if [d['day'] for d in left] != [d['day'] for d in right]:
        raise AssertionError('plan calendars differ')
    a, b = index(left), index(right)
    common = a.keys() & b.keys()
    submitted = [k for k in common if a[k]['status'] == b[k]['status'] == 'submitted']
    status_changed = [k for k in common if (a[k]['status'], a[k].get('execution')) !=
                      (b[k]['status'], b[k].get('execution'))]
    fraction_days = [x['day'] for x, y in zip(left, right) if x['fraction'] != y['fraction']]
    return {'left_only': len(a.keys() - b.keys()), 'right_only': len(b.keys() - a.keys()),
            'status_changed': len(status_changed), 'submitted_both': len(submitted),
            'shares_differ': sum(abs(a[k]['shares'] - b[k]['shares']) > 1e-12 for k in submitted),
            'fraction_changed_days': fraction_days}


def main():
    hp, dp = REPORTS / 'strong_continue_hc.json', REPORTS / 'strong_continue_hd.json'
    h, d = json.loads(hp.read_text()), json.loads(dp.read_text())
    if (d['script_sha256'] != sha(Path(hd.__file__)) or h['script_sha256'] != sha(Path(hc.__file__)) or
            d['hc_sha256'] != sha(hp) or d['dataset_digest'] != h['dataset_digest'] or
            d['system_sha256'] != sha(Path(system.__file__)) or d['planner_sha256'] != sha(Path(preopen.__file__))):
        raise ValueError('source or data differs')
    out = {}
    for name, left in h['results'].items():
        right = d['same_open'][name]
        a = Counter(tuple(t) for t in left['trade_keys'])
        b = Counter(tuple(t) for t in right['trade_keys'])
        plans = compare_plans(left['plans'], right['plans'])
        if a != b or plans['left_only'] or plans['right_only'] or plans['status_changed']:
            raise AssertionError('reported identities or execution status differ: ' + name)
        out[name] = {'identical_trade_keys': sum(a.values()), **plans}
    target = REPORTS / 'strong_continue_hd_verify.json'
    target.write_text(json.dumps({'hc_sha256': sha(hp), 'hd_sha256': sha(dp),
                                  'script_sha256': sha(Path(__file__)), 'results': out},
                                 ensure_ascii=False, separators=(',', ':')) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
