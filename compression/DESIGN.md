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
