import unittest

from studies.trader_replication.martin_continue_ck import availability


class PublicationAvailabilityTests(unittest.TestCase):
    def test_month_precision_is_not_treated_as_early_knowledge(self):
        source = 'lS9zbnLi1Gg@00:47:31'
        self.assertEqual(availability(source, '2025-04-30')['status'], 'known_sources_not_yet_available')
        self.assertEqual(availability(source, '2025-05-01')['status'], 'confirmed_available')

    def test_unknown_alternate_source_is_not_called_unpublished(self):
        source = 'VKNEJA5r8zw@00:01:00 unknown1234@00:04:00'
        self.assertEqual(availability(source, '2025-01-01')['status'], 'unknown_publication')
        self.assertEqual(availability(source, '2026-02-01')['status'], 'confirmed_available')
        self.assertEqual(availability('', '2026-02-01')['status'], 'unknown_publication')


if __name__ == '__main__':
    unittest.main()
