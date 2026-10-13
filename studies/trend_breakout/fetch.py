"""Build the trend-breakout daily-bar dataset from the shared market sources (see sources.py).

    <out>/<market>/universe.json      source, filters, snapshot time, codes and names
    <out>/<market>/bars_raw.csv.gz    code,date,open,high,low,close,volume,turnover (unadjusted)
    <out>/<market>/bars_qfq.csv.gz    same columns, the source's own forward adjustment (audit only)
    <out>/<market>/actions.csv.gz     code,ex_date,factor_a,factor_b (price before -> a * price + b)
    <out>/<market>/progress.json      finished codes and failures; a rerun resumes from it

Run from the repository root, one market at a time (US / HK need /opt/futu-opend/venv/bin/python):

    PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.fetch us --out data/trend-breakout-v1
    PYTHONUTF8=1 python3 -m studies.trend_breakout.fetch cn --out data/trend-breakout-v1
    PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.fetch hk --actions-only --out ...
    python3 -m studies.trend_breakout.fetch checksums --out data/trend-breakout-v1

``--shares-only`` (A-shares) writes shares.csv.gz with Sina's total-share history for point-in-time market caps;
``--band MIN MAX`` builds an A-share universe of MIN <= market cap < MAX instead of the default >= 10bn.
``--history-from F1 F2 --start --end`` fetches older A-share bars from Tencent for the codes of those folders;
``--actions-only`` backfills actions.csv.gz for codes whose bars were fetched before it existed
(add ``--redo-actions`` to rebuild it).
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path

from . import sources

START, END = '2023-09-01', '2026-10-09'  # warmup + train + test, see notes/SPLITS.md


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def write_json(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    tmp.replace(path)


def append_rows(path, rows):
    with gzip.open(path, 'at', encoding='utf-8', newline='') as f:
        csv.writer(f).writerows(rows)


def prepare(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for name, header in (('bars_qfq.csv.gz', sources.COLUMNS), ('bars_raw.csv.gz', sources.COLUMNS),
                         ('actions.csv.gz', sources.ACTION_COLUMNS)):
        if not (folder / name).exists():
            append_rows(folder / name, [header])
    path = folder / 'progress.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'done': [], 'failed': {}}


def fetch(out, market, start, end, band=None):
    """``band`` = (min, max) market cap in CNY for an A-share universe other than the default (>= 10bn)."""
    folder = out / market
    progress = prepare(folder)
    src = sources.get(market)
    try:
        if not (folder / 'universe.json').exists():
            stocks = src.universe(*band) if band else src.universe()
            desc = {**src.describe(), **({'band_mktcap_cny': list(band)} if band else {})}
            write_json(folder / 'universe.json', {'market': market, **desc, 'snapshot_utc': now(),
                                                  'window': [start, end], 'stocks': stocks})
        stocks = json.loads((folder / 'universe.json').read_text(encoding='utf-8'))['stocks']
        done = set(progress['done'])
        todo = [s['code'] for s in stocks if s['code'] not in done]
        for n, (code, raw, qfq) in enumerate(src.bars(todo, start, end), 1):
            if not raw or not qfq or [r[1] for r in raw] != [r[1] for r in qfq]:
                progress['failed'][code] = 'empty or mismatched raw/qfq dates'
            else:
                try:
                    actions = src.actions(code, raw, qfq)
                except Exception as exc:
                    progress['failed'][code] = f'actions: {exc!r}'[:200]
                    write_json(folder / 'progress.json', progress)
                    continue
                append_rows(folder / 'bars_raw.csv.gz', raw)
                append_rows(folder / 'bars_qfq.csv.gz', qfq)
                append_rows(folder / 'actions.csv.gz', actions)
                progress['done'].append(code)
                progress['actions_done'] = progress.get('actions_done', []) + [code]
                progress['failed'].pop(code, None)
            write_json(folder / 'progress.json', progress)  # every code, so a kill never leaves unrecorded rows
            if n % 50 == 0 or n == len(todo):
                print(f'{market} {len(progress["done"])}/{len(stocks)} failed {len(progress["failed"])}', flush=True)
        if hasattr(src, 'history_quota'):
            progress['history_quota_after'] = src.history_quota()
        progress['finished_utc'] = now()
        write_json(folder / 'progress.json', progress)
    finally:
        src.close()
    return progress


def shares_have(folder):
    """Codes already written to any shares*.csv.gz of the folder (the files are the record of what is done)."""
    import glob
    have = set()
    for path in glob.glob(str(folder / 'shares*.csv.gz')):
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as f:
            have |= {row[0] for row in csv.reader(f) if row and row[0] != 'code'}
    return have


def fetch_shares(out, market='cn', part=None):
    """shares*.csv.gz: code,date,total_shares for every fetched A-share code (Sina history; resumable).
    ``part`` = (k, n) fetches every n-th remaining code into its own shares_part{k}.csv.gz, so n workers can
    run side by side without sharing a file."""
    folder = out / market
    progress = prepare(folder)
    path = folder / ('shares.csv.gz' if part is None else f'shares_part{part[0]}.csv.gz')
    if not path.exists():
        append_rows(path, [('code', 'date', 'total_shares')])
    have = set(progress.get('shares_done', [])) | shares_have(folder)
    todo = [c for c in progress['done'] if c not in have]
    if part is not None:
        todo = todo[part[0]::part[1]]
        progress = {'done': progress['done'], 'failed': {}}  # a worker never rewrites progress.json
    src = sources.get(market)
    for n, code in enumerate(todo, 1):
        try:
            rows = src.share_history(code)
        except Exception as exc:
            progress.setdefault('shares_failed', {})[code] = repr(exc)[:200]
            if part is None:
                write_json(folder / 'progress.json', progress)
            else:
                print(f'shares failed {code}: {exc!r}'[:200], flush=True)
            continue
        append_rows(path, [(code, d, s) for d, s in rows] or [(code, '', '')])  # empty history still marks done
        if part is None:
            progress['shares_done'] = progress.get('shares_done', []) + [code]
            progress.get('shares_failed', {}).pop(code, None)
            write_json(folder / 'progress.json', progress)
        if n % 100 == 0 or n == len(todo):
            print(f'{market} shares {n}/{len(todo)}', flush=True)
    return progress


def fetch_history(out, from_folders, start, end, part=None):
    """A-share history before the dataset window (Tencent static files + Sina), for every code of
    ``from_folders`` (cn only): <out>/cn/universe.json (union) + bars_raw*.csv.gz; actions and shares stay in the
    source folders. ``part`` = (k, n): worker k of n takes every n-th remaining code and writes its own
    bars_raw_part{k}.csv.gz / progress_part{k}.json, so workers never share a file."""
    folder = out / 'cn'
    progress = prepare(folder)
    if part is not None:
        import glob
        done_all = set(progress['done'])
        for path in glob.glob(str(folder / 'progress_part*.json')):
            done_all |= set(json.loads(Path(path).read_text(encoding='utf-8'))['done'])
        mine = folder / f'progress_part{part[0]}.json'
        own = json.loads(mine.read_text(encoding='utf-8')) if mine.exists() else {'done': [], 'failed': {}}
    if not (folder / 'universe.json').exists():
        stocks = {}
        for src_folder in from_folders:
            for s in json.loads((Path(src_folder) / 'cn' / 'universe.json').read_text(encoding='utf-8'))['stocks']:
                stocks.setdefault(s['code'], s)
        write_json(folder / 'universe.json', {'market': 'cn', 'source': 'Tencent fqkline day (unadjusted)',
                                              'from': [str(x) for x in from_folders], 'snapshot_utc': now(),
                                              'window': [start, end], 'stocks': list(stocks.values())})
    stocks = json.loads((folder / 'universe.json').read_text(encoding='utf-8'))['stocks']
    src = sources.get('cn')
    if part is None:
        bars, prog_path, todo = folder / 'bars_raw.csv.gz', folder / 'progress.json', \
            [s['code'] for s in stocks if s['code'] not in set(progress['done'])]
    else:
        bars, prog_path = folder / f'bars_raw_part{part[0]}.csv.gz', mine
        if not bars.exists():
            append_rows(bars, [sources.COLUMNS])
        todo = [s['code'] for s in stocks if s['code'] not in done_all][part[0]::part[1]]
        progress = own
    for n, code in enumerate(todo, 1):
        try:
            rows = src.history_tencent(code, start, end)
        except Exception as exc:
            progress['failed'][code] = repr(exc)[:200]
            write_json(prog_path, progress)
            continue
        append_rows(bars, rows)
        progress['done'].append(code)
        progress['failed'].pop(code, None)
        write_json(prog_path, progress)
        if n % 100 == 0 or n == len(todo):
            print(f'history {len(progress["done"])}/{len(stocks)} failed {len(progress["failed"])}', flush=True)
    progress['finished_utc'] = now()
    write_json(prog_path, progress)
    return progress


def backfill_actions(out, market, redo=False, part=None):
    """Write actions for fetched codes that do not have them yet; ``redo`` rebuilds the whole file.
    ``part`` = (k, n): worker k of n writes actions_part{k}.csv.gz for every n-th code with no actions yet."""
    folder = out / market
    progress = prepare(folder)
    if part is not None:
        import glob
        have = set()
        for path in glob.glob(str(folder / 'actions*.csv.gz')) + glob.glob(str(folder / 'actions_done_part*.json')):
            if path.endswith('.json'):
                have |= set(json.loads(Path(path).read_text(encoding='utf-8')))
        todo = [c for c in progress['done'] if c not in have][part[0]::part[1]]
        path, mark = folder / f'actions_part{part[0]}.csv.gz', folder / f'actions_done_part{part[0]}.json'
        done = json.loads(mark.read_text(encoding='utf-8')) if mark.exists() else []
        todo = [c for c in todo if c not in set(done)]
        if not path.exists():
            append_rows(path, [sources.ACTION_COLUMNS])
        src = sources.get(market)
        for n, code in enumerate(todo, 1):
            try:
                append_rows(path, src.actions(code))
            except Exception as exc:
                print(f'actions failed {code}: {exc!r}'[:200], flush=True)
                continue
            done.append(code)
            write_json(mark, done)
            if n % 100 == 0 or n == len(todo):
                print(f'{market} actions part {part[0]}: {n}/{len(todo)}', flush=True)
        return progress
    if redo:
        (folder / 'actions.csv.gz').unlink()
        append_rows(folder / 'actions.csv.gz', [sources.ACTION_COLUMNS])
        progress['actions_done'] = []
    have = set(progress.get('actions_done', []))
    todo = [c for c in progress['done'] if c not in have]
    src = sources.get(market)
    try:
        for n, code in enumerate(todo, 1):
            append_rows(folder / 'actions.csv.gz', src.actions(code))
            progress['actions_done'] = progress.get('actions_done', []) + [code]
            write_json(folder / 'progress.json', progress)
            if n % 50 == 0 or n == len(todo):
                print(f'{market} actions {n}/{len(todo)}', flush=True)
    finally:
        src.close()
    return progress


def checksums(out):
    lines = [f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}'
             for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'CHECKSUMS.sha256']
    (out / 'CHECKSUMS.sha256').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('market', choices=('us', 'hk', 'cn', 'checksums'))
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--start', default=START)
    parser.add_argument('--end', default=END)
    parser.add_argument('--actions-only', action='store_true')
    parser.add_argument('--redo-actions', action='store_true', help='with --actions-only: rebuild the file')
    parser.add_argument('--history-from', nargs='+', type=Path, metavar='FOLDER',
                        help='cn: fetch Tencent history (--start/--end) for the codes of these dataset folders')
    parser.add_argument('--shares-only', action='store_true', help='cn: fetch total-share history (shares.csv.gz)')
    parser.add_argument('--part', nargs=2, type=int, metavar=('K', 'N'),
                        help='with --shares-only, --actions-only or --history-from: worker K of N')
    parser.add_argument('--band', nargs=2, type=float, metavar=('MIN', 'MAX'),
                        help='cn universe by market cap in CNY, MIN <= cap < MAX (default: >= 10bn)')
    args = parser.parse_args(argv)
    if args.market == 'checksums':
        print('\n'.join(checksums(args.out)))
        return
    if args.history_from:
        result = fetch_history(args.out, args.history_from, args.start, args.end, tuple(args.part) if args.part else None)
    elif args.shares_only:
        result = fetch_shares(args.out, args.market, tuple(args.part) if args.part else None)
    elif args.actions_only:
        result = backfill_actions(args.out, args.market, args.redo_actions, tuple(args.part) if args.part else None)
    else:
        result = fetch(args.out, args.market, args.start, args.end, args.band)
    print(json.dumps({'done': len(result['done']), 'failed': result['failed']}, ensure_ascii=False)[:2000], flush=True)
    os._exit(0)  # the futu client can keep a thread alive after close


if __name__ == '__main__':
    main()
