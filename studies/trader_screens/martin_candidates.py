"""Read-only IE8 candidate pool and IE9 reference ranking, separate from accounts."""
from __future__ import annotations

import csv
from itertools import groupby

import numpy as np

from studies.martin_luk.luk import rolling_mean
from studies.trader_replication import ie_factor_library as lib
from studies.trader_replication import martin_continue_ie8 as ie8, martin_continue_ie9 as ie9
from studies.trader_replication.martin_continue_ee import fast_events
from studies.trader_replication.martin_continue_ie import completed_week
from studies.trader_replication.martin_strong import pct
from studies.trader_replication.watchlist import roll_mean

LABEL = '研究观察版、未验证'
FILTERS = (('h4_history', .6), ('adr20', .7), ('option_volume', .8), ('low20', .5))
FACTORS = tuple(name for name, _ in FILTERS) + ('after_inside', 'near_ema9')
REASON = '历史反复强势、期权活跃、振幅较大，脱离20日低点幅度通过过滤条件。'


def leader_columns(panel, evening):
    """The complete IE5 leader scope; later calendar dates contain no price inputs."""
    days = list(map(str, panel['days']))
    a, b = completed_week(days, evening)
    if b is None or b < 21:
        return np.array([], dtype=int)
    close = panel['close']
    with np.errstate(all='ignore'):
        dollar = close[b] * panel['volume'][a:b + 1].sum(0)
        gain = close[b] / close[b - 21] - 1
    return np.flatnonzero((dollar > 3e8) & np.isfinite(gain)
                         & np.isfinite(close[evening]) & (close[evening] > 0))


def history_group(panel, dataset):
    """Only H4's history group, in 64-stock blocks; no peer graph or account replay.

    Keep the research's float32 arithmetic, two pool lags, ordinal ties and
    action-aware raw-close events. The other H4 groups do not enter this filter.
    """
    days, codes = list(map(str, panel['days'])), list(map(str, panel['codes']))
    height, width = panel['close'].shape
    result = np.full(width, np.nan, np.float32)
    if height < 252:
        return result
    # rk[t] reads activity[t-1] inside U4[t-1]; U4 itself reads t-1.
    values = np.full((250, width), np.nan)
    active_value = np.full(width, np.nan, np.float32)
    allowed = np.zeros(width, bool)
    for start in range(0, width, 64):
        sl = slice(start, start + 64)
        h, l, money, raw = (panel[k][:, sl] for k in ('high', 'low', 'turnover', 'raw_close'))
        with np.errstate(all='ignore'):
            h32, l32, money32 = (x.astype(np.float32) for x in (h, l, money))
            adr32 = roll_mean(h32 / l32 - 1, 20).astype(np.float32)
            money20 = roll_mean(money32, 20).astype(np.float32)
            active_value[sl] = np.log(money20[-2] * adr32[-2])
            allowed[sl] = (raw[-2].astype(np.float32) >= 2) & (money20[-2] >= 1e7)
            ranges = h.astype(float) / l.astype(float) - 1
            money64 = money.astype(float)
            activity = np.log(roll_mean(money64, 20) * roll_mean(ranges, 20))
            u4 = ((raw >= 2) & (rolling_mean(money64, 20) >= 5e7)
                  & (rolling_mean(ranges, 20) * 100 >= 3))
        # The 250 rk rows used by stay250[t-1].
        values[:, sl] = np.where(u4[-253:-3] if height > 252 else
                                np.vstack([np.zeros((1, u4.shape[1]), bool), u4[:249]]),
                                activity[-252:-2], np.nan)
    stayed = np.zeros(width, np.int32)
    for row in values:
        ranks = np.argsort(np.argsort(-np.where(np.isfinite(row), row, -np.inf)))
        stayed += np.isfinite(row) & (ranks < 100)
    stayed = (stayed / 250).astype(np.float32)
    active = np.zeros(width, bool)
    ix = np.flatnonzero(allowed & np.isfinite(active_value))
    if len(ix) > 300:
        active[ix[np.argsort(-active_value[ix])[:300]]] = True
    fast = np.full(width, np.nan, np.float32)
    di, ci = {day: t for t, day in enumerate(days)}, {code: j for j, code in enumerate(codes)}
    actions = dataset.actions()
    for code, rows in groupby(dataset.rows(), key=lambda r: r[0]):
        if code not in ci:
            continue
        observed = [(day, bar[3]) for _, day, bar in rows if day in di]
        if not observed:
            continue
        dates, closes = zip(*observed)
        indices = np.array([di[day] for day in dates])
        events = np.zeros((height, 1), np.float32)
        events[indices, 0] = fast_events(dates, closes, actions.get(code, []), indices)
        fast[ci[code]] = roll_mean(events, 250)[-2, 0]
    # Same group averaging and missing-neutral treatment as IE5.prepare.
    score = np.zeros(width, np.float32)
    for field in (stayed, fast):
        score += np.nan_to_num(pct(field[None, :], active[None, :])[0] - .5) / 2
    result[active] = score[active] + .5
    return result


def option_volume(codes, day, mode):
    """Exact-day statistics through the existing frozen/live option-data paths."""
    from studies.trader_options.pricing import DATA, LIVE
    roots = (DATA, LIVE) if mode == 'live' else (DATA,)
    values = np.full(len(codes), np.nan, np.float32)
    latest = ''
    for j, code in enumerate(codes):
        for root in roots:
            path = root / 'stat' / (code + '.csv')
            if not path.exists():
                continue
            with path.open(encoding='utf-8') as stream:
                for row in csv.DictReader(stream):
                    date = row.get('time', '')[:10]
                    if date > day:
                        continue
                    latest = max(latest, date)
                    if date != day or (root != DATA and np.isfinite(values[j])):
                        continue
                    try:
                        value = float(row.get('option_volume', ''))
                    except (ValueError, TypeError):
                        continue
                    if np.isfinite(value):
                        values[j] = value
    return values, latest or None


def price_values(panel, columns):
    """The IE4/IE5 normalized price formulas, rounded at the research cache boundary."""
    out = np.full((len(columns), 4), np.nan, np.float32)
    for k, j in enumerate(columns):
        c, h, l = (panel[field][:, j].astype(float) for field in ('close', 'high', 'low'))
        valid = np.flatnonzero(np.isfinite(c) & (c > 0))
        scale = 100 / c[valid[0]] if len(valid) else 1.
        c, h, l = (x * scale for x in (c, h, l))
        adr = lib.roll(lib.divide(h, l) - 1, 20)
        low = lib.divide(c, lib.roll(c, 20, 'min')) - 1
        near = -lib.divide(abs(lib.divide(c, lib.smooth(c, 9)) - 1), adr)
        previous = (h[-3:-1], l[-3:-1])
        inside = (float(h[-2] <= h[-3] and l[-2] >= l[-3])
                  if len(c) >= 3 and all(np.isfinite(x).all() for x in previous) else np.nan)
        out[k] = adr[-1], low[-1], inside, near[-1]
    return out


def rank_night(codes, raw):
    """Full-scope filtering, then small-pool IE9 ranking; sort codes before stable ties."""
    indices = np.argsort(np.asarray(codes, dtype=str), kind='stable')
    codes, raw = np.asarray(codes)[indices], np.asarray(raw, np.float32)[indices]
    percentiles = ie8.ie7.night_percentiles(raw[:, :4])
    passed = ie8.gate_mask(percentiles, list(FACTORS[:4]), ie9.GATES)
    kept = np.flatnonzero(passed)
    ranked = raw[:, 4:].copy()
    ranked[kept, 1] = ie8.ie7.night_percentiles(raw[kept, 5:6])[:, 0]
    order, _ = ie9.rank_night(ranked, passed, list(FACTORS[4:]), list(FACTORS[4:]))
    scores = np.nan_to_num(ranked, nan=.5).astype(float).mean(1)
    return dict(codes=codes, raw=raw, percentiles=percentiles, passed=passed,
                ranked=ranked, scores=scores, order=order)


def build(panel, dataset, mode='live', *, asof=None, names=None, industries=None):
    """No refresh, writes or trading interfaces. Missing filtering inputs never pass."""
    from . import data
    days = np.asarray(panel['days'], dtype=str)
    end = int(np.searchsorted(days, asof, side='right')) if asof else len(days)
    result = dict(label=LABEL, status='unavailable', asof=str(days[end - 1]) if end else asof,
                  mode=mode, rules='IE8 + IE9', scope_count=0, count=0, candidates=[], inputs={})
    if not end:
        result['note'] = '没有当晚及以前的日 K 数据，候选池未生成。'
        return result
    columns = leader_columns(panel, end - 1)
    p = {key: value[:end] if isinstance(value, np.ndarray) and value.ndim and key != 'codes' else value
         for key, value in panel.items()}
    codes = [str(p['codes'][j]) for j in columns]
    result.update(scope_count=len(codes), digest=str(p.get('digest', '')))
    if not codes:
        result['note'] = '没有可计算的完整 leader 比较范围，候选池未生成。'
        return result
    raw = np.full((len(codes), len(FACTORS)), np.nan, np.float32)
    raw[:, 0] = history_group(p, dataset)[columns]
    raw[:, 1], raw[:, 3], raw[:, 4], raw[:, 5] = price_values(p, columns).T
    raw[:, 2], latest = option_volume(codes, result['asof'], mode)
    for j, factor in enumerate(FACTORS):
        available = int(np.isfinite(raw[:, j]).sum())
        result['inputs'][factor] = dict(available=available, missing=len(codes) - available)
    result['inputs']['option_volume']['latest_cached_day'] = latest
    selected = rank_night(codes, raw)
    names = dataset.names() if names is None else names
    industries = data.industries(codes, 'us') if industries is None else industries
    for rank, k in enumerate(selected['order'], 1):
        code = str(selected['codes'][k])
        event, near = selected['raw'][k, 4:]
        why = ('内包日次日' if event == 1 else '前日非内包日' if np.isfinite(event)
               else '内包日状态缺失，按中性计分')
        why += (f'；距9日线 {abs(float(near)):.2f} 个日均振幅'
                if np.isfinite(near) else '；9日线距离缺失，按中性计分')
        factors = {name: dict(raw=float(value) if np.isfinite(value) else None)
                   for name, value in zip(FACTORS, selected['raw'][k])}
        for j, factor in enumerate(FACTORS[:4]):
            factors[factor]['percentile'] = float(selected['percentiles'][k, j])
        factors['near_ema9']['percentile'] = (float(selected['ranked'][k, 1])
                                             if np.isfinite(selected['ranked'][k, 1]) else None)
        result['candidates'].append(dict(code=code, name=names.get(code, '') or '名称未缓存',
            industry=industries.get(code, '') or '行业未缓存', label=LABEL, rank=rank,
            reference=rank <= 5, reason=REASON, ranking_reason=why,
            score=float(selected['scores'][k]), factors=factors))
    available = result['inputs']['option_volume']['available']
    missing = [name for name, _ in FILTERS if not result['inputs'][name]['available']]
    result.update(count=len(result['candidates']), unavailable_inputs=missing,
                  status='unavailable' if missing else 'ready' if available == len(codes) else 'partial')
    result['note'] = (f'当晚期权成交量覆盖 {available}/{len(codes)} 只；缺失不通过，旧日期不顶替。'
                      'H4历史组仅在原active范围内有值；排名只供观察，不表示买入。')
    if available < len(codes):
        result['note'] += ' 期权输入未齐，当前结果不能视为完整候选池。'
    if missing:
        labels = dict(h4_history='历史反复强势', adr20='20日平均振幅',
                      option_volume='当晚期权成交量', low20='20日低点位置')
        result['note'] += ' 当晚没有可用的' + '、'.join(labels[name] for name in missing) + '。'
    return result
