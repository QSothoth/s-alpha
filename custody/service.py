"""Durable single-trade state machine: at most one bought option per contract/day.

Broker I/O is injected (:class:`custody.ports.Broker`); market data and strategy
decisions arrive from the caller as :class:`~custody.models.Quote` and
:class:`~custody.models.Frame`. Nothing here opens a network connection.

State path: IDLE -> WATCH -> ENTRY -> IN -> EXIT -> DONE.

Guarantees
----------
* One strategy job per account + option contract + ET trade date: each contract is bought
  once and sold once. The same underlying may have several jobs the same day (for example a
  CALL and a PUT). Identical requests are idempotent; a different request for the same
  contract and day conflicts.
* Smart orders (operator tickets, ``strategy_id`` manual) are atomic: a smart buy or a smart
  sell of one contract within one window, filled once by its end. Several may exist for the
  same contract and day, each in its own slot (ticket name). A smart sell reserves its
  quantity from the locally held position when it is created, so the open sells of a contract
  never exceed what is owned (paper/live also check the broker position).
* Legacy 0-1 DTE or explicitly verified nearest-expiry contracts; registered strategies; live
  mode additionally requires strategy status ``accepted`` (docs/STANDARD.md).
* Entry requires a strategy signal; no heartbeat or deadline can force a purchase.
  Unfilled entries may retry on another ENTER frame before flatten; a partial
  entry is still the day's only trade.
* Every intent is persisted before broker I/O. An ambiguous submission becomes
  UNKNOWN and is never blindly resubmitted. A hard broker reject (never accepted)
  becomes REJECTED immediately so the next retry uses a new client order id.
* Exit cancels any live entry remainder first and sells only the owned quantity.
  Flatten does not depend on bars arriving. Missing quotes or unknown order status
  leave the job in EXIT with an attention flag, never a false DONE.
"""
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import hashlib
import json
import sqlite3

from .models import ET, MANUAL, HardSubmitError, JobRequest, OrderUpdate, UnlockRequiredError, instant, positive, symbol
from .registry import Registry
from .strategy import ACTIONS, flatten_minute
from .position_exit import POLICY as POSITION_EXIT_POLICY, decide as position_exit_decision
from . import ticket as tickets
from .playbook import GUARD, PLAYBOOK_ID

SCHEMA_VERSION = '5'   # 5: jobs.slot lets several smart orders share a contract and day
TERMINAL = {'FILLED', 'CANCELED', 'REJECTED'}
ACTIVE = {'CREATED', 'DISPATCHING', 'UNKNOWN', 'OPEN', 'PARTIAL'}


@dataclass(frozen=True)
class ExecutionPolicy:
    quote_max_age_seconds: float = 30  # TEMP 2026-09-22 live: Futu option update_time often lags >5s
    frame_max_age_seconds: float = 15
    entry_timeout_seconds: float = 30
    exit_timeout_seconds: float = 30
    max_spread_fraction: float = .30

    def __post_init__(self):
        for key, value in asdict(self).items():
            positive(value, key)
        if self.max_spread_fraction > 1:
            raise ValueError('invalid spread fraction')


JOBS_TABLE = ('CREATE TABLE IF NOT EXISTS %s (id TEXT PRIMARY KEY, account TEXT NOT NULL, contract TEXT NOT NULL, '
              "day TEXT NOT NULL, slot TEXT NOT NULL DEFAULT '', fingerprint TEXT NOT NULL, body TEXT NOT NULL, "
              'UNIQUE(account, contract, day, slot))')
DEADLINE_LEAD = timedelta(seconds=60)    # a smart order still undecided this long before its end acts at once
BUY_GRACE = timedelta(minutes=2)         # a smart buy stops buying this long after its end
ZERO_DTE_BUFFER, CLOSE_BUFFER = timedelta(minutes=15), timedelta(minutes=2)   # latest end: 15:45 for 0DTE


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class CustodyService:
    def __init__(self, db_path, account, contracts, calendar, registry=None, policy=None, mode='paper'):
        if not account or mode not in ('paper', 'live', 'dryrun'):
            raise ValueError('account and server mode (paper|live|dryrun) required')
        if str(db_path) == ':memory:':
            raise ValueError('durable file database required')
        self.path, self.account, self.mode = str(db_path), account, mode
        self.contracts, self.calendar = contracts, calendar
        self.registry = registry or Registry()
        self.policy = policy or ExecutionPolicy()
        with self._tx() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if version is None and 'jobs' in tables:
                raise ValueError('database was created by an older custody runtime; use a new database file')
            if version is not None and version[0] == '4':
                migrate = True
            elif version is not None and version[0] != SCHEMA_VERSION:
                raise ValueError('unsupported custody database schema %s' % version[0])
            else:
                migrate = False
            db.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (SCHEMA_VERSION,))
            db.execute('CREATE TABLE IF NOT EXISTS service_modes (account TEXT PRIMARY KEY, mode TEXT NOT NULL)')
            bound = db.execute('SELECT mode FROM service_modes WHERE account=?', (account,)).fetchone()
            if bound and bound[0] != mode:
                raise ValueError('database account already bound to another mode')
            db.execute('INSERT OR IGNORE INTO service_modes VALUES (?,?)', (account, mode))
            db.execute('CREATE TABLE IF NOT EXISTS strategy_versions (id TEXT PRIMARY KEY, sha TEXT NOT NULL)')
            for item in self.registry.list():
                prior = db.execute('SELECT sha FROM strategy_versions WHERE id=?', (item['strategy_id'],)).fetchone()
                if prior and prior[0] != item['sha256']:
                    raise ValueError('immutable strategy version changed: ' + item['strategy_id'])
                db.execute('INSERT OR IGNORE INTO strategy_versions VALUES (?,?)', (item['strategy_id'], item['sha256']))
            db.execute(JOBS_TABLE % 'jobs')
            db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS order_events (order_id TEXT NOT NULL, sequence INTEGER NOT NULL, '
                       'job_id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(order_id, sequence))')
        if migrate:
            self._migrate_v4()

    def _migrate_v4(self):
        """Schema 4 -> 5: every existing job keeps its identity in the empty slot."""
        with closing(sqlite3.connect(self.path, timeout=15)) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == '4':
                db.execute(JOBS_TABLE % 'jobs_v5')
                db.execute("INSERT INTO jobs_v5 (id, account, contract, day, slot, fingerprint, body) "
                           "SELECT id, account, contract, day, '', fingerprint, body FROM jobs")
                db.execute('DROP TABLE jobs')
                db.execute('ALTER TABLE jobs_v5 RENAME TO jobs')
                db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (SCHEMA_VERSION,))
            db.commit()

    @classmethod
    def jobs_in(cls, db_path):
        """``(job_id, service)`` for every job of a runtime database, each service bound to its account/mode."""
        if not Path(db_path).is_file():
            raise ValueError('no custody database at %s' % db_path)
        with closing(sqlite3.connect(db_path)) as db:
            rows = db.execute('SELECT j.id, j.account, m.mode FROM jobs j JOIN service_modes m USING (account) '
                              'ORDER BY j.rowid').fetchall()
        services = {}
        for _, account, mode in rows:
            if (account, mode) not in services:
                services[account, mode] = cls(db_path, account, None, None, mode=mode)
        return [(job_id, services[account, mode]) for job_id, account, mode in rows]

    # ------------------------------------------------------------ storage
    @contextmanager
    def _tx(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _load(self, db, job_id):
        row = db.execute('SELECT body FROM jobs WHERE id=? AND account=?', (job_id, self.account)).fetchone()
        if row is None:
            raise KeyError('job not found')
        return json.loads(row[0])

    def _save(self, db, job):
        db.execute('UPDATE jobs SET body=? WHERE id=?', (encode(job), job['id']))

    def _orders(self, db, job):
        return [json.loads(r[0]) for r in db.execute('SELECT body FROM orders WHERE job_id=? ORDER BY rowid', (job['id'],))]

    def _store_order(self, db, order):
        db.execute('UPDATE orders SET body=? WHERE id=?', (encode(order), order['client_order_id']))

    def get_job(self, job_id):
        with self._tx() as db:
            job = self._load(db, job_id)
            job['orders'] = self._orders(db, job)
            return job

    # ------------------------------------------------------------ jobs
    def create_job(self, payload, now, position=None):
        now = instant(now)
        request = JobRequest.parse(payload, now)
        ticket = request.ticket
        if request.trade_action == 'sell_only' and self.mode == 'live' and ticket is None:
            raise ValueError('sell_only position_pnl_v1 has no independent validation; use dryrun/paper')
        if request.max_loss_usd is not None and self.mode == 'live':
            raise ValueError('max_loss_usd guard has no independent validation; use dryrun/paper')
        if ticket is not None:
            # 2026-10-25 user decision: operator tickets may trade live; their caps are required by JobRequest.
            strategy = {'strategy_id': MANUAL, 'sha256': PLAYBOOK_ID if ticket['playbook'] == 'v2' else None,
                        'status': MANUAL}
        else:
            strategy = self.registry.get(request.strategy_id)
            if strategy['status'] == 'retired':
                raise ValueError('strategy is retired')
            if self.mode == 'live' and strategy['status'] != 'accepted':
                raise ValueError('live mode requires a strategy with status accepted (docs/STANDARD.md)')
        request_body = asdict(request)
        if ticket is None:
            request_body.pop('ticket')  # Preserve existing job fingerprints.
        if request.trade_action == 'round_trip':
            request_body.pop('trade_action')  # Preserve legacy restart identities.
        if request.expiry_policy == '0_1dte':
            request_body.pop('expiry_policy')  # Preserve existing job fingerprints.
        if request.entry_valid_until is None:
            request_body.pop('entry_valid_until')
        if request.max_entry_premium is None:
            request_body.pop('max_entry_premium')  # Preserve identities of existing jobs without a cap.
        if request.max_loss_usd is None:
            request_body.pop('max_loss_usd')
            request_body.pop('estimated_round_trip_fee_per_contract_usd')
        fingerprint = hashlib.sha256(encode(request_body).encode()).hexdigest()
        slot = '' if ticket is None else ticket['name'] or '%s-%s' % (
            'BUY' if request.trade_action == 'buy_only' else 'SELL', fingerprint[:12])
        existing = self._existing_job(request, fingerprint, slot)
        if existing is not None:
            return existing
        if request.entry_valid_until and now >= instant(request.entry_valid_until):
            raise ValueError('entry review card expired')
        if now.astimezone(ET).date().isoformat() != request.trade_date:
            raise ValueError('job trade_date must be today in ET; use custody evaluate for history')
        contract = self.contracts.resolve(request.contract)
        nearest = (self.contracts.nearest_expiry(request.symbol, request.trade_date)
                   if request.expiry_policy == 'nearest' and request.trade_action != 'sell_only' else None)
        contract.validate(request, nearest_expiry=nearest)
        session = self.calendar.session(request.trade_date)
        if session.day != request.trade_date:
            raise ValueError('calendar date mismatch')
        smart = None
        if ticket is not None:
            end = instant(ticket['end_at'])
            latest = session.closes - (ZERO_DTE_BUFFER if contract.expiry == request.trade_date else CLOSE_BUFFER)
            if end > latest:
                raise ValueError('end_at must be at or before %s for this contract' % latest.isoformat())
            if now >= end:
                raise ValueError('the window is over: end_at has passed')
            start = max(now, instant(ticket['start_at'])) if ticket['start_at'] else now
            smart = {'start_at': start.isoformat(), 'end_at': end.isoformat(), 'slot': slot, 'arrival': None,
                     'decided': None, 'playbook': PLAYBOOK_ID if ticket['playbook'] == 'v2' else 'off',
                     'zero_dte': contract.expiry == request.trade_date}
            flatten_at = end if request.trade_action == 'sell_only' else min(end + BUY_GRACE, session.closes)
        else:
            flatten_at = session.opens + timedelta(minutes=flatten_minute(strategy['config']['params'], session))
            if now >= (session.closes if request.trade_action == 'sell_only' else flatten_at):
                raise ValueError('entry window closed: create the job before %s' % flatten_at.isoformat())
        identity = [self.account, request.contract, request.trade_date] + ([slot] if slot else [])
        job_id = hashlib.sha256(encode(identity).encode()).hexdigest()[:32]
        job = {'id': job_id, 'request': request_body, 'strategy': strategy, 'contract': asdict(contract),
               'mode': self.mode, 'state': 'IDLE', 'position_qty': 0, 'entry_at': None, 'entry_underlying': None,
               'entry_reason': None, 'entry_diagnostics': None, 'exit_requested': False, 'exit_reason': None,
               'exit_decision_at': None, 'attention': None, 'last_bar': None,
               'opens': session.opens.isoformat(), 'closes': session.closes.isoformat(),
               'flatten_at': flatten_at.isoformat(),
               'created_at': now.isoformat()}
        if smart is not None:
            job['smart'] = smart
        with self._tx() as db:
            row = db.execute('SELECT id, fingerprint FROM jobs WHERE account=? AND contract=? AND day=? AND slot=?',
                             (self.account, request.contract, request.trade_date, slot)).fetchone()
            if row is None:
                if ticket is not None and request.trade_action != 'sell_only':
                    self._check_daily_cap(db, request)
                prior = [json.loads(r[0]) for r in db.execute(
                    'SELECT body FROM jobs WHERE account=? AND contract=?', (self.account, request.contract))]
                held = [j for j in prior if j['state'] == 'HELD' and j['position_qty']]
                unsettled = [j for j in prior if j['state'] not in ('DONE', 'HELD', 'TRANSFERRED')]
                if any(not (ticket is not None and j.get('smart') and j['request']['trade_date'] == request.trade_date)
                       for j in unsettled):
                    raise ValueError('existing contract job must be reconciled before a new session')
                if held and request.trade_action != 'sell_only' and ticket is None:
                    raise ValueError('held position requires sell_only takeover in the same database')
                if ticket is not None and request.trade_action == 'sell_only':
                    self._reserve(db, job, request, prior, held, now, position)
                elif request.trade_action == 'sell_only':
                    if len(held) > 1 or (held and held[0]['position_qty'] != request.max_qty):
                        raise ValueError('takeover must match the entire locally held quantity')
                    if self.mode != 'dryrun':
                        if (position is None or position.account != self.account or position.mode != self.mode
                                or position.contract != request.contract or type(position.quantity) is not int
                                or position.quantity < request.max_qty
                                or not 0 <= (now-instant(position.as_of)).total_seconds() <= 30):
                            raise ValueError('fresh broker position verification required for sell_only')
                    elif not held:
                        raise ValueError('dryrun sell_only requires a locally held position; no invented holdings')
                    if held:
                        buys = [o for o in self._orders(db, held[0]) if o['side'] == 'BUY_OPEN' and o['cumulative_qty']]
                        qty = sum(o['cumulative_qty'] for o in buys)
                        cost = sum(positive(o.get('average_option_price'), 'entry fill price') * o['cumulative_qty']
                                   for o in buys) / qty if qty else None
                        cost_source = 'source_job_buy_fills'
                    else:
                        cost, cost_source = position.average_cost, 'broker_average_cost'
                    cost = positive(cost, 'verified average entry cost')
                    job.update(state='IN', position_qty=request.max_qty,
                               adopted_position={'quantity': request.max_qty, 'verified_at': now.isoformat(),
                                                 'source_job': held[0]['id'] if held else None,
                                                 'average_cost': cost, 'cost_source': cost_source},
                               position_exit={'policy': dict(POSITION_EXIT_POLICY), 'peak_gross_return': 0.0,
                                              'last_quote_at': None, 'fees': 'NOT_DEDUCTED'})
                    if held:
                        source = held[0]
                        if any(o['status'] in ACTIVE for o in self._orders(db, source)):
                            raise ValueError('cannot transfer a position with unresolved orders')
                        source.update(state='TRANSFERRED', position_qty=0, transferred_to=job_id,
                                      transferred_qty=request.max_qty)
                        self._save(db, source)
                db.execute('INSERT INTO jobs (id, account, contract, day, slot, fingerprint, body) VALUES (?,?,?,?,?,?,?)',
                           (job_id, self.account, request.contract, request.trade_date, slot, fingerprint, encode(job)))
            elif row['fingerprint'] != fingerprint:
                raise ValueError('one_job_per_contract_day: a different request already exists for this contract'
                                 + (' and ticket name %s' % slot if slot else ''))
        return self.get_job(job_id)

    def _reserve(self, db, job, request, prior, held, now, position):
        """A smart sell takes its quantity out of the held position now, so open sells never exceed holdings."""
        qty = request.max_qty
        selling = [j for j in prior if j.get('smart') and j['request'].get('trade_action') == 'sell_only'
                   and j['state'] not in ('DONE', 'TRANSFERRED')]
        reserved = sum(j['position_qty'] for j in selling)
        local = sum(j['position_qty'] for j in held)
        if self.mode != 'dryrun':
            if (position is None or position.account != self.account or position.mode != self.mode
                    or position.contract != request.contract or type(position.quantity) is not int
                    or not 0 <= (now-instant(position.as_of)).total_seconds() <= 30):
                raise ValueError('fresh broker position verification required for a smart sell')
            if position.quantity < reserved + qty:
                raise ValueError('smart sell of %d exceeds the position: broker holds %d, open smart sells reserve %d'
                                 % (qty, position.quantity, reserved))
        elif local < qty:
            raise ValueError('dryrun smart sell of %d exceeds the locally held %d; no invented holdings' % (qty, local))
        draws, need, spent = [], qty, Decimal(0)
        for source in held:
            if not need:
                break
            if any(o['status'] in ACTIVE for o in self._orders(db, source)):
                raise ValueError('cannot reserve from a position with unresolved orders')
            take = min(need, source['position_qty'])
            buys = [o for o in self._orders(db, source) if o['side'] == 'BUY_OPEN' and o['cumulative_qty']]
            bought = sum(o['cumulative_qty'] for o in buys)
            if source.get('adopted_position'):
                unit = Decimal(str(source['adopted_position']['average_cost']))
            else:
                unit = sum(Decimal(str(o['average_option_price'])) * o['cumulative_qty'] for o in buys) / bought
            spent += unit * take
            need -= take
            source['position_qty'] -= take
            source.setdefault('reserved_by', []).append({'job': job['id'], 'qty': take, 'at': now.isoformat()})
            if not source['position_qty']:
                source.update(state='TRANSFERRED', transferred_to=job['id'])
            self._save(db, source)
            draws.append({'job': source['id'], 'qty': take})
        if need:   # the rest is verified broker inventory outside this database
            spent += Decimal(str(positive(position.average_cost, 'broker average_cost'))) * need
        job.update(state='IN', position_qty=qty,
                   adopted_position={'quantity': qty, 'verified_at': now.isoformat(), 'sources': draws,
                                     'average_cost': float(spent / qty),
                                     'cost_source': 'source_job_buy_fills' if not need else 'broker_average_cost'})

    def _check_daily_cap(self, db, request):
        """Spent premium of finished entries plus the caps of entries still open must fit the day's cap."""
        committed = Decimal(str(request.max_entry_premium))
        for raw, in db.execute('SELECT body FROM jobs WHERE account=? AND day=?', (self.account, request.trade_date)):
            other = json.loads(raw)
            if other['request'].get('trade_action', 'round_trip') == 'sell_only':
                continue
            if other['state'] in ('IDLE', 'WATCH', 'ENTRY'):
                if other['request'].get('max_entry_premium') is None:
                    raise ValueError('daily premium cap: an uncapped entry is still open today (job %s)' % other['id'])
                committed += Decimal(str(other['request']['max_entry_premium']))
            else:
                committed += sum(Decimal(str(o['average_option_price'])) * o['cumulative_qty']
                                 for o in self._orders(db, other) if o['side'] == 'BUY_OPEN' and o['cumulative_qty']
                                 ) * other['contract']['multiplier']
        cap = Decimal(str(request.ticket['daily_premium_cap_usd']))
        if committed > cap:
            raise ValueError('daily premium cap %s USD exceeded: %s USD spent or reserved today with this ticket'
                             % (cap, committed))

    def _existing_job(self, request, fingerprint, slot=''):
        with self._tx() as db:
            row = db.execute('SELECT id, fingerprint FROM jobs WHERE account=? AND contract=? AND day=? AND slot=?',
                             (self.account, request.contract, request.trade_date, slot)).fetchone()
            if row is None:
                return None
            if row['fingerprint'] != fingerprint:
                raise ValueError('one_job_per_contract_day: a different request already exists for this contract')
        return self.get_job(row['id'])

    def stop_job(self, job_id, now):
        """Stop the mandate: buy_only retains holdings; other actions request liquidation."""
        now = instant(now)
        with self._tx() as db:
            job = self._load(db, job_id)
            if job['state'] not in ('DONE', 'TRANSFERRED'):
                self._request_exit(db, job, 'operator_stop', now, None)
            self._save(db, job)
        return self.get_job(job_id)

    def flag_attention(self, job_id, attention):
        with self._tx() as db:
            job = self._load(db, job_id)
            job['attention'] = attention
            self._save(db, job)

    # ------------------------------------------------------------ events
    def heartbeat(self, job_id, now, quote=None):
        now = instant(now)
        with self._tx() as db:
            job = self._load(db, job_id)
            self._clock(db, job, now, quote)
            # TEMP 2026-09-22: after deadline_entry, keep retrying on every poll while quote gate blocks
            if (job['state'] == 'WATCH' and job.get('attention') == 'ENTRY_WAITING_VALID_QUOTE'
                    and job.get('entry_reason') and quote is not None):
                self._enter(db, job, now, quote, job['entry_reason'], job.get('entry_diagnostics'))
            self._save(db, job)
        return self.get_job(job_id)

    def on_frame(self, job_id, frame, now, quote=None):
        now = instant(now)
        with self._tx() as db:
            job = self._load(db, job_id)
            if symbol(frame.symbol) != job['request']['symbol'] or frame.strategy_hash != job['strategy']['sha256']:
                raise ValueError('frame/job identity mismatch')
            if frame.action not in ACTIONS:
                raise ValueError('unknown frame action')
            bar = instant(frame.bar_close)
            elapsed = (bar - instant(job['opens'])).total_seconds()
            if elapsed <= 0 or elapsed % 60 or bar > instant(job['closes']):
                raise ValueError('frame is not a completed regular-session 1m bar')
            if not 0 <= (now - bar).total_seconds() <= self.policy.frame_max_age_seconds:
                raise ValueError('future or stale frame')
            if job['last_bar'] and bar < instant(job['last_bar']):
                raise ValueError('out-of-order frame')
            self._clock(db, job, now, quote)
            fresh = job['state'] not in ('DONE', 'HELD', 'TRANSFERRED') and not (job['last_bar'] and bar == instant(job['last_bar']))
            if fresh:
                job['last_bar'] = bar.isoformat()
                if job['state'] == 'IDLE':
                    job['state'] = 'WATCH'
                if job.get('smart'):
                    side = 'ENTER' if job['request']['trade_action'] == 'buy_only' else 'EXIT'
                    if frame.action == side and not job['smart']['decided'] and now >= instant(job['smart']['start_at']):
                        self._decide(db, job, now, quote, frame.reason or 'playbook', frame.diagnostics)
                elif job['state'] == 'WATCH' and frame.action == 'ENTER':
                    self._enter(db, job, now, quote, frame.reason or 'strategy_entry', frame.diagnostics)
                elif (job['position_qty'] and not job['exit_requested'] and frame.action == 'EXIT'
                      and job['request'].get('trade_action', 'round_trip') == 'round_trip'):
                    self._request_exit(db, job, frame.reason or 'strategy_exit', now, quote)
            self._save(db, job)
        return self.get_job(job_id)

    def apply_update(self, event, now):
        now, at = instant(now), instant(event.as_of)
        if at > now or type(event.sequence) is not int or event.sequence < 0:
            raise ValueError('invalid order event time/sequence')
        if event.status not in {'OPEN', 'PARTIAL', *TERMINAL}:
            raise ValueError('unknown broker order status')
        with self._tx() as db:
            row = db.execute('SELECT body FROM orders WHERE id=?', (event.client_order_id,)).fetchone()
            if row is None:
                raise KeyError('unknown client order ID')
            order = json.loads(row[0])
            job = self._load(db, order['job_id'])
            if order['kind'] != 'LIMIT':
                raise ValueError('cancel acknowledgment is not a fill')
            body = asdict(event)
            body['as_of'] = at.isoformat()
            if event.first_fill_at is not None:
                body['first_fill_at'] = instant(event.first_fill_at).isoformat()
            body = encode(body)
            if event.sequence == order['sequence']:
                # Polling observes the same state again later; only the broker facts must agree.
                last = json.loads(order['last_update'])
                if any(last[k] != getattr(event, k) for k in ('status', 'cumulative_qty', 'average_option_price')):
                    raise ValueError('conflicting duplicate event')
                duplicate = True
            elif event.sequence < order['sequence']:
                raise ValueError('out-of-order order event; reconcile')
            else:
                duplicate = False
            if not duplicate:
                self._apply_fill(db, job, order, event, at, body, now)
        return self.get_job(job['id'])

    def _apply_fill(self, db, job, order, event, at, body, now):
        if at < instant(order['created_at']):
            raise ValueError('fill predates order intent')
        qty = event.cumulative_qty
        if type(qty) is not int or not order['cumulative_qty'] <= qty <= order['quantity']:
            raise ValueError('invalid cumulative fill quantity')
        if event.status == 'FILLED' and qty != order['quantity']:
            raise ValueError('FILLED requires complete quantity')
        if event.status == 'REJECTED' and qty:
            raise ValueError('rejected order cannot carry fills')
        if event.status == 'PARTIAL' and not 0 < qty < order['quantity']:
            raise ValueError('invalid partial fill')
        if event.status == 'OPEN' and qty:
            raise ValueError('OPEN cannot carry fills')
        if order['status'] in TERMINAL and (event.status != order['status'] or qty != order['cumulative_qty']):
            raise ValueError('terminal order changed; reconcile broker state')
        delta = qty - order['cumulative_qty']
        if delta:
            positive(event.average_option_price, 'average_option_price')
            if order['side'] == 'BUY_OPEN':
                if job['entry_at'] is None:
                    first = instant(event.first_fill_at)
                    if not instant(order['created_at']) <= first <= at:
                        raise ValueError('invalid first fill timestamp')
                    job['entry_underlying'] = positive(event.underlying_mark, 'underlying fill mark')
                    job['entry_at'] = first.isoformat()
                job['position_qty'] += delta
            else:
                if delta > job['position_qty']:
                    raise ValueError('sell fill exceeds owned quantity')
                job['position_qty'] -= delta
        order.update(status=event.status, cumulative_qty=qty, sequence=event.sequence, last_update=body,
                     average_option_price=event.average_option_price)
        if delta and order.get('first_fill_at') is None:
            order['first_fill_at'] = instant(event.first_fill_at).isoformat() if event.first_fill_at else at.isoformat()
        if event.status in TERMINAL:
            order['finished_at'] = at.isoformat()
        self._store_order(db, order)
        if event.status in TERMINAL:
            # The target's confirmed terminal state makes a pending cancel obsolete,
            # including a cancel whose response was lost before a restart.
            for cancel in self._orders(db, job):
                if (cancel['kind'] == 'CANCEL' and cancel['target'] == order['client_order_id']
                        and cancel['status'] in ACTIVE):
                    cancel.update(status='CANCELED', resolution='TARGET_TERMINAL')
                    self._store_order(db, cancel)
        db.execute('INSERT INTO order_events VALUES (?,?,?,?)', (order['client_order_id'], event.sequence, job['id'], body))
        if job['exit_requested']:
            self._exit(db, job, now, None)
        elif order['side'] == 'BUY_OPEN':
            if event.status in TERMINAL:
                self._entry_finished(job, now)
            else:
                job['state'] = 'ENTRY'
        self._clock(db, job, now, None)
        self._save(db, job)

    def dispatch_next(self, adapter, now):
        """Send the oldest CREATED intent. Dryrun never dispatches."""
        now = instant(now)
        if self.mode == 'dryrun':
            raise ValueError('dryrun mode never dispatches broker orders')
        if adapter.account != self.account or adapter.mode != self.mode:
            raise ValueError('adapter/account/mode mismatch')
        with self._tx() as db:
            candidates = [json.loads(r[0]) for r in db.execute('SELECT body FROM orders ORDER BY rowid')]
            candidates = [o for o in candidates if o['account'] == self.account and o['status'] == 'CREATED']
            if not candidates:
                return None
            order = candidates[0]
            job = self._load(db, order['job_id'])
            stale = order['kind'] == 'LIMIT' and not 0 <= (now - instant(order['quote_as_of'])).total_seconds() <= self.policy.quote_max_age_seconds
            forbidden = (order['side'] == 'BUY_OPEN' and job['request'].get('trade_action') == 'sell_only'
                         or order['side'] == 'SELL_CLOSE' and job['request'].get('trade_action') == 'buy_only')
            stale = stale or forbidden
            if order['side'] == 'BUY_OPEN' and (job['exit_requested'] or now >= instant(job['flatten_at'])
                                               or job.get('entry_stopped') or self._entry_expired(job, now)):
                stale = True
            if stale:
                # Never send an old price. The next heartbeat/frame re-creates a fresh intent.
                order['status'] = 'CANCELED'
                self._store_order(db, order)
                if order['side'] == 'BUY_OPEN' and not job['exit_requested']:
                    self._entry_finished(job, now)
                self._save(db, job)
                return {'not_sent': order['client_order_id']}
            order['status'] = 'DISPATCHING'
            self._store_order(db, order)
        try:
            if order['kind'] == 'CANCEL':
                adapter.cancel(order['target'], order['client_order_id'])
                with self._tx() as db:
                    order['status'] = 'ACKED'
                    self._store_order(db, order)
            else:
                event = adapter.submit(json.loads(encode(order)), now)
                if not isinstance(event, OrderUpdate) or event.client_order_id != order['client_order_id']:
                    raise ValueError('invalid broker acknowledgment')
                self.apply_update(event, now)
            return {'submitted': order['client_order_id']}
        except Exception as exc:
            return self._dispatch_failure(order, now, exc)

    def _dispatch_failure(self, order, now, exc):
        """Classify a submit/cancel failure: hard reject vs ambiguous UNKNOWN.

        Always records the full broker/OpenD message on the job (``last_error``) and
        sets a specific attention code. Never swallows the error into a silent reconcile.
        """
        message = '%s: %s' % (type(exc).__name__, exc)
        hard = isinstance(exc, HardSubmitError) and order['kind'] == 'LIMIT'
        if isinstance(exc, UnlockRequiredError):
            attention = 'TRADE_UNLOCK_REQUIRED'
        elif hard:
            attention = 'ENTRY_ORDER_REJECTED' if order['side'] == 'BUY_OPEN' else 'EXIT_ORDER_REJECTED'
        else:
            attention = 'RECONCILE_ORDER_STATUS'
        if hard:
            # Authoritative: nothing reached the book. Reject so a fresh client id can be minted.
            self.apply_update(OrderUpdate(order['client_order_id'], 1, 'REJECTED', 0, now), now)
            with self._tx() as db:
                job = self._load(db, order['job_id'])
                job['attention'] = attention
                job['last_error'] = message
                self._save(db, job)
            return {'rejected': order['client_order_id'], 'attention': attention,
                    'error': message, 'error_type': type(exc).__name__}
        with self._tx() as db:
            current = json.loads(db.execute(
                'SELECT body FROM orders WHERE id=?', (order['client_order_id'],)).fetchone()[0])
            if current['status'] == 'DISPATCHING':
                current['status'] = 'UNKNOWN'
                self._store_order(db, current)
            job = self._load(db, order['job_id'])
            job['attention'] = attention
            job['last_error'] = message
            self._save(db, job)
        return {'unknown': order['client_order_id'], 'attention': attention,
                'error': message, 'error_type': type(exc).__name__}

    # ------------------------------------------------------------ rules
    def _quote_ok(self, job, quote, now, allow_wide=False):
        try:
            if quote is None or quote.contract != job['request']['contract']:
                return False
            bid, ask = positive(quote.bid, 'bid'), positive(quote.ask, 'ask')
            age = (now - instant(quote.as_of)).total_seconds()
            return (0 <= age <= self.policy.quote_max_age_seconds and ask >= bid
                    and (allow_wide or (ask - bid) / ask <= self.policy.max_spread_fraction))
        except (ValueError, TypeError):
            return False

    def _new(self, db, job, kind, side, qty, now, quote=None, target=None, reason=None):
        action = job['request'].get('trade_action', 'round_trip')
        if (side == 'BUY_OPEN' and action == 'sell_only') or (side == 'SELL_CLOSE' and action == 'buy_only'):
            raise ValueError('order side forbidden by trade_action')
        existing = self._orders(db, job)
        if kind == 'CANCEL':
            suffix = 'CANCEL_' + target.rsplit(':', 1)[-1]
        else:
            prefix = 'BUY' if side == 'BUY_OPEN' else 'SELL'
            suffix = '%s_%d' % (prefix, 1 + sum(o['side'] == side for o in existing))
        key = job['id'] + ':' + suffix
        if any(o['client_order_id'] == key for o in existing):
            return None
        order = {'client_order_id': key, 'job_id': job['id'], 'account': self.account, 'mode': self.mode,
                 'kind': kind, 'side': side, 'contract': job['request']['contract'], 'quantity': qty,
                 'limit_price': self._limit(job, side, quote, sum(o['side'] == side for o in existing), reason, now),
                 'quote_as_of': quote.as_of.isoformat() if quote else None, 'target': target, 'reason': reason,
                 'position_effect': {'BUY_OPEN': 'OPEN', 'SELL_CLOSE': 'CLOSE'}.get(side),
                 'reduce_only': side == 'SELL_CLOSE', 'decision_bar': job['last_bar'], 'status': 'CREATED',
                 'cumulative_qty': 0, 'sequence': -1, 'last_update': None, 'created_at': now.isoformat()}
        if job.get('smart') and kind == 'LIMIT':
            # What later measures pricing and re-tests the playbook on new data (docs/RUNTIME.md 1b).
            decided = job['smart']['decided'] or {}
            order.update(quote_bid=quote.bid if quote else None, quote_ask=quote.ask if quote else None,
                         scene=decided.get('scene'), decided_at=decided.get('at'),
                         arrival=job['smart']['arrival'])
        db.execute('INSERT INTO orders VALUES (?,?,?)', (key, job['id'], encode(order)))
        return order

    @staticmethod
    def _limit(job, side, quote, attempt, reason, now):
        if quote is None:
            return None
        ticket = job['request'].get('ticket')
        if ticket is None:
            return quote.ask if side == 'BUY_OPEN' else quote.bid
        if now >= instant(job['smart']['end_at']):
            reason = 'deadline'   # past the end every order of a smart ticket is urgent
        return tickets.limit_price(ticket, side, quote.bid, quote.ask, attempt, reason)

    def _timeout(self, job, side):
        ticket = job['request'].get('ticket')
        if ticket is not None:
            return ticket['reprice_seconds']
        return self.policy.entry_timeout_seconds if side == 'BUY_OPEN' else self.policy.exit_timeout_seconds

    def _enter(self, db, job, now, quote, reason, diagnostics):
        if job['request'].get('trade_action') == 'sell_only' or job.get('entry_stopped'):
            return
        if self._entry_expired(job, now):
            self._entry_finished(job, now)
            return
        if any(o['side'] == 'BUY_OPEN' and o['status'] in ACTIVE for o in self._orders(db, job)):
            return
        job.update(entry_reason=reason, entry_diagnostics=diagnostics)
        if not self._quote_ok(job, quote, now):
            job['attention'] = 'ENTRY_WAITING_VALID_QUOTE'
            return
        cap = job['request'].get('max_entry_premium')
        attempt = sum(o['side'] == 'BUY_OPEN' for o in self._orders(db, job))
        price = self._limit(job, 'BUY_OPEN', quote, attempt, reason, now)
        qty = job['request']['max_qty'] - (job['position_qty'] if job.get('smart') else 0)
        spent = sum(Decimal(str(o['average_option_price'])) * o['cumulative_qty']
                    for o in self._orders(db, job) if o['side'] == 'BUY_OPEN' and o['cumulative_qty'])
        premium = (Decimal(str(price)) * qty + spent) * job['contract']['multiplier']
        if cap is not None and premium > Decimal(str(cap)):
            job['attention'] = 'ENTRY_PREMIUM_LIMIT'
            return
        self._new(db, job, 'LIMIT', 'BUY_OPEN', qty, now, quote, reason=reason)
        job.update(state='ENTRY', entry_reason=reason, entry_diagnostics=diagnostics, attention=None)

    def _entry_finished(self, job, now):
        """A BUY order reached a terminal state (or was dropped unsent)."""
        if job.get('smart') and job['position_qty'] < job['request']['max_qty'] and now < instant(job['flatten_at']):
            job.update(state='WATCH', attention='ENTRY_RETRY_PENDING')   # an atomic buy completes its quantity
        elif job['position_qty']:
            job.update(state='HELD' if job['request'].get('trade_action') == 'buy_only' else 'IN', attention=None)
        elif self._entry_expired(job, now):
            job.update(state='DONE', attention='ENTRY_REVIEW_EXPIRED')
        elif now < instant(job['flatten_at']):
            job.update(state='WATCH', attention='ENTRY_RETRY_PENDING')
        else:
            job.update(state='DONE', attention='ENTRY_NOT_FILLED')

    def _request_exit(self, db, job, reason, now, quote):
        if job['request'].get('trade_action') == 'buy_only':
            self._retain(db, job, now)
            return
        job['exit_decision_at'] = job['exit_decision_at'] or now.isoformat()
        job['exit_requested'] = True
        job['exit_reason'] = job['exit_reason'] or reason
        job['state'] = 'EXIT'
        self._exit(db, job, now, quote)

    def _exit(self, db, job, now, quote):
        orders = self._orders(db, job)
        waiting = False
        for buy in (o for o in orders if o['side'] == 'BUY_OPEN' and o['status'] in ACTIVE):
            if buy['status'] == 'CREATED':
                buy['status'] = 'CANCELED'
                self._store_order(db, buy)
            else:
                self._new(db, job, 'CANCEL', 'CANCEL', 0, now, target=buy['client_order_id'])
                waiting = True
        if waiting:
            job['attention'] = 'WAITING_ENTRY_CANCEL_CONFIRMATION'
            return
        if job['position_qty'] == 0:
            never_entered = job['entry_at'] is None and not job.get('adopted_position') and job['exit_reason'] != 'operator_stop'
            attempted = job['entry_reason'] is not None or any(o['side'] == 'BUY_OPEN' for o in orders)
            outcome = 'ENTRY_NOT_FILLED' if attempted else 'NO_ENTRY_SIGNAL'
            job.update(state='DONE', attention=outcome if never_entered else None)
            return
        sells = [o for o in orders if o['side'] == 'SELL_CLOSE' and o['status'] in ACTIVE]
        if sells:
            sell = sells[-1]
            age = (now - instant(sell['created_at'])).total_seconds()
            if sell['status'] == 'CREATED' and (not 0 <= (
                    now-instant(sell['quote_as_of'])).total_seconds() <= self.policy.quote_max_age_seconds
                    or job['request'].get('ticket') is not None and age >= self._timeout(job, 'SELL_CLOSE')):
                sell['status'] = 'CANCELED'  # unsent (dryrun) intents reprice locally
                self._store_order(db, sell)
            elif sell['status'] != 'CREATED' and age >= self._timeout(job, 'SELL_CLOSE'):
                if self._new(db, job, 'CANCEL', 'CANCEL', 0, now, target=sell['client_order_id']):
                    job['attention'] = 'EXIT_REPRICE_CANCEL_PENDING'
                return
            else:
                return
        if not self._quote_ok(job, quote, now, allow_wide=True):
            job['attention'] = 'EXIT_WAITING_VALID_QUOTE'
            return
        self._new(db, job, 'LIMIT', 'SELL_CLOSE', job['position_qty'], now, quote, reason=job['exit_reason'])
        job['attention'] = None

    @staticmethod
    def _entry_expired(job, now):
        deadline = job['request'].get('entry_valid_until')
        return deadline is not None and now >= instant(deadline)

    def _clock(self, db, job, now, quote):
        if job['state'] in ('DONE', 'HELD', 'TRANSFERRED'):
            return
        if job['request'].get('trade_action') == 'buy_only' and (
                job.get('entry_stopped') or now >= instant(job['flatten_at'])):
            self._retain(db, job, now)
            return
        if now >= instant(job['flatten_at']) and not job['exit_requested']:
            self._request_exit(db, job, 'scheduled_flatten', now, quote)
            return
        if job['exit_requested']:
            self._exit(db, job, now, quote)
            return
        ticket = job['request'].get('ticket')
        if ticket:
            self._smart_clock(db, job, now, quote)
            if job['request']['trade_action'] == 'sell_only' or job['state'] in ('DONE', 'HELD'):
                return
        elif job['request'].get('trade_action') == 'sell_only':
            self._position_exit(db, job, now, quote)
            return
        self._loss_guard(db, job, now, quote)
        if job['exit_requested']:
            return
        buys = [o for o in self._orders(db, job) if o['side'] == 'BUY_OPEN' and o['status'] in ACTIVE]
        expired = self._entry_expired(job, now)
        if expired and not buys and not job['position_qty']:
            job.update(state='DONE', attention='ENTRY_REVIEW_EXPIRED')
            return
        for buy in buys:
            if not expired and (now - instant(buy['created_at'])).total_seconds() < self._timeout(job, 'BUY_OPEN'):
                continue
            if buy['status'] == 'CREATED':
                buy['status'] = 'CANCELED'
                self._store_order(db, buy)
                self._entry_finished(job, now)
            elif self._new(db, job, 'CANCEL', 'CANCEL', 0, now, target=buy['client_order_id']):
                job['attention'] = 'ENTRY_TIMEOUT_CANCEL_PENDING'
        if (ticket and job['smart']['decided'] and job['state'] in ('IDLE', 'WATCH')
                and job['position_qty'] < job['request']['max_qty'] and not job.get('entry_stopped')
                and now < instant(job['flatten_at'])
                and not any(o['side'] == 'BUY_OPEN' and o['status'] in ACTIVE for o in self._orders(db, job))):
            job['state'] = 'WATCH'
            self._enter(db, job, now, quote, job['smart']['decided']['scene'], None)

    def _loss_guard(self, db, job, now, quote):
        request = job['request']
        if (request.get('max_loss_usd') is None or request.get('trade_action', 'round_trip') != 'round_trip'
                or not job['position_qty'] or now < instant(job['opens'])):
            return
        state = job.setdefault('loss_guard', {})
        if not self._quote_ok(job, quote, now, allow_wide=True):
            state.update(status='WAITING_VALID_QUOTE', checked_at=now.isoformat())
            job['attention'] = 'LOSS_GUARD_WAITING_VALID_QUOTE'
            return
        if state.get('quote_at') and instant(quote.as_of) < instant(state['quote_at']):
            state.update(status='WAITING_VALID_QUOTE', checked_at=now.isoformat())
            job['attention'] = 'LOSS_GUARD_WAITING_VALID_QUOTE'
            return
        buys = [o for o in self._orders(db, job) if o['side'] == 'BUY_OPEN' and o['cumulative_qty']]
        qty = sum(o['cumulative_qty'] for o in buys)
        try:
            cost = sum(Decimal(str(positive(o.get('average_option_price'), 'entry fill price')))
                       * o['cumulative_qty'] for o in buys) / qty
        except (ValueError, TypeError, ZeroDivisionError):
            state.update(status='WAITING_ENTRY_COST', checked_at=now.isoformat())
            job['attention'] = 'LOSS_GUARD_WAITING_ENTRY_COST'
            return
        fees = Decimal(str(request['estimated_round_trip_fee_per_contract_usd'])) * job['position_qty']
        net = (Decimal(str(quote.bid)) - cost) * job['position_qty'] * job['contract']['multiplier'] - fees
        triggered = net <= -Decimal(str(request['max_loss_usd']))
        state.update(status='TRIGGERED' if triggered else 'MONITORING', checked_at=now.isoformat(),
                     quote_at=instant(quote.as_of).isoformat(), bid=quote.bid, average_entry_cost=float(cost),
                     position_qty=job['position_qty'], estimated_fees_usd=float(fees), estimated_net_pnl_usd=float(net))
        if job.get('attention') in ('LOSS_GUARD_WAITING_VALID_QUOTE', 'LOSS_GUARD_WAITING_ENTRY_COST'):
            job['attention'] = None
        if triggered:
            self._request_exit(db, job, 'option_max_loss', now, quote)

    def _smart_clock(self, db, job, now, quote):
        """Arrival quote, quote protection, the deadline and playbook ``off``; the playbook itself arrives as frames."""
        smart = job['smart']
        if smart['decided'] or now < instant(smart['start_at']) or now < instant(job['opens']):
            return
        buy = job['request']['trade_action'] == 'buy_only'
        fresh = self._quote_ok(job, quote, now, allow_wide=True)
        if smart['arrival'] is None and fresh:
            smart['arrival'] = {'bid': quote.bid, 'ask': quote.ask, 'as_of': instant(quote.as_of).isoformat()}
        arrival = smart['arrival']
        if now >= instant(smart['end_at']) - DEADLINE_LEAD:
            self._decide(db, job, now, quote, 'deadline', None)
        elif smart['playbook'] == 'off':
            self._decide(db, job, now, quote, 'immediate', None)
        elif fresh and arrival and ((quote.ask >= arrival['ask'] * GUARD['BUY']) if buy
                                    else (quote.bid <= arrival['bid'] * GUARD['SELL'])):
            self._decide(db, job, now, quote, 'protect_quote', None)

    def _decide(self, db, job, now, quote, scene, diagnostics):
        """The moment of a smart order: buy (complete the quantity) or sell everything this ticket holds."""
        job['smart']['decided'] = {'at': now.isoformat(), 'scene': scene, 'bar': job['last_bar'],
                                   'diagnostics': diagnostics}
        if job['request']['trade_action'] == 'buy_only':
            job['state'] = 'WATCH'
            self._enter(db, job, now, quote, scene, diagnostics)
        else:
            self._request_exit(db, job, scene, now, quote)

    def _position_exit(self, db, job, now, quote):
        if now < instant(job['opens']):
            return
        if not self._quote_ok(job, quote, now, allow_wide=True):
            job['attention'] = 'POSITION_EXIT_WAITING_VALID_QUOTE'
            return
        state = job['position_exit']
        if state['last_quote_at'] and instant(quote.as_of) <= instant(state['last_quote_at']):
            return
        reason, value, peak = position_exit_decision(state['policy'], job['adopted_position']['average_cost'],
                                                     quote.bid, state['peak_gross_return'])
        state.update(last_quote_at=instant(quote.as_of).isoformat(), gross_return=value, peak_gross_return=peak)
        job['attention'] = None
        if reason:
            self._request_exit(db, job, reason, now, quote)

    def _retain(self, db, job, now):
        """End a buy-only mandate without selling; reconcile every entry remainder first."""
        job['entry_stopped'] = True
        waiting = False
        for buy in self._orders(db, job):
            if buy['side'] != 'BUY_OPEN' or buy['status'] not in ACTIVE:
                continue
            if buy['status'] == 'CREATED':
                buy['status'] = 'CANCELED'
                self._store_order(db, buy)
            else:
                self._new(db, job, 'CANCEL', 'CANCEL', 0, now, target=buy['client_order_id'])
                waiting = True
        job.update(state='ENTRY' if waiting else 'HELD' if job['position_qty'] else 'DONE',
                   attention='WAITING_ENTRY_CANCEL_CONFIRMATION' if waiting else
                   'POSITION_RETAINED' if job['position_qty'] else 'ENTRY_NOT_FILLED')
