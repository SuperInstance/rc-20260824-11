# Gate Mechanisms — DESIGN.md (Lane 2, 2026-10-04)

ZeroClaw build direction, item 3: *ticks-as-probabilities — cells' answer
history as an append-only data structure (no RNG); gates firing pipelines on
tick thresholds; reflex formation = thresholds that tighten from evidence.*
This is the design for the middle clause, proven by `poc.py` (runs green,
receipt printed, NO VERIFIED SHA, NO BELIEF).

Lineage honored: exoj `gan/unitTable.mjs` (fnv1a content-derived entropy,
**no RNG anywhere**), exoj `core.mjs` ledger accumulation (commutative,
append-only), pincher match thresholds (the seed of gate firing).

## 1. The cell (recap, Lane 1 substrate)

A **cell** is a question answered over time. Every answer is a **tick**:
`+1` or `-1`, appended to a ledger that is never mutated.

- `p = (ups + 1) / (n + 2)` — Laplace-smoothed mean; starts at 0.5 on an
  empty ledger, stays in `[0,1]` *by construction* (no clamping, no float
  coercion — counts are the state).
- The tally is **commutative**: any permutation of the same tick multiset
  yields the same `p`. Order lives only in *when* ticks arrive, never in
  the cell's aggregate state. (Same property exoj receipts for its
  `accumulate()` multisets, residual float noise aside — counts here are
  exact.)
- The world's stimulus stream is **deterministic**: tick t for question q
  is `fnv1a(q + ":" + t) % 100 < bias`. Re-running the POC reproduces the
  run bit-for-bit. There is no `random` import in `poc.py`.

## 2. The gate: firing contract

A **gate** is a directed edge between cells with a threshold `θ`, a
refractory period `R`, and an adaptation rate `λ`. On each world tick, after
the world's ticks land, every gate evaluates **against a snapshot** of
source probabilities taken before any gate fired that tick (synchronous
semantics). If the predicate holds and the refractory permits, the gate
**fires**: it appends exactly one tick to its target's ledger.

Three rules bound every firing:

1. **Refractory** `R`: after a gate fires it cannot fire again for `R`
   ticks. Spike-then-rest. This is what makes cascades *lagged* rather
   than instantaneous, and what bounds all loops.
2. **Adaptation (reflex formation):** on fire, `θ ← θ + λ·(1 − θ)` — the
   gate tightens; evidence that a gate fires a lot makes it *harder* to
   fire again (habituation). Between fires it relaxes toward its base
   threshold: `θ ← θ − ρ·(θ − θ_base)`. A reflex that dampens itself —
   the charter's requirement — is this rule plus loop topology.
3. **Append-only emission:** a gate can only add ticks. It never edits,
   retracts, or reweights history. Damping = writing `-1` ticks, never
   deleting `+1` ticks.

## 3. Gate kinds (exactly three primitives)

| kind | predicate (on source `p`) | emission to target |
|---|---|---|
| `excite` | `p ≥ θ` | `+1` tick |
| `inhibit` | `p ≥ θ` | `-1` tick |
| `sign` (bidirectional) | `p ≥ θ` → `+1`; `p ≤ 1−θ` → `-1` | tick carrying the source's evidence sign |

`sign` is the only primitive that transmits in both directions: it carries
*which way* the source leans, not just its strength. It is how a pipeline
propagates "no" as loudly as "yes".

## 4. Cascade and negative feedback are not kinds — they are compositions

This is the core design claim:

- **Cascade** = gate A's target is gate B's source. No cascade object
  exists anywhere in the code. Because emissions land after the snapshot,
  a cascade of depth k propagates with lag ≥ k ticks — delay is emergent,
  measurable, and equals structural depth. Pipelines *are* the wiring.
- **Negative feedback** = any cycle in the wiring whose edges are
  predominantly `inhibit` (or an `excite`→`inhibit` pair against a shared
  cell), plus per-gate adaptation. The loop's own activity raises θ and
  writes damping ticks back into its source — the reflex dampens itself
  twice: topologically (the `-1` ticks) and parametrically (θ tightening).
- **Pipelines emerge from scratch** because nothing schedules them: cells
  start empty (`p = 0.5`, below every θ), world ticks arrive, and any gate
  whose source crosses θ starts firing. The activity pattern *is* the
  pipeline; wiring + thresholds are the only authored structure.

## 5. The POC circuit (3 cells, 3 gates — minimal)

```
world ──ticks──▶ C1 sees-light ──G1 excite(θ=.70)──▶ C2 approach ──G3 sign(θ=.65)──▶ C3 commit-move
                     ▲                                  │
                     └────────── G2 inhibit(θ=.75) ──────┘   (negative feedback loop)
```

- **G1** demonstrates threshold firing: world stream is 80% `+1`; C1
  crosses 0.70 and G1 fires, injecting evidence into C2.
- **G3** demonstrates cascade + bidirectional: it fires only *after* G1
  has driven C2 across 0.65 — lag ≥ 1 tick is asserted, never scheduled.
- **G2** demonstrates negative feedback: when C2 (approach) gets
  confident, it writes `-1` ticks back into C1 — approach's own evidence
  damps its cause. Assertions: G2 fires, and C1's post-damping peak stays
  below its pre-damping peak; θ₂ ends above its base (adaptation held).

## 6. What this does NOT do (L4)

- No learning of *wiring* — the circuit topology is authored, not grown.
  Threshold adaptation is the only plasticity.
- No `context_sha256`-style spec output yet — the run receipt is a sha256
  over canonical JSON of the whole tick/fire ledger, but it is not yet in
  `zeroclaw-reflex-spec/v1` form for pincher to `loadZeroclawSpecs()`.
- No persistence, no concurrency, no hex lattice, no γ/η amplitudes —
  cells here are pure tick tallies. exoj field coupling is future work.
- No veto/listener tier (pincher's third cell) — gates have no safety
  override beyond refractory + adaptation.

## 7. When it fails / what to do (L5)

- **Assertions trip (exit ≠ 0):** read the printed invariant name first —
  refractory violations mean a code bug (the guard is total); damping/
  cascade assertions mean parameter drift. Re-tune θ/λ/ρ in the CONFIG
  block at the top of `poc.py` and re-run; do not delete the assertion
  (fail loud is the law).
- **No gate fires at all:** world bias too low or θ too high. Check the
  printed p-trace, lower θ toward the source's equilibrium p.
- **Loop locks up (G2 fires every permitted tick):** raise R or λ. A
  healthy loop oscillates, it does not saturate.

## 8. Next research questions

1. Can wiring *grow* — a gate that, after N correlated co-fires, sprouts
   an `excite` edge between previously unconnected cells (Hebbian
   tick-correlation over the append-only ledger, still no RNG)?
2. Is θ-tightening the right reflex former, or should thresholds track a
   running p-quantile so they self-calibrate per cell?
3. How does a cascade of `sign` gates behave under an adversarial
   (50/50) stream — bounded oscillation or gridlock? (Refractory says
   bounded; measure it.)
4. Serialize the fired-gate ledger as a `zeroclaw-reflex-spec/v1` payload
   and have pincher serve it — closing Lane 2 into the Lane 1 seam.
