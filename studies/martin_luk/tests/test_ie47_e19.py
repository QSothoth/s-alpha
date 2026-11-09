"""E19 keeps the fixed gates, retry caps and entry-loop position accounting."""
import unittest

from studies.martin_luk import e19_research as E19, e16_research as E16, e15_research as E15


class E19Tests(unittest.TestCase):
    def test_candidates_keep_the_c062_layers_and_only_s1_s2_release_slots(self):
        with E19.runtime():
            for name in E19.SPECS:
                base = E16.arm_rules(E16.M.e8_rules('E8c'), name)
                rules = E15.candidate_rules(E15.P.B.X.rule_layers(base, ('AS', 'X1')), E15.SPECS['C062'])
                self.assertEqual(rules.max_open, 11)
                self.assertEqual(rules.max_new_long, 4)
                self.assertEqual(rules.max_open_by_kind[E19.RETRY], 1 if name == 'S5' else 2)
                self.assertEqual(bool(rules.make_room_kind), name in ('S1', 'S2'))
                self.assertEqual(rules.make_room_confirmed, name == 'S2')

    def test_selection_never_waives_the_midpoint_or_annual_floor(self):
        summary = {name+'_train': dict(by_year={'2024': .8, '2025': .8}, maxdd=.3, midpoint_his=11)
                   for name in ('BASE', *E19.SPECS)}
        self.assertEqual(E19.select(summary), ([], None))
        summary['S1_train'].update(midpoint_his=12)
        self.assertEqual(E19.select(summary), (['S1'], 'S1'))
        summary['S1_train']['by_year']['2025'] = .799999
        self.assertEqual(E19.select(summary), ([], None))

    def test_near_ties_use_midpoint_then_candidate_number(self):
        summary = {name+'_train': dict(by_year={'2024': .7, '2025': .7}, maxdd=.3, midpoint_his=12)
                   for name in ('BASE', *E19.SPECS)}
        summary['S1_train']['by_year']['2025'] = .69
        summary['S2_train'].update(midpoint_his=13)
        summary['S3_train'].update(midpoint_his=13)
        self.assertEqual(E19.select(summary)[1], 'S2')

    def test_make_room_is_held_before_the_entry_loop_but_not_at_close(self):
        trades = [dict(entry='2024-01-02', exit='2024-01-03', why='make_room', kind=E19.RETRY),
                  dict(entry='2024-01-02', exit='2024-01-03', why='stop', kind='base'),
                  dict(entry='2024-01-03', exit='2024-01-04', why='end', kind='base')]
        row = E19.daily_positions(trades, ['2024-01-03'])['2024-01-03']
        self.assertEqual((row['at_open'], row['before_entries'], row['at_close']), (2, 1, 1))
        self.assertEqual((row['retry_before_entries'], row['retry_at_close']), (1, 0))


if __name__ == '__main__':
    unittest.main()
