"""Descriptive runs around S9 (no decision depends on the breakdown / weekday / custody parts).

    python3 studies/us_preopen_bias/code/s9_describe.py explore    > reports/s7_attention_explore_select_raw.txt
    python3 studies/us_preopen_bias/code/s9_describe.py breakdown  > reports/q2_breakdown_raw.txt
    python3 studies/us_preopen_bias/code/s9_describe.py custody    > reports/q2_custody_l2_raw.txt
    python3 studies/us_preopen_bias/code/s9_describe.py s10        > reports/s10_aux_raw.txt
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preopen  # noqa: E402
import signals  # noqa: E402

SELECT = (['data/preopen-us-train-v1', 'data/preopen-us-valid-v1', 'data/preopen-us-ext30-select-v1'], '2023-08-01', '2026-09-23')
HOLDOUT = (['data/preopen-us-holdout-2016-v1', 'data/preopen-us-train-v1', 'data/preopen-us-ext30-holdout-v1'],
           '2020-02-03', '2023-07-31')


def rows_of(seg):
    dirs, a, b = seg
    return preopen.build(preopen.load(dirs), a, b)


def show(title, sel):
    if not sel:
        print(title, 'none')
        return
    print('%-44s n=%5d down=%5.1f%% mean_oc=%+6.1fbp' % (title, len(sel), 100 * mean(r['y']['down'] for r in sel),
                                                        1e4 * mean(r['y']['ret_oc'] for r in sel)))


def explore():
    """Disclosed exploration after S7 on the selection segment only."""
    rows = rows_of(SELECT)
    show('all', rows)
    for thr in (0.25, 0.5, 1.0):
        for lab, grp in (('single', lambda r: not r['f']['is_index']), ('index', lambda r: r['f']['is_index'])):
            sel = [r for r in rows if grp(r) and r['f']['ah_z'] is not None and abs(r['f']['ah_z']) >= thr]
            show('|ah_z|>=%.2f %s' % (thr, lab), sel)
            show('   ah up', [r for r in sel if r['f']['ah_z'] > 0])
            show('   ah down', [r for r in sel if r['f']['ah_z'] < 0])
            show('   first half (<2025-02)', [r for r in sel if r['date'] < '2025-02-01'])
            show('   second half', [r for r in sel if r['date'] >= '2025-02-01'])
    for thr in (1.0, 2.0):
        show('|gap_z|>=%.1f single' % thr, [r for r in rows if not r['f']['is_index'] and r['f']['gap_z'] is not None
                                            and abs(r['f']['gap_z']) >= thr])
    show('pm_ratio>=3 single', [r for r in rows if not r['f']['is_index'] and r['f']['pm_ratio'] is not None
                                and r['f']['pm_ratio'] >= 3])


def breakdown():
    for label, seg in (('selection 2023-08..2026-09', SELECT), ('holdout 2020-02..2023-07', HOLDOUT)):
        sig = [r for r in rows_of(seg) if signals.q2_ah_attention_short_strong(r['f'])]
        print('==', label, 'n', len(sig), 'down %.1f%%' % (100 * mean(r['y']['down'] for r in sig)))
        groups = defaultdict(list)
        for r in sig:
            groups['ah up' if r['f']['ah_z'] > 0 else 'ah down'].append(r)
            groups['year ' + r['date'][:4]].append(r)
            groups['gap agrees with ah' if (r['f']['gap'] > 0) == (r['f']['ah_z'] > 0) else 'gap reversed ah'].append(r)
            groups['sym ' + r['symbol']].append(r)
        for k in sorted(groups):
            g = groups[k]
            print('   %-22s n=%4d down=%5.1f%% mean_oc=%+7.1fbp' % (k, len(g), 100 * mean(r['y']['down'] for r in g),
                                                                 1e4 * mean(r['y']['ret_oc'] for r in g)))


def custody():
    rows = preopen.build(preopen.load(SELECT[0]), '2026-08-18', '2026-09-23')
    hits = [(r['date'], r['symbol'], round(r['f']['ah_z'], 2), round(1e4 * r['y']['ret_oc'], 1))
            for r in rows if signals.q2_ah_attention_short_strong(r['f'])]
    print('Q2 signals 2026-08-18..09-23 (date, symbol, ah_z, open->close bp):')
    for h in hits:
        print('  ', h)
    cases = {}
    for strat in ('open_hold_v3', 'zero_dte_timing_v6.6'):
        for ds in ('custody-0dte-v6.1', 'custody-eval-2026-09-18-v2'):
            rep = json.loads(Path('reports/%s/%s/report.json' % (strat, ds)).read_text(encoding='utf-8'))
            for c in rep['cases']:
                cases.setdefault((c['trade_date'], c['symbol'], c['direction']), {})[strat] = (
                    c['net_return'], c['benchmark_net_return'])
    print('custody cases on those sessions (SHORT = PUT):')
    for d, s, _, _ in hits:
        for side in ('SHORT', 'LONG'):
            v = cases.get((d, s, side))
            print('  ', d, s, side, 'no 0DTE case frozen' if not v else
                  {k: tuple(None if x is None else round(100 * x, 1) for x in pair) for k, pair in v.items()})
    print('\nQ2 signals by weekday (count only; 0DTE for single names exists Mon/Wed/Fri in 2026):')
    for label, seg in (('selection 2023-08..2026-09', SELECT), ('holdout 2020-02..2023-07', HOLDOUT)):
        sig = [r for r in rows_of(seg) if signals.q2_ah_attention_short_strong(r['f'])]
        c = Counter(r['f']['weekday'] for r in sig)
        print('  %-28s n=%d  Mon %d Tue %d Wed %d Thu %d Fri %d  -> Mon/Wed/Fri share %.0f%%' % (
            label, len(sig), c[0], c[1], c[2], c[3], c[4], 100 * (c[0] + c[2] + c[4]) / len(sig)))




def s10_aux():
    """S10 auxiliary reports (do not change the S10 verdict): K1 by stock / ETF on the new names, and 16 + 40 pooled."""
    import evaluate as ev
    types = json.loads((Path(__file__).resolve().parents[1] / 'notes' / 's10_security_types.json').read_text())
    rows = preopen.build(preopen.load(['data/preopen-us-xsec-v1']), '2025-10-22', '2026-09-23')
    for kind in ('STOCK', 'ETF'):
        sub = [r for r in rows if types[r['symbol']] == kind]
        print(ev.fmt('K1 new %s (%d names)' % (kind, len({r['symbol'] for r in sub})), ev.score(sub, signals.k1_retail_flow_fade)))
    old = preopen.build(preopen.load(['data/preopen-us-train-v1', 'data/preopen-us-valid-v1']), '2025-10-22', '2026-09-23')
    print(ev.fmt('K1 pooled 16 + 40', ev.score(old + rows, signals.k1_retail_flow_fade)))
    singles = [r for r in old if not r['f']['is_index']] + [r for r in rows if types[r['symbol']] == 'STOCK']
    print(ev.fmt('K1 pooled single stocks', ev.score(singles, signals.k1_retail_flow_fade)))


if __name__ == '__main__':
    {'explore': explore, 'breakdown': breakdown, 'custody': custody, 's10': s10_aux}[sys.argv[1]]()
