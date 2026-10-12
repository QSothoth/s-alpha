"""SV2 step 1: calibrate the option proxy on already-used real 0DTE data (notes/SV2_PREREG.md).

    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.sv2_calibrate --out studies/us_0dte_picks/reports/sv2_calibration.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from custody.dataset import Dataset
from custody.evaluate import ACCOUNT_BUDGET_USD, run_strategy
from custody.registry import Registry

from .proxy import measure_k_w, proxy_case
from .sv1 import NEW, OLD, gap_side

DATASETS = ('data/custody-0dte-v6.1', 'data/custody-eval-2026-09-18-v2')
IV_CACHE = Path('data/sv2-calibration-iv.json')
LIMITS = {'C1_same_entry_minute': 0.90, 'C2_sign_agreement': 0.75, 'C3_spearman': 0.70, 'C4_mean_bias_abs': 0.05}


def fetch_ivs(symbols, start='2026-07-20', end='2026-09-18'):
    if IV_CACHE.exists():
        return json.loads(IV_CACHE.read_text(encoding='utf-8'))
    import logging
    logging.disable(logging.CRITICAL)
    import futu as ft
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    out = {}
    try:
        for code in sorted(symbols):
            ret, frame, *_ = ctx.get_option_underlying_his_volatility(code, begin_time=start, end_time=end)
            if ret != 0:
                raise RuntimeError(str(frame))
            out[code] = {str(r['time'])[:10]: float(r['iv']) / 100 for r in frame.to_dict('records') if r['iv'] not in (None, '')}
    finally:
        ctx.close()
    IV_CACHE.write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def previous_iv(ivs, symbol, day):
    rows = {d: v for d, v in ivs.get(symbol, {}).items() if d < day and v > 0}
    return rows[max(rows)] if rows else None


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2
        i = j + 1
    return ranks


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return cov / (va * vb) ** 0.5 if va and vb else None


def compare(real, proxy):
    either = [(r, p) for r, p in zip(real, proxy) if r['entry'] or p['entry']]
    same_minute = sum(bool(r['entry'] and p['entry'] and r['entry_signal']['minute'] == p['entry_signal']['minute'])
                      for r, p in either)
    both = [(r['net_return'], p['net_return']) for r, p in zip(real, proxy)
            if r['net_return'] is not None and p['net_return'] is not None]
    rr, pp = [x for x, _ in both], [y for _, y in both]
    sign = sum((x > 0) == (y > 0) for x, y in both)
    bias = (sum(pp) - sum(rr)) / len(both) if both else None
    out = {'traded_either': len(either), 'traded_both': len(both),
           'C1_same_entry_minute': same_minute / len(either) if either else None,
           'C2_sign_agreement': sign / len(both) if both else None,
           'C3_spearman': spearman(rr, pp),
           'C4_mean_bias_abs': abs(bias) if bias is not None else None, 'mean_bias': bias,
           'real_mean_return': sum(rr) / len(rr) if rr else None, 'proxy_mean_return': sum(pp) / len(pp) if pp else None}
    out['passed'] = all(out[k] is not None and (out[k] <= v if k == 'C4_mean_bias_abs' else out[k] >= v) for k, v in LIMITS.items())
    return out


def total_usd(trades):
    return sum(t['net_return'] * ACCOUNT_BUDGET_USD for t in trades if t['net_return'] is not None)


def calibrate():
    registry = Registry()
    new, old = registry.get(NEW), registry.get(OLD)
    datas = []
    for path in DATASETS:
        ds = Dataset(path)
        datas += [ds.load(c) for c in ds.cases]
    ivs = fetch_ivs({d.case.symbol for d in datas})
    case_iv = [previous_iv(ivs, d.case.symbol, d.case.trade_date) for d in datas]
    k, w, measured = measure_k_w(datas, case_iv)
    keep = [i for i, v in enumerate(case_iv) if v is not None]
    real = [datas[i] for i in keep]
    proxy = [proxy_case(datas[i], case_iv[i], k, w) for i in keep]
    result = {'preregistration': 'studies/us_0dte_picks/notes/SV2_PREREG.md', 'datasets': DATASETS,
              'cases': len(datas), 'cases_with_iv': len(keep), 'k': k, 'w': w, 'cases_measured': measured,
              'limits': LIMITS, 'strategies': {}}
    for item in (new, old):
        r = [run_strategy(d, item) for d in real]
        p = [run_strategy(d, item) for d in proxy]
        result['strategies'][item['strategy_id']] = compare(r, p)
        if item is new:
            flows = {'N_real': total_usd(r), 'N_proxy': total_usd(p)}
        else:
            gap = [i for i, d in enumerate(real) if gap_side(d) == d.case.direction]
            flows.update(O_real=total_usd([r[i] for i in gap]), O_proxy=total_usd([p[i] for i in gap]))
    flows['N_minus_O_real'] = flows['N_real'] - flows['O_real']
    flows['N_minus_O_proxy'] = flows['N_proxy'] - flows['O_proxy']
    result['flows_report_only'] = flows
    result['passed'] = all(s['passed'] for s in result['strategies'].values())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit('refuse: calibration runs once; %s exists' % args.out)
    result = calibrate()
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
