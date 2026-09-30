"""Bounded read-only candidate monitor; emits review drafts, never broker orders.

Inputs are today's premarket ranking and frozen 14-session opening-volume baselines.
The relative ranking is a human-review heuristic, not a validated directional strategy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
import math
from pathlib import Path
import time

from custody.marketdata import _et, _num, normalize_bar_rows
from custody.models import ET, Session
from custody.opend import OpenDMarket, OpenDContractResolver, _futu, _records
from custody.registry import Registry
from custody.strategy import build_strategy

REFERENCES = {'US.SPY': 'broad_market', 'US.QQQ': 'nasdaq100',
              'US.SMH': 'semiconductors', 'US.XBI': 'biotech'}


def reference_summary(raw, code, session, boundary):
    bars = [b for b in normalize_bar_rows(raw, code, boundary=boundary)
            if session.opens < b.close_time <= boundary]
    count = int((boundary-session.opens).total_seconds()/60)
    if [b.close_time for b in bars] != [session.opens+timedelta(minutes=i) for i in range(1,count+1)]:
        raise ValueError('incomplete reference 1m bars')
    total = sum(b.volume for b in bars)
    if not bars or total <= 0:
        raise ValueError('empty reference volume')
    vwap = sum((b.high+b.low+b.close)/3*b.volume for b in bars)/total
    return {'code': code, 'role': REFERENCES[code], 'open': bars[0].open, 'close': bars[-1].close,
            'open_move_pct': 100*(bars[-1].close/bars[0].open-1),
            'vwap': vwap, 'above_vwap': bars[-1].close > vwap}


def write_json_atomic(path, value):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text)
    temporary.replace(path)


def summarize(rows, source, session, boundary, volume=None, volume_base=None, volume_minutes=None):
    """Use only contiguous, completed same-session bars; never silently fill a gap."""
    bars = [b for b in normalize_bar_rows(rows, source['code'], boundary=boundary)
            if session.opens < b.close_time <= boundary]
    minutes = int((boundary-session.opens).total_seconds()/60)
    expected = [session.opens+timedelta(minutes=i) for i in range(1, minutes+1)]
    if not bars or [b.close_time for b in bars] != expected:
        raise ValueError('incomplete same-day 1m bars')
    total = sum(b.volume for b in bars)
    if total <= 0:
        raise ValueError('zero opening volume')
    op, close = bars[0].open, bars[-1].close
    high, low = max(b.high for b in bars), min(b.low for b in bars)
    vwap = sum((b.high+b.low+b.close)/3*b.volume for b in bars)/total
    change = close/op-1
    sigma = source['iv']/100/math.sqrt(252)*math.sqrt((390-minutes)/390)
    if sigma <= 0:
        raise ValueError('invalid remaining-session IV scale')
    direction = 'LONG' if change > 0 else 'SHORT' if change < 0 else 'FLAT'
    return {
        'code':source['code'], 'rank_pre':source['rank'], 'open':op, 'close':close,
        'expiry':source.get('expiry', session.day),
        'expiry_policy':source.get('expiry_policy', '0_1dte'),
        'open_move_pct':change*100, 'change_t1_pct':100*(close/source['close_t1']-1),
        'direction':direction, 'vwap':vwap, 'high':high, 'low':low,
        'same_vwap_side':(close-vwap)*change>0,
        'range_location':(close-low)/(high-low) if high>low else .5,
        'strength_sigma':abs(change)/sigma,
        'rvol':volume/volume_base if volume is not None and volume_base else None,
        'rvol_minutes':volume_minutes,
    }, bars


def option_check(row, direction, day, now, premium_cap, expiry=None):
    """Inspect real contract sizing, freshness, liquidity and full entry premium."""
    reason=[]
    bid,ask,delta=(_num(row.get(k)) for k in ('bid_price','ask_price','option_delta'))
    stamp=_et(row.get('update_time'))
    right='CALL' if direction=='LONG' else 'PUT'
    if direction=='FLAT' or row.get('option_type')!=right:
        reason.append('direction')
    expiry = expiry or day
    if expiry < day or str(row.get('strike_time',''))[:10]!=expiry or row.get('option_valid') is not True:
        reason.append('expiry_or_validity')
    if row.get('sec_status') not in ('NORMAL',''):
        reason.append('security_status')
    if _num(row.get('option_contract_multiplier'))!=100:
        reason.append('nonstandard_multiplier')
    if stamp is None or not 0 <= (now-stamp).total_seconds() <= 30:
        reason.append('stale_quote')
    if bid is None or ask is None or not 0<bid<=ask:
        reason.append('invalid_bid_ask')
    elif (ask-bid)/ask>.10:
        reason.append('wide_spread')
    if delta is None or abs(delta)<.30:
        reason.append('delta_below_0.30')
    if (_num(row.get('volume')) or 0)<100:
        reason.append('option_volume_below_100')
    premium=Decimal(str(ask))*100 if ask is not None and ask>0 else None
    if premium is None or premium>Decimal(str(premium_cap)):
        reason.append('entry_premium_limit')
    return {'contract':row.get('code'),'expiry':expiry,'strike':_num(row.get('option_strike_price')),
            'bid':bid,'ask':ask,'delta':delta,'volume':row.get('volume'),
            'quoted_at':row.get('update_time'),'entry_premium':float(premium) if premium else None,
            'rejections':reason}


def choose_drafts(ranked, quotes, day, now, premium_budget):
    """Choose the relative best affordable name first; at most one extra distinct name.

    A single draft gets the full premium cap. Two drafts each get half, so their
    persisted per-job caps cannot exceed the caller's premium allocation in total.
    """
    eligible=[]
    for row in ranked:
        inspected=[option_check(q,row['direction'],day,now,premium_budget,row.get('expiry'))
                   for q in quotes.get(row['code'],[])]
        row['contracts_checked']=inspected
        good=[c for c in inspected if not c['rejections'] and c['strike'] is not None]
        if good:
            contract=min(good,key=lambda c:(abs(c['strike']-row['close']),c['ask'],c['contract']))
            eligible.append({'symbol':row['code'],'direction':row['direction'],
                             'expiry_policy':row.get('expiry_policy','0_1dte'),**contract})
    if not eligible:
        return []
    chosen=[eligible[0]]
    half=float(Decimal(str(premium_budget))/2)
    if chosen[0]['entry_premium']<=half:
        second=next((r for r in eligible[1:] if r['entry_premium']<=half),None)
        if second:
            chosen.append(second)
    cap=half if len(chosen)==2 else premium_budget
    return [{**row,'strategy_id':'open_hold_v3','max_qty':1,'max_entry_premium':cap,
             'trade_date':day,'role':'HUMAN_REVIEW_DRAFT'} for row in chosen]


def annotate_timing(ranked, bars_by_code, strategy, session):
    """Expose every inspected contract's timing, including unselected candidates.

    Replay uses the current candidate direction and never invents a fill. An old
    latched ENTER is explicitly different from a first entry on the latest bar;
    today's quote checks cannot establish eligibility at that earlier time.
    """
    timings, signals = {}, []
    for row in ranked:
        if row['direction'] not in ('LONG', 'SHORT'):
            continue
        bars = bars_by_code[row['code']]
        for contract in row.get('contracts_checked', []):
            strike = contract['strike']
            if strike is None or not math.isfinite(strike) or strike <= 0:
                continue
            engine = build_strategy(strategy, row['direction'], session, strike)
            first = None
            for bar in bars:
                decision = engine.on_bar(bar)
                if decision.action == 'ENTER' and first is None:
                    first = bar.close_time
            status = ('NO_ENTRY_YET' if first is None else
                      'FIRST_ENTRY_THIS_MINUTE' if first == bars[-1].close_time else
                      'EARLIER_ENTRY_UNFILLED')
            timing = {'engine_action': decision.action, 'engine_reason': decision.reason,
                      'first_enter_at': first.isoformat() if first else None,
                      'signal_status': status, 'diagnostics': decision.diagnostics,
                      'historical_quote_eligibility': 'NOT_RECONSTRUCTED'}
            contract['timing'] = timing
            timings[contract['contract']] = timing
            if first is not None:
                signals.append({'symbol': row['code'], 'direction': row['direction'],
                                'contract': contract['contract'], **timing,
                                'quote_eligible_now': not contract['rejections'],
                                'quote_rejections_now': contract['rejections']})
    return timings, signals


def build_review_card(ranked, signals, day, boundary, premium_budget):
    """Return only newly actionable, currently eligible contracts for human review."""
    fresh = {s['contract']: s for s in signals
             if s['signal_status'] == 'FIRST_ENTRY_THIS_MINUTE' and s['quote_eligible_now']}
    eligible = []
    for row in ranked:
        contracts = [c for c in row.get('contracts_checked', [])
                     if c['contract'] in fresh and not c['rejections'] and c['strike'] is not None]
        if contracts:
            contract = min(contracts, key=lambda c: (
                abs(c['strike'] - row['close']), c['ask'], c['contract']))
            eligible.append({'symbol': row['code'], 'direction': row['direction'], **contract,
                             'expiry_policy': row.get('expiry_policy', '0_1dte'),
                             'signal': fresh[contract['contract']]})
    chosen = eligible[:1]
    half = float(Decimal(str(premium_budget)) / 2)
    if chosen and chosen[0]['entry_premium'] <= half:
        second = next((item for item in eligible[1:] if item['entry_premium'] <= half), None)
        if second:
            chosen.append(second)
    cap = half if len(chosen) == 2 else premium_budget
    actions = []
    for item in chosen:
        actions.append({
            **item, 'strategy_id': 'open_hold_v3', 'trade_date': day,
            'max_qty': 1, 'max_entry_premium': cap,
            'custody_request': {
                'strategy': 'open_hold_v3', 'symbol': item['symbol'],
                'direction': item['direction'], 'contract': item['contract'],
                'max_qty': 1, 'max_entry_premium': cap,
                'expiry_policy': item['expiry_policy'],
            },
        })
    return {
        'as_of': boundary.isoformat(),
        'valid_until': (boundary + timedelta(minutes=1)).isoformat(),
        'status': 'ENTER_REVIEW' if actions else 'WAIT',
        'fresh_signal_required': True,
        'orders_submitted': False,
        'trade_date': day,
        'premium_budget': premium_budget,
        'actions': actions,
    }


def validate_inputs(ranking, bases, day, calendar, required_periods=(15,30)):
    if ranking.get('trade_date')!=day:
        raise ValueError('candidate file must be for today')
    rows=ranking.get('top10',[])
    if not 1<=len(rows)<=20 or len({r['code'] for r in rows})!=len(rows):
        raise ValueError('need 1-20 distinct candidates')
    previous=calendar[calendar.index(day)-1]
    recent=set(calendar[max(0,calendar.index(day)-20):calendar.index(day)])
    for row in rows:
        if row.get('expiry_policy') == 'nearest':
            if datetime.fromisoformat(row['expiry']).date().isoformat() != row['expiry'] or row['expiry'] < day:
                raise ValueError('invalid candidate expiry')
        base=bases[row['code']]
        if not row['code'].startswith('US.') or (_num(row.get('iv')) or 0)<=0:
            raise ValueError('invalid candidate')
        age=(datetime.fromisoformat(day)-datetime.fromisoformat(row['volatility_date'])).days
        if not 1<=age<=7:
            raise ValueError('stale IV')
        for minutes in required_periods:
            dates=base[f'rvol{minutes}_days']
            if len(dates)!=14 or dates!=sorted(set(dates)) or dates[-1]!=previous or not set(dates)<=recent:
                raise ValueError('invalid frozen opening-volume dates')
            if (_num(base.get(f'rvol{minutes}_base')) or 0)<=0:
                raise ValueError('invalid frozen opening-volume mean')
    return rows


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidates',type=Path,required=True)
    parser.add_argument('--baselines',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--until',default='10:05',help='ET cutoff; the process is finite')
    parser.add_argument('--budget-usd',type=float,default=300)
    parser.add_argument('--fee-reserve-usd',type=float,default=20)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args(argv)
    if not math.isfinite(args.budget_usd) or not math.isfinite(args.fee_reserve_usd) or not 0<=args.fee_reserve_usd<args.budget_usd:
        parser.error('budget must exceed a nonnegative fee reserve')
    started=datetime.now(ET)
    day=started.date().isoformat()
    cutoff=datetime.fromisoformat(day+'T'+args.until).replace(tzinfo=ET)
    if not started<cutoff<=started.replace(hour=15,minute=45,second=0,microsecond=0):
        parser.error('cutoff must be later today and no later than 15:45 ET')
    ranking=json.loads(args.candidates.read_text())
    bases=json.loads(args.baselines.read_text())
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'inputs').mkdir()
    source_root = Path(__file__).resolve().parents[2]
    for relative in ('studies/us_0dte_picks/live_watch.py', 'custody/strategy.py',
                     'custody/marketdata.py', 'custody/models.py', 'custody/indicators.py',
                     'custody/engines/zero_dte_timing.py',
                     'custody/strategies/open_hold_v3.json', 'custody/strategies/index.json'):
        destination = args.out/'sources'/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((source_root/relative).read_bytes())
    strategy=Registry().get('open_hold_v3')
    with OpenDMarket() as market:
        ft=_futu()
        calendar_rows=market.trading_days((started.date()-timedelta(days=60)).isoformat(),day)
        calendar=sorted(r['time'] for r in calendar_rows)
        if not any(r['time']==day and r.get('trade_date_type')=='WHOLE' for r in calendar_rows):
            raise ValueError('full market session required')
        session=Session(day,started.replace(hour=9,minute=30,second=0,microsecond=0),started.replace(hour=16,minute=0,second=0,microsecond=0))
        periods=(30,) if started>=session.opens+timedelta(minutes=30) else (15,30)
        candidates=validate_inputs(ranking,bases,day,calendar,periods)
        codes=[r['code'] for r in candidates]
        types=[ft.SubType.K_1M,ft.SubType.K_15M,ft.SubType.K_30M]
        ret,quota=market.context.query_subscription(is_all_conn=True)
        if ret!=0 or quota['remain']<len(codes)*len(types)+len(REFERENCES):
            raise RuntimeError('insufficient subscription quota')
        ret,msg=market.context.subscribe(codes,types,subscribe_push=False,session=ft.Session.RTH)
        if ret!=0: raise RuntimeError(str(msg))
        subscribed=time.monotonic()
        chains={}
        references_subscribed = False
        try:
            ret,msg=market.context.subscribe(list(REFERENCES),[ft.SubType.K_1M],subscribe_push=False,session=ft.Session.RTH)
            if ret!=0: raise RuntimeError(str(msg))
            references_subscribed = True
            subscribed=time.monotonic()
            resolver = OpenDContractResolver(market)
            for candidate in candidates:
                code = candidate['code']
                expiry = candidate.get('expiry', day)
                if candidate.get('expiry_policy') == 'nearest' and resolver.nearest_expiry(code, day) != expiry:
                    raise ValueError('nearest expiry changed; prepare again: ' + code)
                # OpenD permits ten option-chain requests per thirty seconds.
                time.sleep(3.1)
                chains[code]=[c for c in market.option_chain(code,expiry)
                              if c.get('option_standard_type')=='STANDARD' and str(c['strike_time'])[:10]==expiry
                              and not c.get('suspension')]
            missing = [code for code, chain in chains.items()
                       if not any(c.get('option_type') == 'CALL' for c in chain)
                       or not any(c.get('option_type') == 'PUT' for c in chain)]
            if missing:
                raise ValueError('selected-expiry standard call/put chain missing: ' + ', '.join(missing))
            write_json_atomic(args.out/'ready.json', {
                'ready_at': datetime.now(ET).isoformat(), 'trade_date': day,
                'candidates': codes, 'selected_expiry_chains_verified': True,
                'expiries': {c['code']: c.get('expiry', day) for c in candidates},
                'role': 'READ_ONLY_HUMAN_REVIEW', 'orders_submitted': False,
            })
            write_json_atomic(args.out/'review_card.json', {
                'as_of': datetime.now(ET).isoformat(), 'trade_date': day,
                'status': 'WAIT', 'reason': 'WAITING_FOR_COMPLETED_OPENING_BARS',
                'actions': [], 'orders_submitted': False,
            })
            last=None
            while datetime.now(ET)<cutoff:
                now=datetime.now(ET)
                boundary=now.replace(second=0,microsecond=0)
                if boundary<=session.opens or now.second<3 or boundary==last:
                    time.sleep(1)
                    continue
                last=boundary
                minutes=int((boundary-session.opens).total_seconds()/60)
                volume_minutes=30 if minutes>=30 else 15 if minutes>=15 else None
                rows,bars_by_code,errors=[],{},{}
                inputs = {'as_of':boundary.isoformat(),'underlying':{},'opening_volume':{},
                          'references':{},'option_snapshots':{}}
                for source in candidates:
                    code=source['code']
                    try:
                        raw=market.current_kline(code,600,'K_1M')
                        inputs['underlying'][code] = [r for r in raw if str(r['time_key'])[:10]==day]
                        volume=None
                        if volume_minutes:
                            native=market.current_kline(code,40,f'K_{volume_minutes}M')
                            stamp=(session.opens+timedelta(minutes=volume_minutes)).strftime('%Y-%m-%d %H:%M:%S')
                            matching=[r for r in native if r['time_key']==stamp]
                            inputs['opening_volume'][code] = matching
                            if len(matching)!=1: raise ValueError('completed native opening bar unavailable')
                            volume=float(matching[0]['volume'])
                        row,bars=summarize(raw,source,session,boundary,volume,
                            bases[code][f'rvol{volume_minutes}_base'] if volume_minutes else None,volume_minutes)
                        rows.append(row)
                        bars_by_code[code]=bars
                    except (RuntimeError,ValueError,KeyError) as exc:
                        errors[code]=str(exc)
                    time.sleep(.1)
                rows.sort(key=lambda r:(-r['strength_sigma'],-(r['rvol'] or 0),r['rank_pre']))
                context = []
                for code in REFERENCES:
                    try:
                        raw_reference = market.current_kline(code,600,'K_1M')
                        inputs['references'][code] = [r for r in raw_reference if str(r['time_key'])[:10]==day]
                        context.append(reference_summary(raw_reference,code,session,boundary))
                    except (RuntimeError,ValueError,KeyError) as exc:
                        errors[code] = str(exc)
                    time.sleep(.1)
                quote_groups={}
                if minutes>=15:
                    targets={}
                    for row in rows:
                        right='CALL' if row['direction']=='LONG' else 'PUT'
                        near=sorted([c for c in chains[row['code']] if c['option_type']==right],key=lambda c:abs(float(c['strike_price'])-row['close']))[:5]
                        for c in near: targets[c['code']]=row['code']
                    try:
                        snapshots=market.snapshot(list(targets)) if targets else {}
                    except RuntimeError as exc:
                        errors['option_snapshot']=str(exc)
                        snapshots={}
                    for code,q in snapshots.items(): quote_groups.setdefault(targets[code],[]).append(q)
                    inputs['option_snapshots'] = snapshots
                drafts=choose_drafts(rows,quote_groups,day,datetime.now(ET),args.budget_usd-args.fee_reserve_usd)
                timings,signals=annotate_timing(rows,bars_by_code,strategy,session)
                for draft in drafts:
                    draft.update(timings[draft['contract']])
                review_card=build_review_card(rows,signals,day,boundary,
                                              args.budget_usd-args.fee_reserve_usd)
                review_card['market_context'] = context
                review_card['context_errors'] = {code: errors[code] for code in REFERENCES if code in errors}
                review_card['strategy_scope'] = '0DTE_MODEL_UNCHANGED_NEAREST_EXPIRY_PERFORMANCE_UNVALIDATED'
                result={'as_of':boundary.isoformat(),'collected_at':datetime.now(ET).isoformat(),
                        'role':'READ_ONLY_HUMAN_REVIEW','orders_submitted':False,'strategy_sha256':strategy['sha256'],
                        'budget_usd':args.budget_usd,'fee_reserve_usd':args.fee_reserve_usd,
                        'ranking':rows,'drafts':drafts,'entry_signals':signals,
                        'market_context':context,
                        'review_card':review_card,'errors':errors}
                (args.out/'inputs'/(boundary.strftime('%H%M')+'.json')).write_text(
                    json.dumps(inputs,ensure_ascii=False,default=str)+'\n')
                text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
                (args.out/(boundary.strftime('%H%M')+'.json')).write_text(text)
                write_json_atomic(args.out/'latest.json',result)
                write_json_atomic(args.out/'review_card.json',review_card)
                print(json.dumps({'as_of':result['as_of'],'review_card':review_card,
                                  'drafts':drafts,'errors':errors},ensure_ascii=False),flush=True)
                if args.once: break
        finally:
            while time.monotonic()-subscribed<61: time.sleep(1)
            market.context.unsubscribe(codes,types)
            if references_subscribed:
                market.context.unsubscribe(list(REFERENCES),[ft.SubType.K_1M])
    return 0


if __name__=='__main__':
    raise SystemExit(main())
