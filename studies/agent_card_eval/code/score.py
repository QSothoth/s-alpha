"""Score one harness's card decisions against the replayed outcomes (study agent_card_eval, A1 rules).

    python3 -m studies.agent_card_eval.code.score --cards <cards dir> --raw <raw dir> [--out result.json]

The per-card decision is the majority of the repetitions; an invalid answer counts as SKIP.
Compared with taking every card (the rule alone) and with random subsets of the same size.
"""
import argparse
import json
import random
import statistics
from collections import Counter, defaultdict
from pathlib import Path

RANDOM_DRAWS = 10000
BOOTSTRAP_DRAWS = 2000
PASS_P = 0.10


def _side(pnls):
    wins, losses = [x for x in pnls if x > 0], [-x for x in pnls if x < 0]
    return {'n': len(pnls), 'total_usd': sum(pnls), 'expectancy_usd': statistics.mean(pnls) if pnls else None,
            'win_rate': len(wins) / len(pnls) if pnls else None,
            'payoff_ratio': statistics.mean(wins) / statistics.mean(losses) if wins and losses else None}


def score(cards_dir, raw_dir, seed=20261002, skip_lowest=None):
    outcomes = {o['card_id']: o for o in map(json.loads, (Path(cards_dir) / 'outcomes.jsonl').read_text(encoding='utf-8').splitlines())}
    calls = defaultdict(list)
    for path in sorted(Path(raw_dir).glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        calls[record['card_id']].append(record)
    missing = sorted(set(outcomes) - set(calls))
    if missing:
        raise SystemExit('cards without answers: %s' % missing)
    ids = sorted(outcomes)
    pnl = {i: outcomes[i]['pnl_usd_at_budget'] for i in ids}
    take, stable, invalid = {}, 0, 0
    if skip_lowest is None:
        for i in ids:
            votes = [r['decision'] or 'SKIP' for r in calls[i]]
            invalid += sum(r['decision'] is None for r in calls[i])
            take[i] = Counter(votes)['TAKE'] * 2 > len(votes)
            stable += len(set(r['decision'] for r in calls[i])) == 1 and calls[i][0]['decision'] is not None
    else:  # A2 B2: rank by the mean probability (invalid answers count as 0), skip the lowest share
        mean_p = {}
        for i in ids:
            ps = [r.get('p_big_win') for r in calls[i]]
            invalid += sum(p is None for p in ps)
            mean_p[i] = sum(p or 0.0 for p in ps) / len(ps)
        skipped = set(sorted(ids, key=lambda i: (mean_p[i], i))[:int(skip_lowest * len(ids))])
        take = {i: i not in skipped for i in ids}
        stable = sum(max(r.get('p_big_win') or 0 for r in calls[i]) - min(r.get('p_big_win') or 0 for r in calls[i]) <= 0.05
                     for i in ids)
    taken = [i for i in ids if take[i]]
    agent_total = sum(pnl[i] for i in taken)
    all_total = sum(pnl.values())
    rng = random.Random(seed)
    values = list(pnl.values())
    ge = sum(sum(rng.sample(values, len(taken))) >= agent_total for _ in range(RANDOM_DRAWS))
    days = defaultdict(list)
    for i in ids:
        days[outcomes[i]['trade_date']].append(i)
    names = sorted(days)
    diffs = []
    for _ in range(BOOTSTRAP_DRAWS):
        pick = [i for _ in names for i in days[rng.choice(names)]]
        diffs.append(sum(pnl[i] for i in pick if take[i]) - sum(pnl[i] for i in pick))
    diffs.sort()
    records = [r for rs in calls.values() for r in rs]
    usage = [r['usage'] or {} for r in records]
    p_random = (ge + 1) / (RANDOM_DRAWS + 1)
    return {
        'cards': len(ids), 'calls': len(records), 'reps_per_card': sorted(Counter(len(v) for v in calls.values())),
        'invalid_answers': invalid, 'stable_cards': stable, 'stable_share': stable / len(ids),
        'take_rate': len(taken) / len(ids),
        'agent': _side([pnl[i] for i in taken]), 'take_all': _side(values),
        'skipped': _side([pnl[i] for i in ids if not take[i]]),
        'agent_minus_take_all_usd': agent_total - all_total,
        'bootstrap_by_day_95': [diffs[int(0.025 * (len(diffs) - 1))], diffs[int(0.975 * (len(diffs) - 1))]],
        'p_vs_random_same_size': p_random,
        'passed': agent_total > all_total and p_random <= PASS_P,
        'mean_input_tokens': statistics.mean(u.get('input_tokens', 0) for u in usage),
        'mean_output_tokens': statistics.mean(u.get('output_tokens', 0) for u in usage),
        'mean_seconds': statistics.mean(r['seconds'] for r in records),
        'cost_usd': sum(r['cost_usd'] or 0 for r in records),
        'decisions': {i: {'take': take[i], 'votes': [r['decision'] for r in calls[i]],
                          'p_big_win': [r.get('p_big_win') for r in calls[i]], 'pnl_usd': pnl[i],
                          'symbol': outcomes[i]['symbol'], 'trade_date': outcomes[i]['trade_date']} for i in ids},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--cards', required=True)
    parser.add_argument('--raw', required=True)
    parser.add_argument('--out')
    parser.add_argument('--skip-lowest', type=float, default=None, help='A2 B2: skip this share of cards with the lowest p_big_win')
    args = parser.parse_args(argv)
    result = score(args.cards, args.raw, skip_lowest=args.skip_lowest)
    text = json.dumps(result, indent=2, ensure_ascii=False) + '\n'
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'decisions'}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
