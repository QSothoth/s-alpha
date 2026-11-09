"""EO: reconstruct ASH's potential-scan eligibility around the cutoff."""
import json
from pathlib import Path

import numpy as np
from studies import trader_data
from studies.trader_data.panel import cache_path
from studies.trend_breakout.panel import factors
from studies.trader_replication import watchlist
from studies.trader_replication.martin_continue_dq import ROOT, sha

CODE, DAY, CUT = 'US.ASH', '2026-05-12', '2026-06-30'


def reconstruct(days, raw, actions):
    stock_days = sorted(raw)
    r = np.array([raw[d] for d in stock_days], dtype=float)
    factor = factors(r[:, 3], np.array(stock_days), actions)
    price = [(r[:, k] * factor).astype(np.float32) for k in range(4)]
    o, h, l, c = price
    h = np.fmax(h, np.fmax(o, c))
    l = np.fmin(l, np.fmin(o, c))
    all_h = np.full((len(days), 1), np.nan, np.float32)
    all_l = np.full((len(days), 1), np.nan, np.float32)
    all_t = np.full((len(days), 1), np.nan, np.float32)
    idx = {day: i for i, day in enumerate(days)}
    indices = [idx[d] for d in stock_days]
    all_h[indices, 0], all_l[indices, 0] = h, l
    all_t[indices, 0] = r[:, 5].astype(np.float32)
    with np.errstate(divide='ignore', invalid='ignore'):
        ranges = all_h / all_l - 1
        adr = watchlist.roll_mean(ranges, 5)[:, 0]
        turnover = watchlist.roll_mean(all_t, 20)[:, 0]
    i = idx[DAY]
    return {'adr5': float(adr[i]), 'turnover20': float(turnover[i]),
            'adr_ok': bool(adr[i] >= .035), 'turnover_ok': bool(turnover[i] >= 5e7),
            'last5': [{'day': days[k], 'high': float(all_h[k, 0]), 'low': float(all_l[k, 0]),
                       'range': float(ranges[k, 0]), 'raw': raw.get(days[k])}
                      for k in range(i - 4, i + 1)]}


def main():
    root = ROOT / 'studies/trader_replication/reports/gap_review'
    full_path, cut_path = root / 'strong_continue_en_full.json', root / 'strong_continue_en_cut.json'
    full, cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    base = trader_data.dataset('us', mode='frozen', version='trader-data-v1')
    cache = cache_path(base)
    if not cache.exists():
        raise ValueError('existing frozen panel cache required for the exact market calendar')
    with np.load(cache) as p:
        if str(p['digest']) != base.digest():
            raise ValueError('cached market calendar digest differs')
        days = list(map(str, p['days']))
    raw = {}
    for code, day, values in base.rows():
        if code == CODE:
            if day in raw:
                raise ValueError('duplicate bar')
            raw[day] = values
    actions = base.actions().get(CODE, [])
    full_result = reconstruct(days, raw, actions)
    cut_result = reconstruct([d for d in days if d <= CUT], {d: v for d, v in raw.items() if d <= CUT}, actions)
    if not (full_result['adr_ok'] and full_result['turnover_ok'] and not (cut_result['adr_ok'] and cut_result['turnover_ok'])):
        raise AssertionError('single-stock eligibility does not reproduce EN')
    if CODE not in full['potentials'][-1]['selected'] or CODE in cut['potentials'][-1]['selected']:
        raise AssertionError('EN selected list changed')
    out = {'en_full_sha256': sha(full_path), 'en_cut_sha256': sha(cut_path), 'script_sha256': sha(Path(__file__)),
           'dataset_digest': base.digest(), 'calendar_cache_sha256': sha(cache), 'code': CODE, 'day': DAY,
           'actions_after_cut': [a for a in actions if CUT < a[0] <= days[-1]],
           'full': full_result, 'cut': cut_result}
    target = root / 'strong_continue_eo.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
