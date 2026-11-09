import unittest

from studies.trader_replication.martin_continue_cd import added


class AddedTradeTests(unittest.TestCase):
    def test_only_actual_add_executions_count(self):
        attempted = {'add_tries': 2, 'executions': [{'action': 'entry'}, {'action': 'stop'}]}
        executed = {'add_tries': 1, 'executions': [{'action': 'entry'}, {'action': 'add'}, {'action': 'stop'}]}
        self.assertFalse(added(attempted))
        self.assertTrue(added(executed))


if __name__ == '__main__':
    unittest.main()
