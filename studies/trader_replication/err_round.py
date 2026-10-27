"""ERR rounds (PREREG_ERR15_20261027_CN.md rules): sourced errors for each candidate; chosen = smallest max error among
those beating the same-pool random median, carried only when it beats the base.  usage: python -m studies.trader_replication.err_round ERR2 [who...]"""
import collections, csv, datetime as dt, json, os, sys
import numpy as np
RD = 'studies/trader_replication/rounds_err'
name = sys.argv[1]; spec = json.load(open(f'{RD}/{name}.json'))
who = sys.argv[2:] or list(spec)
P = f'{RD}/{name.lower()}_result.json'
out = json.load(open(P)) if os.path.exists(P) else {}
def save(): json.dump(out, open(P, 'w'), indent=1, default=float)
def rel(o, h):
    if o is None: return 1.0
    if isinstance(h, (tuple, list)):
        h = h[0] if o < h[0] else h[1] if o > h[1] else o
    return abs(o / h - 1) if o * h > 0 else 1.0
def deep(base, ch):
    c = json.loads(json.dumps(base))
    for k, v in ch.items():
        if isinstance(v, dict) and isinstance(c.get(k), dict): c[k].update(v)
        else: c[k] = v
    return c
def base_of(ST, s):
    return json.loads(json.dumps(s['base_cfg'])) if 'base_cfg' in s else ST.config(s['base'])
SEL = ('2024-01-02', '2025-12-31'); V = ('2026-01-02', '2026-10-16')
wk = lambda d: dt.date.fromisoformat(d[:10]).isocalendar()[:2]
def worst_day(curve):
    c = np.asarray(curve); r = c[1:] / c[:-1] - 1
    return float(-r.min()) if len(r) else None
def goal_study(key, ST, s, his_ret, his_beh):
    base = base_of(ST, s)
    if base.get('data'): ST.data_tag = base['data']
    A = ST.arrays('us'); res = {}
    for k, ch in s['cands'].items():
        cfg = deep(base, ch)
        entries, rules, mask, pool = ST.build(A, cfg)
        st, tr = ST.run(A, entries, SEL, pool, rules, placebo=20, audit=True)
        b, p = dict(st.get('goal_behaviour', {})), st.get('periods', {})
        if 'worst_day' in his_beh: b['worst_day'] = worst_day(st.get('_curve', []))
        err = {f'ret {n}': abs((1 + p[n]) / (1 + h) - 1) for n, h in his_ret.items() if p.get(n) is not None}
        err.update({m: rel(b.get(m), h) for m, h in his_beh.items()})
        st26, tr26 = ST.run(A, entries, V, pool, rules, placebo=20, audit=True)
        res[k] = dict(cfg=cfg, change=ch, periods={n: round(v, 3) for n, v in p.items() if v is not None},
                      beh={m: round(v, 4) for m, v in b.items() if v is not None}, err={m: round(v, 3) for m, v in err.items()},
                      maxerr=round(max(err.values()), 3), total=round(st['total'], 3), maxdd=round(st['maxdd'], 3),
                      placebo=round(st['placebo']['median'], 3), beats=bool(st['total'] > st['placebo']['median']),
                      y2026=dict(total=round(st26['total'], 3), placebo=round(st26['placebo']['median'], 3), n=len(tr26)))
        print(key, k, json.dumps({x: res[k][x] for x in ('err', 'maxerr', 'periods', 'beats', 'y2026')}), flush=True)
    return res
for key in who:
    s = spec[key]
    if key == 'evan':
        from studies.evan_medeiros.replicate import STUDY as E
        res = goal_study(key, E, s, {'2024': .2045, '2025-01..08': .0503}, dict(per_year=328, win=.6376, avg_win=.0229, avg_loss=-.0229 / .81, days=4))
    elif key == 'sam':
        from studies.sam_miesse.replicate import STUDY as S
        res = goal_study(key, S, s, {'2024': 1.0}, dict(per_year=(400, 1250), worst_day=(.13, .23)))
    elif key == 'karl':
        from studies.karl_domm.replicate import STUDY as K
        base = base_of(K, s); h = K.HIS_2025; res = {}
        for k, ch in s['cands'].items():
            cfg = dict(base, **ch)
            st, tr = K.evaluate(cfg, ('2025-01-02', '2025-12-31'), draws=6)
            st26, _ = K.evaluate(cfg, V)
            dist = [(abs(t['Kc'] / t['S0'] - 1) + abs(t['Kp'] / t['S0'] - 1)) / 2 for t in tr if t.get('Kc') and t.get('S0')]
            err = {'ret 2025': abs((1 + st['total']) / (1 + h['ret']) - 1), 'per_year': rel(st['trades'], h['per_year']),
                   'win': rel(st['win'], h['win']), 'hold': rel(st['hold'], h['hold'])}
            if s.get('strike_target'):
                err['strike'] = rel(float(np.median(dist)) if dist else None, tuple(s['strike_target']))
            res[k] = dict(cfg=cfg, change=ch, total=round(st['total'], 3), n=st['trades'], win=round(st['win'], 3), hold=round(st['hold'], 2),
                          strike_med=round(float(np.median(dist)), 3) if dist else None, err={m: round(v, 3) for m, v in err.items()},
                          maxerr=round(max(err.values()), 3), placebo=round(st['placebo']['median'], 3), beats=bool(st['total'] > st['placebo']['median']),
                          y2026=dict(total=round(st26['total'], 3), n=st26['trades']))
            print(key, k, json.dumps({x: res[k][x] for x in ('err', 'maxerr', 'total', 'strike_med', 'beats', 'y2026')}), flush=True)
    elif key == 'hol':
        from studies.alfredo_holguin.replicate import STUDY as H
        base = base_of(H, s); res = {}
        his = dict(ret=.56, win=.898, per_week=16.6, names_per_week=12.7, per_name_week=1.31)
        for k, ch in s['cands'].items():
            cfg = dict(base, **ch)
            st, tr = H.evaluate(cfg, ('2025-01-02', '2025-12-31'), draws=10)
            g = collections.Counter((t['code'], wk(t['entry'])) for t in tr); weeks = len({wk(t['entry']) for t in tr}) or 1
            b = dict(win=st['win'], per_week=len(tr) / weeks, names_per_week=len(g) / weeks, per_name_week=len(tr) / max(len(g), 1))
            err = {'ret 2025': abs((1 + st['total']) / (1 + his['ret']) - 1)}
            err.update({m: rel(b[m], his[m]) for m in b})
            st26, tr26 = H.evaluate(cfg, ('2026-01-02', '2026-05-29'), draws=10)
            g26 = collections.Counter((t['code'], wk(t['entry'])) for t in tr26); w26 = len({wk(t['entry']) for t in tr26}) or 1
            res[k] = dict(cfg=cfg, change=ch, total=round(st['total'], 3), beh={m: round(v, 3) for m, v in b.items()},
                          err={m: round(v, 3) for m, v in err.items()}, maxerr=round(max(err.values()), 3),
                          placebo=round(st['placebo']['median'], 3), beats=bool(st['total'] > st['placebo']['median']),
                          y2026=dict(total=round(st26['total'], 3), placebo=round(st26['placebo']['median'], 3), per_week=round(len(tr26) / w26, 1),
                                     names_per_week=round(len(g26) / w26, 1), his=dict(ret=.445, per_week=23.5, names_per_week=17.0)))
            print(key, k, json.dumps({x: res[k][x] for x in ('err', 'maxerr', 'total', 'beats', 'y2026')}), flush=True)
    ref = s['ref']
    ok = [k for k in res if res[k]['beats']]
    best = min(ok, key=lambda k: res[k]['maxerr']) if ok else ref
    chosen = best if res[best]['maxerr'] < res[ref]['maxerr'] else ref
    out[key] = dict(results=res, ref=ref, chosen=chosen, meets=bool(res[chosen]['maxerr'] <= .15 and res[chosen]['beats']))
    print(key, 'CHOSEN', chosen, res[chosen]['maxerr'], 'meets', out[key]['meets'], flush=True); save()
print('exit 0')
