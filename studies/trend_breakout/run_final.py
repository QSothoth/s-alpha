"""Replay the final scheme of one market and list its state at the data end.

    OPENBLAS_NUM_THREADS=1 PYTHONUTF8=1 /opt/futu-opend/venv/bin/python -m studies.trend_breakout.run_final cn

Writes reports/final_<market>.json. Expected (2026-10 research, local data to 2026-10-09):
cn +113.0% / -16.5%, us +55.9% / -7.7%, hk +166.2% / -15.7%.
"""
from __future__ import annotations

import argparse
import json

import numpy as np

from .final import SCHEMES, Book

HERE = __import__('pathlib').Path(__file__).resolve().parent
EXPECTED = {'cn': 1.1300, 'us': .5590, 'hk': 1.6617}


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('market', choices=tuple(SCHEMES))
    market = parser.parse_args().market
    np.seterr(invalid='ignore', divide='ignore')
    book = Book(market)
    scheme = SCHEMES[market]
    metrics, account = book.run(scheme)
    if abs(metrics['total_return'] - EXPECTED[market]) > 5e-4:
        raise SystemExit(f'{market}: total return {metrics["total_return"]:.4f} differs from the research '
                         f'result {EXPECTED[market]:.4f}')
    result = {'market': market, 'scheme': scheme, 'metrics': metrics, 'hold_pool': book.hold_pool(),
              'state': book.holdings(scheme, account)}
    (HERE / f'reports/final_{market}.json').write_text(json.dumps(clean(result), ensure_ascii=False, indent=1) + '\n')
    m = metrics
    print(f"{market}: {m['total_return']:.1%} / {m['max_drawdown']:.1%}, alpha {m['alpha_annual']:.1%} "
          f"(t {m['t']:.1f}), {m['trades']} trades, median hold {m['median_hold_weeks']} weeks")
    s = result['state']
    print(f"data end {s['data_end']}, market ok {s['market_ok']}, {len(s['positions'])} positions, "
          f"{len(s['next_week_candidates'])} candidates")


if __name__ == '__main__':
    main()
