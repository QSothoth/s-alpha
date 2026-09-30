"""One-off pull of OpenD unusual option events (rolling ~1 year) per underlying, read-only.

No history-kline quota.  Raw pages are kept per symbol.  Run with the OpenD venv from the
repository root, with a JSON list of codes:

    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.fetch_option_events \
        --codes names.json --out data/p3-option-events-raw
"""
import argparse
import json
import logging
from pathlib import Path
import time

logging.disable(logging.CRITICAL)
import futu as ft  # noqa: E402


def fetch(ctx, code):
    rows, page, pages, total = [], None, 0, None
    for attempt in range(40):
        time.sleep(1.2)
        result = ctx.get_option_event(ft.OptionMarket.US_SECURITY, count=300, page=page, filter_list=[
            ft.OptionEventFilter(ft.EventIndicatorType.OWNER_LIST, security_list=[code])])
        if result[0] != ft.RET_OK:
            message = str(result[1])
            if 'freq' in message.lower() or '频率' in message or 'too many' in message.lower():
                time.sleep(10)
                continue
            raise RuntimeError(message)
        data = result[1]
        rows += data['event_list'].to_dict('records')
        total, page, pages = data['all_count'], data['next_page'], pages + 1
        if not page:
            return {'code': code, 'all_count': total, 'pages': pages, 'rows': rows}
    raise RuntimeError('too many pages or retries')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--codes', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    codes = json.loads(args.codes.read_text(encoding='utf-8'))
    args.out.mkdir(parents=True, exist_ok=True)
    log = {'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'symbols': len(codes), 'errors': {}, 'rows': {}}
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        for index, code in enumerate(codes, 1):
            path = args.out / (code.split('.', 1)[1] + '.json')
            if path.exists():
                continue
            try:
                payload = fetch(ctx, code)
            except RuntimeError as exc:
                log['errors'][code] = str(exc)
                continue
            path.write_text(json.dumps(payload, default=str, ensure_ascii=False), encoding='utf-8')
            log['rows'][code] = len(payload['rows'])
            if index % 50 == 0:
                print(index, 'of', len(codes), 'errors', len(log['errors']), flush=True)
    finally:
        ctx.close()
        log['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        (args.out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'symbols': len(codes), 'errors': len(log['errors'])}), flush=True)


if __name__ == '__main__':
    main()
