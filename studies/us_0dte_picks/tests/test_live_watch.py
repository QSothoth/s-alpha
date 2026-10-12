import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from custody.models import ET, Session
from custody.engines.open_hold import OpenHold
from custody.registry import Registry
from studies.us_0dte_picks.live_watch import (STRATEGY_ID, annotate_timing, build_review_card,
    choose_drafts, option_check, reference_summary, select_candidates, summarize, validate_inputs)

DAY='2026-09-28'
NOW=datetime(2026,9,28,9,45,5,tzinfo=ET)


def option(code, ask=1.20, **changes):
    return {'code':code,'option_type':'CALL','strike_time':DAY,'option_valid':True,
            'sec_status':'NORMAL','option_contract_multiplier':100,'option_delta':.5,
            'bid_price':ask-.05,'ask_price':ask,'update_time':NOW.isoformat(),
            'volume':500,'option_strike_price':100,**changes}


def candidate(code, rank):
    return {'code':code,'direction':'LONG','rank_pre':rank,'close':100}


class LiveWatchTests(unittest.TestCase):
    def test_selected_slots_use_same_quote_and_card_cap_when_signals_arrive_separately(self):
        ranked=[candidate('US.AAA',1),candidate('US.BBB',2)]
        expensive='US.AAA260928C100000'
        affordable='US.AAA260928C101000'
        second='US.BBB260928C100000'
        quotes={'US.AAA':[option(expensive,2.5),option(affordable,1.2,option_strike_price=101)],
                'US.BBB':[option(second,1.2)]}
        choose_drafts(ranked,quotes,DAY,NOW,280,140)
        self.assertIn('entry_premium_limit',ranked[0]['contracts_checked'][0]['rejections'])
        for contract in (affordable,second):
            signals=[{'contract':contract,'signal_status':'FIRST_ENTRY_THIS_MINUTE','quote_eligible_now':True}]
            result=build_review_card(ranked,signals,DAY,NOW.replace(second=0),280,140)
            self.assertEqual(len(result['actions']),1)
            self.assertEqual(result['actions'][0]['contract'],contract)
            self.assertEqual(result['actions'][0]['custody_request']['max_entry_premium'],140)
        drafts=choose_drafts(ranked[:1],quotes,DAY,NOW,280,280)
        self.assertEqual(drafts[0]['contract'],expensive)
        self.assertEqual(drafts[0]['max_entry_premium'],280)

    def test_human_selection_limits_the_frozen_pool_and_rejects_unknown_or_empty_scope(self):
        rows = [{'code': 'US.AAPL', 'rank': 1}, {'code': 'US.NVDA', 'rank': 2}, {'code': 'US.TSLA', 'rank': 3}]
        self.assertEqual(select_candidates(rows, ' nvda,US.AAPL '), rows[:2])
        self.assertEqual(select_candidates(rows), rows)
        for symbols in ('', 'AAPL,', 'AAPL,US.AAPL', 'SPY'):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                select_candidates(rows, symbols)

    def test_nearest_expiry_flows_through_quote_checks_and_custody_request(self):
        expiry = '2026-10-02'
        ranked = [{**candidate('US.AAA', 1), 'expiry': expiry, 'expiry_policy': 'nearest'}]
        contract = 'US.AAA261002C100000'
        quotes = {'US.AAA': [option(contract, strike_time=expiry)]}
        choose_drafts(ranked, quotes, DAY, NOW, 280)
        self.assertEqual(ranked[0]['contracts_checked'][0]['rejections'], [])
        card = build_review_card(ranked, [{'contract': contract, 'signal_status': 'FIRST_ENTRY_THIS_MINUTE',
                                         'quote_eligible_now': True}], DAY, NOW.replace(second=0), 280)
        self.assertEqual(card['actions'][0]['expiry'], expiry)
        self.assertEqual(card['actions'][0]['custody_request']['expiry_policy'], 'nearest')
        quotes['US.AAA'][0]['strike_time'] = '2026-10-09'
        self.assertEqual(choose_drafts(ranked, quotes, DAY, NOW, 280), [])

    def test_after_opening_half_hour_only_the_used_volume_baseline_is_required(self):
        days=['2026-09-%02d'%d for d in [8,9,10,11,14,15,16,17,18,21,22,23,24,25]]
        rows=[{'code':'US.AAA','iv':30,'volatility_date':'2026-09-25'}]
        ranking={'trade_date':DAY,'top10':rows}
        bases={'US.AAA':{'rvol30_days':days,'rvol30_base':1000}}
        self.assertEqual(validate_inputs(ranking,bases,DAY,days+[DAY],(30,)),rows)
        with self.assertRaises(KeyError):
            validate_inputs(ranking,bases,DAY,days+[DAY])

    def test_drafts_prioritize_best_affordable_and_total_caps_fit_budget(self):
        ranked=[candidate('US.AAA',1),candidate('US.BBB',2),candidate('US.CCC',3)]
        quotes={'US.AAA':[option('US.AAA260928C100000',2.5)],
                'US.BBB':[option('US.BBB260928C100000',1.1)],
                'US.CCC':[option('US.CCC260928C100000',1.2)]}
        drafts=choose_drafts(ranked,quotes,DAY,NOW,280)
        self.assertEqual([(d['symbol'],d['max_entry_premium']) for d in drafts],[('US.AAA',280)])
        quotes['US.AAA']=[option('US.AAA260928C100000',1.2)]
        drafts=choose_drafts(ranked,quotes,DAY,NOW,280)
        self.assertEqual([d['symbol'] for d in drafts],['US.AAA','US.BBB'])
        self.assertEqual(sum(d['max_entry_premium'] for d in drafts),280)
        self.assertTrue(all(d['max_qty']==1 for d in drafts))

    def test_contract_expiry_freshness_liquidity_and_budget_are_required(self):
        valid=option('US.AAA260928C100000',2.8)
        self.assertEqual(option_check(valid,'LONG',DAY,NOW,280)['rejections'],[])
        for changes,reason in [
            ({'ask_price':2.81},'entry_premium_limit'),
            ({'strike_time':'2026-09-29'},'expiry_or_validity'),
            ({'option_contract_multiplier':10},'nonstandard_multiplier'),
            ({'update_time':(NOW-timedelta(seconds=31)).isoformat()},'stale_quote'),
            ({'update_time':(NOW+timedelta(seconds=1)).isoformat()},'stale_quote'),
            ({'option_delta':.1},'delta_below_0.30'),
            ({'volume':99},'option_volume_below_100'),
            ({'bid_price':2.0},'wide_spread'),
        ]:
            with self.subTest(reason=reason):
                self.assertIn(reason,option_check({**valid,**changes},'LONG',DAY,NOW,280)['rejections'])
        self.assertEqual(choose_drafts([candidate('US.AAA',1)],{'US.AAA':[{**valid,'volume':0}]},DAY,NOW,280),[])

    def test_completed_bars_exclude_future_and_reject_a_missing_minute(self):
        opens=NOW.replace(hour=9,minute=30,second=0)
        session=Session(DAY,opens,opens.replace(hour=16))
        rows=[]
        for i in range(1,17):
            close=100+i*.1 if i<=15 else 999
            rows.append({'time_key':(opens+timedelta(minutes=i)).strftime('%Y-%m-%d %H:%M:%S'),
                         'open':100,'high':close,'low':99,'close':close,'volume':100})
        source={'code':'US.AAA','rank':1,'iv':30,'close_t1':100}
        row,bars=summarize(rows,source,session,opens+timedelta(minutes=15),1500,1000,15)
        self.assertEqual((len(bars),row['close'],row['rvol']),(15,101.5,1.5))
        reference = reference_summary(rows,'US.SPY',session,opens+timedelta(minutes=15))
        self.assertAlmostEqual(reference['open_move_pct'],1.5)
        self.assertEqual(reference['role'],'broad_market')
        with self.assertRaisesRegex(ValueError,'incomplete'):
            summarize(rows[1:],source,session,opens+timedelta(minutes=15))
        with self.assertRaisesRegex(ValueError,'incomplete'):
            reference_summary(rows[1:],'US.SPY',session,opens+timedelta(minutes=15))

    def test_unselected_signal_is_visible_and_old_entry_is_not_a_fresh_signal(self):
        opens=NOW.replace(hour=9,minute=30,second=0)
        session=Session(DAY,opens,opens.replace(hour=16))
        raw=[{'time_key':(opens+timedelta(minutes=i)).isoformat(),
              'open':100,'high':101,'low':99,'close':100,'volume':100}
             for i in range(1,6)]
        source={'code':'US.AAA','rank':1,'iv':30,'close_t1':100}
        _,bars=summarize(raw,source,session,opens+timedelta(minutes=5))
        ranked=[candidate('US.AAA',1),candidate('US.BBB',2)]
        quotes={'US.AAA':[option('US.AAA260928C100000',2.5)],
                'US.BBB':[option('US.BBB260928C101000',1.1,option_strike_price=101)]}
        drafts=choose_drafts(ranked,quotes,DAY,NOW,280)
        self.assertEqual([d['symbol'] for d in drafts],['US.AAA'])

        def build(item,direction,session,strike):
            return OpenHold({'entry_minute':3 if strike==101 else 10,
                             'flatten_before_close_minutes':15},direction,session,strike)

        with patch('studies.us_0dte_picks.live_watch.build_strategy',side_effect=build):
            timings,signals=annotate_timing(ranked,{'US.AAA':bars,'US.BBB':bars},{},session)
            self.assertEqual(timings[drafts[0]['contract']]['signal_status'],'NO_ENTRY_YET')
            self.assertEqual([s['symbol'] for s in signals],['US.BBB'])
            self.assertEqual(signals[0]['signal_status'],'EARLIER_ENTRY_UNFILLED')
            self.assertEqual(signals[0]['first_enter_at'],(opens+timedelta(minutes=3)).isoformat())
            self.assertEqual(signals[0]['historical_quote_eligibility'],'NOT_RECONSTRUCTED')
            _,fresh=annotate_timing(ranked,{'US.AAA':bars[:3],'US.BBB':bars[:3]},{},session)
            self.assertEqual(fresh[0]['signal_status'],'FIRST_ENTRY_THIS_MINUTE')

    def test_both_sides_are_watched_and_the_signal_picks_the_side(self):
        opens=NOW.replace(hour=9,minute=30,second=0)
        session=Session(DAY,opens,opens.replace(hour=16))
        raw=[{'time_key':(opens+timedelta(minutes=i)).isoformat(),
              'open':100,'high':101,'low':99,'close':100,'volume':100} for i in range(1,6)]
        _,bars=summarize(raw,{'code':'US.AAA','rank':1,'iv':30,'close_t1':100},session,opens+timedelta(minutes=5))
        ranked=[candidate('US.AAA',1)]  # the move since the open is up ...
        call,put='US.AAA260928C100000','US.AAA260928P100000'
        choose_drafts(ranked,{'US.AAA':[option(call),option(put,option_type='PUT',option_delta=-.5)]},DAY,NOW,280)
        self.assertEqual({c['contract']:c['direction'] for c in ranked[0]['contracts_checked']},{call:'LONG',put:'SHORT'})
        self.assertTrue(all(not c['rejections'] for c in ranked[0]['contracts_checked']))

        def build(item,direction,session,strike):  # ... but only the PUT side's own signal fires
            return OpenHold({'entry_minute':5 if direction=='SHORT' else 60,
                             'flatten_before_close_minutes':15},direction,session,strike)

        with patch('studies.us_0dte_picks.live_watch.build_strategy',side_effect=build):
            _,signals=annotate_timing(ranked,{'US.AAA':bars},{},session)
        self.assertEqual([(s['contract'],s['direction'],s['signal_status']) for s in signals],
                         [(put,'SHORT','FIRST_ENTRY_THIS_MINUTE')])
        card=build_review_card(ranked,signals,DAY,NOW.replace(second=0),280)
        request=card['actions'][0]['custody_request']
        self.assertEqual((request['contract'],request['direction'],request['strategy']),(put,'SHORT',STRATEGY_ID))

    def test_session_strategy_is_the_timing_line_without_a_deadline_entry(self):
        item=Registry().get(STRATEGY_ID)
        self.assertEqual(item['config']['engine'],'zero_dte_timing')
        self.assertIsNone(item['config']['params'].get('must_enter_by_minute'))

    def test_review_card_only_contains_fresh_currently_eligible_signals(self):
        ranked=[candidate('US.AAA',1),candidate('US.BBB',2),candidate('US.CCC',3)]
        quotes={'US.AAA':[option('US.AAA260928C100000',1.2)],
                'US.BBB':[option('US.BBB260928C100000',1.3)],
                'US.CCC':[option('US.CCC260928C100000',1.1)]}
        choose_drafts(ranked,quotes,DAY,NOW,280)
        signals=[]
        for row,status,eligible in zip(ranked,
                ('EARLIER_ENTRY_UNFILLED','FIRST_ENTRY_THIS_MINUTE','FIRST_ENTRY_THIS_MINUTE'),
                (True,True,False)):
            contract=row['contracts_checked'][0]
            if not eligible:
                contract['rejections']=['wide_spread']
            signals.append({'contract':contract['contract'],'symbol':row['code'],
                            'signal_status':status,'quote_eligible_now':eligible})
        card=build_review_card(ranked,signals,DAY,NOW.replace(second=0),280)
        self.assertEqual(card['status'],'ENTER_REVIEW')
        self.assertEqual([a['symbol'] for a in card['actions']],['US.BBB'])
        self.assertEqual(card['actions'][0]['max_entry_premium'],280)
        self.assertFalse(card['orders_submitted'])


if __name__=='__main__':
    unittest.main()
