<?php
// Auction house prices: world.auctionhousebot_market_price, the table the server's auction house bot prices its listings
// from. The Everlake image fills it at each worldserver start from TradeSkillMaster's public WoW Forever data (Samples = 0,
// Quantity = TSM's sold per day); older rows came from auction house browse scans (Samples > 0). The data is read from
// the realm's database at run time and never stored in this repository (TSM's terms: no bulk republishing).

function auction_prices_ready(): bool { return table_exists('auctionhousebot_market_price', 'world'); }

/** One item's row: ['price' => copper per unit, 'sold' => sold per day (TSM) or quantity seen, 'tsm' => bool], or null. */
function auction_price(int $item): ?array
{
    if (!auction_prices_ready()) return null;
    $r = row('SELECT UnitPrice, Quantity, Samples FROM auctionhousebot_market_price WHERE ItemID = ?', [$item], 'world');
    return $r ? ['price' => (int)$r['UnitPrice'], 'sold' => (int)$r['Quantity'], 'tsm' => (int)$r['Samples'] === 0] : null;
}

/** Copper as gold, silver and copper coins (the tooltip's .money style). */
function money_html(int $copper): string
{
    $g = intdiv($copper, 10000); $s = intdiv($copper % 10000, 100); $c = $copper % 100;
    return '<span class="money">' . ($g ? '<b class="g">' . number($g) . '</b>' : '') . ($s ? '<b class="s">' . $s . '</b>' : '')
        . ($c || (!$g && !$s) ? '<b class="c">' . $c . '</b>' : '') . '</span>';
}
