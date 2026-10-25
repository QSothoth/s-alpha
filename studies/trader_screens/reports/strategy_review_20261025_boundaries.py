"""Synthetic unit characterizations of reviewed boundaries; no market data or writes."""
import json
import math
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np

from studies.trader_replication import system as Y, shorts, systems, runner, compare
from studies.trader_screens import intraday as I, board, scan
from studies.trader_data.live import LiveDataset

OUT = {}
NOCOST = dict(buy_cost=0, sell_cost=0, margin_rate=0, borrow_rate=0)

def px(rows, codes=('US.A',)):
    a = np.asarray(rows, float)
    if a.ndim == 2:
        a = a[:, None, :]
    return dict(zip(('open', 'high', 'low', 'close'), (a[:, :, i] for i in range(4))),
                dates=np.array(['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'][:len(a)]),
                codes=np.array(codes))

def sim(p, rules, entries, ema=None):
    return Y.simulate(p, ema or {}, rules, entries, p['dates'][0], p['dates'][-1], audit=True)

p = px([(10, 10, 10, 10), (13, 13, 9.5, 9.8)])
_, _, tr = sim(p, Y.Rules(trail='', trims=(), breakeven_r=2, **NOCOST), [[(0, 0, 1, 10, 9, 'case')], []])
assert tr[0]['why'] == 'end' and tr[0]['state']['stop'] == 10
OUT['breakeven_after_open_already_above_trigger'] = tr[0]

for name in ('clement_ang', 'qullamaggie', 'marios_stamatoudis'):
    s = systems.get(name)
    r = shorts.short_rules(Y.Rules(**s.config['rule_opts']), s.config['short'], ['s_test'])
    OUT.setdefault('short_inheritance', {})[name] = dict(base_trims=list(r.trims), short_trims=r.short_trims,
                                                        breakeven_r=r.breakeven_r)
    if name == 'clement_ang':
        p = px([(10, 10, 10, 10), (10, 10.2, 7, 8)])
        r = replace(r, buy_cost=0, sell_cost=0, borrow_rate=0, margin_rate=0)
        _, _, tr = sim(p, r, [[(0, 0, -1, 10, 11, 's_test')], []],
                       {'ema20': np.full((2, 1), 20.), 'ema10': np.full((2, 1), 20.),
                        'atr50x8': np.zeros((2, 1), bool)})
        OUT['clement_short_trim_observed'] = tr[0]['executions']
        assert tr[0]['executions'][1]['action'] == 'trim'

p = px([(10, 10, 10, 10), (np.nan, np.nan, np.nan, np.nan)])
A = dict(p, days=p['dates'])
rules = Y.Rules(trail='', trims=(), **NOCOST)
entry = [[(0, 0, 1, 10, 9, 'toy')], []]
st = SimpleNamespace(build=lambda A, cfg: (entry, rules, None, None), ema_inputs=lambda A, pool, rules: {},
                     px=lambda A: p, market_gate=lambda A, cfg: None)
sys_ = SimpleNamespace(study=st, config={}, id='toy', name='toy', version='toy', status='research', label='toy',
                       strategy={}, freeze='2024-01-02')
r = runner.run(sys_, 'us', A=A)
assert np.isfinite(r['account']['ret']) and np.isnan(r['holdings'][0]['close']) and np.isnan(r['account']['exposure'])
OUT['missing_latest_holding'] = dict(holding=r['holdings'][0], account=r['account'],
                                      json_has_nan='NaN' in json.dumps(r))

snap = {'US.A': dict(trading=True, time='2026-10-23 09:30:00')}
OUT['stale_us_snapshot_accepted'] = I.check_time('us', snap, '2026-10-23', datetime(2026, 10, 23, 15, 50, tzinfo=ZoneInfo('America/New_York')))

class NoOverlap:
    @staticmethod
    def history(codes, start, end):
        yield 'US.A', [('US.A', '2026-10-19', 10, 10, 10, 10, 1, 10)], []
rows, acts, check = LiveDataset.from_history(NoOverlap, ['US.A'], '2026-10-16', ['2026-10-19'], {'US.A': 10})
assert check['overlap_checked'] == 0 and len(rows) == 1
OUT['zero_overlap_history_accepted'] = dict(rows=rows, check=check)

class WrongDateSnapshot:
    @staticmethod
    def snapshot(codes):
        return {'US.A': dict(open=10, high=10, low=10, close=10, volume=1, turnover=10,
                             prev_close=10, trading=True, time='2026-10-15 16:00:00')}
rows, acts, check = LiveDataset.from_snapshot(WrongDateSnapshot, ['US.A'], '2026-10-19', {'US.A': ('2026-10-16', 10)})
OUT['wrong_day_official_snapshot_relabelled'] = dict(rows=rows, check=check)
assert rows[0][1] == '2026-10-19'

h = dict(code='US.A', side=-1, stop=11, trail=None, trail_name='', next_trim=None, next_target=None,
         day_trim_pending=False, days=0)
OUT['short_exit_text_omits_time_and_daytrim'] = board.exit_text(h)

current = compare.code_digest()
OUT['reference_provenance'] = dict(current_code=current, systems={})
for s in systems.all_():
    OUT['reference_provenance']['systems'][s.id] = {}
    for m in ('us', 'hk', 'cn'):
        ref = runner.reference(s, m)
        OUT['reference_provenance']['systems'][s.id][m] = None if ref is None else dict(code=ref['run']['code_digest'], same_code=ref['run']['code_digest'] == current)


from unittest.mock import patch
from studies.christian_flanders.replicate import Flanders
dates = np.array(['2026-01-02', '2026-01-05'])
features = SimpleNamespace(c=np.array([[95.], [100.]]), l=np.array([[90.], [80.]]),
                           o=np.array([[92.], [90.]]))
study = Flanders()
config = {'entry': 'close', 'stop_min': .01, 'stop_cap': .06}
mask = np.array([[False], [True]])
with patch.object(study, 'priority', return_value=np.zeros((2, 1))):
    actual_entry = study.entries({'F': features}, config, {'ep': (mask, features.o, features.l)})[1][0]
layer2_entry = study.his_entry({'close': features.c, 'low': features.l}, 1, 0, config)
assert actual_entry[4] == 94 and layer2_entry[4] == 80
px2 = {'open': np.array([[90.], [100.]]), 'high': np.array([[102.], [111.]]),
       'low': np.array([[80.], [99.]]), 'close': np.array([[100.], [110.]]),
       'dates': dates, 'codes': ['TEST']}
exit_rules = Y.Rules(trail='', trims=(), max_days=1, **NOCOST)
result = {}
for name, entry in [('actual', actual_entry), ('layer2', layer2_entry)]:
    _, _, trades = Y.simulate(px2, {}, exit_rules, [[entry], []], dates[0], dates[-1], audit=True)
    result[name] = {k: float(trades[0][k]) for k in ('stop', 'risk_pct', 'ret', 'r')}
assert np.isclose(result['actual']['r'], 10 / 6)
assert np.isclose(result['layer2']['r'], .5)
OUT['second_layer_stop'] = result


traders = [dict(name='A', buys=[dict(code='US.X', day='2026-10-19', side=1)], holdings=[]),
           dict(name='B', buys=[dict(code='US.X', day='2026-10-23', side=1)], holdings=[])]
overlap = scan.overlaps(traders, {})
assert overlap['bought'] == [dict(code='US.X', traders=['A', 'B'], industry='')]

strategy = {k: '' for k in ('选股与形态', '入场与止损', '离场', '仓位与市况')}
def trader(name):
    return dict(id=name, name=name, version='toy', status='research', gate_today=None,
                account=dict(exposure=0, ret=0, maxdd=0), forward=dict(days=0),
                buys=[], sells=[], holdings=[], wanted=[], wanted_n=0, strategy=strategy)
a, b = trader('has_reference'), trader('no_reference')
a['check'] = dict(ok=True)
r = dict(days=1, market='us', last_day='2026-10-23', state=dict(above_ema20=True, above_ema50=True),
         traders=[a,b], common={})
text = board.render(r)
assert '到冻结日的分年收益与比对表全部一致' in text
OUT['overlap_between_different_days'] = overlap['bought']
OUT['reference_coverage_assertion'] = dict(checked=1, total=2, assertion=[s for s in text.splitlines() if '全部一致' in s])

p = dict(open=np.array([[10.],[10.]]), high=np.array([[10.],[10.2]]), low=np.array([[10.],[8.]]),
         close=np.array([[10.],[8.]]), dates=np.array(['2024-01-02','2024-01-03']), codes=np.array(['US.A']))
A = dict(p, to20=np.ones((2,1)), adr=np.full((2,1),20.))
e=[[],[]]
shorts.level_entries(A, 'ptop', np.array([[False],[True]]), None, dict(stop_w=.2),e,at_open=True)
rule=Y.Rules(trail='',trims=(),short_targets=('sma10',),short_target_frac=0,buy_cost=0,sell_cost=0,margin_rate=0)
_,_,tr=Y.simulate(p,{'sma10':np.full((2,1),9.)},rule,e,p['dates'][0],p['dates'][-1],audit=True)
assert tr[0]['why']=='end' and all(x['action']!='target' for x in tr[0]['executions'])
OUT['day0_target_not_managed'] = dict(entry=e[1], trades=tr)


def json_safe(value):
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, (float, np.floating)) and not math.isfinite(value):
        return str(float(value))
    if isinstance(value, np.generic):
        return value.item()
    return value

print(json.dumps(json_safe(OUT), ensure_ascii=False, indent=2, allow_nan=False))
