"""Smart buy / smart sell (atomic operator orders): validation, pricing, timing, reservations, records. Synthetic only."""
import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from custody import ticket as tickets
from custody.models import MANUAL, Frame, OrderUpdate, PositionSnapshot, Quote, parse_ticket
from custody.playbook import PLAYBOOK_ID
from custody.runner import PlaybookFrameSource, Runner, build_argument_parser, ticket_from_args
from custody.service import CustodyService
from custody.tests.test_service import CALL, DAY, SID, T, Calendar, Catalog

WEEKLY = 'US.SPY260918C600000'  # expires four days after DAY
PUT = 'US.SPY260914P600000'


def at(minutes):
    return T + timedelta(minutes=minutes)


def ticket(action='buy_only', **kw):
    base = {'end_at': at(60).isoformat()}
    if action == 'buy_only':
        base['daily_premium_cap_usd'] = 1000
    return {**base, **kw}


class PricingTests(unittest.TestCase):
    def spec(self, **kw):
        return parse_ticket(ticket(**kw), DAY, 'buy_only')

    def test_mid_chase_moves_toward_the_fill_side_and_rounds_passively(self):
        t = self.spec(chase_step=0.25)
        self.assertEqual([tickets.limit_price(t, 'BUY_OPEN', 1.00, 1.10, k) for k in range(4)],
                         [1.05, 1.06, 1.07, 1.08])
        self.assertEqual(tickets.limit_price(t, 'BUY_OPEN', 1.00, 1.10, 4), 1.10)
        self.assertEqual([tickets.limit_price(t, 'SELL_CLOSE', 1.00, 1.10, k) for k in range(4)],
                         [1.05, 1.04, 1.03, 1.02])
        self.assertEqual(tickets.limit_price(t, 'BUY_OPEN', 3.00, 3.40, 0), 3.20)
        self.assertEqual(tickets.limit_price(t, 'BUY_OPEN', 3.05, 3.30, 0), 3.15)  # 3.175 floors to 3.15

    def test_urgent_triggers_take_the_far_side_and_strength_sales_chase(self):
        t = self.spec()
        self.assertEqual(tickets.limit_price(t, 'BUY_OPEN', 1.00, 1.10, 0, 'deadline'), 1.10)
        self.assertEqual(tickets.limit_price(t, 'BUY_OPEN', 1.00, 1.10, 0, 'protect_quote'), 1.10)
        self.assertEqual(tickets.limit_price(t, 'BUY_OPEN', 1.00, 1.10, 0, 'spike_down'), 1.05)
        for weak in ('stop_low', 'spike_down', 'against', 'lose', 'sunk'):
            self.assertEqual(tickets.limit_price(t, 'SELL_CLOSE', 1.00, 1.10, 0, weak), 1.00)
        for strong in ('spike_up', 'stretched', 'with', 'chop', 'urgency'):
            self.assertEqual(tickets.limit_price(t, 'SELL_CLOSE', 1.00, 1.10, 0, strong), 1.05)

    def test_validation(self):
        for bad, action in [({'end_at': None}, 'buy_only'), ({'start_at': at(60).isoformat()}, 'buy_only'),
                            ({'end_at': '2026-09-15T10:00:00-04:00'}, 'buy_only'), ({'name': 'a b'}, 'buy_only'),
                            ({'playbook': 'v1'}, 'buy_only'), ({'chase_step': 0}, 'buy_only'),
                            ({'reprice_seconds': 300}, 'buy_only'), ({'take_profit_pct': .5}, 'buy_only'),
                            ({'daily_premium_cap_usd': None}, 'buy_only'), ({'daily_premium_cap_usd': 100}, 'sell_only')]:
            with self.assertRaises(ValueError, msg=bad):
                parse_ticket({k: v for k, v in ticket(**bad).items() if v is not None}
                             if bad.get('end_at', 1) is None else ticket(**bad), DAY, action)
        t = parse_ticket(ticket('sell_only', name='tp-1'), DAY, 'sell_only')
        self.assertEqual((t['playbook'], t['start_price'], t['name']), ('off', 'mid', 'tp-1'))


class SmartServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'jobs.sqlite'

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, mode='dryrun'):
        return CustodyService(self.path, 'test', Catalog(), Calendar(), mode=mode)

    def request(self, contract=CALL, action='buy_only', premium=300, qty=1, direction='LONG', **kw):
        body = {'strategy_id': MANUAL, 'symbol': 'SPY', 'direction': direction, 'contract': contract, 'max_qty': qty,
                'trade_date': DAY, 'expiry_policy': 'any', 'trade_action': action, 'ticket': ticket(action, **kw)}
        if premium is not None and action == 'buy_only':
            body['max_entry_premium'] = premium
        return body

    @staticmethod
    def quote(t, bid=1.0, ask=1.1, contract=CALL):
        return Quote(contract, bid, ask, t)

    @staticmethod
    def frame(t, action, reason):
        return Frame('SPY', PLAYBOOK_ID, t, 600.0, action, reason)

    def fill(self, service, order, when, price, qty=None, status='FILLED', seq=1):
        qty = order['quantity'] if qty is None else qty
        return service.apply_update(OrderUpdate(order['client_order_id'], seq, status, qty, when, 600.0, price,
                                                when if order['side'] == 'BUY_OPEN' and qty else None), when)

    def bought(self, service, qty=2, name=None):
        job = service.create_job(self.request(qty=qty, premium=1000, playbook='off', name=name), T)
        state = service.heartbeat(job['id'], T, self.quote(T))
        return self.fill(service, state['orders'][0], T, 1.05)

    def test_request_rules_and_legacy_fingerprint(self):
        service = self.service()
        body = self.request()
        for change in ({'trade_action': 'round_trip'}, {'max_entry_premium': None}, {'expiry_policy': 'nearest'}):
            with self.assertRaises(ValueError, msg=change):
                service.create_job({k: v for k, v in {**body, **change}.items() if v is not None}, T)
        with self.assertRaises(ValueError):    # 0DTE must be filled by 15:45
            service.create_job(self.request(end_at=T.replace(hour=15, minute=46).isoformat()), T)
        with self.assertRaises(ValueError):    # the window is already over
            service.create_job(self.request(end_at=at(-1).isoformat()), T)
        weekly = service.create_job(self.request(WEEKLY, end_at=T.replace(hour=15, minute=58).isoformat()), T)
        self.assertEqual(weekly['flatten_at'][11:16], '16:00')   # buying stops at the close for a late window
        self.assertEqual(service.create_job(self.request(), T)['state'], 'IDLE')   # 0DTE smart buys are allowed
        legacy = {'strategy_id': SID, 'symbol': 'SPY', 'direction': 'SHORT', 'contract': PUT, 'trade_date': DAY}
        with self.assertRaises(ValueError):
            service.create_job({**legacy, 'ticket': ticket()}, T)
        self.assertNotIn('ticket', service.create_job(legacy, T)['request'])

    def test_playbook_off_buys_at_the_start_and_chases_from_the_mid(self):
        service = self.service()
        job = service.create_job(self.request(start_at=at(5).isoformat(), playbook='off', reprice_seconds=10,
                                              chase_step=0.5), T)
        self.assertEqual(service.heartbeat(job['id'], T, self.quote(T))['orders'], [])
        state = service.heartbeat(job['id'], at(5), self.quote(at(5)))
        order = state['orders'][0]
        self.assertEqual((order['limit_price'], order['scene'], order['quote_bid'], order['quote_ask']),
                         (1.05, 'immediate', 1.0, 1.1))
        self.assertEqual(order['arrival'], {'bid': 1.0, 'ask': 1.1, 'as_of': at(5).isoformat()})
        later = at(5) + timedelta(seconds=10)
        state = service.heartbeat(job['id'], later, self.quote(later))
        self.assertEqual([o['status'] for o in state['orders']], ['CANCELED', 'CREATED'])
        self.assertEqual(state['orders'][1]['limit_price'], 1.07)        # half way to the ask, rounded passively
        state = self.fill(service, state['orders'][1], later, 1.07)
        self.assertEqual((state['state'], state['position_qty']), ('HELD', 1))
        self.assertEqual(state['orders'][1]['first_fill_at'], later.isoformat())
        self.assertEqual(state['orders'][1]['finished_at'], later.isoformat())

    def test_playbook_buy_waits_for_its_frame_quote_protection_and_the_deadline(self):
        service = self.service()
        job = service.create_job(self.request(playbook='v2'), T)
        self.assertEqual(service.heartbeat(job['id'], T, self.quote(T))['orders'], [])
        state = service.on_frame(job['id'], self.frame(at(1), 'EXIT', 'spike_up'), at(1), self.quote(at(1)))
        self.assertEqual(state['orders'], [])                            # a buy ignores sell frames
        state = service.on_frame(job['id'], self.frame(at(2), 'ENTER', 'spike_down'), at(2), self.quote(at(2)))
        self.assertEqual((state['smart']['decided']['scene'], state['orders'][0]['scene'],
                          state['orders'][0]['limit_price']), ('spike_down', 'spike_down', 1.05))

        guarded = service.create_job(self.request(PUT, direction='SHORT', playbook='v2'), T)
        service.heartbeat(guarded['id'], T, self.quote(T, contract=PUT))  # arrival ask 1.10
        self.assertEqual(service.heartbeat(guarded['id'], at(1), self.quote(at(1), 1.1, 1.2, PUT))['orders'], [])
        state = service.heartbeat(guarded['id'], at(2), self.quote(at(2), 1.15, 1.22, PUT))
        self.assertEqual((state['smart']['decided']['scene'], state['orders'][0]['limit_price']),
                         ('protect_quote', 1.22))                        # +10% on the ask: buy at the ask

        late = service.create_job(self.request(WEEKLY, end_at=at(30).isoformat(), playbook='v2'), T)
        self.assertEqual(service.heartbeat(late['id'], at(28), self.quote(at(28), contract=WEEKLY))['orders'], [])
        state = service.heartbeat(late['id'], at(29), self.quote(at(29), contract=WEEKLY))
        self.assertEqual((state['orders'][0]['scene'], state['orders'][0]['limit_price']), ('deadline', 1.1))

    def test_a_partial_buy_completes_its_quantity_and_the_premium_cap_counts_fills(self):
        service = self.service()
        job = service.create_job(self.request(qty=2, premium=230, playbook='off'), T)
        state = service.heartbeat(job['id'], T, self.quote(T))
        state = self.fill(service, state['orders'][0], T, 1.05, qty=1, status='PARTIAL')
        later = T + timedelta(seconds=30)
        state = service.heartbeat(job['id'], later, self.quote(later))   # timeout: cancel the remainder
        cancel = [o for o in state['orders'] if o['kind'] == 'CANCEL'][0]
        state = self.fill(service, state['orders'][0], later, 1.05, qty=1, status='CANCELED', seq=2)
        self.assertEqual(cancel['status'], 'CREATED')
        self.assertEqual(state['state'], 'WATCH')                         # retries on the next fresh quote
        state = service.heartbeat(job['id'], later, self.quote(later))
        buy = [o for o in state['orders'] if o['side'] == 'BUY_OPEN'][-1]
        self.assertEqual((buy['quantity'], buy['limit_price']), (1, 1.06))   # second rung; 105 spent + 106 <= 230
        state = self.fill(service, buy, later, 1.06)
        self.assertEqual((state['state'], state['position_qty']), ('HELD', 2))

    def test_several_tickets_share_a_contract_and_day(self):
        service = self.service()
        a = service.create_job(self.request(), T)
        self.assertEqual(service.create_job(self.request(), T)['id'], a['id'])       # same request: same ticket
        b = service.create_job(self.request(name='second'), T)
        c = service.create_job(self.request(end_at=at(90).isoformat()), T)
        self.assertEqual(len({a['id'], b['id'], c['id']}), 3)
        with self.assertRaises(ValueError):
            service.create_job(self.request(name='second', end_at=at(30).isoformat()), T)

    def test_smart_sells_reserve_what_is_held_and_never_exceed_it(self):
        service = self.service()
        held = self.bought(service, qty=2)
        self.assertEqual(held['state'], 'HELD')
        one = service.create_job(self.request(action='sell_only', name='tp', playbook='v2'), T)
        self.assertEqual((one['state'], one['position_qty'], one['adopted_position']['average_cost']), ('IN', 1, 1.05))
        self.assertEqual(service.get_job(held['id'])['position_qty'], 1)
        two = service.create_job(self.request(action='sell_only', name='stop', playbook='v2'), T)
        self.assertEqual(service.get_job(held['id'])['state'], 'TRANSFERRED')
        with self.assertRaises(ValueError):
            service.create_job(self.request(action='sell_only', name='third'), T)
        state = service.on_frame(one['id'], self.frame(at(1), 'EXIT', 'spike_up'), at(1), self.quote(at(1)))
        self.assertEqual((state['exit_reason'], state['orders'][0]['quantity'], state['orders'][0]['limit_price']),
                         ('spike_up', 1, 1.05))                          # selling into strength chases from the mid
        state = service.on_frame(two['id'], self.frame(at(1), 'EXIT', 'stop_low'), at(1), self.quote(at(1)))
        self.assertEqual(state['orders'][0]['limit_price'], 1.0)         # leaving weakness sells at the bid
        state = self.fill(service, state['orders'][0], at(1), 1.0)
        self.assertEqual((state['state'], state['position_qty']), ('DONE', 0))

    def test_smart_sell_deadline_and_live_reservations_against_the_broker(self):
        service = self.service()
        self.bought(service, qty=1)
        sell = service.create_job(self.request(action='sell_only', end_at=at(30).isoformat(), playbook='v2'), T)
        self.assertEqual(service.heartbeat(sell['id'], at(28), self.quote(at(28)))['orders'], [])
        state = service.heartbeat(sell['id'], at(29), self.quote(at(29)))
        self.assertEqual((state['exit_reason'], state['orders'][0]['limit_price']), ('deadline', 1.0))

        self.path = Path(self.tmp.name) / 'live.sqlite'
        live = self.service('live')
        snap = PositionSnapshot('test', 'live', WEEKLY, 2, T, 2.0)
        first = live.create_job(self.request(WEEKLY, 'sell_only', qty=2), T, position=snap)
        self.assertEqual((first['state'], first['position_qty'], first['adopted_position']['average_cost']),
                         ('IN', 2, 2.0))
        with self.assertRaises(ValueError):       # the broker's 2 are already reserved by the first sell
            live.create_job(self.request(WEEKLY, 'sell_only', name='more'), T, position=snap)
        with self.assertRaises(ValueError):
            live.create_job(self.request(WEEKLY, 'sell_only', name='stale'), T,
                            position=PositionSnapshot('test', 'live', WEEKLY, 5, T - timedelta(minutes=5), 2.0))

    def test_daily_cap_counts_open_caps_and_spent_premium(self):
        service = self.service()
        first = service.create_job(self.request(premium=600, playbook='off'), T)
        with self.assertRaises(ValueError):
            service.create_job(self.request(PUT, direction='SHORT', premium=500), T)
        state = service.heartbeat(first['id'], T, self.quote(T))
        self.fill(service, state['orders'][0], T, 1.05)   # spent 105 instead of the 600 reserve
        self.assertEqual(service.create_job(self.request(PUT, direction='SHORT', premium=500), T)['state'], 'IDLE')

    def test_live_accepts_smart_orders_but_not_unaccepted_strategies(self):
        self.path = Path(self.tmp.name) / 'live.sqlite'
        live = self.service('live')
        job = live.create_job(self.request(WEEKLY), T)
        self.assertEqual((job['strategy']['status'], job['strategy']['sha256']), (MANUAL, None))
        self.assertEqual(live.create_job(self.request(WEEKLY, playbook='v2'), T)['strategy']['sha256'], PLAYBOOK_ID)
        with self.assertRaises(ValueError):
            live.create_job({'strategy_id': SID, 'symbol': 'SPY', 'direction': 'LONG', 'contract': PUT,
                             'trade_date': DAY}, T)

    def test_schema_4_databases_migrate_in_place(self):
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute("INSERT INTO meta VALUES ('schema_version', '4')")
            db.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, account TEXT NOT NULL, contract TEXT NOT NULL, '
                       'day TEXT NOT NULL, fingerprint TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(account, contract, day))')
            db.execute('CREATE TABLE orders (id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), body TEXT NOT NULL)')
            db.execute('CREATE TABLE service_modes (account TEXT PRIMARY KEY, mode TEXT NOT NULL)')
            db.execute("INSERT INTO service_modes VALUES ('test', 'dryrun')")
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?)', ('old', 'test', CALL, DAY, 'f', json.dumps({'id': 'old', 'state': 'DONE', 'request': {'trade_date': DAY, 'trade_action': 'sell_only'}})))
            db.execute('INSERT INTO orders VALUES (?,?,?)', ('old:BUY_1', 'old', json.dumps({'client_order_id': 'old:BUY_1'})))
        service = self.service()
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '5')
            self.assertEqual(db.execute('SELECT id, slot FROM jobs').fetchall(), [('old', '')])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertEqual(service.create_job(self.request(PUT, direction='SHORT'), T)['state'], 'IDLE')


class SmartRunnerTests(unittest.TestCase):
    def test_cli_builds_a_ticket(self):
        args = build_argument_parser('run').parse_args(
            ['--mode', 'live', '--acc-id', '1', '--manual', '--contract', WEEKLY, '--trade-action', 'buy_only',
             '--start-at', '10:30', '--end-at', '11:30', '--playbook', 'off', '--name', 'open-1',
             '--daily-premium-cap-usd', '500'])
        built = ticket_from_args(args, T)
        self.assertEqual(built, {'name': 'open-1', 'start_at': '2026-09-14T10:30:00-04:00',
                                 'end_at': '2026-09-14T11:30:00-04:00', 'playbook': 'off',
                                 'daily_premium_cap_usd': 500.0})
        self.assertEqual(parse_ticket(built, DAY, 'buy_only')['playbook'], 'off')

    def test_dryrun_fills_only_marketable_intents(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = CustodyService(Path(tmp) / 'jobs.sqlite', 'test', Catalog(), Calendar(), mode='dryrun')
            body = {'strategy_id': MANUAL, 'symbol': 'SPY', 'direction': 'LONG', 'contract': CALL, 'trade_date': DAY,
                    'expiry_policy': 'any', 'trade_action': 'buy_only', 'max_entry_premium': 300,
                    'ticket': ticket(playbook='off')}
            job = service.create_job(body, T)
            runner = Runner(service, None, job['id'], simulate_fills=True, logger=lambda *a, **k: None)
            state = service.heartbeat(job['id'], T, Quote(CALL, 1.0, 1.1, T))
            state = runner._simulate_fills(state, T, 600.0, Quote(CALL, 1.0, 1.1, T))
            self.assertEqual(state['position_qty'], 0)
            state = runner._simulate_fills(state, T, 600.0, Quote(CALL, 0.98, 1.05, T))
            self.assertEqual(state['position_qty'], 1)

    def test_playbook_frames_come_from_completed_bars_inside_the_window(self):
        from custody.tests.helpers import path_bars, session

        class History:
            def collect(self, boundary):
                s = session(DAY)
                bars = path_bars([600.0] * 390, day=DAY)
                return s, [b for b in bars if b.close_time <= boundary]

        class Market:
            def current_bars(self, code, count, ktype, boundary=None):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            service = CustodyService(Path(tmp) / 'jobs.sqlite', 'test', Catalog(), Calendar(), mode='dryrun')
            body = {'strategy_id': MANUAL, 'symbol': 'SPY', 'direction': 'LONG', 'contract': CALL, 'trade_date': DAY,
                    'expiry_policy': 'any', 'trade_action': 'buy_only', 'max_entry_premium': 300,
                    'ticket': ticket(start_at=at(10).isoformat(), playbook='v2')}
            job = service.create_job(body, T)
            source = PlaybookFrameSource(History(), Market())
            self.assertIsNone(source.frame(job, at(5) + timedelta(seconds=3)))      # before the window
            frame = source.frame(job, at(10) + timedelta(seconds=3))
            self.assertEqual((frame.action, frame.reason, frame.strategy_hash, frame.bar_close),
                             ('ENTER', 'chop', PLAYBOOK_ID, at(10)))       # a flat tape: patient buy at the range low
            state = service.on_frame(job['id'], frame, at(10) + timedelta(seconds=3), Quote(CALL, 1.0, 1.1, at(10)))
            self.assertEqual(state['orders'][0]['scene'], 'chop')


if __name__ == '__main__':
    unittest.main()
