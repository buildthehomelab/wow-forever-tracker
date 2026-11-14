"""python -m unittest discover -s tools/tests"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from ft import quests  # noqa: E402

# a record as EG Link keeps it: what the client's quest cache holds
RECORD = {
    'title': 'Elemental Aid', 'objectivesText': 'Defeat Charlga Razorflank.', 'description': 'Now that you have mastered the elements...\r\n\r\nGo.',
    'completionText': 'Bring the note to Rau.', 'areaDescription': '', 'flags': 36700168, 'flagsEx': 2, 'level': 33, 'minLevel': 30, 'nextQuestId': 79364,
    'questInfoId': 81, 'questType': 2, 'raceMask': 'aa2aaaaa4e0ab3b2', 'categoryId': 82, 'startItemId': 5, 'timeLimitSeconds': 600, 'sources': 1,
    'objectives': [{'amount': 1, 'id': 472435, 'objectId': 274463, 'storageIndex': 0, 'type': 'item', 'typeId': 1},
                   {'amount': 8, 'id': 472436, 'objectId': 4421, 'storageIndex': 1, 'type': 'monster', 'typeId': 0, 'text': 'Quilboar slain'},
                   {'amount': 1, 'id': 472437, 'objectId': 99, 'storageIndex': -1, 'typeId': 2}, {'amount': 1, 'id': 472438, 'objectId': 4422, 'storageIndex': 3, 'typeId': 3},
                   {'amount': 1, 'id': 472439, 'objectId': 7, 'storageIndex': 4, 'typeId': 14}],
    'itemDrops': [{'itemId': 279378, 'count': 1}],
    'rewards': {'money': 3500, 'xpDifficulty': 6, 'xpMultiplier': 2.1, 'spellId': 8, 'items': [{'itemId': 10, 'count': 2}],
                'choices': [{'itemId': 3443, 'count': 1}, {'itemId': 4961, 'count': 1}], 'currencies': [{'currencyId': 3402, 'amount': 50}],
                'reputation': [{'factionId': 81, 'tier': 5}, {'factionId': 72, 'tier': -2, 'override': 50000}],
                'displaySpells': [{'spellId': 635, 'type': 0}, {'spellId': 1230643, 'type': 2}]},
}


class Rows(unittest.TestCase):
    def test_a_record_s_rows(self):
        quest, problems = quests.rows(79360, RECORD)
        self.assertEqual(problems, [])
        t = quest.template
        self.assertEqual([t[c] for c in ('ID', 'QuestType', 'QuestInfoID', 'RewardNextQuest', 'StartItem', 'Flags', 'FlagsEx', 'FlagsEx2', 'TimeAllowed')],
                         [79360, 2, 81, 79364, 5, 36700168, 2, 0, 600])
        self.assertEqual((t['QuestSortID'], t['RewardXPDifficulty'], t['RewardXPMultiplier'], t['RewardSpell']), (-82, 6, 2.1, 8))
        self.assertEqual(t['AllowableRaces'], 0xaa2aaaaa4e0ab3b2)
        self.assertEqual([t[c] for c in ('RewardItem1', 'RewardAmount1', 'RewardItem2', 'ItemDrop1', 'ItemDropQuantity1', 'ItemDrop2')], [10, 2, 0, 279378, 1, 0])
        self.assertEqual([t[c] for c in ('RewardChoiceItemID1', 'RewardChoiceItemQuantity1', 'RewardChoiceItemID2', 'RewardChoiceItemID3')], [3443, 1, 4961, 0])
        self.assertEqual([t[c] for c in ('RewardCurrencyID1', 'RewardCurrencyQty1', 'RewardCurrencyID2')], [3402, 50, 0])
        # the tier is the value; the cap is 7 in every slot, used or not, as the world's own rows hold it
        self.assertEqual([t[f'RewardFaction{c}{i}'] for i in (1, 2, 3) for c in ('ID', 'Value', 'Override', 'CapIn')], [81, 5, 0, 7, 72, -2, 50000, 7, 0, 0, 0, 7])
        self.assertEqual((t['AcceptedSoundKitID'], t['CompleteSoundKitID'], t['Expansion']), (890, 878, -2))
        self.assertEqual((t['LogTitle'], t['LogDescription'], t['QuestCompletionLog'], t['AreaDescription']),
                         ('Elemental Aid', 'Defeat Charlga Razorflank.', 'Bring the note to Rau.', ''))
        self.assertEqual(t['QuestDescription'], 'Now that you have mastered the elements...\r\n\r\nGo.')          # to the character
        self.assertEqual([tuple(o.values()) for o in quest.objectives], [
            (472435, 79360, 1, 0, 0, 274463, 1, 32, ''), (472436, 79360, 0, 1, 1, 4421, 8, 32, 'Quilboar slain'), (472437, 79360, 2, 2, -1, 99, 1, 32, ''),
            (472438, 79360, 3, 3, 3, 4422, 1, 32, ''), (472439, 79360, 14, 4, 4, 7, 1, 32, '')])
        self.assertEqual((quest.level, quest.money, quest.spells, quest.classes), ((33, 30), 3500, [(635, 0), (1230643, 2)], 64))      # filed under Shaman
        self.assertEqual(quests.targets(quest), {'npc': [4421, 4422], 'object': [99]})
        self.assertEqual(quest.unread, [])
        more = dict(RECORD, conditionalDescriptions=[{'playerConditionId': 1, 'text': 'x'}], treasurePickerIds=[5], rewards=dict(RECORD['rewards'], somethingNew=1))
        self.assertEqual(quests.rows(79360, more)[0].unread, ['conditionalDescriptions', 'treasurePickerIds', 'rewards.somethingNew'])     # carried, not written: named

    def test_every_row_names_the_same_columns(self):
        bare, problems = quests.rows(5, {'title': 'Bare', 'flags': 0, 'level': 1, 'minLevel': 1, 'questType': 0, 'raceMask': 'ffffffffffffffff', 'rewards': {}})
        self.assertEqual(problems, [])
        self.assertEqual(list(bare.template), list(quests.rows(79360, RECORD)[0].template))
        self.assertEqual((bare.template['QuestSortID'], bare.template['RewardXPMultiplier'], bare.template['AllowableRaces']), (0, 1, 2 ** 64 - 1))
        self.assertEqual((bare.objectives, bare.money, bare.spells, bare.classes), ([], 0, [], 0))
        zone = quests.rows(6, dict(RECORD, zoneAreaId=17, categoryId=0))[0]
        self.assertEqual((zone.template['QuestSortID'], zone.classes), (17, 0))             # a zone, not a category: no class follows from it

    def test_a_record_that_cannot_be_written_says_why(self):
        def broken(**changes):
            record = copy.deepcopy(RECORD)
            for key, value in changes.items():
                target = record['rewards'] if key in ('items', 'choices', 'reputation', 'currencies', 'displaySpells', 'money', 'xpMultiplier', 'spellId') else record
                if value is None:
                    target.pop(key, None)
                else:
                    target[key] = value
            return quests.rows(1, record)[1]
        self.assertEqual(quests.rows(1, None), (None, ['its record is not a record']))
        self.assertEqual(broken(title='  '), ['it has no title'])
        self.assertEqual(broken(title=5), ['title is not text the file can hold', 'it has no title'])
        self.assertEqual(broken(description='half a pair \ud83d'), ['description is not text the file can hold'])
        self.assertEqual(broken(description='a\x00b'), ['description is not text the file can hold'])
        self.assertEqual(broken(questType=4), ['questType is not a number the column takes'])
        self.assertEqual(broken(zoneAreaId=12), ['it names both a zone and a category: the row has room for one'])
        self.assertEqual(broken(reputation=[{'factionId': 81, 'tier': 10}]), ['reputation: factionId, tier or override is not a number the columns take'])
        self.assertEqual(broken(flags=True), ['flags is not a number the column takes'])
        self.assertEqual(broken(flags=2 ** 32), ['flags is not a number the column takes'])
        self.assertEqual(broken(raceMask='0x10'), ['raceMask is not 64 bits written in hex'])
        self.assertEqual(broken(raceMask=None), ['raceMask is not 64 bits written in hex'])
        self.assertEqual(broken(items=[{'itemId': 1, 'count': 1}] * 5), ['5 items: the row has room for 4'])
        self.assertEqual(broken(choices=[{'itemId': 1}]), ['choices: itemId or count is not a number above 0'])
        self.assertEqual(broken(reputation=[{'factionId': 81, 'tier': 'high'}]), ['reputation: factionId, tier or override is not a number the columns take'])
        self.assertEqual(broken(reputation='many'), ['reputation is not a list of records'])
        self.assertEqual(broken(objectives=[{'id': 0, 'typeId': 1, 'objectId': 1}]), ['an objective has no id, or a field the columns do not take'])
        self.assertEqual(broken(objectives=[{'id': 9, 'typeId': 1, 'objectId': 1}] * 2), ['two objectives share an id'])
        self.assertEqual(broken(level=None), ['level or minLevel is not a number'])
        self.assertEqual(broken(money='lots'), ['money is not a number'])
        self.assertEqual(broken(xpMultiplier=True), ['xpDifficulty or xpMultiplier is not a number'])
        self.assertEqual(broken(displaySpells=[{'type': 2}]), ['displaySpells: spellId or type is not a number'])
        self.assertEqual(broken(rewards=[]), ['rewards is not a record'])
        self.assertEqual(broken(zoneAreaId=-5), ['zoneAreaId or categoryId is not a number the column takes'])


class Said(unittest.TestCase):
    def test_one_wording_is_the_text_with_the_world_s_line_breaks(self):
        self.assertEqual(quests.said(['Well done, $N.\n\nTake this.']), ('Well done, $N.$B$BTake this.', ''))
        self.assertEqual(quests.said(['  One. \r\n Two.\rThree.  ']), ('One.$BTwo.$BThree.', ''))
        self.assertEqual(quests.said(['Same.\n', 'Same.', '  Same.']), ('Same.', ''))              # one wording, however often it was seen
        self.assertEqual(quests.said(["It's \\ 'quoted' \u00e9."]), ("It's \\ 'quoted' \u00e9.", ''))

    def test_what_is_not_one_text_is_not_taken(self):
        self.assertEqual(quests.said(['To a mage.', 'To a warrior.']), (None, '2 wordings were recorded'))
        self.assertEqual(quests.said([]), (None, 'nothing was recorded'))
        self.assertEqual(quests.said(['  ', None, 5]), (None, 'nothing was recorded'))
        self.assertEqual(quests.said(['a\x00b']), (None, 'it is not text the file can hold'))
        self.assertEqual(quests.said(['half a pair \ud83d']), (None, 'it is not text the file can hold'))


if __name__ == '__main__':
    unittest.main()
