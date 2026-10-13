import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime

from custody.models import ET
from studies.us_0dte_picks.session_risk import check_risk_budget, validate_risk_budget


NOW = datetime(2026, 10, 13, 10, tzinfo=ET)


class RiskBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.permission = {
            'mode': 'dryrun', 'acc_id': None, 'security_firm': 'FUTUSECURITIES',
            'risk_budget': {'start_date': '2026-10-10', 'loss_limit_usd': '100',
                            'estimated_round_trip_fee_per_contract_usd': '2'}}

    def check(self, premium='0'):
        return check_risk_budget(self.root, self.permission, premium, NOW)

    def handoff(self, day, *, buy=None, sell=None, state='DONE', mode='dryrun',
                account=None, fee_scope='FUTUSECURITIES', close_day=None):
        folder = self.root / day / mode
        folder.mkdir(parents=True)
        entry = {'contract': 'US.TEST261016C100000', 'cap': '40',
                 'account': account, 'security_firm': fee_scope}
        if buy is not None:
            entry['job_id'] = day
            job = {'id': day, 'mode': mode, 'request': {'contract': entry['contract'], 'trade_date': day},
                   'state': state, 'position_qty': 0 if sell is not None else 1,
                   'attention': None, 'contract': {'multiplier': 100}}
            with sqlite3.connect(folder / 'custody.sqlite') as db:
                db.execute('CREATE TABLE jobs (id TEXT, account TEXT, contract TEXT, day TEXT, body TEXT)')
                db.execute('CREATE TABLE orders (job_id TEXT, body TEXT)')
                db.execute('INSERT INTO jobs VALUES (?, ?, ?, ?, ?)',
                           (day, 'opend-dryrun' if mode == 'dryrun' else str(account),
                            entry['contract'], day, json.dumps(job)))
                for side, price in (('BUY_OPEN', buy), ('SELL_CLOSE', sell)):
                    if price is None:
                        continue
                    order = {'side': side, 'kind': 'LIMIT', 'status': 'FILLED',
                             'cumulative_qty': 1, 'average_option_price': price,
                             'last_update': json.dumps({'as_of': (close_day or day) + 'T15:30:00-04:00'})}
                    db.execute('INSERT INTO orders VALUES (?, ?)', (day, json.dumps(order)))
        (folder / 'ledger.json').write_text(json.dumps({'accepted': [entry]}))
        return folder

    def test_explicit_config_and_legacy_opt_out(self):
        self.assertIsNone(check_risk_budget(self.root, {}, now=NOW))
        for change in ({'start_date': '2026-10-14'}, {'loss_limit_usd': 'NaN'},
                       {'estimated_round_trip_fee_per_contract_usd': -1}, {'loss_limit_usd': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_risk_budget({**self.permission['risk_budget'], **change}, NOW)
        report = self.check('98')
        self.assertEqual(report['proposed_exposure_usd'], '100')
        self.assertEqual(self.check()['proposed_exposure_usd'], '0')
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            self.check('99')

    def test_real_fills_net_estimate_accumulates_across_days(self):
        self.handoff('2026-10-10', buy='.40', sell='.10')  # -32 including fees.
        self.handoff('2026-10-11', buy='.20', sell='.30')  # +8 including fees.
        report = self.check('74')
        self.assertEqual(report['estimated_realized_net_pnl_usd'], '-24.00')
        self.assertEqual(report['remaining_budget_usd'], '76.00')
        self.assertEqual(report['fees'], 'USER_ESTIMATE')
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            self.check('75')

    def test_old_unresolved_reservations_and_open_positions_consume_cap(self):
        self.handoff('2026-10-08')
        self.handoff('2026-10-09', buy='.20', state='HELD')
        self.assertEqual(self.check()['reserved_exposure_usd'], '84')
        self.check('14')
        with self.assertRaisesRegex(ValueError, 'exhausted'):
            self.check('15')

    def test_closed_before_start_excluded_but_later_close_included(self):
        self.handoff('2026-10-08', buy='.40', sell='.10')
        self.handoff('2026-10-09', buy='.40', sell='.20', close_day='2026-10-10')
        self.assertEqual(self.check()['realized_loss_usd'], '22.00')

    def test_scopes_are_separate_and_unknown_scope_blocks(self):
        self.handoff('2026-10-10', buy='.40', sell='.01', mode='paper', account=5)
        self.assertEqual(self.check()['realized_loss_usd'], '0')
        self.permission.update(mode='paper', acc_id=6)
        self.assertEqual(self.check()['realized_loss_usd'], '0')
        self.permission['acc_id'] = 5
        self.assertEqual(self.check()['realized_loss_usd'], '41.00')
        path = self.root / '2026-10-10/paper/ledger.json'
        payload = json.loads(path.read_text())
        del payload['accepted'][0]['account']
        path.write_text(json.dumps(payload))
        self.permission['acc_id'] = 6
        with self.assertRaisesRegex(ValueError, 'scope is missing'):
            self.check()

    def test_missing_job_and_transferred_holdings_fail_closed(self):
        folder = self.handoff('2026-10-10', buy='.40', state='TRANSFERRED')
        with self.assertRaisesRegex(ValueError, 'transferred'):
            self.check()
        (folder / 'custody.sqlite').unlink()
        with self.assertRaisesRegex(ValueError, 'database is missing'):
            self.check()

    def test_unbalanced_done_fills_fail_closed(self):
        folder = self.handoff('2026-10-10', buy='.40', sell='.20')
        with sqlite3.connect(folder / 'custody.sqlite') as db:
            db.execute('DELETE FROM orders WHERE rowid = 2')
        with self.assertRaisesRegex(ValueError, 'does not reconcile'):
            self.check()

    def test_uncertain_order_never_releases_reservation(self):
        folder = self.handoff('2026-10-10', buy='.40', sell='.20')
        with sqlite3.connect(folder / 'custody.sqlite') as db:
            row = json.loads(db.execute('SELECT body FROM orders LIMIT 1').fetchone()[0])
            row['status'] = 'UNKNOWN'
            db.execute('UPDATE orders SET body=? WHERE rowid=1', (json.dumps(row),))
        self.assertEqual(self.check()['reserved_exposure_usd'], '42')

    def test_cancel_ack_does_not_hide_completed_loss(self):
        folder = self.handoff('2026-10-10', buy='.40', sell='.20')
        with sqlite3.connect(folder / 'custody.sqlite') as db:
            db.execute('INSERT INTO orders VALUES (?, ?)', ('2026-10-10', json.dumps(
                {'kind': 'CANCEL', 'status': 'ACKED'})))
        report = self.check()
        self.assertEqual(report['realized_loss_usd'], '22.00')
        self.assertEqual(report['reserved_exposure_usd'], '0')
        # A cancel acknowledgment does not make the original order terminal.
        with sqlite3.connect(folder / 'custody.sqlite') as db:
            order = json.loads(db.execute('SELECT body FROM orders WHERE rowid=2').fetchone()[0])
            order['status'] = 'UNKNOWN'
            db.execute('UPDATE orders SET body=? WHERE rowid=2', (json.dumps(order),))
        self.assertEqual(self.check()['reserved_exposure_usd'], '42')

    def test_missing_all_fills_cannot_erase_an_entered_trade(self):
        folder = self.handoff('2026-10-10', buy='.40', sell='.20')
        with sqlite3.connect(folder / 'custody.sqlite') as db:
            job = json.loads(db.execute('SELECT body FROM jobs').fetchone()[0])
            job['entry_at'] = '2026-10-10T10:00:00-04:00'
            db.execute('UPDATE jobs SET body=?', (json.dumps(job),))
            db.execute('DELETE FROM orders')
        with self.assertRaisesRegex(ValueError, 'does not reconcile'):
            self.check()

    def test_done_unfilled_attention_releases_only_reconciled_jobs(self):
        folder = self.handoff('2026-10-10', buy='.40', sell='.20')
        for attention in ('ENTRY_NOT_FILLED', 'NO_ENTRY_SIGNAL', 'ENTRY_REVIEW_EXPIRED', 'UNKNOWN'):
            with self.subTest(attention=attention):
                with sqlite3.connect(folder / 'custody.sqlite') as db:
                    job = json.loads(db.execute('SELECT body FROM jobs').fetchone()[0])
                    job['attention'] = attention
                    db.execute('UPDATE jobs SET body=?', (json.dumps(job),))
                    db.execute('DELETE FROM orders')
                expected = '42' if attention == 'UNKNOWN' else '0'
                self.assertEqual(self.check()['reserved_exposure_usd'], expected)

    def test_future_close_and_mismatched_job_body_fail_closed(self):
        folder = self.handoff('2026-10-10', buy='.40', sell='.20', close_day='2026-10-14')
        with self.assertRaisesRegex(ValueError, 'future close'):
            self.check()
        with sqlite3.connect(folder / 'custody.sqlite') as db:
            job = json.loads(db.execute('SELECT body FROM jobs').fetchone()[0])
            job['request']['trade_date'] = '2026-10-09'
            db.execute('UPDATE jobs SET body=?', (json.dumps(job),))
        with self.assertRaisesRegex(ValueError, 'scope mismatch'):
            self.check()


if __name__ == '__main__':
    unittest.main()
