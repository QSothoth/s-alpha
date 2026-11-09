"""E8c trades: did the stock run after our entry, and if so why did we not keep it."""
from contextlib import ExitStack
import json
import sys
from unittest.mock import patch

import numpy as np

sys.path.insert(0, '/opt/opend-us-options/.claude/worktrees/gap-review')
from studies import trader_data as TD
from studies.trader_data import panel as TP
from studies.martin_luk import ie47_e1 as M
from studies.martin_luk.e1_board_smoke import offline

REP = '/opt/opend-us-options/.claude/worktrees/gap-review/studies/martin_luk/reports/'
OUT = REP+'e9_work/why_lose_rows.json'


def main():
    A = M.IE47Study().arrays('us')
    days = list(map(str, A['days']))
    di, ci = {d: i for i, d in enumerate(days)}, {str(c): j for j, c in enumerate(A['codes'])}
    h, l, c = A['high'], A['low'], A['close']
    rows = []
    for t in json.load(open(REP+'e8_work/full_trades.json')):
        if 'exit' not in t or t.get('exit') is None:
            continue
        i, j, x = di[t['entry']], ci[t['code']], di[t['exit']]
        end = min(len(days), i+61)
        hh = h[i+1:end, j]
        if not len(hh) or not np.isfinite(hh).any():
            continue
        k = int(np.nanargmax(hh))
        peak = float(hh[k]/t['fill']-1)
        low_before = float(np.nanmin(l[i+1:i+2+k, j])/t['fill']-1)
        # first day the low reached our initial stop
        hit = np.flatnonzero(l[i+1:end, j] <= t['stop'])
        rows.append(dict(code=t['code'], entry=t['entry'], year=t['entry'][:4], why=t['why'], ret=t['ret_invested'],
                         r=t['r'], days=t['days'], risk=t['risk_pct'], peak=peak, peak_day=k+1,
                         dip_before_peak=low_before, stop_day=int(hit[0])+1 if len(hit) else None,
                         exit_vs_peak=x-i < k+1))
    json.dump(rows, open(OUT, 'w'))
    print(len(rows))


if __name__ == '__main__':
    offline()
    original = TP.build
    def existing_load(market, mode=None, version=None, upto=None, **kwargs):
        return original(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def read_only_build(ds, upto=None, cache=True, write_cache=True):
        return original(ds, upto=upto, cache=cache, write_cache=False)
    with ExitStack() as s:
        s.enter_context(patch.object(TD, 'load', existing_load))
        s.enter_context(patch.object(TP, 'build', read_only_build))
        main()
