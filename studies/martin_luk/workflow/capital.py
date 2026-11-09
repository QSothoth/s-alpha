"""Check capital rules and reconstruct close-of-day exposure from frozen ledgers."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
import math

import numpy as np

from . import adapter as D


def check_rules(rules, capital, profile):
    if not isinstance(profile, str) or profile not in capital['profiles']:
        raise ValueError('a valid capital profile must be declared')
    spec = capital['profiles'][profile]
    for key, expected in (('max_gross', spec['initial']), ('margin_rate', spec['margin_rate']),
                          ('maintenance', spec['maintenance'])):
        actual = getattr(rules, key)
        if actual != expected or (actual is not None and not math.isfinite(actual)):
            raise ValueError(f'{key} differs from capital profile {profile}')
    if rules.deleverage not in capital['deleverage_methods']:
        raise ValueError('invalid deleverage method')
    if profile == 'L1' and not rules.gross_cost:
        raise ValueError('cash profile requires fees in the entry limit')
    return rules


def candidate_rules(rules, capital, profile, method=None):
    if not isinstance(profile, str) or profile not in capital['profiles']:
        raise ValueError('a valid capital profile must be declared')
    spec = capital['profiles'][profile]
    return check_rules(replace(rules, max_gross=spec['initial'], margin_rate=spec['margin_rate'],
                               maintenance=spec['maintenance'],
                               gross_cost=True if profile == 'L1' else rules.gross_cost,
                               deleverage=capital['deleverage_default'] if method is None else method),
                       capital, profile)


def daily_exposure(record, dates, codes, close):
    """Rebuild closing positions in O(events + trading days × open positions)."""
    day_index = {str(day): i for i, day in enumerate(dates)}
    code_index = {str(code): j for j, code in enumerate(codes)}
    events = defaultdict(list)
    for trade in record['trades']:
        if not trade.get('executions'):
            raise ValueError('trade has no executions')
        for event in trade['executions']:
            action = event['action']
            if action == 'end':
                continue  # synthetic final liquidation happens after the last equity mark
            change = event['shares'] * (1 if action in ('entry', 'add') else -1)
            events[event['time']].append(((trade['code'], trade['side']), change))
    positions = defaultdict(float)
    result = []
    for day, equity in zip(record['curve']['days'], record['curve']['equity'], strict=True):
        for key, change in events.pop(day, []):
            positions[key] += change
        for key in list(positions):
            if abs(positions[key]) < 1e-10:
                del positions[key]
            elif positions[key] < 0:
                raise ValueError(f'negative position for {key} on {day}')
        if equity <= 0:
            raise ValueError('nonpositive equity')
        i = day_index[day]
        gross = 0.0
        for (code, _side), shares in positions.items():
            j = code_index[code]
            k = i
            while k >= 0 and not np.isfinite(close[k, j]):
                k -= 1
            if k < 0:
                raise ValueError(f'no close for {code} on {day}')
            gross += shares * float(close[k, j])
        result.append(dict(day=day, gross=gross / equity))
    if events:
        raise ValueError('executions outside account curve')
    return result


def annual_exposure(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['day'][:4]].append(row)
    return {year: dict(max=max(x['gross'] for x in group),
                       mean=sum(x['gross'] for x in group) / len(group),
                       max_day=max(group, key=lambda x: x['gross'])['day'], days=len(group))
            for year, group in groups.items()}


def audit(profile):
    """Verify profile declarations, native replays, and the version scorecards."""
    cfg = D.read(D.FLOW/'config.json')
    cap = cfg['capital']
    if profile not in cap['profiles']:
        raise ValueError('a valid capital profile must be declared')
    root = D.OUT/'work/leverage_profiles'
    versions = {row['version']: row for row in D.read(D.FLOW/'versions.json')}
    systems, checked_sources = {}, {}
    for version, name in (('v0', 'master'), ('v1', 'C062')):
        entry = versions[version]
        if entry.get('capital_profile') != cap['acceptance_profile']:
            raise ValueError('version does not declare the acceptance profile')
        systems[name] = {}
        for selected in cap['profiles']:
            path = root/f'{name}_{selected}_weakest_first.json'
            run = D.read(path)
            if run['system'] != name or run['profile'] != selected or run['method'] != cap['deleverage_default']:
                raise ValueError('profile replay identity mismatch')
            check_rules(D.load_rules(run['rules']), cap, selected)
            if entry['scorecard'][selected] != run['annual']:
                raise ValueError('version scorecard differs from the replay')
            if not run.get('fingerprints'):
                raise ValueError('replay lacks input and code fingerprints')
            for source, digest in run['fingerprints'].items():
                if source not in checked_sources:
                    checked_sources[source] = D.sha(D.ROOT/source)
                if checked_sources[source] != digest:
                    raise ValueError('replay source changed: '+source)
            systems[name][selected] = dict(rules={k: run['rules'][k] for k in
                ('max_gross', 'margin_rate', 'maintenance', 'deleverage')},
                replay=str(path.relative_to(D.ROOT)), sha256=D.sha(path))
        other_path = root/f'{name}_{profile}_pro_rata.json'
        if profile == cap['acceptance_profile']:
            other = D.read(other_path)
            if other['system'] != name or other['profile'] != profile or other['method'] != 'pro_rata':
                raise ValueError('comparison replay identity mismatch')
            check_rules(D.load_rules(other['rules']), cap, profile)
            if entry['deleverage_comparison'][profile]['pro_rata'] != other['annual']:
                raise ValueError('comparison scorecard differs from replay')
            for source, digest in other['fingerprints'].items():
                if source not in checked_sources:
                    checked_sources[source] = D.sha(D.ROOT/source)
                if checked_sources[source] != digest:
                    raise ValueError('comparison source changed: '+source)
            systems[name]['pro_rata'] = dict(replay=str(other_path.relative_to(D.ROOT)), sha256=D.sha(other_path))
        legacy_path = root/f'{name}_legacy.json'
        legacy = D.read(legacy_path)
        if not (legacy.get('curve_exact') and legacy.get('trades_exact') and legacy.get('fingerprints')):
            raise ValueError('native default replay did not match the registered ledger')
        for source, digest in legacy['fingerprints'].items():
            if source not in checked_sources:
                checked_sources[source] = D.sha(D.ROOT/source)
            if checked_sources[source] != digest:
                raise ValueError('native replay source changed: '+source)
        systems[name]['legacy'] = dict(replay=str(legacy_path.relative_to(D.ROOT)), sha256=D.sha(legacy_path),
                                       curve_exact=True, trades_exact=True)
    return dict(ok=True, capital=cap, profile=profile, systems=systems, sources=checked_sources,
                config_sha256=D.sha(D.FLOW/'config.json'),
                versions_sha256=D.sha(D.FLOW/'versions.json'))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('command', choices=('audit', 'check'))
    parser.add_argument('--rules', help='candidate Rules JSON, required for check')
    parser.add_argument('--profile', help='declared capital profile, required for audit')
    parser.add_argument('--out')
    args = parser.parse_args()
    if args.command == 'check':
        if not args.rules:
            parser.error('check requires --rules')
        value = D.read(args.rules)
        # Do not allow Rules defaults to hide missing candidate fields.
        if not {'capital_profile', 'max_gross', 'margin_rate', 'maintenance', 'deleverage'} <= value.keys():
            raise ValueError('candidate rules must declare profile, gross, rate, maintenance and deleverage')
        if args.profile is not None and args.profile != value['capital_profile']:
            raise ValueError('profile argument differs from candidate declaration')
        check_rules(D.load_rules(value), D.read(D.FLOW/'config.json')['capital'], value['capital_profile'])
        result = {'ok': True, 'rules': args.rules, 'capital_profile': value['capital_profile']}
    else:
        if not args.profile:
            parser.error('audit requires --profile')
        result = audit(args.profile)
    if args.out:
        D.write(args.out, result)
    else:
        print(D.json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
