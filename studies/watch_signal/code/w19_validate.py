"""One-shot W19 C1 validation on the preregistered untouched 2024H1 window."""
import argparse
import json
import resource
import time
from pathlib import Path

import w13_score as w13
import w15_market_score as w15
import w16_validate as w16
import w19_overall_strength as w19

ROOT = Path(__file__).resolve().parents[3]
START, END = '2024-01-02', '2024-05-31'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--train-bars', type=Path, default=ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz')
    parser.add_argument('--train-index', type=Path, default=ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    parser.add_argument('--validation-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w19_2024h1_1m.csv.gz')
    args = parser.parse_args()
    started = time.monotonic()
    train_hsi, train_refs = w15.load_hsi(args.train_index)
    train = list(w19.events(args.train_bars, train_hsi, train_refs, '2025-12-01', '2026-08-14'))
    fitted = w19.fit(train)
    quality = w16.quality_scan(args.validation_bars)
    hsi, refs = w15.load_hsi(args.validation_bars)
    validation = list(w19.events(
        args.validation_bars, hsi, refs, START, END, set(quality)))
    rows = w19.score(validation, fitted)['C1']
    result = w19.evaluate(rows, hsi, refs)
    bucket_counts = {str(group): len(values) for group, values in sorted(fitted[0].items())}
    sample_gate = min(bucket_counts.values()) >= 2000
    result['gates']['sample'] = result['gates']['sample'] and sample_gate
    result['pass_all'] = all(result['gates'].values())
    print(json.dumps(w13.w12.clean(dict(
        candidate='C1 weakest', validation_window=[START, END],
        training_n=len(train), training_bucket_counts=bucket_counts,
        validation_days=len({row[0] for row in validation}),
        excluded_invalid_codes=quality, result=result,
        predictive_claim_allowed=False,
        elapsed_seconds=time.monotonic() - started,
        max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
        ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
