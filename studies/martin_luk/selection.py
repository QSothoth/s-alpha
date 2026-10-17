"""Point-in-time 'his scanners' selection over the broad US daily universe (3424 names).

    nice -n 19 /opt/futu-opend/venv/bin/python -m studies.martin_luk.selection coverage
"""
from __future__ import annotations

import json
import sys

import numpy as np

from . import fetch_r8, intraday as I, luk

CACHE = luk.CACHE / 'broad_daily.npz'


def broad():
    """Dense (days x codes) adjusted daily panel of the broad universe, built one stock at a time."""
    if not CACHE.exists():
        from studies.trend_breakout import panel
        folder = fetch_r8.DAILY / 'us'
        actions = panel.read_actions(folder / 'actions.csv.gz')
        listed = {s['code'] for s in json.loads((folder / 'universe.json').read_text())['stocks']}
        days = set()
        for code, day, _ in panel.read_bars(folder / 'bars_raw.csv.gz'):
            days.add(day)
        days = np.array(sorted(days))
        di = {d: i for i, d in enumerate(days)}
        codes = sorted(listed)
        ci = {c: i for i, c in enumerate(codes)}
        out = {k: np.full((len(days), len(codes)), np.nan, np.float32)
               for k in ('open', 'high', 'low', 'close', 'turnover', 'raw_close')}

        def flush(code, dd, rows):
            if code not in ci or not rows:
                return
            r = np.array(rows, float)
            f = panel.factors(r[:, 3], np.array(dd), actions.get(code, []))
            idx = [di[d] for d in dd]
            j = ci[code]
            for k, n in (('open', 0), ('high', 1), ('low', 2), ('close', 3)):
                out[k][idx, j] = r[:, n] * f
            out['turnover'][idx, j] = r[:, 5]
            out['raw_close'][idx, j] = r[:, 3]

        cur, dd, rows = None, [], []
        for code, day, values in panel.read_bars(folder / 'bars_raw.csv.gz'):
            if code != cur:
                flush(cur, dd, rows)
                cur, dd, rows = code, [], []
            dd.append(day)
            rows.append(values)
        flush(cur, dd, rows)
        np.savez_compressed(CACHE, days=days, codes=np.array(codes), **out)
    z = np.load(CACHE)
    return {k: z[k] for k in z.files}


def scanners(b, top=.02, adr_min=4.0, min_price=5.0, min_turnover=20e6):
    """Per day (using that day's close): base liquidity/volatility gate and top-`top` relative strength on 1/3/6 months."""
    c = b['close'].astype(float)
    adr = luk.rolling_mean(b['high'].astype(float) / b['low'].astype(float) - 1, 20) * 100
    to20 = luk.rolling_mean(b['turnover'].astype(float), 20)
    with np.errstate(invalid='ignore', divide='ignore'):
        base = (b['raw_close'] >= min_price) & (to20 >= min_turnover) & (adr >= adr_min)
        sel = np.zeros_like(base)
        for h in (21, 63, 126):
            r = c / luk.lag(c, h) - 1
            r = np.where(base, r, np.nan)
            cut = np.nanquantile(r, 1 - top, axis=1)
            sel |= base & (r >= cut[:, None])
    return base, sel, adr


def coverage():
    b = broad()
    base, sel, _ = scanners(b)
    days = b['days']
    m = (days >= '2024-01-02') & (days <= '2026-10-16')
    have = {'US.' + s for s in I.files()} | set(json.loads((I.R8_DIR / 'sample.json').read_text())['picked'])
    codes = b['codes']
    hv = np.array([c in have for c in codes])
    per_day = sel[m].sum(1)
    union = np.flatnonzero(sel[m].any(0))
    picks = sel[m].sum()
    covered = sel[m][:, hv].sum()
    out = dict(base_per_day=float(np.median(base[m].sum(1))), selected_per_day=float(np.median(per_day)),
               union=len(union), union_covered=int(hv[union].sum()), pick_days=int(picks),
               pick_days_covered=int(covered), share_covered=float(covered / picks))
    missing = sorted(str(codes[j]) for j in union if not hv[j])
    out['missing'] = missing
    (I.OUT / 'selection_coverage.json').write_text(json.dumps(out, indent=1))
    print({k: v for k, v in out.items() if k != 'missing'})


if __name__ == '__main__' and sys.argv[1] == 'coverage':
    coverage()


def industries(codes):
    """INDUSTRY plate per code from OpenD get_owner_plate (no quota), cached."""
    path = luk.CACHE / 'industry.json'
    have = json.loads(path.read_text()) if path.exists() else {}
    todo = [c for c in codes if c not in have]
    if todo:
        import time
        import futu as ft
        q = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
        try:
            for k in range(0, len(todo), 200):
                batch = todo[k:k + 200]
                ret, df = q.get_owner_plate(batch)
                if ret != ft.RET_OK:
                    raise RuntimeError(str(df))
                ind = df[df.plate_type == 'INDUSTRY']
                for c in batch:
                    names = ind[ind.code == c].plate_name.tolist()
                    have[c] = names[0] if names else ''
                time.sleep(3.5)                      # 10 requests / 30 s
        finally:
            q.close()
        path.write_text(json.dumps(have, ensure_ascii=False, indent=0))
    return have


def r9():
    b = broad()
    days, codes = b['days'], b['codes']
    base, s1, adr = scanners(b)
    c, o, h = (b[k].astype(float) for k in ('close', 'open', 'high'))
    e9, e21, e50 = luk.ema(c, 9), luk.ema(c, 21), luk.ema(c, 50)
    with np.errstate(invalid='ignore', divide='ignore'):
        s2 = s1 & (e9 > e21) & (e21 > e50)
        r1 = np.where(base, c / luk.lag(c) - 1, np.nan)
        to20 = luk.rolling_mean(b['turnover'].astype(float), 20)
        cut = np.nanquantile(r1, .98, axis=1)
        s4 = base & (r1 >= cut[:, None]) & (b['turnover'] >= 2 * luk.lag(to20))
    union = sorted({str(codes[j]) for j in np.flatnonzero(s2.any(0))})
    ind = industries(union)
    ind_id = {}
    col_ind = np.array([ind_id.setdefault(ind.get(str(cc), ''), len(ind_id)) if ind.get(str(cc), '') else -1
                        for cc in codes])
    s3 = np.zeros_like(s2)
    for t in range(len(days)):
        js = np.flatnonzero(s2[t])
        if len(js):
            ids = col_ind[js]
            for j, g in zip(js, ids):
                if g >= 0 and (ids == g).sum() >= 2:
                    s3[t, j] = True
    s5 = s2 | s4
    T = len(days)
    o1 = np.full_like(c, np.nan)
    o1[:-1] = o[1:]
    fwd = np.full_like(c, np.nan)
    hi = np.full_like(c, np.nan)
    for t in range(T - 10):
        fwd[t] = c[t + 10] / o1[t] - 1
        hi[t] = np.nanmax(h[t + 1:t + 11], axis=0) / o1[t] - 1
    big = np.where(np.isnan(hi), np.nan, (hi >= .20).astype(float))
    valid = base & ~np.isnan(fwd) & ~np.isnan(o1)
    m = (days >= '2024-01-02') & (days <= '2026-10-16')
    out = {}
    for name, s in (('S1', s1), ('S2', s2), ('S3', s3), ('S4', s4), ('S5', s5)):
        rows = []
        for t in np.flatnonzero(m):
            a, z = valid[t] & s[t], valid[t] & ~s[t]
            if a.sum() and z.sum():
                rows.append((days[t], fwd[t, a].mean() - fwd[t, z].mean(), big[t, a].mean() - big[t, z].mean(),
                             fwd[t, a].mean(), big[t, a].mean(), int(a.sum())))
        ex = np.array([r[1] for r in rows])
        exb = np.array([r[2] for r in rows])
        boots = np.random.default_rng(0).choice(ex, (2000, len(ex))).mean(axis=1)
        seg = {k: float(np.mean([r[1] for r in rows if (r[0] < '2025') == (k == '2024')])) for k in ('2024', '2025-26')}
        out[name] = dict(days=len(rows), picks_per_day=float(np.mean([r[5] for r in rows])),
                         fwd10_selected=float(np.mean([r[3] for r in rows])), fwd10_excess=float(ex.mean()),
                         ci=[float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
                         big10_selected=float(np.mean([r[4] for r in rows])), big10_excess=float(exb.mean()),
                         segments=seg, passed=bool(np.percentile(boots, 2.5) > 0 and min(seg.values()) > 0))
        print(name, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out[name].items()}, flush=True)
    out['base'] = dict(fwd10=float(np.nanmean(np.where(valid & m[:, None], fwd, np.nan))),
                       big10=float(np.nanmean(np.where(valid & m[:, None], big, np.nan))))
    print('base', out['base'])
    (I.OUT / 'r9_selection.json').write_text(json.dumps(out, indent=1))


if __name__ == '__main__' and sys.argv[1] == 'r9':
    r9()
