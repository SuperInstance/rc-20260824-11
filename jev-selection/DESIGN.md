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

---

# J2 — WIRING LEARNED FROM THE SELECTION-OUTCOME LOOP (2026-10-04)

**Question (swarm lane J2):** *Instead of hand-writing JEV wiring W_m,
can it be learned from the loop itself — the same cell-update mechanism
Lane 1 already trusts?*

## 1. The answer in one paragraph

Yes. The wiring row `W_m(y)` is a **Dirichlet posterior over a
|answers|×|agents| contingency table**: `c[y][a]` counts the ticks where
cell m answered `y` and the correct agent was `a`. The update is the Lane-1
mechanism verbatim — decay all counts by `λ`, land the observation, project
the posterior mean `(c+α)/(Σc+Nα)` on demand. Supervision is the loop: each
tick the cells observe the world, the mesh pools the learned rows into
firing odds, the moth fires one agent, and the outcome (the TRUE correct
agent) lands in every cell's table. No hand ever writes a row.

## 2. The world (so "correct" means something)

Hidden state `z_t ∈ {0,1,2}` per tick; cell m observes z through its own
confusion matrix (0.80 / 0.70 / 0.55 main mass — cells differ in
informativeness); the correct agent is `g(z)`. The **Bayes-optimal wiring**
`row*(y) = P(g(z)=a | y_m=y)` is closed-form from the confusion matrix. It
gives (a) the ceiling — the mesh run with ideal rows — and (b) the
ground-truth target the learned rows must approach. The learner starts from
"random" wiring: fnv1a noise pseudo-counts (deterministic, replay-stable,
uninformative). A frozen copy of that noise run is the no-learning baseline.

## 3. Measured results (100 ticks, N=5, M=3, |answers|=3)

- **Rows converge onto Bayes:** learned rows ≈ 0.68–0.78 on the dominant
  agent vs ideal 0.80; never-correct agents (SENSE, COMPRESS) decay to
  0.01–0.03 — doubted, never zeroed.
- **Mesh converges:** mean L∞(Ĵ, J_ideal) over the last window falls
  0.225 → 0.051.
- **Selection quality** (argmax Ĵ == correct, trailing window): baseline
  frozen noise 0%, learned 65%, Bayes ceiling 75% — the loop earns 87% of
  the ceiling; 90%-of-ceiling crossing at t=88.
- **Literal odds hold under a moving mesh:** per-agent fired frequencies
  match mean Ĵ mass within 0.0171 (J1's law, now verified on learned rows).
- **Soft-evidence honesty:** mean Ĵ mass on the correct agent is ~29%, so
  moth draws hit the correct agent ~20% cumulative — draws sample the odds
  they are given; argmax quality is the selection claim, draws are honest
  collapses of soft evidence. (Flat Ĵ is the N0=8 whisper-while-young
  design doing its job on n_eff≈2.5 reactive cells; sharpening the pool is
  a later knob, not a wiring problem.)
- **Determinism:** two full runs byte-identical in-process AND across
  processes (full-output sha256 identical). No RNG anywhere — states,
  observations, init noise, moth draws are all fnv1a content.

## 4. What this does NOT do (L4)

- No outcome feedback into the *cell ledgers* (Lane 3 gates territory) —
  only the wiring tables consume outcomes.
- No credit assignment beyond the binary "who was correct" — no delayed
  reward, no per-agent latency modeling.
- The correct-agent oracle is an oracle; a real swarm replaces it with
  downstream verification (Lane 2 mutants carrying falsifiable claims are
  the natural source).
- λ_w=0.99, α_w=0.25 are first knobs, not tuned optima.

## 5. J2 receipts

- POC: `wiring_learn.py` (271 lines, stdlib + Lane-1 cells imported,
  no RNG). Run: `python3 jev-selection/wiring_learn.py` → ALL CHECKS PASS.
- Cross-process replay: full stdout sha256 identical across runs.
- i2i ledger: booked to `zeroclaw-loop`, title
  `swarm J2 wiring-learn: wiring rows are Dirichlet posteriors over the
  selection-outcome loop; learned mesh reaches 87% of the Bayes ceiling`.

---

# Lane D2 — the dice roll, deepened (B-run, 2026-10-04)

**Question (swarm D2):** *J1 fixed the moth quantum as one fnv1a draw over
the sha-receipted odds vector. What other sampling strategies exist for the
dice roll? Is fnv1a sufficient? What about temperature scaling? Sampling
multiple times? Does the dice strategy matter for long-term swarm health?*

Runnable proof: `dice_variants_deep.py` (this box, stdlib only, imports J1's
`poc.py` — the projector is used, not re-implemented). A sibling A-run
(`dice_variants.py`) benchmarks the same variant families on abstract N=10
truths; this B-run plugs them into the real J1 mesh and audits the entropy
source itself. Both runs are kept distinct — no clobbering (fleet law).

## 1. Two laws, earned by measurement (not asserted)

**D2-1 — RECEIPT WHAT YOU ROLL.** Any tilt (temperature, diversity, order
statistics) enters through an *effective distribution* `J_eff` that is
content-addressed alongside JEV's pure projection: the draw targets
`sha([rcpt, strategy, J_eff])`. JEV's odds stay literal; when the dice tilt,
the tilt is visible in the receipt. A strategy with a hidden tilt is a
strategy that lies about its odds.

**D2-2 — EVERY DIE GETS ITS OWN SHA RECEIPT.** The audit (§2) found J1's
k-sweep pattern `fnv1a(receipt:k)` serially correlated (lag-1 ≈ **+0.30**,
chi² 33.4 vs crit 30.6 at α=0.01). fnv1a over sha-preprocessed die content is
clean (chi² 10.1, lag-1 ≈ −0.02). This is not a J1 bug — J1's live pattern
draws k=1 against a fresh per-round receipt and was never exposed — it is an
edge condition: any multi-draw, k-sweep, or rejection loop must give each die
its own sha receipt before the fnv1a mix step.

## 2. Entropy audit (section [A] of the POC, 4096 draws each)

| stream | chi² (df15, α=.01 → crit 30.58) | lag-1 r | verdict |
|---|---|---|---|
| `fnv1a(receipt:k)` — J1 k-sweep | 33.38 | **+0.303** | correlated — D2-2 |
| `fnv1a(str(k))` — raw ints | **192.79** | **+0.912** | never hash un-hashed content |
| `die_receipt(k)` = fnv1a(sha(…)) | 10.07 | −0.020 | clean — D2 dice |
| CDF walk @ uniform J (df4 → 13.28) | 2.13 | — | walk itself unbiased |

**fnv1a is sufficient** as the final mix step over sha-receipted content —
its 32-bit output is uniform and uncorrelated when the input is already
well-mixed. It is not sufficient as a hash of low-entropy content: the raw-int
stream is the cautionary receipt (chi² 193, r 0.91 — consecutive integers
produce correlated draws through fnv1a's weak avalanche).

## 3. The four families (section [B], frozen J1 mesh t=20, effective odds)

| strategy | SENSE | PINCH | RELAY | MOLT | COMP | semantics |
|---|---|---|---|---|---|---|
| single (J) | 34.3 | 17.1 | 32.9 | 5.6 | 10.0 | literal odds — the contract |
| T=0.5 | 43.8 | 10.9 | 40.4 | 1.2 | 3.8 | sharpen (exploit) |
| T=2.0 | 27.5 | 19.4 | 27.0 | 11.2 | 14.9 | flatten (explore) |
| best2 | 56.9 | 8.3 | 32.4 | 0.3 | 2.1 | order-statistics bias |
| best3 | 71.7 | 3.1 | 24.8 | 0.0 | 0.4 | stronger bias |
| div(λ), cold ledger | = J | = J | = J | = J | = J | no history → no tilt |

Four proofs, all receipted in the run output:

- **Temperature ≡ pool-weight scaling.** `J^(1/T) ∝ Π s̃_m^(w_m/T)`: scaling
  the dice temperature is *identically* scaling every cell's vote weight by
  1/T (verified: max|Δ| ≈ 7e-10, two float paths). The pool already owns an
  organic temperature schedule — thin evidence → flat odds — so a bolted-on T
  duplicates a knob the mesh has. T is only meaningful as an explicit
  exploit/explore override, and then D2-1 applies: receipt the tilted odds.
- **best-of-K is exact and enumerable.** Effective policy by enumeration over
  N^K tuples, cross-checked against the closed form for K=2
  (P(a) = 1−(1−J_a)² − 2·J_a·Σ_{J_b>J_a} J_b, agreement 1.1e-16); 4000
  empirical draws match the exact policy within 0.5pt.
- **Rejection sampling ≡ direct sampling** for finite normalized targets
  (2000 accepted draws vs direct J_T: 1.1pt; acceptance rate 0.519 vs theory
  1/M = 0.504). It earns its keep only when the target can't be normalized —
  ours always can. No role at this dice; documented closed.
- **Diversity tilt is bounded.** `tilt_a = 1 + λ(1 − T_a/max T)` over the
  decayed turn-ledger (the D1 turn-cell, minimal form; γ=0.97 ≈ 23-round
  memory). A starved agent's odds never exceed (1+λ)× its J odds; a cold
  ledger leaves J untouched (the swarm starts fair, same as J1's cold start).

## 4. Long-term health (section [C], 400 rounds × 7 strategies × 3 regimes)

Three regimes: **stationary** (frozen warm mesh), **skew stress**
(hand-authored J = 62/16/10/7/5 — one dominant lane), **world flip**
(decisive regime change at round 200). Key receipts:

- **single** holds the contract everywhere: fidelity ≤ 2.7pt, flip recovery
  in one window (50 rounds). A pure random draw is *responsive* — it never
  fights a world change.
- **Sharpening starves tails — measured.** Under skew: T=0.5 takes the 5%
  agent to 0.0% (400-round starvation), best3 to 0.2%, best2 to 0.2%.
  In the stationary mesh, best3 fires the 5.6% lane **zero times in 400
  rounds**. Order-statistics bias is silently lethal to tail lanes — this is
  the strongest anti-best-of-K receipt in the lane.
- **div3 is the starvation guardrail**: worst tail gap 67 → 29 rounds (57%
  cut) under skew, flip recovery still 50 rounds, fidelity cost paid openly
  (24pt vs J — the price of welfare). div1 is gentler (gap 40, 15pt).
- **Flattening (T=2.0) buys coverage at fidelity's expense** (skew: tail at
  11% vs 5% projected, 24pt off) — the same trade as div but with no ledger,
  no bound, and no memory of *who* was starved. Diversity tilt dominates
  temperature-flattening for the explore direction: it spends the budget
  where the starvation actually happened.
- **Sharpening direction** (T<1) is dominated by best-of-K, which achieves
  the same effect without touching the receipted distribution J (draws are
  always fair samples of J; only selection biases). Both starve tails; the
  table quantifies by how much.

## 5. Answer to the key question

Does the dice-roll strategy matter for long-term swarm health? **Yes — at
the tails, not at the top.** Every strategy eventually fires the dominant
lanes; they differ violently on the 5% lanes (0.0%–11.5% realized under the
same skew) and on starvation gaps (29–400 rounds). The single fnv1a draw is
the right *default* — it is the only strategy where percentages stay literal
(fidelity 2.2pt) and adaptation is never delayed. The principled amendment
is bounded diversity (div-λ) as an explicit, receipted welfare guardrail
against tail starvation; sharpening (T<1, best-of-K) belongs only in
deliberate exploit windows, never as a standing dice, because it silently
amputates tail lanes — and in this swarm, tail lanes are the compression and
mutation reflexes the charter depends on.

## 6. What this does NOT do (L4)

- λ is hand-set (1 and 3 measured), not learned from outcomes. Learning λ —
  or promoting the turn-ledger to a full Lane-1 cell with its own question
  ("who is starving?") and gate — is D-lane follow-up.
- The turn-ledger decays but does not chain (no sha chain yet); it is a
  counter, not proof. Promotion to a chained cell is trivial by Lane-1 law.
- Adaptive temperature (annealed by mesh confidence) unexplored; §3's
  equivalence says it would be redundant with pool weights anyway.
- best-of-K receipts the *policy* but selection is post-hoc; a "dice that
  audits itself" (empirical vs exact policy drift alarm) is future work.

## 7. When it fails (L5)

- **λ unbounded or γ→1**: tilt converges to round-robin regardless of J —
  the swarm stops listening to evidence. λ ≤ 3 and γ = 0.97 kept the
  fidelity cost ≤ 24pt in the stress regimes; beyond that, re-measure.
- **Any die without its own sha receipt** (D2-2 violation): draws correlate
  (r ≈ +0.30 measured), statistical tests drift, best-of-K silently degrades
  toward single-draw. The audit section exists to catch exactly this.
- **Tilt without receipt** (D2-1 violation): the receipted J and the rolled
  distribution diverge — the swarm believes one odds vector and executes
  another. Fail loud: compare receipt vs draw distribution, not just J.

## 8. Receipts

- POC run: `dice_variants_deep.py` output (ALL CHECKS PASS, determinism:
  two in-process runs byte-identical, output sha 0b5fe6fb0ca89edb…).
- Commit + `git ls-remote` verbatim in the lane report.
- i2i ledger: booked to `zeroclaw-loop`.
