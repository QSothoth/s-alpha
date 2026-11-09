"""PREREG_E16_CN: IE47 watch-list mechanics (no cooldown, persistent list, retries) under fixed C062 execution."""
from __future__ import annotations

import csv
from contextlib import ExitStack
from dataclasses import replace
from datetime import date
import json
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

from . import ie47_e1 as M

ROOT = Path(__file__).resolve().parents[2]
OUT = M.STUDY.root/'reports/e16_work'
ARMS = {'N0': dict(cooldown=0),
        'L1': dict(exit='e21', width=12, renew=False),
        'L2': dict(exit='e21', width=12, renew=True),
        'L3': dict(exit='e21', width=6, renew=False),
        'L4': dict(exit='e50', width=12, renew=False)}


def picks_with_cooldown(R, codes, days, cooldown):
    """IE47's own nightly choice (frozen scores, unavailable-benchmark nights empty) with another cooldown."""
    rows, scores, offset = [], [], 0
    for t, ix in zip(R['night_indices'], R['kept']):
        s = R['scores'][offset:offset+len(ix)]
        offset += len(ix)
        on = R['regime'][t] >= 0
        rows.append(ix if on else np.array([], int))
        scores.append(s if on else np.array([], np.float32))
    chosen = M.select_nights(rows, scores, codes, cooldown)
    return {days[t]: [str(codes[j]) for j in ix] for t, ix in zip(R['night_indices'], chosen)}


def persistent_book(A, picks, exit_line, width=12, renew=False, cap_max=.05, pool=None, offset=0):
    """A pick joins the list for the next session and stays until a later close below exit_line (acted on the
    session after); a break does not use the name up. Over `width` (None: no limit), the earliest picked names
    leave. A trigger is E6c's close above the previous high with its capped stop; renew also requires the close to
    exceed every high since the name's previous trigger; pool (E17 Q4) requires the name in the previous night's
    filtering pool. Same-day priority: the most recent pick first, then its IE47 rank; offset shifts the priority
    key behind another book's ranks."""
    days, codes = list(map(str, A['days'])), list(map(str, A['codes']))
    ci = {c: j for j, c in enumerate(codes)}
    h, l, c = (A[k] for k in ('high', 'low', 'close'))
    entries, listed, last, sizes = [[] for _ in days], {}, {}, []
    width = len(codes) if width is None else width
    for d in range(1, len(days)):
        for j, (born, _) in list(listed.items()):
            if d-1 > born and c[d-1, j] < exit_line[d-1, j]:
                del listed[j]
                last.pop(j, None)
        for rank, code in enumerate(picks.get(days[d-1], ())):
            if code not in ci:
                raise ValueError('IE47 pick not on the common panel: '+code)
            listed[ci[code]] = (d-1, rank)
        for j, _ in sorted(listed.items(), key=lambda kv: (kv[1][0], -kv[1][1]))[:max(0, len(listed)-width)]:
            del listed[j]
            last.pop(j, None)
        sizes.append(len(listed))
        for j, (born, rank) in sorted(listed.items(), key=lambda kv: (-kv[1][0], kv[1][1])):
            inputs = (h[d, j], l[d, j], c[d, j], h[d-1, j], A['adr'][d-1, j])
            if not np.isfinite(inputs).all() or min(inputs) <= 0 or c[d, j] <= h[d-1, j]:
                continue
            if renew and j in last and c[d, j] <= np.nanmax(h[last[j]:d, j]):
                continue
            if pool is not None and not pool[d-1, j]:
                continue
            last[j] = d
            stop = M.capped_stop(float(c[d, j]), float(l[d, j]), A['adr'][d-1, j], cap_max)
            if stop is None:
                continue
            entries[d].append(((offset+d-1-born, born, rank, codes[j]), j, 1, float(c[d, j]), stop, M.CLOSE_KIND, None))
    return entries, sizes


RETRY_KIND = 'ie47_close_retry'


def overlay_book(A, base, picks, exit_line, width=None, renew=False, pool=None):
    """E17: the base book unchanged; list retries after every base entry of the day, none for a name the base
    already enters that day."""
    extra, sizes = persistent_book(A, picks, exit_line, width, renew, pool=pool, offset=1000)
    out, retries = [], 0
    for row, more in zip(base, extra):
        taken = {e[1] for e in row}
        add = [e[:5]+(RETRY_KIND, None) for e in more if e[1] not in taken]
        retries += len(add)
        out.append(list(row)+add)
    return out, sizes, retries


def ema(x, span):
    from studies.trader_screens import screens as S
    return S.ema(x, span)


E17 = {'Q1': dict(exit='e21', width=None, renew=False, pool=False),
       'Q2': dict(exit='e21', width=30, renew=False, pool=False),
       'Q3': dict(exit='e50', width=None, renew=False, pool=False),
       'Q4': dict(exit='e21', width=None, renew=False, pool=True),
       'Q5': dict(exit='e21', width=None, renew=True, pool=False)}


# PREREG_E18_CN: E17 lists with the retries' own open (and for R5 daily) caps inside the eleven positions.
E18 = {'R1': ('Q1', dict(max_open_by_kind={RETRY_KIND: 3})),
       'R2': ('Q1', dict(max_open_by_kind={RETRY_KIND: 2})),
       'R3': ('Q1', dict(max_open_by_kind={RETRY_KIND: 5})),
       'R4': ('Q3', dict(max_open_by_kind={RETRY_KIND: 3})),
       'R5': ('Q1', dict(max_open_by_kind={RETRY_KIND: 3}, max_new_by_kind={RETRY_KIND: 1}))}


def arm_rules(rules, name):
    return replace(rules, **E18[name][1]) if name in E18 else rules


def arm_book(A, R, name, base=None):
    days, codes = list(map(str, A['days'])), np.asarray(A['codes'], str)
    if name in E18:
        return arm_book(A, R, E18[name][0], base)
    if name in E17:
        spec = E17[name]
        line = A.setdefault(spec['exit'], ema(A['close'], 21 if spec['exit'] == 'e21' else 50))
        book, sizes, retries = overlay_book(A, base, R['picks'], line, spec['width'], spec['renew'],
                                            R['pool'] if spec['pool'] else None)
        return book, dict(width_median=float(np.median(sizes)), width_max=int(max(sizes)), retries=retries)
    spec = ARMS[name]
    if 'cooldown' in spec:
        picks = picks_with_cooldown(R, codes, days, spec['cooldown'])
        book, _, _ = M.entry_book(A, picks, **M.E6['E6c'], pullback=M.E8['E8c']['pullback'])
        return book, dict(picks=picks)
    line = A.setdefault(spec['exit'], ema(A['close'], 21 if spec['exit'] == 'e21' else 50))
    book, sizes = persistent_book(A, R['picks'], line, spec['width'], spec['renew'])
    return book, dict(width_median=float(np.median(sizes)), width_max=int(max(sizes)))


def extra(trades, master, his):
    closed = [t for t in trades if t.get('exit')]
    pnl = sorted((t['pnl'] for t in closed), reverse=True)
    codes = {t['code'] for t in trades}
    def near(a, b, n):
        return abs((date.fromisoformat(a)-date.fromisoformat(b)).days) <= n
    overlap = sum(any(m['code'] == t['code'] and near(m['entry'], t['entry'], 3) for m in master) for t in trades)
    his_hit = sum(any(t['code'] == code and near(t['entry'], day, 5) and t['pnl'] > 0 for t in trades)
                  for code, day in his)
    return dict(pnl_sum=sum(pnl), pnl_sum_ex_top1=sum(pnl[1:]), pnl_sum_ex_top3=sum(pnl[3:]),
                r15=sum(t['r'] >= 15 for t in closed), trades=len(trades), tickers=len(codes),
                per_ticker=len(trades)/max(1, len(codes)), master_overlap=overlap/max(1, len(trades)),
                his_bought_won=his_hit, his_total=len(his))


def main(arms, spans=('train',)):
    from studies.martin_luk import e13_research as E13, e14_research as E14, e15_research as E15, e1_research as E
    st, A, cfg = E15.setup()
    st.build(A, dict(cfg, candidate='K2'))
    original = A['_e14_base']
    R = st.selected(A)
    his = [('US.'+r['ticker'], r['entry_date']) for r in csv.DictReader(open(M.STUDY.ledger, encoding='utf-8'))
           if r['side'] == 'long' and r['entry_date'][:4] in ('2024', '2025')]
    master = json.loads((M.STUDY.root/'reports/e15_work/master_swap/train/C062_2024_trades.json').read_text())
    OUT.mkdir(exist_ok=True)
    summary_path = OUT/'summary.json'
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    spans_map = {'train': E.TRAIN, '2026': E.VALIDATE, 'full': (E.TRAIN[0], E.VALIDATE[1])}
    with ExitStack() as quiet:
        for mod in (E13, E14, E15):
            for fn in ('baseline_check', 'update_checks'):
                if hasattr(mod, fn):
                    quiet.enter_context(patch.object(mod, fn, lambda *a, **k: None))
        for name in arms:
            if name == 'BASE':
                book, info = original[0], {}
            else:
                book, info = arm_book(A, R, name, original[0])
            mask = np.zeros_like(original[2])
            for d, row in enumerate(book):
                for e in row:
                    mask[d, e[1]] = True
            A['_e14_base'] = (book, arm_rules(original[1], name), mask, original[3])
            A.pop('_e15_books', None)
            for span_name in spans:
                span = spans_map[span_name]
                legs = E15.B.main_legs(A, R['picks'], span)
                s = E15.evaluate(st, A, cfg, 'C062', legs, span, OUT/f'{name}_{span_name}')
                trades = json.loads((OUT/f'{name}_{span_name}'/f'C062_{span[0][:4]}_trades.json').read_text())
                row = dict(total=s['total'], by_year=s['by_year'], maxdd=s['maxdd'], account=s['account'],
                           midpoint_his=s.get('midpoint_his'), entries=sum(map(len, book)), **info)
                if span_name == 'train':
                    row.update(extra(trades, master, his))
                summary[f'{name}_{span_name}'] = row
                summary_path.write_text(json.dumps(summary, default=float, indent=1, ensure_ascii=False))
                print(name, span_name, json.dumps({k: row[k] for k in ('total', 'by_year', 'maxdd', 'midpoint_his')},
                                                  default=float), flush=True)
    A['_e14_base'] = original


if __name__ == '__main__':
    from studies import trader_data as TD
    from studies.trader_data import panel as TP
    from studies.martin_luk.e1_board_smoke import offline
    offline()
    build = TP.build
    def existing_load(market, mode=None, version=None, upto=None, **kw):
        return build(TD.dataset(market, mode, version), upto=upto, write_cache=False)
    def read_only(ds, upto=None, cache=True, write_cache=True):
        return build(ds, upto=upto, cache=cache, write_cache=False)
    args = sys.argv[1:]
    spans = tuple(a[len('--span='):] for a in args if a.startswith('--span=')) or ('train',)
    with ExitStack() as s:
        s.enter_context(patch.object(TD, 'load', existing_load))
        s.enter_context(patch.object(TP, 'build', read_only))
        main([a for a in args if not a.startswith('--')] or ['BASE', *ARMS], spans)
