import unittest

from studies.trader_replication.martin_continue_ay import cap_thirty
from studies.trader_replication.system import Rules


class CapThirty(unittest.TestCase):
    def test_tightens_every_kind_without_loosening_existing_cap(self):
        original = Rules(max_position=.35, management_by_kind={
            'list': {'add_levels': (1, 3)}, 'short': {'max_position': .20}})
        result = cap_thirty(original)
        self.assertEqual(result.max_position, .30)
        self.assertEqual(result.management_by_kind['list'], {'add_levels': (1, 3), 'max_position': .30})
        self.assertEqual(result.management_by_kind['short']['max_position'], .20)
        self.assertEqual(original.max_position, .35)
        self.assertNotIn('max_position', original.management_by_kind['list'])
