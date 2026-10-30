"""Phase-2 frontier: how much each representative version looks like him (executed trades vs his ledger, +-5 and
+-10 minutes, selection ledger <= 2026-05-31 and validation ledger after) next to its seven quarterly returns.
Report only, never used to choose. Writes reports/frontier.json.

    /opt/opend-us-options/.venv/bin/python -m studies.david_trullas.frontier
"""
import json
import os

from . import engine as E
from .replicate import REPORTS, cfg_of, fidelity, ledger_timed, market, override

VERSIONS = {
    'R6 (clean out-of-sample)': ('r6', {}),
    'R8 (return-chosen)': ('r8', {}),
    'R12: tight entry, far target on the 60-min leg, 80/20': ('r12', {}),
    'M930: MACD 09:00-10:30': ('r8', {'windows': [[540, 630]]}),
    'MDROP60: MACD after a 60-pt open drop': ('r8', {'windows': [[570, 630]], 'macd_drop': 60}),
    'MO930F: MACD + opening patterns, his stops': ('r8', {'trig': 'macd+open', 'windows': [[540, 630]],
                                                          'stop_pts': 15, 'be_at': 0.5}),
    'OPENF: opening patterns only, his stops': ('r8', {'trig': 'open', 'windows': [[540, 630]],
                                                       'stop_pts': 15, 'be_at': 0.5}),
}


def main():
    mk = market()
    sel, val = ledger_timed(hi='2026-05-31'), ledger_timed(lo='2026-06-01')
    out = {}
    for name, (src, over) in VERSIONS.items():
        with open(os.path.join(REPORTS, f'{src}.json'), encoding='utf-8') as f:
            cfg = override(cfg_of(json.load(f)['chosen_cfg']), over)
        row = {'returns': {q: round(E.quarter(mk, cfg, q)[0], 1) for q in E.QUARTERS}}
        for lname, led in (('selection', sel), ('validation', val)):
            for tol in (5, 10):
                f = fidelity(mk, cfg, led, tol)
                row[f'{lname}_tol{tol}'] = dict(hits=f['hits'], n=f['n'], random=f['random_hits'])
                if tol == 5:
                    row[f'{lname}_style'] = {k: f[k] for k in ('time_distance', 'stop_med_pts', 'hold_med', 'win',
                                                                'our_buckets', 'his_buckets')}
        out[name] = row
        r = row
        print(f"{name:44} sel {r['selection_tol5']['hits']}/{r['selection_tol5']['n']} "
              f"(r{r['selection_tol5']['random']}) ±10 {r['selection_tol10']['hits']} (r{r['selection_tol10']['random']}) | "
              f"val {r['validation_tol5']['hits']}/{r['validation_tol5']['n']} (r{r['validation_tol5']['random']}) "
              f"±10 {r['validation_tol10']['hits']} (r{r['validation_tol10']['random']}) | tdist "
              f"{r['validation_style']['time_distance']} stop {r['validation_style']['stop_med_pts']} "
              f"win {r['validation_style']['win']} | " + ' '.join(f"{v:+.0f}" for v in r['returns'].values()))
    with open(os.path.join(REPORTS, 'frontier.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, indent=1, ensure_ascii=False, default=float)


if __name__ == '__main__':
    main()
