from copy import deepcopy
from datetime import datetime, timedelta
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custody.models import ET
from studies.us_0dte_picks.auto_watch import handoff_card, load_authorization, main
from studies.us_0dte_picks.session import (accept as real_accept, authorize, check_handoff_authorization,
                                          RejectedEntryQuote, selected_action, StaleReviewCard, status,
                                          validate_authorization)

NOW = datetime(2026, 9, 30, 9, 45, 5, tzinfo=ET)


def prepared(folder):
    (folder/'ranking.json').write_text(json.dumps({'trade_date': '2026-09-30',
        'top10': [{'code':'US.AAA'}, {'code':'US.BBB'}]}))
    (folder/'monitor').mkdir()
    (folder/'monitor/ready.json').write_text(json.dumps({'trade_date':'2026-09-30', 'candidates':['US.AAA']}))


def card():
    actions=[]
    for symbol in ('US.AAA', 'US.BBB'):
        contract=symbol+'260930C100000'
        request={'strategy':'zero_dte_timing_v6.6', 'symbol':symbol, 'direction':'LONG',
                 'contract':contract, 'max_qty':1, 'max_entry_premium':140, 'expiry_policy':'nearest'}
        actions.append({'symbol':symbol, 'direction':'LONG', 'contract':contract, 'custody_request':request})
    return {'trade_date':'2026-09-30', 'as_of':NOW.replace(second=0).isoformat(),
            'valid_until':(NOW.replace(second=0)+timedelta(minutes=1)).isoformat(),
            'status':'ENTER_REVIEW', 'actions':actions}


class AutoWatchTests(unittest.TestCase):
    def test_card_expired_or_replaced_while_waiting_for_lock_never_starts_preflight(self):
        for automatic in (False, True):
            for race in ('expiry', 'replacement'):
                with self.subTest(automatic=automatic, race=race), tempfile.TemporaryDirectory() as tmp:
                    root=Path(tmp);prepared(root);runtime=root/'runtime'
                    permission=authorize(root,'AAA','dryrun',None,'FUTUSECURITIES',True,
                                         until='09:48',now=NOW)['authorization'] if automatic else None
                    current=card();current['actions']=current['actions'][:1]
                    current['actions'][0]['expiry']='2026-09-30'
                    path=root/'monitor/review_card.json';path.write_text(json.dumps(current))
                    now=[NOW]
                    def waited_for_lock(*args):
                        if race=='expiry':now[0]=NOW.replace(minute=46,second=0)
                        else:path.write_text(json.dumps(dict(current,updated_quote=True)))
                    with patch('studies.us_0dte_picks.session.RUNTIME',runtime), \
                         patch('studies.us_0dte_picks.session.datetime') as clock, \
                         patch('studies.us_0dte_picks.session.fcntl.flock',side_effect=waited_for_lock), \
                         patch('studies.us_0dte_picks.session.subprocess.run',
                               side_effect=AssertionError('stale card launched slow preflight')) as process, \
                         patch('custody.opend.OpenDMarket') as market:
                        clock.now.side_effect=lambda *args:now[0]
                        with self.assertRaises(StaleReviewCard):
                            real_accept(root,current['actions'][0]['contract'],'dryrun',None,
                                        'FUTUSECURITIES',True,authorization=permission)
                        process.assert_not_called();market.assert_not_called()
                    self.assertFalse((runtime/'2026-09-30/dryrun/ledger.json').exists())
                    self.assertEqual(list(runtime.rglob('preflight-*')),[])
                    if automatic:self.assertEqual(json.loads((root/'authorization.json').read_text()),permission)

    def test_cli_exit_status_matches_recorded_failure_or_permission_expiry(self):
        script = """
import runpy
import sys
from datetime import datetime
from unittest.mock import patch
from custody.models import ET

folder, outcome = sys.argv[1:]
sys.argv = ['auto_watch', '--session', folder]
class TestClock(datetime):
    calls = 0
    @classmethod
    def now(cls, tz=None):
        cls.calls += 1
        if outcome == 'expired' and cls.calls > 1:
            return cls(2026, 9, 30, 15, 45, tzinfo=ET)
        return cls(2026, 9, 30, 9, 45, 5, tzinfo=ET)
with patch('datetime.datetime', TestClock):
    runpy.run_module('studies.us_0dte_picks.auto_watch', run_name='__main__')
"""
        for outcome, expected_code, expected_status in (
                ('failed', 1, 'STOPPED_REQUIRES_REVIEW'),
                ('expired', 0, 'ENTRY_AUTHORIZATION_EXPIRED')):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); prepared(root)
                authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', True, now=NOW)
                (root/'monitor/review_card.json').write_text('{invalid')
                result = subprocess.run([sys.executable, '-c', script, str(root), outcome],
                                        capture_output=True, text=True, timeout=5)
                final = json.loads((root/'auto/final.json').read_text())
                self.assertEqual(final['status'], expected_status)
                self.assertEqual(final['handoffs'], [])
                self.assertEqual(result.returncode, expected_code, result.stderr)

    def test_invalid_contract_or_malformed_quote_still_stops_before_any_reservation(self):
        for changes, expiry in (({'option_type':'PUT'},'2026-09-30'),
                                ({'option_valid':False},'2026-09-30'),
                                ({'option_contract_multiplier':10},'2026-09-30'),
                                ({'bid_price':None},'2026-09-30'),
                                ({'code':'US.BBB260930C100000'},'2026-09-30'),
                                ({'strike_time':'2026-10-02'},'2026-10-02')):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); prepared(root); runtime=root/'runtime'
                permission=authorize(root,'AAA','dryrun',None,'FUTUSECURITIES',True,now=NOW)['authorization']
                current=card(); current['actions']=current['actions'][:1]
                current['actions'][0]['expiry']='2026-09-30'
                (root/'monitor/review_card.json').write_text(json.dumps(current))
                contract=current['actions'][0]['contract']
                quote={'code':contract,'option_type':'CALL','strike_time':'2026-09-30',
                       'option_valid':True,'sec_status':'NORMAL','option_contract_multiplier':100,'option_delta':.5,
                       'bid_price':1.0,'ask_price':1.2,'volume':500,'option_strike_price':100,
                       'update_time':NOW.isoformat(),**changes}  # structural rejection plus an ordinary wide spread
                def process(command, **kwargs):
                    self.assertNotEqual(command[0],'systemd-run')
                    db=Path(command[command.index('--db')+1])
                    with sqlite3.connect(db) as conn:
                        conn.execute('CREATE TABLE jobs (body TEXT)')
                        conn.execute('INSERT INTO jobs VALUES (?)',(json.dumps(
                            {'id':contract,'position_qty':1,'request':{'contract':contract}}),))
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                with patch('studies.us_0dte_picks.auto_watch.RUNTIME',runtime), \
                     patch('studies.us_0dte_picks.session.RUNTIME',runtime), \
                     patch('studies.us_0dte_picks.auto_watch.datetime') as auto_clock, \
                     patch('studies.us_0dte_picks.session.datetime') as accept_clock, \
                     patch('studies.us_0dte_picks.auto_watch.accept',side_effect=real_accept), \
                     patch('studies.us_0dte_picks.session.subprocess.run',side_effect=process) as run, \
                     patch('studies.us_0dte_picks.auto_watch.time.sleep') as sleep, \
                     patch('custody.opend.OpenDMarket') as market, \
                     patch('custody.opend.OpenDContractResolver') as resolver:
                    auto_clock.now.return_value=accept_clock.now.return_value=NOW
                    resolver.return_value.nearest_expiry.return_value=expiry
                    market.return_value.__enter__.return_value.snapshot.return_value={contract:quote}
                    self.assertEqual(main(['--session',str(root)]),1)
                    self.assertEqual(run.call_count,1); sleep.assert_not_called()
                final=json.loads((root/'auto/final.json').read_text())
                self.assertEqual(final['status'],'STOPPED_REQUIRES_REVIEW')
                self.assertEqual(final['handoffs'],[])
                self.assertIn('live contract check failed',final['error'])
                self.assertNotIn('last_skipped_quote',final)
                self.assertFalse((runtime/'2026-09-30/dryrun/ledger.json').exists())
                self.assertEqual(json.loads((root/'authorization.json').read_text()),permission)

    def test_quote_rejection_keeps_permission_and_waits_without_retrying_the_same_card(self):
        for changes, reason in (({'bid_price': 1.4, 'ask_price': 1.5}, 'entry_premium_limit'),
                                ({'bid_price': 1.0}, 'wide_spread'),
                                ({'update_time': (NOW-timedelta(seconds=31)).isoformat()}, 'stale_quote'),
                                ({'option_delta': .2}, 'delta_below_0.30'),
                                ({'volume': 99}, 'option_volume_below_100'),
                                ({'sec_status': 'HALT'}, 'security_status')):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); prepared(root); runtime=root/'runtime'
                permission=authorize(root,'AAA','dryrun',None,'FUTUSECURITIES',True,until='09:48',now=NOW)['authorization']
                current=card(); current['actions']=current['actions'][:1]
                current['actions'][0]['expiry']='2026-09-30'
                path=root/'monitor/review_card.json'; path.write_text(json.dumps(current))
                now=[NOW]; commands=[]; sleeps=[]; snapshots=[]
                quote={'code':current['actions'][0]['contract'],'option_type':'CALL','strike_time':'2026-09-30',
                       'option_valid':True,'sec_status':'NORMAL','option_contract_multiplier':100,'option_delta':.5,
                       'bid_price':1.1,'ask_price':1.2,'volume':500,'option_strike_price':100}
                def process(command, **kwargs):
                    commands.append(command)
                    db=Path(command[command.index('--db')+1]); contract=command[command.index('--contract')+1]
                    with sqlite3.connect(db) as conn:
                        conn.execute('CREATE TABLE IF NOT EXISTS jobs (body TEXT)')
                        conn.execute('INSERT INTO jobs VALUES (?)',(json.dumps(
                            {'id':contract,'position_qty':1,'request':{'contract':contract}}),))
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                def snapshot(*args):
                    snapshots.append(args)
                    row=dict(quote,update_time=now[0].isoformat())
                    if len(snapshots)==1: row.update(changes)
                    return {quote['code']:row}
                def sleep(seconds):
                    sleeps.append(seconds)
                    if len(sleeps)<=2:
                        self.assertFalse((runtime/'2026-09-30/dryrun/ledger.json').exists())
                        self.assertEqual(len(commands),1)
                        self.assertEqual(len(snapshots),1)
                    if len(sleeps)==1: now[0]+=timedelta(seconds=2)  # unchanged card must not be retried
                    elif len(sleeps)==2:
                        now[0]=NOW+timedelta(minutes=1)
                        path.write_text(json.dumps(dict(current,as_of=now[0].replace(second=0).isoformat(),
                            valid_until=now[0].replace(minute=47,second=0).isoformat())))
                    else: now[0]=NOW.replace(minute=48,second=0)
                with patch('studies.us_0dte_picks.auto_watch.RUNTIME',runtime), \
                     patch('studies.us_0dte_picks.session.RUNTIME',runtime), \
                     patch('studies.us_0dte_picks.auto_watch.datetime') as auto_clock, \
                     patch('studies.us_0dte_picks.session.datetime') as accept_clock, \
                     patch('studies.us_0dte_picks.auto_watch.accept',side_effect=real_accept), \
                     patch('studies.us_0dte_picks.session.subprocess.run',side_effect=process), \
                     patch('studies.us_0dte_picks.auto_watch.time.sleep',side_effect=sleep), \
                     patch('custody.opend.OpenDMarket') as market, \
                     patch('custody.opend.OpenDContractResolver') as resolver:
                    auto_clock.now.side_effect=accept_clock.now.side_effect=lambda *args:now[0]
                    resolver.return_value.nearest_expiry.return_value='2026-09-30'
                    market.return_value.__enter__.return_value.snapshot.side_effect=snapshot
                    self.assertEqual(main(['--session',str(root)]),0)
                final=json.loads((root/'auto/final.json').read_text())
                events=[json.loads(line) for line in (root/'auto/events.jsonl').read_text().splitlines()]
                self.assertEqual(events[0]['status'],'SKIPPED_ENTRY_QUOTE')
                self.assertIn(reason,events[0]['reason'])
                self.assertEqual(final['last_skipped_quote']['reason'],events[0]['reason'])
                self.assertEqual(final['status'],'ENTRY_AUTHORIZATION_EXPIRED')
                self.assertEqual(len(final['handoffs']),1)
                self.assertEqual(json.loads((root/'authorization.json').read_text()),permission)
                ledger=json.loads((runtime/'2026-09-30/dryrun/ledger.json').read_text())
                self.assertEqual([(row['state'],row['cap']) for row in ledger['accepted']],[('JOB_CREATED',140)])
                self.assertEqual(len(commands),3)
                self.assertEqual(sum(command[0]=='systemd-run' for command in commands),1)

    def test_preflight_card_replacement_or_expiry_waits_for_a_new_card_under_original_permission(self):
        for race in ('replacement', 'expiry', 'quote_replacement', 'lock_replacement', 'lock_expiry'):
            with self.subTest(race=race), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prepared(root);runtime=root/'runtime'
                permission=authorize(root,'AAA','dryrun',None,'FUTUSECURITIES',True,until='09:48',now=NOW)['authorization']
                path=root/'monitor/review_card.json';current=card()
                current['actions']=current['actions'][:1];current['actions'][0]['expiry']='2026-09-30'
                path.write_text(json.dumps(current))
                now=[NOW];commands=[];sleeps=[];locks=[]
                def waited_for_lock(*args):
                    locks.append(args)
                    if len(locks)==1:
                        if race=='lock_expiry':now[0]=NOW.replace(minute=46,second=0)
                        elif race=='lock_replacement':path.write_text(json.dumps(dict(current,updated_quote=True)))
                def process(command, **kwargs):
                    commands.append(command)
                    db=Path(command[command.index('--db')+1])
                    contract=command[command.index('--contract')+1]
                    with sqlite3.connect(db) as conn:
                        conn.execute('CREATE TABLE IF NOT EXISTS jobs (body TEXT)')
                        conn.execute('INSERT INTO jobs VALUES (?)',(json.dumps(
                            {'id':contract,'position_qty':1,'request':{'contract':contract}}),))
                    if len(commands)==1:
                        if race=='replacement':path.write_text(json.dumps(dict(current,updated_quote=True)))
                        elif race=='expiry':now[0]=NOW.replace(minute=46,second=0)
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                def sleep(seconds):
                    sleeps.append(seconds)
                    if len(sleeps)==1:
                        self.assertFalse((runtime/'2026-09-30/dryrun/ledger.json').exists())
                        if race.startswith('lock_'):self.assertEqual(commands,[])
                        now[0]=NOW+timedelta(minutes=1)
                        fresh=dict(current,as_of=now[0].replace(second=0).isoformat(),
                                   valid_until=now[0].replace(minute=47,second=0).isoformat())
                        path.write_text(json.dumps(fresh))
                    else:now[0]=NOW.replace(minute=48,second=0)
                quote={'code':current['actions'][0]['contract'],'option_type':'CALL','strike_time':'2026-09-30',
                       'option_valid':True,'sec_status':'NORMAL','option_contract_multiplier':100,'option_delta':.5,
                       'bid_price':1.1,'ask_price':1.2,'volume':500,'option_strike_price':100}
                def snapshot(*args):
                    if race=='quote_replacement' and len(commands)==1:
                        path.write_text(json.dumps(dict(current,updated_quote=True)))
                    return {quote['code']:dict(quote,update_time=now[0].isoformat())}
                with patch('studies.us_0dte_picks.auto_watch.RUNTIME',runtime), \
                     patch('studies.us_0dte_picks.session.RUNTIME',runtime), \
                     patch('studies.us_0dte_picks.auto_watch.datetime') as auto_clock, \
                     patch('studies.us_0dte_picks.session.datetime') as accept_clock, \
                     patch('studies.us_0dte_picks.auto_watch.accept',side_effect=real_accept), \
                     patch('studies.us_0dte_picks.session.fcntl.flock',side_effect=waited_for_lock), \
                     patch('studies.us_0dte_picks.session.subprocess.run',side_effect=process), \
                     patch('studies.us_0dte_picks.auto_watch.time.sleep',side_effect=sleep), \
                     patch('custody.opend.OpenDMarket') as market, \
                     patch('custody.opend.OpenDContractResolver') as resolver:
                    auto_clock.now.side_effect=accept_clock.now.side_effect=lambda *args:now[0]
                    resolver.return_value.nearest_expiry.return_value='2026-09-30'
                    market.return_value.__enter__.return_value.snapshot.side_effect=snapshot
                    self.assertEqual(main(['--session',str(root)]),0)
                final=json.loads((root/'auto/final.json').read_text())
                events=[json.loads(line) for line in (root/'auto/events.jsonl').read_text().splitlines()]
                self.assertEqual(final['status'],'ENTRY_AUTHORIZATION_EXPIRED')
                self.assertEqual(len(final['handoffs']),1)
                self.assertEqual(events[0]['status'],'SKIPPED_STALE_REVIEW')
                self.assertEqual(events[1]['handoff']['state'],'JOB_CREATED')
                self.assertEqual(json.loads((root/'authorization.json').read_text()),permission)
                ledger=json.loads((runtime/'2026-09-30/dryrun/ledger.json').read_text())
                self.assertEqual(len(ledger['accepted']),1)
                self.assertEqual(ledger['accepted'][0]['state'],'JOB_CREATED')
                self.assertEqual(ledger['accepted'][0]['cap'],140)
                self.assertEqual(len(commands),2 if race.startswith('lock_') else 3)
                self.assertEqual(sum(command[0]=='systemd-run' for command in commands),1)

    def test_stale_review_does_not_hide_revocation_or_changed_authorization(self):
        for rejection, changes in ((kind, change) for kind in (StaleReviewCard, RejectedEntryQuote) for change in
                ({'revoked_at':NOW.isoformat()},{'valid_until':NOW.replace(hour=15,minute=44).isoformat()})):
            with self.subTest(rejection=rejection,changes=changes), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);prepared(root)
                permission=authorize(root,'AAA','dryrun',None,'FUTUSECURITIES',True,now=NOW)['authorization']
                (root/'monitor/review_card.json').write_text(json.dumps(card()))
                def stale(*args,**kwargs):
                    (root/'authorization.json').write_text(json.dumps(dict(permission,**changes)))
                    raise rejection('preflight opportunity rejected')
                with patch('studies.us_0dte_picks.auto_watch.RUNTIME',root/'runtime'), \
                     patch('studies.us_0dte_picks.auto_watch.datetime') as clock, \
                     patch('studies.us_0dte_picks.auto_watch.accept',side_effect=stale) as accept, \
                     patch('studies.us_0dte_picks.auto_watch.time.sleep') as sleep, \
                     patch('studies.us_0dte_picks.session.subprocess.run') as process:
                    clock.now.return_value=NOW
                    self.assertEqual(main(['--session',str(root)]),1)
                    self.assertEqual(accept.call_count,1);sleep.assert_not_called();process.assert_not_called()
                final=json.loads((root/'auto/final.json').read_text())
                self.assertEqual(final['status'],'STOPPED_REQUIRES_REVIEW')
                self.assertEqual(final['handoffs'],[])

    def test_successful_handoff_is_preserved_and_not_repeated_after_next_card_goes_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepared(root);runtime=root/'runtime'
            (root/'monitor/ready.json').write_text(json.dumps({'trade_date':'2026-09-30','candidates':['US.AAA','US.BBB']}))
            permission=authorize(root,'AAA,BBB','dryrun',None,'FUTUSECURITIES',True,until='09:48',now=NOW)['authorization']
            path=root/'monitor/review_card.json';path.write_text(json.dumps(card()))
            now=[NOW];calls=[];sleeps=[]
            ledger_path=runtime/'2026-09-30/dryrun/ledger.json'
            def accept(folder,contract,*args,**kwargs):
                calls.append(contract)
                if len(calls)==2:raise StaleReviewCard('review card expired or invalid')
                ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else {'accepted':[]}
                ledger['accepted'].append({'symbol':'US.AAA' if len(calls)==1 else 'US.BBB',
                    'contract':contract,'cap':140,'state':'JOB_CREATED'})
                ledger_path.parent.mkdir(parents=True,exist_ok=True);ledger_path.write_text(json.dumps(ledger))
                return {'job_id':contract,'state':'JOB_CREATED'}
            def sleep(seconds):
                sleeps.append(seconds)
                if len(sleeps)==1:
                    now[0]=NOW+timedelta(minutes=1)
                    path.write_text(json.dumps(dict(card(),as_of=now[0].replace(second=0).isoformat(),
                        valid_until=now[0].replace(minute=47,second=0).isoformat())))
                else:now[0]=NOW.replace(minute=48,second=0)
            with patch('studies.us_0dte_picks.auto_watch.RUNTIME',runtime), \
                 patch('studies.us_0dte_picks.auto_watch.datetime') as clock, \
                 patch('studies.us_0dte_picks.auto_watch.accept',side_effect=accept), \
                 patch('studies.us_0dte_picks.auto_watch.time.sleep',side_effect=sleep), \
                 patch('studies.us_0dte_picks.session.subprocess.run') as process:
                clock.now.side_effect=lambda *args:now[0]
                self.assertEqual(main(['--session',str(root)]),0);process.assert_not_called()
            final=json.loads((root/'auto/final.json').read_text())
            self.assertEqual(final['status'],'ENTRY_AUTHORIZATION_EXPIRED')
            self.assertEqual([result['job_id'] for result in final['handoffs']],
                             ['US.AAA260930C100000','US.BBB260930C100000'])
            self.assertEqual(calls,['US.AAA260930C100000','US.BBB260930C100000','US.BBB260930C100000'])
            ledger=json.loads(ledger_path.read_text())
            self.assertEqual(len(ledger['accepted']),2)
            self.assertEqual(sum(row['cap'] for row in ledger['accepted']),280)
            self.assertEqual(json.loads((root/'authorization.json').read_text()),permission)

    def test_authorization_expiring_during_stale_preflight_ends_without_retry_or_new_permission(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);prepared(root)
            authorize(root,'AAA','dryrun',None,'FUTUSECURITIES',True,until='09:46',now=NOW)
            (root/'monitor/review_card.json').write_text(json.dumps(card()));now=[NOW]
            def stale(*args,**kwargs):
                now[0]=NOW.replace(minute=46,second=0)
                raise StaleReviewCard('review card expired or invalid')
            with patch('studies.us_0dte_picks.auto_watch.RUNTIME',root/'runtime'), \
                 patch('studies.us_0dte_picks.auto_watch.datetime') as clock, \
                 patch('studies.us_0dte_picks.auto_watch.accept',side_effect=stale) as accept, \
                 patch('studies.us_0dte_picks.auto_watch.time.sleep') as sleep, \
                 patch('studies.us_0dte_picks.session.subprocess.run') as process:
                clock.now.side_effect=lambda *args:now[0]
                self.assertEqual(main(['--session',str(root)]),0)
                self.assertEqual(accept.call_count,1);sleep.assert_not_called();process.assert_not_called()
            final=json.loads((root/'auto/final.json').read_text())
            self.assertEqual(final['status'],'ENTRY_AUTHORIZATION_EXPIRED')
            self.assertEqual(final['handoffs'],[])

    def test_invalid_future_wrong_day_or_long_lived_card_is_not_a_recoverable_expiry(self):
        original=card();contract=original['actions'][0]['contract']
        expired=deepcopy(original);expired['valid_until']=NOW.isoformat()
        with self.assertRaises(StaleReviewCard):selected_action(expired,contract,NOW)
        for changes in ({'as_of':(NOW+timedelta(seconds=5)).isoformat()},
                        {'trade_date':'2026-09-29'},
                        {'valid_until':(NOW+timedelta(minutes=2)).isoformat()},
                        {'valid_until':original['as_of']}):
            with self.subTest(changes=changes):
                try:selected_action(dict(original,**changes),contract,NOW)
                except StaleReviewCard:self.fail('invalid metadata classified as a recoverable stale card')
                except ValueError:pass
                else:self.fail('invalid review accepted')

    def test_separate_fresh_cards_share_budget_through_actual_handoff_preflight_and_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            permission=authorize(root,'AAA,BBB','dryrun',None,'FUTUSECURITIES',True,now=NOW)['authorization']
            commands=[]
            def run(command, **kwargs):
                commands.append(command)
                self.assertEqual(command[command.index('--max-entry-premium')+1],'140.0')
                db=Path(command[command.index('--db')+1])
                contract=command[command.index('--contract')+1]
                with sqlite3.connect(db) as conn:
                    conn.execute('CREATE TABLE IF NOT EXISTS jobs (body TEXT)')
                    conn.execute('INSERT INTO jobs VALUES (?)',(json.dumps(
                        {'id':contract,'position_qty':1,'request':{'contract':contract}}),))
                return SimpleNamespace(returncode=0,stdout='',stderr='')
            with patch('studies.us_0dte_picks.session.RUNTIME',self.runtime), \
                 patch('studies.us_0dte_picks.auto_watch.accept',side_effect=real_accept), \
                 patch('studies.us_0dte_picks.session.datetime') as clock, \
                 patch('studies.us_0dte_picks.session.subprocess.run',side_effect=run), \
                 patch('custody.opend.OpenDMarket') as market, \
                 patch('custody.opend.OpenDContractResolver') as resolver:
                resolver.return_value.nearest_expiry.return_value='2026-09-30'
                attempted=set()
                for i,action in enumerate(card()['actions']):
                    now=NOW+timedelta(minutes=i)
                    clock.now.return_value=now
                    action['expiry']='2026-09-30'
                    action['custody_request']['max_entry_premium']=280
                    contract=action['contract']
                    market.return_value.__enter__.return_value.snapshot.return_value={contract:{
                        'code':contract,'option_type':'CALL','strike_time':'2026-09-30','option_valid':True,
                        'sec_status':'NORMAL','option_contract_multiplier':100,'option_delta':.5,
                        'bid_price':1.1,'ask_price':1.2,'update_time':now.isoformat(),
                        'volume':500,'option_strike_price':100}}
                    current={**card(),'as_of':now.replace(second=0).isoformat(),
                             'valid_until':(now.replace(second=0)+timedelta(minutes=1)).isoformat(),
                             'actions':[action]}
                    raw=json.dumps(current).encode()
                    (root/'monitor/review_card.json').write_bytes(raw)
                    result=list(handoff_card(root,permission,raw,attempted,now))
                    self.assertEqual(result[0]['state'],'JOB_CREATED')
                    self.assertEqual((root/'monitor/review_card.json').read_bytes(),raw)
            rows=json.loads((self.runtime/'2026-09-30/dryrun/ledger.json').read_text())['accepted']
            self.assertEqual([r['cap'] for r in rows],[140,140])
            self.assertEqual(len(commands),4)
            self.assertTrue(all(r['state']=='JOB_CREATED' for r in rows))

    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.runtime=Path(directory.name)/'runtime'
        override=patch('studies.us_0dte_picks.auto_watch.RUNTIME', self.runtime)
        override.start()
        self.addCleanup(override.stop)

    def test_confirmed_duplicates_are_skipped_but_uncertain_reservations_stop_new_handoffs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            permission=authorize(root, 'AAA,BBB', 'paper', 123, 'FUTUINC', False, now=NOW)['authorization']
            ledger=self.runtime/'2026-09-30/paper/ledger.json'
            ledger.parent.mkdir(parents=True)
            row={'symbol':'US.AAA', 'cap':140, 'state':'JOB_CREATED'}
            ledger.write_text(json.dumps({'accepted':[row]}))
            with patch('studies.us_0dte_picks.auto_watch.accept', return_value={'job_id':'second'}) as accept:
                self.assertEqual(list(handoff_card(root, permission, json.dumps(card()).encode(), set(), NOW)), [{'job_id':'second'}])
                self.assertEqual(accept.call_args.args[1], 'US.BBB260930C100000')
                row['state']='RESERVED'
                ledger.write_text(json.dumps({'accepted':[row]}))
                with self.assertRaisesRegex(ValueError, 'unconfirmed existing reservation'):
                    list(handoff_card(root, permission, json.dumps(card()).encode(), set(), NOW))
                self.assertEqual(accept.call_count, 1)

    def test_partial_handoff_is_retained_when_next_action_is_uncertain_and_workers_are_not_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            (root/'monitor/ready.json').write_text(json.dumps({'trade_date':'2026-09-30', 'candidates':['US.AAA','US.BBB']}))
            authorize(root, 'AAA,BBB', 'paper', 123, 'FUTUINC', True, now=NOW)
            (root/'monitor/review_card.json').write_text(json.dumps(card()))
            success={'state':'JOB_CREATED', 'job_id':'first'}
            with patch('studies.us_0dte_picks.auto_watch.datetime') as clock, \
                 patch('studies.us_0dte_picks.auto_watch.accept', side_effect=[success, RuntimeError('uncertain launch')]), \
                 patch('studies.us_0dte_picks.session.subprocess.run') as systemctl:
                clock.now.return_value=NOW
                self.assertEqual(main(['--session',str(root)]), 1)
                systemctl.assert_not_called()
            final=json.loads((root/'auto/final.json').read_text())
            self.assertEqual(final['status'], 'STOPPED_REQUIRES_REVIEW')
            self.assertEqual(final['handoffs'], [success])
            self.assertEqual(final['error'], 'uncertain launch')
            self.assertEqual(len(final['attempted_card_contracts']), 2)
            events=(root/'auto/events.jsonl').read_text().splitlines()
            self.assertEqual(json.loads(events[0])['handoff'], success)

    def test_one_explicit_decision_is_previewed_then_persisted_without_orders(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            preview=authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', False, now=NOW)
            self.assertFalse(preview['orders_submitted'])
            self.assertFalse((root/'authorization.json').exists())
            result=authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', True, now=NOW)
            self.assertEqual(load_authorization(root, NOW), result['authorization'])
            with self.assertRaises(FileExistsError):
                authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', True, now=NOW)
            with self.assertRaisesRegex(ValueError, 'outside the frozen pool'):
                authorize(root, 'ZZZ', 'dryrun', None, 'FUTUSECURITIES', False, now=NOW)

    def test_mode_account_and_buy_only_permission_are_carried_to_one_selected_action(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            permission=authorize(root, 'AAA', 'paper', 123, 'FUTUINC', False,
                                 trade_action='buy_only', now=NOW)['authorization']
            attempted=set()
            with patch('studies.us_0dte_picks.auto_watch.accept', return_value={'state':'JOB_CREATED'}) as accept:
                raw=json.dumps(card()).encode()
                self.assertEqual(list(handoff_card(root, permission, raw, attempted, NOW)), [{'state':'JOB_CREATED'}])
                accept.assert_called_once_with(root, 'US.AAA260930C100000', 'paper', 123, 'FUTUINC', True,
                                               'buy_only', authorization=permission)
                self.assertEqual(list(handoff_card(root, permission, raw, attempted, NOW)), [])
                self.assertEqual(len(attempted), 1)
                expired=card()
                expired['valid_until']=NOW.isoformat()
                self.assertEqual(list(handoff_card(root, permission, json.dumps(expired).encode(), attempted, NOW)), [])
                self.assertEqual(accept.call_count, 1)

    def test_expiry_revocation_strategy_change_budget_and_live_candidate_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            base=authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', False, now=NOW)['authorization']
            for changes in ({'revoked_at':NOW.isoformat()}, {'strategy_sha256':'bad'},
                            {'premium_budget_usd':300}, {'max_qty':True}, {'symbols':[{}]},
                            {'mode':'live', 'acc_id':123}, {'mode':'paper', 'acc_id':None}):
                permission=dict(base, **changes)
                with self.subTest(changes=changes), patch('studies.us_0dte_picks.auto_watch.accept') as accept:
                    with self.assertRaises(ValueError):
                        list(handoff_card(root, permission, json.dumps(card()).encode(), set(), NOW))
                    accept.assert_not_called()
            with self.assertRaises(ValueError):
                validate_authorization(base, NOW.replace(hour=15, minute=45))

    def test_bound_frozen_input_and_monitor_scope_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', True, now=NOW)
            (root/'monitor/ready.json').write_text(json.dumps({'trade_date':'2026-09-30', 'candidates':['US.AAA','US.BBB']}))
            with self.assertRaisesRegex(ValueError, 'exactly the authorized'):
                load_authorization(root, NOW)
            (root/'ranking.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'different session or frozen'):
                load_authorization(root, NOW)

    def test_shared_handoff_clamps_entry_deadline_and_rechecks_revocation_after_wait(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            permission=authorize(root, 'AAA', 'paper', 123, 'FUTUINC', True, until='09:46', now=NOW)['authorization']
            current=card()
            current.update(as_of=NOW.isoformat(), valid_until=(NOW+timedelta(minutes=1)).isoformat())
            (root/'monitor/review_card.json').write_text(json.dumps(current))
            with patch('studies.us_0dte_picks.session.datetime') as clock, \
                 patch('studies.us_0dte_picks.session.custody_command', return_value=[]) as command:
                clock.now.return_value=NOW
                real_accept(root, current['actions'][0]['contract'], 'paper', 123, 'FUTUINC', False,
                            authorization=permission)
                self.assertEqual(command.call_args.args[1], permission['valid_until'])
            check_handoff_authorization(root, permission, current['actions'][0], 'paper', 123, 'FUTUINC', 'round_trip', NOW)
            with self.assertRaises(ValueError):
                check_handoff_authorization(root, permission, current['actions'][0], 'paper', 123, 'FUTUINC',
                                             'round_trip', NOW.replace(minute=46))
            (root/'authorization.json').write_text(json.dumps(dict(permission, revoked_at=NOW.isoformat())))
            with self.assertRaises(ValueError):
                check_handoff_authorization(root, permission, current['actions'][0], 'paper', 123, 'FUTUINC', 'round_trip', NOW)

    def test_revocation_during_real_shared_preflight_prevents_service_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            permission=authorize(root, 'AAA', 'paper', 123, 'FUTUINC', True, now=NOW)['authorization']
            (root/'monitor/review_card.json').write_text(json.dumps(card()))
            def revoke_during_preflight(*args, **kwargs):
                (root/'authorization.json').write_text(json.dumps(dict(permission, revoked_at=NOW.isoformat())))
                return SimpleNamespace(returncode=0, stdout='', stderr='')
            with patch('studies.us_0dte_picks.session.RUNTIME', self.runtime), \
                 patch('studies.us_0dte_picks.session.datetime') as clock, \
                 patch('studies.us_0dte_picks.session.jobs_in', return_value=[{'position_qty':1}]), \
                 patch('studies.us_0dte_picks.session.subprocess.run', side_effect=revoke_during_preflight) as process:
                clock.now.return_value=NOW
                with self.assertRaises(ValueError):
                    real_accept(root, card()['actions'][0]['contract'], 'paper', 123, 'FUTUINC', True,
                                authorization=permission)
                self.assertEqual(process.call_count, 1)  # only quote-only dryrun, no service/order task

    def test_status_prefers_terminal_auto_error_over_older_running_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'auto').mkdir()
            (root/'auto/latest.json').write_text(json.dumps({'as_of':datetime.now(ET).isoformat(), 'status':'WAITING'}))
            (root/'auto/final.json').write_text(json.dumps({'as_of':datetime.now(ET).isoformat(),
                'status':'STOPPED_REQUIRES_REVIEW', 'error':'authorization revoked'}))
            with patch('studies.us_0dte_picks.session.RUNTIME', root/'runtime'):
                result=status(root)
            self.assertTrue(result['auto']['finished'])
            self.assertEqual(result['auto']['status'], 'STOPPED_REQUIRES_REVIEW')
            self.assertEqual(result['auto']['error'], 'authorization revoked')

    def test_malformed_card_is_reported_as_terminal_failure_without_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            prepared(root)
            authorize(root, 'AAA', 'dryrun', None, 'FUTUSECURITIES', True, now=NOW)
            (root/'monitor/review_card.json').write_text('[]')
            with patch('studies.us_0dte_picks.auto_watch.datetime') as clock, \
                 patch('studies.us_0dte_picks.auto_watch.accept') as accept:
                clock.now.return_value=NOW
                self.assertEqual(main(['--session',str(root)]), 1)
                accept.assert_not_called()
            final=json.loads((root/'auto/final.json').read_text())
            self.assertEqual(final['status'], 'STOPPED_REQUIRES_REVIEW')
            self.assertEqual(final['handoffs'], [])


if __name__=='__main__':
    unittest.main()
