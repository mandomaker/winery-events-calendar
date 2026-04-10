# Gmail Search Queries for Winery Events

## Primary search query (use this first)

```
(winery OR vineyard OR wine club OR wine tasting OR wine dinner OR cellar OR sommelier OR "wine release" OR "harvest" OR "wine pickup") newer_than:30d
```

## Sender-based (add known wineries over time)

If the user has known winery email domains, add them:
```
(from:*winery.com OR from:*vineyard.com OR from:*wines.com OR from:*cellars.com) newer_than:30d
```

## Event-type specific queries

**Tastings & dinners:**
```
("wine tasting" OR "tasting event" OR "wine dinner" OR "winemaker dinner" OR "barrel tasting") newer_than:30d
```

**Wine club pickups:**
```
("wine club" OR "club pickup" OR "member pickup" OR "pick up your wine" OR "your order is ready") newer_than:30d
```

**Releases & launches:**
```
("wine release" OR "new release" OR "release party" OR "library release" OR "allocation" OR "futures") newer_than:30d
```

**Harvest & seasonal:**
```
("harvest event" OR "crush party" OR "harvest dinner" OR "vineyard tour" OR "estate visit") newer_than:30d
```

## Exclusion filters (add to any query to reduce noise)

```
-subject:receipt -subject:invoice -subject:order confirmation -subject:shipping
```

## Combined recommended query

```
(winery OR vineyard OR "wine club" OR "wine tasting" OR "wine dinner" OR "wine release" OR "barrel tasting" OR "winemaker dinner" OR "harvest event" OR "club pickup" OR "member pickup" OR "wine pickup" OR "tasting room") -subject:receipt -subject:invoice newer_than:30d
```
