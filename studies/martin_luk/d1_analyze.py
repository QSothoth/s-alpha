"""Lot accounting, per-leg funnels and bounded, same-night D1 portraits."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from pathlib import Path

import numpy as np

from .d1_research import HOME, ROOT, OUT, clean, log, offline, panel, read, sha, write


def eligible(leg, index, price):
    return any(index >= e['index']-3 and leg['top']/price-1 >= .5*e['gain']-1e-12
               for e in leg['entries'])


def assign(legs, code, index, price):
    candidates = [l for l in legs if l['code'] == code and l['first']-3 <= index < l['peak']]
    return min(candidates, key=lambda l: (-(l['top']/price-1), l['first'])) if candidates else None


def split_lots(trade, fee_buy=.0005, fee_sell=.0005):
    """Allocate every actual partial proportionally to the then-open acquisition lots."""
    lots = []
    for event in trade['executions']:
        q, price = event['shares'], event['price']
        if event['action'] in ('entry', 'add'):
            lots.append(dict(day=event['time'], action=event['action'], price=price, shares=q,
                             remaining=q, sales=[], cost=q*price*(1+fee_buy)))
        else:
            total = sum(l['remaining'] for l in lots)
            assert q <= total+1e-10 and total > 0, (trade['code'], event, total)
            for lot in lots:
                sold = lot['remaining']*min(1., q/total)
                if sold > 0:
                    lot['sales'].append(dict(day=event['time'], shares=sold, price=price,
                                            action=event['action'], proceeds=sold*price*(1-fee_sell)))
                    lot['remaining'] -= sold
    assert abs(sum(l['remaining'] for l in lots)) < 1e-9
    assert np.isclose(sum(sum(s['proceeds'] for s in l['sales'])-l['cost'] for l in lots),
                      trade['pnl'], rtol=1e-8, atol=1e-10), trade
    return lots


def lot_values(lot, cutoff, close, di):
    """Segment PNL through cutoff, marking unsold inventory without a hypothetical selling fee."""
    sales = [s for s in lot['sales'] if di[s['day']] <= cutoff and s['action'] != 'end']
    remaining = max(0., lot['shares']-sum(s['shares'] for s in sales))
    pnl = sum(s['proceeds'] for s in sales) + remaining*float(close[cutoff]) - lot['cost']
    q = np.zeros(len(close))
    born = di[lot['day']]
    q[born:] = lot['shares']
    for s in lot['sales']:
        if s['action'] != 'end':
            q[di[s['day']]:] -= s['shares']
    q = np.maximum(0., q)
    return pnl, q


def account_specs():
    base = HOME/'reports/e21_work'
    swap = HOME/'reports/e15_work/master_swap'
    return {
        'master': (OUT/'master_trades.json', OUT/'master_curve.json', OUT/'master_attempts.json'),
        'master_C062': (swap/'full/C062_2024_trades.json', swap/'full/C062_2024_curve.json', OUT/'master_c062_attempts.json'),
        'IE47_C062': (base/'BASE_full/C062_2024_trades.json', base/'BASE_full/C062_2024_curve.json', base/'BASE_full/attempts.json'),
        'master_S1': (base/'master/S1_full/C062_2024_trades.json', base/'master/S1_full/C062_2024_curve.json', base/'master/S1_full/attempts.json'),
        'IE47_S1': (base/'S1_full/C062_2024_trades.json', base/'S1_full/C062_2024_curve.json', base/'S1_full/attempts.json'),
    }


def account(name, trades, curve, legs, days, p):
    di, ci = {d: i for i, d in enumerate(days)}, {str(c): j for j, c in enumerate(p['codes'])}
    equity = np.full(len(days), np.nan)
    for day, value in zip(curve['days'], curve['equity']):
        equity[di[day]] = value
    exposure, confirmed_exposure = np.zeros(len(days)), np.zeros(len(days))
    leg_exposure = {l['id']: np.zeros(len(days)) for l in legs}
    leg_conf = {l['id']: np.zeros(len(days)) for l in legs}
    rows, reconciled = [], 0
    all_lots = []
    for tid, trade in enumerate(trades):
        # The registered master includes shorts in the account; its H labels are long-only.
        if trade['side'] < 0:
            q = np.zeros(len(days))
            for e in trade['executions']:
                if e['action'] == 'end':
                    continue
                q[di[e['time']]:] += e['shares']*(1 if e['action'] in ('entry', 'add') else -1)
            exposure += np.maximum(0., q)*np.nan_to_num(p['close'][:, ci[trade['code']]])
            continue
        lots = split_lots(trade)
        reconciled += 1
        additions = [e['time'] for e in trade['executions'] if e['action'] == 'add']
        confirmed = trade.get('confirmed_day') or (min(additions) if additions else None)
        if isinstance(confirmed, int):
            confirmed = days[confirmed]
        conf_index = di[confirmed] if confirmed else len(days)
        j = ci[trade['code']]
        for lid, lot in enumerate(lots):
            born = di[lot['day']]
            _, quantity = lot_values(lot, len(days)-1, p['close'][:, j], di)
            value = quantity*np.nan_to_num(p['close'][:, j])
            exposure += value
            confirmed_exposure[conf_index:] += value[conf_index:]
            leg = assign(legs, trade['code'], born, lot['price'])
            full_pnl = sum(s['proceeds'] for s in lot['sales'])-lot['cost']
            item = dict(trade_id=tid, lot_id=lid, code=trade['code'], entry=trade['entry'], day=lot['day'],
                        action=lot['action'], exit=trade['exit'], why=trade['why'], fill=lot['price'],
                        shares=lot['shares'], notional=lot['shares']*lot['price'],
                        full_pnl=full_pnl, leg=leg['id'] if leg else None,
                        confirmed_day=confirmed, additions=additions,
                        proof_trail_day=trade.get('proof_trail_day'),
                        trailing_at_exit='e21' if name == 'master' or (trade.get('proof_trail_day') and
                                          trade['proof_trail_day'] <= trade['exit']) else 'e9',
                        initial_nominal_equity=lots[0]['shares']*lots[0]['price']/equity[di[trade['entry']]],
                        kind=trade['kind'], observed=trade.get('observed'), origin=trade.get('origin'))
            if leg:
                peak = leg['peak']
                pnl, _ = lot_values(lot, peak, p['close'][:, j], di)
                realized_sales = [s for s in lot['sales'] if di[s['day']] <= peak and s['action'] != 'end']
                sold = sum(s['shares'] for s in realized_sales)
                realized = sum(s['proceeds'] for s in realized_sales)-lot['cost']*sold/lot['shares']
                leg_exposure[leg['id']][:peak+1] += value[:peak+1]
                if conf_index <= peak:
                    leg_conf[leg['id']][conf_index:peak+1] += value[conf_index:peak+1]
                item.update(pnl=pnl, pnl_realized=realized, pnl_marked=pnl-realized,
                            early=eligible(leg, born, lot['price']), offset=born-leg['first'],
                            lifecycle=(lot['price']-leg['low'])/(leg['top']-leg['low']),
                            potential_total=item['notional']*leg['entries'][0]['gain'],
                            potential_remaining=lot['shares']*(leg['top']-lot['price']),
                            mark_to=days[min(di[trade['exit']], peak)],
                            mark_reason='peak_close' if di[trade['exit']] > peak or trade['why'] == 'end' else trade['why'])
            all_lots.append(item)
    for leg in legs:
        items = [x for x in all_lots if x['leg'] == leg['id']]
        initials = sorted([x for x in items if x['action'] == 'entry'], key=lambda x: x['day'])
        early_initials = [x for x in initials if x['early']]
        pnl = sum(x['pnl'] for x in items)
        potential = sum(x['potential_total'] for x in items)
        rem = sum(x['potential_remaining'] for x in items)
        weight = leg_exposure[leg['id']]/equity
        rows.append(dict(system=name, leg=leg['id'], any=bool(initials), early=bool(early_initials),
            synced=any(any(e['index']-3 <= di[x['day']] <= e['index']+2 for e in leg['entries'])
                       for x in early_initials), first_fill=initials[0] if initials else None,
            first_early=early_initials[0] if early_initials else None,
            pnl=pnl, gross_profit=sum(max(0., x['pnl']) for x in items),
            pnl_realized=sum(x['pnl_realized'] for x in items), pnl_marked=sum(x['pnl_marked'] for x in items),
            potential_total=potential, potential_remaining=rem,
            capture_total=pnl/potential if potential else None,
            capture_remaining=pnl/rem if rem > 0 else None,
            max_nominal_equity=float(np.nanmax(weight)) if items else 0.,
            equity_days=float(np.nansum(weight)), confirmed_equity_days=float(np.nansum(leg_conf[leg['id']]/equity)),
            had_add=any(x['action'] == 'add' for x in items),
            last_exit=max((x['exit'] for x in initials), default=None),
            trade_count=len(initials), lot_count=len(items), trades=initials,
            lots=items))
    annual = {}
    total_leg_exposure = sum(leg_exposure.values())
    total_leg_conf = sum(leg_conf.values())
    for year in ('2024', '2025', '2026'):
        labels = [l for l in legs if l['year'] == year]
        ids = {l['id'] for l in labels}
        selected = [r for r in rows if r['leg'] in ids]
        ix = np.array([d.startswith(year) and np.isfinite(equity[i]) for i, d in enumerate(days)])
        ty = [t for t in trades if t['entry'].startswith(year)]
        iy = [x for x in all_lots if x['entry'].startswith(year) and x['leg']]
        his_pnl = sum(x['pnl'] for x in iy)
        # A common split of every trade's realized PNL into H and post-peak/other residuals.
        trade_h = defaultdict(float)
        for x in iy:
            trade_h[x['trade_id']] += x['pnl']
        gp = sum(max(0., t['pnl']) for t in ty)
        gross_h = sum(max(0., v) for v in trade_h.values())
        gross_other = sum(max(0., t['pnl']-trade_h.get(i, 0.)) for i, t in enumerate(trades) if t['entry'].startswith(year))
        denom_total = sum(x['potential_total'] for x in iy)
        denom_rem = sum(x['potential_remaining'] for x in iy)
        top = sorted([(i, t) for i, t in enumerate(trades) if t['entry'].startswith(year) and t['pnl'] > 0],
                     key=lambda x: -x[1]['pnl'])[:10]
        top_closed = sorted([(i, t) for i, t in enumerate(trades) if t['entry'].startswith(year)
                             and t['pnl'] > 0 and t['why'] != 'end'], key=lambda x: -x[1]['pnl'])[:10]
        early_lots = [x for x in iy if x['early']]
        early_trade_ids = {x['trade_id'] for x in iy if x['early'] and x['action'] == 'entry'}
        year_ix = np.flatnonzero(ix)
        initial = next((curve['equity'][k-1] if k else 1. for k, d in enumerate(curve['days']) if d.startswith(year)), None)
        annual[year] = dict(n=len(labels), any=sum(r['any'] for r in selected), early=sum(r['early'] for r in selected),
            early_positive=sum(r['early'] and r['pnl'] > 0 for r in selected), synced=sum(r['synced'] for r in selected),
            label_year_pnl=sum(r['pnl'] for r in selected), pnl=his_pnl,
            pnl_realized=sum(x['pnl_realized'] for x in iy), pnl_marked=sum(x['pnl_marked'] for x in iy),
            early_lot_pnl=sum(x['pnl'] for x in early_lots),
            early_full_trade_pnl=sum(trades[i]['pnl'] for i in early_trade_ids),
            gross_h=gross_h, gross_all=gp, purity_gross=gross_h/(gross_h+gross_other) if gross_h+gross_other else None,
            purity_legacy=gross_h/gp if gp else None,
            total_trade_pnl=sum(t['pnl'] for t in ty), other_pnl=sum(t['pnl'] for t in ty)-his_pnl,
            year_initial_equity=initial, pnl_year_equity=his_pnl/initial if initial else None,
            year_return=float(equity[year_ix[-1]]/initial-1) if len(year_ix) and initial else None,
            capture_total=his_pnl/denom_total if denom_total else None,
            capture_remaining=his_pnl/denom_rem if denom_rem > 0 else None,
            cap_equity=float(np.nanmean(total_leg_exposure[ix]/equity[ix])) if ix.any() else None,
            cap_share=float(total_leg_exposure[ix].sum()/exposure[ix].sum()) if exposure[ix].sum() else None,
            cap_confirmed=float(total_leg_conf[ix].sum()/confirmed_exposure[ix].sum()) if confirmed_exposure[ix].sum() else None,
            top10_h=sum(trade_h.get(i, 0.) > 0 for i, _ in top_closed),
            top10=[dict(code=t['code'], entry=t['entry'], pnl=t['pnl'], h=trade_h.get(i, 0.)) for i, t in top_closed],
            top10_including_end_h=sum(trade_h.get(i, 0.) > 0 for i, _ in top),
            opened=len(ty), closed_win=sum(t['pnl'] > 0 and t['why'] != 'end' for t in ty)/max(1, sum(t['why'] != 'end' for t in ty)))
    return dict(system=name, legs=rows, annual=annual, long_trades_reconciled=reconciled,
                lots=all_lots, input_trade_count=len(trades))


def funnel(p, legs, results):
    from studies.martin_luk import luk
    days, codes = list(map(str, p['days'])), list(map(str, p['codes']))
    di, ci = {d: i for i, d in enumerate(days)}, {c: j for j, c in enumerate(codes)}
    selection = read(OUT/'ie_selection.json')
    ie_nights = {r['index']: r for r in selection['nights']}
    scope_j = np.load(OUT/'ie_scope_j.npy', mmap_mode='r')
    gate_pct = np.load(OUT/'ie_gate_pct.npy', mmap_mode='r')
    picks = selection['picks']
    observations = read(OUT/'ie_observations.json')
    master_liq = np.load(OUT/'master_liquidity.npy', mmap_mode='r')
    master_mom = np.load(OUT/'master_momentum.npy', mmap_mode='r')
    ie_pool = np.load(OUT/'ie_pool.npy', mmap_mode='r')
    streams = {
        'master': read(OUT/'master_capped.json'),
        'master_C062': read(OUT/'master_capped.json'),
        'IE47_C062': read(HOME/'reports/e21_work/BASE_signals.json'),
        'IE47_S1': read(HOME/'reports/e21_work/S1_signals.json'),
    }
    master_s1 = read(HOME/'reports/e21_work/master/S1_full/attempts.json')
    streams['master_S1'] = [dict(day=a['day'], code=a['code'], kind=a['kind']) for a in master_s1]
    trace = {stage: read(OUT/f'master_{stage}.json') for stage in ('raw', 'filtered', 'capped')}
    route_masks = {f.stem.removeprefix('master_'): np.load(f, mmap_mode='r')
                   for f in sorted(OUT.glob('master_family_*.npy'))}
    route_masks.update({n: np.load(OUT/f'master_{n}.npy', mmap_mode='r') for n in ('ep', 'bpath')})
    attempts = {name: read(spec[2]) for name, spec in account_specs().items()}
    out = []
    for leg in legs:
        code, first, peak = leg['code'], leg['first'], leg['peak']
        j = ci.get(code)
        assert j is not None
        close, high = p['close'][:, j], p['high'][:, j]
        valid = [d for d in range(max(1, first-3), peak) if np.isfinite(close[d]) and eligible(leg, d, close[d])]
        end = max(valid, default=first-3)
        early_breaks = [d for d in valid if close[d] > high[d-1]]
        code_picks = [di[day] for day, names in picks.items() if code in names]
        history = [d for d in code_picks if first-8 <= d < peak]
        ranges = p['high'][:, j].astype(float)/p['low'][:, j].astype(float)-1
        raw_adr = luk.rolling_mean(ranges[:, None], 20)[:, 0]*100
        early_breaks = [d for d in early_breaks if np.isfinite(raw_adr[d-1]) and raw_adr[d-1] >= 2.]
        from studies.trader_screens import screens as S
        e21 = S.ema(close[:, None], 21)[:, 0]
        for name, result in results.items():
            row = next(r for r in result['legs'] if r['leg'] == leg['id'])
            is_master = name.startswith('master')
            evaluated = range(max(0, first-3), end+1) if is_master else range(max(0, first-8), end)
            pool_days = [d for d in evaluated if (master_liq[d, j] if is_master else ie_pool[d, j])]
            momentum_days = [d for d in evaluated if master_mom[d, j]] if is_master else pool_days
            named = [d for d in history if d < end] if not is_master else []
            prior_named = [d for d in code_picks if d < end] if not is_master else []
            sig = [s for s in streams[name] if s['code'] == code and first-3 <= di[s['day']] < peak]
            early_sig = [s for s in sig if di[s['day']] in valid]
            blocked = [a for a in attempts[name] if a['code'] == code and di[a['day']] in valid and a['reason'] != 'filled']
            obs = [o for o in observations if o['code'] == code and first-8 <= di[o['day']] < peak]
            gate_trace = []
            if not is_master:
                for d in evaluated:
                    r = ie_nights.get(d)
                    if r is None:
                        continue
                    sl = slice(r['scope_start'], r['scope_end'])
                    found = np.flatnonzero(scope_j[sl] == j)
                    if not len(found):
                        gate_trace.append(dict(day=days[d], in_scope=False))
                        continue
                    k = r['scope_start']+int(found[0])
                    ps = clean(gate_pct[k])
                    fail = [g[0] for z, g in enumerate(selection['gates'])
                            if (ps[z] is None and z != 0) or (ps[z] is not None and ps[z] < g[1])]
                    cooling = set().union(*(set(picks.get(days[b], [])) for b in range(max(0, d-10), d)))
                    available = [c for c in sorted(r['ranks'], key=r['ranks'].get) if c not in cooling]
                    gate_trace.append(dict(day=days[d], in_scope=True, failed=fail, percentiles=ps,
                        rank=r['ranks'].get(code), score=r['scores'].get(code), cooling=code in cooling,
                        eligible_rank=available.index(code)+1 if code in available else None,
                        picked=code in picks.get(days[d], [])))
            stages = {stage: [s for s in stream if s['code'] == code and di[s['day']] in valid and s.get('side', 1) > 0]
                      for stage, stream in trace.items()} if is_master else {}
            late = [s['day'] for s in sig if di[s['day']] not in valid]
            if row['early']:
                category = 'early_profitable' if row['pnl'] > 0 else 'early_lost'
            elif early_sig:
                category = 'early_signal_blocked'
            elif not pool_days:
                category = 'pool_excluded'
            elif is_master:
                category = ('market_blocked' if stages['raw'] and not stages['filtered'] else
                            'daily_cap' if stages['filtered'] and not stages['capped'] else
                            'no_setup_or_stop' if momentum_days else 'momentum_watch_excluded')
            elif not named:
                category = 'pool_not_named'
            elif early_breaks:
                subsequent_breaks = [d for d in early_breaks if any(b < d for b in named)]
                ages = [d-max(b for b in code_picks if b < d) for d in subsequent_breaks]
                category = ('named_after_early_break' if not ages else
                            'observation_expired' if min(ages) > 5 else 'observation_consumed_or_stop')
                if name.endswith('S1'):
                    removed = []
                    for d in early_breaks:
                        born = max((b for b in code_picks if b < d), default=None)
                        if born is not None and np.any(close[born+1:d] < e21[born+1:d]):
                            removed.append(days[d])
                    category = 'persistent_list_removed' if removed else 'observation_consumed_or_stop'
            else:
                category = 'no_early_close_break'
            item = dict(system=name, leg=leg['id'], code=code, year=leg['year'], in_panel=True,
                first=leg['first_date'], peak=leg['peak_date'], first_pool=days[pool_days[0]] if pool_days else None,
                first_momentum=days[momentum_days[0]] if momentum_days else None,
                first_pick=days[named[0]] if named else None,
                previous_pick=days[max((d for d in code_picks if d < first-8), default=-1)] if any(d < first-8 for d in code_picks) else None,
                first_pick_ever=days[code_picks[0]] if code_picks else None,
                stale_nomination=bool(prior_named and not named),
                first_signal=min((s['day'] for s in sig), default=None),
                first_early_signal=min((s['day'] for s in early_sig), default=None),
                category=category, rejection_counts=dict(Counter(a['reason'] for a in blocked)),
                rejected=blocked, qualified_fill_days=[days[d] for d in valid],
                price_breaks=[dict(day=days[d], age=d-max((b for b in code_picks if b < d), default=-10000),
                                   prior_adr=float(raw_adr[d-1])) for d in early_breaks],
                late_signals=late, observations=obs if not is_master else [], nominations=[days[d] for d in history] if not is_master else [],
                gate_trace=gate_trace, master_signal_stages=stages, **{k: v for k, v in row.items() if k not in ('system', 'leg')})
            if is_master:
                item['signal_routes'] = {s['day']: [n for n, m in route_masks.items() if m[di[s['day']], j]]
                                         for s in sig}
                item['entry_context'] = {}
                for trade in row['trades']:
                    d = di[trade['entry']]
                    last_pick = max((b for b in code_picks if b < d), default=None)
                    item['entry_context'][trade['entry']] = dict(
                        close_over_prior_high=bool(close[d] > high[d-1]),
                        ie_previous_pick=days[last_pick] if last_pick is not None else None,
                        ie_watch_age=d-last_pick if last_pick is not None else None,
                        ie_pool_previous_night=bool(ie_pool[d-1, j]))
            out.append(item)
    return out


def measure():
    frozen = read(OUT/'legs_legacy42.json')
    legs, days = frozen['legs'], frozen['days']
    p = panel()
    assert days == list(map(str, p['days']))
    # Confirm labels against the actual common panel, not merely the older cache.
    from studies.trader_replication import mainleg
    ci = {str(c): j for j, c in enumerate(p['codes'])}
    px = {c: {k: p[v][:, j] for k, v in (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'))} for c, j in ci.items()}
    entries = [(l['code'], e['index'], e['label']) for l in legs for e in l['entries']]
    regenerated = mainleg.legs(entries, px)
    assert [(l['code'], l['peak']) for l in regenerated] == [(l['code'], l['peak']) for l in legs]
    results = {}
    for name, paths in account_specs().items():
        results[name] = account(name, read(paths[0]), read(paths[1]), legs, days, p)
        write(name+'_metrics.json', results[name])
        log(name+' lot accounting reconciled')
    write('summary.json', {n: r['annual'] for n, r in results.items()})
    rows = funnel(p, legs, results)
    write('funnel.json', rows)
    fields = ('system', 'leg', 'code', 'year', 'first', 'peak', 'first_pool', 'first_momentum', 'first_pick',
              'first_signal', 'first_early_signal', 'category', 'any', 'early', 'synced', 'trade_count',
              'had_add', 'max_nominal_equity', 'equity_days', 'pnl', 'capture_total', 'capture_remaining', 'last_exit')
    with (OUT/'funnel.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        w = csv.DictWriter(stream, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k) for k in fields})
    specs = account_specs()
    write('account_inputs.json', {n: {str(p.relative_to(ROOT)): sha(p) for p in paths} for n, paths in specs.items()})
    # Preserve the advisor's mixed-account early-PNL approximation as an audit bridge, not the main comparison.
    bridge = {}
    swap = HOME/'reports/e15_work/master_swap'
    for label, directory, stem in [('train', swap/'train', '2024'), ('standalone2026', swap/'2026', '2026')]:
        trades = read(directory/f'C062_{stem}_trades.json')
        bridge[label] = account(label, trades, read(directory/f'C062_{stem}_curve.json'), legs, days, p)['annual']
    write('pi_bridge.json', bridge)
    log(f'{len(rows)} per-segment/system funnels complete')


FEATURES = ('dollar_vol20_M', 'adr20_pct', 'perf21_pct', 'perf63_pct', 'perf126_pct',
            'from_high252_pct', 'ema_stack', 'ext_ema9_adr', 'ext_ema21_adr', 'ema9_21_gap_adr',
            'rvol20', 'rvol3_20', 'inside_day', 'nr7', 'contract3_adr', 'gap_today_adr',
            'close_pos', 'perf1_pct', 'perf5_pct', 'low252_distance_pct')


def portraits():
    from studies.trader_replication import standard_indicators as SI
    from studies.trader_data import supplemental as SP
    from studies.martin_luk import luk
    p = panel()
    days = list(map(str, p['days']))
    legs = read(OUT/'legs_legacy42.json')['legs']
    ci = {str(c): j for j, c in enumerate(p['codes'])}
    opportunities = []
    for leg in legs:
        c = p['close'][:, ci[leg['code']]]
        qualified = [d for d in range(max(0, leg['first']-3), leg['peak']) if np.isfinite(c[d]) and eligible(leg, d, c[d])]
        opportunities.extend(dict(leg=leg['id'], code=leg['code'], year=leg['year'], index=d, day=days[d],
                                  first_three=k < 3) for k, d in enumerate(qualified))
    indices = sorted({r['index'] for r in opportunities})
    ni = {d: i for i, d in enumerate(indices)}
    shape = (len(indices), len(p['codes']), len(FEATURES))
    matrix = np.lib.format.open_memmap(OUT/'portrait_values.npy', mode='w+', dtype='float32', shape=shape)
    liquid = np.lib.format.open_memmap(OUT/'portrait_liquid.npy', mode='w+', dtype='bool', shape=shape[:2])
    qqq, _ = SP.benchmark('US.QQQ', days, 'frozen')
    subset = tuple(n for n in FEATURES if n != 'perf126_pct')
    for j in range(len(p['codes'])):
        arrays = {key: p[field][:, j] for key, field in
                  (('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume'),
                   ('t', 'turnover'), ('raw_c', 'raw_close'))}
        values = SI.per_stock(arrays, qqq, names=subset)
        values['perf126_pct'] = 100*(SI.divide(arrays['c'], SI.lag(arrays['c'], 126))-1)
        matrix[:, j, :] = np.column_stack([values[n][indices] for n in FEATURES])
        to20 = luk.rolling_mean(arrays['t'].astype(float)[:, None], 20)[:, 0]
        liquid[:, j] = (arrays['raw_c'][indices] >= 1) & (to20[indices] >= 2e6)
        if j % 400 == 0:
            log(f'portrait per-stock indicators {j}/{len(p["codes"])}')
    matrix.flush()
    liquid.flush()
    master_pool = np.load(OUT/'master_liquidity.npy', mmap_mode='r')
    master_watch = np.load(OUT/'master_momentum.npy', mmap_mode='r')
    ie_pool = np.load(OUT/'ie_pool.npy', mmap_mode='r')
    rows = []
    for target in opportunities:
        d, j = target['index'], ci[target['code']]
        s = ni[d]
        peers = dict(liquid=liquid[s], master_pool=master_pool[min(d+1, len(days)-1)],
                     master_momentum=master_watch[min(d+1, len(days)-1)], IE47_pool=ie_pool[d])
        target = dict(target, memberships={n: bool(m[j]) for n, m in peers.items()}, features={})
        for f, name in enumerate(FEATURES):
            x = float(matrix[s, j, f])
            result = dict(value=x)
            for name_pool, mask in peers.items():
                v = matrix[s, mask, f]
                v = v[np.isfinite(v)]
                result[name_pool] = dict(n=len(v), percentile=float(100*(np.count_nonzero(v < x)+.5*np.count_nonzero(v == x))/len(v))
                                         if len(v) and np.isfinite(x) else None)
            target['features'][name] = result
        rows.append(target)
    write('portraits.json', dict(features=FEATURES, nights=indices, records=rows))
    with (OUT/'portraits.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        fields = ('leg', 'code', 'year', 'day', 'first_three', 'feature', 'value', 'peer_pool', 'in_pool', 'n', 'percentile')
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            for feature, data in row['features'].items():
                for pool, member in row['memberships'].items():
                    writer.writerow(clean(dict(leg=row['leg'], code=row['code'], year=row['year'], day=row['day'],
                        first_three=row['first_three'], feature=feature, value=data['value'], peer_pool=pool,
                        in_pool=member, **data[pool])))
    summarize(rows)
    write('portrait_metadata.json', dict(shape=shape, records=len(rows), first_three=sum(r['first_three'] for r in rows),
          aggregation='median per segment over first three qualified close nights, then median/IQR across segments',
          percentile='100 * (less + 0.5*ties)/finite peers; target may be outside peer pool',
          supplemental_126='100*(close/close[t-126]-1), same units as v1.1 perf21/perf63, no registered 126-day column',
          no_fitting=True, indicator_source_sha256=sha(SI.__file__)))
    log(f'portraits complete: {len(rows)} opportunity nights, {len(indices)} unique dates')


def summarize(rows=None):
    rows = read(OUT/'portraits.json')['records'] if rows is None else rows
    aggregates = {}
    for year in ('2024', '2025', '2026'):
        aggregates[year] = {}
        for feature in FEATURES:
            grouped = defaultdict(list)
            for row in rows:
                if row['year'] == year and row['first_three']:
                    grouped[row['leg']].append(row['features'][feature])
            raw = [float(np.median([x['value'] for x in g if x['value'] is not None and np.isfinite(x['value'])]))
                   for g in grouped.values() if any(x['value'] is not None and np.isfinite(x['value']) for x in g)]
            item = dict(n=len(raw), median=float(np.nanmedian(raw)) if raw else None,
                        q25=float(np.nanpercentile(raw, 25)) if raw else None,
                        q75=float(np.nanpercentile(raw, 75)) if raw else None)
            for pool in ('liquid', 'master_pool', 'master_momentum', 'IE47_pool'):
                v = [float(np.nanmedian([np.nan if x[pool]['percentile'] is None else x[pool]['percentile'] for x in g]))
                     for g in grouped.values() if any(x[pool]['percentile'] is not None for x in g)]
                item[pool] = dict(n=len(v), median=float(np.nanmedian(v)) if v else None,
                                  q25=float(np.nanpercentile(v, 25)) if v else None,
                                  q75=float(np.nanpercentile(v, 75)) if v else None)
            aggregates[year][feature] = item
    write('portrait_summary.json', aggregates)


def check():
    t = dict(code='TEST', pnl=23.782, executions=[
        dict(time='a', action='entry', price=10., shares=2.),
        dict(time='b', action='add', price=12., shares=1.),
        dict(time='c', action='trim', price=15., shares=1.5),
        dict(time='d', action='trail', price=17., shares=1.5)])
    t['pnl'] = 1.5*15*.9995+1.5*17*.9995-(20+12)*1.0005
    lots = split_lots(t)
    assert [round(s['shares'], 9) for s in lots[0]['sales']] == [1., 1.]
    price = np.array([10., 12., 15., 17.])
    di = dict(a=0, b=1, c=2, d=3)
    pnl, q = lot_values(lots[0], 2, price, di)
    assert np.isclose(pnl, 15*.9995+15-20*1.0005)
    np.testing.assert_allclose(q, [2, 2, 1, 0])
    from copy import deepcopy
    changed = deepcopy(lots[0])
    changed['sales'][-1]['price'] *= 50
    changed['sales'][-1]['proceeds'] *= 50
    assert lot_values(changed, 2, price, di)[0] == pnl
    a = dict(code='TEST', first=4, peak=10, top=20., entries=[dict(index=4, gain=1.)])
    b = dict(code='TEST', first=5, peak=11, top=25., entries=[dict(index=5, gain=1.5)])
    assert assign([a, b], 'TEST', 4, 12.) is b
    assert assign([a], 'TEST', 0, 10.) is None
    assert assign([a], 'TEST', 10, 10.) is None
    assert eligible(a, 1, 13.) and not eligible(a, 1, 14.)
    assert not eligible(a, 0, 10.)
    write('self_check.json', dict(ok=True, checks=['proportional partials', 'peak mark without future exit',
          'future-sale perturbation', 'quantity timing', 'overlapping segment unique allocation',
          'lead/peak boundaries', 'actual-fill half gain']))
    log('D1 accounting self-check passed')


def verify():
    """Check the persisted artifacts and protected inputs, not merely the running code."""
    import ast
    frozen = read(OUT/'legs_legacy42.json')
    legs = frozen['legs']
    rows = read(OUT/'funnel.json')
    assert len(legs) == 42 and len(rows) == 210
    assert len({(r['system'], r['leg']) for r in rows}) == 210
    assert all(r['in_panel'] for r in rows)
    summary = read(OUT/'summary.json')
    overlaps = {}
    for name in account_specs():
        measured = read(OUT/f'{name}_metrics.json')
        assert measured['annual'] == summary[name]
        assert len({(x['trade_id'], x['lot_id']) for x in measured['lots']}) == len(measured['lots'])
        for lot in measured['lots']:
            candidates = [l for l in legs if l['code'] == lot['code'] and
                          frozen['days'][max(0, l['first']-3)] <= lot['day'] < l['peak_date']]
            if len(candidates) > 1:
                overlaps.setdefault(name, []).append(dict(trade_id=lot['trade_id'], lot_id=lot['lot_id'],
                    code=lot['code'], day=lot['day'], action=lot['action'], assigned=lot['leg'],
                    possible=[l['id'] for l in candidates]))
            if lot['leg']:
                leg = next(l for l in legs if l['id'] == lot['leg'])
                assert frozen['days'][max(0, leg['first']-3)] <= lot['day'] < leg['peak_date']
                assert np.isclose(lot['pnl_realized']+lot['pnl_marked'], lot['pnl'])
        for year, r in summary[name].items():
            matching = [x for x in rows if x['system'] == name and x['year'] == year]
            assert r['early'] == sum(x['early'] for x in matching)
            assert np.isclose(r['label_year_pnl'], sum(x['pnl'] for x in matching))
    write('overlap_audit.json', overlaps)
    assert read(OUT/'selection_check.json')['exact_e21_picks']
    assert all(read(OUT/'trace_checks.json')[k] for k in
               ('master_capped_matches_e21', 'ie_base_book_matches_e21', 'master_c062_trades_exact', 'master_c062_curve_exact'))
    assert read(OUT/'master_paths.json')['routes_exact']
    assert read(OUT/'self_check.json')['ok']
    portrait = read(OUT/'portraits.json')
    assert {r['leg'] for r in portrait['records']} == {l['id'] for l in legs}
    for row in portrait['records']:
        for value in row['features'].values():
            for pool in ('liquid', 'master_pool', 'master_momentum', 'IE47_pool'):
                assert value[pool]['percentile'] is None or 0 <= value[pool]['percentile'] <= 100
    tests = {}
    for suite, count in (('martin', 200), ('custody', 237)):
        path = OUT/f'tests_{suite}.log'
        text = path.read_text()
        assert f'Ran {count} tests' in text and text.rstrip().endswith('OK'), suite
        tests[suite] = dict(count=count, ok=True, sha256=sha(path))
    protocol = read(OUT/'protocol.json')
    protected = {name: sha(ROOT/name) == digest for name, digest in protocol['sources'].items()
                 if name != 'studies/trader_replication/mainleg.py' and not Path(name).name.startswith('d1_')}
    assert all(protected.values()), [n for n, ok in protected.items() if not ok]
    code = {}
    for path in HOME.glob('d1_*.py'):
        ast.parse(path.read_text())
        code[str(path.relative_to(ROOT))] = sha(path)
    write('verification.json', dict(ok=True, segment_system_rows=210, legacy_segments=42,
          tests=tests, source_unchanged=protected, scripts=code, network_disabled=True,
          A_line_mainleg_changed=sha(ROOT/'studies/trader_replication/mainleg.py') != protocol['sources']['studies/trader_replication/mainleg.py'],
          interrupted_serialization_attempt='stopped before 900 MiB; switched diagnostics to bounded arrays; selection unchanged',
          hook_install='installer declined to overwrite an existing core.hooksPath; no commit/push or hook bypass',
          checks=['unique lot assignment', 'every long trade execution cash flow reconciled',
                  'realized plus marked PNL', 'segment bounds', 'summary to per-leg totals',
                  'exact upstream books and master C062 ledger/equity', 'portrait peer ranges', 'protected sources']))
    log('persisted D1 artifacts and protected inputs verified')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=('measure', 'portraits', 'summarize', 'check', 'verify'))
    args = parser.parse_args()
    offline()
    globals()[args.stage]()
