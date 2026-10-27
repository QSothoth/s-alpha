"""The return goal of docs/prompts/new_styles_return_goal.md for studies built on trader_replication.study.

A configuration meets the goal when (1) every period he published that lies in the selection segment is within 0.3
of his figure in log terms, (2) every behaviour measure he published is within +-30% of his, and (3) the selection
segment beats the same-pool random-entry median.  His trade count per year is required: a trader with no sourced
count never meets the goal, and a (low, high) pair states a sourced range.  `goal` folds (1) and (2) into one number to maximise:

    goal = -max(max period gap / 0.3, max behaviour deviation / 0.3)      (>= -1 means both are met)

Periods are (first day, last day, his return) so a part year (Evan's 2025 to August) is compared over the same
months.  The mixin also reports the periods outside the selection segment (2026, already used once) without scoring
them, and renders the scoreboard with the first-round version and his targets side by side.
"""
from __future__ import annotations

import json

import numpy as np

YEAR_TOL = 0.3          # |log((1 + ours) / (1 + his))|
BEHAVIOUR_TOL = 0.3     # |ours / his - 1|


def period_returns(curve, dates, periods):
    """{name: our return over [first, last]} for the periods the curve covers (None when it covers none of it)."""
    dates = np.asarray(dates).astype(str)
    out = {}
    for name, (a, b, _) in periods.items():
        idx = np.flatnonzero((dates >= a) & (dates <= b))
        if not len(idx):
            out[name] = None
            continue
        base = curve[idx[0] - 1] if idx[0] > 0 else 1.0
        out[name] = float(curve[idx[-1]] / base - 1)
    return out


def behaviour_of(tr, n_days):
    """The measures the five traders publish, from closed trades over n_days sessions."""
    ret = np.array([t['ret'] for t in tr]) if tr else np.zeros(0)
    win = ret > 0
    years = max(n_days / 252, 1e-9)
    return dict(per_year=len(tr) / years, per_week=len(tr) / years / 52,
                win=float(win.mean()) if len(ret) else None,
                avg_win=float(ret[win].mean()) if win.any() else None,
                avg_loss=float(ret[~win].mean()) if (~win).any() else None,
                days=float(np.mean([t['days'] for t in tr])) if tr else None)


def deviations(ours, his):
    """{measure: |ours / his - 1|} over the measures he published (sign mismatches count as 1).  A (low, high) pair is
    a sourced range: 0 inside it, else the distance to the nearer end."""
    out = {}
    for k, h in his.items():
        o = ours.get(k)
        if o is None or h is None or h == 0:
            continue
        if isinstance(h, (tuple, list)):
            lo, hi = h
            h = lo if o < lo else hi if o > hi else o
        out[k] = abs(o / h - 1) if o * h > 0 else 1.0
    return out


def meets(goal, devs, total, placebo_median):
    """A replication counts only with his published trade count matched: no sourced count, no pass."""
    return bool(goal >= -1 and 'per_year' in devs and total > placebo_median)


def period_gaps(rets, periods, seg):
    """{name: |log((1 + ours) / (1 + his))|} for his periods inside the segment."""
    out = {}
    for name, (a, b, h) in periods.items():
        if h is None or a < seg[0] or b > seg[1] or rets.get(name) is None:
            continue
        o = rets[name]
        out[name] = abs(float(np.log((1 + o) / (1 + h)))) if 1 + o > 0 else 9.0
    return out


def goal_of(period_gap, devs):
    y = max(period_gap.values()) / YEAR_TOL if period_gap else 9.0
    b = max(devs.values()) / BEHAVIOUR_TOL if devs else 0.0
    return -max(y, b), y, b


class GoalMixin:
    """Put before study.Study in the bases; set `periods` and `goal_behaviour`."""
    periods = {}            # name -> (first ISO day, last ISO day, his return)
    goal_behaviour = {}     # measure -> his value (behaviour_of names)
    first_round = ''        # the first-round report shown on the scoreboard ('r3.json')

    def run(self, A, entries, seg, pool, rules, placebo=None, audit=False, track=None):
        st, tr = super().run(A, entries, seg, pool, rules, placebo, audit, track)
        if audit and '_curve' in st:
            d = A['days'].astype(str)
            dates = d[(d >= seg[0]) & (d <= seg[1])]
            curve = st['_curve']
            if len(dates) == len(curve):
                st['periods'] = period_returns(curve, dates, self.periods)
                st['goal_behaviour'] = behaviour_of(tr, len(dates))
        return st, tr

    def evaluate(self, A, cfg, ls, lv, placebo=None):
        st, tr = super().evaluate(A, cfg, ls, lv, placebo)
        pg = period_gaps(st.get('periods', {}), self.periods, self.full)
        dv = deviations(st.get('goal_behaviour', {}), self.goal_behaviour)
        st['goal'], st['goal_years'], st['goal_behav'] = goal_of(pg, dv)
        st['goal_parts'] = dict(periods=pg, behaviour=dv)
        st['meets'] = meets(st['goal'], dv, st['total'], st['placebo']['median'])
        return st, tr

    @staticmethod
    def passes(st, ref, gates):
        """Study.passes plus 'years' (year distance within tolerance, or no worse than the reference's) and
        'behav' (the same for the behaviour distance): one half of the goal cannot be bought with the other."""
        from studies.trader_replication import study as S
        rest = [g for g in gates if g not in ('years', 'behav')]
        fails = S.Study.passes(st, ref, rest)
        for g, k in (('years', 'goal_years'), ('behav', 'goal_behav')):
            if g in gates and st.get(k, 9) > max(ref.get(k, 9), 1.0) + 1e-9:
                fails.append(g)
        return fails

    @staticmethod
    def board_row(st):
        from studies.trader_replication import study as S
        row = S.Study.board_row(st)
        row.update(periods=st.get('periods'), goal=st.get('goal'), goal_years=st.get('goal_years'),
                   goal_behav=st.get('goal_behav'), gb=st.get('goal_behaviour'), meets=st.get('meets'))
        return row

    def render_scoreboard(self, rows):
        pct = lambda x: '—' if x is None else f'{x:+.1%}'
        num = lambda x, f='{:.1f}': '—' if x is None else f.format(x)
        names = list(self.periods)
        head = ['轮次', '带入'] + [f'{n}（他 {pct(self.periods[n][2])}）' for n in names] + \
            ['笔数 / 年', '胜率', '平均赚 / 亏', '持有天数', '年距离 / 0.3', '行为距离 / 0.3', '目标分', '安慰剂中位 / 排位', '达标']
        g = self.goal_behaviour
        his = ['他本人', ''] + [pct(self.periods[n][2]) for n in names] + \
            [num(g.get('per_year'), '{:.0f}'), num(g.get('win'), '{:.0%}'),
             f"{pct(g.get('avg_win'))} / {pct(g.get('avg_loss'))}", num(g.get('days')), '', '', '', '', '']
        lines = [f'# {self.name} 记分板', '',
                 '每轮自动写入（`studies.trader_options.goal`）。选择段 2024-01-02 → 2025-12-31，全部样本内；'
                 '2026 列为已用过的验证段，只照报、不参与选择。目标分 = −max(年距离, 行为距离)，≥ −1 且跑赢安慰剂中位才算达标。', '',
                 '| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head), '| ' + ' | '.join(his) + ' |']
        for r in rows:
            b = r.get('gb') or {}
            p = r.get('periods') or {}
            cells = [r['round'], r['chosen']] + [pct(p.get(n)) for n in names] + \
                [num(b.get('per_year', r.get('per_year')), '{:.0f}'), num(b.get('win', r.get('win')), '{:.0%}'),
                 f"{pct(b.get('avg_win', r.get('avg_win')))} / {pct(b.get('avg_loss', r.get('avg_loss')))}",
                 num(b.get('days')), num(r.get('goal_years'), '{:.2f}'), num(r.get('goal_behav'), '{:.2f}'),
                 num(r.get('goal'), '{:+.2f}'), f"{pct(r['placebo_median'])} / {r['placebo_rank']:.2f}",
                 {True: '是', False: '否'}.get(r.get('meets'), '—')]
            lines.append('| ' + ' | '.join(cells) + ' |')
        (self.root / 'notes' / 'SCOREBOARD_CN.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def baseline(self, report, key='chosen', label='R0'):
        """Score an earlier round's configuration with the goal and put it on the scoreboard as `label`."""
        A = self.arrays(self.home[0])
        ls, lv = self.ledger_sets(A)
        st, _ = self.evaluate(A, self.config(report, key), ls, lv, placebo=self.draws)
        rows = json.loads(self.scoreboard.read_text(encoding='utf-8')) if self.scoreboard.exists() else []
        rows = [r for r in rows if r['round'] != label]
        rows.insert(0, dict(round=label, chosen=f'{report}:{key}', ref='', **self.board_row(st)))
        self.scoreboard.write_text(json.dumps(rows, indent=1, default=float), encoding='utf-8')
        self.render_scoreboard(rows)
        print(label, report, key, 'goal', round(st['goal'], 3), st['goal_parts'], 'periods', st.get('periods'),
              'placebo', round(st['placebo']['median'], 3), 'total', round(st['total'], 3), flush=True)
        return st
