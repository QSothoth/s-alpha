"""Read-only signal audit on existing frozen data, one system per process."""
import json
import resource
import subprocess
import sys

resource.setrlimit(resource.RLIMIT_AS, (1800 * 1024**2, 1800 * 1024**2))
import numpy as np
from studies import trader_data as TD
from studies.trader_screens import screens as S
from studies.trader_replication import systems, panels, compare

sid = sys.argv[1]
if sid not in ('marios_stamatoudis', 'oliver_kell', 'christian_flanders'):
    raise SystemExit('Choose marios_stamatoudis, oliver_kell or christian_flanders')
p = TD.panel.build(TD.frozen('us'), write_cache=False)
if p['digest'] != panels.pinned()['markets']['us']:
    raise SystemExit('Frozen US data digest does not match DATA_PIN.json')
F = S.Feat(p, 'us')
A = dict(days=p['days'], codes=p['codes'], market='us', F=F, open=F.o, high=F.h, low=F.l, close=F.c,
         turnover=F.turnover, raw=F.raw, volume=F.v, to20=F.to20, adr=F.adr, has=F.has, digest=p['digest'])
del p
x = systems.get(sid)
entries, rules, mask, pool = x.study.build(A, x.config)
total, bad, examples = 0, 0, []
for d, row in enumerate(entries):
    if not '2024-01-02' <= A['days'][d] <= '2026-10-16':
        continue
    for e in row:
        if e[2] < 0:
            continue
        total += 1
        j = e[1]
        outside = not pool[d, j] if sid == 'marios_stamatoudis' else (
            e[5] in ('pop', 'cross') and F.to20[d - 1, j] < 100e6)
        if outside:
            bad += 1
            if len(examples) < 5:
                examples.append(dict(day=str(A['days'][d]), code=str(A['codes'][j]), kind=e[5],
                                     turnover_prev=float(F.to20[d-1,j]), raw_prev=float(F.raw[d-1,j]),
                                     adr_prev=float(F.adr[d-1,j]), price=e[3]))
result = dict(commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              code_digest=compare.code_digest(), config_digest=compare.config_digest(x.config),
              dataset=TD.DEFAULT_TAG, data_digest=A['digest'], numpy=np.__version__,
              window=list(panels.WINDOW), system=sid, config=x.config,
              offered_long_entries=total, outside=bad, examples=examples)
if sid == 'christian_flanders':
    cfg = dict(x.config, pool=dict(x.config['pool'], adr=999))
    orig = x.study.base.setups(A, x.config)['hi52'][0]
    impossible = x.study.base.setups(A, cfg)['hi52'][0]
    result['adr_2_vs_999_masks_equal'] = bool(np.array_equal(orig, impossible))
    result['hi52_signal_count_all_input_dates'] = int(orig.sum())
result['peak_rss_mib'] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
print(json.dumps(result, ensure_ascii=False, indent=2, default=float))
