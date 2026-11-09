"""FR: explain winner windows held by FO1 but missed by the 11-position account."""
from collections import Counter
import json
from pathlib import Path

from studies.trader_replication import martin_continue_du as du
from studies.trader_replication import martin_continue_es as es
from studies.trader_replication import martin_continue_fq as fq
from studies.trader_replication.martin_continue_dq import sha


def overlapping(keys, code, start, end):
    return [t for t in keys if t[0] == code and t[1] > 0 and t[3] <= end and t[4] >= start]


def main():
    root = du.REPORTS
    es_path, fq_path = root / 'strong_continue_es.json', root / 'strong_continue_fq.json'
    base, accounts = json.loads(es_path.read_text()), json.loads(fq_path.read_text())
    if (base['script_sha256'] != sha(Path(es.__file__)) or accounts['script_sha256'] != sha(Path(fq.__file__)) or
            base['dataset_digest'] != accounts['dataset_digest']):
        raise ValueError('ES / FQ source differs')
    windows = base['results']['U1']['windows']
    if len(windows) != 25:
        raise AssertionError('winner window count differs')
    fo_keys, fq_keys = (accounts['results'][n]['trade_keys'] for n in ('FO1', 'FQ1'))
    trace = {(r['day'], r['kind'], r['code']): r for r in accounts['traces']['FQ1']['orders']}
    fq_entries = {(t[3], t[2], t[0]): t for t in fq_keys}
    details = []
    for w in windows:
        start, end, code = w['date'], w['end'], w['code']
        a, b = overlapping(fo_keys, code, start, end), overlapping(fq_keys, code, start, end)
        evidence = []
        if a and not b:
            for t in a:
                key = (t[3], t[2], t[0])
                found = trace.get(key, {'reason': 'not_found'})
                same_entry = fq_entries.get(key)
                if found['reason'] == 'opened' and same_entry is None:
                    raise AssertionError('trace says opened without trade')
                evidence.append({'entry': t[3], 'kind': t[2], 'exit': t[4], 'exit_reason': t[5],
                                 'fq_reason': found['reason'],
                                 'fq_exit': same_entry[4] if same_entry else None,
                                 'fq_exit_reason': same_entry[5] if same_entry else None,
                                 'fq_held_entry': found.get('held_entry')})
        details.append({'date': start, 'end': end, 'code': code, 'fo_held': bool(a),
                        'fq_held': bool(b), 'fo_only_evidence': evidence})
    yearly = {}
    for y in ('2024', '2025', '2026'):
        sample = [x for x in details if x['date'].startswith(y)]
        yearly[y] = {'windows': len(sample), 'fo_held': sum(x['fo_held'] for x in sample),
                     'fq_held': sum(x['fq_held'] for x in sample),
                     'fo_only': sum(x['fo_held'] and not x['fq_held'] for x in sample)}
        for n, key in (('FO1', 'fo_held'), ('FQ1', 'fq_held')):
            if yearly[y][key] != accounts['results'][n]['fidelity']['prepeak_ten_day'][y]['held']:
                raise AssertionError('FQ window count differs ' + n + ' ' + y)
    unique = {(e['entry'], e['kind'], w['code']): e for w in details for e in w['fo_only_evidence']}
    out = {'dataset_digest': accounts['dataset_digest'], 'es_sha256': sha(es_path), 'fq_sha256': sha(fq_path),
           'script_sha256': sha(Path(__file__)), 'years': yearly, 'windows': details,
           'unique_fo_entries': len(unique), 'unique_reasons': dict(Counter(e['fq_reason'] for e in unique.values()))}
    target = root / 'strong_continue_fr.json'
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, flush=True)


if __name__ == '__main__':
    main()
