import json,sys
d=json.load(open('rounds/WF00/bench.json'))
name=sys.argv[1]
b=d[name]
tr={}
for t in b['attribution']:
    if t.get('leg'): tr.setdefault(t['leg'],[]).append(t)
for g in b['per_leg']:
    if g['year'] not in ('2024','2025') or g['censored']: continue
    st='HELD' if g['peak_held'] else ('early-lost' if g['covered'] else ('late/none'))
    print(f"{g['key']:38s} {g['year']} dur={g['duration']:3d} {st:10s} off={g.get('offset')} pw={g.get('peak_weight')} cap={g.get('capture_total')}")
    for t in tr.get(g['key'],[]):
        ex=' '.join(f"{e['action'][:6]}@{e['time'][5:]}" for e in t['executions'][:6])
        print(f"     {t['kind']:16s} {t['entry']}->{t['exit']} {t['why']:12s} R={t['r']:.2f} riskpct={t['risk_pct']:.3f} | {ex}")
