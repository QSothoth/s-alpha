"""SV1: one-off validation slice of past same-day-expiry ATM CALL/PUT pairs (notes/SV1_PREREG.md).

Expired chains are no longer listed, so the contract code is built from the strike nearest the
first 1m open on a fixed grid (finest first, then 2x and 4x; retries stay in the same chain).
Charges the option history quota once per (symbol, date) chain; refuses to start more than
--max-chains new chains or to charge any underlying that is not already charged::

    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.fetch_sv1 \
        --dataset data/sv1-session-validation-work --dates 2026-07-24 --symbols US.AAPL --max-chains 1
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from custody.dataset import Dataset, write_bars, write_checksums
from custody.freeze import SELECTION, RateLimiter
from custody.marketdata import normalize_daily_rows
from custody.models import ET
from custody.opend import OpenDMarket, OpenDTradingCalendar

POOL = tuple('US.' + c for c in 'AAPL AMD AMZN AVGO GOOGL INTC META MSFT MU NVDA TSLA'.split())
FINEST = {'US.INTC': 0.5}
# Already-charged liquid stocks outside the pool (SV2 selection comparison).
OUTSIDE = tuple('US.' + c for c in ('APO ARM ASTS BA BAC BB BE BMNR COIN CRWV DELL EOSE F GME HOOD MARA MRNA MRVL '
                                    'MSTR NBIS NFLX NKE NOK NVO ONDS ORCL PCG PFE PLTR RIVN RKLB SNDK SOFI WBD WMT WULF').split())


def strikes_to_try(symbol, reference):
    """Nearest strike on the finest grid, then on 2x and 4x grids (ties go to the lower strike)."""
    out = []
    for mult in (1, 2, 4):
        step = FINEST.get(symbol, 2.5) * mult
        low = (reference // step) * step
        strike = round(min((low, low + step), key=lambda k: (abs(k - reference), k)), 3)
        if strike not in out:
            out.append(strike)
    return out


def option_code(symbol, day, right, strike):
    return '%s%s%s%d' % (symbol, date.fromisoformat(day).strftime('%y%m%d'), right[0], round(strike * 1000))


def _bars(market, code, day):
    try:
        return [b for b in market.history_bars(code, 'K_1M', day, day) if b.close_time.date().isoformat() == day], None
    except RuntimeError as exc:
        return [], str(exc)


def quota_exhausted(error):
    return error is not None and '历史K线额度不足' in error


def fetch_pair(market, limiter, symbol, day, reference):
    attempts = []
    for strike in strikes_to_try(symbol, reference):
        legs = {}
        for right in ('CALL', 'PUT'):
            code = option_code(symbol, day, right, strike)
            limiter.acquire()
            bars, error = _bars(market, code, day)
            attempts.append({'code': code, 'bars': len(bars), 'error': error})
            if quota_exhausted(error):
                return None, None, attempts
            if not bars:
                break
            legs[right] = (code, bars)
        if len(legs) == 2:
            return strike, legs, attempts
    return None, None, attempts


def append_csv(src, target):
    """Append another bounded session without overwriting previously captured dates."""
    with target.open(encoding='utf-8') as existing:
        header = existing.readline()
        seen = set(existing)
    with src.open(encoding='utf-8') as incoming:
        if incoming.readline() != header:
            raise ValueError('incompatible CSV headers')
        with target.open('a', encoding='utf-8') as output:
            for row in incoming:
                if row not in seen:
                    output.write(row)
                    seen.add(row)


def import_cases(source, root, symbols):
    """Copy the named symbols' cases and files from an existing validation dataset."""
    src = Dataset(source)
    picked = [c for c in json.loads((src.root / 'cases.json').read_text(encoding='utf-8'))['cases'] if c['symbol'] in symbols]
    for case in picked:
        for rel in ('underlying/%s.csv' % case['symbol'], 'option/%s.csv' % case['contract']):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            if rel.startswith('underlying/') and (root / rel).exists():
                append_csv(src.root / rel, root / rel)
            else:
                shutil.copyfile(src.root / rel, root / rel)
    return picked, {'dataset': src.name, 'checksums_sha256': src.fingerprint, 'cases': len(picked)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--dates', required=True, help='comma-separated ET session dates')
    parser.add_argument('--symbols', default=','.join(POOL))
    parser.add_argument('--max-chains', required=True, type=int, help='user-approved cap on new option chains this run')
    parser.add_argument('--import-from', type=Path, help='also copy the symbols\' cases from this validation dataset')
    args = parser.parse_args(argv)
    days = [d.strip() for d in args.dates.split(',') if d.strip()]
    symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    root = args.dataset
    root.mkdir(parents=True, exist_ok=True)
    cases_path, manifest_path = root / 'cases.json', root / 'manifest.json'
    cases = json.loads(cases_path.read_text(encoding='utf-8'))['cases'] if cases_path.exists() else []
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {
        'dataset': root.name, 'role': 'validation/custody', 'max_dte': 0, 'schema': 'custody-0dte/1',
        'selection_policy': SELECTION, 'contract_codes': 'constructed from a strike grid (studies/us_0dte_picks/fetch_sv1.py)',
        'preregistration': 'studies/us_0dte_picks/notes/SV1_PREREG.md', 'sessions': [], 'skipped': [], 'runs': []}
    done = {(c['symbol'], c['trade_date']) for c in cases}
    todo = [(s, d) for d in days for s in symbols if (s, d) not in done]
    if len(todo) > args.max_chains:
        raise SystemExit('refuse: %d new chains exceed --max-chains %d' % (len(todo), args.max_chains))
    run = {'started_at': datetime.now(ET).isoformat(), 'argv': argv, 'max_chains': args.max_chains,
           'chains_requested': [], 'pairs': [], 'skipped': []}
    if args.import_from:
        picked, info = import_cases(args.import_from, root, set(symbols))
        known = {(c['contract'], c['trade_date']) for c in cases}
        cases += [c for c in picked if (c['contract'], c['trade_date']) not in known]
        run['imported'] = info
    limiter = RateLimiter(calls=20, window=30.0)
    with OpenDMarket() as market:
        ctx = market.context
        used, remain, detail = ctx.get_history_kl_quota(get_detail=True)[1]
        charged = {row['code'] for row in detail}
        uncharged = sorted({s for s, _ in todo} - charged)
        if uncharged:
            raise SystemExit('refuse: underlyings not yet charged: %s' % uncharged)
        run['quota_before'] = [used, remain]
        calendar = OpenDTradingCalendar(market)
        try:
            for index, (symbol, day) in enumerate(todo):
                session = calendar.session(day)
                expected = int((session.closes - session.opens).total_seconds() // 60)
                limiter.acquire()
                underlying = [b for b in market.history_bars(symbol, 'K_1M', day, day)
                              if session.opens < b.close_time <= session.closes]
                if len(underlying) != expected:
                    run['skipped'].append({'symbol': symbol, 'trade_date': day,
                                           'reason': 'incomplete underlying 1m (%d/%d)' % (len(underlying), expected)})
                    continue
                limiter.acquire()
                start = (date.fromisoformat(day) - timedelta(days=10)).isoformat()
                prior = [r for r in normalize_daily_rows(market.request_kline(symbol, 'K_DAY', start, day)) if r['date'] < day]
                run['chains_requested'].append([symbol, day])
                strike, legs, attempts = fetch_pair(market, limiter, symbol, day, underlying[0].open)
                run['pairs'].append({'symbol': symbol, 'trade_date': day, 'reference_open': underlying[0].open,
                                     'strike': strike, 'attempts': attempts})
                if legs is None:
                    run['skipped'].append({'symbol': symbol, 'trade_date': day, 'reason': 'no CALL+PUT pair on the tried strikes'})
                    print('skip', symbol, day, [a['code'] for a in attempts], flush=True)
                    if any(quota_exhausted(a['error']) for a in attempts):
                        run['stop_reason'] = 'option_history_quota_exhausted'
                        run['deferred'] = [{'symbol': s, 'trade_date': d} for s, d in todo[index + 1:]]
                        break
                    continue
                write_bars(root / 'underlying' / (symbol + '.csv'), underlying)
                codes = {right: code for right, (code, _) in legs.items()}
                for right, (code, bars) in legs.items():
                    write_bars(root / 'option' / (code + '.csv'), bars)
                    cases.append({'symbol': symbol, 'contract': code, 'trade_date': day, 'expiry': day, 'right': right,
                                  'direction': 'LONG' if right == 'CALL' else 'SHORT', 'strike': strike,
                                  'reference_open': underlying[0].open, 'prev_close': prior[-1]['close'] if prior else None,
                                  'session_close': session.closes.isoformat(), 'selection': SELECTION,
                                  'call_contract': codes['CALL'], 'put_contract': codes['PUT']})
                print('ok', symbol, day, strike, {r: len(b) for r, (_, b) in legs.items()}, flush=True)
        finally:
            run['quota_after'] = list(ctx.get_history_kl_quota()[1][:2])
            run['finished_at'] = datetime.now(ET).isoformat()
            cases.sort(key=lambda c: (c['trade_date'], c['symbol'], c['contract']))
            manifest['sessions'] = sorted({c['trade_date'] for c in cases})
            manifest['skipped'] = manifest.get('skipped', []) + run['skipped']
            manifest['runs'] = manifest.get('runs', []) + [run]
            manifest['case_count'] = len(cases)
            cases_path.write_text(json.dumps({'cases': cases}, indent=2) + '\n', encoding='utf-8')
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            write_checksums(root)
    if cases:
        Dataset(root)
    print(json.dumps({k: run.get(k) for k in ('quota_before', 'quota_after')}
                     | {'chains': len(run['chains_requested']), 'pairs_ok': len(run['chains_requested']) - len(run['skipped']),
                        'stop_reason': run.get('stop_reason'), 'deferred_chains': len(run.get('deferred', []))}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
