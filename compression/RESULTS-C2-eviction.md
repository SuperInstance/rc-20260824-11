# C2 Eviction POC — RESULTS (2026-10-04 17:4x AKDT)

Question: **when summaries outnumber cells, which summaries get evicted?**

POC: `eviction_policy.py` (236 lines, stdlib only, NO RNG — every world bit
derives from `fnv1a(content)`). World: 50 C1-style summaries over 48 doubt
coordinates (8 topics × 6 variants); world truth `p` is a property of the
**coordinate**, hosts differ only in evidence depth `n_eff` (same-world
coherence asserted). Evict 50 → 20 (= cell count) under 3 policies. 40
deterministic future agents probe coordinates and try to reach gate-fire
`LB95 ≥ θ=0.70`, inheriting the deepest surviving host's Tier-K prior
(fewer new ticks) or starting fresh if no host survived.

## Comparison (all invariants green, fail-loud asserts active)

```
strategy         kept evic uniq_lost crit_lost  cover% mean_ticks saved
------------------------------------------------------------------------
none (baseline)    50    0         0         0   100.0        5.4    8.6
access             20   30         9         6    47.5        9.6    4.4
diversity          20   30         9         6    47.5        9.2    4.8
hybrid             20   30         6         0    40.0       10.5    3.4
```

- `uniq_lost` = sole-reference doubts destroyed (the ONLY summary covering
  that edge case was evicted). `crit_lost` = subset that are near-misses
  (deficit ≤ 0.05 at freeze) — C1's "nearly-knowledge" doubts.
- `saved` = mean ticks saved per future agent vs fresh-start.

## Findings

1. **The C1 risk is real for BOTH single-axis policies.** Access-based
   (rank-only) and diversity-based (redundancy-only) eviction destroy the
   *same* 6 critical sole-reference doubts out of the pool. Redundancy at
   topic level does NOT imply redundancy at doubt level: a summary can be
   topic-redundant while holding the only stamp on a specific coordinate
   variant. Rank and similarity are both blind to it.
2. **Diversity ≥ access on inheritance speed** (9.2 vs 9.6 mean ticks,
   4.8 vs 4.4 saved): redundancy-aware eviction accidentally keeps
   deeper-evidence hosts per coordinate. Coverage ties (47.5%).
3. **Hybrid (access + anti-redundancy + unique-doubt protection + near-miss
   bonus) drives critical losses to ZERO** (0 vs 6/6) at a price: −7.5pp
   coverage (40.0% vs 47.5%) and +0.9 mean ticks vs diversity. The trade is
   the point: irreplaceable evidence is not purchasable back with a colder
   cache, but ordinary coverage is.
4. Hybrid still loses 6 NON-critical unique doubts (weights W_UNIQUE=2.5,
   W_NEAR=1.0 fully shield near-misses, partially shield ordinary uniques).
   Weight sweep = follow-up lane.

## Determinism

Two in-process runs byte-identical (asserted); two independent process
invocations → identical output sha256
`fad226653960a675aa8a93d646e13cdc37839a9d2e406faab261972c931b2d4b`.
Results digest (in-band): `a4a16bb972901f39`.

## Receipts

- `eviction_policy.py` — this POC (run output above reproduced by
  `python3 compression/eviction_policy.py`).
- `eviction_policy.alt-20261004.py` — preserved parallel lane draft that
  raced this file 17:39 AKDT (byte-identical duplicate snapshot removed;
  sha256 `0e82f8fcbed0f1243c30ebe47f9db34c588806e030fd03509aa8902a1170ba52`).
  Its thesis ("evictability = redundancy, never rank alone") is consistent
  with finding 1 — a merge candidate for the weight-sweep lane.
- Books to: i2i ledger, `experiment:zeroclaw-c2-eviction`.
