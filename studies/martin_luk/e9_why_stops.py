from contextlib import ExitStack
import json, sys
from unittest.mock import patch
import numpy as np
sys.path.insert(0, '/opt/opend-us-options/.claude/worktrees/gap-review')
from studies import trader_data as TD
from studies.trader_data import panel as TP
from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.e1_board_smoke import offline
REP = '/opt/opend-us-options/.claude/worktrees/gap-review/studies/martin_luk/reports/'

def main():
    A = M.IE47Study().arrays('us')
    days = list(map(str, A['days'])); di = {d: i for i, d in enumerate(days)}
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    o, h, l, c = A['open'], A['high'], A['low'], A['close']
    T = [t for t in json.load(open(REP+'e8_work/full_trades.json')) if t.get('exit')]
    by = {}
    for t in T: by.setdefault(t['code'], []).append(t)
    out = {}
    for seg, ok in (('2024-25', lambda y: y < '2026'), ('2026', lambda y: y == '2026')):
        stopped = [t for t in T if ok(t['entry'][:4]) and t['why'] in ('stop', 'gap_stop')]
        rows = []
        for t in stopped:
            i, j, x = di[t['entry']], ci[t['code']], di[t['exit']]
            end = min(len(days), i+61)
            peak = np.nanmax(h[i+1:end, j])/t['fill']-1
            back = np.flatnonzero(c[x+1:end, j] > t['fill'])          # first close back above our fill
            later = [u for u in by[t['code']] if t['entry'] < u['entry'] <= days[end-1]]
            rows.append(dict(peak=peak, day1=x-i == 1, close_above_stop=c[x, j] > t['stop'],
                             gap=t['why'] == 'gap_stop', back=int(back[0])+1 if len(back) else None,
                             rebought=len(later), rebought_ret=sum(u['ret_invested'] for u in later),
                             entry_close_off_low=t['fill']/l[i, j]-1, break_over_pdh=t['fill']/h[i-1, j]-1))
        big = [r for r in rows if r['peak'] >= .33]
        f = lambda rs, k: float(np.mean([r[k] for r in rs]))
        out[seg] = dict(stopped=len(rows), big=len(big),
                        day1_share=f(rows, 'day1'), big_day1=f(big, 'day1'),
                        close_above_stop_share=f(rows, 'close_above_stop'), big_close_above_stop=f(big, 'close_above_stop'),
                        gap_share=f(rows, 'gap'),
                        big_back_median=float(np.median([r['back'] for r in big if r['back']])),
                        big_back_within10=float(np.mean([r['back'] is not None and r['back'] <= 10 for r in big])),
                        big_rebought_share=float(np.mean([r['rebought'] > 0 for r in big])),
                        entry_off_low_median=float(np.median([r['entry_close_off_low'] for r in rows])),
                        break_over_pdh_median=float(np.median([r['break_over_pdh'] for r in rows])))
    print(json.dumps(out, indent=1))

if __name__ == '__main__':
    offline()
    original = TP.build
    def existing_load(market, mode=None, version=None, upto=None, **kw):
        return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def read_only_build(ds, upto=None, cache=True, write_cache=True):
        return original(ds, upto=upto, cache=cache, write_cache=False)
    with ExitStack() as s:
        s.enter_context(patch.object(TD, 'load', existing_load))
        s.enter_context(patch.object(TP, 'build', read_only_build))
        main()
