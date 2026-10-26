"""Sam Miesse (ApatheticTrader) through skills/trader-replication: intraday shorts of small caps that gap up into a
parabolic move, entered at a fixed time, hard stop, out the same day (Chat With Traders 291, YouTube ZCmCoYRJwi0,
notes/RULES_CN.md).  His numbers: about 400 round trips a year, five or fewer a day, 2019 +800%, 2020 -> 2.2M,
2022-2023 "basically a wash", 2024 "up like 100%" (October 2024).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.sam_miesse.replicate round R1
    $PY -m studies.sam_miesse.replicate validate r1.json

Daily bars only: the short is filled at the open (his entry minute is not public), stopped at open x (1 + stop) when
the day's high reaches it (before any fall: conservative), else covered at the close.  No dated trades are public:
fidelity is his trade count and his years.  Shorts win more often than momentum longs; the 35% win-rate ceiling is
not used (notes/PREREG_R1.md).  Locates are not in the data: each short pays `locate` of its value on top of costs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

from studies.trader_replication import panels, study, system as Y
from studies.trader_screens import screens as S
from studies.trader_options.goal import GoalMixin

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

DRAFT = dict(
    gap=.20,                      # the open at least 20% above the prior close ("gapping stocks overnight")
    price=(1.0, 20.0),            # small caps: the prior close between 1 and 20 USD (researcher values)
    turnover_max=50e6,            # little institutional involvement: 20-day turnover under 50M USD before the gap
    run=0.0,                      # > 0: also up at least this much over the 5 sessions before the gap (parabolic)
    stop=.20,                     # hard stop above the open
    priority='gap',               # biggest gap first
    max_new=5,                    # "five and under on average"
    locate=.005,                  # locate fee, a share of the short's value
    rule_opts=dict(risk=.02, max_position=.25, max_gross=2.0, max_open=10, trail='', trims=()),
)


class Sam(GoalMixin, study.Study):
    id, name = 'sam_miesse', 'Sam Miesse'
    root = ROOT / 'studies' / 'sam_miesse'
    ledger = None
    full = SELECT
    home = ('us',)
    his = {'2024': dict(ret=1.0)}
    his_behaviour = dict(per_year=400)
    base = DRAFT
    periods = {'2024': ('2024-01-02', '2024-12-31', 1.0), '2025': ('2025-01-02', '2025-12-31', None),
               '2023 (behaviour only)': ('2023-01-03', '2023-12-29', 0.0), '2026 (used)': ('2026-01-02', '2026-10-16', None)}
    goal_behaviour = dict(per_year=400)
    starts = ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02')

    data_tag = 'trader-data-v1'        # a round's "data" key (and a config's) switches the frozen dataset

    def arrays(self, market, upto=None, mode=None):
        os.environ['TRADER_DATA_TAG'] = self.data_tag
        return panels.arrays(market, upto, mode)

    def round(self, name):
        spec = json.loads((self.rounds / f'{name}.json').read_text(encoding='utf-8'))
        self.data_tag = spec.get('data', 'trader-data-v1')
        return super().round(name)

    def ledger_sets(self, A):
        return [], []

    def pool(self, A, cfg):
        """Names a gap short could come from, as of the prior close: price band and turnover ceiling."""
        F = A['F']
        lo, hi = cfg.get('price', (1.0, 20.0))
        with np.errstate(invalid='ignore'):
            return (F.raw >= lo) & (F.raw <= hi) & (F.to20 <= cfg.get('turnover_max', 50e6)) & np.isfinite(F.c)

    def build(self, A, cfg, trace=None):
        F = A['F']
        o, h, l, c = F.o, F.h, F.l, F.c
        pool = lag(self.pool(A, cfg))
        with np.errstate(invalid='ignore', divide='ignore'):
            gap = o / lag(c) - 1
            m = pool & (gap >= cfg.get('gap', .20)) & np.isfinite(c)
            if cfg.get('run'):
                m &= lag(F.ret(5)) >= cfg['run']
            if cfg.get('d2'):                                     # day two of the move: the prior session closed
                m &= lag(F.ret(1)) >= cfg['d2']                   # at least this far above its own prior close
            if cfg.get('gap_max'):
                m &= gap <= cfg['gap_max']
            if cfg.get('vol_mult'):                               # premarket interest proxy: the day's volume
                pass                                              # is not known at the open; not used
        stop = cfg.get('stop', .20)
        entries = [[] for _ in range(len(c))]
        pri = cfg.get('priority', 'gap')
        spike = cfg.get('spike', 0.0)               # > 0: sell into the morning push, a limit this far above the
        if spike:                                   # open (his fixed entry minute is not public)
            m = m & (h >= o * (1 + spike))
        ext = cfg.get('ext', 0.0)                   # > 0: sell the hyperextension, a limit at prior close x (1 + ext)
        if ext:                                     # (at the open when it opens above), whenever the day reaches it
            with np.errstate(invalid='ignore'):
                lvl = lag(c) * (1 + ext)
                m = m & (h >= lvl)
        for d, j in zip(*np.nonzero(m)):
            f = max(float(o[d, j]), float(lvl[d, j])) if ext else float(o[d, j]) * (1 + spike)
            st = f * (1 + stop)
            ex = st if h[d, j] >= st else float(c[d, j])
            pr = -float(gap[d, j]) if pri == 'gap' else float(gap[d, j])
            entries[d].append((pr, int(j), -1, f, st, 'gap', ex))
        ro = dict(cfg.get('rule_opts', {}))
        ro['trims'] = tuple(ro.get('trims', ()))
        ro['sell_cost'] = ro.get('sell_cost', .0005) + cfg.get('locate', 0.0)
        rules = Y.Rules(**ro, intraday_kinds=('gap',), max_new_all=cfg.get('max_new', 5))
        A['kind_pools'] = None
        return entries, rules, m, pool

    def robust_variants(self, cfg):
        """The account nudges plus one step either side of the knobs R6-R9 moved (gap floor, push, stop)."""
        v = super().robust_variants(cfg)
        v.update({'gap -5%': {'gap': cfg['gap'] - .05}, 'gap +5%': {'gap': cfg['gap'] + .05},
                  'spike -2%': {'spike': max(cfg.get('spike', 0) - .02, 0.0)}, 'spike +2%': {'spike': cfg.get('spike', 0) + .02},
                  'stop 25%': {'stop': .25}, 'stop 35%': {'stop': .35}})
        return v

    def robust(self, report, key='chosen'):
        self.data_tag = self.config(report, key).get('data', 'trader-data-v1')
        return super().robust(report, key)

    def validate(self, report, key='chosen'):
        cfg = self.config(report, key)
        self.data_tag = cfg.get('data', 'trader-data-v1')
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        out = {'report': report, 'config': cfg}
        for nm, seg in (('y2023', ('2023-02-01', '2023-12-29')), ('select', SELECT), ('validate', VALIDATE),
                        ('window', WINDOW)):
            st, tr = self.run(A, entries, seg, pool, rules, audit=True)
            st.pop('_curve', None)
            out[nm] = st
            print('VALIDATE', nm, f"total {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                  f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, 'n', st['trades'], 'win', st['win'],
                  'avg', st.get('avg_win'), st.get('avg_loss'), flush=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'validate_{report.replace(".json", "")}_{key}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out


STUDY = Sam()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    else:
        study.main(STUDY, sys.argv)
