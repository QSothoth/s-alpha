"""TK1 execution timing on hand-built bars (mechanics only, not market data)."""
import unittest
from datetime import timedelta

from custody.dataset import Case, CaseData
from custody.evaluate import PRIMARY_FILL
from custody.marketdata import Bar
from custody.registry import Registry
from custody.tests.helpers import path_bars, session
from studies.us_0dte_picks import ticket_eval
from studies.us_0dte_picks.ticket_eval import inplay_set, run_ticket

CODE = 'US.SPY260914C600000'


def data(option_prices, closes=None, symbol='US.SPY'):
    s = session()
    under = path_bars(closes or [600.0] * 390, code=symbol)
    option = [Bar(CODE, s.opens + timedelta(minutes=m), p, p, p, p, 10.0) for m, p in option_prices.items()]
    return CaseData(Case(symbol, CODE, '2026-09-14', 'LONG', 600.0), s, tuple(under), tuple(option))


def flat(overrides=None, price=1.0):
    prices = {m: price for m in range(1, 391)}
    prices.update(overrides or {})
    return prices


class TicketTimingTests(unittest.TestCase):
    def run_spec(self, prices, **spec):
        spec = {'entry': 15, 'take_profit_pct': 1.0, 'stop_loss_pct': 0.5, 'exit_minute': None, **spec}
        return run_ticket(data(prices), spec, PRIMARY_FILL, Registry())

    def test_entry_fills_on_the_bar_after_the_decision(self):
        trade = self.run_spec(flat({16: 1.2}))
        self.assertEqual((trade['entry']['minute'], trade['entry']['fill_minute'], trade['entry']['price']), (15, 16, 1.2))

    def test_take_profit_and_stop_sell_on_the_next_bar(self):
        trade = self.run_spec(flat({30: 2.0, 31: 1.9}))  # zero-range bars: sellable price = close
        self.assertEqual((trade['exit']['reason'], trade['exit']['minute'], trade['exit']['fill_minute'],
                          trade['exit']['price']), ('ticket_take_profit', 30, 31, 1.9))
        trade = self.run_spec(flat({40: 0.5, 41: 0.45}))
        self.assertEqual((trade['exit']['reason'], trade['exit']['fill_minute'], trade['exit']['price']),
                         ('ticket_stop_loss', 41, 0.45))
        trade = self.run_spec(flat({40: 0.51}))
        self.assertEqual(trade['exit']['reason'], 'platform_flatten')

    def test_exit_time_and_close_buffer(self):
        trade = self.run_spec(flat(), exit_minute=360)
        self.assertEqual((trade['exit']['reason'], trade['exit']['minute'], trade['exit']['fill_minute']),
                         ('ticket_exit_at', 360, 361))
        trade = self.run_spec(flat())
        self.assertEqual((trade['exit']['minute'], trade['exit']['fill_minute']), (375, 376))

    def test_trail_sells_after_giving_back_half_of_the_peak(self):
        prices = flat({30: 3.0, 31: 2.5, 32: 2.0, 33: 1.9})   # peak gain +200%; trail at +100% = 2.0
        trade = self.run_spec(prices, take_profit_pct=None, trail_after_pct=1.0, trail_keep=0.5)
        self.assertEqual((trade['exit']['reason'], trade['exit']['minute'], trade['exit']['fill_minute'],
                          trade['exit']['price']), ('ticket_trail', 32, 33, 1.9))

    def test_no_stop_rides_a_deep_drawdown_and_trail_keeps_seventy_percent(self):
        prices = flat({40: 0.1, 41: 0.1, 60: 2.5, 61: 2.0, 62: 1.9, 63: 1.8})   # peak +150%; 0.7 x 1.5 = +105%
        trade = self.run_spec(prices, take_profit_pct=None, stop_loss_pct=None, trail_after_pct=1.0, trail_keep=0.7)
        self.assertEqual((trade['exit']['reason'], trade['exit']['minute'], trade['exit']['fill_minute']),
                         ('ticket_trail', 61, 62))

    def test_missing_option_bar_waits_for_the_next_trade(self):
        prices = flat({30: 2.0})
        del prices[31], prices[32]
        trade = self.run_spec(prices)
        self.assertEqual((trade['exit']['minute'], trade['exit']['fill_minute']), (30, 33))



class RatchetTimingTests(unittest.TestCase):
    """TK8 lock lines (notes/TK8_PREREG.md); entry fills at minute 16 at 1.0."""

    def run_spec(self, prices, closes=None, **spec):
        spec = {'entry': 15, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None, **spec}
        return run_ticket(data(prices, closes), spec, PRIMARY_FILL, Registry())

    def exit_of(self, trade):
        return trade['exit']['reason'], trade['exit']['minute'], trade['exit']['fill_minute']

    def test_ladder_moves_to_breakeven_after_fifty_percent(self):
        trade = self.run_spec(flat({30: 1.6, 31: 1.0}), ratchet='ladder')
        self.assertEqual(self.exit_of(trade), ('ticket_ratchet', 31, 32))
        trade = self.run_spec(flat({30: 1.4}), ratchet='ladder')   # never reached +50%: no lock
        self.assertEqual(trade['exit']['reason'], 'platform_flatten')

    def test_ladder_locks_one_hundred_after_two_hundred_and_steps_by_hundreds(self):
        prices = flat({m: 2.5 for m in range(31, 391)})
        prices.update({30: 3.1, 31: 2.5, 32: 2.0})                # peak +210% -> lock +100%
        self.assertEqual(self.exit_of(self.run_spec(prices, ratchet='ladder')), ('ticket_ratchet', 32, 33))
        prices = flat({m: 4.5 for m in range(30, 391)})
        prices.update({30: 5.5, 31: 4.1, 32: 4.0})                # peak +450% -> lock +300%
        self.assertEqual(self.exit_of(self.run_spec(prices, ratchet='ladder')), ('ticket_ratchet', 32, 33))

    def test_progressive_keeps_half_of_the_peak_between_one_and_two_hundred(self):
        prices = flat({m: 1.6 for m in range(30, 391)})
        prices.update({30: 2.0, 31: 1.6, 32: 1.5})                # peak +100% -> lock +50%
        self.assertEqual(self.exit_of(self.run_spec(prices, ratchet='progressive')), ('ticket_ratchet', 32, 33))

    def test_climax_sells_the_first_bar_that_stops_rising_after_a_spike(self):
        prices = flat({m: 2.2 for m in range(30, 391)})
        prices.update({27: 1.5, 28: 2.0, 29: 2.3, 30: 2.2})       # 26 -> 29 up 130%, 30 no new high
        trade = self.run_spec(prices, ratchet='ladder', climax=True)
        self.assertEqual(self.exit_of(trade), ('ticket_climax', 30, 31))
        self.assertEqual(self.run_spec(prices, ratchet='ladder')['exit']['reason'], 'platform_flatten')

    def test_late_keep_tightens_to_eighty_percent_from_two_thirty(self):
        prices = flat({m: 2.0 for m in range(280, 291)})
        prices.update({m: 1.7 for m in range(291, 391)})          # peak +100%, +70% held until 14:30
        trade = self.run_spec(prices, ratchet='ladder', late_keep=0.8)
        self.assertEqual(self.exit_of(trade), ('ticket_late_trail', 300, 301))

    def test_ema_trail_sells_when_a_five_minute_close_falls_below_its_ema(self):
        closes = [600 + .1 * m for m in range(1, 101)] + [590.0] * 290
        prices = flat({m: 2.5 for m in range(30, 391)})
        trade = self.run_spec(prices, closes, ratchet='ema')
        self.assertEqual(self.exit_of(trade), ('ticket_ema_trail', 105, 106))
        prices = flat({m: 1.8 for m in range(30, 391)})           # peak +80%: no trail yet
        self.assertEqual(self.run_spec(prices, closes, ratchet='ema')['exit']['reason'], 'platform_flatten')


class CryptoExitTimingTests(unittest.TestCase):
    """TK9 exits (notes/TK9_PREREG.md); entry fills at minute 16 at 1.0."""

    def exit_of(self, prices, **spec):
        spec = {'entry': 15, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None, **spec}
        e = run_ticket(data(prices), spec, PRIMARY_FILL, Registry())['exit']
        return e['reason'], e['minute'], e['fill_minute']

    def test_roi_target_steps_down_with_time_held(self):
        self.assertEqual(self.exit_of(flat({40: 3.9, 50: 3.0}), roi=True), ('ticket_roi', 50, 51))     # held 34: +200%
        self.assertEqual(self.exit_of(flat({100: 2.0}), roi=True), ('ticket_roi', 100, 101))           # held 84: +100%
        self.assertEqual(self.exit_of(flat({140: 1.5}), roi=True), ('ticket_roi', 140, 141))           # held 124: +50%
        self.assertEqual(self.exit_of(flat({m: .9 for m in range(17, 391)}), roi=True)[0], 'platform_flatten')
        prices = flat({m: .9 for m in range(17, 330)})                                             # 15:00: break-even
        self.assertEqual(self.exit_of(prices, roi=True), ('ticket_roi', 330, 331))

    def test_time_limit_sells_after_holding_two_hours(self):
        self.assertEqual(self.exit_of(flat(), take_profit_pct=3.0, time_limit=120), ('ticket_time_limit', 136, 137))

    def test_price_trail_starts_after_doubling_and_trails_a_quarter_from_the_high(self):
        prices = flat({m: 2.4 for m in range(30, 391)})
        prices.update({30: 3.0, 31: 2.3, 32: 2.25})              # high 3.0 -> trail at 2.25
        self.assertEqual(self.exit_of(prices, price_trail=(1.0, .75)), ('ticket_price_trail', 32, 33))
        prices = flat({m: 1.4 for m in range(30, 391)})
        prices.update({30: 1.9})                                 # never doubled: no trail
        self.assertEqual(self.exit_of(prices, price_trail=(1.0, .75))[0], 'platform_flatten')

    def test_chandelier_trails_three_option_atrs_below_the_high(self):
        prices = flat({m: 1.6 for m in range(30, 391)})
        prices.update({30: 1.6, 31: 1.6})                        # zero-range bars after 31: ATR shrinks to 0
        self.assertEqual(self.exit_of(prices, chandelier=(.5, 3.0, 14))[0], 'platform_flatten')
        prices.update({50: 1.59})
        self.assertEqual(self.exit_of(prices, chandelier=(.5, 3.0, 14))[:2], ('ticket_chandelier', 50))


class UnderlyingTrailTimingTests(unittest.TestCase):
    """TK11 underlying ATR trails (notes/TK11_PREREG.md); flat 600 bars have a 5-minute true range of 0.04."""

    def exit_of(self, prices, closes, **spec):
        spec = {'entry': 15, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None, **spec}
        e = run_ticket(data(prices, closes), spec, PRIMARY_FILL, Registry())['exit']
        return e['reason'], e['minute'], e['fill_minute']

    closes = [600.0] * 100 + [599.5] * 290                 # minute 101 closes 0.52 below the high (> 3 x 0.04)

    def test_trail_sells_the_minute_the_underlying_breaks_three_atrs_below_its_high(self):
        self.assertEqual(self.exit_of(flat(), self.closes, under_trail=(3.0, None)), ('ticket_under_trail', 101, 102))
        self.assertEqual(self.exit_of(flat(), [600.0] * 390, under_trail=(3.0, None))[0], 'platform_flatten')

    def test_activation_waits_for_two_atrs_of_favourable_move(self):
        self.assertEqual(self.exit_of(flat(), self.closes, under_trail=(1.0, 2.0))[0], 'platform_flatten')
        rise = [600.0] * 30 + [601.0] * 70 + [600.5] * 290    # +1 above entry, then 0.5 back
        self.assertEqual(self.exit_of(flat(), rise, under_trail=(1.0, 2.0))[:2], ('ticket_under_trail', 101))

    def test_pure_underlying_risk_ignores_the_option_stop(self):
        prices = flat({m: .4 for m in range(40, 391)})
        self.assertEqual(self.exit_of(prices, [600.0] * 390, under_trail=(3.0, None))[0], 'ticket_stop_loss')
        self.assertEqual(self.exit_of(prices, [600.0] * 390, under_trail=(3.0, None), stop_loss_pct=None)[0],
                         'platform_flatten')

    def test_account_view_sums_days_and_measures_drawdown(self):
        from types import SimpleNamespace
        datas = [SimpleNamespace(case=SimpleNamespace(trade_date=day)) for day in ('2026-09-14', '2026-09-15', '2026-09-16')]
        trades = [{'net_return': 1.0}, {'net_return': -0.5}, {'net_return': None}]
        a = ticket_eval.account(datas, trades)
        self.assertEqual((a['days'], a['total'], a['max_drawdown']), (3, 0.5, 0.5))


class PositionTimingTests(unittest.TestCase):
    """TK12 positions (notes/TK12_PREREG.md); every contract enters at minute 16 at 1.0."""

    def position(self, prices, legs):
        legs = [{**leg, 'entry': 15} for leg in legs]
        return ticket_eval.run_position(data(prices), legs, PRIMARY_FILL, Registry())

    def test_two_contracts_sell_one_at_double_and_stop_the_rest_at_breakeven(self):
        prices = flat({m: 1.5 for m in range(30, 391)})
        prices.update({30: 2.0, 31: 2.0, 40: 1.0, 41: 1.0})
        pos = self.position(prices, ticket_eval.TK12['P2A'])
        self.assertEqual([(e['reason'], e['minute'], e['fill_minute']) for e in pos['contracts']],
                         [('ticket_take_profit', 30, 31), ('ticket_ratchet', 40, 41)])
        first = (2.0 - 1.0) * 100 - 2 * .65
        second = (1.0 - 1.0) * 100 - 2 * .65
        self.assertAlmostEqual(pos['net_return'], (first + second) / 2 / 100)

    def test_third_contract_locks_one_hundred_after_the_second_target(self):
        prices = flat({m: 2.5 for m in range(30, 391)})
        prices.update({30: 3.1, 31: 3.1, 40: 2.0, 41: 2.0})
        pos = self.position(prices, ticket_eval.TK12['P3C'])
        self.assertEqual([(e['reason'], e['minute']) for e in pos['contracts']],
                         [('ticket_take_profit', 30), ('ticket_take_profit', 30), ('ticket_ratchet', 40)])

    def test_no_signal_means_no_position(self):
        pos = self.position(flat(), ticket_eval.TK12['P3A'])
        self.assertIsNotNone(pos['entry'])
        legs = [{**leg, 'entry': 400} for leg in ticket_eval.TK12['P2B']]
        self.assertIsNone(ticket_eval.run_position(data(flat()), legs, PRIMARY_FILL, Registry())['entry'])


class PriceActionTimingTests(unittest.TestCase):
    """TK13 price-action legs (notes/TK13_PREREG.md); entry fills at minute 16 at 1.0; flat 600 has lows 599.98."""

    spike = {27: 1.5, 28: 2.0, 29: 2.3, 30: 2.2}               # 26 -> 29 up 130%, 30 the first lower bar

    def exits(self, prices, legs, closes=None):
        legs = [{**leg, 'entry': 15} for leg in legs]
        pos = ticket_eval.run_position(data(prices, closes), legs, PRIMARY_FILL, Registry())
        return [(e['reason'], e['minute']) for e in pos['contracts']]

    def after_spike(self, extra=None):
        prices = flat({m: 2.2 for m in range(30, 391)})
        prices.update(self.spike)
        prices.update(extra or {})
        return prices

    def test_structure_stop_before_any_strength(self):
        closes = [600.0] * 29 + [599.9] * 361
        self.assertEqual(self.exits(flat(), ticket_eval.TK13['S1'], closes), [('ticket_structure_stop', 30)])

    def test_first_contract_sells_into_strength_and_the_runner_holds(self):
        self.assertEqual(self.exits(self.after_spike(), ticket_eval.TK13['S2']),
                         [('ticket_strength', 30), ('platform_flatten', 375)])

    def test_runner_moves_to_breakeven_after_the_first_sale(self):
        prices = self.after_spike({m: 1.0 for m in range(50, 391)})
        self.assertEqual(self.exits(prices, ticket_eval.TK13['S2']), [('ticket_strength', 30), ('ticket_ratchet', 50)])

    def test_second_contract_waits_for_a_new_high_and_a_second_strength_event(self):
        prices = self.after_spike({34: 2.4, 35: 2.8, 36: 3.0, **{m: 2.9 for m in range(37, 391)}})
        self.assertEqual(self.exits(prices, ticket_eval.TK13['S3'])[:2], [('ticket_strength', 30), ('ticket_strength', 37)])

    def test_swing_and_vwap_trails_after_the_first_sale(self):
        closes = [600.0] * 59 + [599.99] * 331                 # below VWAP (600), above the swing lows (599.98)
        self.assertEqual(self.exits(self.after_spike(), ticket_eval.TK13['S5'], closes),
                         [('ticket_strength', 30), ('platform_flatten', 375), ('ticket_vwap_trail', 60)])
        closes = [600.0] * 59 + [599.9] * 331
        self.assertEqual(self.exits(self.after_spike(), ticket_eval.TK13['S4'], closes)[1], ('ticket_swing_trail', 60))

    def test_ema_trail_waits_for_a_five_minute_close(self):
        closes = [600.0] * 57 + [599.0] * 333
        self.assertEqual(self.exits(self.after_spike(), ticket_eval.TK13['S1'], closes), [('ticket_ema_trail', 60)])


class RMultipleTimingTests(unittest.TestCase):
    """TK14 (notes/TK14_PREREG.md): entry fills at minute 16 with the underlying at 600; the 15 minutes before
    have lows 599.98, so R = max(0.02, ATR 0.04) = 0.04 on flat bars."""

    def exits(self, closes, legs, prices=None):
        legs = [{**leg, 'entry': 15} for leg in legs]
        pos = ticket_eval.run_position(data(prices or flat(), closes), legs, PRIMARY_FILL, Registry())
        return [(e['reason'], e['minute']) for e in pos['contracts']]

    def test_structure_stop_before_one_r(self):
        closes = [600.0] * 29 + [599.97] * 361
        self.assertEqual(self.exits(closes, ticket_eval.TK14['T1']), [('ticket_structure_stop', 30)])

    def test_breakeven_after_one_r(self):
        closes = [600.0] * 29 + [600.05] * 10 + [599.99] * 351   # high 600.07 = 1.75R, then below entry
        self.assertEqual(self.exits(closes, ticket_eval.TK14['T1']), [('ticket_breakeven', 40)])

    def test_first_contract_sells_the_first_lower_close_after_two_r(self):
        closes = [600.0] * 29 + [600.1, 600.2, 600.3, 600.25] + [600.3] * 357
        self.assertEqual(self.exits(closes, ticket_eval.TK14['T2'])[0], ('ticket_r_strength', 33))   # 30-32 still rising

    def test_second_contract_waits_for_four_r(self):
        closes = [600.0] * 29 + [600.1, 600.2, 600.3, 600.25] + [600.3] * 357
        self.assertEqual([r for r, _ in self.exits(closes, ticket_eval.TK14['T3'])][:2],
                         ['ticket_r_strength', 'ticket_r_strength'])
        self.assertEqual(self.exits(closes, ticket_eval.TK14['T3'])[1], ('ticket_r_strength', 33))
        closes = [600.0] * 29 + [600.07] + [600.06] * 360        # high 600.09 = 2.25R: only the first sells
        reasons = self.exits(closes, ticket_eval.TK14['T3'])
        self.assertEqual(reasons[0], ('ticket_r_strength', 31))
        self.assertNotEqual(reasons[1][0], 'ticket_r_strength')

    def test_runner_trails_after_two_r(self):
        closes = [600.0] * 29 + [600.3] * 30 + [600.05] * 331   # 2R reached, then a 5-minute close under EMA9
        self.assertEqual(self.exits(closes, ticket_eval.TK14['T1']), [('ticket_ema_trail', 60)])


class EntryWaitTimingTests(unittest.TestCase):
    """TK10 buy rules (notes/TK10_PREREG.md); the signal is minute 15."""

    def entry(self, prices, **spec):
        spec = {'entry': 15, 'take_profit_pct': None, 'stop_loss_pct': 0.5, 'exit_minute': None, **spec}
        e = run_ticket(data(prices), spec, PRIMARY_FILL, Registry())['entry']
        return e['minute'], e['fill_minute'], e['price']

    def test_no_chase_waits_for_the_first_lower_bar_after_a_spike(self):
        spike = {12: 1.0, 13: 1.1, 14: 1.2, 15: 1.3}
        prices = flat({**spike, 16: 1.4, 17: 1.35, 18: 1.36})
        self.assertEqual(self.entry(prices, entry_wait='no_chase', wait_minutes=5), (17, 18, 1.36))
        prices = flat({**spike, **{m: 1.3 + .01 * (m - 15) for m in range(16, 30)}})
        self.assertEqual(self.entry(prices, entry_wait='no_chase', wait_minutes=5)[:2], (20, 21))
        prices = flat({**spike, 16: 1.6, 17: 1.7})                 # +23% over the signal price: buy now
        self.assertEqual(self.entry(prices, entry_wait='no_chase', wait_minutes=5)[:2], (16, 17))
        self.assertEqual(self.entry(flat(), entry_wait='no_chase', wait_minutes=5)[:2], (15, 16))

    def test_dip_waits_for_five_percent_cheaper_or_ten_minutes(self):
        self.assertEqual(self.entry(flat({18: 0.94, 19: 0.93}), entry_wait='dip', wait_minutes=10), (18, 19, 0.93))
        self.assertEqual(self.entry(flat({18: 0.96}), entry_wait='dip', wait_minutes=10)[:2], (25, 26))

    def test_pullback_waits_for_the_first_lower_bar(self):
        self.assertEqual(self.entry(flat({16: 1.1, 17: 1.05}), entry_wait='pullback', wait_minutes=5)[:2], (17, 18))
        self.assertEqual(self.entry(flat(), entry_wait='pullback', wait_minutes=5)[:2], (20, 21))


class OrbTimingTests(unittest.TestCase):
    ORB = {'orb': 30, 'stop': 'opposite'}

    def closes(self, after):
        # opening range 599.9-600.1 (wick 0.02 around 600 +/- 0.08), then the given path from minute 31
        base = [600.0 + (0.08 if i % 2 else -0.08) for i in range(30)]
        return base + after + [after[-1]] * (360 - len(after))

    def test_breakout_after_the_range_fills_next_bar_and_stops_at_the_far_side(self):
        path = [600.0, 600.5, 600.6] + [600.6] * 10 + [599.5]
        trade = run_ticket(data(flat(), self.closes(path)), self.ORB, PRIMARY_FILL, Registry())
        self.assertEqual((trade['entry']['minute'], trade['entry']['fill_minute']), (32, 33))
        self.assertEqual((trade['exit']['reason'], trade['exit']['minute']), ('orb_stop', 44))

    def test_breakeven_after_two_risks(self):
        # entry mark = close of the fill minute 33 (600.5), risk 0.6 to the range low 599.9; 2R reached at 603
        path = [600.0, 600.5, 600.5] + [603.0] * 5 + [600.4]
        trade = run_ticket(data(flat(), self.closes(path)), self.ORB, PRIMARY_FILL, Registry())
        self.assertEqual((trade['exit']['reason'], trade['exit']['minute']), ('breakeven_stop', 39))

    def test_swing_stop_sits_within_two_atr_of_the_decision_close(self):
        # ATR about 0.22, so the stop is capped near 600.5 - 2 ATR = 600.06, above the 599.9 range low
        path = [600.0, 600.5] + [600.5] * 10 + [600.0]
        swing = run_ticket(data(flat(), self.closes(path)), {'orb': 30, 'stop': 'swing'}, PRIMARY_FILL, Registry())
        self.assertEqual(swing['entry']['minute'], 32)
        self.assertEqual((swing['exit']['reason'], swing['exit']['minute']), ('orb_stop', 43))
        wide = run_ticket(data(flat(), self.closes(path)), {'orb': 30, 'stop': 'opposite'}, PRIMARY_FILL, Registry())
        self.assertEqual(wide['exit']['reason'], 'platform_flatten')

    def test_no_breakout_no_entry_and_inplay_filter(self):
        trade = run_ticket(data(flat(), self.closes([600.0])), self.ORB, PRIMARY_FILL, Registry())
        self.assertIsNone(trade['entry'])
        wide = data(flat(), [600.0 + (3 if i % 2 else -3) for i in range(30)] + [600.0] * 360, 'US.AAA')
        narrow = data(flat(), self.closes([600.0]), 'US.BBB')
        self.assertEqual(inplay_set([wide, narrow], top=1), {('US.AAA', '2026-09-14')})
        ticket_eval.INPLAY.clear()
        trade = run_ticket(data(flat(), self.closes([600.0, 600.5])), {**self.ORB, 'inplay': True}, PRIMARY_FILL, Registry())
        self.assertIsNone(trade['entry'])


if __name__ == '__main__':
    unittest.main()
