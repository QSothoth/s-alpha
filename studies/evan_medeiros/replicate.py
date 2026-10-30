"""Evan Medeiros (Trade Risk, the Lamorak system) through skills/trader-replication: short-term mean reversion on
US stocks, long and short, from his own article (thetraderisk.com/mean-reversion-trading-tips-strategy, rules from
Cesar Alvarez, notes/RULES_CN.md) and the published Lamorak statistics (328 trades a year, 63.76% winners, average
winner 2.29%, win / loss 0.81, 4 days held, leverage up to 150%; 2024 +20.45%, 2025 to August +5.03%).

    PY="nice -n 19 env OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/opend-us-options/.venv/bin/python"
    $PY -m studies.evan_medeiros.replicate round R1
    $PY -m studies.evan_medeiros.replicate validate r1.json

No dated trades are public, so fidelity is his behaviour and his years; rounds choose on the selection segment
2024-01-02 -> 2025-12-31 and `validate` runs the carried configuration once on 2026-01-02 -> 2026-10-16.  Mean
reversion wins most trades: the engineering gate's 35% win-rate ceiling is a momentum rule and is not used here
(notes/PREREG_R1.md).
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
    sides=['long', 'short'],
    long=dict(rsi=5, down=3, hv=40, trend=True, limit=.03),        # RSI2 crosses under 5 after 3+ down days, above a
    short=dict(rsi=99, up=3, hv=40, trend=True, limit=.03, run=.10),  # rising 200-day, HV100 >= 40; limit 3% under
    pool=dict(turnover=5e6, price=5.0),                             # the prior close (his 2-10%)
    regime='sma200',                                                 # longs above / shorts below the index's 200-day
    exit_long='xhi', exit_short='xlo',                               # "wait for a bounce": a close beyond the prior bar
    priority='hv',
    rule_opts=dict(risk=1.0, max_position=.10, max_gross=1.5, max_open=15, trail='', trims=(), max_days=10,
                   short_max_days=10, buy_cost=.0005, sell_cost=.0005, borrow_rate=.03),
    stop=.20,                                                        # a wide disaster stop ("20% maximum loss")
)


def rsi(c, n):
    """Wilder RSI of each column (NaN until n changes are known)."""
    d = np.diff(c, axis=0, prepend=np.nan)
    up, dn = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    up[np.isnan(d)] = np.nan
    dn[np.isnan(d)] = np.nan
    out = np.full_like(c, np.nan)
    au = np.full(c.shape[1], np.nan)
    ad = np.full(c.shape[1], np.nan)
    cnt = np.zeros(c.shape[1])
    for t in range(len(c)):
        u, w = up[t], dn[t]
        ok = np.isfinite(u)
        cnt = np.where(ok, cnt + 1, 0)
        first = ok & (cnt <= n)
        au = np.where(first, np.where(cnt == 1, u, (np.nan_to_num(au) * (cnt - 1) + u) / cnt), au)
        ad = np.where(first, np.where(cnt == 1, w, (np.nan_to_num(ad) * (cnt - 1) + w) / cnt), ad)
        later = ok & (cnt > n)
        au = np.where(later, (au * (n - 1) + u) / n, au)
        ad = np.where(later, (ad * (n - 1) + w) / n, ad)
        au = np.where(ok, au, np.nan)
        ad = np.where(ok, ad, np.nan)
        with np.errstate(invalid='ignore', divide='ignore'):
            out[t] = np.where(cnt >= n, np.where(ad == 0, 100.0, 100 - 100 / (1 + au / ad)), np.nan)
    return out


def streak(c, sign):
    """Consecutive closes below (sign -1) or above (+1) the previous close, ending today."""
    d = np.sign(np.diff(c, axis=0, prepend=np.nan))
    out = np.zeros(c.shape)
    run = np.zeros(c.shape[1])
    for t in range(len(c)):
        run = np.where(d[t] == sign, run + 1, 0)
        out[t] = run
    return out


class Evan(GoalMixin, study.Study):
    id, name = 'evan_medeiros', 'Evan Medeiros'
    root = ROOT / 'studies' / 'evan_medeiros'
    ledger = None
    full = SELECT
    home = ('us',)
    his = {'2024': dict(ret=.2045)}
    his_behaviour = dict(per_year=328, win=.6376, avg_win=.0229, avg_loss=-.0229 / .81, days_win=4, days_loss=4)
    base = DRAFT
    periods = {'2024': ('2024-01-02', '2024-12-31', .2045), '2025-01..08': ('2025-01-02', '2025-08-29', .0503),
               '2026 (used)': ('2026-01-02', '2026-10-16', None)}
    goal_behaviour = dict(per_year=328, win=.6376, avg_win=.0229, avg_loss=-.0229 / .81, days=4)
    starts = ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02')

    data_tag = 'trader-data-v1'        # R9: a round's "data" key (and a config's) switches the frozen dataset

    def arrays(self, market, upto=None, mode=None):
        os.environ['TRADER_DATA_TAG'] = self.data_tag
        return panels.arrays(market, upto, mode)

    def round(self, name):
        spec = json.loads((self.rounds / f'{name}.json').read_text(encoding='utf-8'))
        self.data_tag = spec.get('data', 'trader-data-v1')
        return super().round(name)

    def robust(self, report, key='chosen'):
        self.data_tag = self.config(report, key).get('data', 'trader-data-v1')
        return super().robust(report, key)

    def ledger_sets(self, A):
        return [], []

    # ----- features -----
    def feat(self, A):
        F = A['F']
        rsi2 = F.get(('rsi', 2), lambda: rsi(F.c, 2))
        with np.errstate(invalid='ignore', divide='ignore'):
            lr = np.log(F.c / lag(F.c))
        def hvf():
            m, m2 = S.rolling(lr, 100, 'mean'), S.rolling(lr * lr, 100, 'mean')
            return np.sqrt(np.maximum(m2 - m * m, 0) * 100 / 99) * np.sqrt(252) * 100
        hv = F.get(('hv', 100), hvf)
        down = F.get(('streak', -1), lambda: streak(F.c, -1))
        up = F.get(('streak', 1), lambda: streak(F.c, 1))
        return F, rsi2, hv, down, up

    def index(self, A):
        """The pool's equal-weight daily index (price >= 5, 20-day turnover >= 20M, as of the day before), as the
        short-side gate of docs/TRADER_PROTOCOL_CN.md section 5."""
        F = A['F']

        def f():
            prev = lag(F.c)
            with np.errstate(invalid='ignore', divide='ignore'):
                ok = lag((F.raw >= 5) & (F.to20 >= 20e6))
                r = np.where(ok & np.isfinite(prev) & np.isfinite(F.c), F.c / prev - 1, np.nan)
                return np.cumprod(1 + np.nan_to_num(np.nanmean(r, axis=1)))
        return F.get('ew_index', f)

    def pool(self, A, cfg):
        F, rsi2, hv, *_ = self.feat(A)
        p = cfg.get('pool', {})
        with np.errstate(invalid='ignore'):
            return (F.raw >= p.get('price', 5.0)) & (F.to20 >= p.get('turnover', 5e6)) & np.isfinite(F.c)

    def armed(self, A, cfg, side):
        """Day t-1 setups (bool, days x codes, as of the close they are read on)."""
        F, rsi2, hv, down, up = self.feat(A)
        base = self.pool(A, cfg)
        s200 = F.sma(200)
        with np.errstate(invalid='ignore'):
            if side > 0:
                o = cfg['long']
                m = base & (down >= o['down']) & (hv >= o['hv'])
                if o.get('hv_max'):                                   # a volatility band (Lamorak's published
                    m &= hv < o['hv_max']                             # 2.3% average winner, not the article's)
                ext_r = (rsi2 < o['rsi']) & (lag(rsi2) >= o['rsi']) if o.get('rsi') is not None else None
                ext_d = None
                if o.get('drop'):                                     # down 10%+ over the last 3 days (his other
                    r3 = F.ret(3)                                     # version of the extreme), its first day
                    ext_d = (r3 <= -o['drop']) & (lag(r3) > -o['drop'])
                if o.get('either') and ext_r is not None and ext_d is not None:
                    m &= ext_r | ext_d                                # either of his two extremes
                else:
                    for e in (ext_r, ext_d):
                        if e is not None:
                            m &= e
                if o.get('trend', True):
                    m &= (F.c > s200) & (s200 > lag(s200, 20))
            else:
                o = cfg['short']
                m = base & (rsi2 > o['rsi']) & (lag(rsi2) <= o['rsi']) & (up >= o['up']) & (hv >= o['hv'])
                if o.get('hv_max'):
                    m &= hv < o['hv_max']
                if o.get('trend', True):                              # the mirror: under a falling 200-day
                    m &= (F.c < s200) & (s200 < lag(s200, 20))
                if o.get('run'):                                      # his third indicator for shorts
                    m &= F.ret(3) >= o['run']
            reg = cfg.get('regime', '')
            if reg:
                idx = self.index(A)
                n = int(reg[3:])
                sm = S.rolling(idx[:, None], n, 'mean')[:, 0]
                ok = idx > sm if side > 0 else idx < sm
                m &= ok[:, None]
        return m

    def build(self, A, cfg, trace=None):
        F = A['F']
        _, rsi2, hv, *_ = self.feat(A)
        o, h, l, c = F.o, F.h, F.l, F.c
        nd, nc = c.shape
        entries = [[] for _ in range(nd)]
        mask = np.zeros(c.shape, bool)
        stop = cfg.get('stop', .20)
        for side, name in ((1, 'long'), (-1, 'short')):
            if name not in cfg.get('sides', ['long']):
                continue
            arm = lag(self.armed(A, cfg, side))
            lim_k = cfg[name].get('limit', .03)
            with np.errstate(invalid='ignore'):
                if cfg[name].get('limit_atr'):                        # the limit in ATRs instead of percent
                    off = lag(F.atr14) * cfg[name]['limit_atr']
                    level = lag(c) - side * off
                else:
                    level = lag(c) * (1 - side * lim_k)
                hit = arm & ((l <= level) if side > 0 else (h >= level)) & np.isfinite(o)
                fill = np.where(side > 0, np.fmin(o, level), np.fmax(o, level))
            pri_ = cfg.get('priority', 'hv')
            if pri_ == 'hv':
                pr = -lag(hv)
            elif pri_ == 'drop3':                    # R10: the deepest 3-session move into the setup first
                pr = lag(F.ret(3)) * side
            else:                                    # 'rsi': the most stretched RSI2 first
                pr = lag(rsi2) * side
            kind = 'mrl' if side > 0 else 'mrs'
            for d, j in zip(*np.nonzero(hit)):
                f = float(fill[d, j])
                st = f * (1 - side * stop)
                ex = None
                if (side > 0 and l[d, j] <= st) or (side < 0 and h[d, j] >= st):
                    ex = st
                entries[d].append((float(pr[d, j]), int(j), side, f, st, kind, ex))
                mask[d, j] = True
        ro = dict(cfg.get('rule_opts', {}))
        ro['trims'] = tuple(ro.get('trims', ()))
        rules = Y.Rules(**ro, exit_signal=cfg.get('exit_long', ''), short_exit_signal=cfg.get('exit_short', ''),
                        intraday_kinds=('mrl', 'mrs'))
        pool = lag(self.pool(A, cfg))
        A['kind_pools'] = None
        if trace is not None:
            trace['raw'] = entries
        return entries, rules, mask, pool

    def named(self, A, pool, name):
        F, rsi2, *_ = self.feat(A)
        with np.errstate(invalid='ignore'):
            if name == 'xhi':                       # close above the previous day's high
                return F.c > lag(F.h)
            if name == 'xlo':
                return F.c < lag(F.l)
            if name == 'xsma5':                     # close above the 5-day average
                return F.c > F.sma(5)
            if name == 'xsma5s':
                return F.c < F.sma(5)
            if name.startswith('xrsi'):             # RSI2 above k (longs) / 'xrsis' below 100-k (shorts)
                k = float(name[5:]) if name.startswith('xrsis') else float(name[4:])
                return rsi2 < 100 - k if name.startswith('xrsis') else rsi2 > k
            if name == 'xup':                       # the first up close / down close
                return F.c > lag(F.c)
            if name == 'xdn':
                return F.c < lag(F.c)
        raise KeyError(name)

    def robust_variants(self, cfg):
        """The account nudges plus one step either side of the knobs R4-R8 moved (HV band, limit, time stop)."""
        v = super().robust_variants(cfg)
        lo, hi = cfg['long']['hv'], cfg['long'].get('hv_max')
        both = lambda **k: {'long': k, 'short': k}
        v.update({'hv lo -5': both(hv=lo - 5), 'hv lo +5': both(hv=lo + 5),
                  'limit -0.5%': both(limit=cfg['long']['limit'] - .005), 'limit +0.5%': both(limit=cfg['long']['limit'] + .005),
                  'time stop -1': {'rule_opts': {'max_days': cfg['rule_opts']['max_days'] - 1,
                                                 'short_max_days': cfg['rule_opts']['max_days'] - 1}},
                  'time stop +1': {'rule_opts': {'max_days': cfg['rule_opts']['max_days'] + 1,
                                                 'short_max_days': cfg['rule_opts']['max_days'] + 1}}})
        if hi:
            v.update({'hv hi -5': both(hv_max=hi - 5), 'hv hi +5': both(hv_max=hi + 5)})
        return v

    def validate(self, report, key='chosen'):
        cfg = self.config(report, key)
        self.data_tag = cfg.get('data', 'trader-data-v1')
        A = self.arrays('us')
        entries, rules, mask, pool = self.build(A, cfg)
        out = {'report': report, 'config': cfg}
        for nm, seg in (('select', SELECT), ('validate', VALIDATE), ('window', WINDOW)):
            st, tr = self.run(A, entries, seg, pool, rules, audit=True)
            st.pop('_curve', None)
            st['ew_hold_pool'] = study.ew_hold(A, pool, seg, lagged=True)
            out[nm] = st
            print('VALIDATE', nm, f"total {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                  f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_pool']:+.3f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, 'n', st['trades'], 'win', st['win'],
                  'avg', st.get('avg_win'), st.get('avg_loss'), flush=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'validate_{report.replace(".json", "")}_{key}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out


STUDY = Evan()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'validate':
        STUDY.validate(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'chosen')
    else:
        study.main(STUDY, sys.argv)
