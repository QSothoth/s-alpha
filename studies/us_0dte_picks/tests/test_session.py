"""Synthetic checks for frozen denominators and the manual execution boundary."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import json
import os
import pwd
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from custody.models import ET
from studies.us_0dte_picks.prepare_watch import nearest_expiry, opening_baseline
from studies.us_0dte_picks.session import selected_action, reserve, custody_command, accept, status
from studies.us_0dte_picks.tests.test_daily_list import daily_rows, weekdays, T, T1


class SessionTests(unittest.TestCase):
    def test_review_handoff_propagates_buy_only_but_rejects_sell_only(self):
        action = {'custody_request': {'strategy': 'open_hold_v3', 'symbol': 'US.AAA', 'direction': 'LONG',
                                     'contract': 'US.AAA260930C100000', 'max_qty': 1,
                                     'max_entry_premium': 280, 'expiry_policy': 'nearest'}}
        command = custody_command(action, '2026-09-30T10:00:00-04:00', Path('/tmp/test.sqlite'),
                                  trade_action='buy_only')
        self.assertEqual(command[command.index('--trade-action')+1], 'buy_only')
        self.assertIn('dryrun', command)
        with self.assertRaisesRegex(ValueError, 'existing holdings'):
            custody_command(action, '', Path('/tmp/test.sqlite'), trade_action='sell_only')

    def test_status_preserves_failed_handoff_without_claiming_a_fill(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'mock').mkdir()
            (root/'mock/latest.json').write_text(json.dumps({
                'as_of': (datetime.now(ET)-timedelta(days=1)).isoformat(),
                'status': 'HANDOFF_FAILED', 'positions': [], 'orders_submitted': False,
                'handoff_errors': [{'error': 'preflight failed'}]}))
            (root/'mock/final.json').write_text('{}')
            with patch('studies.us_0dte_picks.session.RUNTIME', root/'runtime'):
                result = status(root)
            self.assertEqual(result['mock']['status'], 'HANDOFF_FAILED')
            self.assertFalse(result['mock']['fresh'])
            self.assertTrue(result['mock']['finished'])
            self.assertEqual(result['mock']['handoff_errors'][0]['error'], 'preflight failed')
            self.assertEqual(result['jobs'], [])
            self.assertFalse(result['mock']['orders_submitted'])
            with self.assertRaisesRegex(ValueError, 'does not exist'):
                status(root/'missing')

    def test_status_does_not_present_future_card_as_current(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'monitor').mkdir()
            now = datetime.now(ET)
            (root/'monitor/review_card.json').write_text(json.dumps({
                'as_of': (now+timedelta(minutes=1)).isoformat(),
                'valid_until': (now+timedelta(minutes=2)).isoformat(),
                'trade_date': now.date().isoformat(), 'status': 'ENTER_REVIEW'}))
            with patch('studies.us_0dte_picks.session.RUNTIME', root/'runtime'):
                self.assertEqual(status(root)['status'], 'STALE_OR_STOPPED')

    def test_accept_runs_preflight_before_reserving_and_launching_once(self):
        now = datetime.now(ET)
        day = now.date().isoformat()
        expiry = (now+timedelta(days=1)).date().isoformat()
        contract = 'US.AAA' + (now+timedelta(days=1)).strftime('%y%m%d') + 'C100000'
        request = {'strategy': 'open_hold_v3', 'symbol': 'US.AAA', 'direction': 'LONG',
                   'contract': contract, 'expiry_policy': 'nearest', 'max_qty': 1, 'max_entry_premium': 280}
        action = {'symbol': 'US.AAA', 'direction': 'LONG', 'contract': contract,
                  'expiry': expiry, 'custody_request': request}
        card = {'status': 'ENTER_REVIEW', 'trade_date': day, 'as_of': now.isoformat(),
                'valid_until': (now+timedelta(minutes=1)).isoformat(), 'actions': [action]}
        quote = {'code': contract, 'option_type': 'CALL', 'strike_time': expiry, 'option_valid': True,
                 'sec_status': 'NORMAL', 'option_contract_multiplier': 100, 'option_delta': .5,
                 'bid_price': 1.1, 'ask_price': 1.2, 'update_time': now.strftime('%Y-%m-%d %H:%M:%S'),
                 'volume': 500, 'option_strike_price': 100}
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[0] != 'systemd-run':
                self.assertEqual(kwargs['env']['HOME'],pwd.getpwuid(os.getuid()).pw_dir)
            else:
                self.assertIn('--property=User='+pwd.getpwuid(os.getuid()).pw_name,command)
            db = Path(command[command.index('--db')+1])
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE jobs (body TEXT)')
                conn.execute('INSERT INTO jobs VALUES (?)', (json.dumps(
                    {'id': 'synthetic', 'position_qty': 1, 'request': {'contract': contract}}),))
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'monitor').mkdir()
            (root/'monitor/review_card.json').write_text(json.dumps(card))
            with patch('studies.us_0dte_picks.session.RUNTIME', root/'runtime'), \
                 patch.dict(os.environ, {'PATH':os.environ.get('PATH','')}, clear=True), \
                 patch('studies.us_0dte_picks.session.subprocess.run', side_effect=run), \
                 patch('custody.opend.OpenDMarket') as market, \
                 patch('custody.opend.OpenDContractResolver') as resolver:
                market.return_value.__enter__.return_value.snapshot.return_value = {contract: quote}
                resolver.return_value.nearest_expiry.return_value = expiry
                preview = accept(root, contract, 'dryrun', None, 'FUTUSECURITIES', False)
                self.assertFalse(preview['executed'])
                self.assertEqual(calls, [])
                result = accept(root, contract, 'dryrun', None, 'FUTUSECURITIES', True)
                self.assertEqual(result['state'], 'JOB_CREATED')
                self.assertIn('--once', calls[0])
                self.assertEqual(calls[1][0], 'systemd-run')
                self.assertNotIn('--once', calls[1])
                with self.assertRaisesRegex(ValueError, 'already accepted'):
                    accept(root, contract, 'dryrun', None, 'FUTUSECURITIES', True)
                self.assertEqual(len(calls), 2)

    def test_real_expiry_selection_and_matching_baselines(self):
        rows = [{'strike_time': d} for d in ['2026-10-02', '2026-09-25', '2026-09-30']]
        self.assertEqual(nearest_expiry(rows, '2026-09-29'), '2026-09-30')
        self.assertEqual(nearest_expiry(rows, '2026-09-30'), '2026-09-30')
        self.assertIsNone(nearest_expiry(rows, '2026-10-03'))
        raw30, raw15 = daily_rows(False), []
        for row in raw30:
            stamp = datetime.fromisoformat(row['time_key'])
            for delta in (-15, 0):
                raw15.append({**row, 'time_key': (stamp+timedelta(minutes=delta)).isoformat(sep=' '),
                              'volume': row['volume']/2})
        base = opening_baseline(raw15, raw30, T, weekdays(T, 60))
        self.assertEqual(base['rvol15_days'], weekdays(T1, 14))
        self.assertAlmostEqual(base['rvol15_base']*2, base['rvol30_base'])
        with self.assertRaisesRegex(ValueError, 'matching complete'):
            opening_baseline(raw15[:-1], raw30, T, weekdays(T, 60))

    def test_fresh_card_exact_contract_budget_and_explicit_execution_mode(self):
        now = datetime(2026, 9, 29, 9, 51, 10, tzinfo=ET)
        action = {'symbol': 'US.AAA', 'direction': 'LONG', 'contract': 'US.AAA260930C100000',
                  'custody_request': {'strategy': 'open_hold_v3', 'symbol': 'US.AAA', 'direction': 'LONG',
                                      'contract': 'US.AAA260930C100000', 'expiry_policy': 'nearest',
                                      'max_qty': 1, 'max_entry_premium': 140}}
        card = {'status': 'ENTER_REVIEW', 'trade_date': '2026-09-29', 'as_of': now.replace(second=0).isoformat(),
                'valid_until': now.replace(minute=52, second=0).isoformat(), 'actions': [action]}
        self.assertEqual(selected_action(card, action['contract'], now), action)
        for stamp in (now-timedelta(minutes=1), now+timedelta(minutes=1)):
            with self.assertRaisesRegex(ValueError, 'expired or invalid'):
                selected_action(card, action['contract'], stamp)
        with self.assertRaisesRegex(ValueError, 'not uniquely'):
            selected_action(card, 'US.BBB260930C100000', now)
        ledger = {}
        reserve(ledger, action)
        with self.assertRaisesRegex(ValueError, 'already accepted'):
            reserve(ledger, action)
        second = deepcopy(action)
        second.update(symbol='US.BBB', contract='US.BBB260930C100000')
        second['custody_request'].update(symbol=second['symbol'], contract=second['contract'])
        second['custody_request']['max_entry_premium'] = 141
        with self.assertRaisesRegex(ValueError, 'daily limit'):
            reserve(ledger, second)
        second['custody_request']['max_entry_premium'] = 140
        reserve(ledger, second)
        self.assertEqual(len(ledger['accepted']), 2)
        command = custody_command(action, card['valid_until'], Path('/tmp/test.sqlite'))
        self.assertIn('dryrun', command)
        self.assertIn('--stream-only', command)
        self.assertIn('--entry-valid-until', command)
        with self.assertRaisesRegex(ValueError, 'explicit account'):
            custody_command(action, card['valid_until'], Path('/tmp/test.sqlite'), mode='live')


if __name__ == '__main__':
    unittest.main()
