"""Audit whether HC previous-close position marks actually have a prior-session bar."""
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from itertools import groupby
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_replication import preopen, system
from studies.trader_replication import martin_continue_hc as hc
from studies.trader_replication.martin_continue_dq import sha
from studies.trader_replication.martin_continue_du import REPORTS
from studies.trend_breakout.panel import factors


def holding_requests(results):
    required = defaultdict(set)
    for name, account in results.items():
        days = [d['day'] for d in account['plans']]
        if len(days) != len(set(days)) or days != sorted(days):
            raise ValueError('invalid account session calendar')
        for t in account['trades']:
            first = bisect_right(days, t['entry'])
            last = bisect_right(days, t['exit'])
            for i in range(first, last):
                if i == 0:
                    raise AssertionError('no preceding session')
                required[(t['code'], days[i - 1])].add((name, days[i]))
    return required


def main():
    path = REPORTS / 'strong_continue_hc.json'
    ref = json.loads(path.read_text())
    if (ref['script_sha256'] != sha(Path(hc.__file__)) or ref['system_sha256'] != sha(Path(system.__file__)) or
            ref['planner_sha256'] != sha(Path(preopen.__file__))):
        raise ValueError('HC source differs')
    ds = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    if ds.digest() != ref['dataset_digest']:
        raise ValueError('frozen data differs')
    required = holding_requests(ref['results'])
    del ref
    by_code = defaultdict(set)
    for code, day in required:
        by_code[code].add(day)
    actions, found, bad = ds.actions(), set(), {}
    for code, group in groupby(ds.rows(), key=lambda r: r[0]):
        if code not in by_code:
            continue
        records = [(day, values) for _, day, values in group]
        dates = np.array([r[0] for r in records])
        close = np.array([r[1][3] for r in records], dtype=float)
        adj = factors(close, dates, actions.get(code, []))
        for day, raw, factor in zip(dates, close, adj):
            if day not in by_code[code]:
                continue
            key = (code, str(day))
            found.add(key)
            value = float(np.float32(raw * factor))
            if not np.isfinite(value) or value <= 0:
                bad[key] = 'invalid_adjusted_close'
    for key in required.keys() - found:
        bad[key] = 'missing_previous_session'
    records = [{'account': account, 'day': day, 'code': code, 'previous_day': prior, 'reason': reason}
               for (code, prior), reason in sorted(bad.items()) for account, day in sorted(required[(code, prior)])]
    summary = {}
    for name in sorted(results_names(required)):
        all_pairs = sum(1 for identities in required.values() for account, _ in identities if account == name)
        stale = [r for r in records if r['account'] == name]
        summary[name] = {'prior_position_marks': all_pairs, 'stale_marks': len(stale),
                         'by_year': dict(Counter(r['day'][:4] for r in stale))}
    out = {'dataset_digest': ds.digest(), 'hc_sha256': sha(path), 'script_sha256': sha(Path(__file__)),
           'summary': summary, 'stale': records}
    target = REPORTS / 'strong_continue_hc_marks.json'
    target.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')) + '\n')
    print('wrote', target, summary, flush=True)


def results_names(required):
    return {name for identities in required.values() for name, _ in identities}


if __name__ == '__main__':
    main()
