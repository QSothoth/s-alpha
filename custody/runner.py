"""Resident OpenD worker for one custody job, plus the operator commands.

* ``custody dryrun`` - real quotes and same-day 1m bars, no broker at all.
  ``CustodyService.dispatch_next`` refuses to dispatch in dryrun; intents are logged
  and, unless ``--intent-only``, marked filled locally at the live quote.
* ``custody run --mode paper|live`` - the same loop with
  :class:`custody.broker.OpenDBroker`: orders go to an OpenD SIMULATE (paper) or
  REAL (live, ``accepted`` strategies only) account.
* ``custody status`` / ``custody stop`` - read a runtime database or request an exit
  from another shell; a running worker executes the stop on its next poll.

Offline historical evaluation is ``custody evaluate`` (:mod:`custody.evaluate`).
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from .controller import Controller
from .dataset import parse_option_code
from .models import ET, MANUAL, Frame, OrderUpdate, instant, symbol as normalize_symbol
from .playbook import PLAYBOOK_ID, decide as playbook_decide, underlying_series as playbook_series
from .opend import OpenDContractResolver, OpenDMarket, OpenDTradingCalendar
from .registry import Registry, add_strategy_arguments
from .service import ACTIVE, CustodyService, ExecutionPolicy
from .strategy import build_strategy, session_minute

SECURITY_FIRMS = ('FUTUSECURITIES', 'FUTUINC', 'FUTUSG', 'FUTUAU', 'FUTUCA', 'FUTUMY', 'FUTUJP')


def bar_boundary(now):
    """Floor ``now`` to the latest completed regular-session 1m bar close, or None."""
    now = instant(now).astimezone(ET)
    minute = now.hour * 60 + now.minute
    if minute <= 570 or minute > 960:
        return None
    return now.replace(second=0, microsecond=0)


def _json_logger(event, **fields):
    print(json.dumps({'event': event, **fields}, sort_keys=True, default=str, ensure_ascii=False), flush=True)


def _push_notify(title, body, *, wxpusher_spt=None):
    """Best-effort WxPusher phone push. Never raises.

    ``GET https://wxpusher.zjiecode.com/api/send/message/{SPT}/{urlencoded text}``.
    The SPT is a secret supplied via ``CUSTODY_WXPUSHER_SPT``;
    it is never persisted or logged.
    """
    if not wxpusher_spt:
        return
    try:
        text = ('%s\n%s' % (title, body)).strip()
        url = 'https://wxpusher.zjiecode.com/api/send/message/%s/%s' % (
            str(wxpusher_spt).strip(), urllib.parse.quote(text[:900]))
        with urllib.request.urlopen(url, timeout=8) as resp:
            resp.read()
    except Exception:  # noqa: BLE001 - a push must never break the worker loop
        pass


class SameDayHistorySource:
    """Complete same-session 1m underlying bars up to a boundary; nothing older."""

    def __init__(self, market, calendar, symbol, allow_history=True):
        self.market, self.calendar = market, calendar
        self.allow_history = allow_history
        self.symbol = symbol if str(symbol).upper().startswith('US.') else 'US.' + str(symbol).upper()
        self._day = None
        self._bars = {}

    def collect(self, boundary):
        boundary = instant(boundary)
        day = boundary.astimezone(ET).date().isoformat()
        session = self.calendar.session(day)
        if not session.opens < boundary <= session.closes:
            raise ValueError('boundary outside the trading session')
        if self._day != day:
            self._day, self._bars = day, {}
        count = int((boundary - session.opens).total_seconds() // 60)
        expected = [session.opens + timedelta(minutes=i) for i in range(1, count + 1)]

        def accept(rows):
            for bar in rows:
                if session.opens < bar.close_time <= boundary:
                    if bar.interval != '1m' or normalize_symbol(bar.code) != normalize_symbol(self.symbol):
                        raise ValueError('wrong symbol/interval in same-day market data')
                    self._bars[bar.close_time] = bar
        try:
            current = self.market.current_bars(self.symbol, 600, 'K_1M', boundary=boundary)
        except Exception:  # noqa: BLE001 - history below is an independent same-day source
            current = []
        accept(current)
        if self.allow_history and any(t not in self._bars for t in expected):
            try:
                accept(self.market.history_bars(self.symbol, 'K_1M', day, day, boundary=boundary))
            except Exception as exc:  # noqa: BLE001
                raise ValueError('same-day 1m history unavailable') from exc
            accept(current)  # the freshest stream observation wins
        missing = [t for t in expected if t not in self._bars]
        if missing:
            raise ValueError('same-day data not ready: %d missing 1m bars; first=%s'
                             % (len(missing), missing[0].isoformat()))
        return session, [self._bars[t] for t in expected]


class StrategyFrameSource:
    """Replay the job's strategy over today's bars at each completed minute.

    The engine is rebuilt from the session open every time, with the job's actual
    entry fill (time and underlying mark) injected before the first bar that closes
    at or after it. Decisions are therefore restart-safe and identical to
    ``custody evaluate`` given the same bars and fill.
    """

    def __init__(self, history, max_age_seconds=15):
        self.history = history
        self.max_age_seconds = float(max_age_seconds)
        self._key = self._frame = None

    def frame(self, job, now=None):
        now = instant(now) if now is not None else datetime.now(ET)
        boundary = bar_boundary(now)
        if boundary is None:
            return None
        key = (boundary.isoformat(), job['entry_at'])
        if key != self._key:
            session, bars = self.history.collect(boundary)
            engine = build_strategy(job['strategy'], job['request']['direction'], session, job['contract']['strike'])
            entry_at = instant(job['entry_at']) if job['entry_at'] else None
            decision = None
            for bar in bars:
                if entry_at is not None and entry_at <= bar.close_time:
                    engine.on_entry_filled(entry_at, job['entry_underlying'])
                    entry_at = None
                decision = engine.on_bar(bar)
            if decision is None:
                return None
            self._key = key
            self._frame = Frame(job['request']['symbol'], job['strategy']['sha256'], bars[-1].close_time,
                                bars[-1].close, decision.action, decision.reason, decision.diagnostics)
        if (now - instant(self._frame.bar_close)).total_seconds() > self.max_age_seconds:
            return None
        return self._frame


class PlaybookFrameSource:
    """Replay the smart-order playbook over today's completed bars at each minute (restart-safe).

    Underlying 1m comes from the same-day history; the contract's 1m from the subscribed stream (traded minutes
    only). The first decision inside the window becomes an ENTER (smart buy) or EXIT (smart sell) frame whose
    reason is the scene; quote protection and the deadline are the service's.
    """

    def __init__(self, history, market, max_age_seconds=15):
        self.history, self.market = history, market
        self.max_age_seconds = float(max_age_seconds)
        self._key = self._frame = None

    def frame(self, job, now=None):
        now = instant(now) if now is not None else datetime.now(ET)
        boundary = bar_boundary(now)
        if boundary is None:
            return None
        if boundary.isoformat() != self._key:
            session, bars = self.history.collect(boundary)
            contract = job['request']['contract']
            try:
                rows = self.market.current_bars(contract, 600, 'K_1M', boundary=boundary)
            except Exception:  # noqa: BLE001 - without option bars the playbook reads the underlying only
                rows = []
            options = {session_minute(session, b.close_time): b for b in rows
                       if session.opens < b.close_time <= boundary and b.volume and b.volume > 0}
            smart, side = job['smart'], 'BUY' if job['request']['trade_action'] == 'buy_only' else 'SELL'
            minute = lambda t: max(0, int((instant(t) - session.opens).total_seconds() // 60))
            sign = 1 if job['contract']['right'] == 'CALL' else -1
            found = playbook_decide(side, playbook_series(bars, session, sign), options, minute(smart['start_at']),
                                    minute(smart['end_at']), None, smart['zero_dte'], until=len(bars))
            self._key = boundary.isoformat()
            self._frame = None if found is None else Frame(
                job['request']['symbol'], PLAYBOOK_ID, bars[-1].close_time, bars[-1].close,
                'ENTER' if side == 'BUY' else 'EXIT', found[1], {'decided_bar': found[0]})
        if self._frame is None or (now - instant(self._frame.bar_close)).total_seconds() > self.max_age_seconds:
            return None
        return self._frame


class Runner:
    """Resident loop: poll market data, advance the controller, log every order change.

    Without a broker the service must be in dryrun mode (the controller enforces it);
    only then may ``simulate_fills`` mark intents filled locally.
    """

    def __init__(self, service, market, job_id, broker=None, frame_source=None, interval=5.0, logger=None,
                 wxpusher_spt=None, simulate_fills=False):
        if simulate_fills and service.mode != 'dryrun':
            raise ValueError('simulated fills exist only in dryrun')
        self.controller = Controller(service, broker)
        self.service, self.market, self.job_id = service, market, job_id
        self.frame_source = frame_source
        self.interval = float(interval)
        self.log = logger or _json_logger
        if wxpusher_spt is None:
            wxpusher_spt = os.environ.get('CUSTODY_WXPUSHER_SPT')
        self.wxpusher_spt = (wxpusher_spt or '').strip() or None
        self.simulate_fills = bool(simulate_fills)
        self._seen = {}

    def tick(self, now=None):
        clock = (lambda: datetime.now(ET)) if now is None else None
        now = instant(now) if now is not None else datetime.now(ET)
        job = self.service.get_job(self.job_id)
        if job['state'] in ('DONE', 'HELD', 'TRANSFERRED'):
            return job
        contract, underlying = job['request']['contract'], job['request']['symbol']
        quote = mark = frame = None
        try:
            quote = self.market.quote(contract, now)
        except Exception as exc:  # noqa: BLE001 - keep the resident loop alive
            self.log('quote_error', contract=contract, error=repr(exc))
        try:
            mark = self.market.underlying_mark(underlying, now)
        except Exception as exc:  # noqa: BLE001
            self.log('underlying_error', symbol=underlying, error=repr(exc))
        if self.frame_source is not None:
            try:
                frame = self.frame_source.frame(job, now)
            except Exception as exc:  # noqa: BLE001 - data gaps are non-fatal
                self.log('frame_error', symbol=underlying, error=repr(exc))
        try:
            if clock:
                now = clock()
            state = self.controller.step(self.job_id, now, quote, frame, clock=clock)
        except Exception as exc:  # noqa: BLE001 - the worker must keep managing an open position
            self.log('step_error', job_id=self.job_id, error=repr(exc))
            return None
        dispatch = getattr(self.controller, 'last_dispatch', None)
        if isinstance(dispatch, dict) and (dispatch.get('error') or dispatch.get('unknown') or dispatch.get('rejected')):
            self.log('dispatch_result', job_id=self.job_id, **dispatch)
        self._log_orders(state)
        if self.simulate_fills:
            if clock:
                now = clock()
            state = self._simulate_fills(state, now, mark, quote)
        self.log('tick', mode=self.service.mode, state=state['state'], underlying_mark=mark,
                 action=frame and frame.action, reason=frame and frame.reason, position_qty=state['position_qty'],
                 attention=state['attention'],
                 quote=None if quote is None else {'bid': quote.bid, 'ask': quote.ask, 'as_of': quote.as_of.isoformat()})
        return state

    def _simulate_fills(self, state, now, mark, quote=None):
        """Fill an unsent intent at its limit only while the live quote would take it (buy >= ask, sell <= bid)."""
        for order in state['orders']:
            marketable = quote is not None and quote.contract == order['contract'] and order['limit_price'] is not None and (
                order['limit_price'] >= quote.ask if order['side'] == 'BUY_OPEN' else order['limit_price'] <= quote.bid)
            if (order['kind'] != 'LIMIT' or order['status'] != 'CREATED' or order['limit_price'] is None
                    or not marketable
                    or (order['side'] == 'BUY_OPEN' and not mark)
                    or not 0 <= (now-instant(order['quote_as_of'])).total_seconds() <= self.service.policy.quote_max_age_seconds):
                continue
            first = now if order['side'] == 'BUY_OPEN' else None
            state = self.service.apply_update(OrderUpdate(order['client_order_id'], 0, 'FILLED', order['quantity'],
                                                          now, mark, order['limit_price'], first), now)
            self.log('simulated_fill', client_order_id=order['client_order_id'], side=order['side'],
                     price=order['limit_price'], underlying_mark=mark, submitted=False)
        return state

    def _log_orders(self, state):
        for order in state['orders']:
            key, seen = order['client_order_id'], (order['status'], order['cumulative_qty'])
            if self._seen.get(key) == seen:
                continue
            self._seen[key] = seen
            self.log('order', mode=self.service.mode, client_order_id=key, side=order['side'], kind=order['kind'],
                     contract=order['contract'], quantity=order['quantity'], limit_price=order['limit_price'],
                     status=order['status'], filled=order['cumulative_qty'],
                     average_price=order.get('average_option_price'), reason=order['reason'])
            if self.wxpusher_spt:
                _push_notify('%s %s %s %s' % (self.service.mode, order['side'], order['status'], order['contract']),
                             '%s qty=%s filled=%s limit=%s\nreason=%s\nid=%s' % (
                                 order['kind'], order['quantity'], order['cumulative_qty'], order['limit_price'],
                                 order['reason'], key),
                             wxpusher_spt=self.wxpusher_spt)

    def run(self, ticks=None):
        """Poll until the job is DONE (or ``ticks``). Ctrl-C only stops polling: broker orders stay as they are."""
        executed = 0
        try:
            while ticks is None or executed < ticks:
                state = self.tick()
                executed += 1
                if state is not None and state['state'] in ('DONE', 'HELD', 'TRANSFERRED'):
                    self.log('done' if state['state'] == 'DONE' else 'mandate_finished',
                             job_id=self.job_id, state=state['state'], position_qty=state['position_qty'],
                             attention=state['attention'])
                    break
                if ticks is None or executed < ticks:
                    time.sleep(self.interval)
        except KeyboardInterrupt:
            job = self.service.get_job(self.job_id)
            self.log('stopped', reason='keyboard_interrupt', state=job['state'], position_qty=job['position_qty'],
                     open_orders=[o['client_order_id'] for o in job['orders'] if o['status'] in ACTIVE])
        return executed


HELP = {
    'dryrun': 'Watch one option job on read-only OpenD with simulated fills; never sends an order.',
    'run': 'Trade one option job through OpenD: paper = SIMULATE account, live = REAL money.',
    'status': 'Show the jobs of a runtime database.',
    'stop': 'Stop entry and request exit; buy_only cancels entry remainders and retains holdings.',
}


def build_argument_parser(command):
    parser = argparse.ArgumentParser(prog='custody ' + command, description=HELP[command])
    if command in ('status', 'stop'):
        parser.add_argument('--db', required=True, help='runtime SQLite database of dryrun / run')
        parser.add_argument('--job', required=command == 'stop', help='job id (status: every job when omitted)')
        return parser
    if command == 'run':
        parser.add_argument('--mode', choices=['paper', 'live'], required=True,
                            help='paper: OpenD SIMULATE account; live: REAL money, accepted strategies only')
        parser.add_argument('--acc-id', type=int, required=True, help='OpenD US trading account id')
        parser.add_argument('--security-firm', choices=SECURITY_FIRMS, default='FUTUSECURITIES')
    else:
        parser.add_argument('--account', default='opend-dryrun')
        parser.add_argument('--intent-only', action='store_true', help='do not mark intents as simulated fills')
    add_strategy_arguments(parser)
    parser.add_argument('--symbol', default=None, help='underlying, e.g. US.QQQ (manual: taken from the contract)')
    parser.add_argument('--direction', choices=['LONG', 'SHORT'], default=None,
                        help='required for strategy jobs; manual tickets take it from the contract')
    parser.add_argument('--contract', required=True, help='exact upstream-selected option code')
    parser.add_argument('--expiry-policy', choices=['0_1dte', 'nearest'], default='0_1dte',
                        help='nearest: verify the earliest unexpired expiry with OpenD')
    parser.add_argument('--max-qty', type=int, default=1)
    parser.add_argument('--trade-action', choices=['round_trip', 'buy_only', 'sell_only'], default='round_trip',
                        help='round_trip: intraday buy/sell; buy_only: retain fills; sell_only: adopt holdings and auto-exit on verified cost/bid (dryrun/paper only)')
    parser.add_argument('--entry-valid-until', default=None, help='review expiry; stops new buys, never position management')
    parser.add_argument('--stream-only', action='store_true', help='never request historical-kline quota on a data gap')
    parser.add_argument('--max-entry-premium', type=float, default=None,
                        help='maximum entry premium in USD for this job, excluding fees; persisted across restarts')
    parser.add_argument('--max-loss-usd', type=float, default=None,
                        help='optional round_trip bid-based loss trigger in USD; not a guaranteed loss ceiling')
    parser.add_argument('--estimated-round-trip-fee-per-contract-usd', type=float, default=None,
                        help='explicit combined entry/exit fee estimate per contract, required with --max-loss-usd')
    parser.add_argument('--db', default=None, help='durable SQLite path (default: custody-<mode>.sqlite)')
    parser.add_argument('--host', default=None, help='OpenD host (default: FUTU_HOST or 127.0.0.1)')
    parser.add_argument('--port', type=int, default=None, help='OpenD port (default: FUTU_PORT or 11111)')
    parser.add_argument('--interval', type=float, default=5.0, help='seconds between polls')
    parser.add_argument('--ticks', type=int, default=None, help='stop after N polls (default: until the job is done)')
    parser.add_argument('--once', action='store_true', help='run a single poll')
    parser.add_argument('--no-subscribe', action='store_true', help='snapshot/history polling only')
    manual = parser.add_argument_group(
        'smart order (--manual: no strategy; any unexpired contract; live allowed). '
        '--trade-action buy_only = smart buy, sell_only = smart sell (only what is held)')
    manual.add_argument('--manual', action='store_true', help='place a smart buy / smart sell instead of a strategy job')
    manual.add_argument('--name', default=None,
                        help='ticket name; needed only for a second identical ticket on the same contract and day')
    manual.add_argument('--start-at', default=None, help='window start, ET (HH:MM or ISO); default: now')
    manual.add_argument('--end-at', default=None,
                        help='window end, ET (HH:MM or ISO): filled by then; 0DTE at most 15:45, others close-2min')
    manual.add_argument('--playbook', choices=['v2', 'off'], default=None,
                        help='off (default): act at the start; v2: scenario playbook v2 picks the moment '
                             '(failed EXEC8 on seen data, opt-in only)')
    manual.add_argument('--start-price', choices=['bid', 'mid', 'ask'], default=None, help='start of the price chase')
    manual.add_argument('--chase-step', type=float, default=None, help='share of the spread added per reprice (0-1]')
    manual.add_argument('--reprice-seconds', type=float, default=None, help='seconds an order rests before repricing')
    manual.add_argument('--daily-premium-cap-usd', type=float, default=None,
                        help='account cap on premium spent or reserved today; required for a smart buy')
    return parser


TICKET_ARGS = ('name', 'start_at', 'end_at', 'playbook', 'start_price', 'chase_step', 'reprice_seconds',
               'daily_premium_cap_usd')


def _et_time(value, now):
    """``HH:MM`` means today in ET; anything else must be an ISO timestamp with a zone."""
    if value is None or 'T' in value or '+' in value:
        return value
    hour, minute = (int(x) for x in value.split(':'))
    return instant(now).astimezone(ET).replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def ticket_from_args(args, now):
    ticket = {name: getattr(args, name) for name in TICKET_ARGS if getattr(args, name) is not None}
    for name in ('start_at', 'end_at'):
        if name in ticket:
            ticket[name] = _et_time(ticket[name], now)
    return ticket


def _summary(job):
    return {'job_id': job['id'], 'mode': job['mode'], 'contract': job['request']['contract'],
            'trade_action': job['request'].get('trade_action', 'round_trip'),
            'trade_date': job['request']['trade_date'], 'state': job['state'], 'position_qty': job['position_qty'],
            'attention': job['attention'], 'entry_reason': job['entry_reason'], 'exit_reason': job['exit_reason'],
            'loss_guard': job.get('loss_guard')}


def _operate(command, args):
    jobs = [(job_id, service) for job_id, service in CustodyService.jobs_in(args.db) if args.job in (None, job_id)]
    if args.job and not jobs:
        raise SystemExit('job not found: %s' % args.job)
    if command == 'stop':
        job_id, service = jobs[0]
        print(json.dumps(_summary(service.stop_job(job_id, datetime.now(ET))), ensure_ascii=False))
    elif args.job:
        print(json.dumps(jobs[0][1].get_job(args.job), indent=2, ensure_ascii=False))
    else:
        for job_id, service in jobs:
            print(json.dumps(_summary(service.get_job(job_id)), ensure_ascii=False))
    return 0


def main(command, argv=None):
    parser = build_argument_parser(command)
    args = parser.parse_args(argv)
    if command in ('status', 'stop'):
        return _operate(command, args)
    registry = Registry()
    if args.manual:
        underlying, _, right, _ = parse_option_code(args.contract)
        args.symbol = args.symbol or underlying
        args.direction = args.direction or ('LONG' if right == 'CALL' else 'SHORT')
        args.expiry_policy, strategy_id = 'any', MANUAL
    else:
        if any(getattr(args, name) is not None for name in TICKET_ARGS):
            parser.error('ticket options need --manual')
        if args.symbol is None or args.direction is None:
            parser.error('--symbol and --direction are required for strategy jobs')
        try:
            strategy_id = registry.resolve_id(args.strategy, args.strategy_version, args.strategy_mode)
        except ValueError as exc:
            parser.error(str(exc))
    mode = args.mode if command == 'run' else 'dryrun'
    if mode == 'live' and args.trade_action == 'sell_only' and not args.manual:
        raise SystemExit('sell_only position_pnl_v1 has no independent validation; use dryrun/paper')
    if mode == 'live' and args.max_loss_usd is not None:
        raise SystemExit('max_loss_usd guard has no independent validation; use dryrun/paper')
    market = OpenDMarket(host=args.host, port=args.port)
    broker, subscribed = None, False
    try:
        calendar = OpenDTradingCalendar(market)
        if command == 'run':
            from .broker import OpenDBroker, trade_password_present
            if mode == 'live' and not trade_password_present():
                raise SystemExit(
                    'live mode requires FUTU_TRADE_PASSWORD or FUTU_TRADE_PASSWORD_MD5 in the environment; '
                    'do not strip them with env -u — GUI unlock expires and place_order then fails silently')
            broker = OpenDBroker.connect(market, mode, args.acc_id, args.security_firm)
        service = CustodyService(args.db or 'custody-%s.sqlite' % mode, broker.account if broker else args.account,
                                 OpenDContractResolver(market), calendar, registry=registry, mode=mode,
                                 policy=ExecutionPolicy(frame_max_age_seconds=60, max_spread_fraction=.10)
                                 if args.entry_valid_until else None)
        payload = {'strategy_id': strategy_id, 'symbol': args.symbol,
                                  'direction': args.direction, 'contract': args.contract,
                                  'max_qty': args.max_qty, 'max_entry_premium': args.max_entry_premium,
                                  'max_loss_usd': args.max_loss_usd,
                                  'estimated_round_trip_fee_per_contract_usd': args.estimated_round_trip_fee_per_contract_usd,
                                  'expiry_policy': args.expiry_policy,
                                  'trade_action': args.trade_action,
                                  'entry_valid_until': args.entry_valid_until}
        if args.manual:
            payload['ticket'] = ticket_from_args(args, datetime.now(ET))
        position = None
        if args.trade_action == 'sell_only' and broker is not None:
            # Called only when a new job is created; existing jobs resume from their own durable fills.
            position = lambda: broker.position_snapshot(args.contract, datetime.now(ET))
        job = service.create_job(payload, datetime.now(ET), position=position)
        underlying = 'US.' + normalize_symbol(args.symbol)
        if not args.no_subscribe:
            try:
                market.subscribe([underlying, args.contract])
                subscribed = True
            except Exception as exc:  # noqa: BLE001 - polling still works
                _json_logger('subscribe_error', error=repr(exc))
        history = SameDayHistorySource(market, calendar, underlying, allow_history=not args.stream_only)
        if args.manual:
            frame_source = (PlaybookFrameSource(history, market, max_age_seconds=service.policy.frame_max_age_seconds)
                            if job['smart']['playbook'] == PLAYBOOK_ID else None)
        else:
            frame_source = None if args.trade_action == 'sell_only' else StrategyFrameSource(
                history, max_age_seconds=service.policy.frame_max_age_seconds)
        runner = Runner(service, market, job['id'], broker=broker, frame_source=frame_source,
                        interval=args.interval,
                        simulate_fills=command == 'dryrun' and not args.intent_only)
        _json_logger('start', command=command, mode=mode, account=service.account, db=service.path, job_id=job['id'],
                     strategy_version=args.strategy_version, strategy_mode=args.strategy_mode,
                     ticket=job['request'].get('ticket'),
                     strategy_id=job['strategy']['strategy_id'], strategy_status=job['strategy']['status'],
                     symbol=underlying, direction=args.direction, contract=args.contract, state=job['state'],
                     flatten_at=job['flatten_at'], orders_to=broker.env if broker else None)
        runner.run(ticks=1 if args.once else args.ticks)
        return 0
    finally:
        if subscribed:
            market.unsubscribe_all()
        if broker is not None:
            broker.close()
        market.close()
