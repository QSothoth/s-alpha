"""Dan Zanger through skills/trader-replication, on the Flanders machinery (entries, pools, the generic loop); only
his base breakout, stop and exits are his own.

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python"
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

# The success card (user, 2026-10-29; sources in notes/TARGET_CARD_CN.md).  Counts and days are sessions.
CARD = dict(
    per_year=(104.0, float('inf')),      # "at least 200 trades or more" in the 23 months of 1998-2000
    source='Traders\' magazine 2003 (chartpattern.com/articles/tradermag.pdf): "It had to have been at least 200 '
           'trades or more" over the 23 months of 1998-2000, his own account, a floor',
    behaviour=dict(
        open_mean=(2.0, 4.0),            # "two to four stocks in the strongest groups" (Traders World 2010)
        days_mean=(6.0, 12.0),           # "Most trades ... are about 6-12 days long" (Traders' 2003)
        median_days_win=(10.0, 40.0),    # "a couple of weeks to a couple of months" (Active Trader 2006)
        max_days=(1.0, 50.0),            # "up to ten weeks at most" (Traders' 2003, 2006-11)
    ),
    years={},                            # his record years (1998-2000) are outside the data
)
USED_VALIDATE = 'R1 R3 R5 R7 R8'         # 2026 already evaluated: rule 6 here is a reference only

# His other patterns (chart-patterns.cfm lists eleven; "sometimes falling wedges, descending trendlines, descending
# channels, sometimes horizontal channels, cup and handles", Traders World 2004).  He gives no numbers for them:
# every number below is the researcher's (notes/PREREG_R10.md).  Each is a level known at t-1 that day t closes
# over, with the base's chase and volume rules.
PATTERNS = dict(
    zflag=dict(flag=10, depth=15.0, pole=.30),       # a 10-session flag at most 15% deep after a 30% pole
    ztri=dict(days=40, depth=40.0, top=.03, recent=15),   # flat top (a second touch within 3% in the last 15
                                                     # sessions), lows of those 15 above the earlier lows
    zdtl=dict(span=60, recent=15, lower=.03),        # a line through the span's high and a lower high in the
                                                     # last 15 sessions, extended to t
    zlong=dict(days=50, depth=35.0),                 # "a long base for example 6-8 to 10 weeks" (Traders World 2006)
)

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
        """zbase and his other patterns (PATTERNS) plus any Flanders setup named in cfg['setups'] ('ep': his
        "gap-ups on earnings", bought at the close with the day's low as stop)."""
        F = A['F']
        names = cfg.get('setups', ['zbase'])
        own = [s for s in names if s == 'zbase' or s in PATTERNS]
        rest = [s for s in names if s not in own]
        out = super().setups(A, dict(cfg, setups=rest)) if rest else {}
        b = dict(DRAFT['base'], **cfg.get('base', {}))
        pool = lag(self.pool(A, cfg))
        pct = cfg.get('stop_pct', .05)
        mode = cfg.get('stop', 'fill')                  # 'low': the day's low ("about $1 below the breakout")
        with np.errstate(invalid='ignore', divide='ignore'):
            for name in own:
                pivot, ready = self.pattern(F, name, b, dict(PATTERNS.get(name, {}), **cfg.get(name, {})))
                m = (pool & ready & (F.c > pivot) & (F.c <= pivot * (1 + b['chase']))
                     & (F.v >= b['vol'] * lag(F.vol(20))))
                if name == 'zbase' and cfg.get('near_high'):   # "leaders at or near new highs": within x of
                    m &= lag(F.c >= (1 - cfg['near_high']) * F.hi(252))   # the 52-week high as of t-1
                stop = pivot * (1 - pct) if mode == 'pivot' else F.l if mode == 'low' else F.c * (1 - pct)
                out[name] = (m, pivot, stop)
        return out

    def strength_ok(self, A, cfg):
        """'grp<NN>': "two to four stocks in the strongest groups" (Traders World 2010): the name's industry ranks in
        the top (100 - NN)% of industries by its members' median RS as of t-1; a name with no industry keeps the
        stock floor RS >= 80.  Other values: Flanders'."""
        s = cfg.get('strength', '')
        if not s.startswith('grp'):
            return super().strength_ok(A, cfg)
        g = self.group_rank(A)
        own = lag(self.rs(A)) >= .8
        with np.errstate(invalid='ignore'):
            return np.where(np.isnan(g), own, g >= int(s[3:]) / 100)

    def group_rank(self, A):
        """Per day (as of t-1): the percentile of the name's industry among industries with three or more ranked
        members, by the members' median RS; NaN for names without an industry (OpenD INDUSTRY plates, a current
        snapshot: membership is taken as fixed over the window)."""
        def f():
            from studies.trader_screens import data as TSD
            ind = TSD.industries([str(c) for c in A['codes']], A['market']) if A['market'] == 'us' else {}
            labels = [ind.get(str(c), '') for c in A['codes']]
            groups = {}
            for j, g in enumerate(labels):
                if g:
                    groups.setdefault(g, []).append(j)
            groups = [np.array(ix) for ix in groups.values() if len(ix) >= 3]
            rs = self.rs(A)
            out = np.full(rs.shape, np.nan)
            for t in range(len(rs)):
                med = np.array([np.nanmedian(rs[t, ix]) if np.isfinite(rs[t, ix]).sum() >= 3 else np.nan
                                for ix in groups])
                ok = np.isfinite(med)
                if ok.sum() < 5:
                    continue
                pct = np.full(len(groups), np.nan)
                pct[ok] = (np.argsort(np.argsort(med[ok])) + .5) / ok.sum()
                for ix, p in zip(groups, pct):
                    out[t, ix] = p
            return lag(out)
        with np.errstate(invalid='ignore'):
            return A['F'].get('zanger_group_rank', f)

    @staticmethod
    def pattern(F, name, b, p):
        """(level, ready): the line day t has to close over and whether the pattern stood at t-1 (bars to t-1)."""
        if name in ('zbase', 'zlong'):
            days, depth = (b['days'], b['depth']) if name == 'zbase' else (p['days'], p['depth'])
            return lag(F.hi(days)), lag(F.range(days) <= depth)
        if name == 'zflag':
            f = p['flag']
            top = lag(F.hi(f))
            return top, lag(F.range(f) <= p['depth']) & (top >= (1 + p['pole']) * lag(F.lo(20), f + 1))
        if name == 'ztri':
            d, r = p['days'], p['recent']
            top = lag(F.hi(d))
            ready = (lag(F.range(d) <= p['depth'])
                     & (lag(F.hi(r)) >= (1 - p['top']) * top) & (lag(F.hi(d - r), r + 1) >= (1 - p['top']) * top)
                     & (lag(F.lo(r)) > lag(F.lo(d - r), r + 1)))
            return top, ready
        if name == 'zdtl':
            line = F.get(('zdtl', p['span'], p['recent'], p['lower']), lambda: trendline(F.h, **p))
            return line, np.isfinite(line) & (lag(F.c) <= line)    # a fresh break: yesterday closed under it
        raise ValueError(name)

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

    def success(self, report, key='chosen'):
        """The seven success rules (skills/trader-replication) for one configuration on the US window: the gate's
        data / look-ahead / fill checks, the win rate, the count and his behaviour (CARD), the window and 2026
        against same-pool random entry (2026 already used: a reference only), and the window rerun without the two
        best trades' entries.  reports/success_<tag>.json."""
        from studies.trader_replication import gate as G, panels, success as SU
        cfg = self.config(report, key)
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        st, tr = self.run(A, entries, WINDOW, pool, rules, audit=True)
        curve = st.pop('_curve')
        days = A['days'][(A['days'] >= WINDOW[0]) & (A['days'] <= WINDOW[1])]
        span = [str(days[0]), str(days[-1])] if len(curve) == len(days) else ['?', '?']
        pin = panels.pinned()
        checks = dict(data=G.check_data(panels.TAG, A.get('digest'), span, pin['tag'], pin['markets'].get('us'),
                                        WINDOW, A['days']),
                      fills=G.check_fills(A, tr), lookahead=G.check_lookahead(self, cfg, 'us', full=A))
        val, _ = self.run(A, entries, VALIDATE, pool, rules)
        drop, _ = self.run(A, SU.drop_top(A, entries, tr), WINDOW, pool, rules, placebo=0)
        ours = facts(st, tr, val, drop, {k: v['ok'] for k, v in checks.items()})
        rows = SU.judge(CARD, ours)
        out = dict(report=report, key=key, config=cfg, card=CARD, used_validate=USED_VALIDATE, ours=ours,
                   rules=[dict(rule=r, ok=ok, why=why) for r, ok, why in rows], passed=SU.passed(rows),
                   gate=checks, by_year=st['by_year'], maxdd=st['maxdd'], behaviour=st['behaviour'],
                   trades_by_year={y: study.year_trades(tr, y) for y in sorted(st['by_year'])},
                   why={w: sum(t['why'] == w for t in tr) for w in sorted({t['why'] for t in tr})},
                   top=sorted(({k: t[k] for k in ('code', 'entry', 'exit', 'ret', 'days', 'why')} for t in tr),
                              key=lambda t: -t['ret'])[:10],
                   drop2=dict(total=drop['total'], by_year=drop['by_year']))
        for r, ok, why in rows:
            print('SUCCESS', r, 'pass' if ok else 'FAIL', why, flush=True)
        self.write(f'success_{self.tag(report, key)}.json', out)
        return out

    def write(self, name, out):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / name).write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')


def _peak(h, n, skip):
    """Per row s: the highest high of rows s-skip-n+1 .. s-skip and its row (the latest one on a tie)."""
    best, row = np.full(h.shape, -np.inf), np.full(h.shape, np.nan)
    rows = np.arange(len(h), dtype=float)[:, None]
    for k in range(skip, skip + n):
        x = lag(h, k) if k else h
        up = x > best
        best, row = np.where(up, x, best), np.where(up, rows - k, row)
    return np.where(np.isfinite(best), best, np.nan), row


def trendline(h, span, recent, lower):
    """Per day t, from the highs of t-1 and earlier: the descending line through the highest high of the span
    before the last `recent` sessions and the highest high of those `recent` sessions (at least `lower` below
    it), extended to t; NaN where there is no such pair."""
    h1, i1 = _peak(h, span - recent, recent)
    h2, i2 = _peak(h, recent, 0)
    t = np.arange(len(h), dtype=float)[:, None] + 1          # the line is read one row later
    with np.errstate(invalid='ignore', divide='ignore'):
        line = h2 + (h2 - h1) / (i2 - i1) * (t - i2)
        ok = (h2 <= (1 - lower) * h1) & (i2 > i1)
    return lag(np.where(ok, line, np.nan))


def facts(st, tr, val, drop, gate):
    """What success.judge reads, from the window run (stats with behaviour, trades), the 2026 run, the window run
    without the best two and the gate's check verdicts.  Rule 3's all-trade mean and longest hold are over closed
    trades ('end' rows only value open positions)."""
    closed = [t for t in tr if t['why'] != 'end']
    ret = np.array([t['ret'] for t in closed], float)
    days = [t['days'] for t in closed]
    b = dict(st['behaviour'], days_mean=float(np.mean(days)) if days else None,
             max_days=float(max(days)) if days else None)
    return dict(gate=dict(gate), win=float((ret > 0).mean()) if len(ret) else None, closed=len(closed),
                per_year=b['per_year'], behaviour={k: b.get(k) for k in CARD['behaviour']}, years={},
                total=st['total'], placebo_median=st['placebo']['median'], validate_total=val['total'],
                validate_placebo_median=val['placebo']['median'], total_drop2=drop['total'])


STUDY = Zanger()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in ('validate', 'success'):
        getattr(STUDY, sys.argv[1])(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    else:
        study.main(STUDY, sys.argv)
