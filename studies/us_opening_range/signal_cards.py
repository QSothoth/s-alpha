"""Export every frozen RG1 event as a causal SVG card; never recalculate labels."""
import argparse
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from html import escape
import heapq
from itertools import groupby
import json
import math
from pathlib import Path
import shutil

from custody.dataset import sha256_file
from custody.models import ET
from . import reverse_replay as source


EVENTS = Path('data/rg1-asset-transfer-signals-20260926.jsonl')
EVENTS_SHA256 = '8bbb1a564c2b403916b40ed5c6f0b7c4be01e6882a535784ee0b4c6569929be4'
EVENT_COUNT = 118
CODE_PINS = {
    'studies/us_opening_range/reverse_replay.py': 'ceaf7333badaf8764507cc96bd8b77ce1d5946a824fae2244f3f8c6eafa32f73',
    'studies/us_opening_range/daily_replay.py': '80ebf94b35e99ef8f28af172e01c4f00bc2389c3341b07e875a4b5954241955d',
    'studies/us_opening_range/event_signals.py': 'c891d118a5fa8995f8ac77825d33c286ee3c5d9686f373b6a672037880c81d44',
    'studies/us_opening_range/daily_signals.py': '1568d3ac0f4cc65270be73ceec9e157789f5a4577fcc99882e8b3511963ef91a',
    'custody/marketdata.py': 'c1b8259982eac9e70798f1ee731582853bb1c43d8a3f7024529a8ced3d4827c1',
    'custody/models.py': '9546f1bb6c565e50fab35ff3ac91f8152d80f6816dc8ef53c987aefa23647f9a',
    'custody/dataset.py': 'c9b4e398217eb278bf8999fdf2fe853969e291f92bdd1f38e2c097c0ddd3a924'}
CONTEXT_KEYS = ('symbol', 'time', 'direction', 'original_direction', 'reference', 'range_high20',
                'range_low20', 'key_level', 'snapshot_minutes', 'atr', 'gap_atr', 'rvol', 'activity_reason')


def read_events(path):
    if Path(path).is_symlink() or sha256_file(path) != EVENTS_SHA256:
        raise ValueError('RG1 events checksum mismatch')
    events, seen = [], set()
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            event = json.loads(line)
            stamp = datetime.fromisoformat(event['time'])
            key = event['time'], event['symbol']
            if (len(events) >= EVENT_COUNT or key in seen or event['candidate'] != source.CANDIDATE
                    or event['symbol'] not in {'US.' + name for name in source.SYMBOLS}
                    or stamp.tzinfo is None or not source.START <= stamp.astimezone(ET).date().isoformat() <= source.END
                    or stamp != stamp.astimezone(ET).replace(hour=9, minute=30, second=0, microsecond=0)
                    + timedelta(minutes=event['snapshot_minutes'])
                    or event['snapshot_minutes'] not in (15, 20, 30)
                    or event['direction'] not in ('LONG', 'SHORT')):
                raise ValueError('unexpected RG1 event identity/count/time')
            seen.add(key)
            events.append(event)
    if len(events) != EVENT_COUNT:
        raise ValueError('expected exactly 118 RG1 events')
    return sorted(events, key=lambda event: (event['time'], event['symbol']))


def iter_contexts(root, calendar, events):
    """Only 20 preceding daily summaries and a bounded current day per symbol."""
    history = {symbol: deque(maxlen=20) for symbol in source.SYMBOLS}
    selected = {day: list(rows) for day, rows in groupby(events, key=lambda row: row['time'][:10])}
    streams = [source.iter_sessions(Path(root) / ('US.' + symbol + '.csv'), symbol, calendar) for symbol in source.SYMBOLS]
    streams.append(((day, '', None, None) for day in calendar))
    emitted = 0
    for day, records in groupby(heapq.merge(*streams, key=lambda row: (row[0], row[1])), key=lambda row: row[0]):
        if day not in calendar or day > source.END:
            raise ValueError('card context outside the frozen calendar')
        current = {symbol: (bars, complete) for _, symbol, bars, complete in records if symbol}
        for symbol in source.SYMBOLS:
            if symbol not in current:
                history[symbol].clear()
        for event in selected.get(day, []):
            symbol, stamp = event['symbol'].removeprefix('US.'), datetime.fromisoformat(event['time'])
            past = list(history[symbol])
            prefix = source.prefix_at_checkpoint(current.get(symbol, ([], False))[0],
                       {'symbol': event['symbol'], 'trade_date': day}, event['snapshot_minutes'])
            if len(past) != 20 or prefix is None or prefix[-1].close_time != stamp:
                raise ValueError('missing prior 20 sessions or event prefix: ' + str((day, symbol)))
            if (any(bar.close_time >= stamp or bar.close_time.astimezone(ET).date().isoformat() >= day for bar in past)
                    or not all(math.isclose(actual, event[key], rel_tol=1e-12) for key, actual in
                               (('reference', prefix[-1].close), ('range_high20', max(bar.high for bar in past)),
                                ('range_low20', min(bar.low for bar in past))))):
                raise ValueError('event/source context mismatch')
            serialize = lambda bar: asdict(bar) | {'close_time': bar.close_time.isoformat()}
            yield {'event': {key: event.get(key) for key in CONTEXT_KEYS},
                   'daily': [serialize(bar) for bar in past], 'opening': [serialize(bar) for bar in prefix]}
            emitted += 1
        for symbol, (bars, complete) in current.items():
            if complete:
                history[symbol].append(source.aggregate_daily(bars, calendar[day]))
            else:
                history[symbol].clear()
    if emitted != len(events):
        raise ValueError('not every frozen event received a card')


def render_svg(context, title=None, key_level_label='原20日边界', label_overlay=False):
    event = context['event']
    if title is None:
        title = f"UNVALIDATED · {event['symbol']} · {event['time']} · 观察 {event['direction']}（原方向 {event['original_direction']}）"
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 455" role="img">',
             '<title>' + escape(title) + '</title><rect width="1200" height="455" fill="white"/>',
             '<g font-family="sans-serif" font-size="13" fill="#20252b">',
             '<text x="20" y="26">' + escape(title) + '</text>',
             '<text x="20" y="48">仅显示提示时已知数据；左右纵轴独立；不是购买建议，不含未来K线或事后收益。</text>']
    daily_lines = [('20日高', event['range_high20'], '#596b80'), ('20日低', event['range_low20'], '#596b80'),
                   ('参考价', event['reference'], '#8b3fa8')]
    opening_lines = [(key_level_label, event['key_level'], '#596b80'), ('参考价', event['reference'], '#8b3fa8')]
    for x, rows, lines, caption in ((65, context['daily'], daily_lines, '此前20个完整交易日日K'),
                                    (665, context['opening'], opening_lines, '当日已完成5分钟K；截至提示时刻')):
        lower = min([bar['low'] for bar in rows] + [value for _, value, _ in lines])
        upper = max([bar['high'] for bar in rows] + [value for _, value, _ in lines])
        padding = max((upper - lower) * .12, upper * .001)
        low, high = lower - padding, upper + padding
        y = lambda price: 355 - (price - low) / (high - low) * 245
        width, step = 475, 475 / len(rows)
        parts.append(f'<text x="{x}" y="82">{caption}</text><rect x="{x}" y="100" width="475" height="265" fill="none" stroke="#bbb"/>')
        for index in range(5):
            value = low + (high - low) * index / 4
            parts.append(f'<text x="{x - 55}" y="{y(value):.2f}">{value:.2f}</text>')
        for label, price, color in lines:
            parts.append(f'<path d="M{x},{y(price):.2f}h{width}" stroke="{color}" stroke-dasharray="4 3"/>')
            if not label_overlay:
                parts.append(f'<text x="{x + 4}" y="{y(price) - 4:.2f}" fill="{color}">{escape(label)} {price:.4f}</text>')
        for index, bar in enumerate(rows):
            bx = x + step * (index + .5)
            color = '#16836c' if bar['close'] >= bar['open'] else '#c3414a'
            body = min(22, step * .55)
            parts.append(f'<path d="M{bx:.2f},{y(bar["high"]):.2f}V{y(bar["low"]):.2f}" stroke="{color}"/>')
            parts.append(f'<rect x="{bx - body / 2:.2f}" y="{min(y(bar["open"]), y(bar["close"])):.2f}" width="{body:.2f}" height="{max(abs(y(bar["open"]) - y(bar["close"])), 1):.2f}" fill="{color}"/>')
            label = bar['close_time'][:10] if rows is context['daily'] else bar['close_time'][11:16]
            if rows is context['opening'] or index in (0, len(rows) - 1):
                parts.append(f'<text x="{bx:.2f}" y="388" text-anchor="middle">{escape(label)}</text>')
        if label_overlay:
            placed, previous_y = [], 95.
            for desired, label, price, color in sorted((y(price) - 4, label, price, color) for label, price, color in lines):
                previous_y = max(112., desired, previous_y + 17)
                placed.append((previous_y, label, price, color))
            shift = max(0., previous_y - 355)
            for label_y, label, price, color in placed:
                parts.append(f'<text class="key-label" x="{x + 4}" y="{label_y - shift:.2f}" fill="{color}" stroke="white" stroke-width="4" stroke-linejoin="round" paint-order="stroke">{escape(label)} {price:.4f}</text>')
    parts.append('<text x="20" y="425">颜色：绿=收≥开，红=收＜开。20日边界为当时历史高低；参考价为提示收盘价，非成交保证。</text></g></svg>')
    return '\n'.join(parts)


def export(out, events_path=EVENTS, root=source.ROOT):
    out, events_path = Path(out), Path(events_path)
    if out.exists() or out.is_symlink():
        raise ValueError('refusing to overwrite output directory')
    repo = Path(__file__).resolve().parents[2]
    if any(sha256_file(repo / name) != digest for name, digest in CODE_PINS.items()):
        raise ValueError('frozen RG1 source code changed')
    events = read_events(events_path)  # Count/hash preflight happens before creating outputs.
    calendar, inputs = source.load_inputs(root)
    out.mkdir(parents=True)
    with events_path.open('rb') as original, (out / 'events.jsonl').open('xb') as copied:
        shutil.copyfileobj(original, copied)
    if sha256_file(out / 'events.jsonl') != EVENTS_SHA256:
        raise ValueError('events source changed while copying')
    cards = []
    with (out / 'contexts.jsonl').open('x', encoding='utf-8') as handle:
        for index, context in enumerate(iter_contexts(root, calendar, events), 1):
            filename = f'card-{index:03d}.svg'
            (out / filename).write_text(render_svg(context), encoding='utf-8')
            handle.write(json.dumps(context, ensure_ascii=False, allow_nan=False) + '\n')
            label = escape(context['event']['time'] + ' ' + context['event']['symbol'])
            cards.append(f'<li><a href="{filename}">{label}</a><img loading="lazy" src="{filename}" alt="{label}" width="1200" height="455" style="max-width:100%;height:auto"></li>')
    # Existing labels are deliberately separated from causal SVGs/contexts.
    audit = []
    for event in events:
        value = event.get('return_30m')
        audit.append('<tr>' + ''.join('<td>' + escape(str(v)) + '</td>' for v in
                     (event['time'], event['symbol'], event['direction'], f'{value * 10000:+.2f}' if value is not None else '缺失')) + '</tr>')
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>RG1 UNVALIDATED 观察卡</title>'
            '<style>body{font:16px sans-serif;max-width:1250px;margin:24px auto;padding:12px}td,th{padding:6px;border-bottom:1px solid #ddd}li{margin:20px 0}img{display:block}</style>'
            f'<h1>RG1 UNVALIDATED：全部{len(events)}次观察</h1><p>按提示时间、标的排序；不挑赢家。不是购买建议，历史逐日期权挂牌及成交未认证。</p>'
            '<h2>因果图：只含此前20日日K与提示前缀</h2><ol>' + ''.join(cards) + '</ol>'
            '<h2>事后审计表：已有30分钟历史标签，不是当时已知信息</h2><p>只复制既有标签，不重新计算；不是期权损益，也不是图形胜率预测。</p>'
            '<table><tr><th>提示时间</th><th>标的</th><th>观察方向</th><th>已有30分钟标签bp</th></tr>' + ''.join(audit) + '</table></html>')
    (out / 'index.html').write_text(html, encoding='utf-8')
    source.load_inputs(root)  # Recheck pinned source bytes after the bounded read.
    manifest = {'status': 'UNVALIDATED', 'created_at': datetime.now(timezone.utc).isoformat(), 'events': len(events),
                'preregistration_sha256': source.PREREG_SHA256,
                'inputs': inputs, 'events_input': {'path': str(events_path), 'sha256': EVENTS_SHA256},
                'code_sha256': CODE_PINS | {str(Path(__file__).resolve().relative_to(repo)): sha256_file(__file__)},
                'scope': '仅RG1三ETF，截至2026-09-24；09/25仅参与原文件字节验签，不解析价格。',
                'causal_context': '此前20完整日K与截至提示时刻的已完成开盘前缀；无未来K线、无新标签。',
                'labels': '原events字节保留；index事后标签表与因果SVG分离。',
                'order': 'time,symbol', 'complete': True}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    checks = [sha256_file(path) + '  ' + path.name for path in sorted(out.iterdir())]
    (out / 'CHECKSUMS.sha256').write_text('\n'.join(checks) + '\n', encoding='utf-8')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--events', type=Path, default=EVENTS)
    parser.add_argument('--root', type=Path, default=source.ROOT)
    args = parser.parse_args(argv)
    export(args.out, args.events, args.root)


if __name__ == '__main__':
    main()
