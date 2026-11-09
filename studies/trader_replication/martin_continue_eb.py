"""EB: identify exactly where EA full/cut leader membership differs."""
import json
from pathlib import Path

from studies.trader_replication.martin_continue_dq import ROOT, sha


def summarize(full, cut):
    codes = full['codes']
    if codes != cut['codes'] or set(full['audit']) != set(cut['audit']):
        raise ValueError('EA axes differ')
    rows = []
    for day in sorted(full['audit']):
        a, b = full['audit'][day], cut['audit'][day]
        ha, hb = set(a['all']['holding']), set(b['all']['holding'])
        if ha == hb:
            continue
        ca = {row[0]: row[1] for row in a['all']['candidates']}
        cb = {row[0]: row[1] for row in b['all']['candidates']}
        sa = {row[0]: row[1] for row in a['spaced']['candidates']}
        sb = {row[0]: row[1] for row in b['spaced']['candidates']}
        diff = []
        for j in sorted(ha ^ hb):
            diff.append({'code': codes[j], 'full_h3': j in ha, 'cut_h3': j in hb,
                         'full_candidate': ca.get(j), 'cut_candidate': cb.get(j),
                         'full_spaced': sa.get(j), 'cut_spaced': sb.get(j)})
        rows.append({'date': day, 'differences': diff})
    return rows


def main():
    root = ROOT / 'studies/trader_replication/reports/gap_review'
    full_path, cut_path = root / 'strong_continue_ea_full.json', root / 'strong_continue_ea_cut.json'
    full, cut = json.loads(full_path.read_text()), json.loads(cut_path.read_text())
    if cut['full_sha256'] != sha(full_path) or cut['script_sha256'] != full['script_sha256']:
        raise ValueError('EA fingerprints differ')
    rows = summarize(full, cut)
    if len(rows) != cut['cutoff_differences']['all'].get('holding', 0):
        raise AssertionError('EA holding count differs')
    result = {'ea_full_sha256': sha(full_path), 'ea_cut_sha256': sha(cut_path),
              'script_sha256': sha(Path(__file__)), 'dates': len(rows), 'rows': rows}
    target = root / 'strong_continue_eb.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    print('wrote', target, 'dates', len(rows))


if __name__ == '__main__':
    main()
