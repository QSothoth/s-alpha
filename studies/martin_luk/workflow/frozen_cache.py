"""Freeze WF00 inputs and recompute its selection and execution metrics locally."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from studies.trader_replication import funnel, mainleg, regime
from studies.trader_replication.datasets import sha
from . import adapter as D

ROOT, FLOW, OUT = D.ROOT, D.FLOW, D.OUT
FROZEN = FLOW/'frozen'
CODE = (
    'studies/trader_replication/funnel.py', 'studies/trader_replication/mainleg.py',
    'studies/trader_replication/pipeline.py', 'studies/trader_replication/regime.py',
    'studies/trader_replication/system.py', 'studies/martin_luk/workflow/adapter.py',
    'studies/martin_luk/workflow/frozen_cache.py', 'studies/martin_luk/workflow/capital.py',
    'studies/martin_luk/p3_research.py', 'studies/martin_luk/p4_policy.py',
    'studies/martin_luk/p5_policy.py', 'studies/martin_luk/ie47_e1.py',
    'studies/martin_luk/e10_research.py', 'studies/martin_luk/e15_research.py',
    'studies/martin_luk/replicate.py', 'studies/trader_replication/allocation.py',
    'studies/trader_data/supplemental.py',
)


def identity():
    cfg = D.read(FLOW/'config.json')
    # Dataset identity comes from the pinned whitelist, including artifacts and evaluation SHAs.
    pinned = {k: v for k, v in cfg['datasets'].items() if k != 'approved_by_user'}
    data = json.dumps(pinned, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return {p: sha(ROOT/p) for p in CODE}, hashlib.sha256(data).hexdigest()


def load(line, version):
    code, data = identity()
    folder = FROZEN/line/version
    state = D.read(FLOW/'state.json')
    if 'frozen_caches' in state:
        entry = state['frozen_caches'].get(line, {}).get(version)
        if not entry or entry.get('manifest_sha256') != sha(folder/'manifest.json'):
            raise ValueError('frozen cache manifest differs from state')
    return funnel.load_frozen(folder, version, code, data, line=line)


def save(line, version, files, sources, **metadata):
    folder = FROZEN/line/version
    folder.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
        (folder/name).write_text(json.dumps(D.clean(value), ensure_ascii=False,
                                           separators=(',', ':'), allow_nan=False)+'\n')
    code, data = identity()
    manifest = dict(line=line, version=version,
        generated_at=datetime.now(timezone.utc).isoformat(),
        command='/opt/opend-us-options/.venv/bin/python -m studies.martin_luk.workflow.frozen_cache build',
        code_fingerprints=code, data_fingerprint=data,
        data_fingerprint_scope='canonical config.datasets excluding approval date, including pinned artifacts and evaluation inputs',
        sources={str(Path(p).relative_to(ROOT)): sha(p) for p in sources},
        files={name: sha(folder/name) for name in files}, **metadata)
    (folder/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1)+'\n')


def refresh_manifest(line, version):
    folder = FROZEN/line/version
    manifest = D.read(folder/'manifest.json')
    if manifest['line'] != line or manifest['version'] != version:
        raise ValueError('frozen cache identity mismatch')
    for name, digest in manifest['files'].items():
        if sha(folder/name) != digest:
            raise ValueError('frozen cache content mismatch: '+str(folder/name))
    mutable = {str((FLOW/name).relative_to(ROOT)) for name in ('config.json', 'state.json')}
    for name, digest in list(manifest['sources'].items()):
        if name == str((FLOW/'state.json').relative_to(ROOT)):
            del manifest['sources'][name]
            manifest['state_source'] = 'state.components.conversion is checked against allocation.json on load'
            continue
        current = sha(ROOT/name)
        if name not in mutable and current != digest:
            raise ValueError('unchanged cache source mismatch: '+name)
        manifest['sources'][name] = current
    manifest['code_fingerprints'], manifest['data_fingerprint'] = identity()
    manifest['generated_at'] = datetime.now(timezone.utc).isoformat()
    (folder/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1)+'\n')


def selection_source(cfg, version):
    systems = cfg['systems']
    direct = systems.get(version, {}).get('picks')
    paths = {spec['picks'] for spec in systems.values()
             if spec.get('picks') and Path(spec['picks']).name.removesuffix('.gz').removesuffix('.json') == version}
    if direct:
        paths = {direct}
    if len(paths) != 1:
        raise ValueError('no unique registered picks for frozen selection: '+version)
    return ROOT/paths.pop()


def event_prices(A, legs):
    """Only labelled-window opens and peak closes, never a market-panel copy."""
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    opens, closes = defaultdict(dict), defaultdict(dict)
    for g in legs:
        code, j = g['code'], ci[g['code']]
        for t in range(max(0, g['first']-4), min(g['peak']-1, len(A['days'])-1)):
            x = float(A['open'][t+1, j])
            opens[code][str(t+1)] = x if np.isfinite(x) else None
        for t in (g['peak']-1, g['peak']):
            x = float(A['close'][t, j])
            closes[code][str(t)] = x if np.isfinite(x) else None
    return dict(open=opens, close=closes)


def array_inputs(calendar, legs, prices):
    codes = sorted({g['code'] for g in legs})
    A = dict(days=calendar, codes=codes)
    for kind in ('open', 'close'):
        values = np.full((len(calendar), len(codes)), np.nan)
        for j, code in enumerate(codes):
            for t, value in prices[kind].get(code, {}).items():
                if value is not None:
                    values[int(t), j] = value
        A[kind] = values
    # holding_coverage only reads closes for label attribution and peak weights.
    A['high'] = A['low'] = A['open']
    return A


def build():
    state, cfg, saved_regime = D.read(FLOW/'state.json'), D.read(FLOW/'config.json'), D.read(OUT/'regime.json')
    selection_version = state['components']['selection']['version']
    trading_version = state['components']['trading']['version']
    regime_version = state['components']['regime']['version']
    source = selection_source(cfg, selection_version)
    candidate_order = D.REPORTS/'p2a_work/market'/f'{selection_version}_order.json'
    market_inputs = [D.REPORTS/'p3_work/market'/f'{k}.npy' for k in ('open', 'close')]
    market_inputs += [D.REPORTS/'u1_work/panel'/f'{k}.npy' for k in ('days', 'codes')]
    pins = {item['path']: item['sha256'] for item in cfg['datasets']['artifacts']}
    upstream = candidate_order if str(candidate_order.relative_to(ROOT)) in pins else source
    for path in [source, upstream, *market_inputs]:
        relative = str(path.relative_to(ROOT))
        if pins.get(relative) != sha(path):
            raise ValueError('cache source is not the pinned artifact: '+relative)
    A, legs = D.market(), D.labels()
    calendar = list(map(str, A['days']))
    if calendar != saved_regime['calendar'] or len(calendar) != len(saved_regime['label']):
        raise ValueError('frozen regime calendar mismatch')
    states = saved_regime['label']
    prices = event_prices(A, legs)
    price_array = array_inputs(calendar, legs, prices)
    opens = {code: price_array['open'][:, j] for j, code in enumerate(price_array['codes'])}
    picks, order = D.indexed(A, source), D.indexed(A, upstream)
    k3 = mainleg.signal_coverage_budget(picks, None, legs, calendar, opens, 3)
    native_unlimited = mainleg.signal_coverage_budget(picks, None, legs, calendar, opens, None)
    upstream_unlimited = mainleg.signal_coverage_budget(order, None, legs, calendar, opens, None)
    selection = dict(calendar=calendar, legs=legs, source_picks=picks,
        k3_picks=k3['picks'], native_unlimited_picks=native_unlimited['picks'],
        upstream_order=order, upstream_unlimited_picks=upstream_unlimited['picks'],
        source=str(source.relative_to(D.REPORTS) if source.is_relative_to(D.REPORTS) else source.relative_to(ROOT)),
        width_policy='native unlimited removes the external K only; the saved input retains its own limit',
        upstream_policy=('raw pre-K ranking' if upstream != source else 'own nominations; raw ranking unavailable'))
    cfg_path, legs_path = FLOW/'config.json', ROOT/cfg['legs']['path']
    manifest_sources = [cfg_path, legs_path, source, upstream, OUT/'regime.json', *market_inputs]
    if saved_regime['spec_sha'] != state['components']['regime']['spec_sha']:
        raise ValueError('frozen regime definition mismatch')
    save('selection', selection_version, {'inputs.json': selection, 'prices.json': prices}, manifest_sources,
         upstream_order_source=str(upstream.relative_to(ROOT)),
         upstream_order_policy=selection['upstream_policy'])
    D.execution_inputs(A)
    A['master_filtered'] = D.master_books(A)['filtered']
    record, rules, nominations = funnel.execution_bench(A, legs, picks,
        lambda market, offered: D.execution(market, offered, trading_version,
                                            profile=cfg['capital']['acceptance_profile']))
    account = dict(record=record, rules=asdict(rules))
    combined, his, control = nominations['picks'], nominations['his'], nominations['control']
    end = cfg['selection_years'][-1]+'-12-31'
    day_index = max(i for i, day in enumerate(calendar) if day <= end)
    ci = {str(c): j for j, c in enumerate(A['codes'])}
    end_marks = {}
    for trade in account['record']['trades']:
        if trade['entry'] <= end < trade['exit']:
            index, j = day_index, ci[trade['code']]
            while index > 0 and not np.isfinite(A['close'][index, j]):
                index -= 1
            end_marks[trade['code']] = float(A['close'][index, j])
    inputs = dict(calendar=calendar, legs=legs, his=his, control=control, combined=combined,
        selection_version=selection_version,
        behaviour_card=cfg['behaviour_card'], tolerance=cfg['hard_lines']['behaviour_tolerance'],
        selection_years=cfg['selection_years'], selection_end=calendar[day_index], selection_end_marks=end_marks)
    execution_sources = [ROOT/p for p in pins if any(p.endswith('/'+name) for name in (
        'master_metadata.json', 'master_liquidity.npy', 'master_raw.json', 'master_filtered.json',
        'master_book.json', 'master_short_entries.json', 'selection.npz'))]
    save('trading', trading_version, {'inputs.json': inputs, 'account.json': account,
        'prices.json': prices}, [cfg_path, legs_path, source, OUT/'regime.json', *market_inputs, *execution_sources],
        selection_version=selection_version)
    refresh_manifest('regime', regime_version)
    refresh_manifest('conversion', state['components']['conversion']['version'])
    for name in cfg['reference_accounts']:
        refresh_manifest('reference', name)
    size = sum(p.stat().st_size for p in FROZEN.rglob('*') if p.is_file())
    if size > 200_000_000:
        raise RuntimeError(f'frozen cache exceeds 200MB: {size}')
    print('frozen cache bytes:', size, flush=True)


def selection_score():
    state = D.read(FLOW/'state.json')
    files = load('selection', state['components']['selection']['version'])
    payload, prices = files['inputs.json'], files['prices.json']
    states = load('regime', state['components']['regime']['version'])['states.json']
    calendar, legs = payload['calendar'], payload['legs']
    if states['calendar'] != calendar:
        raise ValueError('cache calendars do not match')
    A = array_inputs(calendar, legs, prices)
    opens = {code: A['open'][:, j] for j, code in enumerate(A['codes'])}
    picks = {int(t): names for t, names in payload['source_picks'].items()}
    possible = {int(t): names for t, names in payload['upstream_order'].items()}
    score = mainleg.signal_coverage_budget(picks, None, legs, calendar, opens, 3)
    wide = mainleg.signal_coverage_budget(picks, None, legs, calendar, opens, None)
    if ({str(t): v for t, v in score['picks'].items()} != payload['k3_picks'] or
            {str(t): v for t, v in wide['picks'].items()} != payload['native_unlimited_picks']):
        raise ValueError('cached selection nominations differ from recomputation')
    reachable = {}
    for g in legs:
        reachable[g['key']] = any(g['code'] in possible.get(t, ()) and np.isfinite(opens[g['code']][t+1])
            and opens[g['code']][t+1] > 0 and (g['top']/opens[g['code']][t+1]-1)/g['gain'] >= .5-1e-12
            for t in range(max(0, g['first']-4), min(g['peak']-1, len(calendar)-1)))
    for y, annual in score['annual'].items():
        annual['unlimited_mean_new_names'] = wide['annual'][y]['mean_new_names']
        annual['unlimited_unique_names'] = wide['annual'][y]['unique_names']
        annual['reachable'] = sum(reachable[g['key']] for g in legs if calendar[g['first']].startswith(y))
        annual['by_state'] = {}
        for s in regime.NAMES:
            rows = [r for g, r in zip(legs, score['per_leg']) if r['year'] == y and states['label'][g['first']] == s]
            nights = [t for t in wide['picks'] if calendar[t].startswith(y) and states['label'][t] == s]
            names = [c for t in nights for c in wide['picks'][t]]
            annual['by_state'][s] = dict(n=len(rows), covered=sum(r['covered'] for r in rows),
                reachable=sum(reachable[g['key']] for g in legs if calendar[g['first']].startswith(y) and states['label'][g['first']] == s),
                unlimited_mean_new_names=len(names)/len(nights) if nights else None,
                unique_names=len({c for t in nights for c in score['picks'][t]}), unlimited_unique_names=len(set(names)))
    score.pop('picks')
    score.update(source=payload['source'], unlimited=wide['annual'], reachable_per_leg=reachable,
        upper_bound_policy=('同一上游名单与合格夜，忽略外层K/冷却冲突的上限；'+payload['upstream_policy']))
    return D.clean(score)


def bench_score():
    state = D.read(FLOW/'state.json')
    files = load('trading', state['components']['trading']['version'])
    inputs, account = files['inputs.json'], files['account.json']
    if inputs['selection_version'] != state['components']['selection']['version']:
        raise ValueError('bench cache depends on a different frozen selection')
    states = load('regime', state['components']['regime']['version'])['states.json']
    calendar, legs = inputs['calendar'], inputs['legs']
    if states['calendar'] != calendar:
        raise ValueError('cache calendars do not match')
    A = array_inputs(calendar, legs, files['prices.json'])
    record, rules = account['record'], D.load_rules(account['rules'])
    cov = funnel.holding_coverage(A, record, rules, legs)
    di = {d: t for t, d in enumerate(calendar)}
    assigned = []
    for trade in record['trades']:
        g = mainleg.leg_at(trade['code'], di[trade['entry']], legs, trade['fill']) if trade['side'] > 0 else None
        assigned.append(dict(trade, leg=g['key'] if g else None,
            anchor_year=calendar[g['first']][:4] if g else None, state=states['label'][di[trade['entry']]]))
    annual, prior = {}, 1.
    for year in ('2024', '2025', '2026'):
        all_trades = [t for t in assigned if t['entry'].startswith(year)]
        his = [t for t in assigned if t['anchor_year'] == year]
        controls = [t for t in all_trades if t['leg'] is None]
        eq = [e for d, e in zip(record['curve']['days'], record['curve']['equity']) if d.startswith(year)]
        stats = funnel.trade_stats(all_trades)
        stats['return'], prior = eq[-1]/prior-1, eq[-1]
        counts = [r for r in cov if r['year'] == year]
        annual[year] = dict(n=len(counts), peak_held=sum(r['peak_held'] is True for r in counts),
            early=sum(r['covered'] for r in counts), his=funnel.trade_stats(his), control=funnel.trade_stats(controls),
            account=stats, behaviour_gap=funnel.behaviour_gap(stats, inputs['behaviour_card'].get(year, {}),
                inputs['tolerance']), by_state={})
        for state in regime.NAMES:
            part = [r for g, r in zip(legs, cov) if r['year'] == year and states['label'][g['first']] == state]
            h = [t for t in his if states['label'][next(g['first'] for g in legs if g['key'] == t['leg'])] == state]
            annual[year]['by_state'][state] = dict(n=len(part), peak_held=sum(r['peak_held'] is True for r in part),
                early=sum(r['covered'] for r in part), his=funnel.trade_stats(h),
                control=funnel.trade_stats([t for t in controls if t['state'] == state]),
                account=funnel.trade_stats([t for t in all_trades if t['state'] == state]))
    years = inputs['selection_years']
    chosen_his = [t for t in assigned if t['anchor_year'] in years]
    chosen_control = [t for t in assigned if t['leg'] is None and t['entry'][:4] in years]
    closed = [t for t in chosen_his if t['why'] != 'end']
    selection = dict(his_mean_r=float(np.mean([t['r'] for t in closed])) if closed else None,
        control_pnl=sum(t['pnl'] for t in chosen_control),
        behaviour_within=sum(annual[y]['behaviour_gap']['within'] for y in years))
    # The retained full ledger contains all pre-cutoff fills. Mark positions still
    # open at the selection boundary, without replaying the execution engine.
    end = inputs['selection_end']
    training_trades = [t for t in assigned if t['exit'] <= end]
    crossing = sorted((t for t in assigned if t['entry'] <= end < t['exit']), key=lambda t: t['entry'])
    for trade in crossing:
        cash, shares = 0., 0.
        for event in trade['executions']:
            if event['time'] > end:
                break
            quantity, price = event['shares'], event['price']
            if event['action'] in ('entry', 'add'):
                shares += quantity
                cash -= quantity*price*(1+rules.buy_cost)
            else:
                shares -= quantity
                cash += quantity*price*(1-rules.sell_cost)
        cash += shares*inputs['selection_end_marks'][trade['code']]*(1-rules.sell_cost)
        training_trades.append(dict(trade, why='end', pnl=cash))
    training = dict(annual={}, selection={})
    for year in years:
        part = [r for r in cov if r['year'] == year]
        training['annual'][year] = dict(peak_held=sum(r['peak_held'] is True and r['peak_eve'] <= end for r in part),
            peak_unknown=sum(r['peak_eve'] > end for r in part), by_state={
                s: dict(n=sum(r['year'] == year and states['label'][g['first']] == s for g, r in zip(legs, cov)),
                    peak_held=sum(r['year'] == year and states['label'][g['first']] == s and r['peak_held'] is True and r['peak_eve'] <= end for g, r in zip(legs, cov)),
                    peak_unknown=sum(r['year'] == year and states['label'][g['first']] == s and r['peak_eve'] > end for g, r in zip(legs, cov)))
                for s in regime.NAMES})
    his_closed = [t for t in training_trades if t['anchor_year'] in years and t['why'] != 'end']
    training['selection'] = dict(his_mean_r=float(np.mean([t['r'] for t in his_closed])) if his_closed else None,
        control_pnl=sum(t['pnl'] for t in training_trades if t['leg'] is None),
        behaviour_within=sum(funnel.behaviour_gap(funnel.trade_stats([t for t in training_trades if t['entry'].startswith(y)]),
            inputs['behaviour_card'][y], inputs['tolerance'])['within'] for y in years))
    return D.clean(dict(annual=annual, selection=selection, per_leg=cov, attribution=assigned,
                        rules=account['rules'], training=training))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('build',))
    parser.parse_args()
    build()


if __name__ == '__main__':
    main()
