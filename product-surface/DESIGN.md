# TICKBOARD — the cells-as-ticks paradigm as a product surface

**Lane:** product-surface (ZeroClaw R&D, 2026-10-04) · **Status:** POC runs, receipted below

## The one-liner

**A wall of questions that answers itself from evidence.** You declare the
questions you're holding ("is prod healthy?", "is the agent behaving?").
Evidence ticks arrive, the board's probabilities evolve, and gates fire real
pipelines — slowly at first, then with muscle memory.

## The problem

Operators, analysts, and agent-supervisors hold dozens of yes/no questions
over time. The existing tools each fail one way:

| Tool | Fails how |
|---|---|
| Dashboards | Show *current state*, not accumulated belief. A blip and a collapse look identical for one frame. |
| Logs | Show events, never the probability the events add up to. |
| Static alert thresholds | Fire on any crossing — flap-page on noise, or wait for catastrophe. One sensitivity for all of history. |
| LLM copilots | Non-deterministic chat. No auditable belief state, no replay, no proof. |

What's missing is a surface where **belief is computed from recorded
evidence, actions fire on belief with enough margin, and the margin itself
learns from experience.** That is literally the paradigm.

## Who uses it

1. **First user: this fleet.** Casey + the supervisor agent watching build
   lanes (relay up? tests green? ledger reachable? agent drifting?). The
   dogfood loop in CHARTER.md is the customer-development channel.
2. **The wedge: on-call / agent-ops.** Anyone paged by flapping alerts, or
   not paged until it's too late, who wants the alerting threshold to have
   *learned* how much evidence this signal usually needs.
3. **Later: decision journals** (forecast calibration, vendor risk) — same
   primitive, different evidence sources.

## Paradigm → feature mapping (the whole point of this lane)

| Charter paradigm | TICKBOARD feature |
|---|---|
| Cells as probabilities recorded as ticks over time | A **Cell** = a question + an append-only tick ledger. `p(t)` = recency-weighted mean of tick values. No RNG anywhere: "noise" is fnv1a-derived from content (exoj `unitTable` lineage). |
| The cells' probabilities for the logic decompose | Probability decomposes into **level** `p(t)` and **volatility** `vol` (mean \|Δ\| of recent ticks) — what it says, and how much it's still churning. |
| Append-only data structure, no RNG (build direction 3) | Every event (declare/tick/fire) is a row in a **sha256-chained ledger** (canonical JSON + prev-hash, exoj `core.mjs` lineage). Tamper detection is in the selftest. |
| Gates firing pipelines | A **Gate** fires a **Pipeline** (real side effect) when `p` crosses a threshold *by enough margin*. |
| Muscle-memory-like reflexes; thresholds tighten from evidence | `margin_required(n) = base · k/(k+n)` — a newborn cell needs overwhelming evidence to act; each tick of history tightens the gate. Tiers map to pincher's engine: SLOW → MEDIUM → FAST. |
| Listener-cell veto (pincher lineage) | **Hysteresis**: after firing, the gate stays open until `p` recovers past the threshold. Flapping cells can't page you. |

## User flow (three verbs)

```
DECLARE  tickboard cell add relay.healthy "is the workers relay serving 2xx?"
         tickboard gate add relay.healthy below 0.50 → page-runbook
TICK     evidence sources append ticks (http-check, ci-run, ping, verdict-scan)
WATCH    tickboard watch   → the board: p(t), tick sparkline, vol, gate states
```

Declaring intents up front is the product's contract: the operator states
the question AND what should happen when the answer goes bad — then stops
staring at graphs. The board holds the questions so the human doesn't have to.

## What the POC proves (receipted, run 2026-10-04)

`demo.py` replays a deterministic 36-minute night shift over 4 cells.
Verified output (system python3, stdlib only, bit-identical ledger across
runs — sha256 `219acab6…fad33b`):

1. **A blip doesn't page.** `relay.healthy` takes one 0.44 tick at t+08.
   Aggregation holds p at 0.88 — no fire. A static threshold at 0.50 would
   have paged.
2. **Sustained evidence does.** The real degradation slides p down; the gate
   fires at **t+24, tier MEDIUM** (margin_required 0.109, p=0.359).
   `page-runbook` writes a real runbook line.
3. **Muscle memory is visible.** After recovery, re-degradation fires at
   **t+34, tier FAST** — same gate, *weaker* evidence (p=0.414 vs 0.359),
   ten minutes faster, because 34 ticks of history tightened the required
   margin to 0.084. The second reflex is faster than the first. That is the
   paradigm's core claim, demonstrated.
4. **Flap doesn't page.** `ledger.reachable` oscillates 0.85/0.25 all night
   (vol 0.60); its below-0.30 gate never fires.
5. **Peace of mind is a feature.** `tests.green` sits at p≈0.96 with an
   armed gate that never fires — the board shows you what *didn't* go wrong.
6. **The ledger is the proof.** 155 chained rows, `verify: OK`, tamper
   detection selftested. Deterministic replay: same input, same hash, always.

Honest design note: tier reflects *gate experience* (tick count), not prior
fires — `agent.drift`'s first fire is FAST because the cell earned 29 ticks
of evidence before crossing. Firing history vs evidence count as the
tightening driver is an open question (below).

## Why this is the thinnest surface

One screen, three verbs, no LLM in the loop, no server required. The core
interaction — *declare a question, watch belief accumulate, watch the gate
learn* — survives translation to a terminal, a web board, or a phone push.
Everything harder (live probes, web UI, agent handoff) is additive, not
structural:

- **v0.2 — live:** real probes (HTTP check on :7860, `npm test`, ledger
  ping) as tick sources. The scenario stream is already behind one function
  (`scenario_value`); swap it for probes.
- **v0.3 — web:** the board as a forge-portal gallery page (:7860 already
  serves JSONL receipts; the ledger file drops straight in).
- **v0.4 — muscle:** a fired FAST gate compiles to a
  `zeroclaw-reflex-spec/v1` file; pincher's `loadZeroclawSpecs` serves it
  sub-50ms. TICKBOARD becomes the *trainer*, pincher the *reflex executor* —
  the developmental-GAN loop closed into a product.

## Next research question (this lane)

**Reflex loosening.** Margins that only tighten are a one-way ratchet: after
a regime change (new deploy, new normal), a FAST gate overfires on evidence
the world has stopped producing. Muscle memory must decay. What evidence
schedule (time-decay of n? volatility-triggered widening? verdict feedback
from the judge half?) widens margins again without reintroducing flap? The
demo's `margin_required(n)` is one line — the loosening law is the next
increment.

## Run it

```
cd product-surface && python3 demo.py        # selftest + night-shift replay
python3 demo.py --quiet                      # single final frame
```

Receipts: `out/night-shift.ledger.jsonl` (sha-chained, 155 rows),
`out/runbook.log` (pipeline side effects). Both regenerate bit-identically
from a clean checkout.
