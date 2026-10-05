# agent-mutation — DESIGN.md (ZeroClaw Swarm Lane M1, 2026-10-04)

Charter target (VERDICTS.md 16:52, Casey's swarm architecture): *"Agent
mutation mid-process: each agent generates at least one new agent design that
might be better for the next step."* MicroMoth = simulation before execution;
non-selected agents compress into documentation ("doubt stamped, not
lowered"). This lane answers the three M1 questions with a running agent
(`poc.py`, stdlib python3, deterministic, exit 0, receipt printed).

## 1. Q1 — What a "new agent design" is, as a data structure

**An agent design is a genome**: one canonical, content-addressed JSON object
holding everything needed to instantiate the agent. Lanes 1–2 authored the
circuit in code; M1 promotes it to a first-class, hash-identified DESIGN:

```text
AgentGenome (zeroclaw-agent-genome/v1)
  cells: [ { name, question, lam } ]            # Lane-1 atoms: a question +
                                                # its decay (read-out policy)
  gates: [ { name, src, dst, kind,              # Lane-2 wiring: excite /
             theta_base, R, lam_adapt, rho } ]  #   inhibit / sign + threshold,
                                                #   refractory, adaptation
  identity = "agnt-" + sha256(canonical(genome))[:12]
```

The design's *name IS its hash* — two designs are the same design iff their
canonical forms hash equal. Runtime state (decayed counts, adapted θ, fire
tallies) is **earned from the world**, never part of the genome; it is what
the genome is *evaluated against*. A cell's raw tick ledger is truth; `lam`
is a read-out policy over it (Lane 1 law), so a lam-mutation re-tallies the
**same ledger** (`rebuild_from_ledger`) — history is never rewritten.

One modeling law was learned the hard way (fail-loud caught it): **decay
must advance with time, not with input.** A cell that stops receiving ticks
but never forgets is exactly the frozen-confidence pathology this lane
mutates against — the parent agent's C2 sat at p=0.93 for 40+ ticks after
the world flipped, committing on a dead memory.

## 2. Q2 — How the new design differs from the current agent

A **mutation operator is a pure function**: `genome × evidence → (genome',
Δ)`. Evidence is a **diagnostic over the agent's own tick ledgers** — the
mutation source is *what the agent lived*, never RNG (fleet law; entropy is
content-derived, fnv1a lineage). No triggered diagnostic ⇒ no mutation
(an operator that fires without evidence is dishonest by construction).

| operator | trigger (diagnostic) | gene edit | rationale |
|---|---|---|---|
| `forget-widening` | sense drift: \|overall_p − recent_p\| ≥ 0.20 | `lam ← 0.80` on sense cell + descendants, **coupled** `rho ← 0.05` on gates reading them | the world changed; forget it — but gates must re-open as fast as memory evaporates |
| `habituate` | gate over-fires (fires ≥ 12, utilization ≥ 0.30) | `theta_base += 0.10` | Lane-2 runtime habituation made hereditable |
| `sprout-feedback` | terminal cell p ≥ 0.80, no existing edge | `+gate C3 --inhibit(0.75, R=8)--> C1` | a second self-damping loop, grown from confidence |

**Uniqueness is measured twice, and both must hold:**

1. **Structural**: symmetric difference of canonical gene sets ≥ 1 (each
   changed gene counts out+in), and genome hashes differ.
2. **Behavioral**: MicroMoth simulation — the candidate is cloned *from the
   live state* (same ledgers, same adapted θ) and run on the SAME
   deterministic future stream. Fire-sets must diverge (Jaccard distance
   > 0) and mission score must differ. Different bytes that behave
   identically are not a new agent.

**The coupling lesson (the run's real finding):** the first forget-widening
mutated `lam` alone and was **falsified by a counterfactual good-regime
probe** — the child stopped committing entirely. Cause: G1's habituated θ
fired so sparsely that no forgetful cell could re-accumulate evidence.
Forgetting without loosening is lobotomy. The operator now mutates the
**coupled pair** (lam down + rho up), and the probe is a standing invariant:
*a quiet child must not be a dead child* (winner must still commit ≥ 1 time
in a forced good regime).

## 3. Q3 — How the mutation is recorded

Three layers, each append-only:

1. **Local mutation ledger** (`out/mutations.jsonl`) — every candidate,
   selected or not, one row each, sha256-chained
   (`row_sha = sha256(canonical([prev_row_sha, row]))`, Lane-1 lineage) and
   replay-verified in-run. Selected rows carry the sim score and delta;
   **stamped losers carry `why_not`** — doubt stamped, not lowered. Losers
   are compressed to documentation, never deleted.
2. **`zeroclaw-reflex-spec/v1`** (`out/specs/<id>.json`) — the winning child
   encoded in the format pincher already consumes
   (`loadZeroclawSpecs`/`parseZeroclawSpec`, the verified Run-1 seam):
   `payload.content` = canonical child genome (DATA, never executed as
   code), `payload.output_sha256` = its sha, `context_sha256` = sha of the
   parent's live state at mutation time (cache-integrity: the proposal is
   only valid for the state that earned it), `cites[]` = the evidence
   strings, `provenance.parentOrder` = parent genome id (**the lineage
   back-pointer**).
3. **i2i ledger** (`books_to: zeroclaw-loop`) — the fleet-visible receipt,
   booked from the shell after the run (ledger unreachability must never
   fail an experiment).

Receipts from the actual run (2026-10-04, this box):

- Parent `agnt-e07272df81ec` ran live t=1..140; world flipped good→bad at
  t=100. Diagnostics at t=140: sense drift 0.361 (overall 0.543 vs recent
  0.182), terminal p 0.962 → 2 candidates triggered (habituate honestly
  no-op'd: its evidence bar wasn't met).
- MicroMoth window t=141..200: parent **10 bad commits, score −10** (frozen
  memory keeps voting commit in a bad world); `forget-widening` child
  `agnt-d297db6869c1` **0 bad commits, score 0**, G3 fire-set Jaccard
  distance 1.000, gene distance 12; `sprout-feedback` tied the parent
  (−10) — stamped with why-not.
- Counterfactual good-regime probe: winner still commits (1 vs parent's 6 —
  the honest price of forgetting is re-accumulation latency).
- Mutation ledger: 2 chained rows, replay-verified, head `a571755d09aa…`.
- Spec `mut-140-agnt-d297db6869c` parsed by **pincher's real
  `parseZeroclawSpec`** (tsx, quilt-pincher@src): `PINCHER-PARSE-OK`, child
  genome decoded (3 cells, 3 gates) from the payload.
- Run receipt `6cc55da3…`, exit 0. Deterministic: re-runs are bit-identical.

## 4. Mid-process semantics (what "mid-process" means here)

The parent keeps its live ledger untouched: mutation happens **at** t_mid
**from** the live state, candidates are evaluated in **simulation cloned
from that state**, and only the winning *design* (not the runtime) is
emitted. The child would be instantiated for the next step by whoever wins
selection — in the full swarm that is JEV's probability projection over
"which agent runs next" (percentages as literal firing odds, the moth
quantum). M1 deliberately stops at *propose + encode + record*: **selection
by simulation is the preview; stochastic selection is M2.**

## 5. What this is NOT (scope fence)

- No stochastic selection (moth quantum / JEV odds) — M2.
- No cross-agent mating / recombination — single-parent mutation only.
- One sense cell, one mission; operators are hand-seeded heuristics
  (Hebbian co-fire sprouting, where wiring grows from tick correlation, is
  the natural next operator — Lane 2's open question still stands).
- The mission score (commit votes track the true regime) is authored; no
  general reward discovery.

## 6. Next research question

**Lineage under selection:** the spec's `provenance.parentOrder` now forms a
genome family tree. When JEV's dice (M2) actually pick agents, does the
chain of coupled `lam+rho` mutations drift toward a *species* (a stable
parameter band that survives regime flips), or does each flip reset the
lineage? Concretely: run the mutated child as the next step's live agent,
flip the world again, and measure whether the second-generation mutation is
smaller (pre-adapted) — the first test of whether mutation accumulates
wisdom or just chases the last flip.

## 7. M2 — Lineage under selection: the answer (`lineage_evolution.py`)

**Question (from §6):** in a generational lineage where the world flips,
does accumulated mutation wisdom compound or reset?

**Setup.** World: good t=1..50 | bad t=51..100 | good t=101..150. Gen-0 =
fresh v0; at each boundary an onset probe (clone stepped 10 ticks into the
NEW regime) measures sense-cell drift `d = |overall_p − recent_p|`; the
coupled operator mutates `lam` down + `rho` up together, monotone-clamped
to a drift-proportional band (widen never tightens). Three tracks on the
same deterministic ticks: **LINEAGE** (child inherits ledgers, re-tallied
under the new lam), **FRESH-G** (lineage genome, fresh runtime — isolates
genome from ledger), **INDEPENDENT** (fresh v0 each generation).

**Results** (run receipt `41378f8a5e465fa9`, exit 0, cross-process
byte-identical):

- mutation_size (L1 from parent): **0.78 → 0.027** — the second flip needed
  a 29× smaller mutation. The lineage pre-adapted into the forgetful band.
- Every flip-sensed mutation beat the unmutated parent on the child's own
  window (flip 1: −8 → 0; flip 2: +2 → +3). Selection held both times.
- mutation_accuracy (single moves that help alone): **1/6 both flips**.
  Only the sense-cell lam move helps by itself; the coupled set wins
  JOINTLY. Per-move counterfactuals are a lower bound on coupled fitness —
  the coupling is real pleiotropy, not six independent bets.
- But: all-window totals **lineage +12 < fresh-genome +11 < independent
  +18**. On the return to a good world (gen-2): lineage +3, fresh-genome
  +2, fresh v0 +9. The flip-specialist genome (lam≈0.756) pays a standing
  tax in stable regimes — v0's frozen memory (lam=1.0) is optimal when the
  world never contradicts you, and a fresh agent has no baggage to decay.

**Answer: compounding and reset happen in different layers.** Genome
wisdom compounds — mutations shrink toward an asymptotic band and each one
beats the do-nothing alternative. Ledger wisdom resets worse — inherited
posterior baggage taxes re-entry. And a fresh reset wins outright when
flips are rare relative to the window: lineages are flip-specialists.
Lineage selection should win when flips are frequent; resets win when the
world is long-stable. The unexplored middle is the `stable:tighten` branch
(re-tighten lam toward v0 when the world reads stable) — never triggered by
this schedule (drifts 0.236/0.244 stayed above the 0.20 trigger); a
long-horizon schedule with stable gaps between flips is the natural M3.
Sensitivity note: both boundary drifts sit barely above trigger — the
G2-inhibit feedback keeps overall_p honest (0.600/0.654), which is what
keeps flips detectable after the first widening; trigger 0.20 is
load-bearing.

Artifacts: `agent-mutation/lineage_evolution.py` (299 lines, stdlib only,
no RNG), run receipt printed in-trace, second-run determinism asserted
in-file.
