"""Run the four frozen R27 candidates through the official CLI in isolation.

python3 -m studies.us_0dte_picks.r27 --out studies/us_0dte_picks/reports/R27
Only the registered development Release is used. No quotes, broker, or held-out tapes.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile

from custody.evaluate import composite_score, summarize

ROOT = Path(__file__).resolve().parents[2]
BASE = 'zero_dte_timing_v6.6'
CHANGES = {
    'C2': {'entry_confirm_minutes': 2},
    'C3': {'entry_confirm_minutes': 3},
    'S2': {'entry_confirm_minutes': 2, 'min_breakout_volume_ratio': 1.0, 'min_close_location': 0.75},
    'S3': {'entry_confirm_minutes': 3, 'min_breakout_volume_ratio': 1.0, 'min_close_location': 0.75},
}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def metrics(rows, hit_rate=0.5):
    summary = summarize(rows, rows, hit_rate)
    return composite_score(summary)['score'], summary


def selection(reports, candidates=CHANGES, round_name='R27'):
    base = reports['V6.6']
    rows = {key: report['cases'] for key, report in reports.items()}
    keys = [(r['contract'], r['trade_date']) for r in rows['V6.6']]
    if any([(r['contract'], r['trade_date']) for r in rs] != keys for rs in rows.values()):
        raise ValueError('case alignment differs')
    days = sorted({r['trade_date'] for r in rows['V6.6']})
    by_day = {day: [i for i, r in enumerate(rows['V6.6']) if r['trade_date'] == day] for day in days}
    folds, held = [], []
    for day in days:
        train = {key: [r for r in rs if r['trade_date'] != day] for key, rs in rows.items()}
        scores = {key: (metrics(rs)[0], metrics(rs, 0.6)[0]) for key, rs in train.items()}
        eligible = []
        for key in candidates:
            bal = metrics(train[key])[1]['balanced']
            if (scores[key][0] > scores['V6.6'][0] and scores[key][1] > scores['V6.6'][1]
                    and (bal['payoff_ratio'] or 0) >= 2 and (bal['profit_factor'] or 0) > 1):
                eligible.append(key)
        chosen = max(eligible, key=lambda key: scores[key][0]) if eligible else 'V6.6'
        held.extend(rows[chosen][i] for i in by_day[day])
        folds.append({'day': day, 'chosen': chosen, 'training_scores': scores})

    rng = random.Random(20261014)
    differences = {key: [] for key in candidates}
    for _ in range(1000):
        idx = [i for _ in days for i in by_day[rng.choice(days)]]
        control = metrics([rows['V6.6'][i] for i in idx])[0]
        for key in candidates:
            differences[key].append(metrics([rows[key][i] for i in idx])[0] - control)
    intervals = {key: [sorted(v)[int(q * (len(v) - 1))] for q in (0.025, 0.975)]
                 for key, v in differences.items()}
    candidate_results = {}
    for key in candidates:
        report = reports[key]
        checks = report['gates_in_sample']
        qualified = (report['prefix_consistency']['passed'] and all(v is True for v in checks.values())
                     and report['score']['strategy']['score'] > base['score']['strategy']['score']
                     and report['score']['strategy_hit_0.6']['score'] > base['score']['strategy_hit_0.6']['score']
                     and intervals[key][0] > 0)
        candidate_results[key] = {
            'verdict': report['verdict'], 'qualified': qualified,
            'failed_or_unavailable_gates': [k for k, v in checks.items() if v is not True],
            'score': report['score']['strategy']['score'],
            'score_hit_0.6': report['score']['strategy_hit_0.6']['score'],
            'score_difference_95': intervals[key],
        }
    ranking = sorted(candidates, key=lambda key: (len(candidate_results[key]['failed_or_unavailable_gates']),
                                               -candidate_results[key]['score']))
    winner = next((key for key in ranking if candidate_results[key]['qualified']), None)
    return {'round': round_name, 'dataset': base['dataset'], 'candidates': candidate_results,
            'ranking': ranking, 'winner': winner, 'folds': folds,
            'fold_choices': dict(Counter(f['chosen'] for f in folds)),
            'cross_selected_held_days': metrics(held)[1],
            'cross_selected_score': metrics(held)[0],
            'caveat': 'Repeatedly used development data; simplified leave-one-day selection, not nested full gates or independent validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source_registry = ROOT / 'custody/strategies'
    baseline_config = json.loads((source_registry / (BASE + '.json')).read_text())
    reports = {}
    with tempfile.TemporaryDirectory(prefix='custody-r27-') as temporary:
        work = Path(temporary)
        shutil.copytree(ROOT / 'custody', work / 'custody', ignore=shutil.ignore_patterns('__pycache__'))
        registry = work / 'custody/strategies'
        index = json.loads((registry / 'index.json').read_text())
        ids = {'V6.6': BASE}
        for key, changes in CHANGES.items():
            config = json.loads(json.dumps(baseline_config))
            sid = 'zero_dte_timing_r27_' + key.lower()
            config.update(strategy_id=sid, description='R27 ' + key + '：连续完整信号确认研究候选')
            config['developed_on']['sessions_through'] = '2026-10-14'
            config['params'].update(changes)
            write_json(registry / (sid + '.json'), config)
            digest = hashlib.sha256((registry / (sid + '.json')).read_bytes()).hexdigest()
            index['strategies'][sid] = {'file': sid + '.json', 'sha256': digest, 'status': 'candidate'}
            write_json(out / (key + '_config.json'), config)
            ids[key] = sid
        write_json(registry / 'index.json', index)
        for key, sid in ids.items():
            dest = out / key
            command = [sys.executable, '-m', 'custody', 'evaluate', '--strategy', sid,
                       '--dataset', str(ROOT / 'data/custody-0dte-v6.1'), '--out', str(dest)]
            print('Evaluating ' + key, flush=True)
            with (out / (key + '_cli.log')).open('w') as log:
                result = subprocess.run(command, cwd=work, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode not in (0, 1) or not (dest / 'report.json').exists():
                raise RuntimeError('evaluation failed: ' + str(out / (key + '_cli.log')))
            reports[key] = json.loads((dest / 'report.json').read_text())
            print(key + ': ' + reports[key]['verdict'], flush=True)
            write_json(out / (key + '_command.json'), {'argv': command, 'isolated_registry': True,
                                                       'returncode': result.returncode})
    # Whole old baseline report must remain identical, not just its aggregate score.
    old = json.loads((ROOT / 'reports' / BASE / 'custody-0dte-v6.1/report.json').read_text())
    if reports['V6.6'] != old:
        raise AssertionError('V6.6 report changed')
    result = selection(reports)
    result['baseline_report_unchanged'] = True
    result['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (Path(__file__).resolve(), ROOT / 'custody/engines/zero_dte_timing.py',
                                         ROOT / 'studies/us_0dte_picks/notes/R27_PREREG.md')}
    write_json(out / 'selection.json', result)
    print(json.dumps({'winner': result['winner'], 'candidates': result['candidates']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
