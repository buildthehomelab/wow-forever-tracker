"""Keys handed out by hotfix in any region, from wago.tools (ft.cdn.wago_keys), next to wowdev's TACTKeys list."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from ft import cdn  # noqa: E402

# WoW: Forever's TactKey 7754 and its name in TactKeyLookup (wago.tools, 2026-11-18)
KEY = bytes.fromhex('245BECCE' + '00' * 12)
TACT_KEY = ('ID,' + ','.join(f'Key_{i}' for i in range(16)) + '\n'
            + '7754,' + ','.join(str(b) for b in KEY) + '\n'
            + '9999,' + ','.join('0' for _ in range(16)) + '\n'      # an empty key: not handed out
            + '8000,' + ','.join('1' for _ in range(16)) + '\n')     # no name for it
LOOKUP = ('ID,' + ','.join(f'TACTID_{i}' for i in range(8)) + '\n'
          + '7754,137,147,229,131,229,23,33,14\n'
          + '9999,1,2,3,4,5,6,7,8\n')


def fetcher(tables, asked=None):
    def fetch(url):
        if asked is not None:
            asked.append(url)
        for name, text in tables.items():
            if f'/db2/{name}/csv?product=' in url:
                return text.encode()
        raise cdn.Gone(url)
    return fetch


class WagoKeys(unittest.TestCase):
    def test_keys_are_named_through_the_lookup_table(self):
        asked = []
        keys = cdn.wago_keys('wowf', fetcher({'TactKey': TACT_KEY, 'TactKeyLookup': LOOKUP}, asked))
        self.assertEqual(keys, {'0E2117E583E59389': KEY})   # the name is stored low byte first
        self.assertEqual(asked, ['https://wago.tools/db2/TactKey/csv?product=wowf', 'https://wago.tools/db2/TactKeyLookup/csv?product=wowf'])

    def test_wago_down_adds_nothing(self):
        self.assertEqual(cdn.wago_keys('wowf', fetcher({'TactKey': TACT_KEY})), {})
        self.assertEqual(cdn.wago_keys('wowf', fetcher({'TactKey': 'not,a\ncsv', 'TactKeyLookup': '<html>'})), {})

    def test_published_list_comes_first(self):
        listed = b'0E2117E583E59389 ' + b'11' * 16 + b'\nFA505078126ACB3E ' + b'22' * 16 + b'\n'
        with mock.patch.object(cdn, 'get', side_effect=lambda url, *a, **k: listed if url == cdn.KEYS else fetcher({'TactKey': TACT_KEY, 'TactKeyLookup': LOOKUP})(url)):
            keys = cdn.published_keys('wowf')
        self.assertEqual(keys['0E2117E583E59389'], bytes.fromhex('11' * 16))
        self.assertIn('FA505078126ACB3E', keys)

    def test_a_key_only_wago_has_is_published(self):
        with mock.patch.object(cdn, 'get', side_effect=lambda url, *a, **k: b'' if url == cdn.KEYS else fetcher({'TactKey': TACT_KEY, 'TactKeyLookup': LOOKUP})(url)):
            self.assertEqual(cdn.published_keys('wowf'), {'0E2117E583E59389': KEY})


if __name__ == '__main__':
    unittest.main()
