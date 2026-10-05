# cell-internals — DESIGN.md (ZeroClaw R&D Lane 1, 2026-10-04)

Charter target: *"ticks-as-probabilities — a cell's answer history as an
append-only data structure (no RNG); gates firing pipelines on tick
thresholds; reflex formation = thresholds that tighten from evidence."*

This lane answers the four questions: **what is a cell, what is its
probability distribution, how does it update from tick evidence, and what is
the minimal data structure.**

## 1. What a cell is

A cell is the minimal object that converts an **answer history** into a
**belief**. It owns exactly one question:

> *"When this question is asked, which answer does the world give?"*

Everything else — the shell lattice (exoj), the reflex engine (quilt-pincher) —
consumes cells; they do not define them. A cell here is the atom.

## 2. The minimal data structure

Four fields of state, one field of proof:

```text
Cell {
  question : str                      # the question this cell answers
  answers  : (a1, ..., ak)            # finite answer set, fixed at birth
  counts   : [c1, ..., ck]  (floats)  # decayed pseudo-counts, one per answer
  n        : int                      # ticks observed (monotone)
  head     : sha256 hex               # chain head of the tick ledger
}
constants (per cell): alpha (prior mass per answer), lam (decay ∈ (0,1])
```

That is the whole cell. `counts + n` is the **sufficient statistic**; `head`
is the append-only proof that the statistic was earned honestly
(the exoj `'ledger'` policy transplanted: **state is a ledger, the
distribution is a pure projection computed at sense time** — normalisation
never mutates the ledger, and every tick is content-addressed and chained:

```text
row_hash(t) = sha256( canonical( [ head, n, answer ] ) )
```

No RNG anywhere. All "entropy" enters as ticks from the world, content-derived.

## 3. The probability distribution

The cell's distribution is a **Dirichlet posterior mean over its answers**,
read out on demand:

```text
p_i = (c_i + alpha) / (Σc + k·alpha)
```

This is the unique estimator that (a) is a probability distribution,
(b) equals the Laplace/Dirichlet posterior mean of the tick history,
(c) is a **pure function of the ledger** — recompute from the tick log and
you get the same numbers, byte for byte (verified in the POC).

## 4. The update rule (tick → state)

One tick = one observed answer, from the world, appended:

```text
tick(a_j):
  counts ← [c_i · lam  for all i]     # (b) every count decays
  counts[j] += 1                      # (a) the observed tick lands
  n ← n + 1
  head ← sha256(canonical([head, n, a_j]))
```

Two knobs, two honest behaviours:

- **`lam = 1.0`** (no decay): the cell is a perfect frequentist. `p` converges
  to the world's true rate with error O(1/N); it never forgets.
- **`lam < 1.0`**: the cell keeps an effective memory of T = 1/(1−lam) ticks
  (exponentially-weighted pseudo-counts). It converges on a stationary world
  up to a bounded tracking bias, and **re-converges within O(T) ticks after
  the world changes** — demonstrated in the POC (world flip at tick 11).

The update is O(k) time, O(k) space, strictly append-only, and associative in
the decay sense: a snapshot+restore of `(counts, n, head)` round-trips exactly.
Note the consequence visible in the POC: two cells fed the *same* tick stream
(e.g. `lam=1.0` vs `lam=0.60` on the flipped world) produce the **same chain
head** — the ledger records *observations*; decay is a read-out policy over
it. The belief-earning is identical; the belief-reading is a knob.

## 5. Gates and reflex formation (the seam to quilt-pincher)

A **gate** on answer `a_i` fires a pipeline when the cell is *confident
enough*, not merely when the point estimate is high:

```text
gate(a_i, fire=θ):  fires ⇔  LB(a_i) ≥ θ      LB = one-sided 95% posterior lower bound
                    LB(a_i) = p_i − z · sqrt( Var_i ),   Var_i = Dirichlet variance
```

The margin `p − LB = z·σ` **shrinks like 1/√N_eff** as ticks accumulate
(`N_eff = Σc·(1+lam)/(1+lam·...) ≈ Σ counts` — effective sample size of the
decayed ledger). That shrinkage *is* reflex formation in its minimal form:
**the threshold tightens from evidence.** A young cell must shout to fire a
gate; a seasoned cell needs only a whisper above θ. Early on, noise cannot
trip pipelines; later, the same gate fires on small, real margins — the
muscle-memory-like reflex the charter asks for. (In pincher terms this is the
pinch→match→veto confidence seam; the gate here is deliberately
pipeline-agnostic — it only emits `fire`/`hold`.)

## 6. Convergence properties (what the POC demonstrates)

1. **Convergence:** with a stationary world, `p` → true rate; error shrinks
   as ticks accumulate (shown per-tick in the run).
2. **Calibrated uncertainty:** LB starts wide (gates can't fire on thin
   evidence) and tightens monotonically in the effective sample size.
3. **Adaptation with decay:** after a world flip, `lam=0.85` re-converges in
   a handful of ticks while `lam=1.0` would stay frozen (POC compares).
4. **Proof:** the tick ledger replays and re-derives the same chain head —
   NO VERIFIED SHA, NO BELIEF, satisfied per-cell.

## 7. What this is NOT (scope fence)

- No geometry (hex lattice is exoj's job), no vectors/HDC (pincher's seam),
  no execution of payloads — a cell only believes and fires.
- No inference between cells yet — Lane 2's problem (gates *between* cells).
- No likelihood modelling beyond multinomial answers (answers are nominal).

## 8. Next research question (handing to the loop)

**Coupling:** when one cell's gate fires, which other cells receive the tick?
The minimal candidate is neighbour-priors — a fired gate on cell A adds a
fraction of pseudo-mass to a named answer of cell B (exoj's ring, one hop) —
but the honest open question is whether coupling should live in the *gates*
(pincher's world: pipelines carry ticks) or in the *cells* (exoj's world:
the field deforms). That is Lane 2.
