# Compression — DESIGN.md (ZeroClaw Swarm Lane C1, 2026-10-04)

Swarm law (Casey, via verdict): *agents that don't fire get reduced in size,
summarized into documentation that others link to. Essential experiences
become knowledge.* And the two-ledgers law: **doubt is stamped, not lowered**
— trust is a stamp on a kept doubt, never a replacement of it.

This lane answers: **when an agent fails selection, what of its experience
survives compression — and in what form can other agents use it?**

## 1. What an agent is at freeze time

An agent is a set of **cells** (Lane 1: one question each, decayed
pseudo-counts, hash-chained tick ledger, `counts + n` = sufficient
statistic) plus **gates** (Lane 2: watch answer, threshold θ, LB95 firing
predicate). When JEV's dice pass the agent over, that state is frozen. The
raw state is big: every tick row, every chain hash, every gate probe. The
swarm cannot afford to keep every non-selected agent at full resolution.

## 2. The compression model — four tiers

Compression is **one more ledger operation**, not a deletion. The agent's
ledgers stop growing and emit a **summary document**. Tier by tier:

### Tier K — KNOWLEDGE (preserved, lossless under the model)

Per cell: `question, answers, counts, n, alpha, lam` — the sufficient
statistic. Under the multinomial + decay model the posterior is a *pure
projection* of exactly these fields: replaying the raw tick ledger re-derives
a byte-identical `dist()`. The POC asserts this equality. What the model
summarizes perfectly is kept perfectly.

Also preserved: the cell's **original chain head** — not to carry the ledger,
but to bind provenance. If the raw ledger is archived elsewhere, the summary
can still name it: *this statistic was earned under head `ab12…`*.

### Tier D — DOUBTS (preserved, stamped not lowered)

Every gate that never fired at freeze gets a **doubt stamp**:

```text
DoubtStamp { question, watch, p, LB95, theta, deficit = θ − LB, N_eff }
```

The stamp is exact. No rounding toward "it would probably have fired," no
promotion of a near-miss into a belief. The deficit is the open thread:
a new agent that links to this summary inherits a *number*, not a vibe —
"relay/alive was 0.07 short of firing at N_eff 14." Doubts are the
**reference points** other agents cite. A small-deficit doubt is
nearly-knowledge; the stamp keeps that difference honest forever.

### Tier T — TRAJECTORY (preserved, a 3-number sketch)

`p_first_half`, `p_second_half`, LB trend. Classifies each cell as
`converged | drifting | thin`. This is the honest flag for where the
sufficient-statistic model *does* lose information (non-stationarity,
order). If a cell drifted, the summary says so instead of silently
averaging the drift away.

### Tier P — PROOF (preserved, self-verifying)

The summary document is canonical JSON; its **ID is its own sha256**.
Content address ⇒ linkable ⇒ verifiable by anyone who holds the doc:
re-hash it, get the same ID. The ID is chained across cells' original
heads, so a summary cannot silently mix histories. NO VERIFIED SHA,
NO BELIEF — extended from ticks to summaries.

## 3. What is discarded

Raw tick rows, per-tick gate probes, interleavings — everything the
sufficient statistic already summarizes (Tier K), and everything whose loss
Tier T explicitly flags. Discard is honest: the trajectory verdict is the
receipt for what the model cannot carry. The raw ledger may be archived
(head-bound), but the swarm's working memory holds only the summary.

## 4. Linkability — how other agents use a summary

1. **Cite.** Any agent references `@C1:<id16>` plus a doubt coordinate
   (`question`, `watch`). Doubts are addressable, so a downstream agent can
   say "resolved doubt @C1:ab12… [relay/alive]" when its inherited gate
   finally fires — the doubt's life ends in a receipt, not in silence.
2. **Inherit.** A new agent constructs a cell whose genesis head **is the
   summary ID** and whose counts are seeded from Tier K. Provenance is
   structural: the child cell's chain grows out of the summary itself.
   Essential experience becomes knowledge, literally, as prior mass.
3. **Render.** The summary projects to a small human-readable doc (the
   compressed reflex-spec): one line per cell, doubts verbatim.

## 5. Why inheritance is the proof of the paradigm

If compression kept only "small size," it would be mere bookkeeping. The
claim is that the *essential experience* transfers: an agent that inherits
a compressed cell should reach a firing gate **faster** than a fresh agent
on the same world — because the doubt's evidence is prior mass now. The POC
measures both tick counts. Faster inheritance = compression preserved the
right thing. No speedup = compression kept bytes and lost the experience.

## 6. What this is NOT

- No summarization of *payloads/log text* — only of cell/gate state. Natural
  language compression is a different lane.
- No probabilistic sketching beyond the trajectory tier; no Bloom/count
  sketches (the sufficient statistic already is the sketch).
- No eviction policy yet — this lane compresses ONE non-selected agent;
  when summaries outnumber cells, an archive/decay policy for *summaries*
  becomes its own lane (C2 candidate).

## 7. Next research question

**Doubt resolution as a first-class event.** When an inheriting agent's gate
fires, the origin doubt should be *closed with a receipt* (summary ID cited,
tick count, world context) — and closed doubts are exactly the evidence a
JEV projector should use to raise a compressed agent's re-selection odds.
Open: should re-selection probability come from the doubt deficit
(δ-weighted), the trajectory verdict, or both?

---

# C2 — The registry problem (2026-10-04): when summaries outnumber cells

C1 compressed one non-selected agent. But the swarm keeps selecting *one*
agent per round and freezing the others — the summary registry grows
monotonically while live cells stay few. This lane answers the next
question: **when the registry is over capacity, which summaries are
evicted?**

## 8. The criterion: evictability = replaceability, not rank

Not all summaries are equally useful, but "useful" has two axes that do
not correlate:

- **heat** — how often a summary is inherited/cited (access count,
  recency). Hot summaries speed up the *current* workload.
- **irreplaceability** — whether any other summary holds the same doubt
  coordinates. A near-miss doubt on a rarely-visited world may exist in
  exactly one summary (C1's warning). Evicting it does not lose bytes; it
  loses the only evidence that anyone ever probed that edge.

The C2 law: **the accessibility score may order evictions only among the
replaceable.** A summary is evictable iff, after the whole eviction batch,
every doubt coordinate it holds keeps ≥1 holder elsewhere in the registry
(the *uniqueness floor* — batch-aware, because two holders of the same
coordinate must not die to the same batch). Eviction is **demotion from
working memory, not deletion**: the content-addressed doc stays in the
archive (Tier P; house archive law), but the swarm's hot memory no longer
inherits from it and JEV no longer projects from it.

### The accessibility score (among the replaceable)

```
score(s) = 0.6 · norm( uses(s) · γ^age(s) )  +  0.4 · ( 1 − maxsim(s, rest) )
```

`uses·γ^age` is classic heat (γ=0.75 per cycle); `1−maxsim` rewards
summaries whose question-set + doubt-set no other summary covers. Evict
lowest score first. When pressure exceeds the floor (not observed at 4.8×
oversubscription), breaches are *forced evictions*, counted and logged —
never silent.

## 9. The POC (`eviction_policy.py` + `compare_eviction.py`)

Deterministic world (fnv1a lineage, no RNG module anywhere — asserted at
import): 11 questions — 6 common worlds (rates 0.65–0.90, many watchers)
and 5 rare/edge worlds (`listener/veto?` is C1's drift world 0.20→0.80 at
tick 24; `ghost/echo?` rate 0.15; etc.). 145 agents → 145 summaries
(100 seed + 45 arrivals over 9 rounds), each agent 2–4 cells, 32 ticks,
C1-format compression. Registry capacity 30 (4.8× oversubscription).
Per cycle: admit arrivals → 24 future-agent tasks (82% common / 18% rare
worlds, θ∈[0.50,0.74]) → evict to capacity. Every task runs BOTH a fresh
cell and the registry inheritor on the same world stream (fair
counterfactual). Four policies: `full` (never evict — control), `access`
(uses×recency only), `diversity` (greedy max-redundancy only), `hybrid`
(uniqueness floor + score). All four re-run bit-identically (receipts).

Coordinate anatomy (the thing eviction gambles with): 10 doubt coordinates
ever stamped; 6 near-miss (deficit<0.12). Scarcity ≠ question rarity:
`pinch/match?` has 48 stamps, `ghost/echo?` has 2, and the sharpest C1
case exists in the wild — `tail/overflow?`, a *rare world* whose
*near-miss* stamp (deficit 0.0209) has exactly 2 holders ever.

## 10. Results (240 tasks × 10 cycles, capacity 30 of 145)

| policy | size | hits | mean ticks | saved | regr | cov% | near% | rareQ | dark | lost | forced |
|---|---|---|---|---|---|---|---|---|---|---|---|
| full (control) | 145 | 240 | 38.99 | 1986 | 0 | 100 | 100 | 5/5 | 0 | 0 | 0 |
| access | 30 | 240 | 38.99 | 1986 | 0 | 100 | 100 | 5/5 | **1** | 0 | 0 |
| diversity | 30 | 240 | 38.99 | 1986 | 0 | **90** | 100 | **4/5** | **5** | **2** | 0 |
| hybrid | 30 | 240 | 38.99 | 1986 | 0 | 100 | 100 | 5/5 | **0** | 0 | 0 |

`dark` = coord-rounds the registry held ZERO stamps for a coordinate that
exists in history; `lost` = coordinates destroyed and never recovered.

Receipts: full=a89458fc97e57806 access=e3cd6ab017d65fae
diversity=0320da6c83dd2b7a hybrid=1a1bd0be6bd54b8e (replay bit-identical).

### Findings

1. **Speed metrics cannot see the difference — that IS the result.** All
   four policies post identical ticks/hits/saved. Eviction damage lives
   entirely in (c): coordinate darkness. An access-scored registry that
   "looks healthy" on every speed metric can still be eating its own
   reference points.
2. **Access-based eviction goes dark exactly where traffic is absent.**
   `ghost/echo?` (2 holders ever, no warm-up traffic) was destroyed at the
   cull — 1 dark round, recovered only because an arrival happened to
   re-stamp it (lottery, not policy). The `tail/overflow?` near-miss
   survived access by the same luck, not by protection.
3. **Diversity-as-similarity is not diversity-as-coverage.** The greedy
   max-redundancy policy destroyed `ghost/echo?` *permanently* (both
   holders, in separate batches — nothing constrains coverage) and
   temporarily zeroed `cargo/intact?`, a NEAR-MISS coordinate with 13
   stamps, in one batch. Similarity says "these two summaries cover each
   other"; coverage says "after evicting, is the coordinate still held?"
   The second question is the one that matters, and it needs a floor, not
   a score.
4. **The floor is free.** Hybrid = control speed at 30/145 the size, 100%
   coordinate coverage, 0 dark rounds, 0 forced breaches. Protecting last
   holders cost nothing measurable under this workload.
5. **Re-earning is a floor price, not a true cost.** The destroyed
   `ghost/echo?` stamp (n_eff=32, LB95=0.0848) costs a fresh agent 34
   ticks to re-derive — *before* counting the JEV selection odds of a rare
   world ever being assigned again. Lost near-miss references on rare
   worlds are effectively unrecoverable in working memory.

### Mid-POC lesson (recorded for the fleet)

Inheritance first ranked candidate summaries by `p̂` (point estimate).
That let a *smaller* registry beat the unbounded control on ticks —
because a high-p̂/low-depth summary outranked a deeper one. Evidence
depth is what fires gates: ranking is now by the summary cell's **LB95**
(re-derived from Tier K counts; no replay needed — the sufficient
statistic IS the posterior). The control is now a true upper bound
(asserted).

## 11. Open questions (C3 candidates)

- **Archive-vs-working-memory pricing.** Eviction here models hot memory
  only; archived docs remain linkable (Tier P). What is the recall cost —
  should JEV be able to project re-selection odds onto archived
  summaries, and what re-admission evidence (a new task hitting a dark
  coordinate) promotes archive → working memory?
- **Doubt resolution closes the loop.** C1 §7: when an inheritor's gate
  fires, the origin doubt closes with a receipt. Closed doubts could
  *deprotect* their coordinates (reference no longer needed) — the
  uniqueness floor should shrink as doubts resolve, not just as holders
  die.
- **Capacity from JEV.** Who sets capacity? A candidate: the floor of the
  JEV projection — summaries below the exploration floor in firing-odds
  space are eviction candidates by the same law that governs agents.

## 12. Twin lane (independent confirmation)

A parallel C2 dispatch built the same lane independently
(`eviction_policy.c2-rank-unique.py`, results in `RESULTS-C2-eviction.md`;
50 summaries / 48 coordinates / single-shot eviction). Its world and mine
differ, its hybrid was not batch-floored — and it still lands on the same
criterion from the other side: sole-reference doubts are what eviction
must not destroy (its access/diversity policies lost 6 critical
coordinates each; its uniqueness-protected hybrid lost 0). Two
implementations, one law. The write-race between the two lanes is
preserved in git history (see `de6f82b`).
