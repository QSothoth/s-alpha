"""FF: summarize the fixed FE random-account runs, including precision-unknown exclusions."""
import json
from pathlib import Path

import numpy as np
from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_fe as fe
from studies.trader_replication.martin_continue_dq import sha


def summarize(real, draws):
    result = {}
    for period in ('total', '2024', '2025', '2026'):
        actual = real['total'] if period == 'total' else real['by_year'][period]
        values = np.array([x['total'] if period == 'total' else x['by_year'][period] for x in draws])
        result[period] = {'real': actual, 'median': float(np.median(values)),
                          'p90': float(np.percentile(values, 90)), 'strictly_below': int(np.sum(values < actual)),
                          'draws': len(draws), 'min': float(np.min(values)), 'max': float(np.max(values))}
    for metric in ('maxdd', 'win', 'payoff'):
        values = np.array([x[metric] for x in draws])
        result[metric] = {'real': real[metric], 'median': float(np.median(values)),
                          'p90': float(np.percentile(values, 90))}
    for year in ('2024', '2025', '2026'):
        values = [x['entries_by_year'][year] for x in draws]
        result[year]['entries'] = {'real': real['entries_by_year'][year], 'median': float(np.median(values)),
                                   'min': min(values), 'max': max(values)}
    return result


def main():
    root = du.REPORTS
    path = root / 'strong_continue_fe.json'
    data = json.loads(path.read_text())
    if data['script_sha256'] != sha(Path(fe.__file__)) or len(data['random']) != fe.DRAWS:
        raise ValueError('FE source or draw count differs')
    clean = [x for x in data['random'] if not x['precision_unknown']]
    out = {'fe_sha256': sha(path), 'script_sha256': sha(Path(__file__)),
           'unknown_draws': len(data['random']) - len(clean),
           'unknown_orders': sum(len(x['precision_unknown']) for x in data['random']),
           'draws_with_shortage': sum(bool(x['shortages']) for x in data['random']),
           'all': summarize(data['real'], data['random']), 'precision_known': summarize(data['real'], clean)}
    target = root / 'strong_continue_ff.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
