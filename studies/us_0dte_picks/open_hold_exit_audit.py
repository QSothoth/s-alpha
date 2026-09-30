"""Read-only, case-at-a-time diagnostics of the registered open_hold_v3."""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from custody.dataset import Dataset, sha256_file
from custody.evaluate import PRIMARY_FILL, _plain, simulate
from custody.registry import Registry
from custody.strategy import build_strategy, session_minute


def audit(dataset_path, reference_path):
    dataset = Dataset(dataset_path)
    item = Registry().get('open_hold_v3')
    reference = json.loads(Path(reference_path).read_text())
    if reference['dataset']['checksums_sha256'] != dataset.fingerprint:
        raise ValueError('reference dataset fingerprint differs')
    if reference['strategy']['sha256'] != item['sha256']:
        raise ValueError('reference strategy fingerprint differs')
    expected = {(r['contract'], r['trade_date']): r for r in reference['cases']}
    if set(expected) != {case.key for case in dataset.cases}:
        raise ValueError('reference cases differ')
    rows = []
    for case in dataset.cases:
        data = dataset.load(case)
        engine = build_strategy(item, case.direction, data.session, case.strike)
        trade = simulate(data, engine, item['config']['params'])
        old = expected[case.key]
        if (_plain(trade['entry']) != old['entry'] or _plain(trade['exit']) != old['exit']
                or abs(trade['net_return'] - old['net_return']) > 0.000001):
            raise ValueError('registered replay mismatch: ' + case.contract)
        entry, exit_ = trade['entry'], trade['exit']
        paid = entry['price']
        fee = 2 * PRIMARY_FILL.fee_per_contract / PRIMARY_FILL.multiplier
        marks = {session_minute(data.session, b.close_time):
                 (PRIMARY_FILL.sell(b) - paid - fee) / paid for b in data.option}
        # Exclude entry minute; do not use any observations after actual exit.
        held = [v for m, v in marks.items()
                if entry['fill_minute'] + PRIMARY_FILL.delay_minutes <= m <= exit_['fill_minute']]
        peak = max(held) if held else None
        signal_close = data.underlying[exit_['minute'] - 1].close
        model = engine._premium(engine.sign * signal_close, exit_['minute']) / engine.entry_value - 1
        rows.append(dict(contract=case.contract, trade_date=case.trade_date,
                         entry_reason=entry['reason'], exit_reason=exit_['reason'],
                         net_return=trade['net_return'], model_return_at_signal=model,
                         marked_net_at_signal=marks.get(exit_['minute']),
                         held_peak_net_return=peak,
                         giveback=None if peak is None else peak - trade['net_return'],
                         hold_minutes=trade['hold_minutes']))
        dataset._tapes.clear()  # Bound cached tapes to one case, not the full dataset.
    def summary(group):
        marked = [r for r in group if r['marked_net_at_signal'] is not None]
        givebacks = [r['giveback'] for r in group if r['giveback'] is not None]
        return dict(n=len(group), mean_net_return=mean(r['net_return'] for r in group),
                    loss_90_count=sum(r['net_return'] <= -0.9 for r in group),
                    negative_count=sum(r['net_return'] < 0 for r in group),
                    mean_model_return_at_signal=mean(r['model_return_at_signal'] for r in group),
                    marked_signal_count=len(marked),
                    median_model_minus_marked_net=(median(r['model_return_at_signal'] - r['marked_net_at_signal']
                                                         for r in marked) if marked else None),
                    median_giveback=median(givebacks) if givebacks else None,
                    positive_peak_then_loss=sum(r['held_peak_net_return'] is not None
                                               and r['held_peak_net_return'] > 0 and r['net_return'] < 0 for r in group))
    grouped = {}
    for field in ('entry_reason', 'exit_reason'):
        groups = defaultdict(list)
        for row in rows:
            groups[row[field]].append(row)
        grouped[field] = {key: summary(group) for key, group in sorted(groups.items())}
    return dict(scope='exposed_0dte_training_diagnostic_only', dataset=dataset.name,
                dataset_sha256=dataset.fingerprint, strategy_sha256=item['sha256'],
                source_sha256=sha256_file(__file__), reference_replay_matched=len(rows),
                summary=summary(rows), groups=grouped, cases=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', default='data/custody-0dte-v6.1')
    parser.add_argument('--reference', default='reports/open_hold_v3/custody-0dte-v6.1/report.json')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = audit(args.dataset, args.reference)
    with Path(args.out).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
