"""Engineering gate (docs/TRADER_PROTOCOL_CN.md §2) on the carried long-short configuration over the whole window
(after the single validation): look-ahead at the protocol's cut days, fills inside the day's range, win rate.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.marios_stamatoudis.gate_check r1.json s1.json
"""
from __future__ import annotations

import json
import sys

from studies.marios_stamatoudis import replicate as R
from studies.trader_replication import gate as G, shorts


def main(report, short_report=''):
    S = R.STUDY
    cfg = S.config(report)
    if short_report:
        sc = json.loads((S.reports / short_report).read_text(encoding='utf-8'))['chosen_short']
        if sc:
            cfg = dict(cfg, short=sc)
    W = shorts.wrap(S)
    A = S.arrays('us')
    entries, rules, mask, pool = W.build(A, cfg)
    st, tr = S.run(A, entries, R.WINDOW, pool, rules, placebo=0, audit=True)
    out = dict(report=report, short_report=short_report, fills=G.check_fills(A, tr), win=G.check_win(tr),
               lookahead=G.check_lookahead(W, cfg, 'us', full=A))
    out['ok'] = all(v['ok'] for v in out.values() if isinstance(v, dict) and 'ok' in v)
    print(json.dumps({k: (v if k != 'fills' else {a: b for a, b in v.items() if a != 'bad'}) for k, v in out.items()},
                     default=float))
    (S.out / f'gate_{S.tag(report, "chosen")}_window.json').write_text(json.dumps(out, indent=1, default=float),
                                                                     encoding='utf-8')
    return out


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else '')
