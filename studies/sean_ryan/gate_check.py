"""Engineering gate (docs/TRADER_PROTOCOL_CN.md §2) on a Sean Ryan round's chosen configuration, before it is
proposed for registration: no look-ahead at the protocol's cut days, every fill inside the day's range and the
win-rate ceiling over the common window.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.sean_ryan.gate_check r7.json
"""
from __future__ import annotations

import json
import sys

from studies.sean_ryan import replicate as R
from studies.trader_replication import gate as G


def main(report, key='chosen', seg='select'):
    """seg 'select' (before the validation segment is opened) or 'window' (after it)."""
    S = R.STUDY
    cfg = S.config(report, key)
    A = S.arrays('us')
    entries, rules, mask, pool = S.build(A, cfg)
    st, tr = S.run(A, entries, R.SELECT if seg == 'select' else R.WINDOW, pool, rules, placebo=0, audit=True)
    out = dict(report=report, segment=seg, fills=G.check_fills(A, tr), win=G.check_win(tr),
               lookahead=G.check_lookahead(S, cfg, 'us', full=A))
    out['ok'] = all(v['ok'] for v in out.values() if isinstance(v, dict) and 'ok' in v)
    print(json.dumps({k: (v if k != 'fills' else {a: b for a, b in v.items() if a != 'bad'}) for k, v in out.items()},
                     default=float))
    S.out.mkdir(parents=True, exist_ok=True)
    (S.out / f'gate_{S.tag(report, key)}_{seg}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'chosen', sys.argv[3] if len(sys.argv) > 3 else 'select')
