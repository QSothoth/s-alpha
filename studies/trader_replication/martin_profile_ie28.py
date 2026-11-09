"""IE28: fit Martin's preference profile on trader-visible daily indicators.

Each indicator is measured in natural units and cut into pool deciles; the score of a
stock-night is the sum over chosen indicators of log(his share / pool share) of its bin,
so a preferred middle zone counts as much as a preferred extreme. Indicators are added
greedily by in-sample coverage (fitting is allowed); shuffled labels and leave-one-half
are reported only. Yardstick: K new names per night, held H nights, entry window -4..+2.
Read-only on caches; writes strong_continue_ie28_profile.json.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/opt/opend-us-options/.claude/worktrees/gap-review')
sys.path.insert(0, str(ROOT))
from studies.trader_replication import martin_continue_ie23 as m  # noqa: E402
from studies.trader_replication import martin_continue_ie9 as ie9  # noqa: E402

GAP = ROOT / 'studies/trader_replication/reports/gap_review'
HALVES = ('2024H1', '2024H2', '2025H1', '2025H2', '2026H1', '2026H2')
LEARN = tuple(int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else '-1,0,1').split(','))
DECILES = int(sys.argv[2]) if len(sys.argv) > 2 else 10
FILTER = sys.argv[3] if len(sys.argv) > 3 else 'ie9'
SMOOTH = 2.0
TAG = f"{'_'.join(map(str, LEARN))}_q{DECILES}_{FILTER}"
MAX_ATTRS = 10

cal = json.load(open(GAP / 'ie5_work/prepared.json'))['days']
cpos = {x: i for i, x in enumerate(cal)}
qqq = pd.Series(np.load(GAP / 'ie5_work/qqq.npy'))
d = m.Data(matrix=False)
b = d.base
GATE_NAMES = list(b.base_names)


def gate_mask(pct):
    ok = np.ones(len(pct), bool)
    for g in ie9.GATES:
        x = pct[:, GATE_NAMES.index(g['name'])]
        if g['name'] == 'h4_history' and FILTER != 'ie9':
            cut = .5 if FILTER == 'h4nan50' else g['cutoff']
            ok &= np.where(np.isfinite(x), x >= cut, True)
        else:
            ok &= np.where(np.isfinite(x), x, -1) >= g['cutoff']
    return ok


passed = np.zeros(b.n, bool)
for day in b.widths:
    sl = b.slices[day]
    passed[sl] = gate_mask(b.base_pct[sl])
if FILTER == 'ie9':
    assert np.array_equal(passed, b.passed & np.isin(np.arange(b.n), np.flatnonzero(passed))), 'gate replica differs'
    assert np.array_equal(np.flatnonzero(passed), d.kept), 'gate replica differs'
kept = np.flatnonzero(passed)
d.slices, d.days, d.codes, off = {}, [], [], 0
for day in b.widths:
    sl = b.slices[day]
    names_ = [c for k, c in enumerate(b.meta['scope'][day]) if passed[sl.start + k]]
    d.slices[day] = slice(off, off + len(names_))
    d.days.extend([day] * len(names_))
    d.codes.extend(names_)
    off += len(names_)
d.n = off
_base = np.load(ie9.WORK / 'full_features.npy', mmap_mode='r')[kept]
_score = np.nan_to_num(_base[:, ie9.NAMES.index('after_inside')], nan=.5) + np.nan_to_num(_base[:, ie9.NAMES.index('near_ema9')], nan=.5)
days = sorted(d.slices)
d.baseline_ranks = np.empty(d.n, np.int32)
for _sl in d.slices.values():
    _o = np.argsort(-_score[_sl], kind='stable')
    d.baseline_ranks[_sl.start + _o] = np.arange(1, _sl.stop - _sl.start + 1)
codes = np.array(d.codes)
row_day = np.array([cpos[x] for x in d.days])
lookup = {(c, i): r for r, (c, i) in enumerate(zip(codes, row_day))}


def anchored_vwap(h, l, c, v, window, pick):
    """VWAP anchored at the lowest low / highest high / largest gap of the trailing window."""
    tp = np.nan_to_num((h + l + c) / 3) * np.nan_to_num(v)
    cpv, cv = np.concatenate(([0], np.cumsum(tp))), np.concatenate(([0], np.cumsum(np.nan_to_num(v))))
    out = np.full(len(c), np.nan)
    for t in range(window, len(c)):
        a = t - window + 1 + pick(t - window + 1, t + 1)
        vol = cv[t + 1] - cv[a]
        if vol > 0:
            out[t] = (cpv[t + 1] - cpv[a]) / vol
    return out


def indicators(code):
    z = np.load(GAP / f'ie5_work/stocks/{code}.npz')
    o, h, l, c, v, t = (z[k].astype(float) for k in ('o', 'h', 'l', 'c', 'v', 't'))
    O, H, L, C, V, T = map(pd.Series, (o, h, l, c, v, t))
    adr = (H / L - 1).rolling(20, min_periods=15).mean()
    e9, e21, e50 = (C.ewm(span=n, adjust=False).mean() for n in (9, 21, 50))
    gap = O / C.shift(1) - 1
    low_ = np.where(np.isfinite(l), l, np.inf)
    high_ = np.where(np.isfinite(h), h, -np.inf)
    gap_ = np.nan_to_num(gap.to_numpy(), nan=-np.inf)
    av_low = anchored_vwap(h, l, c, v, 50, lambda a, b: int(np.argmin(low_[a:b])))
    av_high = anchored_vwap(h, l, c, v, 50, lambda a, b: int(np.argmax(high_[a:b])))
    av_gap = anchored_vwap(h, l, c, v, 60, lambda a, b: int(np.argmax(gap_[a:b])))
    big = np.flatnonzero(np.nan_to_num(gap.to_numpy()) >= .10)
    since = np.full(len(c), 120.)
    for t_ in range(len(c)):
        k = big[big <= t_]
        if len(k):
            since[t_] = min(120, t_ - k[-1])
    rs = C / qqq
    OV = pd.Series(z['extra_option_volume'].astype(float))
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
        'from_high252_pct': (C / H.rolling(252, min_periods=120).max() - 1) * 100,
        'from_high20_pct': (C / H.rolling(20).max() - 1) * 100,
        'over_prior_high_adr': (C / H.shift(1) - 1) / adr,
        'perf1_pct': (C / C.shift(1) - 1) * 100,
        'perf5_pct': (C / C.shift(5) - 1) * 100,
        'perf21_pct': (C / C.shift(21) - 1) * 100,
        'perf63_pct': (C / C.shift(63) - 1) * 100,
        'rs21_vs_qqq_pct': ((C / C.shift(21)) - (qqq / qqq.shift(21))) * 100,
        'rs_line_from_high63_pct': (rs / rs.rolling(63).max() - 1) * 100,
        'close_pos': (C - L) / (H - L),
        'rvol20': V / V.rolling(20, min_periods=15).mean(),
        'rvol3_20': V.rolling(3).mean() / V.rolling(20, min_periods=15).mean(),
        'gap_today_adr': gap / adr.shift(1),
        'days_since_10pct_gap': pd.Series(since),
        'inside_day': ((H <= H.shift(1)) & (L >= L.shift(1))).astype(float),
        'nr7': ((H - L) <= (H - L).rolling(7).min()).astype(float),
        'contract3_adr': (H / L - 1).rolling(3).mean() / adr,
        'avwap_base_low_adr': (C / pd.Series(av_low) - 1) / adr,
        'avwap_base_high_adr': (C / pd.Series(av_high) - 1) / adr,
        'avwap_big_gap_adr': (C / pd.Series(av_gap) - 1) / adr,
        'peer_g5': pd.Series(z['extra_peer_g5'].astype(float)),
        'peer_rank': pd.Series(z['extra_peer_rank'].astype(float)),
        'peers_strong': pd.Series(z['extra_h4_peers'].astype(float)),
        'option_rvol20': OV / OV.rolling(20, min_periods=10).mean(),
        'iv_pct': pd.Series(z['extra_iv'].astype(float)),
    }


NAMES = None
X = None
for code in sorted(set(codes)):
    rows = np.flatnonzero(codes == code)
    ind = indicators(code)
    if X is None:
        NAMES = list(ind)
        X = np.full((len(NAMES), d.n), np.nan, np.float32)
    for k, name in enumerate(NAMES):
        X[k, rows] = ind[name].to_numpy()[row_day[rows]]
X[~np.isfinite(X)] = np.nan
print('indicators', len(NAMES), 'rows', d.n, flush=True)

BINS, EDGES = [], []
for k in range(len(NAMES)):
    x = X[k]
    u = np.unique(x[np.isfinite(x)])
    if len(u) <= 3:
        edges = (u[:-1] + u[1:]) / 2
    else:
        edges = np.unique(np.nanquantile(x, np.linspace(0, 1, DECILES + 1)[1:-1]))
    b = np.where(np.isfinite(x), np.searchsorted(edges, x, side='right'), len(edges) + 1)
    BINS.append(b.astype(np.int16))
    EDGES.append(edges)
NB = [len(e) + 2 for e in EDGES]


def first(x):
    return next(i for i, y in enumerate(cal) if y >= x)


REAL = [(e['code'], first(e['entry_date']), h, bool(p))
        for e, h, p in zip(d.entries, d.entry_half, d.primary)]


def learn_rows(targets):
    out = []
    for code, i0, _, p in targets:
        if p:
            rows = [lookup[(code, i0 + w)] for w in LEARN if (code, i0 + w) in lookup]
            out.append(rows)
    return out


def lr_tables(targets):
    groups = [g for g in learn_rows(targets) if g]
    tables = []
    for k in range(len(NAMES)):
        nb = NB[k]
        pool = np.bincount(BINS[k], minlength=nb).astype(float)
        his = np.zeros(nb)
        for g in groups:
            np.add.at(his, BINS[k][g], 1 / len(g))
        ps = pool / pool.sum()
        hs = (his + SMOOTH * ps) / (his.sum() + SMOOTH)
        tables.append(np.where(pool > 0, np.log(np.where(pool > 0, hs / np.maximum(ps, 1e-12), 1)), 0))
    return tables


def score(attrs, tables):
    s = np.zeros(d.n)
    for k in attrs:
        s += tables[k][BINS[k]]
    return s


def ranks_of(s):
    r = np.empty(d.n, np.int32)
    for sl in d.slices.values():
        order = np.argsort(-s[sl], kind='stable')
        r[sl.start + order] = np.arange(1, sl.stop - sl.start + 1)
    return r


def picks(r, K, H):
    out, recent = {}, []
    for day in days:
        sl = d.slices[day]
        cs = d.codes[sl]
        held = set().union(*recent[-H:]) if recent else set()
        order = np.argsort(r[sl], kind='stable')
        chosen = [cs[k] for k in order if cs[k] not in held][:K]
        out[cpos[day]] = set(chosen)
        recent.append(set(chosen))
    return out


def covered(sel, targets, H):
    return [any(code in sel.get(j, ()) for j in range(i0 - 4 - (H - 1), i0 + 3)) for code, i0, _, _ in targets]


def summary(r, targets, K=3, H=3):
    hit = covered(picks(r, K, H), targets, H)
    prim = [x for x, t in zip(hit, targets) if t[3]]
    half = {h: f'{sum(x for x, t in zip(hit, targets) if t[3] and t[2] == h)}/'
               f'{sum(1 for t in targets if t[3] and t[2] == h)}' for h in HALVES}
    return sum(prim), sum(hit), half


def greedy(train, evaluate=None):
    tables = lr_tables(train)
    chosen, best, path = [], -1, []
    while len(chosen) < MAX_ATTRS:
        trial = []
        for k in range(len(NAMES)):
            if k in chosen:
                continue
            p, a, _ = summary(ranks_of(score(chosen + [k], tables)), train)
            trial.append((p, a, -k, k))
        p, a, _, k = max(trial)
        if p <= best:
            break
        chosen.append(k)
        best = p
        path.append((NAMES[k], p, a))
    return chosen, tables, path


def ablate(chosen, tables, targets):
    current = list(chosen)
    base = summary(ranks_of(score(current, tables)), targets)[0]
    changed = True
    while changed and len(current) > 1:
        changed = False
        for k in list(current):
            rest = [x for x in current if x != k]
            if summary(ranks_of(score(rest, tables)), targets)[0] >= base:
                current, changed = rest, True
                break
    return current


out = {}
ie9 = summary(d.baseline_ranks, REAL)
rng = np.random.default_rng(2026110401)
rand = []
for _ in range(30):
    r = np.empty(d.n, np.int32)
    for sl in d.slices.values():
        r[sl] = rng.permutation(sl.stop - sl.start) + 1
    rand.append(summary(r, REAL)[0])
print('IE9', ie9, 'random mean', np.mean(rand), min(rand), max(rand), flush=True)
out['ie9'], out['random'] = ie9, dict(mean=float(np.mean(rand)), lo=int(min(rand)), hi=int(max(rand)))

tables_all = lr_tables(REAL)
all_attrs = list(range(len(NAMES)))
out['all_indicators'] = summary(ranks_of(score(all_attrs, tables_all)), REAL)
print('all indicators', out['all_indicators'], flush=True)

chosen, tables, path = greedy(REAL)
final = ablate(chosen, tables, REAL)
rf = ranks_of(score(final, tables))
out['greedy_path'] = path
out['final'] = [NAMES[k] for k in final]
out['final_main'] = summary(rf, REAL)
out['final_four'] = summary(rf, REAL, K=2, H=2)
hits = covered(picks(rf, 3, 3), REAL, 3)
detail = []
for (code, i0, h, pr), hit in zip(REAL, hits):
    if not pr:
        continue
    nights = [j for j in range(i0 - 6, i0 + 3) if (code, j) in lookup]
    best = min((int(rf[lookup[(code, j)]]) for j in nights), default=None)
    width = min((d.slices[cal[j]].stop - d.slices[cal[j]].start for j in nights), default=None)
    detail.append(dict(code=code, entry=cal[i0], half=h, hit=bool(hit), pool_nights=len(nights), best_rank=best, pool_width=width))
out['final_targets'] = detail
print('greedy', path, flush=True)
print('final', out['final'], out['final_main'], 'four', out['final_four'], flush=True)

profile = {}
for k in final:
    e = EDGES[k]
    labels = ([f'< {e[0]:.3g}'] + [f'{e[i]:.3g} – {e[i + 1]:.3g}' for i in range(len(e) - 1)]
              + [f'>= {e[-1]:.3g}', 'missing'])
    pool = np.bincount(BINS[k], minlength=NB[k])
    his = np.zeros(NB[k])
    for g in learn_rows(REAL):
        if g:
            np.add.at(his, BINS[k][g], 1 / len(g))
    profile[NAMES[k]] = [dict(bin=labels[b], pool_share=round(pool[b] / pool.sum(), 3),
                              his_share=round(his[b] / his.sum(), 3), log_lr=round(float(tables[k][b]), 2))
                         for b in range(NB[k]) if pool[b]]
out['profile'] = profile

shuffle = []
for seed in range(2026112801, 2026112806):
    g = np.random.default_rng(seed)
    fake = []
    for code, i0, h, p in REAL:
        window = [j for j in range(i0 - 6, i0 + 3) if 0 <= j < len(cal)]
        near = [j for j in range(i0, i0 + 6) if j < len(cal) and cal[j] in d.slices]
        if near and any((code, j) in lookup for j in window):
            sl = d.slices[cal[near[0]]]
            code = d.codes[sl][g.integers(sl.stop - sl.start)]
            i0 = near[0]
        fake.append((code, i0, h, p))
    ch, tb, _ = greedy(fake)
    base = []
    for _ in range(10):
        r = np.empty(d.n, np.int32)
        for sl in d.slices.values():
            r[sl] = g.permutation(sl.stop - sl.start) + 1
        base.append(summary(r, fake)[0])
    shuffle.append(dict(fit=summary(ranks_of(score(ch, tb)), fake)[0], random=float(np.mean(base))))
    print('shuffle', seed, shuffle[-1], flush=True)
out['shuffle_fit'] = shuffle

loo_hit, loo_n, loo_attrs = 0, 0, {}
for h in HALVES:
    train = [t for t in REAL if t[2] != h]
    test = [t for t in REAL if t[2] == h]
    ch, tb, _ = greedy(train)
    ch = ablate(ch, tb, train)
    hit = covered(picks(ranks_of(score(ch, tb)), 3, 3), test, 3)
    loo_hit += sum(x for x, t in zip(hit, test) if t[3])
    loo_n += sum(1 for t in test if t[3])
    loo_attrs[h] = [NAMES[k] for k in ch]
    print('loo', h, sum(x for x, t in zip(hit, test) if t[3]), loo_attrs[h], flush=True)
out['loo'] = dict(hit=loo_hit, n=loo_n, attrs=loo_attrs)

(GAP / f'strong_continue_ie28_profile_{TAG}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str))
print('done', flush=True)
