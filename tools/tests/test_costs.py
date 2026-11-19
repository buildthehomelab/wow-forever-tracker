"""ft.costs: the server's ItemExtendedCost rows keyed by what they ask, as app/wowheadpages.php keys Wowhead's costs."""
import unittest

from ft import costs


def row(id_, **values):
    base = {name: 0 for name in costs.PLAIN}
    for n in range(1, 6):
        base.update({f'ItemID{n}': 0, f'ItemCount{n}': 0, f'CurrencyID{n}': 0, f'CurrencyCount{n}': 0})
    base.update(values, ID=id_)
    return base


class CostsTest(unittest.TestCase):
    def test_key_is_sorted_like_the_website(self):
        # app/wowheadpages.php wowhead_pages_cost_key([0, [[1901, 30]], [[20558, 3], [17, 2]]]) gives the same
        self.assertEqual(costs.cost_key([(1901, 30)], [(20558, 3), (17, 2)]), 'c1901x30,i17x2,i20558x3')
        self.assertEqual(costs.cost_key([(0, 0)], [(5, 0)]), '')

    def test_plain_rows_only_lowest_id(self):
        rows = [row(9, ItemID1=21100, ItemCount1=50), row(3, ItemID1=21100, ItemCount1=50),
                row(4, ItemID1=21100, ItemCount1=50, RequiredAchievement=12),   # asks more than items
                row(5, Money=100, ItemID1=7, ItemCount1=1),                      # money of its own
                row(6, CurrencyID1=1901, CurrencyCount1=30, ItemID2=17, ItemCount2=2),
                row(7)]                                                          # asks nothing
        self.assertEqual(costs.by_key(rows), {'i21100x50': 3, 'c1901x30,i17x2': 6})


if __name__ == '__main__':
    unittest.main()
