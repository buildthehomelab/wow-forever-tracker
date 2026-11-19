"""The server's ItemExtendedCost rows by what they ask, so that a vendor row paid with currencies or items (Wowhead's
sold-by cost) can name the cost the server already has.

A vendor's price in this client is the item's money price plus, when npc_vendor.ExtendedCost is set, what that
ItemExtendedCost row asks: items and currencies. A cost is taken only from rows that ask nothing else (no money of
their own, no arena rating, no achievement, no reputation, no flags): such a row is exactly "these items and these
currencies", and the lowest ID of a kind is the one taken. The website calls `tracker.py costs` and reads the JSON.
"""
from . import db2


def cost_key(currencies, items):
    """The key of a cost: its currencies and items as "c<id>x<count>" and "i<id>x<count>", sorted, comma-separated.
    `currencies` and `items` are [(id, count), ...]; zero ids or counts are dropped. '' for a cost of money only."""
    parts = [f'c{int(i)}x{int(n)}' for i, n in currencies if int(i) > 0 and int(n) > 0]
    parts += [f'i{int(i)}x{int(n)}' for i, n in items if int(i) > 0 and int(n) > 0]
    return ','.join(sorted(parts))


PLAIN = ('Money', 'RequiredArenaRating', 'ArenaBracket', 'Flags', 'MinFactionID', 'MinReputation', 'RequiredAchievement')


def by_key(rows):
    """{key: the lowest ItemExtendedCost ID asking exactly that} from DB2 rows (dicts as ft.db2 reads them)."""
    out = {}
    for row in sorted(rows, key=lambda r: int(r['ID'])):
        if any(int(row.get(column) or 0) for column in PLAIN):
            continue
        key = cost_key([(row.get(f'CurrencyID{n}') or 0, row.get(f'CurrencyCount{n}') or 0) for n in range(1, 6)],
                       [(row.get(f'ItemID{n}') or 0, row.get(f'ItemCount{n}') or 0) for n in range(1, 6)])
        if key:
            out.setdefault(key, int(row['ID']))
    return out


def load(folder):
    """{key: ID} of the ItemExtendedCost.db2 in `folder`; {} when the file is not there."""
    try:
        return by_key(db2.load(folder, 'ItemExtendedCost').values())
    except FileNotFoundError:
        return {}
