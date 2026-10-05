# jev-selection — DESIGN.md (Swarm Lane J1, 2026-10-04)

**Question (charter / Casey's swarm directive):** *How does JEV project a
probability distribution over "which agent fires next"? The percentages are
literal firing odds, not rankings. How is the selection distribution computed
from N cells' probability distributions — does each cell contribute one
dimension? Does it normalize? How is sum-to-1.0 and stability ensured?*

This lane answers those four questions with a design plus a runnable proof
(`poc.py`, green output printed below, receipted). Lineage: the cells are the
**cell-internals** cells (Lane 1, commit `1ce322d`) — imported, not
re-implemented; the no-RNG law is exoj `gan/unitTable` fnv1a; the "soft
deformation, never a definite token" law is exoj `core.mjs` JEV.

## 1. The model in one paragraph

JEV is the **mesh**: a fixed population of agents `a_1…a_N` and a field of
cells `m_1…m_M`. Each cell holds a belief `p_m` (Dirichlet posterior mean
over its own answer set) earned from ticks. A **wiring** `W_m` maps each of
cell m's answers to a distribution over agents — that wiring *is* the logic
decomposition ("if the world says *yes* to relay/alive, here's how my
evidence splits over who should fire"). Collapsing `p_m` through `W_m` puts
every cell at **one point on the agent simplex** `s_m ∈ Δ^N`. JEV then pools
the cell points with a **weighted geometric (log-linear) opinion pool**,
where each cell's vote weight is its evidence mass. The result is normalized
once and becomes the firing odds. The **moth quantum** — a single fnv1a draw
against the content-addressed receipt of that distribution — is the only
collapse event, and it is recorded.

## 2. The five layers

```text
(1) CELLS        p_m ∈ Δ^{k_m}        Dirichlet posterior mean (Lane 1 cell,
                                       decayed pseudo-counts, hash-chained ledger)
(2) WIRING       W_m: Y_m → Δ^N        per answer, a row over agents, rows
                                       normalized (the logic decomposition)
(3) SIMPLEX      s_m = Σ_y p_m(y)·W_m(y) ∈ Δ^N
                POINT                a mixture of rows ⇒ a distribution by
                                       construction; one point per cell
(4) POOL         L(a) = Σ_m w_m · ln s̃_m(a)      weighted log-linear pool;
                J(a) = softmax(L)(a)              w_m = n_eff(m)/(n_eff(m)+n₀)
(5) COLLAPSE     u = fnv1a(receipt)/2³²  → CDF walk → one agent fires
```

Layer 3 is where "N cells' distributions" become one selection
distribution's *ingredients*; layer 4 is the mesh proper.

## 3. Answers to the four questions

**Does each cell contribute one dimension?** No. A cell's native dimension
is its answer set (`k_m` answers), but its *contribution to JEV* is one
point on the agent simplex (`s_m`, an N-vector) plus one scalar weight
(`w_m`). The mesh is therefore `M` weighted points on `Δ^N` — not an
`M`-dimensional tensor, not a ranking. Cells with different answer-set sizes
(`k=2` binary cells, `k≥3` later) mesh without any dimension bookkeeping,
because wiring normalizes every answer to the same target simplex.

**Does it normalize?** Yes — three times, each at a different layer, and
only one of them is an explicit division:

1. `p_m` — Dirichlet posterior mean is a distribution by construction
   (`(c_i+α)/(Σc+kα)`); the ledger is never touched (Lane 1 law).
2. `s_m` — a convex combination (`Σ_y p_m(y)·W_m(y)`) of rows that each sum
   to 1, with weights that sum to 1. A mixture of distributions **is** a
   distribution; no renormalization step exists to drift.
3. `J` — the pool output is normalized once, via log-sum-exp
   (`exp(L−max L)/Σ exp(L−max L)`). This is the only division, it is the
   final act, and float error is one rounding.

**How do you ensure the sum is 1.0?** By construction at every layer, plus a
run-time check: each projection asserts `|ΣJ − 1| < 1e-12` and the POC
prints the actual residual per snapshot. No clamping, no coercion — if a
layer ever produced a non-distribution, the assert fires loudly (fail loud
beats phantom success).

**How is it stable?** Five properties, each demonstrable:

- **Determinism.** No RNG anywhere. World ticks are `fnv1a(question:t)`
  (Lane 1 law); the moth quantum is `fnv1a(receipt:k)`. Identical inputs →
  byte-identical receipts (POC runs the pipeline twice and diffs).
- **No zero odds — ever.** Every `s_m` is floored (`s̃_m = (s_m+ε)/(1+Nε)`,
  `ε=1e-9`) before the log. "Doubt stamped, not lowered": an agent every
  cell votes against keeps small-but-nonzero odds; the compression lane can
  always be selected. This also keeps `ln` finite — the pool cannot produce
  `−∞` or `NaN`.
- **Thin evidence → flat odds.** Pool weights sum to `Σw_m`; with empty
  ledgers every `w_m≈0`, so `L≈0` and `J→uniform`. The swarm starts fair
  and *earns* its skew — no bolted-on temperature schedule.
- **Bounded influence.** `w_m ∈ (0,1)`: no cell speaks with weight above 1,
  and `∂J/∂p_m` scales with `w_m`. A loud-but-empty cell cannot dominate;
  a rich ledger cannot be silenced. A one-tick perturbation of one cell
  moves `J` by a small L∞ distance (measured in the POC), not a jump.
- **Numerics.** Pooling happens in the log domain; the only exponentials
  are post-`max` subtraction (log-sum-exp) — no underflow for large `M`,
  no overflow for confident cells.

## 4. Why geometric pooling (and not linear)

Linear pooling (`J = Σ w_m s_m`) is democratic averaging: one confident
cell's sharp opinion is diluted by every silent cell, and agreement between
cells never sharpens anything. The swarm needs the opposite semantics —
cells are *independent evidence about the same question* ("who fires
next?"), and independent evidence compounds: that is the product of experts,
`J ∝ Π s̃_m^{w_m}` — the log-linear opinion pool (Genest & Zidek 1986, the
classic synthesis). Two cells agreeing that PINCH should fire raises PINCH's
odds multiplicatively; one lukewarm cell can soften but (via the ε-floor)
never zero out a consensus. Percentages stay literal: the pool output is
renormalized to Σ=1 and read directly as firing odds.

## 5. The moth quantum (selection = recorded collapse)

JEV never emits a definite token (exoj law) — it emits the **odds vector
plus its receipt**:

```text
receipt = sha256( canonical( [ cell heads…, round, J ] ) )
u       = fnv1a( canonical( [ receipt, draw_k ] ) ) mod 2³² / 2³²
fire    = the agent whose CDF bucket contains u
```

The draw is content-derived (fnv1a lineage), so the same history always
selects the same agent — but a different history, or the next draw index,
gives a fresh roll. Literal odds are verified statistically: from a frozen
mesh, 400 deterministic draws reproduce `J` within a few points (POC prints
projected vs empirical, max deviation).

## 6. What this does NOT do (L4)

- It does not **learn** the wiring. `W_m` is fixed, hand-written, and
  legible here. Learning `W_m` from (answer, fired, outcome) history is a
  later lane — this lane proves the mesh, not the plasticity.
- It does not do agent **mutation** (each agent proposing a successor
  design) or **compression** of non-selected agents. Those are adjacent
  swarm lanes; J1 only builds the projector they all hang off.
- It does not update cell ledgers from *firing outcomes* — the loop back
  from selection to evidence is Lane 3 territory (gates).
- Weights `w_m = n_eff/(n_eff+n₀)` are a deliberate first knob, not a
  derived optimality. Alternatives (certainty margin `p−LB95` from Lane 1)
  are drop-in; the pool does not care where weights come from.
- `ε=1e-9` floor is a safety floor, not a modeled prior. If an agent should
  carry real prior mass, that belongs in the wiring rows, not the floor.

## 7. When it fails (L5)

- **A wiring row with a zero-sum or malformed row** → `s_m` is not a
  distribution → the `Σs_m≈1` assert fails loudly at layer 3, naming the
  cell. Fix the wiring row; do not widen the assert.
- **All cells at empty ledgers** → `J` is uniform (by design, not by
  failure). If the swarm must act on priors, encode them in the wiring,
  not in fake ticks.
- **Replay mismatch** (receipt differs across runs) → some input escaped
  canonicalization (a set, a dict order, a float repr). Everything that
  enters `canonical()` must be sorted-key JSON with fixed-precision floats.
- **`k_m` changed after birth** — Lane 1 law: answer sets are fixed at cell
  birth. Changing them requires a new cell; the old ledger stays chained.

## 8. Receipts

- POC run: see `poc.py` output (this box, python3 stdlib only, no imports
  beyond stdlib + `../cell-internals/poc.py`).
- Commit + `git ls-remote` verbatim in the lane report.
- i2i ledger: booked to `zeroclaw-loop`, title
  `swarm J1 selection: one paragraph summary`.
