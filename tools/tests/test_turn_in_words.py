"""python -m unittest discover -s tools/tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import server  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'wowhead-quest-text')


def page(name):
    with open(os.path.join(FIXTURES, name + '.txt'), encoding='utf-8') as f:
        return f.read()


class TurnInWords(unittest.TestCase):
    """A quest whose Wowhead page, kept whole, has no Progress and no Completion words is asked no turn-in text."""

    def test_pages_with_words(self):
        self.assertTrue(server.page_has_turn_in_words(page('both')))
        self.assertTrue(server.page_has_turn_in_words(page('complete')))   # the heading glued to the Description

    def test_page_without_words(self):
        # "Progress" and "Completion" in the objectives, before the Description heading, are no headings
        self.assertFalse(server.page_has_turn_in_words(page('none')))
        self.assertFalse(server.page_has_turn_in_words(''))
        self.assertFalse(server.page_has_turn_in_words(None))


if __name__ == '__main__':
    unittest.main()
