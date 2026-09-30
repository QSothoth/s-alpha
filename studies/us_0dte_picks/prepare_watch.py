"""Prepare one bounded nearest-expiry watch session from real OpenD inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from math import isfinite
from pathlib import Path
from statistics import mean
import time

from custody.models import ET
from custody.opend import OpenDMarket, _futu
from . import daily_list, daily_k, p3
from .live_watch import validate_inputs

CODES = ['US.' + code for code in 'AAPL AMD AMZN AVGO GOOGL INTC META MSFT MU NVDA TSLA'.split()]


def nearest_expiry(rows, day):
    dates = sorted({str(row['strike_time'])[:10] for row in rows})
    return next((value for value in dates if value >= day), None)


def opening_baseline(raw15, raw30, day, calendar):
    base = daily_list.premarket_record(raw30, day, calendar)
    sessions = {}
    for row in raw15:
        stamp = str(row['time_key'])
        if stamp[:10] < day:
            sessions.setdefault(stamp[:10], []).append(row)
    grid = [(datetime.fromisoformat(day + 'T09:30') + timedelta(minutes=i)).strftime('%H:%M:%S')
            for i in range(15, 391, 15)]
    complete = {d: sorted(rows, key=lambda r: r['time_key']) for d, rows in sessions.items()
                if sorted(str(r['time_key'])[11:19] for r in rows) == grid
                and all(isfinite(float(r['volume'])) and float(r['volume']) >= 0 for r in rows)}
    dates = base['rvol30_days']
    if not all(d in complete for d in dates):
        raise ValueError('14 matching complete native 15m sessions required')
    volumes = [float(complete[d][0]['volume']) for d in dates]
    if mean(volumes) <= 0:
        raise ValueError('zero 15m volume baseline')
    return {**base, 'rvol15_base': mean(volumes), 'rvol15_days': dates,
            'opening15_volumes': volumes,
            'native15_vs_native30_max_opening_volume_diff': max(
                abs(sum(float(r['volume']) for r in complete[d][:2]) - volume)
                for d, volume in zip(dates, base['opening_volumes']))}


def rank_record(code, raw30, snap, aux, day):
    sessions = daily_list.complete_sessions(raw30, day)
    days = sorted(sessions)
    bars = {d: p3.daily_bar(v) for d, v in sessions.items()}
    prev = bars[days[-1]]
    atr = mean(max(bars[d][1], bars[days[i-1]][3]) - min(bars[d][2], bars[days[i-1]][3])
               for i, d in list(enumerate(days))[-20:])
    price = float(snap.get('pre_price') or 0)
    if not isfinite(price) or price <= 0 or atr <= 0:
        raise ValueError('valid premarket price and ATR required: ' + code)
    gap = price / prev[3] - 1
    thrust = p3.thrust_side(bars, days + [day], len(days))
    tier = 2 if aux['earnings_reaction'] else 1 if thrust else 0
    return {**aux, 'code': code, 'name': snap.get('name'), 'close_t1': prev[3],
            'pre_price': price, 'pre_gap': gap, 'snapshot_update_time': snap.get('update_time'),
            'atr20': atr, 'atr20_fraction': atr/prev[3], 'gap_atr': abs(gap)/(atr/prev[3]),
            'hv_iv': aux['hv']/aux['iv'], 'thrust': thrust, 'event_tier': tier,
            'score': abs(gap)/(atr/prev[3]) + aux['hv']/aux['iv'],
            'direction': 1 if gap > 0 else -1 if gap < 0 else 0}


def prepare(out):
    now = datetime.now(ET)
    day = now.date().isoformat()
    if now.hour*60 + now.minute >= 570:
        raise ValueError('prepare before 09:30 ET; never rebuild frozen inputs intraday')
    out.mkdir(parents=True, exist_ok=False)

    def save(name, data):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str)+'\n')

    method = {'trade_date': day, 'started_at': now.isoformat(), 'initial_pool': CODES,
              'role': 'HUMAN_REVIEW_HEURISTIC_NOT_VALIDATED', 'expiry_policy': 'nearest',
              'sort': ['earnings reaction today, previous-day thrust, other',
                       'descending abs(premarket_gap)/ATR20_fraction + HV/IV',
                       'descending previous-day option volume', 'code'],
              'baselines': '14 matching complete RTH sessions; native 15m and 30m',
              'history': '1000 subscribed bars per symbol/period, no historical-kline quota',
              'budget_usd': 300, 'fee_reserve_usd': 20,
              'pool_scope': '11 named liquid technology stocks; not whole-market or biotech coverage'}
    save('method.json', method)
    (out/'prepare_source.py').write_text(Path(__file__).read_text())
    log, client = [], None
    try:
        with OpenDMarket() as market:
            ft = _futu()
            client = daily_list.Client(market.context, ft)

            def get(endpoint, name, *args, **kwargs):
                requested = datetime.now(ET).isoformat()
                result = client.call(endpoint, *args, **kwargs)[1]
                data = daily_list.records(result) if hasattr(result, 'to_dict') else result
                save(name, data)
                log.append({'endpoint': endpoint, 'args': args, 'kwargs': kwargs,
                            'requested_at': requested, 'returned_at': datetime.now(ET).isoformat()})
                return data

            calendar_rows = get('request_trading_days', 'calendar.json', market='US',
                                start=(now.date()-timedelta(days=120)).isoformat(), end=day)
            calendar = sorted(str(r['time'])[:10] for r in calendar_rows)
            if not any(r['time'] == day and r.get('trade_date_type') == 'WHOLE' for r in calendar_rows):
                raise ValueError('full US trading day required')
            previous = calendar[calendar.index(day)-1]
            eligible, aux, excluded = [], {}, {}
            for code in CODES:
                ticker = code[3:]
                expiry = nearest_expiry(get('get_option_expiration_date', f'expiry/{ticker}.json', code), day)
                if expiry is None:
                    excluded[code] = 'no unexpired option expiry'
                    continue
                time.sleep(3.1)
                chain = get('get_option_chain', f'chains/{ticker}.json', code, start=expiry, end=expiry)
                standard = [r for r in chain if str(r.get('strike_time', ''))[:10] == expiry
                            and r.get('option_standard_type') == 'STANDARD' and not r.get('suspension')]
                if not all(any(r.get('option_type') == right for r in standard) for right in ('CALL', 'PUT')):
                    excluded[code] = 'nearest expiry has no standard call/put pair'
                    continue
                vols = get('get_option_underlying_his_volatility', f'volatility/{ticker}.json', code,
                           begin_time=(now.date()-timedelta(days=7)).isoformat(), end_time=previous)
                valid = [r for r in vols if str(r['time'])[:10] < day and
                         all(r.get(k) not in (None, '', 'N/A') and isfinite(float(r[k])) and float(r[k]) > 0
                             for k in ('iv', 'hv'))]
                if not valid:
                    raise ValueError('no recent IV/HV: ' + code)
                vol = max(valid, key=lambda r: str(r['time']))
                stats = get('get_option_underlying_his_statistic', f'option_stats/{ticker}.json', code,
                            begin_time=previous, end_time=previous)
                get('get_financials_earnings_price_move', f'earnings/{ticker}.json', code, period_count=2)
                aux[code] = {'expiry': expiry, 'expiry_policy': 'nearest',
                             'iv': float(vol['iv']), 'hv': float(vol['hv']), 'volatility_date': str(vol['time'])[:10],
                             'option_volume': daily_list.latest_before(stats, 'option_volume', day),
                             'earnings_reaction': day in daily_k.reaction_days(ticker, calendar, out)}
                eligible.append(code)
            save('excluded.json', excluded)
            if not eligible:
                raise ValueError('no eligible candidates')
            quota = get('query_subscription', 'subscription_before.json', is_all_conn=True)
            if quota['remain'] < len(eligible):
                raise ValueError('insufficient subscription quota')
            bases = {}
            # Keep one symbol's raw bars at a time; persisted files are the source of truth.
            for subtype, folder in [(ft.SubType.K_30M, 'k30'), (ft.SubType.K_15M, 'k15')]:
                def fetch(code):
                    rows = get('get_cur_kline', f'{folder}/{code[3:]}.json', code, 1000, subtype, ft.AuType.QFQ)
                    if folder == 'k15':
                        raw30 = json.loads((out/f'k30/{code[3:]}.json').read_text())
                        bases[code] = opening_baseline(rows, raw30, day, calendar)
                    return True
                fetched = client.subscribed(eligible, subtype, fetch, session=ft.Session.RTH)
                failures = {code: str(value) for code, value in fetched.items() if isinstance(value, Exception)}
                if failures:
                    raise ValueError('incomplete frozen inputs: ' + json.dumps(failures))
            snapshots = get('get_market_snapshot', 'stock_snapshot.json', eligible)
            by_code = {row['code']: row for row in snapshots}
            rows = [rank_record(code, json.loads((out/f'k30/{code[3:]}.json').read_text()),
                                by_code[code], aux[code], day) for code in eligible]
            rows.sort(key=lambda r: (-r['event_tier'], -r['score'], -(r['option_volume'] or 0), r['code']))
            for rank, row in enumerate(rows, 1):
                row['rank'] = rank
            ranking = {'trade_date': day, 'previous': previous, 'method': method, 'top10': rows,
                       'completed_at': datetime.now(ET).isoformat()}
            validate_inputs(ranking, bases, day, calendar)
            save('baselines.json', bases)
            save('ranking.json', ranking)
            get('query_subscription', 'subscription_after.json', is_all_conn=True)
    finally:
        save('requests.json', {'requests': log, 'client_attempts': client.log if client else []})
        with (out/'CHECKSUMS.sha256').open('w') as manifest:
            for path in sorted(out.rglob('*')):
                if path.is_file() and path.name != 'CHECKSUMS.sha256':
                    manifest.write(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+str(path.relative_to(out))+'\n')
    return ranking


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--launch', action='store_true', help='also check and launch the bounded read-only monitor')
    parser.add_argument('--until', default='10:45')
    args = parser.parse_args(argv)
    ranking = prepare(args.out)
    print(json.dumps({'out': str(args.out), 'trade_date': ranking['trade_date'],
                      'candidates': [{k: r[k] for k in ('code', 'rank', 'expiry')} for r in ranking['top10']]}, indent=2))
    if args.launch:
        from .launch_watch import main as launch
        command = ['--candidates', str(args.out/'ranking.json'), '--baselines', str(args.out/'baselines.json'),
                   '--out', str(args.out/'monitor'), '--until', args.until, '--budget-usd', '300', '--fee-reserve-usd', '20']
        launch(command + ['--check-only'])
        launch(command)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
