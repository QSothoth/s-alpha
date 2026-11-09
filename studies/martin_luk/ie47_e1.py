"""IE47 frozen preference profile on the common data layer; E1 research execution."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
from itertools import groupby
import hashlib
import json
from pathlib import Path

import numpy as np

from studies import trader_data as TD
from studies.trader_data import supplemental as SP
from studies.trader_replication import standard_indicators as SI
from studies.trader_replication.martin_continue_ie import completed_week
from studies.trader_replication.martin_continue_ee import fast_events
from studies.trader_replication.martin_strong import pct
from studies.trader_replication.watchlist import roll_mean
from studies.trader_replication import panels, study, system as Y
from studies.martin_luk.luk import rolling_mean

ROOT = Path(__file__).resolve().parents[2]
PROFILE = Path(__file__).resolve().parent / 'reports/ie47_profile.json'
INDICATORS = ('low252_distance_pct', 'perf5_pct', 'weekly_rsi14', 'weinstein_stage',
              'chan_weekly_buy', 'avwap_big_gap_adr', 'smc_low_sweep')
GATES = (('h4_history', .6), ('adr20', .7), ('option_volume', .8), ('low20', .5))
KIND = 'ie47_pdh'
CLOSE_KIND = 'ie47_close_pdh'
PB_KIND = 'ie47_close_pullback'
RETEST_KIND, OPEN_KIND, RE_KIND = 'ie47_retest', 'ie47_next_open', 'ie47_reentry'
CANDIDATES = ('E1', 'E2', 'E3', 'E4')
# PREREG_E6_CN.md: close confirmation; a wide same-day-low stop is capped (or kept) instead of skipped.
E6 = {'E6a': dict(observe=3, close_confirmed=True, wide='cap', cap_max=.05),
      'E6b': dict(observe=3, close_confirmed=True, wide='keep', cap_max=.05),
      'E6c': dict(observe=5, close_confirmed=True, wide='cap', cap_max=.05),
      'E6d': dict(observe=3, close_confirmed=True, wide='cap', cap_max=.03)}
# PREREG_E7_CN.md: E6c plus his sizing words (probe then add, new-trade feedback) and his pullback entry.
E7 = {'E7a': dict(add=True, feedback=False, pullback=False), 'E7b': dict(add=False, feedback=True, pullback=False),
      'E7c': dict(add=True, feedback=True, pullback=False), 'E7d': dict(add=False, feedback=False, pullback=True),
      'E7e': dict(add=True, feedback=True, pullback=True)}

# PREREG_E8_CN.md: E7a with a daily risk multiplier from his market words (QQQ vs 21 EMA; watch-list breadth).
E8 = {'E8a': dict(qqq=True, breadth=False, pullback=False), 'E8b': dict(qqq=False, breadth=True, pullback=False),
      'E8c': dict(qqq=True, breadth=True, pullback=False), 'E8d': dict(qqq=True, breadth=True, pullback=True)}


def regime_scale(qqq, pool_counts, spec):
    """scale[d] from the previous close / night only: halves when QQQ is not above its 21 EMA (⑦) and when the
    filtering pool is smaller than its own 20-night mean (③ the leader list shrinking)."""
    qqq, n = np.asarray(qqq, float), np.asarray(pool_counts, float)
    scale = np.ones(len(qqq))
    if spec['qqq']:
        on = np.isfinite(qqq) & (qqq > SI.ema(qqq, 21))
        scale[1:] *= np.where(on[:-1], 1., .5)
        scale[0] *= .5
    if spec['breadth']:
        mean = np.array([n[max(0, t-19):t+1].mean() for t in range(len(n))])
        scale[1:] *= np.where(n[:-1] >= mean[:-1]-1e-12, 1., .5)
    return scale


def e8_rules(candidate):
    return replace(e7_rules('E7a'), risk_scale='e8_scale')


def e7_rules(candidate):
    """⑦ probe at half risk and add the same shares at the first later close above the fill; ⑦ new-trade feedback."""
    spec, rules = E7[candidate], execution_rules('E5')
    if spec['add']:
        rules = replace(rules, risk=rules.risk/2, add_signal='always', add_signal_profit=True, add_signal_max=1,
                        add_signal_frac=1.0, add_signal_stop='keep')
    if spec['feedback']:
        rules = replace(rules, feedback=5, risk_low=rules.risk/2)
    return rules


def regimes(qqq):
    """IE42's adjust=False EMA; missing benchmark closes stay explicitly unavailable (-1)."""
    # Match pandas' arithmetic in the frozen IE42 implementation, including its operation order.
    def ewm(span):
        out = np.full(len(qqq), np.nan)
        current = np.nan
        for t, x in enumerate(qqq):
            if np.isfinite(x):
                current = x if not np.isfinite(current) else (1-2/(span+1))*current+2/(span+1)*x
            out[t] = current
        return out
    qqq = np.asarray(qqq, float)
    return np.where(~np.isfinite(qqq), -1, np.where(qqq < ewm(50), 2,
                    np.where(qqq <= ewm(21)*1.01, 1, 0)))


def filter_night(raw):
    """IE7 average ties in the entire nightly scope; h4nan is the sole missing-pass rule."""
    raw = np.asarray(raw, np.float32)
    percentiles = np.full(raw.shape, np.nan, np.float32)
    for k in range(4):
        valid = np.flatnonzero(np.isfinite(raw[:, k]))
        n = len(valid)
        if n < 2:
            percentiles[valid, k] = .5
            continue
        idx = valid[np.argsort(raw[valid, k], kind='stable')]
        values = raw[idx, k]
        a = np.r_[0, np.flatnonzero(values[1:] != values[:-1])+1]
        b = np.r_[a[1:], n]
        percentiles[idx, k] = np.repeat((a+b-1)/2/(n-1), b-a)
    passed = np.ones(len(raw), bool)
    for k, (_, cutoff) in enumerate(GATES):
        x = percentiles[:, k]
        passed &= np.where(np.isfinite(x), x >= cutoff, k == 0)
    return passed, percentiles


def select_nights(rows, scores, codes, cooldown=10):
    """At most three new names per night, stable code order on score ties, ten prior nights excluded."""
    recent, out = deque(maxlen=cooldown), []
    for indices, values in zip(rows, scores):
        held = set().union(*recent) if recent else set()
        order = np.argsort(-np.asarray(values, np.float32), kind='stable')
        chosen = [int(indices[k]) for k in order if str(codes[indices[k]]) not in held][:3]
        out.append(chosen)
        recent.append({str(codes[j]) for j in chosen})
    return out


def history_panel(p, ds):
    """Only H4's history group, reconstructed from daily prices in bounded stock blocks."""
    height, width = p['close'].shape
    activity = np.full((height, width), np.nan, np.float32)
    rank_activity = np.full((height, width), np.nan)
    allowed, u4 = np.zeros((height, width), bool), np.zeros((height, width), bool)
    for start in range(0, width, 64):
        sl = slice(start, start+64)
        h, l, money, raw = (p[k][:, sl] for k in ('high', 'low', 'turnover', 'raw_close'))
        h32, l32, money32, raw32 = (x.astype(np.float32) for x in (h, l, money, raw))
        with np.errstate(all='ignore'):
            adr32 = roll_mean(h32/l32-1, 20).astype(np.float32)
            to32 = roll_mean(money32, 20).astype(np.float32)
            activity[:, sl] = np.log(to32*adr32)
            allowed[1:, sl] = (raw32[:-1] >= 2) & (to32[:-1] >= 1e7)
            ranges = h.astype(float)/l.astype(float)-1
            money64 = money.astype(float)
            rank_activity[:, sl] = np.log(roll_mean(money64, 20)*roll_mean(ranges, 20))
            u4[1:, sl] = ((raw[:-1] >= 2) & (rolling_mean(money64, 20)[:-1] >= 5e7)
                         & (rolling_mean(ranges, 20)[:-1]*100 >= 3))
    top, active = np.zeros((height, width), np.float32), np.zeros((height, width), bool)
    for t in range(1, height):
        row = np.where(u4[t-1], rank_activity[t-1], np.nan)
        ranks = np.argsort(np.argsort(-np.where(np.isfinite(row), row, -np.inf)))
        top[t] = np.isfinite(row) & (ranks < 100)
        ix = np.flatnonzero(allowed[t] & np.isfinite(activity[t-1]))
        if len(ix) > 300:
            active[t, ix[np.argsort(-activity[t-1, ix])[:300]]] = True
    del activity, rank_activity, allowed, u4
    days, codes = list(map(str, p['days'])), list(map(str, p['codes']))
    di, ci = {d: i for i, d in enumerate(days)}, {c: j for j, c in enumerate(codes)}
    events = np.zeros((height, width), np.float32)
    actions = ds.actions()
    for code, rows in groupby(ds.rows(), key=lambda r: r[0]):
        j = ci.get(code)
        if j is None:
            continue
        observed = [(day, bar[3]) for _, day, bar in rows if day in di]
        if observed:
            dates, closes = zip(*observed)
            indices = np.array([di[d] for d in dates])
            events[indices, j] = fast_events(dates, closes, actions.get(code, []), indices)
    stay, fast = np.full_like(top, np.nan), np.full_like(top, np.nan)
    for start in range(0, width, 64):
        sl = slice(start, start+64)
        stay[:, sl] = roll_mean(top[:, sl], 250)
        fast[:, sl] = roll_mean(events[:, sl], 250)
    del events, top
    out = np.full((height, width), np.nan, np.float32)
    for t in range(1, height):
        value = np.zeros(width, np.float32)
        for field in (stay, fast):
            value += np.nan_to_num(pct(field[t-1:t], active[t:t+1])[0]-.5)/2
        out[t, active[t]] = value[active[t]]+.5
    return out


def profile_scores(values, regime, profile):
    """Use only exported float32 bin tables; live never reconstructs or fits them."""
    total = np.zeros(len(regime), np.float32)
    for part in ('shared', 'up', 'pullback'):
        rows = np.ones(len(regime), bool) if part == 'shared' else regime == (0 if part == 'up' else 1)
        score = np.zeros(len(regime), np.float32)
        for item in profile['tables'][part]:
            x = values[item['name']]
            edges = np.asarray(item['edges'])
            bins = np.where(np.isfinite(x), np.searchsorted(edges, x, side='right'), len(edges)+1)
            score += item['weight']*np.asarray(item['scores'], np.float32)[bins]
        total[rows] += score[rows]
    return total


def inputs_digest(sources):
    frozen = {p: v for p, v in sources.items() if not p.startswith('data/trader-options-live/')}
    return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()


def selection(p, ds, mode='frozen', profile=None, progress=None):
    """All nightly decisions on the actual panel; no reads from research caches or future labels."""
    profile = profile or json.loads(PROFILE.read_text(encoding='utf-8'))
    days, codes = list(map(str, p['days'])), np.asarray(p['codes'], str)
    qqq, sources = SP.benchmark('US.QQQ', days, mode)
    option, option_sources = SP.option_volume(codes, days, mode)
    sources.update(option_sources)
    if mode == 'live':
        t = len(days)-1
        a, b = completed_week(days, t)
        if b is None or b < 21:
            raise ValueError('IE47 live has no complete comparison scope')
        with np.errstate(all='ignore'):
            dollar = p['close'][b].astype(float)*p['volume'][a:b+1].astype(float).sum(0)
            gain = p['close'][b].astype(float)/p['close'][b-21].astype(float)-1
        scope = (dollar > 3e8) & np.isfinite(gain) & np.isfinite(p['close'][t]) & (p['close'][t] > 0)
        available = int(np.isfinite(option[t, scope]).sum())
        if available != int(scope.sum()):
            raise ValueError(f'IE47 live option_volume coverage {available}/{int(scope.sum())}; '
                             'the complete scope is required, no replacement filter was used')
    if progress:
        progress('read existing supplementary data')
    h4 = history_panel(p, ds)
    if progress:
        progress('rebuilt H4 daily history group')
    shape = p['close'].shape
    scopes, kept, raw_rows = [], [], []
    adr, low20 = np.full(shape, np.nan, np.float32), np.full(shape, np.nan, np.float32)
    from studies.trader_replication import ie_factor_library as lib
    for j in range(shape[1]):
        c, h, l = (p[key][:, j].astype(float) for key in ('close', 'high', 'low'))
        valid = np.flatnonzero(np.isfinite(c) & (c > 0))
        scale = 100/c[valid[0]] if len(valid) else 1.
        c, h, l = c*scale, h*scale, l*scale
        adr[:, j] = lib.roll(lib.divide(h, l)-1, 20)
        low20[:, j] = lib.divide(c, lib.roll(c, 20, 'min'))-1
    night_indices = [t for t, day in enumerate(days) if day >= profile['first_signal']]
    for t in night_indices:
        a, b = completed_week(days, t)
        if b is None or b < 21:
            scope = np.array([], int)
        else:
            with np.errstate(all='ignore'):
                dollar = p['close'][b].astype(float)*p['volume'][a:b+1].astype(float).sum(0)
                gain = p['close'][b].astype(float)/p['close'][b-21].astype(float)-1
            scope = np.flatnonzero((dollar > 3e8) & np.isfinite(gain) & np.isfinite(p['close'][t])
                                   & (p['close'][t] > 0))
        raw = np.column_stack([x[t, scope] for x in (h4, adr, option, low20)])
        passed, _ = filter_night(raw)
        scopes.append(scope)
        kept.append(scope[passed])
        raw_rows.append(raw)
    del h4, adr, low20, option
    row_t = np.concatenate([np.full(len(ix), t, int) for t, ix in zip(night_indices, kept)])
    row_j = np.concatenate(kept)
    values = {name: np.full(len(row_t), np.nan, np.float32) for name in INDICATORS}
    for k, j in enumerate(np.unique(row_j)):
        rows = np.flatnonzero(row_j == j)
        arrays = {key: p[field][:, j] for key, field in
                  (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume'),
                   ('t', 'turnover'), ('raw_c', 'raw_close'))}
        arrays['days'] = days
        result = SI.per_stock(arrays, qqq, names=INDICATORS)
        for name in INDICATORS:
            values[name][rows] = result[name][row_t[rows]]
        if progress and k % 100 == 0:
            progress(f'indicators {k}/{len(np.unique(row_j))}')
    regime = regimes(qqq)
    scores = profile_scores(values, regime[row_t], profile)
    offset, row_scores = 0, []
    for t, ix in zip(night_indices, kept):
        end = offset+len(ix)
        row_scores.append(scores[offset:end] if regime[t] >= 0 else np.full(len(ix), -np.inf, np.float32))
        offset = end
    # An unavailable benchmark cannot be silently classified as an uptrend.
    available_kept = [ix if regime[t] >= 0 else np.array([], int) for t, ix in zip(night_indices, kept)]
    row_scores = [s if regime[t] >= 0 else np.array([], np.float32) for t, s in zip(night_indices, row_scores)]
    picks = select_nights(available_kept, row_scores, codes, profile['cooldown'])
    pool = np.zeros(shape, bool)
    for t, ix in zip(night_indices, kept):
        pool[t, ix] = True
    return dict(picks={days[t]: [str(codes[j]) for j in ix] for t, ix in zip(night_indices, picks)},
                night_indices=night_indices, scopes=scopes, kept=kept, raw=raw_rows,
                row_t=row_t, row_j=row_j, values=values, scores=scores, regime=regime,
                qqq=qqq, pool=pool, sources=sources)


def execution_rules(candidate='E1'):
    """RULES_CN ⑥ exits, ⑦ sizing/feedback; all additions are opt-in engine fields."""
    if candidate in E6:
        candidate = 'E5'
    if candidate not in CANDIDATES + ('E5',):
        raise ValueError('unknown E1 execution candidate')
    buy, sell = study.COSTS['us']
    return Y.Rules(risk=.005, max_position=.25, max_gross=2.8, max_open=11, max_new_long=4,
                   trims=(3, 5), trim_frac=.15, trail='e9', trail_strict=True,
                   exit_signal='below_e9', entry_day_exit_signal=candidate != 'E5',
                   intraday_kinds=() if candidate == 'E5' else (KIND,),
                   feedback=5 if candidate == 'E4' else 0, feedback_prior_close=candidate == 'E4',
                   risk_low=.0025, buy_cost=buy, sell_cost=sell)


def entry_book(A, picks, observe=5, close_confirmed=False, wide='skip', cap_max=.05, pullback=False, setup=False):
    """③⑤ watch t+1..t+N; ④⑤ strict PDH break; ⑤ no chase; ⑥ prior-low/ADR stop.

    The first break consumes an observation even when chase/account/market rules reject it. Day-bar ordering is
    unknown: day_exit stops before any trim; surviving entries only run the completed-close exit that day.
    E5 instead confirms at the close, skips wide same-day-low stops and starts management tomorrow. E6 keeps the
    E5 stop inside the cap; a wider one is narrowed to the cap (wide='cap') or kept at the low (wide='keep').
    E7 pullback (close-confirmed only): 9 EMA > 21 EMA, the low reaches the 9 EMA, a green close above it.
    E10 setup: ④ a break only counts after an inside day or a narrow day (range < 0.6 x the ADR before it); other
    breaks keep the watch open.
    """
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    ci = {c: j for j, c in enumerate(codes)}
    entries, mask, events, watching = [[] for _ in days], np.zeros_like(A['close'], bool), [], {}
    o, h, l, c = (A[k] for k in ('open', 'high', 'low', 'close'))
    for d in range(1, len(days)):
        for rank, code in enumerate(picks.get(days[d-1], ())):
            if code not in ci:
                raise ValueError('IE47 pick not on the common panel: '+code)
            watching[ci[code]] = (d-1, d-1+observe, rank)
        for j, (born, expiry, rank) in list(watching.items()):
            if d > expiry:
                del watching[j]
                events.append(dict(code=codes[j], day=days[d], why='expired'))
                continue
            inputs = (o[d, j], h[d, j], l[d, j], c[d, j], h[d-1, j], l[d-1, j], A['adr'][d-1, j])
            breakout = c[d, j] if close_confirmed else h[d, j]
            if not np.isfinite(inputs).all() or min(inputs) <= 0:
                continue
            reclaim = pullback and A['e9'][d, j] > A['e21'][d, j] and l[d, j] <= A['e9'][d, j] < c[d, j] \
                and c[d, j] > o[d, j]
            if breakout <= h[d-1, j] and not reclaim:
                continue
            if setup and not (d >= 2 and ((h[d-1, j] <= h[d-2, j] and l[d-1, j] >= l[d-2, j])
                                         or (h[d-1, j]/l[d-1, j]-1)*100 < .6*A['adr'][d-2, j])):
                continue
            del watching[j]
            if close_confirmed:
                fill = float(c[d, j])
                width = max(.01, (fill-float(l[d, j]))/fill)
                cap = min(cap_max, float(A['adr'][d-1, j])/200)
                stop = float(min(l[d, j], fill*.99))
                if wide != 'keep' and width > cap+1e-12:
                    if wide == 'skip' or cap < .01:
                        events.append(dict(code=codes[j], day=days[d], why='wide_stop'))
                        continue
                    stop = fill*(1-cap)
                    events.append(dict(code=codes[j], day=days[d], why='capped', width=width))
                day_exit, kind = None, CLOSE_KIND if breakout > h[d-1, j] else PB_KIND
            else:
                fill = float(max(o[d, j], h[d-1, j]))
                if fill > float(o[d, j])*1.03:
                    events.append(dict(code=codes[j], day=days[d], why='chase'))
                    continue
                width = min(.03, float(A['adr'][d-1, j])/200)
                stop = float(min(max(float(l[d-1, j]), fill*(1-width)), fill*.99))
                day_exit, kind = stop if l[d, j] <= stop else None, KIND
            entries[d].append(((rank, born, codes[j]), j, 1, fill, stop, kind, day_exit))
            mask[d, j] = True
            events.append(dict(code=codes[j], day=days[d], why='triggered', observed=days[born], rank=rank+1))
    return entries, mask, events


# PREREG_E9_CN.md: diagnostic arms that swap the names (B, D) or the day inside the watch (C1, C2, D).
def random_picks(picks, pool, days, codes, rng):
    """Each night's IE47 count drawn without replacement from that night's filtering pool (before scores)."""
    di = {str(v): i for i, v in enumerate(days)}
    out = {}
    for night, names in picks.items():
        cand = np.flatnonzero(pool[di[night]])
        out[night] = [str(codes[k]) for k in rng.choice(cand, min(len(names), len(cand)), replace=False)]
    return out


def triggered_watches(events):
    return {(e['observed'], e['code']) for e in events if e['why'] == 'triggered'}


def random_day_book(A, picks, rng, observe=5, cap_max=.05, keep=None):
    """E6c's watch and stop, but the buy is one uniformly drawn close in t+1..t+observe, with no break required.
    keep: only watches (night, code) in it are registered; a re-pick still ends the earlier watch."""
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    ci = {c: j for j, c in enumerate(codes)}
    entries, mask, events, watching = [[] for _ in days], np.zeros_like(A['close'], bool), [], {}
    l, c = A['low'], A['close']
    for d in range(1, len(days)):
        for rank, code in enumerate(picks.get(days[d-1], ())):
            j = ci[code]
            watching.pop(j, None)
            if keep is None or (days[d-1], code) in keep:
                watching[j] = (d-1, d-1+int(rng.integers(1, observe+1)), rank)
        for j, (born, target, rank) in list(watching.items()):
            if d < target:
                continue
            del watching[j]
            inputs = (l[d, j], c[d, j], A['adr'][d-1, j])
            if not np.isfinite(inputs).all() or min(inputs) <= 0:
                events.append(dict(code=codes[j], day=days[d], why='invalid_bar'))
                continue
            fill = float(c[d, j])
            width = max(.01, (fill-float(l[d, j]))/fill)
            cap = min(cap_max, float(A['adr'][d-1, j])/200)
            stop = float(min(l[d, j], fill*.99))
            if width > cap+1e-12:
                if cap < .01:
                    events.append(dict(code=codes[j], day=days[d], why='wide_stop'))
                    continue
                stop = fill*(1-cap)
                events.append(dict(code=codes[j], day=days[d], why='capped', width=width))
            entries[d].append(((rank, born, codes[j]), j, 1, fill, stop, CLOSE_KIND, None))
            mask[d, j] = True
            events.append(dict(code=codes[j], day=days[d], why='triggered', observed=days[born], rank=rank+1))
    return entries, mask, events


# PREREG_E10_CN.md: entries derived from E6c's close breaks; the stop only uses the break day and earlier.
def capped_stop(price, low, adr, cap_max=.05):
    """E6c's stop under `price`: the low (at least 1% away), narrowed to min(cap_max, ADR/2); None below a 1% cap."""
    cap = min(cap_max, float(adr)/200)
    if cap < .01:
        return None
    stop = float(min(low, price*.99))
    return price*(1-cap) if (price-stop)/price > cap+1e-12 else stop


def derived_book(A, base, mode, valid=3, cap_max=.05):
    """mode 'retest': a limit at the broken high h[b-1] for b+1..b+valid (open at or below it fills at the open, an
    open at or below the stop cancels); 'next_open': buy the b+1 open when it is above h[b-1], ⑤ not more than 3%
    above it. The stop is capped_stop(fill price, the break day's low, ADR as of b-1). Same-day stops are declared; a limit above its stop is always filled before the stop is reached."""
    o, h, l = A['open'], A['high'], A['low']
    entries, events = [[] for _ in A['days']], []
    mask = np.zeros_like(A['close'], bool)
    for b, row in enumerate(base[0]):
        for pr, j, _, _, _, kind, *_ in row:
            if kind != CLOSE_KIND:
                continue
            level, code, after = float(h[b-1, j]), pr[2], None
            if mode == 'retest':
                stop = capped_stop(level, l[b, j], A['adr'][b-1, j], cap_max)
                why = 'wide_stop' if stop is None else 'expired'
                for d in range(b+1, min(len(entries), b+1+valid)) if stop is not None else ():
                    if not np.isfinite((o[d, j], l[d, j])).all():
                        continue
                    if o[d, j] <= stop:
                        why = 'cancel_gap'
                        break
                    if l[d, j] > level:
                        continue
                    fill = float(min(o[d, j], level))
                    entries[d].append((pr, j, 1, fill, stop, RETEST_KIND, stop if l[d, j] <= stop else None))
                    mask[d, j], why, after = True, 'filled', d-b
                    break
            else:
                d, why = b+1, 'no_gap'
                if d < len(entries) and np.isfinite(o[d, j]) and o[d, j] > level*1.03:
                    why = 'chase'
                elif d < len(entries) and np.isfinite(o[d, j]) and o[d, j] > level:
                    fill = float(o[d, j])
                    stop = capped_stop(fill, l[b, j], A['adr'][b-1, j], cap_max)
                    why = 'wide_stop' if stop is None else 'filled'
                    if stop is not None:
                        entries[d].append((pr, j, 1, fill, stop, OPEN_KIND, stop if l[d, j] <= stop else None))
                        mask[d, j] = True
            events.append(dict(code=code, day=str(A['days'][b]), why=why, mode=mode, after=after))
    return entries, mask, events


def reentry_book(A, entries, e9, window=10, cap_max=.05):
    """entries plus one re-buy per entry: cleanly stopped (low at or below its stop before any close below the 9 EMA
    and before any high at 3R), then the first close above its fill within `window` sessions is bought at that
    close with E6c's stop."""
    l, c = A['low'], A['close']
    out = [list(row) for row in entries]
    n = len(out)
    for b, row in enumerate(entries):
        for e in row:
            pr, j, _, fill, stop = e[:5]
            out_day = b if len(e) > 6 and e[6] is not None else None
            for d in range(b+1, n) if out_day is None else ():
                if l[d, j] <= stop:
                    out_day = d
                    break
                if c[d, j] < e9[d, j] or A['high'][d, j] >= fill+3*(fill-stop):
                    break
            if out_day is None:
                continue
            for r in range(out_day+1, min(n, out_day+1+window)):
                if np.isfinite(c[r, j]) and c[r, j] > fill:
                    new = capped_stop(float(c[r, j]), l[r, j], A['adr'][r-1, j], cap_max)
                    if new is not None:
                        out[r].append((pr, j, 1, float(c[r, j]), new, RE_KIND, None))
                    break
    return out


class IE47Study(study.Study):
    id, name = 'martin_luk_ie47', 'Martin Luk（IE47 研究版）'
    root = Path(__file__).resolve().parent
    ledger = root / 'notes/trades.csv'
    cutoff = '2026-01-01'
    home = ('us',)
    # below_e9 is an unconditional close exit, including the entry close; its line is already active.
    trail_always_active = True
    his = {'2024': dict(ret=2.83, per_year=423, win=.25, avg_win=.15, avg_loss=-.03),
           '2025': dict(ret=9.70, per_year=940, win=.22, avg_win=.141, avg_loss=-.021)}

    def arrays(self, market, upto=None, mode=None):
        if market != 'us':
            raise ValueError('IE47 is registered for US stocks only')
        from studies.trader_screens import screens as S
        mode = TD.resolve_mode(mode)
        p = panels.load(market, upto, mode)
        A = dict(days=p['days'], codes=p['codes'], market=market, mode=mode, digest=p['digest'], _panel=p)
        A.update({key: p[key] for key in ('open', 'high', 'low', 'close', 'volume', 'turnover')})
        A['raw'], A['has'] = p['raw_close'], np.isfinite(p['close'])
        A['adr'], A['to20'] = np.full_like(A['close'], np.nan, dtype=float), np.full_like(A['close'], np.nan, dtype=float)
        for start in range(0, len(A['codes']), 64):
            sl = slice(start, start+64)
            with np.errstate(all='ignore'):
                A['adr'][:, sl] = S.rolling(A['high'][:, sl].astype(float)/A['low'][:, sl].astype(float)-1, 20, 'mean')*100
            A['to20'][:, sl] = S.rolling(A['turnover'][:, sl].astype(float), 20, 'mean')
        return A

    def selected(self, A):
        if '_ie47' not in A:
            if A['mode'] == 'live':
                qqq, _ = SP.benchmark('US.QQQ', A['days'], 'live')
                missing = np.flatnonzero(~np.isfinite(qqq) | (qqq <= 0))
                if len(missing):
                    raise ValueError(f"IE47 live QQQ closes missing on {len(missing)} sessions, first "
                                     f"{A['days'][missing[0]]}; existing data only, no stale-price substitution")
            A['_ie47'] = selection(A['_panel'], TD.dataset('us', A['mode']), A['mode'],
                                   progress=getattr(self, 'progress', None))
        return A['_ie47']

    def market_gate(self, A, cfg):
        if cfg.get('candidate', 'E1') != 'E2':
            return None
        qqq = self.selected(A)['qqq']
        return np.r_[False, (np.isfinite(qqq) & (qqq >= SI.ema(qqq, 50)))[:-1]]

    def named(self, A, pool, name):
        from studies.trader_screens import screens as S
        if name == 'e9':
            return S.ema(A['close'], 9)
        if name == 'e21':
            return S.ema(A['close'], 21)
        if name == 'always':
            return np.ones(A['close'].shape, bool)
        if name == 'below_e9':
            if 'e9' not in A:
                A['e9'] = self.named(A, pool, 'e9')
            return A['close'] < A['e9']
        raise KeyError(name)

    def build(self, A, cfg, trace=None):
        chosen = cfg.get('candidate', 'E1')
        if cfg.get('profile_sha256') and cfg['profile_sha256'] != SP.sha(PROFILE):
            raise ValueError('IE47 profile differs from the selected configuration')
        result = self.selected(A)
        if cfg.get('frozen_inputs_sha256') and cfg['frozen_inputs_sha256'] != inputs_digest(result['sources']):
            raise ValueError('IE47 frozen supplementary inputs changed')
        if chosen in E7 or chosen in E8:
            for name in ('e9', 'e21'):
                if name not in A:
                    A[name] = self.named(A, None, name)
            spec = E7[chosen] if chosen in E7 else E8[chosen]
            entries, mask, events = entry_book(A, result['picks'], **E6['E6c'], pullback=spec['pullback'])
            if chosen in E8:
                A['e8_scale'] = regime_scale(result['qqq'], result['pool'].sum(axis=1), spec)
        elif chosen in E6:
            entries, mask, events = entry_book(A, result['picks'], **E6[chosen])
        else:
            entries, mask, events = entry_book(A, result['picks'], 3 if chosen in ('E3', 'E5') else 5,
                                             close_confirmed=chosen == 'E5')
        raw = entries
        allow = self.market_gate(A, cfg)
        if allow is not None:
            entries = [row if allow[d] else [] for d, row in enumerate(entries)]
        if trace is not None:
            trace.update(raw=raw, filtered=entries, capped=entries, observations=events)
        rules = e8_rules(chosen) if chosen in E8 else e7_rules(chosen) if chosen in E7 else execution_rules(chosen)
        if cfg.get('rule_opts'):
            rules = replace(rules, **cfg['rule_opts'])
        # The placebo is the whole previous evening's filtering pool, before profile scores.
        pool = np.zeros_like(result['pool'])
        pool[1:] = result['pool'][:-1]
        return entries, rules, mask, pool


STUDY = IE47Study()
