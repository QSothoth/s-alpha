"""Point-in-time A-share panels for TF6 (notes/TF6_PREREG.md): several bar folders merged, point-in-time market cap.

    p = pit.load(parts, meta)   # parts: [(folder, start, end, codes or None)], meta: dataset folders with
                                # universe.json (names), actions.csv.gz and shares.csv.gz
    p['mktcap']                 # (dates x stocks) unadjusted close x total shares as of that day, NaN if unknown

``candidates`` picks the extra-band codes (current cap 3bn-10bn) whose approximate cap ever reached a floor,
so only they need Sina actions and share history: approximate cap = current cap x raw close / last raw close.
"""
from __future__ import annotations

from collections import defaultdict
import csv
import gzip
import json
from pathlib import Path

import numpy as np

from . import fetch, panel

ROOT = Path(__file__).resolve().parents[2]
PIT = ROOT / 'data' / 'trend-breakout-cn-pit-v1'  # Release trend-breakout-cn-pit-v1 (see docs/DATA.md)
HIST = PIT / 'hist' / 'cn'          # the 1,773 main-pool stocks, 2018-01 -> 2023-08
HIST_CNX = PIT / 'hist-cnx' / 'cn'  # current-cap 3bn-10bn stocks, 2018-01 -> 2026-10
CNX = PIT / 'cnx' / 'cn'            # their universe, plus Sina actions and share history for the candidates


def read_shares(folder):
    """{code: [(date, total_shares)]} from every shares*.csv.gz in the folder (rows with no date only mark done)."""
    out = defaultdict(set)
    for path in sorted(Path(folder).glob('shares*.csv.gz')):
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
            for code, day, shares in csv.reader(f):
                if code != 'code' and day:
                    out[code].add((day, float(shares)))
    return {code: sorted(v) for code, v in out.items()}


def shares_asof(dates, history):
    """Total shares in force on each date (latest change on or before it); NaN before the first record."""
    if not history:
        return np.full(len(dates), np.nan)
    days = np.array([d for d, _ in history])
    vals = np.array([v for _, v in history])
    i = np.searchsorted(days, dates, side='right') - 1
    return np.where(i >= 0, vals[np.maximum(i, 0)], np.nan)


def names(meta):
    out = {}
    for folder in meta:
        for s in json.loads((Path(folder) / 'universe.json').read_text(encoding='utf-8'))['stocks']:
            out.setdefault(s['code'], s)
    return out


def load(parts, meta, keep=None):
    """Two streaming passes straight into numpy (a dict of Python rows does not fit in memory for ~4,000
    stocks x 8 years). ``keep(p)`` -> bool per column drops never-needed stocks before indicators run."""
    paths = [(path, start, end, codes) for folder, start, end, codes in parts
             for path in sorted(Path(folder).glob('bars_raw*.csv.gz'))]
    info = names(meta)
    dates, seen = set(), set()
    for path, start, end, codes in paths:
        for code, day, _ in panel.read_bars(path):
            if start <= day <= end and (codes is None or code in codes) and code in info:
                dates.add(day)
                seen.add(code)
    dates, code_list = np.array(sorted(dates)), np.array(sorted(seen))
    di, ci = {d: i for i, d in enumerate(dates)}, {c: j for j, c in enumerate(code_list)}
    raw = np.full((6, len(dates), len(code_list)), np.nan)
    for path, start, end, codes in paths:
        for code, day, values in panel.read_bars(path):
            if start <= day <= end and code in ci and (codes is None or code in codes):
                raw[:, di[day], ci[code]] = values
    actions, shares = {}, {}
    for folder in meta:
        for path in sorted(Path(folder).glob('actions*.csv.gz')):  # actions.csv.gz plus any worker parts
            for code, acts in panel.read_actions(path).items():
                actions[code] = sorted(set(actions.get(code, [])) | set(acts))
        shares.update(read_shares(folder))
    out = {'dates': dates, 'codes': code_list, 'events': {}}
    out['raw_open'], out['raw_high'], out['raw_low'], out['raw_close'] = raw[0], raw[1], raw[2], raw[3]
    out['turnover'] = raw[5]
    for name in ('open', 'high', 'low', 'close', 'volume'):
        out[name] = np.full((len(dates), len(code_list)), np.nan)
    for j, code in enumerate(code_list):
        rows = np.flatnonzero(~np.isnan(raw[3, :, j]))
        if not len(rows):
            continue
        f = panel.factors(raw[3, rows, j], dates[rows], actions.get(code, []))
        out['events'][code] = int(np.sum(np.abs(np.diff(f)) > 1e-12))
        for k, name in enumerate(('open', 'high', 'low', 'close')):
            out[name][rows, j] = raw[k, rows, j] * f
        out['volume'][rows, j] = raw[4, rows, j] / f
    del raw  # the views above keep only the rows they use
    out['mktcap'] = np.column_stack([out['raw_close'][:, j] * shares_asof(dates, shares.get(c, []))
                                     for j, c in enumerate(code_list)])
    out['names'] = {c: info[c].get('name', '') for c in code_list}
    if keep is not None:
        cols = np.asarray(keep(out), bool)
        for k, v in list(out.items()):
            if isinstance(v, np.ndarray) and v.ndim == 2:
                out[k] = np.ascontiguousarray(v[:, cols])
        out['codes'] = code_list[cols]
        out['names'] = {c: out['names'][c] for c in out['codes']}
    return out


def candidates(bars_folder, universe_folder, floor=7e9):
    """Extra-band codes whose approximate cap (current cap x raw close / last raw close) ever reached ``floor``."""
    caps = {s['code']: s['mktcap_cny'] for s in
            json.loads((Path(universe_folder) / 'universe.json').read_text(encoding='utf-8'))['stocks']}
    peak, last = {}, {}
    for path in sorted(Path(bars_folder).glob('bars_raw*.csv.gz')):
        for code, day, values in panel.read_bars(path):
            peak[code] = max(peak.get(code, 0.0), values[3])
            last[code] = values[3]  # each code's rows are written in date order, in one file
    return sorted(c for c in peak if c in caps and last[c] > 0 and caps[c] * peak[c] / last[c] >= floor)


def mark_candidates(bars_folder, universe_folder, floor=7e9):
    """Write the candidates as the 'done' list of the extra-band folder so fetch --actions-only / --shares-only
    pull Sina factors and share history for exactly these codes."""
    codes = candidates(bars_folder, universe_folder, floor)
    folder = Path(universe_folder)
    progress = fetch.prepare(folder)
    progress['done'] = codes
    progress['candidate_floor_cny'] = floor
    fetch.write_json(folder / 'progress.json', progress)
    return codes


if __name__ == '__main__':
    import sys
    if sys.argv[1:2] == ['candidates']:
        got = mark_candidates(HIST_CNX, CNX)
        print(len(got), 'candidates')
