"""One-shot W21 descriptive validation on previously unused 2023H2 data."""
import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

import w13_score as w13
import w15_market_score as w15
import w16_validate as w16
import w20_composite_strength as w20

ROOT = Path(__file__).resolve().parents[3]
START, END = '2023-07-03', '2023-12-29'


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation-bars', type=Path,
                        default=ROOT / 'studies/watch_signal/data/w21_2023h2_1m.csv.gz')
    args = parser.parse_args()
    started = time.monotonic()
    train_hsi, train_refs = w15.load_hsi(ROOT / 'data/watch-hk-index1m-v1/index_1m.csv.gz')
    train = list(w20.events(ROOT / 'data/watch-hk1m-train-v1/bars_1m.csv.gz',
                            train_hsi, train_refs, '2025-12-01', '2026-08-14'))
    fitted = w20.fit(train)
    training_counts = dict(
        buckets={str(group): len(values) for group, values in sorted(fitted['price'].items())},
        triggers={name: len(fitted['trigger'][name]) for name in w20.TRIGGERS})
    training_gate = (min(training_counts['buckets'].values()) >= 2000
                     and min(training_counts['triggers'].values()) >= 10000)
    quality = w16.quality_scan(args.validation_bars)
    hsi, refs = w15.load_hsi(args.validation_bars)
    validation = list(w20.events(args.validation_bars, hsi, refs, START, END, set(quality)))
    result = w20.evaluate(w20.score(validation, fitted)['C1'], hsi, refs)
    descriptive_gates = {name: result['gates'][name]
                         for name in ('sample', 'centered', 'intrinsic', 'extremes')}
    descriptive_gates['training'] = training_gate
    print(json.dumps(w13.w12.clean(dict(
        candidate='C1 median', definition='descriptive trend + structure + HSI B/S strength',
        validation_window=[START, END], validation_file=str(args.validation_bars),
        validation_sha256=sha256(args.validation_bars), training_n=len(train),
        training_counts=training_counts, validation_n=len(validation),
        validation_days=len({row[0] for row in validation}), excluded_invalid_codes=quality,
        result=result, descriptive_gates=descriptive_gates,
        descriptive_pass=all(descriptive_gates.values()), predictive_claim_allowed=False,
        elapsed_seconds=time.monotonic() - started,
        max_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)),
        ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
