"""The locator's candidates: a world object whose own spell makes an item nothing gives (the Wooden Figurine)."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ft import locator  # noqa: E402


class ItemCastingObjects(unittest.TestCase):
    def test_the_object_that_casts_the_items_spell(self):
        item_checks = json.dumps([{'code': 'source', 'ok': False}])

        def query(sql, database='world', account=None):
            if 'FROM ft_entities' in sql:
                return [{'type': 'item', 'id': '190309', 'name': 'Wooden Figurine', 'name_en': 'Wooden Figurine', 'checks': item_checks, 'data': '{}'}]
            if 'FROM gameobject_template gt WHERE gt.type = 10 AND gt.Data10 IN (367069)' in sql:
                return [{'entry': '375544', 'spell': '367069'}]
            if sql.startswith('SELECT entry, name FROM gameobject_template'):
                return [{'entry': '375544', 'name': 'Wooden Figurine'}]
            return []

        with mock.patch.object(locator.sqlio, 'query', side_effect=query), \
                mock.patch.object(locator.sqlio, 'has_column', return_value=False), \
                mock.patch.object(locator.phases, 'load', return_value=[]), \
                mock.patch.object(locator.phases, 'closed', return_value=[]), \
                mock.patch.object(locator.summons, 'known', return_value=(set(), set(), {})):
            found = locator.candidates({367069: 190309, 999: 5})
        self.assertEqual(found[('go', 375544)], {'name': 'Wooden Figurine', 'reasons': [['loot', 'item', 190309]]})
        self.assertEqual(len(found), 1)


if __name__ == '__main__':
    unittest.main()
