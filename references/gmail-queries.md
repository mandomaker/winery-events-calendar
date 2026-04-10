# Gmail Search Queries for Winery Events

## Strategy: Multiple Simple Searches

Complex compound queries with nested quotes don't work reliably through `gog`. Instead, run multiple focused searches and deduplicate by message ID.

## Core searches (run all, deduplicate)

```bash
# 1. Winery keyword
gog gmail messages search "winery newer_than:30d" --max 30 --account USER --json

# 2. Vineyard keyword
gog gmail messages search "vineyard newer_than:30d" --max 30 --account USER --json

# 3. Wine event terms (simple OR)
gog gmail messages search "wine tasting OR wine dinner OR wine club OR release party newer_than:30d" --max 30 --account USER --json

# 4. Specific event types
gog gmail messages search "wine pickup OR club pickup OR barrel tasting OR winemaker dinner newer_than:30d" --max 20 --account USER --json
```

## Known sender searches (add over time)

```bash
# Winery associations
gog gmail messages search "from:dundeehills.org newer_than:30d" --max 10 --account USER --json

# Individual wineries (add as discovered)
gog gmail messages search "from:adelsheim.com newer_than:30d" --max 10 --account USER --json
```

## Filtering out noise

After retrieving candidates, skip emails whose subjects match:
- Receipt, invoice, order confirmation, shipping notification
- Pure sale/discount (no event date in body)
- Unsubscribe confirmations

## What actually works (lessons learned)

1. **Simple keywords beat complex queries** — `winery newer_than:30d` catches more than a 15-term compound query
2. **Newsletters are the primary source** — winery associations and individual wineries send monthly newsletters packed with events
3. **Forwards from family/friends** — someone forwarding a winery email is a strong signal of interest
4. **30 days is the right lookback** — events are announced weeks ahead; 14 days misses too many
5. **Deduplication by message ID** is essential since the same email may match multiple searches
