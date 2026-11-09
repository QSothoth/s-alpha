"""IE29: preference-profile fit with theme-cluster indicators and weighted bins.

Extends IE28: indicators in natural units plus same-theme breadth measured from the
nightly leader scope (60-day return correlation, causal); each indicator may use 3, 5
or 10 pool-quantile bins; scores are weighted sums of log(his share / pool share).
Indicators are added greedily by in-sample coverage, then weights are tuned and unused
indicators dropped (fitting is allowed). Shuffled labels and leave-one-half are reported
only. Yardstick as IE27/IE28: K new names per night, held H nights, window -4..+2.

Run from the worktree root: python -m studies.trader_replication.martin_profile_ie29
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/opt/opend-us-options/.claude/worktrees/gap-review')
sys.path.insert(0, str(ROOT))
if '--ie38-stage' in sys.argv:
    from studies.trader_replication.martin_profile_ie38 import install_offline_guard
    install_offline_guard()
if '--ie40-stage' in sys.argv:
    from studies.trader_replication.martin_profile_ie40 import install_offline_guard
    install_offline_guard()
from studies.trader_replication import martin_continue_ie23 as m  # noqa: E402
from studies.trader_replication import martin_continue_ie9 as ie9  # noqa: E402

GAP = ROOT / 'studies/trader_replication/reports/gap_review'
WORK = GAP / 'ie29_work'
HALVES = ('2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2')
WEIGHTS = (0, .5, 1, 1.5, 2, 3)

ap = argparse.ArgumentParser()
ap.add_argument('--filter', default='h4nan', choices=('ie9', 'h4nan', 'loose'))
ap.add_argument('--learn', default='0,1,2')
ap.add_argument('--bins', default='3,5,10')
ap.add_argument('--max-attrs', type=int, default=12)
ap.add_argument('--checks', action='store_true', help='also run shuffled labels and leave-one-half')
ap.add_argument('--drop', default='listed_days', help='comma list of indicators to exclude')
ap.add_argument('--tag', default='')
ap.add_argument('--mix', type=int, default=0, help='number of data-derived target types')
ap.add_argument('--em', type=int, default=0, help='rounds of relearning from each target best night')
ap.add_argument('--beam', type=int, default=1)
ap.add_argument('--renew', type=int, default=0, help='keep held names ranked within top N')
ap.add_argument('--cap', type=int, default=11)
ap.add_argument('--slots', default='', help='e.g. 2,1: nightly slots per profile')
ap.add_argument('--nested', type=int, default=0, help='IE30: keep indicators chosen in >= N of the inner leave-one-half fits, weight 1, 5 bins')
ap.add_argument('--loo-only', action='store_true', help='skip shuffled-label refits')
ap.add_argument('--holdout', default='', help='IE30: comma list of halves never used in fitting; fit on the rest, test once, exit')
ap.add_argument('--interval', action='store_true', help='IE31: one contiguous preferred interval per indicator, rounded thresholds')
ap.add_argument('--inner-cv', action='store_true', help='IE33: leave-one-half CV inside the training halves')
ap.add_argument('--bag', action='store_true', help='IE33: final score = mean rank-score of inner-fold models and full model')
ap.add_argument('--learn-all', action='store_true', help='IE34: fit on all his entries (not only primary); test still primary')
ap.add_argument('--smooth', type=float, default=2.0)
ap.add_argument('--obj', default='hit', choices=('hit', 'soft'))
ap.add_argument('--cooldown', type=int, default=0, help='nights before a picked name may be picked again (>= H)')
ap.add_argument('--library', choices=('legacy', 'std_v1', 'std_v1_1'), default='legacy')
ap.add_argument('--train-edges', action='store_true', help='v1: training-only bin edges and pool shares')
ap.add_argument('--own-scan', action='store_true', help='v1: add causal own-scan counts')
ap.add_argument('--one-per-family', action='store_true', help='v1: at most one representative from each family')
ap.add_argument('--ie38-stage', choices=('fit', 'finish', 'evaluate', 'shuffle'), default='', help='IE38: training, frozen evaluation or isolated shuffled-label checks')
ap.add_argument('--ie38-shuffle-seed', type=int, default=0)
ap.add_argument('--ie40-stage', choices=('fit', 'evaluate', 'shuffle'), default='')
ap.add_argument('--ie40-shuffle-seed', type=int, default=0)
ap.add_argument('--ie42-stage', choices=('fit', 'evaluate', 'audit', 'breadth', 'quality', 'scorecard', 'agree'), default='')
ap.add_argument('--shrink', action='store_true', help='IE42: bin prior weight = his rows / bins instead of a fixed smooth')
ap.add_argument('--missing-zero', action='store_true', help='IE42: missing values score 0 and are left out of bin shares')
ap.add_argument('--mainleg-objective', action='store_true', help='IE43: targets are main legs, a hit is a buy with half of his move left')
ap.add_argument('--quality-objective', action='store_true', help='IE46: ties in covered legs go to picks that double more often, then to a higher median run')
ap.add_argument('--unimodal', action='store_true', help='IE44: bin scores rise then fall (one preferred range), weighted by pool share')
args = ap.parse_args()
if (args.own_scan or args.one_per_family) and args.library != 'std_v1':
    ap.error('--own-scan and --one-per-family require --library std_v1')
if args.ie38_stage and not args.train_edges:
    ap.error('--ie38-stage requires --train-edges')
if (args.ie40_stage or args.ie42_stage) and (not args.train_edges or args.library != 'std_v1_1'):
    ap.error('--ie40-stage and --ie42-stage require --train-edges and --library std_v1_1')
if args.library == 'std_v1_1' and not (args.ie40_stage or args.ie42_stage):
    ap.error('--library std_v1_1 requires --ie40-stage or --ie42-stage')
if args.ie38_stage or args.library == 'std_v1':
    WEIGHTS = (0, 1, 1.5, 2, 3)
SMOOTH = args.smooth
OBJ = (lambda v: (v[0], v[2])) if args.obj == 'hit' else (lambda v: (v[2], v[0]))
LEARN = tuple(int(x) for x in args.learn.split(','))
BIN_CHOICES = tuple(int(x) for x in args.bins.split(','))
TAG = args.tag or f"{args.filter}_{'_'.join(map(str, LEARN))}_b{'-'.join(map(str, BIN_CHOICES))}"
if args.library == 'std_v1_1':
    WORK = GAP / 'ie40_work'
WORK.mkdir(exist_ok=True)
T0 = time.time()


def log(*a):
    print(f'[{time.time() - T0:6.0f}s]', *a, flush=True)


cal = json.load(open(GAP / 'ie5_work/prepared.json'))['days']
cpos = {x: i for i, x in enumerate(cal)}
qqq_np = np.load(GAP / 'ie5_work/qqq.npy')
qqq = pd.Series(qqq_np)
d = m.Data(matrix=False)
b = d.base
GATE_NAMES = list(b.base_names)


def gate_mask(pct):
    ok = np.ones(len(pct), bool)
    for g in ie9.GATES:
        x = pct[:, GATE_NAMES.index(g['name'])]
        if args.filter == 'loose':
            cut = {'h4_history': .5, 'option_volume': .7}.get(g['name'], g['cutoff'])
            ok &= np.where(np.isfinite(x), x >= cut, g['name'] == 'h4_history')
        elif g['name'] == 'h4_history' and args.filter == 'h4nan':
            ok &= np.where(np.isfinite(x), x >= g['cutoff'], True)
        else:
            ok &= np.where(np.isfinite(x), x, -1) >= g['cutoff']
    return ok


passed = np.zeros(b.n, bool)
for day in b.widths:
    sl = b.slices[day]
    passed[sl] = gate_mask(b.base_pct[sl])
if args.filter == 'ie9':
    assert np.array_equal(np.flatnonzero(passed), d.kept), 'gate replica differs'
kept = np.flatnonzero(passed)
SL, DAYS, CODES, off = {}, [], [], 0
for day in b.widths:
    sl = b.slices[day]
    names_ = [c for k, c in enumerate(b.meta['scope'][day]) if passed[sl.start + k]]
    SL[day] = slice(off, off + len(names_))
    DAYS.extend([day] * len(names_))
    CODES.extend(names_)
    off += len(names_)
N = off
days = sorted(SL)
codes = np.array(CODES)
row_day = np.array([cpos[x] for x in DAYS])
lookup = {(c, i): r for r, (c, i) in enumerate(zip(codes, row_day))}
_base = np.load(ie9.WORK / 'full_features.npy', mmap_mode='r')[kept]
_score = (np.nan_to_num(_base[:, ie9.NAMES.index('after_inside')], nan=.5)
          + np.nan_to_num(_base[:, ie9.NAMES.index('near_ema9')], nan=.5))
log('pool rows', N, 'nights', len(days))


def anchored_vwap(h, l, c, v, window, pick):
    tp = np.nan_to_num((h + l + c) / 3) * np.nan_to_num(v)
    cpv, cv = np.concatenate(([0], np.cumsum(tp))), np.concatenate(([0], np.cumsum(np.nan_to_num(v))))
    out = np.full(len(c), np.nan)
    for t in range(window, len(c)):
        a = t - window + 1 + pick(t - window + 1, t + 1)
        vol = cv[t + 1] - cv[a]
        if vol > 0:
            out[t] = (cpv[t + 1] - cpv[a]) / vol
    return out


def indicators(z):
    o, h, l, c, v, t = (z[k].astype(float) for k in ('o', 'h', 'l', 'c', 'v', 't'))
    O, H, L, C, V, T = map(pd.Series, (o, h, l, c, v, t))
    adr = (H / L - 1).rolling(20, min_periods=15).mean()
    e9, e21, e50 = (C.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    gap = O / C.shift(1) - 1
    low_ = np.where(np.isfinite(l), l, np.inf)
    high_ = np.where(np.isfinite(h), h, -np.inf)
    gap_ = np.nan_to_num(gap.to_numpy(), nan=-np.inf)
    av_low = anchored_vwap(h, l, c, v, 50, lambda a, b_: int(np.argmin(low_[a:b_])))
    av_high = anchored_vwap(h, l, c, v, 50, lambda a, b_: int(np.argmax(high_[a:b_])))
    av_gap = anchored_vwap(h, l, c, v, 60, lambda a, b_: int(np.argmax(gap_[a:b_])))
    big = np.flatnonzero(np.nan_to_num(gap.to_numpy()) >= .10)
    since = np.full(len(c), 120.)
    for t_ in range(len(c)):
        k = big[big <= t_]
        if len(k):
            since[t_] = min(120, t_ - k[-1])
    rs = C / qqq
    OV = pd.Series(z['extra_option_volume'].astype(float))
    first_valid = np.argmax(np.isfinite(c)) if np.isfinite(c).any() else len(c)
    return {
        'dollar_vol20_M': T.rolling(20, min_periods=15).mean() / 1e6,
        'price': C,
        'adr20_pct': adr * 100,
        'range_today_adr': (H / L - 1) / adr,
        'lod_stop_pct': (C / L - 1) * 100,
        'ext_ema9_adr': (C / e9 - 1) / adr,
        'ext_ema21_adr': (C / e21 - 1) / adr,
        'ext_ema50_adr': (C / e50 - 1) / adr,
        'ema_stack': (e9 > e21).astype(float) + (e21 > e50).astype(float),
        'ema9_21_gap_adr': (e9 / e21 - 1) / adr,
        'from_high252_pct': (C / H.rolling(252, min_periods=60).max() - 1) * 100,
        'from_high20_pct': (C / H.rolling(20).max() - 1) * 100,
        'over_prior_high_adr': (C / H.shift(1) - 1) / adr,
        'perf1_pct': (C / C.shift(1) - 1) * 100,
        'perf5_pct': (C / C.shift(5) - 1) * 100,
        'perf21_pct': (C / C.shift(21) - 1) * 100,
        'perf63_pct': (C / C.shift(63) - 1) * 100,
        'rs21_vs_qqq_pct': ((C / C.shift(21)) - (qqq / qqq.shift(21))) * 100,
        'rs5_vs_qqq_pct': ((C / C.shift(5)) - (qqq / qqq.shift(5))) * 100,
        'rs_line_from_high63_pct': (rs / rs.rolling(63).max() - 1) * 100,
        'close_pos': (C - L) / (H - L),
        'rvol20': V / V.rolling(20, min_periods=15).mean(),
        'rvol3_20': V.rolling(3).mean() / V.rolling(20, min_periods=15).mean(),
        'dollar_vol_today_vs20': T / T.rolling(20, min_periods=15).mean(),
        'gap_today_adr': gap / adr.shift(1),
        'days_since_10pct_gap': pd.Series(since),
        'inside_day': ((H <= H.shift(1)) & (L >= L.shift(1))).astype(float),
        'nr7': ((H - L) <= (H - L).rolling(7).min()).astype(float),
        'contract3_adr': (H / L - 1).rolling(3).mean() / adr,
        'avwap_base_low_adr': (C / pd.Series(av_low) - 1) / adr,
        'avwap_base_high_adr': (C / pd.Series(av_high) - 1) / adr,
        'avwap_big_gap_adr': (C / pd.Series(av_gap) - 1) / adr,
        'option_rvol20': OV / OV.rolling(20, min_periods=10).mean(),
        'iv_pct': pd.Series(z['extra_iv'].astype(float)),
        'earn_days': pd.Series(np.minimum(z['extra_earn_days'].astype(float), 120)),
        'new_high252': (C >= H.shift(1).rolling(252, min_periods=60).max()).astype(float),
        'new_high50': (C >= H.shift(1).rolling(50).max()).astype(float),
        'from_high50_adr': (C / H.rolling(50).max() - 1) / adr,
        'above_ema21_days20': (C > e21).astype(float).rolling(20, min_periods=15).sum(),
        'rs_pos_days20': (((C / C.shift(21)) - (qqq / qqq.shift(21))) > 0).astype(float).rolling(20, min_periods=15).sum(),
        'up_days20': (C > C.shift(1)).astype(float).rolling(20, min_periods=15).sum(),
        'listed_days': pd.Series(np.maximum(0, np.arange(len(c)) - first_valid).astype(float)),
    }


cache = WORK / f'indicators_{args.filter}_v2.npz'
if args.library == 'std_v1_1':
    from studies.trader_replication.martin_profile_ie40 import pool_matrix
    NAMES, X = pool_matrix(CODES, row_day, cal, b.meta['scope'])
elif cache.exists():
    zc = np.load(cache, allow_pickle=False)
    NAMES, X = list(zc['names']), zc['x']
    assert X.shape[1] == N
    log('indicators from cache', X.shape)
else:
    NAMES, X = None, None
    rets = {}
    scope_codes = sorted({c for day in days for c in b.meta['scope'][day]})
    for code in scope_codes:
        path = GAP / f'ie5_work/stocks/{code}.npz'
        if not path.exists():
            continue
        z = np.load(path)
        c = z['c'].astype(float)
        with np.errstate(divide='ignore', invalid='ignore'):
            rets[code] = np.log(c[1:] / c[:-1]).astype(np.float32)
        rows = np.flatnonzero(codes == code)
        if not len(rows):
            continue
        ind = indicators(z)
        if X is None:
            NAMES = list(ind)
            X = np.full((len(NAMES) + 6, N), np.nan, np.float32)
        for k, name in enumerate(NAMES):
            X[k, rows] = ind[name].to_numpy()[row_day[rows]]
    log('base indicators done', len(NAMES))
    theme = ['theme_peers_scope', 'theme_peers_moving', 'theme_peer_ret5', 'theme_peer_ret1',
             'theme_peers_pool', 'theme_rank_rs21']
    rs21 = X[NAMES.index('rs21_vs_qqq_pct')]
    for day in days:
        t = cpos[day]
        if t < 61:
            continue
        sc = [c for c in b.meta['scope'][day] if c in rets]
        R = np.stack([rets[c][t - 60:t] for c in sc])
        valid = np.isfinite(R).sum(1) >= 40
        Z = np.where(np.isfinite(R), R, np.nan)
        Z = Z - np.nanmean(Z, 1, keepdims=True)
        Z = np.nan_to_num(Z)
        sd = np.sqrt((Z ** 2).sum(1))
        Z = np.where(sd[:, None] > 0, Z / np.where(sd[:, None] > 0, sd[:, None], 1), 0)
        ret5 = np.nansum(R[:, -5:], 1)
        ret1 = R[:, -1]
        sl = SL[day]
        pool_codes = CODES[sl]
        pos = {c: i for i, c in enumerate(sc)}
        in_pool = np.zeros(len(sc), bool)
        for c in pool_codes:
            if c in pos:
                in_pool[pos[c]] = True
        idx = np.array([pos.get(c, -1) for c in pool_codes], dtype=int)
        ok = idx >= 0
        corr = Z[idx[ok]] @ Z.T
        corr[:, ~valid] = 0
        rows = np.arange(sl.start, sl.stop)[ok]
        for j, (r, i) in enumerate(zip(rows, idx[ok])):
            if not valid[i]:
                continue
            peer = corr[j] >= .5
            peer[i] = False
            n = int(peer.sum())
            X[len(NAMES) + 0, r] = n
            X[len(NAMES) + 1, r] = int((peer & (ret5 >= np.log(1.10))).sum())
            X[len(NAMES) + 2, r] = float(np.nanmean(ret5[peer])) * 100 if n else np.nan
            X[len(NAMES) + 3, r] = float(np.nanmean(ret1[peer])) * 100 if n else np.nan
            X[len(NAMES) + 4, r] = int((peer & in_pool).sum())
            pp = [q for q in np.flatnonzero(peer & in_pool)]
            mates = rs21[[sl.start + pool_codes.index(sc[q]) for q in pp]] if pp else np.array([])
            X[len(NAMES) + 5, r] = (1 + np.sum(mates > rs21[r])) / (1 + len(mates)) if len(mates) else np.nan
    NAMES = NAMES + theme
    X[~np.isfinite(X)] = np.nan
    np.savez(cache, names=np.array(NAMES), x=X)
    log('theme indicators done')

if args.library != 'std_v1_1':
    _run, _cnt20, _prev, _hist = np.zeros(N, np.float32), np.zeros(N, np.float32), {}, {}
    for _i, _day in enumerate(days):
        _sl = SL[_day]
        _now = {}
        for _r in range(_sl.start, _sl.stop):
            _c = CODES[_r]
            _now[_c] = _prev.get(_c, 0) + 1
            _run[_r] = min(_now[_c], 30)
            _h = [j for j in _hist.get(_c, []) if j > _i - 20]
            _cnt20[_r] = len(_h) + 1
            _hist[_c] = _h + [_i]
        _prev = _now
    X = np.vstack([X, _run[None], _cnt20[None]])
    NAMES = list(NAMES) + ['pool_run_nights', 'pool_nights_20']
if args.library == 'std_v1':
    from studies.trader_replication import standard_indicators as standard
    from studies.trader_replication.standard_indicators_dedup import pool_matrix
    NAMES, X = pool_matrix(CODES, row_day, cal, own_scan=args.own_scan, pool_counts=_cnt20)
    FAMILIES = {s['name']: s['family'] for s in standard.V1_SPEC}
    FAMILIES.update(pool_nights_20='own_scan', theme_peers_pool='own_scan')
else:
    FAMILIES = {}
DROP = {x for x in args.drop.split(',') if x}
USE = [k for k, n in enumerate(NAMES) if n not in DROP]
ROW_HALVES = np.array([day[:4] + ('H1' if day[5:7] <= '06' else 'H2') for day in DAYS])
TRAIN_MASK = np.ones(N, bool)
if args.train_edges:
    _PAD = np.full((len(days), max(sl.stop-sl.start for sl in SL.values())), N, np.int32)
    _ROW_NIGHT = np.empty(N, np.int32)
    for _i, _sl in enumerate(SL.values()):
        _PAD[_i, :_sl.stop-_sl.start] = np.arange(_sl.start, _sl.stop)
        _ROW_NIGHT[_sl] = _i
    _CODE_IDS = {c: i for i, c in enumerate(dict.fromkeys(CODES))}
    _ROW_CODE_IDS = np.array([_CODE_IDS[c] for c in CODES], np.int32)


def binning(x, q, train_mask=None):
    source = x if train_mask is None else x[train_mask]
    u = np.unique(source[np.isfinite(source)])
    if len(u) <= 3:
        edges = (u[:-1] + u[1:]) / 2
    else:
        edges = np.unique(np.nanquantile(source, np.linspace(0, 1, q + 1)[1:-1]))
    bins = np.where(np.isfinite(x), np.searchsorted(edges, x, side='right'), len(edges) + 1)
    return bins.astype(np.int16), edges


BINS = {}
if not args.train_edges:
    for k in USE:
        for q in BIN_CHOICES:
            BINS[(k, q)] = binning(X[k], q)


def first(x):
    return next(i for i, y in enumerate(cal) if y >= x)


REAL = [(e['code'], first(e['entry_date']), h, bool(p)) for e, h, p in zip(d.entries, d.entry_half, d.primary)]


FOCUS = {}
LAST = {}
FITTING = False


def learn_groups(targets):
    if FOCUS:
        return [[FOCUS[(c, i0)]] for c, i0, _, p in targets if p and (c, i0) in FOCUS]
    out = []
    for code, i0, _, p in targets:
        if p:
            g = [lookup[(code, i0 + w)] for w in LEARN if (code, i0 + w) in lookup
                 and (not args.train_edges or TRAIN_MASK[lookup[(code, i0+w)]])]
            if g:
                out.append(g)
    return out


def tables_for(targets):
    global TRAIN_MASK
    if args.train_edges:
        halves = {t[2] for t in targets}
        TRAIN_MASK = np.isin(ROW_HALVES, list(halves))
        if not TRAIN_MASK.any():
            raise ValueError('no training pool rows')
        BINS.clear()
        for k in USE:
            for q in BIN_CHOICES:
                BINS[(k, q)] = binning(X[k], q, TRAIN_MASK)
    groups = learn_groups(targets)
    return {key: bin_table(bins, edges, TRAIN_MASK if args.train_edges else slice(None), groups)
            for key, (bins, edges) in BINS.items()}


def bin_table(bins, edges, pool_rows, groups):
    nb = len(edges) + 2
    pool = np.bincount(bins[pool_rows], minlength=nb).astype(float)
    his = np.zeros(nb)
    for g in groups:
        np.add.at(his, bins[g], 1 / len(g))
    if args.missing_zero:
        pool[-1] = his[-1] = 0
    if not pool.sum():
        return np.zeros(nb, np.float32)
    ps = pool / pool.sum()
    prior = his.sum() / (nb - 1) if args.shrink else SMOOTH
    hs = (his + prior * ps) / (his.sum() + prior)
    table = np.where(pool > 0, np.log(np.where(pool > 0, hs, 1) / np.where(pool > 0, ps, 1)), 0)
    if args.unimodal:
        table[:-1] = unimodal(table[:-1], ps[:-1])
    return table.astype(np.float32)


def monotone(y, w):
    """Weighted least-squares non-decreasing fit (pool adjacent violators)."""
    blocks = []
    for v, u in zip(y, w):
        blocks.append([v * u, u, 1])
        while len(blocks) > 1 and blocks[-2][0] * blocks[-1][1] > blocks[-1][0] * blocks[-2][1]:
            a, b = blocks.pop(), blocks.pop()
            blocks.append([a[0] + b[0], a[1] + b[1], a[2] + b[2]])
    return np.concatenate([np.full(n, t / u if u else 0.) for t, u, n in blocks]) if blocks else np.zeros(0)


def unimodal(y, w):
    """Closest rise-then-fall sequence: one preferred range per indicator (an end counts as a range)."""
    y, w = np.asarray(y, float), np.maximum(np.asarray(w, float), 1e-12)
    best = None
    for k in range(len(y) + 1):
        z = np.concatenate([monotone(y[:k], w[:k]), monotone(y[k:][::-1], w[k:][::-1])[::-1]])
        err = float(np.sum(w * (z - y) ** 2))
        if best is None or err < best[0] - 1e-12:
            best = (err, z)
    return best[1]


def score(model, tables):
    s = np.zeros(N, np.float32)
    for key, w in model.items():
        if w:
            s += w * tables[key][BINS[key][0]]
    return s


def ranks_of(s):
    if args.train_edges:
        order = np.argsort(-np.r_[s, -np.inf][_PAD], axis=1, kind='stable')
        ordered = np.take_along_axis(_PAD, order, axis=1)
        ranks = np.broadcast_to(np.arange(1, _PAD.shape[1]+1), _PAD.shape)
        valid = ordered < N
        result = np.empty(N, np.int32)
        result[ordered[valid]] = ranks[valid]
        return result
    r = np.empty(N, np.int32)
    for sl in SL.values():
        order = np.argsort(-s[sl], kind='stable')
        r[sl.start + order] = np.arange(1, sl.stop - sl.start + 1)
    return r


SLOTS = tuple(int(x) for x in args.slots.split(',')) if args.slots else ()
CAP = args.cap


def picks_renew(r, K, H):
    """Held names still ranked within the top RENEW are kept another H nights without using
    a new slot; at most CAP names held at once. Returns the held set per night."""
    out, expiry, i = {}, {}, 0
    rs = r if isinstance(r, tuple) else (r,)
    quota = [round(x * K / sum(SLOTS)) for x in SLOTS] if isinstance(r, tuple) else [K]
    quota[0] += K - sum(quota)
    for i, day in enumerate(days):
        sl = SL[day]
        cs = CODES[sl]
        top = {cs[k] for rr in rs for k in np.argsort(rr[sl], kind='stable')[:args.renew]}
        for c in list(expiry):
            if expiry[c] < i:
                del expiry[c]
            elif c in top:
                expiry[c] = i + H - 1
        chosen = []
        for rr, qn in zip(rs, quota):
            order = np.argsort(rr[sl], kind='stable')
            chosen += [cs[k] for k in order if cs[k] not in expiry and cs[k] not in chosen][:qn]
        for c in chosen:
            if len(expiry) >= CAP:
                break
            expiry[c] = i + H - 1
        out[cpos[day]] = set(expiry)
    return out


def picks(r, K, H):
    if args.renew:
        return picks_renew(r, K, H)
    if args.train_edges and not isinstance(r, tuple):
        ordered = np.full(_PAD.shape, -1, np.int32)
        ordered[_ROW_NIGHT, r-1] = np.arange(N)
        out, recent = {}, []
        for i, day in enumerate(days):
            held = set().union(*recent[-max(H, args.cooldown):]) if recent else set()
            chosen, chosen_codes = set(), set()
            for row in ordered[i]:
                if row < 0:
                    break
                code_id = int(_ROW_CODE_IDS[row])
                if code_id not in held:
                    chosen.add(code_id)
                    chosen_codes.add(CODES[row])
                    if len(chosen) == K:
                        break
            out[cpos[day]] = chosen_codes
            recent.append(chosen)
        return out
    out, recent = {}, []
    rs = r if isinstance(r, tuple) else (r,)
    quota = [round(x * K / sum(SLOTS)) for x in SLOTS] if isinstance(r, tuple) else [K]
    quota[0] += K - sum(quota)
    for day in days:
        sl = SL[day]
        cs = CODES[sl]
        held = set().union(*recent[-max(H, args.cooldown):]) if recent else set()
        chosen = []
        for rr, qn in zip(rs, quota):
            order = np.argsort(rr[sl], kind='stable')
            chosen += [cs[k] for k in order if cs[k] not in held and cs[k] not in chosen][:qn]
        out[cpos[day]] = set(chosen)
        recent.append(set(chosen))
    return out


def covered(sel, targets, H):
    lo = 4 if args.renew else 4 + H - 1
    return [any(code in sel.get(j, ()) for j in range(i0 - lo, i0 + 3)) for code, i0, _, _ in targets]


def holding_stats(sel):
    sizes = np.array([len(v) for v in sel.values()])
    return dict(mean=round(float(sizes.mean()), 2), p90=int(np.percentile(sizes, 90)), max=int(sizes.max()))


def evaluate(r, targets, K=3, H=3):
    selected = picks(r, K, H)
    if args.train_edges and FITTING:
        halves = {t[2] for t in targets}
        selected = {j: value for j, value in selected.items()
                    if cal[j][:4] + ('H1' if cal[j][5:7] <= '06' else 'H2') in halves}
    hit = covered(selected, targets, H)
    prim = sum(x for x, t in zip(hit, targets) if t[3])
    soft = 0.
    for code, i0, _, p in targets:
        if p:
            best = min((min(rr[lookup[(code, j)]] for rr in (r if isinstance(r, tuple) else (r,)))
                        for j in range(i0 - 6, i0 + 3) if (code, j) in lookup
                        and (not args.train_edges or not FITTING or TRAIN_MASK[lookup[(code,j)]])), default=None)
            soft += 1 / best if best else 0
    return prim, sum(hit), round(soft, 4)


def halfyear(r, targets, K=3, H=3):
    hit = covered(picks(r, K, H), targets, H)
    return {h: f'{sum(x for x, t in zip(hit, targets) if t[3] and t[2] == h)}/'
               f'{sum(1 for t in targets if t[3] and t[2] == h)}' for h in HALVES}


def better(a, b_):
    return OBJ(a) > OBJ(b_)


def fit(train):
    global FITTING
    FITTING = True
    tables = tables_for(train)
    beams, path, seen = [({}, None)], [], set()
    while beams and len(beams[0][0]) < args.max_attrs:
        trial = []
        for model, _ in beams:
            for k in USE:
                if any(key[0] == k for key in model):
                    continue
                if args.one_per_family and any(FAMILIES[NAMES[key[0]]] == FAMILIES[NAMES[k]] for key in model):
                    continue
                for q in BIN_CHOICES:
                    cand = {**model, (k, q): 1}
                    sig = frozenset(cand)
                    if sig in seen:
                        continue
                    seen.add(sig)
                    val = evaluate(ranks_of(score(cand, tables)), train)
                    trial.append((OBJ(val), -q, -k, sig, cand, val))
        if not trial:
            break
        trial.sort(key=lambda x: x[:3], reverse=True)
        beams = [(x[4], x[5]) for x in trial[:args.beam]]
        path.extend(beams)
    model, best = max(path, key=lambda x: OBJ(x[1]))
    model = dict(model)
    for _ in range(3):
        changed = False
        for key in list(model):
            for w in WEIGHTS:
                if w == model[key]:
                    continue
                val = evaluate(ranks_of(score({**model, key: w}, tables)), train)
                if better(val, best):
                    model[key], best, changed = w, val, True
        model = {k: w for k, w in model.items() if w}
        for key in list(model):
            for k in USE:
                if any(kk[0] == k for kk in model):
                    continue
                if args.one_per_family and any(kk != key and FAMILIES[NAMES[kk[0]]] == FAMILIES[NAMES[k]] for kk in model):
                    continue
                for q in BIN_CHOICES:
                    trial = {kk: w for kk, w in model.items() if kk != key}
                    trial[(k, q)] = model[key]
                    val = evaluate(ranks_of(score(trial, tables)), train)
                    if better(val, best):
                        model, best, changed = trial, val, True
                        break
                if key not in model:
                    break
        if not changed:
            break
    for key in sorted(model, key=lambda k: model[k]):
        trial = {k: w for k, w in model.items() if k != key}
        if trial:
            val = evaluate(ranks_of(score(trial, tables)), train)
            if (OBJ(val) >= OBJ(best)) if args.quality_objective else val[0] >= best[0]:
                model, best = trial, val
    FITTING = False
    return model, tables, best


SETUP = ['ext_ema9_adr', 'ext_ema21_adr', 'gap_today_adr', 'days_since_10pct_gap', 'contract3_adr',
         'from_high20_pct', 'perf5_pct', 'range_today_adr', 'dollar_vol20_M', 'adr20_pct']
if args.library in ('std_v1', 'std_v1_1'):
    SETUP = [name for name in SETUP if name in NAMES]
PCT = {}
for _name in SETUP:
    _x = X[NAMES.index(_name)]
    _p = np.full(N, np.nan, np.float32)
    for _sl in SL.values():
        _v = _x[_sl]
        _ok = np.isfinite(_v)
        if _ok.sum() > 1:
            _p[np.arange(_sl.start, _sl.stop)[_ok]] = np.argsort(np.argsort(_v[_ok])) / (_ok.sum() - 1)
    PCT[_name] = _p


def kmeans(V, K, seed=2026112900):
    g = np.random.default_rng(seed)
    best = None
    for _ in range(20):
        C = V[g.choice(len(V), K, replace=False)]
        for _ in range(100):
            lab = np.argmin(((V[:, None] - C[None]) ** 2).sum(2), 1)
            newC = np.array([V[lab == k].mean(0) if (lab == k).any() else C[k] for k in range(K)])
            if np.allclose(newC, C):
                break
            C = newC
        inertia = ((V - C[lab]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, lab, C)
    return best[1], best[2]


def fit_slots(train):
    tables = tables_for(train)
    P = len(SLOTS)
    models = [{} for _ in range(P)]

    def ranks(ms):
        return tuple(ranks_of(score(m_, tables)) if m_ else ranks_of(np.zeros(N, np.float32)) for m_ in ms)

    path = []
    while sum(len(x) for x in models) < args.max_attrs * P:
        trial = []
        for k in range(P):
            if len(models[k]) >= args.max_attrs:
                continue
            for a in USE:
                if any(key[0] == a for key in models[k]):
                    continue
                for q in BIN_CHOICES:
                    ms = [dict(x) for x in models]
                    ms[k][(a, q)] = 1
                    val = evaluate(ranks(ms), train)
                    trial.append((OBJ(val), -q, -a, -k, k, (a, q), val))
        if not trial:
            break
        *_, k, key, val = max(trial)
        models[k][key] = 1
        path.append(([dict(x) for x in models], val))
    models, best = max(path, key=lambda x: OBJ(x[1]))
    models = [dict(x) for x in models]
    for _ in range(2):
        changed = False
        for k in range(P):
            for key in list(models[k]):
                for w in WEIGHTS:
                    if w == models[k][key]:
                        continue
                    ms = [dict(x) for x in models]
                    ms[k][key] = w
                    if not ms[k] or not any(ms[k].values()):
                        continue
                    val = evaluate(ranks(ms), train)
                    if better(val, best):
                        models, best, changed = ms, val, True
            models[k] = {kk: w for kk, w in models[k].items() if w}
        if not changed:
            break
    return ranks(models), models


def fit_em(train):
    FOCUS.clear()
    model, tables, best = fit(train)
    history = [(best, model, tables, {})]
    for _ in range(args.em):
        s_ = score(model, tables)
        FOCUS.clear()
        for code, i0, _, p in train:
            rows = [lookup[(code, j)] for j in range(i0 - 6, i0 + 3) if (code, j) in lookup]
            if p and rows:
                FOCUS[(code, i0)] = max(rows, key=lambda r_: s_[r_])
        model, tables, best = fit(train)
        history.append((best, model, tables, dict(FOCUS)))
    FOCUS.clear()
    best, model, tables, focus = max(history, key=lambda x: (x[0][0], x[0][2]))
    LAST.update(tables=tables, focus=focus, rounds=[h[0] for h in history])
    return model, tables, best


def _round2(v):
    if not np.isfinite(v) or v == 0:
        return float(v)
    p = 10 ** (np.floor(np.log10(abs(v))) - 1)
    return float(np.round(v / p) * p)


_TIE = None
IV = {}


def interval_cands(k):
    if k not in IV:
        x = X[k][np.isfinite(X[k])]
        e = sorted({_round2(v) for v in np.quantile(x, np.linspace(.1, .9, 9))})
        e = [-np.inf] + e + [np.inf]
        IV[k] = [(e[i], e[j]) for i in range(len(e)) for j in range(i + 1, len(e)) if not (i == 0 and j == len(e) - 1)]
    return IV[k]


def score_iv(model):
    global _TIE
    if _TIE is None:
        _TIE = (1e-3 * (np.nan_to_num(_score, nan=0) - np.nanmin(_score)) / (np.nanmax(_score) - np.nanmin(_score) + 1e-9)).astype(np.float32)
    s = _TIE.copy()
    for k, lo, hi, w in model:
        x = X[k]
        s += w * ((x >= lo) & (x < hi))
    return s


def _width(k, lo, hi):
    x = X[k]
    ok = np.isfinite(x)
    return float(((x[ok] >= lo) & (x[ok] < hi)).mean())


def fit_interval(train):
    """Greedy add (indicator, interval); ties prefer wider intervals; then refine intervals and
    weights; then drop terms that do not cost coverage."""
    def val(m):
        return evaluate(ranks_of(score_iv(m)), train)

    model, path = [], []
    best = val(model)
    while len(model) < args.max_attrs:
        used = {t[0] for t in model}
        trial = []
        for k in USE:
            if k in used:
                continue
            for lo, hi in interval_cands(k):
                v = val(model + [(k, lo, hi, 1)])
                trial.append(((v[0], round(v[2], 2), _width(k, lo, hi)), (k, lo, hi, 1), v))
        if not trial:
            break
        key, term, v = max(trial, key=lambda x: x[0])
        model = model + [term]
        path.append((list(model), v))
        log('IV add', NAMES[term[0]], term[1], term[2], v)
    model, best = max(path, key=lambda x: (x[1][0], x[1][2], -len(x[0])))
    model = list(model)
    for _ in range(3):
        changed = False
        for i in range(len(model)):
            k, lo, hi, w = model[i]
            for lo2, hi2 in interval_cands(k):
                for w2 in (1, 2, 3):
                    if (lo2, hi2, w2) == (lo, hi, w):
                        continue
                    m2 = model[:i] + [(k, lo2, hi2, w2)] + model[i + 1:]
                    v = val(m2)
                    if better(v, best):
                        model, best, changed = m2, v, True
                        k, lo, hi, w = model[i]
        if not changed:
            break
    for t in sorted(model, key=lambda t: t[3]):
        m2 = [x for x in model if x != t]
        if m2:
            v = val(m2)
            if v[0] >= best[0]:
                model, best = m2, v
    log('IV final', [(NAMES[k], lo, hi, w) for k, lo, hi, w in model], best)
    return model


def fit_nested(train):
    """IE30: stability selection inside the training halves; no test labels are seen."""
    halves = sorted({t[2] for t in train})
    count = {}
    for h in halves:
        model, _, _ = fit([t for t in train if t[2] != h])
        for k in {k for (k, q) in model}:
            count[k] = count.get(k, 0) + 1
    keep = sorted(k for k, c in count.items() if c >= args.nested)
    model = {(k, 5): 1 for k in keep}
    log('nested', {NAMES[k]: count[k] for k in sorted(count, key=lambda k: -count[k])}, 'keep', [NAMES[k] for k in keep])
    return model, tables_for(train)


def fit_scorer(train):
    """Single profile, slot-split profiles, or a mixture of per-type profiles."""
    if args.interval:
        model = fit_interval(train)
        return score_iv(model), [model], None
    if args.nested:
        model, tables = fit_nested(train)
        return score(model, tables), [model], None
    if args.em:
        model, tables, _ = fit_em(train)
        return score(model, tables), [model], None
    if SLOTS:
        r, models = fit_slots(train)
        return r, models, None
    if args.mix <= 1:
        model, tables, _ = fit(train)
        return score(model, tables), [model], None
    prim = [t for t in train if t[3]]
    vecs, members = [], []
    for t in prim:
        g = [lookup[(t[0], t[1] + w)] for w in LEARN if (t[0], t[1] + w) in lookup]
        if g:
            vecs.append([float(np.nanmean(PCT[n][g])) if np.isfinite(PCT[n][g]).any() else .5 for n in SETUP])
            members.append(t)
    V = np.array(vecs)
    K = args.mix
    lab, C = kmeans(V, K)
    while K > 1 and np.bincount(lab, minlength=K).min() < 6:
        K -= 1
        lab, C = kmeans(V, K)
    parts = [[t for t, l in zip(members, lab) if l == k] for k in range(K)]
    prior = [np.log(len(x) / len(members)) for x in parts]
    tabs = [tables_for(x) for x in parts]
    models = [{} for _ in range(K)]

    def joint(ms):
        P = np.stack([prior[k] + score(ms[k], tabs[k]) for k in range(K)])
        mx = P.max(0)
        return mx + np.log(np.exp(P - mx).sum(0))

    path = []
    while sum(len(x) for x in models) < args.max_attrs * K:
        trial = []
        for k in range(K):
            if len(models[k]) >= args.max_attrs:
                continue
            for a in USE:
                if any(key[0] == a for key in models[k]):
                    continue
                for q in BIN_CHOICES:
                    ms = [dict(x) for x in models]
                    ms[k][(a, q)] = 1
                    val = evaluate(ranks_of(joint(ms)), train)
                    trial.append((OBJ(val), -q, -a, -k, k, (a, q), val))
        if not trial:
            break
        *_, k, key, val = max(trial)
        models[k][key] = 1
        path.append(([dict(x) for x in models], val))
    models, best = max(path, key=lambda x: OBJ(x[1]))
    models = [dict(x) for x in models]
    for _ in range(2):
        changed = False
        for k in range(K):
            for key in list(models[k]):
                for w in WEIGHTS:
                    if w == models[k][key]:
                        continue
                    ms = [dict(x) for x in models]
                    ms[k][key] = w
                    val = evaluate(ranks_of(joint(ms)), train)
                    if better(val, best):
                        models, best, changed = ms, val, True
            models[k] = {kk: w for kk, w in models[k].items() if w}
        if not changed:
            break
    types = [dict(n=len(parts[k]), center={n: round(float(c), 2) for n, c in zip(SETUP, C[k])},
                  members=[f'{t[0]} {cal[t[1]]}' for t in parts[k]]) for k in range(K)]
    return joint(models), models, types


if args.ie42_stage:
    from studies.trader_replication.martin_profile_ie42 import run_stage
    run_stage(globals(), args.ie42_stage)
    sys.exit(0)

if args.ie40_stage:
    from studies.trader_replication.martin_profile_ie40 import run_stage
    run_stage(globals(), args.ie40_stage)
    sys.exit(0)

if args.ie38_stage:
    from studies.trader_replication.martin_profile_ie38 import run_stage
    run_stage(globals(), args.ie38_stage)
    sys.exit(0)

out = dict(tag=TAG, names=NAMES)
ie9_r = np.empty(N, np.int32)
for sl in SL.values():
    o = np.argsort(-_score[sl], kind='stable')
    ie9_r[sl.start + o] = np.arange(1, sl.stop - sl.start + 1)
out['ie9'] = evaluate(ie9_r, REAL)
rng = np.random.default_rng(2026110401)
rand = []
for _ in range(30):
    r = np.empty(N, np.int32)
    for sl in SL.values():
        r[sl] = rng.permutation(sl.stop - sl.start) + 1
    rand.append(evaluate(r, REAL)[0])
out['random'] = dict(mean=float(np.mean(rand)), lo=int(min(rand)), hi=int(max(rand)))
ceiling = sum(1 for code, i0, _, p in REAL if p and any((code, j) in lookup for j in range(i0 - 6, i0 + 3)))
out['pool_ceiling'] = ceiling
log('IE9', out['ie9'], 'random', out['random'], 'pool ceiling', ceiling)

if args.holdout:
    HO = set(args.holdout.split(','))
    train = [t for t in REAL if t[2] not in HO]
    train_prim = list(train)
    PRIM = {(c, i) for c, i, _, p in train if p}
    if args.learn_all:
        train = [(c, i, h, True) for c, i, h, _ in train]
    test = [t for t in REAL if t[2] in HO]
    n_test = sum(1 for t in test if t[3])
    inner, inner_scores = {}, []
    if args.inner_cv or args.bag:
        for h in sorted({t[2] for t in train}):
            tr_ = [t for t in train if t[2] != h]
            va_ = [t for t in train if t[2] == h]
            si, _, _ = fit_scorer(tr_)
            ri = ranks_of(si)
            inner[h] = sum(x for x, t in zip(covered(picks(ri, 3, 3), va_, 3), va_) if (t[0], t[1]) in PRIM)
            inner_scores.append(ri)
            log('INNER', h, inner[h], 'of', sum(1 for t in va_ if (t[0], t[1]) in PRIM))
        log('INNER_CV', sum(inner.values()), inner)
    sc_, mdls, _ = fit_scorer(train)
    if args.bag:
        sc_ = -np.mean(np.stack(inner_scores + [ranks_of(sc_)]).astype(np.float32), 0)
    rr = sc_ if isinstance(sc_, tuple) else ranks_of(sc_)
    fit_train = evaluate(rr, train_prim)
    hit = covered(picks(rr, 3, 3), test, 3)
    got = sum(x for x, t in zip(hit, test) if t[3])
    hit4 = covered(picks(rr, 2, 2), test, 2)
    got4 = sum(x for x, t in zip(hit4, test) if t[3])
    ie9_test = sum(x for x, t in zip(covered(picks(ie9_r, 3, 3), test, 3), test) if t[3])
    rng2 = np.random.default_rng(2026110402)
    rt = []
    for _ in range(30):
        r = np.empty(N, np.int32)
        for sl in SL.values():
            r[sl] = rng2.permutation(sl.stop - sl.start) + 1
        rt.append(sum(x for x, t in zip(covered(picks(r, 3, 3), test, 3), test) if t[3]))
    res = dict(holdout=sorted(HO), train_fit=fit_train, test_hit=got, test_n=n_test, test_hit_four=got4,
               ie9_test=ie9_test, random_test=dict(mean=float(np.mean(rt)), lo=int(min(rt)), hi=int(max(rt))),
               model=None if args.interval else [[dict(name=NAMES[k], bins=q, weight=w) for (k, q), w in mdl.items()] for mdl in mdls],
               test_detail=[dict(code=t[0], entry=cal[t[1]], hit=bool(x)) for x, t in zip(hit, test) if t[3]])
    if args.interval:
        res['model'] = [[(NAMES[k], lo, hi, w) for k, lo, hi, w in mdls[0]]]
    res['inner_cv'] = dict(total=sum(inner.values()), by_half=inner)
    log('HOLDOUT', {k: v for k, v in res.items() if k != 'test_detail'})
    abl = []
    if args.interval:
        for t in mdls[0]:
            rest = [x for x in mdls[0] if x != t]
            ra = ranks_of(score_iv(rest))
            tr = evaluate(ra, train)[0]
            te = sum(x for x, tt in zip(covered(picks(ra, 3, 3), test, 3), test) if tt[3])
            grp = learn_groups(train)
            his = float(np.mean([np.mean((X[t[0]][g] >= t[1]) & (X[t[0]][g] < t[2])) for g in grp]))
            abl.append(dict(drop=NAMES[t[0]], lo=t[1], hi=t[2], w=t[3], pool_share=round(_width(t[0], t[1], t[2]), 3),
                            his_share=round(his, 3), train=tr, test=te))
            log('ABLATE', abl[-1], 'of', fit_train[0], got)
        res['model'] = [[dict(name=NAMES[k], lo=lo, hi=hi, weight=w) for k, lo, hi, w in mdls[0]]]
    elif not args.bag and not isinstance(sc_, tuple) and len(mdls) == 1 and mdls[0]:
        tabs = tables_for(train)
        for key in mdls[0]:
            rest = {k: w for k, w in mdls[0].items() if k != key}
            ra = ranks_of(score(rest, tabs)) if rest else ie9_r
            tr = evaluate(ra, train)[0]
            te = sum(x for x, t in zip(covered(picks(ra, 3, 3), test, 3), test) if t[3])
            abl.append(dict(drop=NAMES[key[0]], train=tr, test=te))
            log('ABLATE', NAMES[key[0]], 'train', tr, 'of', fit_train[0], 'test', te, 'of', got)
    res['ablation'] = abl
    res['train_fit_four'] = evaluate(rr, train, K=2, H=2)
    tabs = tables_for(train)
    grp = learn_groups(train)
    prof = {}
    for (k, q), w in (mdls[0].items() if len(mdls) == 1 and not args.interval else ()):
        bins, e = BINS[(k, q)]
        labels = ([f'< {e[0]:.3g}'] + [f'{e[i]:.3g} – {e[i + 1]:.3g}' for i in range(len(e) - 1)]
                  + [f'>= {e[-1]:.3g}', 'missing']) if len(e) else ['all', 'missing']
        nb = len(e) + 2
        pool = np.bincount(bins, minlength=nb)
        his = np.zeros(nb)
        for g in grp:
            np.add.at(his, bins[g], 1 / len(g))
        prof[NAMES[k]] = dict(weight=w, bins=[(labels[i], round(pool[i] / pool.sum(), 3), round(his[i] / his.sum(), 3),
                                               round(float(np.exp(tabs[(k, q)][i])), 2)) for i in range(nb) if pool[i]])
        log('PROFILE', NAMES[k], 'w', w, prof[NAMES[k]]['bins'])
    res['profile'] = prof
    log('FOUR', res['train_fit_four'])
    (GAP / f'strong_continue_ie30_{TAG}.json').write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    log('done')
    sys.exit(0)

sc, models, types = fit_scorer(REAL)
rf = sc if isinstance(sc, tuple) else ranks_of(sc)
out['model'] = [[dict(name=NAMES[k], bins=q, weight=w) for (k, q), w in mdl.items()] for mdl in models]
out['types'] = types
model = models[0]
tables = LAST.get('tables') or tables_for(REAL)
out['em_rounds'] = LAST.get('rounds')
out['fit_main'] = evaluate(rf, REAL)
out['fit_four'] = evaluate(rf, REAL, K=2, H=2)
out['fit_halfyear'] = halfyear(rf, REAL)
out['holding'] = holding_stats(picks(rf, 3, 3))
out['holding_four'] = holding_stats(picks(rf, 2, 2))
log('FIT', out['fit_main'], 'four', out['fit_four'], out['fit_halfyear'], 'holding', out['holding'], out['holding_four'])
log('MODEL', out['model'])

profile = {}
groups = learn_groups(REAL)
for (k, q), w in model.items():
    bins, e = BINS[(k, q)]
    labels = ([f'< {e[0]:.3g}'] + [f'{e[i]:.3g} – {e[i + 1]:.3g}' for i in range(len(e) - 1)]
              + [f'>= {e[-1]:.3g}', 'missing']) if len(e) else ['all', 'missing']
    nb = len(e) + 2
    pool = np.bincount(bins, minlength=nb)
    his = np.zeros(nb)
    for g in groups:
        np.add.at(his, bins[g], 1 / len(g))
    profile[NAMES[k]] = [dict(bin=labels[i], pool=round(pool[i] / pool.sum(), 3), his=round(his[i] / his.sum(), 3),
                              ratio=round(float(np.exp(tables[(k, q)][i])), 2)) for i in range(nb) if pool[i]]
out['profile'] = profile
hits = covered(picks(rf, 3, 3), REAL, 3)
out['targets'] = []
for (code, i0, h, p), hit in zip(REAL, hits):
    if p:
        nights = [j for j in range(i0 - 6, i0 + 3) if (code, j) in lookup]
        best_rank = min((int(min(rr[lookup[(code, j)]] for rr in (rf if isinstance(rf, tuple) else (rf,)))) for j in nights), default=None)
        out['targets'].append(dict(code=code, entry=cal[i0], half=h, hit=bool(hit), pool_nights=len(nights), best_rank=best_rank))

if args.checks:
    shuffle = []
    for seed in (() if args.loo_only else range(2026112901, 2026112906)):
        g = np.random.default_rng(seed)
        fake = []
        for code, i0, h, p in REAL:
            near = [j for j in range(i0, i0 + 6) if j < len(cal) and cal[j] in SL]
            if near and any((code, j) in lookup for j in range(i0 - 6, i0 + 3)):
                sl = SL[cal[near[0]]]
                code = CODES[sl][g.integers(sl.stop - sl.start)]
                i0 = near[0]
            fake.append((code, i0, h, p))
        sc_, mdls, _ = fit_scorer(fake)
        shuffle.append(evaluate(sc_ if isinstance(sc_, tuple) else ranks_of(sc_), fake)[0])
        log('shuffle', seed, shuffle[-1], [len(x) for x in mdls])
    out['shuffle_fit'] = shuffle
    loo, chosen = 0, {}
    for h in HALVES:
        train = [t for t in REAL if t[2] != h]
        test = [t for t in REAL if t[2] == h]
        sc_, mdls, _ = fit_scorer(train)
        hit = covered(picks(sc_ if isinstance(sc_, tuple) else ranks_of(sc_), 3, 3), test, 3)
        n = sum(x for x, t in zip(hit, test) if t[3])
        loo += n
        chosen[h] = [[NAMES[k] for (k, q) in mdl] for mdl in mdls]
        log('loo', h, n, chosen[h])
    out['loo'] = dict(hit=loo, attrs=chosen)

(GAP / f'strong_continue_ie29_{TAG}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
log('done')
