"""Build anonymised entry cards from a frozen custody dataset (study agent_card_eval).

Each card is one moment where a registered timing strategy decided to buy: everything
an agent may see is cut at that decision minute (completed bars only). The outcome of
taking the card is the strategy's own replayed trade (custody fill model and exits), kept
in a separate file the agent never sees.

    python3 -m studies.agent_card_eval.code.cards --dataset data/custody-0dte-v6.1 \
        --strategy zero_dte_timing_v6.6 --out <dir>

Writes <dir>/cards.jsonl (agent input) and <dir>/outcomes.jsonl (grading only).
"""
import argparse
import hashlib
import json
from pathlib import Path

from custody.dataset import Dataset
from custody.evaluate import ACCOUNT_BUDGET_USD, run_strategy
from custody.registry import Registry
from custody.strategy import session_minute

CONTEXT = ('US.SPY', 'US.QQQ')
CONTEXT_BAR_MINUTES = 5


def _norm(x, base):
    return round(100.0 * x / base, 3)


def _rows(bars, base, until, every=1):
    """Completed bars up to ``until`` (session minutes), prices scaled to base = 100."""
    out, group = [], []
    for bar in bars:
        minute = bar.minute
        if minute > until:
            break
        group.append(bar)
        if minute % every == 0 or minute == until:
            out.append([group[-1].minute, _norm(group[0].open, base), _norm(max(b.high for b in group), base),
                        _norm(min(b.low for b in group), base), _norm(group[-1].close, base),
                        round(sum(b.volume for b in group))])
            group = []
    return out


class _Minuted:
    def __init__(self, bar, session):
        self.__dict__.update(bar.__dict__ if hasattr(bar, '__dict__') else bar._asdict())
        self.minute = session_minute(session, bar.close_time)


def summary(bars, decided, sign, strike, option_close, spy_bars, flatten_minutes=15, minutes_to_close=None):
    """Deterministic numbers from completed bars up to ``decided``, signed so that positive favours the option."""
    seen = [b for b in bars if b.minute <= decided]
    close, open0 = seen[-1].close, seen[0].open
    volume = sum(b.volume for b in seen)
    vwap = sum((b.high + b.low + b.close) / 3 * b.volume for b in seen) / volume if volume else close
    opening = seen[:15]
    edge = max(b.high for b in opening) if sign > 0 else min(b.low for b in opening)
    high, low = max(b.high for b in seen), min(b.low for b in seen)
    position = 0.5 if high == low else ((close - low) if sign > 0 else (high - close)) / (high - low)
    ranges = [max(b.high, prev.close) - min(b.low, prev.close) for prev, b in zip(seen, seen[1:])][-14:]
    recent = seen[-5:]
    out = {
        'move_since_open_pct': round(100 * sign * (close / open0 - 1), 3),
        'vs_vwap_pct': round(100 * sign * (close / vwap - 1), 3),
        'beyond_opening_range_pct': round(100 * sign * (close - edge) / close, 3),
        'day_range_position': round(position, 3),
        'atr14_pct': round(100 * sum(ranges) / len(ranges) / close, 4) if ranges else None,
        'volume_ratio_5': round((sum(b.volume for b in recent) / len(recent)) / (volume / len(seen)), 2) if volume else None,
        'moneyness_pct': round(100 * sign * (close - strike) / close, 3),
        'premium_pct': None if option_close is None else round(100 * option_close / close, 3),
        'minutes_to_forced_exit': minutes_to_close - flatten_minutes,
    }
    if spy_bars:
        spy = [b for b in spy_bars if b.minute <= decided]
        out['spy_move_since_open_pct'] = round(100 * sign * (spy[-1].close / spy[0].open - 1), 3)
    return out


def build(dataset_dir, strategy_id, with_summary=False):
    dataset = Dataset(dataset_dir)
    item = Registry().get(strategy_id)
    datas = [dataset.load(c) for c in dataset.cases]
    context = {(d.case.symbol, d.case.trade_date): d for d in datas if d.case.symbol in CONTEXT}
    cards, outcomes = [], []
    for data in datas:
        trade = run_strategy(data, item)
        if trade['entry'] is None:
            continue
        decided = trade['entry']['minute']
        session = data.session
        bars = [_Minuted(b, session) for b in data.underlying]
        base = bars[0].open
        options = [_Minuted(b, session) for b in data.option if session_minute(session, b.close_time) <= decided]
        card_id = hashlib.sha256(('%s|%s' % (data.case.contract, data.case.trade_date)).encode()).hexdigest()[:12]
        market = {}
        for symbol in CONTEXT:
            ctx = context.get((symbol, data.case.trade_date))
            if ctx is not None:
                cb = [_Minuted(b, ctx.session) for b in ctx.underlying]
                market[symbol.split('.')[1]] = _rows(cb, cb[0].open, decided, CONTEXT_BAR_MINUTES)
        card = {
            'card_id': card_id,
            'option': 'CALL' if data.case.direction == 'LONG' else 'PUT',
            'rule_reason': trade['entry']['reason'],
            'decision_minute': decided,
            'minutes_to_close': int((session.closes - session.opens).total_seconds() // 60) - decided,
            'strike': _norm(data.case.strike, base),
            'last_option_trade': None if not options else {'minute': options[-1].minute,
                                                           'close': _norm(options[-1].close, base),
                                                           'volume_so_far': round(sum(b.volume for b in options))},
            'underlying_1m': _rows(bars, base, decided),
            'market_5m': market,
        }
        if with_summary:
            spy = context.get(('US.SPY', data.case.trade_date))
            card['summary'] = summary(bars, decided, 1 if data.case.direction == 'LONG' else -1, data.case.strike,
                                      options[-1].close if options else None,
                                      [_Minuted(b, spy.session) for b in spy.underlying] if spy else None,
                                      minutes_to_close=card['minutes_to_close'])
        cards.append(card)
        outcomes.append({'card_id': card_id, 'symbol': data.case.symbol, 'contract': data.case.contract,
                         'trade_date': data.case.trade_date, 'net_return': trade['net_return'],
                         'pnl_usd_at_budget': None if trade['net_return'] is None else trade['net_return'] * ACCOUNT_BUDGET_USD,
                         'exit_reason': trade['exit'] and trade['exit']['reason']})
    meta = {'dataset': dataset.name, 'checksums_sha256': dataset.fingerprint, 'strategy_id': strategy_id,
            'strategy_sha256': item['sha256'], 'cards': len(cards)}
    return meta, cards, outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--summary', action='store_true', help='add deterministic summary numbers (A2 B3)')
    args = parser.parse_args(argv)
    meta, cards, outcomes = build(args.dataset, args.strategy, args.summary)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (('cards.jsonl', cards), ('outcomes.jsonl', outcomes)):
        (out / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    (out / 'meta.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(meta))


if __name__ == '__main__':
    main()
