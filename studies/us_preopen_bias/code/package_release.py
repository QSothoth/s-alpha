"""Split the raw pull into the train / validation Release directories (by row date) and hash them.

    python3 studies/us_preopen_bias/code/package_release.py data/preopen-us-raw data
    python3 studies/us_preopen_bias/code/package_release.py --holdout data/preopen-us-holdout-raw data/preopen-us-holdout-2016-v1
    python3 studies/us_preopen_bias/code/package_release.py --ext30 data/preopen-us-ext30-raw data
    python3 studies/us_preopen_bias/code/package_release.py --xsec data/preopen-us-xsec-raw data/preopen-us-xsec-v1
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

CUT = '2025-07-01'   # first validation date
TABLES = {'daily': 'date', 'option_stats': 'time', 'iv': 'time', 'short_volume': 'timestamp_str',
          'capital_flow': 'date'}
FIELDS = {
    'daily/<SYM>.csv': 'OpenD request_history_kline K_DAY, QFQ; date = session date',
    'option_stats/<SYM>.csv': 'get_option_underlying_his_statistic; volumes of that session, OI delayed one day (T-1)',
    'iv/<SYM>.csv': 'get_option_underlying_his_volatility; iv / hv in percent at that session close',
    'short_volume/<SYM>.csv': 'get_daily_short_volume (US); short_percent = total_shares_short / volume, in percent',
    'capital_flow/<SYM>.csv': 'get_capital_flow(DAY); only 2025-09-24 on exists (rolling one year)',
    'market_option.csv': 'get_option_market_statistic US_SECURITY; kind VOLUME / OPEN_INTEREST, ratio = put / call',
}


def split_csv(src, dst_train, dst_valid, key):
    with src.open(encoding='utf-8') as fh:
        r = csv.DictReader(fh)
        cols, rows = r.fieldnames, list(r)
    counts = {}
    for dst, keep in ((dst_train, lambda d: d < CUT), (dst_valid, lambda d: d >= CUT)):
        part = [x for x in rows if keep(x[key])]
        counts[dst] = (len(part), min((x[key] for x in part), default=None), max((x[key] for x in part), default=None))
        if not part:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        with dst.open('w', newline='', encoding='utf-8') as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(part)
    return counts


def checksums(root):
    lines = []
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.name != 'CHECKSUMS.sha256':
            lines.append('%s  %s' % (hashlib.sha256(p.read_bytes()).hexdigest(), p.relative_to(root).as_posix()))
    (root / 'CHECKSUMS.sha256').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    train, valid = out / 'preopen-us-train-v1', out / 'preopen-us-valid-v1'
    for d in (train, valid):
        if d.exists():
            raise SystemExit('refuse: %s exists' % d)
    log = json.loads((raw / 'fetch_log.json').read_text(encoding='utf-8'))
    stats = {train.name: {}, valid.name: {}}
    for table, key in TABLES.items():
        for src in sorted((raw / table).glob('*.csv')):
            rel = '%s/%s' % (table, src.name)
            c = split_csv(src, train / rel, valid / rel, key)
            stats[train.name][rel], stats[valid.name][rel] = c[train / rel], c[valid / rel]
    rel = 'market_option.csv'
    c = split_csv(raw / rel, train / rel, valid / rel, 'time')
    stats[train.name][rel], stats[valid.name][rel] = c[train / rel], c[valid / rel]
    for d, role in ((train, 'train/preopen'), (valid, 'validation/preopen')):
        spans = [v for v in stats[d.name].values() if v[0]]
        window = [min(v[1] for v in spans), max(v[2] for v in spans)]
        manifest = {
            'name': d.name, 'role': role, 'window': window, 'study': 'studies/us_preopen_bias',
            'source': 'local OpenD, read-only; kline only for symbols already charged in the 30-day quota',
            'fetched_at': log['fetched_at'], 'symbols': log['symbols'],
            'kline_quota_before_after': [log['kline_quota_before'], log['kline_quota_after']],
            'files': FIELDS, 'rows': {k: v[0] for k, v in stats[d.name].items()},
            'note': ('selection segment only; no row dated on or after %s' % CUT if d is train else
                     'validation segment only; features need a warm-up, so load together with preopen-us-train-v1'),
        }
        (d / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        checksums(d)
        print(d, sum(v[0] for v in stats[d.name].values()), 'rows')




def package_holdout(raw, dst):
    """Older price-only holdout (daily K before the train release), for rounds S6+."""
    if dst.exists():
        raise SystemExit('refuse: %s exists' % dst)
    log = json.loads((raw / 'fetch_log.json').read_text(encoding='utf-8'))
    rows, spans = {}, []
    for src in sorted((raw / 'daily').glob('*.csv')):
        rel = 'daily/' + src.name
        (dst / 'daily').mkdir(parents=True, exist_ok=True)
        (dst / rel).write_bytes(src.read_bytes())
        with src.open(encoding='utf-8') as fh:
            dates = [r['date'] for r in csv.DictReader(fh)]
        rows[rel] = len(dates)
        spans.append((dates[0], dates[-1]))
    manifest = {
        'name': dst.name, 'role': 'holdout/preopen-price', 'study': 'studies/us_preopen_bias',
        'window': [min(s[0] for s in spans), max(s[1] for s in spans)],
        'source': 'local OpenD request_history_kline K_DAY QFQ, read-only; symbols already charged',
        'fetched_at': log['fetched_at'], 'symbols': log['symbols'],
        'kline_quota_before_after': [log['kline_quota_before'], log['kline_quota_after']],
        'files': {'daily/<SYM>.csv': FIELDS['daily/<SYM>.csv']}, 'rows': rows,
        'note': ('price-only holdout for S6+: labels 2016-01-04 .. 2023-07-31 were never evaluated in S1-S5; '
                 'load together with preopen-us-train-v1 for 2022-06 .. 2023-07'),
    }
    (dst / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    checksums(dst)
    print(dst, sum(rows.values()), 'rows')


EXT30_SPLIT = {'preopen-us-ext30-select-v1': ('2023-06-01', '9999'), 'preopen-us-ext30-holdout-v1': ('0000', '2023-08-01')}


def package_ext30(raw, out):
    """Extended-hours 30m bars (S7): selection part (from 2023-06 for warm-up) and the 2020-2023 holdout part."""
    log = json.loads((raw / 'fetch_log.json').read_text(encoding='utf-8'))
    for name, (lo, hi) in EXT30_SPLIT.items():
        dst = out / name
        if dst.exists():
            raise SystemExit('refuse: %s exists' % dst)
        rows, spans = {}, []
        for src in sorted((raw / 'ext30').glob('*.csv')):
            with src.open(encoding='utf-8') as fh:
                r = csv.DictReader(fh)
                cols, part = r.fieldnames, [x for x in r if lo <= x['time_key'][:10] < hi]
            if not part:
                continue
            rel = 'ext30/' + src.name
            (dst / 'ext30').mkdir(parents=True, exist_ok=True)
            with (dst / rel).open('w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                w.writeheader()
                w.writerows(part)
            rows[rel] = len(part)
            spans.append((part[0]['time_key'][:10], part[-1]['time_key'][:10]))
        holdout = 'holdout' in name
        manifest = {
            'name': name, 'role': 'holdout/preopen-ext30' if holdout else 'train/preopen-ext30', 'study': 'studies/us_preopen_bias',
            'window': [min(x[0] for x in spans), max(x[1] for x in spans)],
            'source': 'local OpenD request_history_kline K_30M QFQ extended_time=True, read-only; symbols already charged',
            'fetched_at': log['fetched_at'], 'symbols': log['symbols'],
            'kline_quota_before_after': [log['kline_quota_before'], log['kline_quota_after']],
            'files': {'ext30/<SYM>.csv': 'only bars closing <= 09:30 (pre-market) or after 16:00 (after-hours); '
                                         'time_key = bar close, US Eastern; pre-market volume is 0 before 2020-01'},
            'rows': rows,
            'note': ('S7 holdout: labels 2020-02-03 .. 2023-07-31 never evaluated before S7; load with '
                     'preopen-us-holdout-2016-v1 + preopen-us-train-v1 for daily K' if holdout else
                     'S7 selection 2023-08-01 .. 2026-09-23 (June-July 2023 only as warm-up); load with the train and valid releases'),
        }
        (dst / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        checksums(dst)
        print(dst, sum(rows.values()), 'rows')


def package_xsec(raw, dst):
    """S10: 40 names never used before (daily K via subscription + capital flow), one-shot test data."""
    if dst.exists():
        raise SystemExit('refuse: %s exists' % dst)
    log = json.loads((raw / 'fetch_log.json').read_text(encoding='utf-8'))
    rows, spans = {}, []
    for table in ('daily', 'capital_flow'):
        for src in sorted((raw / table).glob('*.csv')):
            rel = '%s/%s' % (table, src.name)
            (dst / table).mkdir(parents=True, exist_ok=True)
            (dst / rel).write_bytes(src.read_bytes())
            with src.open(encoding='utf-8') as fh:
                dates = [r['date'] for r in csv.DictReader(fh)]
            rows[rel] = len(dates)
            if dates:
                spans.append((dates[0], dates[-1]))
    manifest = {
        'name': dst.name, 'role': 'holdout/preopen-xsec', 'study': 'studies/us_preopen_bias',
        'window': [min(x[0] for x in spans), max(x[1] for x in spans)],
        'source': ('local OpenD, read-only: daily K from get_cur_kline (K_DAY subscription, latest 1000 bars, QFQ; '
                   'no history-kline quota), capital flow from get_capital_flow(DAY) (rolling one year)'),
        'fetched_at': log['fetched_at'], 'symbols': log['symbols'],
        'universe_rule': 'top 40 US underlyings by option volume on the 2026-09-23 OpenD rank, excluding the 16 study names',
        'kline_quota_before_after': [log['kline_quota_before'], log['kline_quota_after']],
        'files': {'daily/<SYM>.csv': FIELDS['daily/<SYM>.csv'].replace('request_history_kline', 'get_cur_kline'),
                  'capital_flow/<SYM>.csv': FIELDS['capital_flow/<SYM>.csv']},
        'rows': rows, 'note': 'S10 one-shot cross-sectional test of K1; evaluate once',
    }
    (dst / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    checksums(dst)
    print(dst, sum(rows.values()), 'rows')


S21_CUT = '2025-01-01'
S21_TABLES = {'daily': 'date', 'option_stats': 'time', 'iv': 'time', 'short_volume': 'timestamp_str', 'capital_flow': 'date',
              'ext30': 'time_key', 'daily_none': 'date'}


def package_s21(sources, out, universe, prefix='preopen-s21', source_note=None, holdout=None):
    """S21 daily long / short lists: daily-level tables of the 34 small / mid caps, split at 2025-01-01.
    ``sources`` maps a release table name to [(raw dir, subdir)].  With ``holdout`` (a note), one unsplit
    ``<prefix>-holdout-v1`` directory instead (S27: names never used before, evaluated once)."""
    segments = ([(prefix + '-holdout-v1', lambda d: True)] if holdout else
                [(prefix + '-select-v1', lambda d: d < S21_CUT), (prefix + '-valid-v1', lambda d: d >= S21_CUT)])
    for name, keep in segments:
        dst = out / name
        if dst.exists():
            raise SystemExit('refuse: %s exists' % dst)
        rows, spans = {}, []
        for table, key in S21_TABLES.items():
            for raw, sub in sources.get(table, []):
                for src in sorted((raw / sub).glob('*.csv')):
                    with src.open(encoding='utf-8') as fh:
                        r = csv.DictReader(fh)
                        cols, part = r.fieldnames, [x for x in r if keep(x[key][:10])]
                    if not part:
                        continue
                    rel = '%s/%s' % (table, src.name)
                    (dst / table).mkdir(parents=True, exist_ok=True)
                    with (dst / rel).open('w', newline='', encoding='utf-8') as fh:
                        w = csv.DictWriter(fh, fieldnames=cols)
                        w.writeheader()
                        w.writerows(part)
                    rows[rel] = len(part)
                    spans.append((part[0][key][:10], part[-1][key][:10]))
        mk = sources.get('market_option')
        if mk:
            with mk.open(encoding='utf-8') as fh:
                r = csv.DictReader(fh)
                cols, part = r.fieldnames, [x for x in r if keep(x['time'])]
            with (dst / 'market_option.csv').open('w', newline='', encoding='utf-8') as fh:
                w = csv.DictWriter(fh, fieldnames=cols)
                w.writeheader()
                w.writerows(part)
            rows['market_option.csv'] = len(part)
        valid = 'valid' in name or bool(holdout)
        manifest = {
            'name': name, 'role': ('validation/' if valid else 'train/') + prefix, 'study': 'studies/us_preopen_bias',
            'window': [min(x[0] for x in spans), max(x[1] for x in spans)],
            'source': source_note or ('local OpenD, read-only; 34 hot small / mid caps (charged for S20); daily K identical to the '
                                      '5m-derived closes that were cross-checked against Yahoo and Tencent'),
            'universe': universe,
            'files': {'daily/<SYM>.csv': FIELDS['daily/<SYM>.csv'], 'option_stats/<SYM>.csv': FIELDS['option_stats/<SYM>.csv'],
                      'iv/<SYM>.csv': FIELDS['iv/<SYM>.csv'], 'short_volume/<SYM>.csv': FIELDS['short_volume/<SYM>.csv'],
                      'capital_flow/<SYM>.csv': FIELDS['capital_flow/<SYM>.csv'],
                      'ext30/<SYM>.csv': 'pre-market (<= 09:30) and after-hours (> 16:00) 30m K, QFQ, time_key = bar close ET',
                      'daily_none/<SYM>.csv': 'daily K with no price adjustment (actual prices) for the eligibility gate',
                      'market_option.csv': FIELDS['market_option.csv']},
            'rows': rows,
            'note': holdout or ('validation segment 2025-01-02 .. 2026-09-24, evaluate once; load with the select release for warm-up'
                                if valid else 'selection segment, rows before 2025-01-01'),
        }
        (dst / 'manifest.json').write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
        checksums(dst)
        print(dst, sum(rows.values()), 'rows')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--xsec']:
        package_xsec(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:2] == ['--ext30']:
        package_ext30(Path(sys.argv[2]), Path(sys.argv[3]))
    elif sys.argv[1:2] == ['--holdout']:
        package_holdout(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        main()
