"""One-off pull of regular-session 5m bars (QFQ) for new names; charges the history-kline quota.

Refuses to charge more new symbols than --allow-new (the user approved up to 40 on 2026-09-26).
Run with the OpenD venv from the repository root:

    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.fetch_k5 \
        --names studies/us_0dte_picks/notes/p3_validation_names.json --out data/p3-k5-validation-raw --allow-new 35
"""
import argparse
import csv
import json
import logging
from pathlib import Path
import time

logging.disable(logging.CRITICAL)
import futu as ft  # noqa: E402

START, END = '2023-05-01', '2026-09-25'
COLUMNS = ('time_key', 'open', 'high', 'low', 'close', 'volume', 'turnover')


def call(ctx, *args, **kwargs):
    for attempt in range(6):
        time.sleep(0.55)
        result = ctx.request_history_kline(*args, **kwargs)
        if result[0] == ft.RET_OK:
            return result
        message = str(result[1])
        if 'freq' in message.lower() or '频率' in message or 'too many' in message.lower():
            time.sleep(10 * (attempt + 1))
            continue
        raise RuntimeError(message)
    raise RuntimeError('rate limited')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--names', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allow-new', type=int, required=True)
    args = parser.parse_args(argv)
    codes = json.loads(args.names.read_text(encoding='utf-8'))['symbols']
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    log = {'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'window': [START, END], 'rows': {}, 'errors': {}}
    try:
        used, remain, detail = ctx.get_history_kl_quota(get_detail=True)[1]
        charged = {row['code'] for row in detail}
        new = [code for code in codes if code not in charged]
        log.update(quota_before=[used, remain], new_symbols=new)
        if len(new) > args.allow_new or len(new) > remain:
            raise SystemExit('refuse: %d new symbols exceed --allow-new %d or remaining quota %d' % (len(new), args.allow_new, remain))
        (args.out / 'k5').mkdir(parents=True, exist_ok=True)
        for code in codes:
            rows, key = [], None
            try:
                while True:
                    _, frame, key = call(ctx, code, start=START, end=END, ktype=ft.KLType.K_5M, autype=ft.AuType.QFQ,
                                         max_count=1000, page_req_key=key, extended_time=False)
                    rows += [{field: row[field] for field in COLUMNS} for row in frame.to_dict('records')]
                    if key is None:
                        break
            except RuntimeError as exc:
                log['errors'][code] = str(exc)
                continue
            with (args.out / 'k5' / (code.split('.', 1)[1] + '.csv')).open('w', newline='', encoding='utf-8') as handle:
                writer = csv.DictWriter(handle, COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            log['rows'][code] = len(rows)
            print(code, len(rows), flush=True)
        log['quota_after'] = list(ctx.get_history_kl_quota()[1][:2])
    finally:
        ctx.close()
        log['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({key: log.get(key) for key in ('quota_before', 'quota_after')}), flush=True)


if __name__ == '__main__':
    main()
