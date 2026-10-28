"""QQQ 1-minute bars as numpy arrays, one row per minute, grouped by ET trading day.

`load()` returns dict(t=datetime64[m], day=int session index, dates=list of 'YYYY-MM-DD', mins=minute of day ET,
o,h,l,c,v float arrays). Extended hours are kept (04:00-20:00 ET); RTH is 09:30-16:00 (mins 570..959).
Cached as data/trullas-qqq-k1/k1.npz next to the raw csv.
"""
import csv
import gzip
import os

import numpy as np

from .fetch import OUT

RAW = os.path.join(OUT, 'QQQ_k1_raw.csv.gz')
CACHE = os.path.join(OUT, 'k1.npz')


def _parse():
    t, o, h, l, c, v = [], [], [], [], [], []
    with gzip.open(RAW, 'rt') as f:
        r = csv.reader(f)
        next(r)
        for row in r:
            # OpenD time_key is the bar end; store bar start = end - 1 minute
            t.append(row[0][:16].replace(' ', 'T'))
            o.append(float(row[1])); h.append(float(row[2])); l.append(float(row[3])); c.append(float(row[4]))
            v.append(float(row[5]))
    t = np.array(t, dtype='datetime64[m]') - np.timedelta64(1, 'm')
    return t, np.array(o), np.array(h), np.array(l), np.array(c), np.array(v)


def load():
    if not os.path.exists(CACHE) or os.path.getmtime(CACHE) < os.path.getmtime(RAW):
        t, o, h, l, c, v = _parse()
        order = np.argsort(t, kind='stable')
        np.savez(CACHE, t=t[order].astype('int64'), o=o[order], h=h[order], l=l[order], c=c[order], v=v[order])
    z = np.load(CACHE)
    t = z['t'].astype('datetime64[m]')
    d = t.astype('datetime64[D]')
    dates, day = np.unique(d, return_inverse=True)
    mins = (t - d).astype(int)
    return dict(t=t, day=day, dates=[str(x) for x in dates], mins=mins,
                o=z['o'], h=z['h'], l=z['l'], c=z['c'], v=z['v'])


def at(px, date, hhmm):
    """Index of the bar starting at ET `hhmm` ('09:29') on `date`, or None."""
    m = int(hhmm[:2]) * 60 + int(hhmm[3:5])
    i = np.searchsorted(px['t'], np.datetime64(f'{date}T00:00') + np.timedelta64(m, 'm'))
    if i < len(px['t']) and px['t'][i] == np.datetime64(f'{date}T00:00') + np.timedelta64(m, 'm'):
        return int(i)
    return None
