"""Display all seven frozen OM1 observations; no detection or label calculation."""
import argparse
from collections import deque
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import shutil

from custody.dataset import sha256_file, write_checksums
from . import option_bridge as source
from .signal_cards import render_svg


REPO = Path(__file__).resolve().parents[2]
EVENTS = Path('data/om1-observations-20260926.jsonl')
REPORT = Path('studies/us_opening_range/reports/om1_diagnostic.json')
OUT = Path('data/or-om1-cards-20260926-readable-work')
EVENTS_SHA = '3896a22dd3d31317e3ab6838db2fab69374dd5f53195c1d6c49c0227e5c6141d'
REPORT_SHA = '559db24b93f1006130c050fd819e0ddc96c72b131888090e670666206fb426c4'
EXPECTED = (('2026-08-21', 'US.META'), ('2026-08-24', 'US.SPY'), ('2026-09-04', 'US.AAPL'),
            ('2026-09-08', 'US.SPY'), ('2026-09-14', 'US.MSFT'), ('2026-09-15', 'US.IWM'), ('2026-09-18', 'US.MU'))
SIGNAL_KEYS = ('symbol', 'time', 'direction', 'reference', 'level', 'invalidation', 'risk',
               'target', 'room_state', 'boundary20', 'atr', 'snapshot_minutes')
SETUP_KEYS = ('yesterday_high', 'yesterday_low', 'range_high20', 'range_low20', 'nr7', 'inside')


def read_frozen(events_path, report_path):
    for path, digest in ((events_path, EVENTS_SHA), (report_path, REPORT_SHA)):
        if Path(path).is_symlink() or sha256_file(path) != digest:
            raise ValueError('OM1 artifact checksum mismatch')
    report = json.loads(Path(report_path).read_text())
    if (report['study'] != 'OM1' or report['records_artifact']['sha256'] != EVENTS_SHA
            or report['preregistration_sha256'] != source.PREREG_SHA256):
        raise ValueError('OM1 report provenance mismatch')
    for relative, digest in report['code_sha256'].items():
        path = REPO / relative
        if path.is_symlink() or not path.resolve().is_relative_to(REPO) or sha256_file(path) != digest:
            raise ValueError('OM1 frozen code mismatch')
    rows, grouped = [], {}
    with Path(events_path).open() as handle:
        for line in handle:
            row = json.loads(line)
            key = row['trade_date'], row['symbol']
            group = grouped.setdefault(key, {})
            if len(rows) >= 231 or row['candidate'] not in source.CANDIDATES or row['candidate'] in group:
                raise ValueError('unexpected OM1 record count or duplicate identity')
            rows.append(row)
            group[row['candidate']] = row
    if len(rows) != 231 or len(grouped) != 77 or any(set(g) != set(source.CANDIDATES) for g in grouped.values()):
        raise ValueError('expected 231 records for 77 sessions')
    selected = []
    for key, group in sorted(grouped.items()):
        base = group['PD_BREAK']
        members = [name for name in source.CANDIDATES if group[name]['signal'] is not None]
        if not members:
            continue
        if base['signal'] is None or key not in EXPECTED:
            raise ValueError('unexpected OM1 independent observation')
        signal = base['signal']
        stamp = datetime.fromisoformat(signal['time'])
        if (stamp.tzinfo is None or signal['symbol'] != key[1] or stamp.date().isoformat() != key[0]
                or signal['snapshot_minutes'] not in (15, 20, 30) or signal['direction'] not in ('LONG', 'SHORT')
                or stamp != stamp.replace(hour=9, minute=30, second=0, microsecond=0)
                + timedelta(minutes=signal['snapshot_minutes'])):
            raise ValueError('unexpected OM1 signal identity or clock')
        for name in members:
            if (any(group[name]['signal'][field] != signal[field] for field in SIGNAL_KEYS)
                    or group[name]['setup'] != base['setup']):
                raise ValueError('candidate overlap does not share the same observation')
        selected.append(base | {'member_candidates': members})
    if tuple((row['trade_date'], row['symbol']) for row in selected) != EXPECTED:
        raise ValueError('expected exactly all seven OM1 observations')
    return selected, report


def contexts(root, calendar, events):
    results = {}
    for symbol in sorted({row['symbol'].removeprefix('US.') for row in events}):
        wanted = {row['trade_date']: row for row in events if row['symbol'] == 'US.' + symbol}
        history = deque(maxlen=20)
        stream = iter(source.history_sessions(Path(root) / 'preopen-us-k5-valid-v1/k5' / (symbol + '.csv'), symbol, calendar))
        current = next(stream, None)
        for day in calendar:
            bars, complete = [], False
            if current is not None and current[0] == day:
                _, bars, complete = current
                current = next(stream, None)
            if day in wanted:
                row, past = wanted[day], list(history)
                signal, stamp = row['signal'], datetime.fromisoformat(row['signal']['time'])
                prefix = [bar for bar in bars if bar.close_time <= stamp]
                opening = stamp.replace(hour=9, minute=30, second=0, microsecond=0)
                if (len(past) != 20 or len(prefix) != signal['snapshot_minutes'] // 5
                        or any(bar.close_time != opening + timedelta(minutes=5 * i) for i, bar in enumerate(prefix, 1))):
                    raise ValueError('missing twenty-day history or signal prefix')
                if (source.daily_levels(past, date.fromisoformat(day)) != row['setup']
                        or prefix[-1].close != signal['reference']):
                    raise ValueError('OM1 causal context differs from frozen observation')
                serialize = lambda bar: asdict(bar) | {'close_time': bar.close_time.isoformat()}
                event = {key: signal[key] for key in SIGNAL_KEYS}
                event.update({key: row['setup'][key] for key in SETUP_KEYS})
                event.update(key_level=signal['level'], member_candidates=row['member_candidates'])
                results[day, row['symbol']] = {'event': event, 'daily': [serialize(b) for b in past],
                                             'opening': [serialize(b) for b in prefix]}
            if complete:
                history.append(source.aggregate_daily(bars, calendar[day]))
            else:
                history.clear()
    if set(results) != set(EXPECTED):
        raise ValueError('not every OM1 event received context')
    return [results[key] for key in EXPECTED]


def export(out=OUT, events_path=EVENTS, report_path=REPORT, root=Path('data')):
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError('refuse to overwrite cards')
    events, report = read_frozen(events_path, report_path)
    _, calendar, inputs = source.load_inputs(root)
    cards = contexts(root, calendar, events)
    out.mkdir(parents=True)
    originals = ((events_path, 'records.jsonl', EVENTS_SHA), (report_path, 'om1_diagnostic.json', REPORT_SHA),
                 (Path(source.__file__).with_name('notes') / 'OM1_PREREG.md', 'OM1_PREREG.md', source.PREREG_SHA256))
    for original, name, digest in originals:
        with Path(original).open('rb') as src, (out / name).open('xb') as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        if sha256_file(out / name) != digest:
            raise ValueError('artifact changed during copying')
    images, audit = [], []
    with (out / 'contexts.jsonl').open('x') as handle:
        for index, (context, row) in enumerate(zip(cards, events), 1):
            event, name = context['event'], f'card-{index:03d}.svg'
            title = f"UNVALIDATED · OM1 · {event['symbol']} · {event['time']} · 观察 {event['direction']}"
            (out / name).write_text(render_svg(context, title=title,
                key_level_label='昨日高' if event['direction'] == 'LONG' else '昨日低', label_overlay=True), encoding='utf-8')
            handle.write(json.dumps(context, ensure_ascii=False, allow_nan=False) + '\n')
            images.append(f'<li>{escape(title)}；成员 {escape(" / ".join(event["member_candidates"]))}<a href="{name}"><img loading="lazy" src="{name}" alt="{escape(title)}" width="1200" height="455" style="max-width:100%;height:auto"></a></li>')
            value = lambda x, scale: '缺失' if x is None else f'{x * scale:+.2f}'
            cells = (event['time'], event['symbol'], event['direction'], row['option']['contract'],
                     value(row['underlying']['return_30m'], 10000), value(row['option']['mark_return_30m'], 100),
                     ' / '.join(row['option']['missing']) or '无')
            audit.append('<tr>' + ''.join('<td>' + escape(str(cell)) + '</td>' for cell in cells) + '</tr>')
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>OM1 UNVALIDATED</title>'
            '<style>body{font:16px sans-serif;max-width:1250px;margin:24px auto;padding:12px}td,th{padding:6px;border-bottom:1px solid #ddd}li{margin:20px 0}img{display:block}</style>'
            '<h1>OM1 UNVALIDATED：全部7个独立观察</h1><p>按日期／标的；候选重叠仅列成员，不增加样本。不是购买建议。</p><h2>因果图：没有未来行情或标签</h2><ol>' + ''.join(images) + '</ol>'
            '<h2>事后审计表：复制既有30分钟标签，不是当时已知信息</h2><p>期权为同分钟成交收盘毛标价，不是可成交净收益；开盘ATM不等于提示时ATM；缺端点照列，不推断缺失价格。</p>'
            '<table><tr><th>时间</th><th>标的</th><th>方向</th><th>既有合约</th><th>正股方向标签bp</th><th>期权毛标价%</th><th>缺端点</th></tr>' + ''.join(audit) + '</table></html>')
    (out / 'index.html').write_text(html, encoding='utf-8')
    source.load_inputs(root)
    read_frozen(events_path, report_path)
    code = dict(report['code_sha256']) | {str(Path(__file__).relative_to(REPO)): sha256_file(__file__),
        'studies/us_opening_range/signal_cards.py': sha256_file(Path(__file__).with_name('signal_cards.py'))}
    manifest = {'status': 'UNVALIDATED', 'complete': True, 'cards': 7, 'raw_records': 231,
        'created_at': datetime.now(timezone.utc).isoformat(), 'inputs': inputs, 'code_sha256': code,
        'events_sha256': EVENTS_SHA, 'report_sha256': REPORT_SHA, 'preregistration_sha256': source.PREREG_SHA256,
        'scope': '仅OM1已暴露7/21至9/18旧K5；无09/25或另九ETF价格；全7按日期/标的，无新标签。',
        'rendering': '同7旧事件仅重绘：关键位文字置顶、白色描边、相邻文字避让；水平线及原值不变，未重算标签。',
        'original_files_sha256': {name: digest for _, name, digest in originals},
        'separation': '图/context仅白名单因果字段；原231records、机器报告及事后表含既有标签，与因果图分开；预登记原字节保留，不含源码。'}
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    write_checksums(out)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=OUT)
    export(parser.parse_args().out)
