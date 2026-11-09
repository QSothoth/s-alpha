import unittest

import numpy as np

from studies.trader_replication import system


class CloseAllocationTests(unittest.TestCase):
    def run_case(self, after, exit_first=False, include_entry=True, signal_add=False):
        dates = np.array(['2025-01-02', '2025-01-03', '2025-01-06'])
        close = np.array([[10., 10.], [12., 10.], [12., 10.]])
        px = {'dates': dates, 'codes': np.array(['US.A', 'US.B']), 'close': close,
              'open': np.array([[10., 10.], [11.5, 10.], [12., 10.]]),
              'high': np.array([[10., 10.], [12.5, 10.], [12., 10.]]),
              'low': np.array([[10., 10.], [11., 10.], [12., 10.]])}
        entries = [[(0, 0, 1, 10., 9., 'list')], [(0, 1, 1, 10., 9., 'list')], []]
        if not include_entry:
            entries[1] = []
        signal = np.zeros((3, 2), dtype=bool)
        signal[1, 0] = exit_first
        add_signal = np.zeros((3, 2), dtype=bool)
        add_signal[1, 0] = signal_add
        rules = system.Rules(risk=.05, max_position=.6, max_gross=.75, trail='', trims=(),
                             add_levels=() if signal_add else (1,), add_after_entries=after,
                             add_signal='add' if signal_add else '',
                             buy_cost=0, sell_cost=0, margin_rate=0,
                             exit_signal='exit' if exit_first else '')
        _, _, trades = system.simulate(px, {'exit': signal, 'add': add_signal}, rules, entries,
                                       dates[0], dates[-1], audit=True)
        return {t['code']: t for t in trades}

    def test_new_close_entry_gets_room_before_old_add_when_enabled(self):
        original = self.run_case(False)
        changed = self.run_case(True)
        self.assertGreater(changed['US.B']['executions'][0]['shares'],
                           original['US.B']['executions'][0]['shares'])
        self.assertEqual([e['action'] for e in original['US.A']['executions']], ['entry', 'add', 'end'])
        self.assertEqual([e['action'] for e in changed['US.A']['executions']], ['entry', 'end'])
        self.assertEqual(changed['US.B']['executions'][0]['time'], '2025-01-03')

    def test_signal_add_is_also_deferred(self):
        original = self.run_case(False, signal_add=True)
        changed = self.run_case(True, signal_add=True)
        self.assertGreater(changed['US.B']['executions'][0]['shares'],
                           original['US.B']['executions'][0]['shares'])
        self.assertEqual([e['action'] for e in changed['US.A']['executions']], ['entry', 'end'])

    def test_without_competing_entries_the_add_is_unchanged(self):
        original = self.run_case(False, include_entry=False)
        changed = self.run_case(True, include_entry=False)
        self.assertEqual(original['US.A']['executions'], changed['US.A']['executions'])

    def test_exit_position_cannot_receive_a_deferred_add(self):
        original = self.run_case(False, exit_first=True)
        changed = self.run_case(True, exit_first=True)
        self.assertEqual([e['action'] for e in original['US.A']['executions']], ['entry', 'add', 'signal'])
        self.assertEqual([e['action'] for e in changed['US.A']['executions']], ['entry', 'signal'])


if __name__ == '__main__':
    unittest.main()
