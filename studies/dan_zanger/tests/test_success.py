"""The success card and the facts the `success` command hands to success.judge."""
import unittest

from studies.dan_zanger import replicate as R
from studies.trader_replication import success as SU

GATE = dict(data=True, lookahead=True, fills=True)


def trade(ret, days, why='trail'):
    return dict(ret=ret, days=days, why=why, entry='2024-01-02')


def facts(trades, per_year=110.0, open_mean=3.0, median_days_win=20.0, total=.5, drop2=.2):
    st = dict(total=total, by_year={'2024': total}, placebo=dict(median=.1),
              behaviour=dict(per_year=per_year, open_mean=open_mean, median_days_win=median_days_win))
    return R.facts(st, trades, dict(total=-.1, placebo=dict(median=-.05)), dict(total=drop2), GATE)


def verdict(**kw):
    trades = kw.pop('trades', [trade(.5, 30)] + [trade(-.02, 6)] * 3)
    n = int(kw.get('per_year', 110))
    trades = [trades[i % len(trades)] for i in range(n)]
    return {r: ok for r, ok, _ in SU.judge(R.CARD, facts(trades, **kw))}


class CardTests(unittest.TestCase):
    def test_count_is_his_sourced_floor(self):
        self.assertTrue(R.CARD['source'])
        self.assertTrue(verdict(per_year=104)['count'])
        self.assertTrue(verdict(per_year=84)['count'])          # within 20% under 104
        self.assertFalse(verdict(per_year=83)['count'])
        self.assertTrue(verdict(per_year=400)['count'])         # "at least": no ceiling

    def test_hold_measures_come_from_closed_trades(self):
        f = facts([trade(.5, 30), trade(-.02, 6), trade(.1, 300, why='end')])
        self.assertEqual(f['behaviour']['max_days'], 30)        # the open 'end' row is not a trade he closed
        self.assertEqual(f['behaviour']['days_mean'], 18)
        self.assertEqual(f['closed'], 2)
        self.assertEqual(f['win'], .5)

    def test_his_holding_words(self):
        self.assertTrue(verdict()['behaviour'])                  # mean 10.5, longest 30, winners 20, 3 open
        self.assertFalse(verdict(trades=[trade(.5, 80)] + [trade(-.02, 6)] * 3)['behaviour'])   # over 10 weeks
        self.assertFalse(verdict(median_days_win=60)['behaviour'])
        self.assertTrue(verdict(open_mean=1.2)['behaviour'])       # position count is diagnostic in P1

    def test_win_rate_and_best_two(self):
        self.assertFalse(verdict(trades=[trade(.5, 10)] * 2 + [trade(-.02, 6)] * 2)['gate'])   # win rate exceeds 35%
        self.assertNotIn('not two', verdict(drop2=.05))         # random comparison is diagnostic in P1


if __name__ == '__main__':
    unittest.main()
