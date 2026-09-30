"""Synthetic execution-policy checks; no strategy return evaluation or network I/O."""
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from custody.controller import Controller
from custody.models import Frame, OrderUpdate, PositionSnapshot, Quote
from custody.runner import Runner, build_argument_parser
from custody.service import CustodyService
from custody.tests.test_service import Adapter, Calendar, Catalog, DAY, SID, T
from custody.tests.test_broker import FakeTradeContext, Market, SIM
from custody.broker import OpenDBroker

CODE = 'US.SPY260918C600000'


class TradeActionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'jobs.sqlite'
        self.catalog = Catalog()
        self.catalog.nearest_expiry = lambda symbol, day: '2026-09-18'
        self.service = CustodyService(self.path, 'test', self.catalog, Calendar(), mode='dryrun')
        self.request = dict(strategy_id=SID, symbol='SPY', direction='LONG', contract=CODE,
                            trade_date=DAY, max_qty=2, expiry_policy='nearest', trade_action='buy_only')

    def tearDown(self):
        self.tmp.cleanup()

    def frame(self, now, action):
        return Frame('SPY', self.service.registry.get(SID)['sha256'], now, 600, action)

    def quote(self, now):
        return Quote(CODE, 1, 1.05, now)

    def buy(self, partial=False):
        job = self.service.create_job(self.request, T)
        state = self.service.on_frame(job['id'], self.frame(T, 'ENTER'), T, self.quote(T))
        order = state['orders'][0]
        self.service.apply_update(OrderUpdate(order['client_order_id'], 1, 'PARTIAL' if partial else 'FILLED',
                                             1 if partial else 2, T, 600, 1.05, T), T)
        return job, order

    def test_buy_only_retains_through_strategy_exit_stop_close_and_restart(self):
        job, _ = self.buy()
        self.service.on_frame(job['id'], self.frame(T+timedelta(minutes=1), 'EXIT'),
                              T+timedelta(minutes=1), self.quote(T+timedelta(minutes=1)))
        self.service.stop_job(job['id'], T+timedelta(minutes=2))
        service = CustodyService(self.path, 'test', None, None, mode='dryrun')
        state = service.heartbeat(job['id'], T.replace(hour=16), self.quote(T.replace(hour=16)))
        self.assertEqual((state['state'], state['position_qty']), ('HELD', 2))
        self.assertFalse(state['exit_requested'])
        self.assertFalse(any(o['side'] == 'SELL_CLOSE' for o in state['orders']))
        runner = Runner(service, None, job['id'])
        self.assertEqual(runner.tick(T+timedelta(days=1))['state'], 'HELD')

    def test_partial_buy_waits_for_cancel_confirmation_before_retaining(self):
        job, order = self.buy(partial=True)
        now = T.replace(hour=15, minute=45)
        state = self.service.heartbeat(job['id'], now, self.quote(now))
        self.assertEqual(state['state'], 'ENTRY')
        self.assertEqual(state['attention'], 'WAITING_ENTRY_CANCEL_CONFIRMATION')
        self.assertEqual([o['side'] for o in state['orders']], ['BUY_OPEN', 'CANCEL'])
        state = self.service.apply_update(OrderUpdate(order['client_order_id'], 2, 'CANCELED', 1,
                                                      now, 600, 1.05, T), now)
        self.assertEqual((state['state'], state['position_qty']), ('HELD', 1))

    def test_unfilled_buy_stops_without_a_sell(self):
        job = self.service.create_job(self.request, T)
        self.service.on_frame(job['id'], self.frame(T, 'ENTER'), T, self.quote(T))
        state = self.service.stop_job(job['id'], T)
        self.assertEqual((state['state'], state['position_qty']), ('DONE', 0))
        self.assertEqual(state['orders'][0]['status'], 'CANCELED')

    def test_next_day_transfer_and_sell_has_no_invented_entry_or_double_ownership(self):
        old, _ = self.buy()
        now = T+timedelta(days=1)
        request = dict(self.request, trade_date=now.date().isoformat(), trade_action='sell_only')
        job = self.service.create_job(request, now)
        self.assertEqual(job['adopted_position']['source_job'], old['id'])
        self.assertIsNone(job['entry_at'])
        self.assertEqual(self.service.get_job(old['id'])['state'], 'TRANSFERRED')
        self.assertEqual(self.service.get_job(old['id'])['position_qty'], 0)
        self.service.on_frame(job['id'], self.frame(now, 'ENTER'), now, self.quote(now))
        self.assertEqual(self.service.get_job(job['id'])['orders'], [])
        self.service.stop_job(job['id'], now)
        state = self.service.heartbeat(job['id'], now, self.quote(now))
        self.assertEqual([o['side'] for o in state['orders']], ['SELL_CLOSE'])
        order = state['orders'][0]
        state = self.service.apply_update(OrderUpdate(order['client_order_id'], 1, 'FILLED', 2, now,
                                                      average_option_price=1.0), now)
        self.assertEqual((state['state'], state['position_qty']), ('DONE', 0))
        self.assertIsNone(state['attention'])
        self.assertEqual(self.service.create_job(request, now)['position_qty'], 0)

    def test_sell_only_requires_evidence_and_excludes_new_buys_against_held_position(self):
        with self.assertRaisesRegex(ValueError, 'locally held'):
            self.service.create_job(dict(self.request, trade_action='sell_only'), T)
        self.buy()
        now = T+timedelta(days=1)
        request = dict(self.request, trade_date=now.date().isoformat())
        with self.assertRaisesRegex(ValueError, 'held position'):
            self.service.create_job(request, now)
        with self.assertRaisesRegex(ValueError, 'entire locally held'):
            self.service.create_job(dict(request, trade_action='sell_only', max_qty=1), now)

    def test_paper_adoption_freshness_and_scheduled_close(self):
        service = CustodyService(Path(self.tmp.name)/'paper.sqlite', 'test', self.catalog, Calendar())
        request = dict(self.request, trade_action='sell_only')
        for position in (None, PositionSnapshot('other', 'paper', CODE, 2, T),
                         PositionSnapshot('test', 'paper', CODE, 1, T),
                         PositionSnapshot('test', 'paper', CODE, 2, T-timedelta(seconds=31))):
            with self.assertRaisesRegex(ValueError, 'broker position'):
                service.create_job(request, T, position)
        job = service.create_job(request, T, PositionSnapshot('test', 'paper', CODE, 2, T, 1.05))
        now = T.replace(hour=15, minute=46)
        state = Controller(service, Adapter()).step(job['id'], now, self.quote(now))
        self.assertEqual(state['orders'][0]['side'], 'SELL_CLOSE')
        self.assertEqual(state['orders'][0]['quantity'], 2)
        self.assertEqual(service.create_job(request, now)['id'], job['id'])

    def test_broker_takeover_refuses_competing_orders(self):
        context = FakeTradeContext()
        broker = OpenDBroker(context, Market(), 'paper', SIM)
        context.positions[CODE] = 2
        self.assertEqual(broker.position_snapshot(CODE, T).quantity, 2)
        for status in ('SUBMITTED', 'FILL_CANCELLED', 'unexpected'):
            context.orders = [{'code': CODE, 'order_status': status}]
            with self.assertRaisesRegex(ValueError, 'reconcile'):
                broker.position_snapshot(CODE, T)
        self.assertEqual(context.placed, [])

    def test_cli_exposes_all_three_actions(self):
        for action in ('round_trip', 'buy_only', 'sell_only'):
            args = build_argument_parser('dryrun').parse_args([
                '--symbol', 'SPY', '--direction', 'LONG', '--contract', CODE, '--trade-action', action])
            self.assertEqual(args.trade_action, action)

    def test_runner_simulated_buy_finishes_held_without_any_broker(self):
        job = self.service.create_job(self.request, T)
        market = SimpleNamespace(quote=lambda code, now: self.quote(now),
                                 underlying_mark=lambda code, now: 600)
        frames = SimpleNamespace(frame=lambda job, now: self.frame(now, 'ENTER'))
        runner = Runner(self.service, market, job['id'], frame_source=frames,
                        simulate_fills=True, logger=lambda *args, **kwargs: None)
        state = runner.tick(T)
        self.assertEqual((state['state'], state['position_qty']), ('HELD', 2))
        self.assertEqual([o['side'] for o in state['orders']], ['BUY_OPEN'])
        self.assertIsNone(runner.controller.broker)

    def test_sell_only_late_adoption_and_entry_constraints(self):
        service = CustodyService(Path(self.tmp.name)/'late.sqlite', 'test', self.catalog, Calendar())
        request = dict(self.request, trade_action='sell_only')
        now = T.replace(hour=15, minute=50)
        for extra in ({'max_entry_premium': 200}, {'entry_valid_until': now.isoformat()}):
            with self.assertRaisesRegex(ValueError, 'entry constraints'):
                service.create_job(dict(request, **extra), now)
        job = service.create_job(request, now, PositionSnapshot('test', 'paper', CODE, 2, now, 1.05))
        state = service.heartbeat(job['id'], now, self.quote(now))
        self.assertEqual([o['side'] for o in state['orders']], ['SELL_CLOSE'])

    def test_automatic_profit_lock_survives_restart_and_ignores_stale_quotes(self):
        service = CustodyService(Path(self.tmp.name)/'exit.sqlite', 'test', self.catalog, Calendar())
        request = dict(self.request, trade_action='sell_only')
        job = service.create_job(request, T, PositionSnapshot('test', 'paper', CODE, 2, T, 1.0))
        state = service.heartbeat(job['id'], T, Quote(CODE, 1.8, 1.85, T))
        self.assertAlmostEqual(state['position_exit']['peak_gross_return'], .8)
        self.assertEqual(state['orders'], [])
        now = T+timedelta(minutes=1)
        state = service.heartbeat(job['id'], now, Quote(CODE, 9.0, 9.1, T))
        self.assertAlmostEqual(state['position_exit']['peak_gross_return'], .8)
        self.assertEqual(state['orders'], [])
        resumed = CustodyService(service.path, 'test', None, None)
        state = resumed.heartbeat(job['id'], now, Quote(CODE, 1.35, 1.4, now))
        self.assertEqual(state['exit_reason'], 'position_profit_lock')
        self.assertEqual([o['side'] for o in state['orders']], ['SELL_CLOSE'])
        order = state['orders'][0]
        state = resumed.apply_update(OrderUpdate(order['client_order_id'], 1, 'PARTIAL', 1,
                                                 now, average_option_price=1.35), now)
        self.assertEqual(state['position_qty'], 1)
        state = resumed.apply_update(OrderUpdate(order['client_order_id'], 2, 'CANCELED', 1,
                                                 now, average_option_price=1.35), now)
        now += timedelta(seconds=1)
        state = resumed.heartbeat(job['id'], now, Quote(CODE, 1.3, 1.35, now))
        self.assertEqual(state['orders'][-1]['quantity'], 1)

    def test_automatic_stop_profit_and_cost_requirement(self):
        request = dict(self.request, trade_action='sell_only')
        for price, reason in ((.65, 'position_stop_loss'), (2.1, 'position_take_profit')):
            service = CustodyService(Path(self.tmp.name)/(reason+'.sqlite'), 'test', self.catalog, Calendar())
            with self.assertRaisesRegex(ValueError, 'entry cost'):
                service.create_job(request, T, PositionSnapshot('test', 'paper', CODE, 2, T))
            job = service.create_job(request, T, PositionSnapshot('test', 'paper', CODE, 2, T, 1.0))
            state = service.heartbeat(job['id'], T, Quote(CODE, price, price+.05, T))
            self.assertEqual(state['exit_reason'], reason)
            self.assertEqual(state['orders'][0]['side'], 'SELL_CLOSE')

    def test_unvalidated_exit_policy_cannot_inherit_live_acceptance(self):
        service = CustodyService(Path(self.tmp.name)/'live.sqlite', 'test', self.catalog, Calendar(), mode='live')
        with self.assertRaisesRegex(ValueError, 'no independent validation'):
            service.create_job(dict(self.request, strategy_id='open_hold_v3', trade_action='sell_only'), T)

    def test_terminal_buy_retires_redundant_cancel_before_transfer(self):
        job, order = self.buy(partial=True)
        now = T.replace(hour=15, minute=45)
        self.service.heartbeat(job['id'], now, self.quote(now))
        state = self.service.apply_update(OrderUpdate(order['client_order_id'], 2, 'CANCELED', 1,
                                                      now, 600, 1.05, T), now)
        self.assertEqual(state['orders'][1]['status'], 'CANCELED')
        tomorrow = T+timedelta(days=1)
        adopted = self.service.create_job(dict(self.request, trade_action='sell_only', max_qty=1,
                                               trade_date=tomorrow.date().isoformat()), tomorrow)
        self.assertEqual(adopted['position_qty'], 1)

    def test_exact_decimal_stop_threshold(self):
        from custody.position_exit import POLICY, decide
        self.assertEqual(decide(POLICY, .10, .07, 0)[0], 'position_stop_loss')

    def test_simulated_exit_needs_no_underlying_and_reprices_old_unsent_intent(self):
        self.buy()
        now = T+timedelta(days=1)
        job = self.service.create_job(dict(self.request, trade_action='sell_only',
                                           trade_date=now.date().isoformat()), now)
        self.service.stop_job(job['id'], now)
        self.service.heartbeat(job['id'], now, self.quote(now))
        # No fill yet: model a process restart with an old unsent sell intent.
        later = now+timedelta(minutes=1)
        market = SimpleNamespace(quote=lambda code, stamp: Quote(CODE, .9, .95, stamp),
                                 underlying_mark=lambda code, stamp: None)
        runner = Runner(self.service, market, job['id'], simulate_fills=True,
                        logger=lambda *args, **kwargs: None)
        state = runner.tick(later)
        self.assertEqual(state['state'], 'DONE')
        self.assertEqual(state['orders'][0]['status'], 'CANCELED')
        self.assertEqual(state['orders'][-1]['average_option_price'], .9)
