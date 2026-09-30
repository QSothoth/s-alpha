"""One-off P2 pull: earnings history and current expiry dates per stock, read-only OpenD.

No history-kline quota.  Raw responses are kept per symbol; only dates and publication
types are used by the study.  Run with the OpenD venv from the repository root:

    /opt/futu-opend/venv/bin/python -m studies.us_0dte_picks.fetch_events --out data/p2-events-raw
"""
import argparse
import json
import logging
from pathlib import Path
import time

logging.disable(logging.CRITICAL)
import futu as ft  # noqa: E402

NOTES = Path(__file__).resolve().parents[1] / 'archive' / 'us_preopen_bias' / 'notes'
UNIVERSES = (NOTES / 'universe_stocks300.json', NOTES / 'universe_stocks301_600.json',
             Path(__file__).with_name('notes') / 'universe_stocks601_900.json')
PERIODS = 16


def call(ctx, name, *args, **kwargs):
    for attempt in range(6):
        time.sleep(0.7)
        result = getattr(ctx, name)(*args, **kwargs)
        if result[0] == ft.RET_OK:
            return result[1]
        message = str(result[1])
        if 'freq' in message.lower() or '频率' in message or 'too many' in message.lower():
            time.sleep(10 * (attempt + 1))
            continue
        return {'error': message}
    return {'error': 'rate limited'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    codes = list(dict.fromkeys(row['code'] for path in UNIVERSES
                               for row in json.loads(path.read_text(encoding='utf-8'))['symbols']))
    for sub in ('expiry', 'earnings'):
        (args.out / sub).mkdir(parents=True, exist_ok=True)
    ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
    log = {'started': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'symbols': len(codes), 'errors': {}}
    try:
        for index, code in enumerate(codes, 1):
            name = code.split('.', 1)[1] + '.json'
            for sub, endpoint, kwargs in (('expiry', 'get_option_expiration_date', {}),
                                          ('earnings', 'get_financials_earnings_price_move', {'period_count': PERIODS})):
                path = args.out / sub / name
                if path.exists():
                    continue
                data = call(ctx, endpoint, code, **kwargs)
                if isinstance(data, dict):
                    log['errors']['%s %s' % (sub, code)] = data['error']
                    continue
                path.write_text(json.dumps(data.to_dict('records'), default=str, ensure_ascii=False), encoding='utf-8')
            if index % 50 == 0:
                print(index, 'of', len(codes), 'errors', len(log['errors']), flush=True)
    finally:
        ctx.close()
    log['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    (args.out / 'fetch_log.json').write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'symbols': len(codes), 'errors': len(log['errors'])}), flush=True)


if __name__ == '__main__':
    main()
