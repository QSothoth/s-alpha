"""Pre-open bias study: load the raw OpenD tables, build point-in-time features and labels.

Decision time is the regular-session open of day T (09:30 ET): everything dated T-1 or earlier
is known, plus the opening print of T (the gap).  Labels are the
open -> close move of T, i.e. the window a 0DTE position opened at the open is exposed to.

Standard library only.  Rows are plain dicts; features and labels are kept in separate dicts so a
signal never sees a label.
"""
import csv
import math
from bisect import bisect_left
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, pstdev

# 10:1 splits inside the option window; option-contract counts are not comparable across them.
SPLITS = {'US.NVDA': '2024-06-10', 'US.AVGO': '2024-07-15'}
SPLIT_MASK_DAYS = 25
INDEX_ETFS = ('US.SPY', 'US.QQQ', 'US.IWM')


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _read(path):
    if not path.is_file():
        return []
    with path.open(encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def _merge(dirs, rel, key):
    """Union of one table over several raw dirs (train + validation releases), keyed by date."""
    out = {}
    for d in dirs:
        for r in _read(Path(d) / rel):
            out[r[key]] = r
    return out


def _ext30(dirs, tag):
    """Extended-hours 30m bars aggregated per date: pre-market turnover and prices, last after-hours close."""
    out = {}
    for d in dirs:
        for r in _read(Path(d) / 'ext30' / tag):
            day, hm = r['time_key'][:10], r['time_key'][11:16]
            e = out.setdefault(day, {'pm_turn': 0.0, 'pm_0830': None, 'pm_0930': None, 'ah_last': None, 'ah_hm': ''})
            if hm <= '09:30':
                e['pm_turn'] += _f(r['turnover']) or 0.0
                if hm == '08:30':
                    e['pm_0830'] = _f(r['close'])
                elif hm == '09:30':
                    e['pm_0930'] = _f(r['close'])
            elif hm > '16:00' and hm >= e['ah_hm']:
                e['ah_last'], e['ah_hm'] = _f(r['close']), hm
    return out


def load(dirs, symbols=None):
    """Return {'symbols': [...], 'tables': {symbol: {...}}, 'market': {...}}.

    Technical data only (price, volume, options volume / IV, short volume, flow); no fundamentals."""
    dirs = [Path(d) for d in dirs]
    if symbols is None:
        symbols = sorted({'US.' + p.stem for d in dirs for p in (d / 'daily').glob('*.csv')})
    tables = {}
    for s in symbols:
        tag = s.split('.')[1] + '.csv'
        tables[s] = {
            'daily': _merge(dirs, 'daily/' + tag, 'date'),
            'opt': _merge(dirs, 'option_stats/' + tag, 'time'),
            'iv': _merge(dirs, 'iv/' + tag, 'time'),
            'sv': _merge(dirs, 'short_volume/' + tag, 'timestamp_str'),
            'cf': _merge(dirs, 'capital_flow/' + tag, 'date'),
            'ext': _ext30(dirs, tag),
        }
    market = {}
    for d in dirs:
        for r in _read(d / 'market_option.csv'):
            market.setdefault(r['kind'], {})[r['time']] = r
    return {'symbols': symbols, 'tables': tables, 'market': market}


def _third_friday(d):
    first = d.replace(day=1)
    offset = (4 - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def _z(x, hist):
    if x is None or len(hist) < 10:
        return None
    sd = pstdev(hist)
    return None if sd <= 0 else (x - mean(hist)) / sd


def atr20(days, h, lo, c, i):
    """Mean true range of the 20 sessions before days[i], as a fraction of the previous close."""
    tr = []
    for j in range(i - 20, i):
        d, pd_ = days[j], days[j - 1]
        if None in (h[d], lo[d], c[pd_]):
            continue
        tr.append((max(h[d], c[pd_]) - min(lo[d], c[pd_])) / c[pd_])
    return mean(tr) if tr else None


def ah_z(ah, close, atr):
    """After-hours move of one session (last bar after 16:00 vs the regular close) in ATR units."""
    return ((ah['ah_last'] / close - 1) / atr) if ah and ah['ah_last'] and close and atr else None


def _prev_rows(table, days, i, n):
    """Values of ``table`` on the n trading days strictly before days[i] (oldest first, missing skipped)."""
    return [table[d] for d in days[max(0, i - n):i] if d in table]


def build(data, start=None, end=None):
    """Point-in-time rows: [{'symbol', 'date', 'f': features, 'y': labels}] for start <= date <= end."""
    mvol = data['market'].get('VOLUME', {})
    spy = data['tables'].get('US.SPY', {}).get('daily', {})
    spy_days = sorted(spy)
    rows = []
    for s in data['symbols']:
        t = data['tables'][s]
        daily = t['daily']
        days = sorted(daily)
        o = {d: _f(daily[d]['open']) for d in days}
        h = {d: _f(daily[d]['high']) for d in days}
        lo = {d: _f(daily[d]['low']) for d in days}
        c = {d: _f(daily[d]['close']) for d in days}
        to = {d: _f(daily[d]['turnover']) for d in days}
        split = SPLITS.get(s)
        for i in range(22, len(days)):
            T, P = days[i], days[i - 1]
            if (start and T < start) or (end and T > end):
                continue
            if None in (o[T], c[T], c[P], o[P]) or c[days[i - 2]] is None:
                continue
            f = {'symbol': s, 'weekday': date.fromisoformat(T).weekday(), 'is_index': s in INDEX_ETFS}
            win = days[i - 20:i]
            atr = atr20(days, h, lo, c, i)
            f['atr20'] = atr
            f['gap'] = o[T] / c[P] - 1
            f['gap_z'] = f['gap'] / atr if atr else None
            f['r1'] = c[P] / c[days[i - 2]] - 1
            f['r1_z'] = f['r1'] / atr if atr else None
            f['oc1'] = c[P] / o[P] - 1
            f['on1'] = o[P] / c[days[i - 2]] - 1
            f['r5'] = c[P] / c[days[i - 6]] - 1 if c.get(days[i - 6]) else None
            f['r20'] = c[P] / c[days[i - 21]] - 1 if c.get(days[i - 21]) else None
            f['r5_z'] = f['r5'] / (atr * math.sqrt(5)) if atr and f['r5'] is not None else None
            rng = (h[P] - lo[P]) if None not in (h[P], lo[P]) else None
            f['clv1'] = (c[P] - lo[P]) / rng if rng else None
            f['range1_z'] = rng / c[days[i - 2]] / atr if rng and atr else None
            ma20 = mean(c[d] for d in win)
            f['dist_ma20'] = c[P] / ma20 - 1
            f['dist_ma20_z'] = f['dist_ma20'] / atr if atr else None
            hist_to = [to[d] for d in days[i - 21:i - 1] if to[d]]
            f['turn_ratio1'] = to[P] / mean(hist_to) if to[P] and hist_to else None
            on = [math.log(o[days[j]] / c[days[j - 1]]) for j in range(i - 20, i)]
            idr = [math.log(c[days[j]] / o[days[j]]) for j in range(i - 20, i)]
            f['on_sum20'], f['id_sum20'] = sum(on), sum(idr)
            f['up_days5'] = sum(1 for j in range(i - 5, i) if c[days[j]] > c[days[j - 1]])
            # options (row P = T-1); counts are masked for a while after a split
            masked = split is not None and split <= T and len([d for d in days[:i + 1] if d >= split]) <= SPLIT_MASK_DAYS
            op = t['opt'].get(P)
            ovol = _f(op['option_volume']) if op else None
            f['ovol1'] = ovol   # contracts traded on T-1 (options liquidity gate)
            cv = _f(op['call_volume']) if op else None
            pv = _f(op['put_volume']) if op else None
            hist = _prev_rows(t['opt'], days, i - 1, 20)
            hv_o = [_f(r['option_volume']) for r in hist if _f(r['option_volume'])]
            f['ovol20'] = mean(hv_o) if hv_o else None   # mean option volume of the 20 sessions before T-1 (point-in-time universe)
            hv_c = [_f(r['call_volume']) for r in hist if _f(r['call_volume'])]
            hv_p = [_f(r['put_volume']) for r in hist if _f(r['put_volume'])]
            ok = not masked and ovol and len(hv_o) >= 15
            f['ovol_ratio'] = ovol / mean(hv_o) if ok else None
            f['cvol_ratio'] = cv / mean(hv_c) if ok and cv and hv_c else None
            f['pvol_ratio'] = pv / mean(hv_p) if ok and pv and hv_p else None
            lp = math.log(pv / cv) if cv and pv else None
            lph = [math.log(_f(r['put_volume']) / _f(r['call_volume'])) for r in hist
                   if _f(r['put_volume']) and _f(r['call_volume'])]
            f['pcr1'] = pv / cv if cv and pv else None
            f['pcr_z'] = _z(lp, lph)
            ohist = _prev_rows(t['opt'], days, i - 1, 1)
            f['pcr_chg'] = None
            if ohist and lp is not None:
                q = ohist[0]
                if _f(q['put_volume']) and _f(q['call_volume']):
                    f['pcr_chg'] = lp - math.log(_f(q['put_volume']) / _f(q['call_volume']))
            f['opt_to_stock'] = (ovol * 100 * c[P] / to[P]) if ovol and to[P] and not masked else None
            # open-interest changes between the rows before T-1 and T-1 (new positions; S28)
            f['coi_chg'] = f['poi_chg'] = f['oi_net'] = None
            if ohist and op and not masked:
                q = ohist[0]
                c0, c1 = _f(q.get('call_open_interest')), _f(op.get('call_open_interest'))
                p0, p1 = _f(q.get('put_open_interest')), _f(op.get('put_open_interest'))
                if c0 and p0 and c1 is not None and p1 is not None:
                    f['coi_chg'], f['poi_chg'] = c1 / c0 - 1, p1 / p0 - 1
                    f['oi_net'] = ((c1 - c0) - (p1 - p0)) / (c0 + p0)
            # implied / historical volatility (row P)
            iv = t['iv'].get(P)
            ivp = _prev_rows(t['iv'], days, i - 1, 60)
            iv1 = _f(iv['iv']) if iv else None
            f['iv'] = iv1
            f['hv'] = _f(iv['hv']) if iv else None
            f['iv_hv'] = iv1 - f['hv'] if iv1 is not None and f['hv'] is not None else None
            f['iv_chg1'] = iv1 - _f(ivp[-1]['iv']) if iv1 is not None and ivp and _f(ivp[-1]['iv']) is not None else None
            f['iv_z60'] = _z(iv1, [_f(r['iv']) for r in ivp if _f(r['iv']) is not None])
            f['implied_move'] = iv1 / 100 / math.sqrt(252) if iv1 else None
            f['gap_iv'] = f['gap'] / f['implied_move'] if f['implied_move'] else None
            # short volume (row P)
            sv = t['sv'].get(P)
            svh = _prev_rows(t['sv'], days, i - 1, 20)
            s1 = _f(sv['short_percent']) if sv else None
            f['short_pct'] = s1
            f['short_z'] = _z(s1, [_f(r['short_percent']) for r in svh if _f(r['short_percent']) is not None])
            # capital flow (row P), only the last year exists
            def flow_share(d, col):
                row = t['cf'].get(d)
                v = _f(row[col]) if row else None
                return v / to[d] if v is not None and to.get(d) else None
            for col, name in (('sml_in_flow', 'sml_share'), ('main_in_flow', 'main_share')):
                f[name] = flow_share(P, col)
                hist = [x for x in (flow_share(d, col) for d in days[i - 21:i - 1]) if x is not None]
                f[name + '_z'] = _z(f[name], hist) if len(hist) >= 15 else None
            # extended hours: pre-market of T (bars closing <= 09:30) and after-hours of T-1
            ext = t['ext']
            pm, ah = ext.get(T), ext.get(P)
            pm_turn = pm['pm_turn'] if pm else None
            pm_hist = [ext[d]['pm_turn'] for d in days[i - 20:i] if d in ext and ext[d]['pm_turn'] > 0]
            ok = pm_turn is not None and pm_turn > 0 and len(pm_hist) >= 15
            f['pm_ratio'] = pm_turn / mean(pm_hist) if ok else None
            reg_hist = [to[d] for d in days[i - 20:i] if to[d]]
            f['pm_share'] = pm_turn / mean(reg_hist) if ok and reg_hist else None
            f['ah_z'] = ah_z(ah, c[P], atr)
            f['pm_late_z'] = ((pm['pm_0930'] / pm['pm_0830'] - 1) / atr) if pm and pm['pm_0930'] and pm['pm_0830'] and atr else None
            # market context
            k = bisect_left(spy_days, T)
            if 0 < k < len(spy_days) and spy_days[k] == T and k >= 2:
                sP, sPP = spy_days[k - 1], spy_days[k - 2]
                f['spy_gap'] = _f(spy[T]['open']) / _f(spy[sP]['close']) - 1
                f['spy_r1'] = _f(spy[sP]['close']) / _f(spy[sPP]['close']) - 1
            else:
                f['spy_gap'] = f['spy_r1'] = None
            mv = mvol.get(P)
            f['mkt_pcr'] = _f(mv['ratio']) if mv else None
            mh = [_f(mvol[d]['ratio']) for d in days[i - 21:i - 1] if d in mvol and _f(mvol[d]['ratio'])]
            f['mkt_pcr_z'] = _z(f['mkt_pcr'], mh) if f['mkt_pcr'] else None
            # calendar of T (mechanical only: option expiry)
            dT = date.fromisoformat(T)
            f['opex'] = dT == _third_friday(dT)
            # labels
            oc = c[T] / o[T] - 1
            y = {'ret_oc': oc, 'up': oc > 0, 'down': oc < 0,
                 'mag': abs(oc) / f['implied_move'] if f['implied_move'] else None,
                 'trend': abs(c[T] - o[T]) / (h[T] - lo[T]) if h[T] and lo[T] and h[T] > lo[T] else None,
                 'hi_oc': h[T] / o[T] - 1 if h[T] else None, 'lo_oc': lo[T] / o[T] - 1 if lo[T] else None}
            rows.append({'symbol': s, 'date': T, 'f': f, 'y': y})
    rows.sort(key=lambda r: (r['date'], r['symbol']))
    spy_row = {r['date']: r['f'] for r in rows if r['symbol'] == 'US.SPY'}
    by_day = {}
    for r in rows:
        sf = spy_row.get(r['date'])
        r['f']['spy_r1_z'] = sf['r1_z'] if sf else None
        r['f']['spy_gap_z'] = sf['gap_z'] if sf else None
        by_day.setdefault(r['date'], []).append(r)
    for day_rows in by_day.values():   # cross-section of the same pre-open moment
        for r in day_rows:
            f = r['f']
            f['has_0dte'] = f['is_index'] or f['weekday'] in (0, 2, 4)   # 2026 listing calendar (see S5)
        ranked = sorted((r for r in day_rows if r['f']['pcr_z'] is not None), key=lambda r: -r['f']['pcr_z'])
        for k, r in enumerate(ranked, 1):
            r['f']['pcr_z_rank'] = k
            r['f']['pcr_z_rank_low'] = len(ranked) + 1 - k
        tradable = [r for r in ranked if r['f']['has_0dte']]
        for k, r in enumerate(tradable, 1):
            r['f']['pcr_z_rank_0dte'] = k
        for r in day_rows:
            for key in ('pcr_z_rank', 'pcr_z_rank_low', 'pcr_z_rank_0dte'):
                r['f'].setdefault(key, None)
    return rows
