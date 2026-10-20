"""The generic replication loop of skills/trader-replication, shared by every trader study.

A trader's study module defines a `Study` subclass with its own stage masks and one `build(A, cfg, trace)` that
turns a configuration dict into (entries, rules, signal mask, placebo pool) on a market's daily arrays `A`; rounds
are data (notes/rounds/R*.json).  Everything else is here and the same for everybody:

    round      run notes/rounds/<name>.json: candidates on top of a base configuration, each against same-pool
               random entry, ledger fidelity (signal-day hits and trades actually bought) and his behaviour; the
               choice follows the round's gates and objective and never carries a worse configuration
    diagnose   for each of his dated longs, the furthest step the system reached (signal, stop rule, market
               filter, daily cap, room, bought) and the top trades
    robust     neighbours of the chosen configuration, start-date shifts and doubled costs (reported only)
    final      the configuration in all three markets: years, placebo, equal-weight holding, trade counts
    three      the three-layer replay: his tickers and days with his own results, with our execution, and ours
    score      his behaviour scoreboard: bought / hits, trades per year and day, holding days (winners and losers
               apart), win rate, average win / loss, concentration, start-date spread, returns by year vs his

The A dict holds (days x codes) float arrays 'open', 'high', 'low', 'close', 'to20', 'adr', 'has' and 1-D 'days',
'codes', plus 'market'.  Entries follow system.simulate.  Martin Luk's own studies/martin_luk/replicate.py is the
first case; `studies.trader_replication.martin` adapts it and checks this module against its R74 reports.
"""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import numpy as np

from . import fidelity as F, ledger as L, negations as N, system as Y

STEPS = ('no_signal', 'no_entry', 'market_filter', 'daily_cap', 'no_room', 'traded')
COSTS = {'us': (.0005, .0005), 'hk': (.0016, .0016), 'cn': (.00076, .00126)}
PREFIX = {'us': 'US.', 'hk': 'HK.', 'cn': ''}


def lag(x, n=1):
    """Value n rows earlier (False / NaN on the first rows)."""
    out = np.zeros_like(x) if x.dtype == bool else np.full_like(x, np.nan, dtype=float)
    if n < len(x):
        out[n:] = x[:-n]
    return out


def merged(base, change):
    """A configuration with `change` applied; nested option dicts (rule_opts, ...) are merged one level deep."""
    out = dict(base)
    for k, v in change.items():
        out[k] = dict(base.get(k) or {}, **v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def ew_hold(A, pool, seg, lagged=False):
    """Equal-weight daily-rebalanced holding of the pool names between ISO dates.  lagged=False keeps the
    historical figure, which holds day t's return on names in day t's pool (a pool that reads day t's close is
    look-ahead: it overstates the benchmark); lagged=True uses the pool as of t-1."""
    c = A['close']
    if lagged:
        pool = lag(pool)
    with np.errstate(invalid='ignore', divide='ignore'):
        r = np.where(pool & np.isfinite(lag(c)), c / lag(c) - 1, np.nan)
    m = (A['days'] >= seg[0]) & (A['days'] <= seg[1])
    return float(np.prod(1 + np.nan_to_num(np.nanmean(r[m], axis=1))) - 1)


def year_trades(tr, y):
    t = [x for x in tr if x['entry'][:4] == y]
    win = [x['ret'] for x in t if x['ret'] > 0]
    loss = [x['ret'] for x in t if x['ret'] <= 0]
    return dict(n=len(t), wins=len(win), losses=len(loss), win=len(win) / len(t) if t else None,
                avg_win=float(np.mean(win)) if win else None, avg_loss=float(np.mean(loss)) if loss else None,
                exp_r=float(np.mean([x['r'] for x in t])) if t else None)


def bought(A, tr, located):
    """How many located trades the system actually opened on a day of their window (same stock, long)."""
    ours = {(t['code'], t['entry']) for t in tr if t['side'] > 0}
    return sum(any((str(A['codes'][j]), str(A['days'][d])) in ours for d in range(a, b + 1))
               for _, j, a, b in located)


def behaviour(curve, dates, tr, sessions=None):
    """What his account looks like from the outside: counts, holding days split by winners and losers, win rate,
    average win / loss, and concentration (entry weight of each new position, open positions per day)."""
    n = len(dates)
    years = max(n / 252, 1e-9)
    ret = np.array([t['ret'] for t in tr]) if tr else np.zeros(0)
    win = ret > 0
    out = dict(trades=len(tr), per_year=len(tr) / years, per_day=len(tr) / max(n, 1),
               win=float(win.mean()) if len(ret) else None,
               avg_win=float(ret[win].mean()) if win.any() else None,
               avg_loss=float(ret[~win].mean()) if (~win).any() else None,
               days_win=float(np.mean([t['days'] for t in tr if t['ret'] > 0])) if win.any() else None,
               days_loss=float(np.mean([t['days'] for t in tr if t['ret'] <= 0])) if (~win).any() else None,
               median_days_win=float(np.median([t['days'] for t in tr if t['ret'] > 0])) if win.any() else None,
               median_days_loss=float(np.median([t['days'] for t in tr if t['ret'] <= 0])) if (~win).any() else None)
    if len(ret):
        pos = np.sort(ret[win])[::-1]
        out['top10_share'] = float(pos[:max(1, len(tr) // 10)].sum() / pos.sum()) if win.any() and pos.sum() > 0 \
            else None                         # share of the winners' sum made by the best tenth of all trades
    di = {str(d): i for i, d in enumerate(dates)}
    weights, open_ = [], np.zeros(n)
    for t in tr:
        i0, i1 = di.get(t['entry']), di.get(t['exit'])
        if i0 is None:
            continue
        open_[i0:(i1 if i1 is not None else n)] += 1
        ex = t.get('executions')
        if ex:
            eq = curve[i0 - 1] if i0 > 0 else 1.0
            weights.append(ex[0]['shares'] * ex[0]['price'] / eq)
    if weights:
        out.update(entry_weight_mean=float(np.mean(weights)), entry_weight_max=float(np.max(weights)))
    out['open_mean'] = float(open_.mean()) if n else None
    out['open_max'] = int(open_.max()) if n else None
    return out


def gap(ours, his):
    """Mean absolute log ratio between our behaviour and his, over the measures he published (lower = more like
    him); a win rate counts as the log of the odds ratio."""
    parts = {}
    for k in ('per_year', 'avg_win', 'avg_loss', 'days_win', 'days_loss'):
        a, b = ours.get(k), his.get(k)
        if a is not None and b is not None and a * b > 0:
            parts[k] = abs(float(np.log(abs(a) / abs(b))))
    a, b = ours.get('win'), his.get('win')
    if a is not None and b is not None and 0 < a < 1 and 0 < b < 1:
        parts['win'] = abs(float(np.log(a / (1 - a)) - np.log(b / (1 - b))))
    return (float(np.mean(list(parts.values()))) if parts else None), parts


class Study:
    """One trader.  Subclasses set the paths and implement arrays() and build()."""
    id = ''
    name = ''
    ledger: Path = None              # notes/trades.csv
    cutoff = ''                      # ledger split, written into the first round's pre-registration
    full = ('2024-01-02', '2026-10-16')
    root: Path = None                # studies/<id>
    home = ('us',)                   # markets he trades (rounds tune only here)
    his = {}                         # year -> his published numbers (ret, win, avg_win, avg_loss, days_win, ...)
    his_behaviour = {}               # behaviour targets for gap() when not per year
    draws = 100                      # placebo draws for a carried configuration and final
    screen_draws = 50                # placebo draws while screening a round's candidates
    base = {}                        # the configuration a round with base ["", "base"] starts from

    # ----- trader-specific -----
    def arrays(self, market, upto=None, mode=None):
        """The market's A dict from studies.trader_data (panels); `upto` cuts it after that ISO day; `mode` frozen /
        live (default: TRADER_DATA_MODE)."""
        raise NotImplementedError

    def build(self, A, cfg, trace=None):
        """(entries, rules, mask, pool); trace (a dict) receives the entries after the stop rule ('raw'), the
        market filter ('filtered') and the daily cap ('capped'), plus any named stage masks for diagnose."""
        raise NotImplementedError

    def market_gate(self, A, cfg):
        """Per day: whether the market filter lets new longs in that day (None: no filter)."""
        return None

    def named(self, A, pool, name):
        """Day arrays the engine reads by name (exit / trim signals, risk scales) that A does not hold."""
        raise KeyError(name)

    def pool_dependent(self, name):
        return False

    def robust_variants(self, cfg):
        """Neighbours of cfg for robust(): name -> change.  The default nudges the account rules."""
        ro = cfg.get('rule_opts', {})
        v = {'base': {}, 'costs x2': {'rule_opts': {'buy_cost': .001, 'sell_cost': .001}}}
        for k, f in (('risk', .8), ('risk', 1.25)):
            if k in ro:
                v[f'{k} x{f}'] = {'rule_opts': {k: ro[k] * f}}
        if cfg.get('max_new'):
            v['max_new -1'] = {'max_new': max(1, cfg['max_new'] - 1)}
            v['max_new +1'] = {'max_new': cfg['max_new'] + 1}
        if 'max_open' in ro and ro['max_open']:
            v['max_open -2'] = {'rule_opts': {'max_open': max(1, ro['max_open'] - 2)}}
            v['max_open +2'] = {'rule_opts': {'max_open': ro['max_open'] + 2}}
        return v

    starts = ('2024-01-02', '2024-02-01', '2024-03-01', '2024-04-01', '2024-07-01', '2025-01-02')

    # ----- paths -----
    @property
    def reports(self):
        return self.root / 'reports'

    @property
    def out(self):
        """Where this module writes (the Martin self-check reads his reports and writes elsewhere)."""
        return self.reports

    @property
    def rounds(self):
        return self.root / 'notes' / 'rounds'

    @property
    def negations(self):
        return self.root / 'notes' / 'NEGATIONS.json'

    # ----- shared pieces -----
    def trades(self):
        return L.load(self.ledger)

    def located(self, A, trades, dated=True):
        """His longs on the panel (dated ones only by default)."""
        loc = F.locate([t for t in trades if t.side == 'long'], A['days'], A['codes'],
                       prefix=PREFIX.get(A['market'], ''), has=A['has'])[0]
        return [x for x in loc if x[0].dated] if dated else loc

    def ledger_sets(self, A):
        sel, val = L.split(self.trades(), self.cutoff)
        return self.located(A, sel), self.located(A, val)

    def config(self, report, key='chosen'):
        if not report:
            return dict(self.base)
        res = json.loads((self.reports / report).read_text(encoding='utf-8'))
        return res['chosen_config'] if key == 'chosen' else res['configs'][key]

    def px(self, A):
        return dict(open=A['open'], high=A['high'], low=A['low'], close=A['close'], dates=A['days'], codes=A['codes'])

    def ema_inputs(self, A, pool, rules):
        """Every array the rules read by name, built on demand through named()."""
        names = {rules.trail, rules.trail_after_trim, rules.trail_alt, rules.exit_signal, rules.trim_signal, rules.trim_signal2,
                 rules.risk_scale, rules.trail_alt_days}
        names |= {o.get('trail', '') for o in rules.management_by_kind.values()}
        names |= set(rules.short_targets)
        names |= {getattr(rules, k, '') for k in ('add_signal', 'trim_day_signal')}
        for k in names:
            if k and (k not in A or self.pool_dependent(k)):
                A[k] = self.named(A, pool, k)
        return {k: A[k] for k in names if k and k in A}

    def run(self, A, entries, seg, pool, rules, placebo=None, audit=False):
        """(stats, trades): the real run with bootstrap R interval, and (placebo > 0) its rank among same-pool
        random entries with the same stop widths."""
        placebo = self.draws if placebo is None else placebo
        px, ema = self.px(A), self.ema_inputs(A, pool, rules)
        curve, dates, tr = Y.simulate(px, ema, rules, entries, *seg, audit=audit)
        st = Y.stats(curve, dates, tr)
        r = np.array([t['r'] for t in tr]) if tr else np.zeros(1)
        boots = np.random.default_rng(0).choice(r, (2000, len(r))).mean(axis=1)
        st['ci_r'] = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
        if placebo:
            st['placebo'] = Y.placebo_rank(px, ema, rules, entries, *seg, pool, draws=placebo)
        if audit:
            st['behaviour'] = behaviour(curve, dates, tr)
            st['_curve'] = curve
        return st, tr

    def his_targets(self):
        """Behaviour targets: his_behaviour, else the mean of his published years."""
        if self.his_behaviour:
            return dict(self.his_behaviour)
        keys = ('per_year', 'win', 'avg_win', 'avg_loss', 'days_win', 'days_loss')
        out = {}
        for k in keys:
            v = [y[k] for y in self.his.values() if y.get(k) is not None]
            if v:
                out[k] = float(np.mean(v))
        return out

    def year_gap(self, by_year):
        """Mean absolute log ratio of (1 + ours) / (1 + his) over his published years we cover."""
        v = [abs(float(np.log((1 + by_year[y]) / (1 + h['ret'])))) for y, h in self.his.items()
             if y in by_year and h.get('ret') is not None and 1 + by_year[y] > 0]
        return float(np.mean(v)) if v else None

    def evaluate(self, A, cfg, ls, lv, placebo=None):
        entries, rules, mask, pool = self.build(A, cfg)
        st, tr = self.run(A, entries, self.full, pool, rules, placebo, audit=True)
        rs, rv = F.recall(mask, ls, A['has']), F.recall(mask, lv, A['has'])
        st['fidelity'] = dict(select=[rs['hits'], rs['n']], validate=[rv['hits'], rv['n']])
        st['bought'] = dict(select=[bought(A, tr, ls), len(ls)], validate=[bought(A, tr, lv), len(lv)])
        st['signals_per_day'] = F.width(mask, A['days'], *self.full)
        y = st['by_year']
        st['min_year'] = float(min(y.values()))
        st['min_2024_2025'] = float(min(y['2024'], y['2025'])) if y.get('2026', 0) > 0 and '2025' in y else -9.0
        st['behaviour_gap'], st['behaviour_parts'] = gap(st['behaviour'], self.his_targets())
        st['year_gap'] = self.year_gap(y)
        st.pop('_curve', None)
        return st, tr

    # ----- the choice -----
    @staticmethod
    def score(st, objective):
        """Higher is better."""
        if objective in st and isinstance(st[objective], (int, float)):
            return st[objective]
        hits = lambda k, i=None: sum(x[0] for x in st[k].values()) if i is None else st[k][i][0]
        if objective == 'bought':
            return (hits('bought'), st['total'])
        if objective == 'bought_select':
            return (hits('bought', 'select'), st['total'])
        if objective == 'hits':
            return (hits('fidelity'), st['total'])
        if objective == 'hits_select':
            return (hits('fidelity', 'select'), st['total'])
        if objective == 'behaviour':
            return -(st['behaviour_gap'] if st['behaviour_gap'] is not None else 9.0)
        if objective == 'his_years':
            return -(st['year_gap'] if st['year_gap'] is not None else 9.0)
        raise ValueError(objective)

    @staticmethod
    def passes(st, ref, gates):
        """Gate names: 'placebo' (full-period total above the placebo median), 'hits' / 'bought' (ledger hits /
        trades bought, selection + validation, at least the reference's), 'behaviour' (behaviour gap no larger
        than the reference's), 'positive' (every year positive), 'width<=N' (median signals a day at most N), 'win<=X' (win rate of the closed trades at most X)."""
        fails = []
        for g in gates:
            if g == 'placebo' and not st['total'] > st['placebo']['median']:
                fails.append('placebo')
            elif g in ('hits', 'bought'):
                key = 'fidelity' if g == 'hits' else 'bought'
                if sum(x[0] for x in st[key].values()) < sum(x[0] for x in ref[key].values()):
                    fails.append(g)
            elif g == 'behaviour' and (st['behaviour_gap'] or 9) > (ref['behaviour_gap'] or 9) + 1e-12:
                fails.append('behaviour')
            elif g == 'positive' and min(st['by_year'].values()) <= 0:
                fails.append('positive')
            elif g.startswith('width<=') and st['signals_per_day']['median'] > float(g[7:]):
                fails.append(g)                        # median signals a day above his workload
            elif g.startswith('win<=') and not (st.get('win') is not None and st['win'] <= float(g[5:])):
                fails.append(g)                        # the engineering gate's win-rate ceiling, as a round gate
        return fails

    def round(self, name):
        """Run notes/rounds/<name>.json: {"stage", "base": [report, key | "chosen"], "ref", "objective",
        "gates", "candidates": {key: changes}, "market"}; results in reports/<name lower-case>.json.  Candidates
        that fail a gate or score below the reference go into the negation register."""
        spec = json.loads((self.rounds / f'{name}.json').read_text(encoding='utf-8'))
        report, key = spec['base']
        base = merged(self.config(report, key), spec.get('base_change', {}))   # a declared correction of the base
        cfgs = {k: merged(base, v) for k, v in spec['candidates'].items()}
        ref = spec['ref']
        cfgs[ref] = base
        objective = spec.get('objective', 'min_2024_2025')
        gates = spec.get('gates', ['placebo', 'hits'])
        market = spec.get('market', self.home[0])
        A = self.arrays(market)
        ls, lv = self.ledger_sets(A)
        out = dict(name=name, stage=spec.get('stage', ''), base=spec['base'], configs=cfgs, full={},
                   objective=objective, gates=gates, market=market)
        draws = spec.get('draws', self.screen_draws)
        for k, cfg in cfgs.items():
            st, _ = self.evaluate(A, cfg, ls, lv, placebo=draws)
            out['full'][k] = st
            self.print_row(name, k, st)
        res = out['full']
        fails = {k: self.passes(res[k], res[ref], gates) for k in cfgs if k != ref}
        ok = [k for k in fails if not fails[k]]
        best = max(ok + [ref], key=lambda k: self.score(res[k], objective))     # never carry a worse system
        while draws < self.draws:                  # the carried configuration gets the full placebo
            st, _ = self.evaluate(A, cfgs[best], ls, lv, placebo=self.draws)
            st['placebo_screen'] = res[best]['placebo']
            res[best] = st
            self.print_row(name, best + f' ({self.draws} draws)', st)
            if best == ref or not self.passes(st, res[ref], gates):
                break
            fails[best] = self.passes(st, res[ref], gates)
            ok.remove(best)
            best = max(ok + [ref], key=lambda k: self.score(res[k], objective))
        out.update(chosen=best, chosen_config=cfgs[best], failed_gates=fails)
        print(name, 'chosen', best, objective, self.score(res[best], objective), flush=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'{name.lower()}.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
        for k, why in fails.items():
            if k == best:
                continue
            reason = 'gates: ' + ', '.join(why) if why else 'objective below ' + best
            N.add(self.negations, dict(round=name, stage=spec.get('stage', ''), candidate=k,
                                       change=spec['candidates'][k], base=spec['base'], chosen=best,
                                       reason=reason, objective=objective,
                                       evidence=self.evidence(res[k], res[best]), base_config=base))
        if self.negations.exists():
            N.render(self.negations, self.name)
        self.update_scoreboard(name, best, res[best], res[ref], ref)
        return out

    @staticmethod
    def evidence(st, best):
        keep = ('total', 'by_year', 'win', 'per_year', 'behaviour_gap', 'year_gap')
        return dict(**{k: st.get(k) for k in keep}, placebo_median=st['placebo']['median'],
                    bought=st['bought'], fidelity=st['fidelity'], best_total=best['total'])

    def print_row(self, tag, k, st):
        b = st['behaviour']
        print(tag, k, f"full {st['total']:+.3f} dd {st['maxdd']:.2f} placebo med {st['placebo']['median']:+.3f} "
              f"rank {st['placebo']['rank']:.2f} n/yr {st['per_year']:.0f} win {st['win']:.3f} "
              f"avg {st['avg_win']:+.3f}/{st['avg_loss']:+.3f} hold {b['days_win']}/{b['days_loss']}",
              'years', {a: round(v, 3) for a, v in st['by_year'].items()}, 'hits', st['fidelity'],
              'bought', st['bought'], 'gap', st['behaviour_gap'] and round(st['behaviour_gap'], 3), flush=True)

    # ----- scoreboard -----
    @property
    def scoreboard(self):
        return self.root / 'notes' / 'SCOREBOARD.json'

    def update_scoreboard(self, name, key, st, ref_st, ref):
        rows = json.loads(self.scoreboard.read_text(encoding='utf-8')) if self.scoreboard.exists() else []
        rows = [r for r in rows if r['round'] != name]
        rows.append(dict(round=name, chosen=key, ref=ref, **self.board_row(st)))
        rows.sort(key=lambda r: int(''.join(ch for ch in r['round'] if ch.isdigit()) or 0))
        self.scoreboard.write_text(json.dumps(rows, indent=1, default=float), encoding='utf-8')
        self.render_scoreboard(rows)

    @staticmethod
    def board_row(st):
        b = st['behaviour']
        return dict(total=st['total'], by_year=st['by_year'], maxdd=st['maxdd'], placebo_median=st['placebo']['median'],
                    placebo_rank=st['placebo']['rank'], bought=st['bought'], hits=st['fidelity'],
                    per_year=b['per_year'], per_day=b['per_day'], win=b['win'], avg_win=b['avg_win'],
                    avg_loss=b['avg_loss'], days_win=b['days_win'], days_loss=b['days_loss'],
                    entry_weight_mean=b.get('entry_weight_mean'), open_mean=b.get('open_mean'),
                    top10_share=b.get('top10_share'), behaviour_gap=st['behaviour_gap'], year_gap=st['year_gap'])

    def render_scoreboard(self, rows):
        pct = lambda x: '—' if x is None else f'{x:+.0%}'
        num = lambda x, f='{:.1f}': '—' if x is None else f.format(x)
        his = self.his_targets()
        yrs = sorted({y for r in rows for y in r['by_year']} | set(self.his))
        head = ['轮次', '带入', '买到他的票（选择 / 验证）', '信号日命中', '笔数 / 年', '笔数 / 天', '持有天数 赢 / 亏（均值）',
                '胜率', '平均赚 / 亏', '单笔仓位均值', '同时持仓', '行为差距'] + [f'{y} 收益' for y in yrs] + ['安慰剂中位 / 排位']
        lines = [f'# {self.name} 记分板', '',
                 '每轮自动写入（`studies.trader_replication.study`）；行为各项是门槛，不能比参照差。全部是样本内。', '',
                 '| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
        hisrow = ['他本人', '', '', '', num(his.get('per_year'), '{:.0f}'), '', f"{num(his.get('days_win'))} / "
                  f"{num(his.get('days_loss'))}", num(his.get('win'), '{:.0%}'),
                  f"{pct(his.get('avg_win'))} / {pct(his.get('avg_loss'))}", '', '', ''] + \
                 [pct(self.his.get(y, {}).get('ret')) for y in yrs] + ['']
        lines.append('| ' + ' | '.join(hisrow) + ' |')
        for r in rows:
            b, h = r['bought'], r['hits']
            cells = [r['round'], r['chosen'], f"{b['select'][0]}/{b['select'][1]}，{b['validate'][0]}/{b['validate'][1]}",
                     f"{h['select'][0]}/{h['select'][1]}，{h['validate'][0]}/{h['validate'][1]}",
                     num(r['per_year'], '{:.0f}'), num(r['per_day'], '{:.2f}'),
                     f"{num(r['days_win'])} / {num(r['days_loss'])}", num(r['win'], '{:.0%}'),
                     f"{pct(r['avg_win'])} / {pct(r['avg_loss'])}", num(r['entry_weight_mean'], '{:.0%}'),
                     num(r['open_mean']), num(r['behaviour_gap'], '{:.2f}')] + \
                    [pct(r['by_year'].get(y)) for y in yrs] + [f"{pct(r['placebo_median'])} / {r['placebo_rank']:.2f}"]
            lines.append('| ' + ' | '.join(cells) + ' |')
        (self.root / 'notes' / 'SCOREBOARD_CN.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    # ----- reports on a chosen configuration -----
    def diagnose(self, report, key='chosen', market=None):
        """For each of his dated longs (inside the full period): the furthest step reached on a day of its window,
        his place among the day's filtered entries, and our result when we traded it; top names and trades."""
        cfg = self.config(report, key)
        A = self.arrays(market or self.home[0])
        trace = {}
        entries, rules, mask, pool = self.build(A, cfg, trace)
        st, tr = self.run(A, entries, self.full, pool, rules, placebo=0)
        ours = {(t['code'], t['entry']): t for t in tr}
        sets = {k: [{e[1] for e in lst} for lst in trace[k]] for k in ('raw', 'filtered', 'capped')}
        rows = []
        for t, j, a, b in self.located(A, self.trades(), dated=False):
            if not t.dated or t.entry_date < self.full[0]:
                continue
            code, best, ours_t, n_day, place = str(A['codes'][j]), 0, None, None, None
            for d in range(a, b + 1):
                k = 0
                if mask[d, j]:
                    k = 1
                    if j in sets['raw'][d]:
                        k = 2
                        if j in sets['filtered'][d]:
                            k = 3
                            if j in sets['capped'][d]:
                                k = 4
                                if (code, str(A['days'][d])) in ours:
                                    k = 5
                                    ours_t = ours[(code, str(A['days'][d]))]
                if k >= 3 and (place is None or k > best):
                    order = [e[1] for e in sorted(trace['filtered'][d], key=lambda e: e[0])]
                    n_day, place = len(order), order.index(j) + 1
                best = max(best, k)
            rows.append(dict(id=t.id, ticker=t.ticker, date=t.entry_date, his_r=t.r_multiple, his_outcome=t.outcome,
                             step=STEPS[best], our_r=ours_t and round(ours_t['r'], 2),
                             our_ret=ours_t and round(ours_t['ret'], 3), our_days=ours_t and ours_t['days'],
                             our_why=ours_t and ours_t['why'], entries_that_day=n_day, his_place=place))
            rows[-1]['input_days'] = [dict(day=str(A['days'][d]),
                **{nm: bool(trace[nm][d, j]) for nm in self.trace_masks(trace)},
                prior_adr=float(A['adr'][d - 1, j]), prior_turnover=float(A['to20'][d - 1, j]),
                gap=float(A['open'][d, j] / A['close'][d - 1, j] - 1),
                relative_turnover=float(A['turnover'][d, j] / A['to20'][d - 1, j])) for d in range(a, b + 1) if d > 0]
        by_year = {}
        for r in rows:
            y = by_year.setdefault(r['date'][:4], {k: 0 for k in STEPS})
            y[r['step']] += 1
        pnl = {}
        for t in tr:
            y = pnl.setdefault(t['entry'][:4], {})
            y[t['code']] = y.get(t['code'], 0.0) + t['pnl']
        top = {y: sorted(v.items(), key=lambda x: -x[1])[:10] for y, v in pnl.items()}
        out = dict(report=report, by_year=by_year, rows=rows, top_names=top, stats={k: v for k, v in st.items()})
        for r in rows:
            print('DIAG', {k: v for k, v in r.items() if k != 'input_days'})
        print('DIAG by year', by_year)
        print('DIAG top names', {y: [(c, round(v, 3)) for c, v in x] for y, x in top.items()})
        for t in sorted(tr, key=lambda t: -t['pnl'])[:15]:
            print('DIAG top trade', {k: (round(v, 3) if isinstance(v, float) else v) for k, v in t.items()})
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'diagnose_{self.tag(report, key)}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out

    @staticmethod
    def tag(report, key):
        """Report file suffix: the round report's stem, plus the key when it is not the chosen one."""
        stem = Path(report).stem or 'base'
        return stem if key == 'chosen' else f'{stem}_{key}'

    @staticmethod
    def trace_masks(trace):
        return [k for k, v in trace.items() if isinstance(v, np.ndarray) and v.dtype == bool and v.ndim == 2]

    def robust(self, report, key='chosen'):
        """Real runs only (no placebo): neighbours of the knobs, start-date shifts, doubled costs.  Reported,
        never used to choose."""
        cfg = self.config(report, key)
        A = self.arrays(self.home[0])
        out = {'report': report, 'config': cfg, 'variants': {}, 'starts': {}}
        for name, change in self.robust_variants(cfg).items():
            entries, rules, mask, pool = self.build(A, merged(cfg, change))
            st = self.run(A, entries, self.full, pool, rules, placebo=0)[0]
            out['variants'][name] = {k: st[k] for k in ('total', 'maxdd', 'per_year', 'win', 'by_year')}
            print('ROBUST', name, f"full {st['total']:+.3f} dd {st['maxdd']:.2f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, flush=True)
        entries, rules, mask, pool = self.build(A, cfg)
        for start in self.starts:
            st = self.run(A, entries, (start, self.full[1]), pool, rules, placebo=0)[0]
            out['starts'][start] = {k: st[k] for k in ('total', 'maxdd', 'by_year')}
            print('ROBUST start', start, f"full {st['total']:+.3f} dd {st['maxdd']:.2f}",
                  {a: round(b, 3) for a, b in st['by_year'].items()}, flush=True)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'robust_{self.tag(report, key)}.json').write_text(json.dumps(out, indent=1, default=float),
                                                                    encoding='utf-8')
        return out

    def final(self, report, key='chosen', markets=('us', 'hk', 'cn')):
        """The configuration in all three markets: full period and calendar years against same-pool random
        entries and equal-weight holding of the pool, trade counts by year, and (home market) ledger hits."""
        res = json.loads((self.reports / report).read_text(encoding='utf-8')) if report else {}
        cfg = self.config(report, key)
        out = {'report': report, 'chosen': res.get('chosen', key), 'config': cfg, 'his': self.his}
        for market in markets:
            A = self.arrays(market)
            entries, rules, mask, pool = self.build(A, cfg)
            st, tr = self.run(A, entries, self.full, pool, rules)
            span = A['days'][(A['days'] >= self.full[0]) & (A['days'] <= self.full[1])]
            st['data_span'] = [str(span[0]), str(span[-1])]
            years = sorted(st['by_year'])
            st['ew_hold_pool'] = ew_hold(A, pool, self.full)
            st['ew_hold_by_year'] = {y: ew_hold(A, pool, (f'{y}-01-01', f'{y}-12-31')) for y in years}
            st['ew_hold_lagged'] = ew_hold(A, pool, self.full, lagged=True)
            st['ew_hold_lagged_by_year'] = {y: ew_hold(A, pool, (f'{y}-01-01', f'{y}-12-31'), lagged=True)
                                            for y in years}
            st['trades_by_year'] = {y: year_trades(tr, y) for y in years}
            st['why'] = {w: sum(t['why'] == w for t in tr) for w in sorted({t['why'] for t in tr})}
            if market == self.home[0]:
                ls, lv = self.ledger_sets(A)
                rs, rv = F.recall(mask, ls, A['has']), F.recall(mask, lv, A['has'])
                st['fidelity'] = {k: {a: b for a, b in r.items() if a != 'per_trade'}
                                  for k, r in (('select', rs), ('validate', rv))}
                st['signals_per_day'] = F.width(mask, A['days'], *self.full)
                st['bought'] = dict(select=[bought(A, tr, ls), len(ls)], validate=[bought(A, tr, lv), len(lv)])
            out[market] = st
            print('FINAL', market, f"full {st['total']:+.3f} dd {st['maxdd']:.2f} placebo median "
                  f"{st['placebo']['median']:+.3f} rank {st['placebo']['rank']:.2f} ew {st['ew_hold_pool']:+.3f}",
                  'years', {a: round(b, 3) for a, b in st['by_year'].items()},
                  'ew years', {a: round(b, 3) for a, b in st['ew_hold_by_year'].items()},
                  'trades', {y: (v['n'], v['win'] and round(v['win'], 3)) for y, v in st['trades_by_year'].items()},
                  flush=True)
            del A
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'final_{self.tag(report, key)}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out

    def his_entry(self, A, d, j, cfg):
        """Layer two of the three-layer replay: his ticker on his day, entered with our execution.  The default
        buys the close with the stop at the day's low, at least 1% and at most 5% below (an engine entry tuple)."""
        c, l = A['close'][d, j], A['low'][d, j]
        if not (np.isfinite(c) and np.isfinite(l) and c > 0):
            return None
        stop = min(max(l, c * .95), c * .99)
        return (0.0, j, 1, c, stop, 'his')

    def three(self, report, key='chosen'):
        """Three-layer replay on his dated longs: (1) his own result from the ledger, (2) his ticker and day with
        our execution (his_entry + our exits and sizing, no daily cap, every trade sized on its own), (3) our
        system.  (1) vs (2) is execution, (2) vs (3) selection."""
        cfg = self.config(report, key)
        A = self.arrays(self.home[0])
        entries, rules, mask, pool = self.build(A, cfg)
        st3, tr3 = self.run(A, entries, self.full, pool, rules, placebo=0, audit=True)
        located = [x for x in self.located(A, self.trades()) if x[0].entry_date >= self.full[0]]
        mine = [[] for _ in range(len(A['days']))]
        di = {str(d): i for i, d in enumerate(A['days'])}
        for t, j, a, b in located:
            d = di.get(t.entry_date)
            if d is None:
                continue
            e = self.his_entry(A, d, j, cfg)
            if e is not None:
                mine[d].append(e)
        alone = replace(rules, max_open=0, max_new_long=0, max_gross=1e9, max_position=1e9,
                        feedback=0, risk_scale='', margin_rate=0.0)
        st2, tr2 = self.run(A, mine, self.full, pool, alone, placebo=0, audit=True)
        rows2 = {(t['code'], t['entry']): t for t in tr2}
        per = []
        for t, j, a, b in located:
            x = rows2.get((str(A['codes'][j]), t.entry_date))
            per.append(dict(id=t.id, ticker=t.ticker, date=t.entry_date, setup=t.setup, his_outcome=t.outcome,
                            his_r=t.r_multiple, our_r=x and round(x['r'], 2), our_ret=x and round(x['ret'], 3),
                            our_days=x and x['days'], our_why=x and x['why']))
        his = [t for t, *_ in located]
        lay1 = dict(n=len(his), wins=sum(t.outcome == 'win' for t in his), losses=sum(t.outcome == 'loss' for t in his),
                    r_known=[t.r_multiple for t in his if t.r_multiple is not None], published=self.his)
        r2 = [p['our_r'] for p in per if p['our_r'] is not None]
        ret2 = [p['our_ret'] for p in per if p['our_ret'] is not None]
        lay2 = dict(n=len(r2), mean_r=float(np.mean(r2)) if r2 else None, median_r=float(np.median(r2)) if r2 else None,
                    win=float(np.mean([x > 0 for x in ret2])) if ret2 else None,
                    mean_ret=float(np.mean(ret2)) if ret2 else None, behaviour=st2['behaviour'],
                    sum_r=float(np.sum(r2)) if r2 else None)
        r3 = [t['r'] for t in tr3]
        lay3 = dict(n=len(tr3), mean_r=float(np.mean(r3)) if r3 else None, total=st3['total'], by_year=st3['by_year'],
                    behaviour=st3['behaviour'], bought=bought(A, tr3, located))
        out = dict(report=report, config=cfg, layer1=lay1, layer2=lay2, layer3=lay3, per_trade=per)
        print('THREE layer1', {k: v for k, v in lay1.items() if k != 'published'})
        print('THREE layer2', {k: v for k, v in lay2.items() if k != 'behaviour'})
        print('THREE layer3', {k: v for k, v in lay3.items() if k != 'behaviour'})
        for p in per:
            print('THREE', p)
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / f'three_{self.tag(report, key)}.json').write_text(
            json.dumps(out, indent=1, default=float), encoding='utf-8')
        return out

    def stale_negations(self, report, key='chosen'):
        """Negations made under a base configuration that has since changed (to retest)."""
        return N.stale(self.negations, self.config(report, key))


def main(study, argv):
    """python -m studies.<id>.replicate round R3 | diagnose r3.json | robust r3.json | final r3.json |
    three r3.json | negations r3.json"""
    action = argv[1]
    if action == 'round':
        study.round(argv[2])
    elif action in ('diagnose', 'robust', 'final', 'three'):
        report = argv[2] if len(argv) > 2 else ''
        getattr(study, action)(report, argv[3] if len(argv) > 3 else 'chosen')
    elif action == 'negations':
        for r in study.stale_negations(argv[2]):
            print('STALE', r['round'], r['candidate'], r['reason'], r['changed'])
    else:
        raise SystemExit(main.__doc__)
