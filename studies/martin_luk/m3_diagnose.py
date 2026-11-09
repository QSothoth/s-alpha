"""Evaluation-only M2A lot attribution and dependency-free SVG timelines."""
from __future__ import annotations

from collections import Counter
import csv
from html import escape
from pathlib import Path

import numpy as np

from . import m3_research as R

OUT, HOME = R.OUT, R.HOME
NAMES = dict(a='首仓不足/加仓迟（50%上限情景）', a75='75%上限情景',
    a_delay='实际加仓的买价延迟', b='止损后峰前没有再买', b_returned='止损后曾再买（原lot缺口）',
    c_trim='分批减仓', c_trail='跟踪线卖出', d='敞口/换仓强制卖出', e='首仓/再试买晚',
    peak_close='峰值高点与峰日收盘差', horizon='训练结束尚未到峰', other='其他退出')


def svg(path, g, prices, events, days):
    """One stock and one bounded window, no plotting dependency or market-wide allocation."""
    lo = max(0, min([g['first']]+[e['index'] for e in events])-4)
    hi = min(len(days)-1, g['peak']+3)
    ix = np.arange(lo, hi+1)
    c = prices['c'][lo:hi+1]
    ymin = float(np.nanmin(prices['l'][lo:hi+1]))*.94
    ymax = max(g['top'], float(np.nanmax(prices['h'][lo:hi+1])))*1.08
    x = lambda d: 65+(d-lo)*1000/max(1, hi-lo)
    y = lambda p: 320-255*(p-ymin)/(ymax-ymin)
    body = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 420">',
        '<rect width="1160" height="420" fill="white"/>',
        '<g font-family="sans-serif" font-size="12">',
        f'<text x="24" y="24">{escape(g["key"])} · M2A · capital unit = initial equity 1</text>']
    for k in range(5):
        p = ymin+(ymax-ymin)*k/4
        body += [f'<path d="M65 {y(p):.2f}H1080" stroke="#ddd"/>',
                 f'<text x="5" y="{y(p):.2f}">{p:.2f}</text>']
    for d in ix:
        if np.isfinite(prices['h'][d]) and np.isfinite(prices['l'][d]):
            body.append(f'<path d="M{x(d):.2f} {y(prices["l"][d]):.2f}V{y(prices["h"][d]):.2f}" stroke="#bac0c8"/>')
    pts = ' '.join(f'{x(d):.2f},{y(p):.2f}' for d, p in zip(ix, c) if np.isfinite(p))
    body.append(f'<polyline points="{pts}" fill="none" stroke="#202b40" stroke-width="2"/>')
    from . import luk
    for n, color in ((9, '#b08a18'), (21, '#8b63b6')):
        line = luk.ema(prices['c'].reshape(-1, 1), n)[:, 0]
        pts = ' '.join(f'{x(d):.2f},{y(line[d]):.2f}' for d in ix if np.isfinite(line[d]))
        body.append(f'<polyline points="{pts}" fill="none" stroke="{color}"/>')
    for index, label in ((g['first'], 'anchor'), (g['peak'], 'peak')):
        body += [f'<path d="M{x(index):.2f} 45V330" stroke="#555" stroke-dasharray="4,4"/>',
            f'<text x="{x(index)+3:.2f}" y="47">{label} {days[index]}</text>']
    cut = int(np.searchsorted(days, R.TRAIN[1], side='right'))
    if lo <= cut <= hi:
        body += [f'<rect x="{x(cut):.2f}" y="52" width="{1080-x(cut):.2f}" height="278" fill="#eee" opacity=".55"/>',
                 f'<text x="{x(cut)+3:.2f}" y="80">past training end: labels only</text>']
    for e in events:
        color = '#087f45' if e['action'] in ('entry', 'add') else '#bb3038'
        body.append(f'<circle cx="{x(e["index"]):.2f}" cy="{y(e["price"]):.2f}" r="4" fill="{color}"><title>'
            f'{escape(e["time"]+" "+e["action"])} price={e["price"]:.3f} shares={e["shares"]:.6f}</title></circle>')
        label = 'A' if e['action'] == 'add' else 'B' if e['action'] == 'entry' else 'S'
        body.append(f'<text x="{x(e["index"])+4:.2f}" y="{y(e["price"])-6:.2f}" fill="{color}">{label}</text>')
    for d in np.linspace(lo, hi, min(7, hi-lo+1), dtype=int):
        body.append(f'<text x="{x(d)-30:.2f}" y="350">{days[d]}</text>')
    body += ['<text x="65" y="382">B entry · A add · S sale/mark; hover for exact lot size; gold EMA9 · purple EMA21</text>',
             '<text x="65" y="402">Peak high is an evaluation ceiling. EOD strategies cannot assume that high is tradable.</text>', '</g></svg>']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(body)+'\n')


def case(g, rows, trades, curve, days, prices, group, number):
    di = {d: i for i, d in enumerate(days)}
    ids = sorted({r['trade'] for r in rows})
    events = [dict(e, index=di[e['time']], trade=i) for i in ids for e in trades[i]['executions']]
    events.sort(key=lambda e: (e['index'], e['trade']))
    buys = [e for e in events if e['action'] in ('entry', 'add') and e['index'] < g['peak']]
    amounts, detail = Counter(), []
    anchor = float(prices['c'][g['first']])
    signed_timing = sale_gap = fees = pnl = anchored = 0.
    for r in rows:
        sale = next(e for e in events if e['trade'] == r['trade'] and e['index'] == r['exit'] and
                    e['action'] not in ('entry', 'add') and abs(e['price']-r['exit_price']) < 1e-8)
        buy = trades[r['trade']]['executions'][r['source']]
        after = [e for e in buys if e['index'] > r['exit']]
        end_price = r.get('h_exit_price') if r.get('bucket') == 'T1' else r['exit_price']
        if r['open'] and r['exit'] < g['peak']:
            reason = 'horizon'
        elif r['exit'] >= g['peak']:
            reason = 'peak_close'
        elif sale['action'] in ('stop', 'gap_stop', 'close_stop'):
            reason = 'b_returned' if after else 'b'
        elif sale['action'] in ('trim', 'signal_trim', 'signal_trim2', 'day_trim'):
            reason = 'c_trim'
        elif sale['action'] in ('trail', 'trail_open'):
            reason = 'c_trail'
        elif sale['action'] in ('gross', 'make_room', 'rotate'):
            reason = 'd'
        else:
            reason = 'other'
        missed = r['shares']*max(0., g['top']-end_price)
        timing = r['shares']*(r['price']-anchor)
        amounts[reason] += missed
        amounts['a_delay' if buy['action'] == 'add' else 'e'] += max(0., timing)
        h = r['h_pnl'] if r.get('bucket') == 'T1' else r['pnl']
        # Exact identity only for funded H pieces; pre-anchor exited pieces are shown separately.
        if r.get('bucket') == 'T1':
            signed_timing += timing
            sale_gap += r['shares']*(g['top']-end_price)
            this_fees = r['shares']*(end_price-r['price'])-h
            fees += this_fees
            pnl += h
            anchored += r['shares']*(g['top']-anchor)
        detail.append(dict(trade=r['trade'], source=r['source'], code=g['code'], leg=g['key'],
            entry=days[r['entry']], exit=days[r['exit']], action=buy['action'], exit_action=sale['action'],
            price=r['price'], exit_price=end_price, shares=r['shares'], bucket=r.get('bucket'),
            potential_remaining=r['shares']*(g['top']-r['price']), actual_h_pnl=h,
            missed_peak=missed, reason=reason, timing=timing, reentered_before_peak=bool(after)))
    equity = dict(zip(curve['days'], curve['equity']))
    sizing = None
    if buys:
        first = min(buys, key=lambda e: e['index'])
        initial = trades[first['trade']]
        unit = abs(initial['fill']-initial['stop'])
        begin, end = first['index']+1, min(g['peak'], int(np.searchsorted(days, R.TRAIN[1], side='right')))
        proof = next((d for d in range(begin, end) if prices['c'][d] >= first['price']+unit), None)
        if proof is not None:
            active = sum(e['shares']*(1 if e['action'] in ('entry', 'add') else -1) for e in events if e['index'] <= proof)
            price = float(prices['c'][proof])
            eq = equity[days[proof]]
            for cap, key in ((.5, 'a'), (.75, 'a75')):
                missing = max(0., cap*eq/price-active)
                amounts[key] = missing*max(0., g['top']-price)
            sizing = dict(day=days[proof], close=price, shares=active, equity=eq,
                actual_weight=active*price/eq, hypothetical_target=.5,
                assumption='unfunded size held to peak, no costs, gross/risk constraints or intervening stops; nonadditive ceiling')
    error = anchored-pnl-signed_timing-sale_gap-fees
    assert abs(error) < 1e-8, error
    filename = f'timelines/{group}_{number:03d}_{g["code"]}.svg'
    svg(OUT/filename, g, prices, events, days)
    return dict(key=g['key'], code=g['code'], year=days[g['first']][:4], group=group,
        anchor=days[g['first']], peak=days[g['peak']], anchor_price=anchor, peak_price=g['top'],
        covered=g.get('covered'), capture_total=g.get('capture_total'), lots=detail,
        events=events, amounts=amounts, sizing=sizing, timeline=filename,
        identity=dict(anchored_potential=anchored, actual_h_pnl=pnl, signed_timing=signed_timing,
            sale_gap=sale_gap, fees=fees, error=error))


def main():
    R.once('lot_diagnosis')
    folder = HOME/'reports/m2_work/candidates/M2A'
    metrics, trades, curve = (R.read(folder/(n+'.json')) for n in ('metrics', 'trades', 'curve'))
    frozen = R.read(HOME/'notes/legs_frozen.json')
    days, prices = frozen['calendar'], R.M.Y1.Prices()
    labels = {g['key']: g for g in frozen['legs']}
    cases = []
    for i, g in enumerate(metrics['legs']):
        if not g['any']:
            continue
        rows = [r for r in metrics['lots'] if r['leg'] == g['key']]
        cases.append(case(dict(labels[g['key']], **g), rows, trades, curve, days, prices[g['code']], 'his', i))
    # All ordinary >=30% future opportunities on executed trades, grouped by stock and actual peak.
    # Exclude overlapping his windows; this is evaluation only and never feeds candidate decisions.
    di = {d: i for i, d in enumerate(days)}
    cutoff = di[R.TRAIN[1]]
    groups = {}
    for i, t in enumerate(trades):
        start = di[t['entry']]
        p = prices[t['code']]
        end = min(start+60, cutoff)
        if start >= end or not np.isfinite(p['h'][start:end+1]).any():
            continue
        peak = start+int(np.nanargmax(p['h'][start:end+1]))
        top = float(p['h'][peak])
        if top/t['fill']-1 < .3 or any(g['code'] == t['code'] and
                max(start, g['first']-3) <= min(peak, g['peak']) for g in frozen['legs']):
            continue
        key = (t['code'], peak)
        group = groups.setdefault(key, dict(first=start, peak=peak, top=top, code=t['code'], ids=[]))
        group['first'] = min(start, group['first'])
        group['ids'].append(i)
    for n, g in enumerate(groups.values()):
        ids = set(g.pop('ids'))
        g['key'] = f'{g["code"]}:{days[g["first"]]}:{days[g["peak"]]}'
        # Normalize ordinary pieces to the same end-of-leg mark, using existing real closes.
        rows = []
        for row in metrics['lots']:
            if row['trade'] not in ids or row['entry'] >= g['peak']:
                continue
            r = dict(row)
            stop = min(r['exit'], g['peak'])
            px = r['exit_price'] if r['exit'] <= g['peak'] else float(prices[g['code']]['c'][stop])
            h = r['pnl'] if r['exit'] <= g['peak'] else r['shares']*(px-r['price'])-r['buy_fee']
            r.update(bucket='T1', h_exit_price=px, h_pnl=h)
            rows.append(r)
        if rows:
            cases.append(case(g, rows, trades, curve, days, prices[g['code']], 'other', n))
    totals = {}
    for group in ('his', 'other'):
        total = Counter()
        selected = [c for c in cases if c['group'] == group]
        for c in selected:
            total.update(c['amounts'])
        totals[group] = dict(cases=len(selected), lots=sum(len(c['lots']) for c in selected), amounts=total,
            stopped_without_return=sum(r['reason'] == 'b' for c in selected for r in c['lots']),
            sizing_observed=len([c for c in selected if c['sizing']]),
            max_identity_error=max((abs(c['identity']['error']) for c in selected), default=0.))
    R.write('lot_diagnosis.json', dict(cases=cases, totals=totals, names=NAMES,
        units='initial equity=1; positive potential only; actual-sale categories partition sale gap, sizing/timing do not add to them',
        ordinary_rule='every executed M2A trade with >=30% high within min(60 sessions, training end); group same stock/peak; exclude any his-window overlap',
        primary_metric='Y1 capture uses lot entry notional times anchor gain; anchored-gap identity here is a separate money diagnostic'))
    for group in ('his', 'other'):
        path = OUT/('lot_diagnosis_'+group+'.csv')
        rows = [r for c in cases if c['group'] == group for r in c['lots']]
        with path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['leg'])
            writer.writeheader()
            writer.writerows(rows)
    render(cases)
    R.log('lot diagnosis: '+str({k: (v['cases'], v['lots'], dict(v['amounts'])) for k, v in totals.items()}))


def render(cases):
    html = ['<!doctype html><meta charset="utf-8"><title>M3 全部逐段时间线</title>',
        '<style>body{font:15px sans-serif;max-width:1200px;margin:30px auto}table{border-collapse:collapse}'
        'td,th{border:1px solid #ccc;padding:5px}img{width:100%}section{margin:45px 0}</style>',
        '<h1>M2A 逐段、逐 lot 诊断</h1><p>单位为初始本金1；峰值是评测上限，不能视为可成交收益。</p>',
        '<p>绿色 B=首仓或再试，A=加仓；红色 S=减仓、离场或期末估值。全部逐lot金额见上级目录CSV/JSON。</p>']
    for c in cases:
        html += [f'<section><h2>{"本人段" if c["group"] == "his" else "其他大赢家机会"}：{escape(c["key"])}</h2>',
            f'<img src="{Path(c["timeline"]).name}" alt="价格、起点峰值及实际买卖时间线">',
            '<table><tr><th>日</th><th>动作</th><th>价格</th><th>股数</th><th>本金金额</th></tr>']
        for e in c['events']:
            html.append('<tr>'+''.join(f'<td>{escape(str(v))}</td>' for v in
                (e['time'], e['action'], f'{e["price"]:.3f}', f'{e["shares"]:.6f}', f'{e["shares"]*e["price"]:.4f}'))+'</tr>')
        html += ['</table><p>'+escape('；'.join(f'{NAMES[k]}={v:.3f}' for k, v in c['amounts'].items()))+'</p></section>']
    (OUT/'timelines/index.html').write_text('\n'.join(html)+'\n')


if __name__ == '__main__':
    R.offline()
    import sys
    if '--render' in sys.argv:
        render(R.read(OUT/'lot_diagnosis.json')['cases'])
    else:
        main()
