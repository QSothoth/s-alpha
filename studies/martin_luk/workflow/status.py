"""Build the selection-year state from the frozen main system and separate bar."""
from collections import Counter
import json

from studies.trader_replication import funnel, regime
from . import adapter as D, capital, frozen_cache as F


def _valid_replay_audit(path, cap):
    try:
        audit = D.read(path)
        if (audit.get('ok') is not True or audit.get('capital') != cap or
                audit.get('profile') != cap['acceptance_profile'] or
                audit.get('config_sha256') != D.sha(D.FLOW/'config.json') or
                audit.get('versions_sha256') != D.sha(D.FLOW/'versions.json')):
            return False
        sources = audit['sources']
        critical = {name: digest for name, digest in sources.items() if name.endswith('.py')}
        if not critical or any(D.sha(D.ROOT/name) != digest for name, digest in critical.items()):
            return False
        config = D.read(D.FLOW/'config.json')
        years = config['selection_years']
        versions = {v['version']: v for v in D.read(D.FLOW/'versions.json')
                    if v['version'].startswith('v') and v['version'][1:].isdigit()}
        if 'versions' in audit:
            original = audit['previous_audit']
            if D.sha(D.ROOT/original['path']) != original['sha256']:
                return False
            original_audit = D.read(D.ROOT/original['path'])
        elif set(versions) == {'v0', 'v1'}:
            original_audit = audit
        else:
            return False
        if (original_audit.get('ok') is not True or original_audit.get('capital') != cap or
                original_audit.get('config_sha256') != D.sha(D.FLOW/'config.json')):
            return False
        for name in ('master', 'C062'):
            runs = original_audit['systems'][name]
            for key in (*cap['profiles'], 'pro_rata', 'legacy'):
                row = runs[key]
                if D.sha(D.ROOT/row['replay']) != row['sha256']:
                    return False
            if not (runs['legacy']['curve_exact'] and runs['legacy']['trades_exact']):
                return False
        if original_audit is audit:
            return True
        if set(audit['versions']) != set(versions):
            return False
        for version, entry in versions.items():
            saved = audit['versions'][version]
            if saved['name'] != entry['name'] or set(saved['profiles']) != set(cap['profiles']):
                return False
            for profile, row in saved['profiles'].items():
                replay, reference = D.ROOT/row['replay'], D.ROOT/row['reference']
                if D.sha(replay) != row['sha256'] or D.sha(reference) != row['reference_sha256']:
                    return False
                run, source = D.read(replay), D.read(reference)
                if (run['version'] != version or run['profile'] != profile or
                        run['reference'] != row['reference'] or run['reference_sha256'] != row['reference_sha256'] or
                        run['end'] != years[-1]+'-12-31' or set(run['annual']) != set(years) or
                        not (run['rules_exact'] and run['annual_exact'] and run['comparison']['ok']) or
                        any(v['differences'] for v in run['annual'].values()) or
                        run['rules'] != source['rules'] or entry['scorecard'][profile] != source['annual'] or
                        any(not result['computed'] or any(source['annual'][year].get(key) != value
                            for key, value in result['computed'].items())
                            for year, result in run['annual'].items())):
                    return False
                manifest = {'engine': run['engine'], 'engine_sha256': run['engine_sha256']}
                capital.check_rules(F.bench_rules(manifest, run['rules']), cap, profile)
        for check in audit.get('cross_checks', []):
            reference = D.ROOT/check['reference']
            if D.sha(reference) != check['reference_sha256']:
                return False
            source = D.read(reference)
            row = audit['versions'][check['version']]['profiles'][check['profile']]
            run = D.read(D.ROOT/row['replay'])
            if (run['record'] != {k: source['record'][k] for k in run['record']} or
                    run['track'] != source['track']):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _replay_evidence(cap):
    paths = sorted((D.FLOW/'rounds').glob('*/capital_audit.json'), reverse=True)
    paths.append(D.OUT/'work/leverage_profiles/capital_audit.json')
    return any(_valid_replay_audit(path, cap) for path in paths)


def _test_evidence():
    paths = sorted((D.FLOW/'rounds').glob('*/logs/tests.json'), reverse=True)
    paths.append(D.OUT/'work/leverage_profiles/tests.json')
    for path in paths:
        try:
            tests = D.read(path)
            required = ('custody/tests', 'studies/trader_replication/tests',
                        'studies/martin_luk/tests', 'studies/trader_screens/tests')
            code = tests['code_sha256']
            required_code = ('studies/trader_replication/system.py', 'studies/martin_luk/workflow/capital.py',
                             'studies/martin_luk/workflow/status.py', 'studies/martin_luk/workflow/versions.py',
                             'studies/martin_luk/workflow/adapter.py', 'studies/martin_luk/workflow/frozen_cache.py',
                             'studies/trader_replication/tests/test_margin_call.py',
                             'studies/martin_luk/tests/test_workflow_versions_capital.py')
            if (tests.get('code_unchanged_during_tests') is True and
                    all(name in code for name in required_code) and
                    all(digest == D.sha(D.ROOT/name) for name, digest in code.items()) and
                    all(tests['suites'][name]['passed'] is True and
                        tests['suites'][name]['returncode'] == 0 and tests['suites'][name]['count'] > 0 and
                        D.sha(D.ROOT/tests['suites'][name]['log']) == tests['suites'][name]['log_sha256']
                        for name in required)):
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


def _cache_evidence(state, cap):
    try:
        code, data = F.identity()
        for line, versions in state['frozen_caches'].items():
            for version, reference in versions.items():
                manifest_path = F.FROZEN/line/version/'manifest.json'
                manifest = D.read(manifest_path)
                if (D.sha(manifest_path) != reference['manifest_sha256'] or
                        manifest['code_fingerprints'] != code or manifest['data_fingerprint'] != data):
                    return False
                files = F.load(line, version)
                if (line == 'conversion' and version == state['components']['conversion']['version'] and
                        files['allocation.json'] != state['components']['conversion']):
                    return False
        for name in ('master', 'C062'):
            check = D.read(D.OUT/f'work/leverage_profiles/bench_{name}.json')
            folder = F.FROZEN/'trading'/name
            if (check['profile'] != cap['acceptance_profile'] or
                    not all(check[k] is True for k in ('curve_exact', 'trades_exact', 'attempts_exact')) or
                    check['system_sha256'] != code['studies/trader_replication/system.py'] or
                    check['adapter_sha256'] != code['studies/martin_luk/workflow/adapter.py'] or
                    check['capital_sha256'] != code['studies/martin_luk/workflow/capital.py'] or
                    check['script_sha256'] != D.sha(D.OUT/'work/leverage_bench_check.py') or
                    check['input_sha256'] != D.sha(folder/'inputs.json') or
                    check['account_sha256'] != D.sha(folder/'account.json')):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _dataset_evidence(cfg):
    paths = sorted((D.FLOW/'rounds').glob('*/logs/datasets_evidence.json'), reverse=True)
    path = paths[0] if paths else D.OUT/'work/leverage_profiles/datasets_check.json'
    try:
        data = D.read(path)
        if not (data.get('ok') is True and data.get('approved_by_user') == cfg['datasets'].get('approved_by_user')
                and data.get('config_sha256') == D.sha(D.FLOW/'config.json')):
            return False
        if paths:
            log = D.ROOT/data['log']
            result = D.read(log)
            return (D.sha(log) == data['log_sha256'] and result.get('ok') is True and
                    result.get('approved_by_user') == cfg['datasets'].get('approved_by_user'))
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def readiness(cfg, state):
    """Fail closed when a prerequisite or its current evidence is absent."""
    g1 = state.get('current_hard_gates', {}).get('G1', {})
    g1_checks = g1.get('numbers', {}).get('checks', {})
    cap = cfg['capital']
    replay = _replay_evidence(cap)
    rule_pins = state.get('rule_fingerprints', {})
    return dict(
        g1=(g1.get('status') == 'pass' and all(g1_checks.get(k, {}).get('ok') is True
            for k in ('data', 'fills', 'lookahead', 'win_rate'))),
        whitelist_approved=bool(cfg['datasets'].get('approved_by_user')),
        datasets=_dataset_evidence(cfg),
        capital_rules=replay,
        registered_unchanged=bool(replay and _test_evidence()),
        cache_consistent=_cache_evidence(state, cap),
        rule_fingerprints=bool(rule_pins) and all(D.sha(D.ROOT/p) == digest for p, digest in rule_pins.items()),
    )


def _missing_unresolved(legs, states, measured, years, cutoff):
    """Retain crossing segments omitted from a selection-cutoff funnel."""
    calendar = states['calendar']
    present = {row['key'] for row in measured}
    missing = []
    for leg in legs:
        year = calendar[leg['first']][:4]
        if year not in years or leg['key'] in present:
            continue
        eve = calendar[leg['peak']-1]
        if eve <= cutoff:
            raise ValueError('completed segment missing from main funnel: '+leg['key'])
        missing.append(dict(key=leg['key'], year=year, state=states['label'][leg['first']],
                            coverage={'peak_eve': eve}))
    return missing


def generate():
    cfg, state = D.read(D.FLOW/'config.json'), D.read(D.FLOW/'state.json')
    folder = D.FLOW/'rounds'/state.get('metrics_round', 'WF00')
    years, cutoff = cfg['selection_years'], cfg['selection_years'][-1]+'-12-31'
    selected, bench = F.selection_score(), F.bench_score()
    selection = F.load('selection', state['components']['selection']['version'])['inputs.json']
    states = F.load('regime', state['components']['regime']['version'])['states.json']
    merge_component = state['components']['merge']
    merged = F.load('merge', merge_component['version'])
    base = merged['funnel.json']
    bar_name = cfg['bar']
    if state['bar'] != bar_name:
        raise ValueError('bar differs from config')
    bar = D.read(D.OUT/'funnels'/f'{bar_name}.json')
    bar_account = F.load('reference', bar_name)['account.json']

    # This evidence is derived from the pinned E1 candidate pool, not from
    # the already-truncated nominations. Reject stale evidence explicitly.
    pool_path = D.OUT/'work/base_c062_pool_evidence.json'
    pool = D.read(pool_path)
    for name, digest in pool['sources'].items():
        if D.sha(D.ROOT/name) != digest:
            raise ValueError('structural pool evidence is stale: '+name)
    pool_by_key = {r['key']: r for r in pool['per_leg']}
    legs_by_key = {g['key']: g for g in selection['legs']}
    selection_by_key = {r['key']: r for r in selected['per_leg']}
    if any(r['key'] not in pool_by_key or r['key'] not in selection_by_key
           for r in base['per_leg'] if r['year'] in years):
        raise ValueError('main funnel, selection and pool segments differ')
    missing = _missing_unresolved(selection['legs'], states, base['per_leg'], years, cutoff)

    def yearly(rows, predicate):
        return {y: sum(bool(predicate(r)) for r in rows if r['year'] == y) for y in years}

    def counts(rows):
        c = Counter(r['layer'] for r in rows)
        return {k: c[k] for k in funnel.LAYERS}

    def in_scope(row, scope):
        return row['year'] in years and (scope == 'common' or row['state'] == scope)

    cells = []
    for scope in ('common', *regime.NAMES):
        rows = [r for r in base['per_leg'] if in_scope(r, scope)]
        missing_in_scope = [r for r in missing if in_scope(r, scope)]
        known = [r for r in rows if r['coverage']['peak_eve'] <= cutoff]
        unresolved = [r for r in rows if r['coverage']['peak_eve'] > cutoff] + missing_in_scope
        selected_rows = [selection_by_key[r['key']] for r in rows + missing_in_scope]
        known_keys = {r['key'] for r in known}
        selected_known = [r for r in selected_rows if r['key'] in known_keys]
        selection_estimates = selected_known if missing_in_scope else selected_rows
        structural = lambda r: bool(pool_by_key[r['key']]['first_hit'])
        observed = lambda r: bool(selected['reachable_per_leg'][r['key']])
        covered = lambda r: bool(r['covered'])
        losses, known_losses = counts(rows), counts(known)
        target = len(rows) + len(missing_in_scope)
        training_parts = [bench['training']['annual'][y] if scope == 'common'
                          else bench['training']['annual'][y]['by_state'][scope] for y in years]
        full_parts = [bench['annual'][y] if scope == 'common'
                      else bench['annual'][y]['by_state'][scope] for y in years]
        metrics = {
            'selection': dict(metric='S_K3_early', current=sum(covered(r) for r in selected_known),
                current_by_year=yearly(selected_known, covered),
                retrospective_current=None if missing_in_scope else sum(covered(r) for r in selected_rows),
                retrospective_current_by_year=None if missing_in_scope else yearly(selected_rows, covered),
                reachable_upper=sum(structural(r) for r in selection_estimates),
                reachable_upper_by_year=yearly(selection_estimates, structural),
                upper_observed_in_emitted_list=sum(observed(r) for r in selection_estimates),
                upper_observed_in_emitted_list_by_year=yearly(selection_estimates, observed),
                structural_upper_among_completed_legs=sum(structural(r) for r in selected_known),
                upper_source=str(pool_path.relative_to(D.FLOW)),
                note='结构性上限取 E1 冻结合格池；名单内观测上限单列。'),
            'trading': dict(metric='his_peak_held_on_bench',
                current=sum(r['peak_held'] for r in training_parts),
                current_by_year={y: r['peak_held'] for y, r in zip(years, training_parts)},
                retrospective_current=sum(r['peak_held'] for r in full_parts),
                reachable_upper=target,
                note='测试台直接喂他的票；上限是样本段数。'),
            'conversion': dict(metric='early_and_peak_held',
                current=sum(r['layer'] == 'L6' for r in known),
                current_by_year=yearly(known, lambda r: r['layer'] == 'L6'),
                retrospective_current=sum(r['layer'] == 'L6' for r in rows),
                early_buy=sum(r['coverage']['covered'] for r in rows),
                projected_early_nominations=sum(r['signal_hit'] for r in rows),
                reachable_upper=target,
                note='L6 为早买且峰前持有；点名数是诊断投影。'),
            'merge': dict(metric='peak_held',
                current=sum(r['coverage']['peak_held'] is True for r in known),
                current_by_year=yearly(known, lambda r: r['coverage']['peak_held'] is True),
                retrospective_current=sum(r['coverage']['peak_held'] is True for r in rows),
                early_buy=sum(r['coverage']['covered'] for r in rows),
                early_and_peak_held=sum(r['layer'] == 'L6' for r in rows),
                reachable_upper=target,
                note='峰前持有包括晚买；L6 只包括早买且峰前持有。')}
        for line, metric in metrics.items():
            if missing_in_scope:
                metric['retrospective_current'] = None
            line_layers = base['layer_lines'].get(line, [])
            row = dict(line=line, state=scope, target=target,
                target_by_year=yearly(rows + missing_in_scope, lambda r: True), frozen_version=state['components'][line],
                observed=bool(target), layer_losses=None if missing_in_scope else losses,
                layer_losses_known_by_selection_cutoff=known_losses,
                unresolved_layers_at_selection_cutoff=len(unresolved),
                unresolved_at_selection_cutoff=len(unresolved),
                loss_in_merge=None if missing_in_scope else sum(losses[k] for k in line_layers),
                loss_known_by_selection_cutoff=sum(known_losses[k] for k in line_layers), **metric)
            upper = sum(structural(r) for r in selected_known) if line == 'selection' else len(known)
            row['recoverable'] = min(max(0, len(known)-row['current']), max(0, upper-row['current']))
            row['recoverable_scope'] = '仅选择年末已完成的段；跨年未决段不参与定格'
            cells.append(row)
    stability = next((r['value'] for r in state['components']['regime'].get('reasons', [])
                      if r.get('rule') == 'stability' and r.get('ok') is True), None)
    if stability is None:
        raise ValueError('frozen regime has no passing stability evidence')
    for scope in ('common', *regime.NAMES):
        cells.append(dict(line='regime', state=scope, current=stability,
            target=cfg['accept']['regime']['min_agreement'], reachable_upper=1.0,
            frozen_version=state['components']['regime'], observed=scope != 'pullback'))
    eligible = [r for r in cells if r['line'] in base['layer_lines'] and r['observed']]
    if not eligible:
        raise ValueError('no observed selection-year cells')
    pick = max(eligible, key=lambda r: (r['loss_known_by_selection_cutoff'], r['recoverable'], r['state'] == 'common'))

    def account_stats(record, measured):
        result = {}
        for year in years:
            trades = [dict(t, why='end') if t['exit'] > cutoff else t
                      for t in record['trades'] if t['entry'].startswith(year)]
            stats = funnel.trade_stats(trades)
            stats['return'] = measured['annual'][year]['account']['return']
            result[year] = {k: stats[k] for k in ('n', 'closed', 'win', 'payoff', 'days', 'return')}
        return result

    def system_summary(name, measured, record, omitted_unresolved=0):
        rows = [r for r in measured['per_leg'] if r['year'] in years]
        complete = [r for r in rows if r['coverage']['peak_eve'] <= cutoff]
        return dict(system=name, account=account_stats(record, measured),
            annual={y: {k: measured['annual'][y][k] for k in
                    ('n', 'layers', 'named', 'early', 'peak_held', 'early_peak_held')} for y in years},
            layers_known_by_selection_cutoff=counts(complete),
            unresolved_at_selection_cutoff=len(rows)-len(complete)+omitted_unresolved,
            convention=measured['convention'])

    main_name = merge_component.get('evaluation_system', merge_component['version'])
    unresolved = [r for r in base['per_leg'] if r['year'] in years and r['coverage']['peak_eve'] > cutoff] + missing
    known = [r for r in base['per_leg'] if r['year'] in years and r['coverage']['peak_eve'] <= cutoff]
    selected_common = [selection_by_key[r['key']] for r in (known if missing else base['per_leg']) if r['year'] in years]
    known_keys = {r['key'] for r in known}
    issues = {}
    issue_path = D.ROOT/'skills/trader-replication/references/workflow_issues.jsonl'
    if issue_path.exists():
        for line in issue_path.read_text().splitlines():
            issue = json.loads(line)
            issues[issue.get('ref', issue['id'])] = issue['status']
    checks = readiness(cfg, state)
    can_start = bool(state.get('can_start_round', False) and all(checks.values()))
    return D.clean(dict(round=folder.name, selection_years=years, holdout=cfg['holdout'],
        cells=cells, components=state['components'], pending_merge=state['pending_merge'],
        bootstrap_done=state['bootstrap_done'], datasets_approved=bool(cfg['datasets']['approved_by_user']),
        can_start_round=can_start, valid_for_next_round=can_start, readiness_checks=checks,
        blocked_reasons=state.get('blocked_reasons', []),
        next_cell=dict(line=pick['line'], state=pick['state'],
            reason='按选择年末已完成的段，先选主线漏斗丢段最多的线，再选可补空间最大的状态；未决段不参与定格。'),
        selection_upper_bound=dict(source=str(pool_path.relative_to(D.FLOW)), source_sha256=D.sha(pool_path),
            pool='studies/martin_luk/reports/e1_work/selection.npz',
            pool_sha256=pool['sources']['studies/martin_luk/reports/e1_work/selection.npz'],
            scope='仅选择年末已完成段' if missing else '冻结漏斗中的选择年段',
            structural=yearly(selected_common, lambda r: bool(pool_by_key[r['key']]['first_hit'])),
            observed_in_emitted_list=yearly(selected_common, lambda r: bool(selected['reachable_per_leg'][r['key']])),
            completed_legs_by_year={y: dict(upper=sum(bool(pool_by_key[r['key']]['first_hit'])
                for r in selected_common if r['year'] == y and r['key'] in known_keys),
                n=sum(r['year'] == y for r in known)) for y in years}),
        unresolved_segments=[dict(key=r['key'], year=r['year'], state=r['state'],
                                  peak_eve=r['coverage']['peak_eve']) for r in unresolved],
        current_merge=system_summary(main_name, base, merged['account.json']['record'], len(missing)),
        baseline_master=system_summary(bar_name, bar, bar_account),
        hard_gates=state.get('current_hard_gates') or D.read(folder/'fixed_cards.json'),
        fingerprints=D.fingerprints(), rule_fingerprints=state.get('rule_fingerprints', {}),
        frozen_caches=state.get('frozen_caches', {}),
        frozen_cache_bytes=sum(p.stat().st_size for p in F.FROZEN.rglob('*') if p.is_file()),
        rule_drift=state.get('rule_drift'), pending_merge_note=state.get('pending_merge_note'),
        workflow_issues_open=[key for key, value in issues.items() if value == 'open']))
