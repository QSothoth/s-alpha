"""Dan Zanger through skills/trader-replication, on the Flanders machinery (entries, pools, the generic loop); only
his base breakout, stop and exits are his own.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.dan_zanger.replicate round R1
    $PY -m studies.dan_zanger.replicate validate r1.json
    $PY -m studies.dan_zanger.replicate final r1.json

No dated trades of his fall inside the data (his public picks stop in 2021 and list winners only), so there is no
ledger fidelity and no trade-count target: rounds choose on the selection segment against same-pool random entry,
and 2026 is evaluated once (notes/PREREG_R1.md).  His rules and sources: notes/RULES_CN.md.

The draft, rule by rule (RULES_CN sections in brackets):
  base      the prior `days` sessions' high-low range at most `depth` percent [2]; the pivot is their high
  trigger   the close above the pivot, at most `chase` above it ("never pay up by more than 5%"), on volume at least
            `vol` times the prior 20-day average ("at least 300%") [3]; bought at that close (daily bars cannot show
            his intraday volume read, so the breakout is close-confirmed)
  stop      `stop_pct` under the fill ('fill': "a 5% stop loss rule") or under the pivot ('pivot': "back under the
            breakout point by $3 to $5") [4]
  exits     no trailing stop; out at the next close still under the fill ("sell ... during that first day"); out when
            it "goes to sleep" (the close not above the close `sleep` sessions earlier) or breaks its trendline (a
            close under the prior 10-day low); 25% off at +15% from the fill ("sell 20-30% as it moves up 15-20%") [5]
  sizing    four names at most, a starter of 25% of equity that doubles once it closes +5% above the fill ("step into
            the stock heavy"), 2:1 gross ("2:1 margin") [6]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from studies.christian_flanders import replicate as CF
from studies.trader_replication import study
from studies.trader_screens import screens as S

ROOT = Path(__file__).resolve().parents[2]
lag = S.lag

SELECT = ('2024-01-02', '2025-12-31')
VALIDATE = ('2026-01-02', '2026-10-16')
WINDOW = ('2024-01-02', '2026-10-16')

DRAFT = dict(
    setups=['zbase'],
    entry='close',
    base=dict(days=20, depth=25.0, vol=3.0, chase=.05),
    stop='fill', stop_pct=.05,
    stop_min=.01, stop_cap=0.0,
    priority='rvol',                 # "the higher [the relative volume], the better"
    max_new=2, strength='', filter='',
    pool=dict(turnover=20e6, adr=0.0, above50=True),   # researcher: leaders trade above their 50-day line
    rule_opts=dict(risk=.0125, max_position=.50, max_gross=2.0, max_open=4, trail='', arm_trail_on_entry=False,
                   exit_signal='zexit5', nft_days=1, trims=(3,), trim_frac=.25, unit_adr='pct5',
                   add_r=1.0, add_frac=1.0),
)


class Zanger(CF.Flanders):
    id, name = 'dan_zanger', 'Dan Zanger'
    root = ROOT / 'studies' / 'dan_zanger'
    ledger = None
    cutoff = ''
    full = SELECT
    home = ('us',)
    his = {}                         # 1998-2000 only; no trade counts or win rate published
    base = DRAFT

    def ledger_sets(self, A):
        return [], []

    def named(self, A, pool, name):
        F = A['F']
        if name.startswith('pct'):                       # a fixed percent of the fill as the trims' unit
            return np.full(F.c.shape, float(name[3:]))
        if name.startswith(('zexit', 'zrev')):           # asleep (no gain over n sessions) or trendline broken;
            n = int(name.lstrip('zexitrv') or 0)         # zrev adds a down close in the lower half of the day's
            with np.errstate(invalid='ignore'):          # range on twice the 20-day volume ("no progress in spite
                out = F.c < lag(F.lo(10))                # of huge volume", a bearish reversal bar)
                if n:
                    out = out | (F.c <= lag(F.c, n))
                if name.startswith('zrev'):
                    out = out | ((F.v >= 2 * lag(F.vol(20))) & (F.c < lag(F.c)) & (F.c <= (F.h + F.l) / 2))
            return out
        if name.startswith('zsleep'):                    # asleep only (the trendline left to an EMA trail)
            with np.errstate(invalid='ignore'):
                return F.c <= lag(F.c, int(name[6:]))
        return super().named(A, pool, name)

    def robust_variants(self, cfg):
        """The account neighbours plus one step either side of his own knobs (reported, never used to choose)."""
        v = super().robust_variants(cfg)
        b = dict(DRAFT['base'], **cfg.get('base', {}))
        for d in (-5, 5):
            v[f'base days {b["days"] + d}'] = {'base': {'days': b['days'] + d}}
        for x in (-.5, .5):
            v[f'vol x{b["vol"] + x}'] = {'base': {'vol': b['vol'] + x}}
        st = cfg.get('strength', '')
        if st.startswith('rs'):
            for d in (-10, 10):
                v[f'rs{int(st[2:]) + d}'] = {'strength': f'rs{int(st[2:]) + d}'}
        tr = cfg.get('rule_opts', {}).get('trail', '')
        if tr.startswith('sma'):
            for d in (-10, 10):
                v[f'sma{int(tr[3:]) + d}'] = {'rule_opts': {'trail': f'sma{int(tr[3:]) + d}'}}
        f = cfg.get('filter', '')
        if f.startswith('IDX'):
            for d in (-10, 10):
                v[f'IDX{int(f[3:]) + d}'] = {'filter': f'IDX{int(f[3:]) + d}'}
        return v

    @staticmethod
    def passes(st, ref, gates):
        """The generic gates plus 'total' (selection-segment return at least the reference's) and 'dd+X' (drawdown at
        most X above the reference's): from R5 on, a better worse year must not come with a worse system (R4 EP)."""
        fails = study.Study.passes(st, ref, [g for g in gates if g != 'total' and not g.startswith('dd+')])
        for g in gates:
            if g == 'total' and st['total'] < ref['total']:
                fails.append(g)
            elif g.startswith('dd+') and st['maxdd'] > ref['maxdd'] + float(g[3:]):
                fails.append(g)
        return fails

    def setups(self, A, cfg):
        """zbase plus any Flanders setup named in cfg['setups'] ('ep': his "gap-ups on earnings", bought at the close
        with the day's low as stop)."""
        F = A['F']
        names = cfg.get('setups', ['zbase'])
        out = super().setups(A, dict(cfg, setups=[s for s in names if s != 'zbase'])) if names != ['zbase'] else {}
        if 'zbase' not in names:
            return out
        b = dict(DRAFT['base'], **cfg.get('base', {}))
        pool = lag(self.pool(A, cfg))
        with np.errstate(invalid='ignore', divide='ignore'):
            pivot = lag(F.hi(b['days']))
            base_ok = lag(F.range(b['days']) <= b['depth'])
            m = (pool & base_ok & (F.c > pivot) & (F.c <= pivot * (1 + b['chase']))
                 & (F.v >= b['vol'] * lag(F.vol(20))))
            if cfg.get('near_high'):                     # "leaders at or near new highs": within x of the
                m &= lag(F.c >= (1 - cfg['near_high']) * F.hi(252))   # 52-week high as of t-1
            pct = cfg.get('stop_pct', .05)
            mode = cfg.get('stop', 'fill')              # 'low': the day's low ("about $1 below the breakout")
            stop = pivot * (1 - pct) if mode == 'pivot' else F.l if mode == 'low' else F.c * (1 - pct)
        out['zbase'] = (m, pivot, stop)
        return out

    def entries(self, A, cfg, masks):
        """Flanders' close entries carry the day's low as the stop; his stop replaces it."""
        out = super().entries(A, cfg, masks)
        smin, cap = cfg.get('stop_min', .01), cfg.get('stop_cap', 0.0)
        res = []
        for d, lst in enumerate(out):
            row = []
            for e in lst:
                s = masks[e[5]][2][d, e[1]]
                if np.isfinite(s):
                    s = min(s, e[3] * (1 - smin))
                    if cap:
                        s = max(s, e[3] * (1 - cap))
                    e = (e[0], e[1], e[2], e[3], float(s), *e[5:])
                row.append(e)
            res.append(row)
        return res

    def segments(self, report, key, segs, markets=('us',)):
        cfg = self.config(report, key)
        out = {'report': report, 'config': cfg}
        for market in markets:
            A = self.arrays(market)
            entries, rules, mask, pool = self.build(A, cfg)
            for nm, seg in segs:
                st, tr = self.run(A, entries, seg, pool, rules, audit=True)
                st.pop('_curve', None)
                st['ew_hold_lagged'] = study.ew_hold(A, pool, seg, lagged=True)
                st['trades_by_year'] = {y: study.year_trades(tr, y) for y in sorted(st['by_year'])}
                st['why'] = {w: sum(t['why'] == w for t in tr) for w in sorted({t['why'] for t in tr})}
                st['top'] = sorted(({k: t[k] for k in ('code', 'entry', 'exit', 'ret', 'r', 'why')} for t in tr),
                                   key=lambda t: -t['ret'])[:10]
                out[f'{market}_{nm}'] = st
                b = st['behaviour']
                print(market, nm, f"total {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                      f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_lagged']:+.3f}",
                      {a: round(v, 3) for a, v in st['by_year'].items()}, 'n', st['trades'],
                      'win', st['win'] and round(st['win'], 3), 'avg', st.get('avg_win'), st.get('avg_loss'),
                      'hold', b['days_win'], b['days_loss'], flush=True)
            del A
        return out

    def validate(self, report, key='chosen'):
        out = self.segments(report, key, (('select', SELECT), ('validate', VALIDATE), ('window', WINDOW)))
        self.write(f'validate_{self.tag(report, key)}.json', out)

    def final(self, report, key='chosen', markets=('us', 'hk', 'cn')):
        out = self.segments(report, key, (('window', WINDOW),), markets)
        self.write(f'final_{self.tag(report, key)}.json', out)

    def write(self, name, out):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / name).write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')


STUDY = Zanger()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    else:
        study.main(STUDY, sys.argv)
