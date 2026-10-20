"""Marios Stamatoudis through skills/trader-replication, on the Qullamaggie study (the board's leader breakout and EP,
his parabolic short), with his own numbers: EPs gapping >= 5% out of a range of months, a stop at the day's low no
wider than 1 ADR, 0.3% risk, 25% per name, no margin, at most 15 names, 3 a day, a quarter sold at 3R (his 2.5-3
ADR) with the stop then at cost, the rest out on a close below the 10-day line.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
    $PY -m studies.marios_stamatoudis.replicate round R1

Rounds choose on the selection segment only (2024-01-02 -> 2025-12-31, PREREG_R0); `validate` runs the carried
configuration once on 2026-01-02 -> 2026-10-16.  His rules and sources: notes/RULES_CN.md; his trades:
notes/trades.csv (all but one dated trade are 2023, so diagnose / three move the period back to 2023-02).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from studies.qullamaggie import replicate as Q
from studies.trader_replication import study
from studies.trader_screens import screens as S

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

DRAFT = dict(
    setups=['brk', 'ep'],
    entry='close', stop_min=.01, stop_cap=0.0, priority='strength', max_new=3, strength='', filter='',
    stop_adr={'brk': 1.0, 'ep': 1.0},
    pool=dict(turnover=20e6, adr=4.0, above50=False),
    ep=dict(min_gap=.05, heavy=3.0, liquid=20e6, escape=63),
    rule_opts=dict(risk=.003, max_position=.25, max_gross=1.0, max_open=15, trail='sma10', arm_trail_on_entry=True,
                   trims=(3,), trim_frac=.25, breakeven_r=3.0, trim_day=0),
)


class Marios(Q.Qullamaggie):
    id, name = 'marios_stamatoudis', 'Marios Stamatoudis'
    root = ROOT / 'studies' / 'marios_stamatoudis'
    ledger = root / 'notes' / 'trades.csv'
    cutoff = '2024-01-01'           # PREREG_R0: the 2023 trades are the selection side; SMCI 2024-01-19 validation
    full = SELECT
    home = ('us',)
    his = {}                        # his USIC year (2023) is before the window
    his_behaviour = dict(win=.32, per_year=500)
    starts = ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02')
    base = DRAFT

    def setups(self, A, cfg):
        """The Qullamaggie setups with his liquidity floors as options.
        ep['escape'] n     the open above the prior n-day high ("escaping a range they have been in for many months")
        ep['price']        a price floor for the EP instead of the board's 5 USD (with ep['liquid'] as turnover)
        brk = {turnover, price, adr, top}   the board's leader breakout on these floors instead of 20M / 5 USD /
                           ADR 4 / top 2% (his own scan: price > 1, ADR > 5, dollar volume >= 1M a day)"""
        bo = cfg.get('brk')
        names = cfg.get('setups', ['brk', 'ep'])
        out = super().setups(A, dict(cfg, setups=[s for s in names if s != 'brk' or not bo]))
        F = A['F']
        o = cfg.get('ep', {})
        with np.errstate(invalid='ignore', divide='ignore'):
            if 'ep' in out and 'price' in o:
                m = ((F.to20 >= o.get('liquid', 20e6)) & (F.raw >= o['price'])
                     & (F.o / lag(F.c) - 1 >= o.get('min_gap', .10)) & (F.v >= o.get('heavy', 3.0) * lag(F.vol(20))))
                out['ep'] = (m, F.o, F.l)
            if 'ep' in out and o.get('escape'):
                m, lv, st = out['ep']
                out['ep'] = (m & (F.o > lag(F.hi(o['escape']))), lv, st)
            if 'brk' in names and bo:
                out['brk'] = self.leader_breakout(F, bo)
        return out

    @staticmethod
    def leader_breakout(F, bo):
        """screens.Qullamaggie's breakout (10-day tightening within 3 ADR, narrowing, higher lows, within 1 ADR of
        the base high; bought over the base high) on other floors."""
        adr = F.adr
        with np.errstate(invalid='ignore'):
            pool = (F.to20 >= bo.get('turnover', 20e6)) & (F.raw >= bo.get('price', 5.0)) & (adr >= bo.get('adr', 4.0))
            watch = pool & (S.strength(F) >= 1 - bo.get('top', .02))
            base = ((F.range(10) <= 3 * adr) & (F.range(5) < F.range(5, 5)) & (F.lo(5) > lag(F.lo(5), 5))
                    & (F.c >= F.hi(10) * (1 - adr / 100)))
        m, entry = S.triggered_from(F, watch & base, F.hi(10))
        return m, entry, F.l

    def his_entry(self, A, d, j, cfg):
        """His ticker on his day with our execution: the close, stop at the day's low (at least stop_min)."""
        c, l = A['close'][d, j], A['low'][d, j]
        if not (np.isfinite(c) and np.isfinite(l) and c > 0):
            return None
        return (0.0, j, 1, c, min(l, c * (1 - cfg.get('stop_min', .01))), 'his')

    def validate(self, report, key='chosen'):
        """The chosen configuration on the validation segment and the whole window, reported only."""
        cfg = self.config(report, key)
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        out = {'report': report, 'config': cfg}
        for name, seg in (('validate', VALIDATE), ('window', WINDOW)):
            st, tr = self.run(A, entries, seg, pool, rules, audit=True)
            st.pop('_curve', None)
            st['ew_hold_pool'] = study.ew_hold(A, pool, seg, lagged=True)
            out[name] = st
            print('VALIDATE', name, f"total {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                  f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_pool']:+.3f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, 'n', st['trades'], 'win', st['win'], flush=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'validate_{self.tag(report, key)}.json').write_text(json.dumps(out, indent=1, default=float),
                                                                       encoding='utf-8')
        return out


STUDY = Marios()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2] if len(sys.argv) > 2 else '', sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    elif len(sys.argv) > 1 and sys.argv[1] in ('diagnose', 'three'):
        STUDY.full = ('2023-02-01', SELECT[1])          # his dated trades are 2023 (data from 2023-01-03)
        study.main(STUDY, sys.argv)
    elif len(sys.argv) > 1 and sys.argv[1] == 'window':  # after the validation: three markets over the window
        STUDY.full = WINDOW
        STUDY.final(sys.argv[2])
    else:
        study.main(STUDY, sys.argv)
