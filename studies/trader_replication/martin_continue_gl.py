"""GL: inspect both directions of the frozen position-cap comparisons."""
from collections import Counter
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_es as es
from studies.trader_replication import martin_continue_fr as fr
from studies.trader_replication import martin_continue_gk as gk
from studies.trader_replication import system
from studies.trader_replication.martin_continue_dq import sha


PAIRS = (('L0', 'Q0'), ('L1_hit', 'Q1_hit'), ('LA', 'QA'), ('LB', 'QB'))


def explain(trade, start, trace, target_entries):
    key = (trade[3], trade[2], trade[0])
    record = trace.get(key)
    evidence = {'entry': trade[3], 'kind': trade[2], 'exit': trade[4], 'exit_reason': trade[5]}
    if record is None:
        return {**evidence, 'classification': 'not_traced', 'reason': None}
    reason = record['reason']
    evidence.update(reason=reason, limiting=record.get('limiting'))
    if reason == 'opened':
        target = target_entries.get(key)
        if target is None or target[4] >= start:
            raise AssertionError('opened target trade missing or overlaps window')
        evidence.update(classification='same_order_ended_earlier', target_trade=target)
    elif record.get('held_entry'):
        held_key = (record['held_entry'], record['held_kind'], trade[0])
        target = target_entries.get(held_key)
        if target is None or target[4] >= start:
            raise AssertionError('target held trade missing or overlaps window')
        evidence.update(classification='already_held', target_trade=target)
    elif 'rules.max_open and len(pos) >= rules.max_open' in reason:
        evidence['classification'] = 'position_limit'
    elif 'val <= 0.001 * equity' in reason:
        evidence['classification'] = 'budget_or_size'
    elif 'no_rebuy_day' in reason:
        evidence['classification'] = 'same_day_rebuy'
    elif reason.startswith('take:'):
        evidence['classification'] = 'daily_limit_or_guard'
    else:
        evidence['classification'] = 'other_guard'
    return evidence


def main():
    root = du.REPORTS
    es_path, gk_path = root / 'strong_continue_es.json', root / 'strong_continue_gk.json'
    base, accounts = json.loads(es_path.read_text()), json.loads(gk_path.read_text())
    if (base['script_sha256'] != sha(Path(es.__file__)) or
            accounts['script_sha256'] != sha(Path(gk.__file__)) or
            accounts['system_sha256'] != sha(Path(system.__file__)) or
            base['dataset_digest'] != accounts['dataset_digest']):
        raise ValueError('ES / GK source differs')
    windows = base['results']['U1']['windows']
    if len(windows) != 25:
        raise AssertionError('winner window count differs')
    entries, traces = {}, {}
    for name in sum(PAIRS, ()):
        keys = accounts['results'][name]['trade_keys']
        entries[name] = {(t[3], t[2], t[0]): t for t in keys}
        orders = accounts['traces'][name]['orders']
        traces[name] = {(r['day'], r['kind'], r['code']): r for r in orders}
        opened = {(r['day'], r['kind'], r['code']) for r in orders if r['reason'] == 'opened'}
        if len(entries[name]) != len(keys) or len(traces[name]) != len(orders) or opened != set(entries[name]):
            raise AssertionError('trade / trace identity differs: ' + name)
    results = {}
    for left, right in PAIRS:
        details = []
        for w in windows:
            start, end, code = w['date'], w['end'], w['code']
            lt = fr.overlapping(entries[left].values(), code, start, end)
            rt = fr.overlapping(entries[right].values(), code, start, end)
            direction, evidence = None, []
            if bool(lt) != bool(rt):
                source, target, trades = (left, right, lt) if lt else (right, left, rt)
                direction = source + '_only'
                evidence = [explain(t, start, traces[target], entries[target]) for t in trades]
            details.append({'date': start, 'end': end, 'code': code, left: bool(lt), right: bool(rt),
                            'direction': direction, 'evidence': evidence})
        yearly = {}
        for year in ('2024', '2025', '2026'):
            sample = [w for w in details if w['date'].startswith(year)]
            yearly[year] = {'windows': len(sample), left: sum(w[left] for w in sample),
                            right: sum(w[right] for w in sample),
                            left + '_only': sum(w['direction'] == left + '_only' for w in sample),
                            right + '_only': sum(w['direction'] == right + '_only' for w in sample)}
            for n in (left, right):
                if yearly[year][n] != accounts['results'][n]['fidelity']['prepeak_ten_day'][year]['held']:
                    raise AssertionError('window count differs ' + n + ' ' + year)
        directions = {}
        for source in (left, right):
            sample = [w for w in details if w['direction'] == source + '_only']
            unique = {}
            for w in sample:
                for e in w['evidence']:
                    key = (e['entry'], e['kind'], w['code'])
                    if key in unique and unique[key] != e:
                        raise AssertionError('inconsistent repeated order evidence')
                    unique[key] = e
            directions[source + '_only'] = {'windows': len(sample), 'unique_orders': len(unique),
                    'unique_order_reasons': dict(Counter(e['classification'] for e in unique.values()))}
        results[left + '_' + right] = {'years': yearly, 'directions': directions, 'windows': details}
    out = {'dataset_digest': accounts['dataset_digest'], 'es_sha256': sha(es_path), 'gk_sha256': sha(gk_path),
           'script_sha256': sha(Path(__file__)), 'results': results}
    target = root / 'strong_continue_gl.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
