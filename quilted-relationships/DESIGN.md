# Quilted Relationships — DESIGN.md (Swarm Q2, 2026-10-04)

**QUESTION:** What does "push and pull" between agents mean at the data
structure level?

**ANSWER (the whole design in one sentence):** push and pull are the two
halves of one directed edge that is itself a cell — two ordered doc-sha
buffers plus decayed hit/miss pseudo-counts, whose Laplace mean `p(hit)`
drives a push-cadence backoff timer. High hit rate → the timer shortens →
the edge pushes often. High miss rate → the timer lengthens → the edge
falls back to targeted pulls. The relationship *learns its own shape*;
nobody schedules it.

Runnable proof: `poc.py` (223 lines, stdlib only, NO RNG — every world bit
is `fnv1a(content)`, exoj law). Receipt below is from the actual run.

## 1. The data structure

```
Edge(src -> dst):
  out_buffer   ordered shas the SOURCE offers   (window of last CAP docs,
                sorted by fnv1a(sha) — content-derived, permutation-stable)
  in_buffer    ordered shas the DST received via THIS edge (arrival order,
                windowed — the edge's private delivery ledger)
  ups, downs   decayed pseudo-counts (Lane-1 cell), lam = 0.90
  p(hit)       = (ups + 1) / (ups + downs + 2)   — Laplace-smoothed mean
  backoff      push cadence timer, 1..8; since = cycles since last push
```

An **Agent** is a doc store (`docs`, `hist`) — nothing more. All
relationship state lives on the edge, not the agents. A bidirectional
relationship is exactly two directed edges (A→B ≠ B→A; each learns its
own cadence from its own evidence).

## 2. Push and pull, precisely

- **PUSH** (source-initiated, *blind*): when `since >= backoff`, src offers
  its **newest** doc. The pusher does not know what the dst wants or has —
  that blindness is what makes push cheap but lossy. Outcome for the edge
  cell:
  - dst already knew it → **redundant** miss,
  - new but not wanted → **unwanted** miss,
  - new and wanted → **hit**.
  - hit → `backoff = max(1, backoff−1)`; miss → `backoff = min(8, backoff+1)`.
- **PULL** (destination-initiated, *targeted*): on off-cadence cycles, dst
  scans src's `out_buffer` for docs it lacks **and** wants
  (`fnv1a(sha:dst:want) % 100 < affinity`), takes the best by
  `fnv1a(sha:dst:score)`. A pull cannot be redundant or unwanted by
  construction — that is the entire point of pull.

So "push vs pull" at the data-structure level = **who supplies the
targeting information**: push spends the *source's* nothing (blind, newest
first, pays in misses); pull spends the *destination's* want-vector
(targeted, pays in asking). The edge cell is the accountant that shifts
traffic toward whichever side's information is currently cheaper.

## 3. Why the edge is cell-like (charter alignment)

Same shape as Lane 1: append-only evidence (every push outcome lands as
±1 after decay), counts are the state, `p` is Laplace-smoothed so a cold
edge starts honest at 0.5, decay `lam=0.90` forgives old misses (reflex
loosening — a relationship that went stale can reopen). No clamping, no
RNG, no floats in the state. The backoff rule is the edge's gate: a
one-parameter reflex that tightens from evidence, exactly the
*ticks-as-probabilities* law applied to relationships instead of cells.

## 4. POC demo (the required six steps) — receipts from the run

World: agents gen 1 doc/cycle; affinity table — B wants 70% of A's docs,
A wants only 30% of B's, C's edges 45–60%. Cycles 1–14 pair AB, C joins
at t=15, mesh to t=20.

1. **A, B different knowledge** — 3 seed docs each, disjoint sets. ✓
2. **Bidirectional edges** — A→B and B→A, independent learners. ✓
3. **20 cycles of push/pull** — full trace printed per cycle. ✓
4. **Edge quality improves** — miss rate (= (redundant+unwanted)/pushes):
   pair AB t1–14: **0.54** → C-join shock t15–17: **0.82** (multipath
   redundancy — the mesh's new second routes make blind pushes collide)
   → settled mesh t18–20: **0.38**. Shock, then adaptation, then better
   than the pre-C baseline. And per-edge shapes diverge as the spec
   predicts: A→B ends `p=0.70, backoff=1` (high hit = frequent push);
   B→A ends `p=0.39, backoff=4, 6 pulls vs 8 pushes` (high miss = more
   pull). ✓
5. **Agent C integrates** — 4 fresh cold edges (p=0.5) at t=15; by t=20
   they carry 9 pulls, and C reaches 15/52 docs = 0.29 coverage vs 0.12
   solo (2.4×). ✓
6. **Full mesh benefits** — coverage at t=20: A 0.73, B 0.87 vs 0.44 solo;
   C 0.29 vs 0.12 solo. Every agent beats its solo counterfactual, and
   the settled-window miss rate beats the pairwise era. ✓

Invariants (asserted, fail-loud): `p ∈ (0,1)`, backoff bounded, buffers
capped at 8, no duplicate delivery via any edge, **bit-identical full
replay** — `sha=e24cf22ef7b481ef` for the whole 20-cycle trace.

## 5. Honest limits

- "Unwanted" misses can never reach zero on a blind push — the floor is
  `1 − affinity`. The edge's job is to *route around* the floor (pull),
  not to repeal it.
- Affinity is static here; a world that drifts would exercise the decay
  path harder (lam is the only knob that tracks it — future lane).
- One doc per push/pull per cycle; batching is a parameter sweep away,
  deliberately out of scope for the simple spec.

## 6. Receipts

- POC: `python3 quilted-relationships/poc.py` → ALL CHECKS PASS,
  deterministic replay sha `e24cf22ef7b481ef` (this box, 2026-10-04).
- Commit + `git ls-remote` verbatim in the lane report (charter law).
- i2i ledger: booked to `zeroclaw-loop`.
- Retry-1 (347-line over-spec attempt) archived by rename as
  `poc.py.retry1-archived-20261004` — nothing deleted.
