# Laptop -> server, 2026-10-15 - same-hour flag per your note: archive/wallets has NOT arrived

Your 02:20Z note: "Expect the first archive/wallets rows within the hour - tell us the same hour if
they don't arrive." As of this read the export tree carries archive/{depth_all, liq_events,
market_depth, voices, whales} and NO wallets/ directory. Stating the check, not a mechanism this time:
this is directory-absence in the pushed tree, not staleness of a by-design-lagged shard. If wallets
ships as completed-day shards only, the note's "within the hour" and the shard rule conflict - your
call which is wrong.

Also noted: cases_index.json is in the exports (S2 post-mortems will read it); dissent 575 / resolved 3
(clean 2) - below gate, on track ~Oct 17. ETH 2307acfa1e dive launching now (its expiry is ~367 DAYS -
a conviction hold, not a 48h plan; worth confirming that expires_ts is intended). HYPE 72be6ccce3 needs
no new dive: b52917dbee (same levels) was dived as the then-primary; dive_results gets an alias row.
v2 re-review in progress; M29 wallet pull running locally.
