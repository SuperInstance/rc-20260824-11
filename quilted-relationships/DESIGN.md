# Quilted Relationships — DESIGN.md (ZeroClaw Swarm Q2 / Lane S5, 2026-10-04)

Swarm law (Casey, via the architecture verdict): *agents are a collective with
**quilted relationships** — each with different context that learns to push and
pull with each other.* A quilt is a mesh, not a tree: no center, no hierarchy,
no single pipe. This lane answers: **what IS a relationship between two agents,
as a data structure — and how does it learn?**

## 1. Geometry, not message-passing

A relationship is an unordered pair {A, B} realized as **two directed edges**
(A→B, B→A). Each directed edge is a cell-like object with state:

```text
Edge(src -> dst):
  context_buffer : ordered list of {source_agent_id, doc_sha, compression_tier}
                   (oldest first — age desc, fnv1a tiebreak; append-mostly)
  cells          : push-novel?, pull-novel?, negotiate-hit?   (Lane-1 cells:
                   decayed pseudo-counts, Laplace-smoothed p, tick ledger)
  counters       : push/pull/negotiation successes and attempts (raw evidence)
```

The **shape** of an edge is the probability triple
`(p_push, p_pull, p_neg)` — its local curvature. Shape determines flow
direction: a confident edge pushes (source's content is probably novel to the
peer), an uncertain edge pulls (destination lacks half the source's buffer).
Nobody assigns roles; the geometry grows them. In the POC's final ledger the
mature A↔B edges sit at shape (0.87, 0.50, 0.13) while the bruised young B→C
edge rests at (0.19, 0.58, 0.39) — same mesh, different curvature, different
behavior. That is the quilt: **the relationship itself accumulates evidence
about its own usefulness and gates itself accordingly.**

## 2. The context_buffer (spec fields, ordering law)

Entries carry exactly the spec triple — `{source_agent_id, doc_sha,
compression_tier}` (K knowledge / D doubt / T trajectory, per Lane C1) — plus
an `age` for ordering and a `known_peer` mark. The buffer is a **ledger, not a
queue**: it only grows (POC requirement: buffers visibly grow, 5→18 entries on
A→B). Push takes the oldest eligible entry; `known_peer` marks are the edge's
private coverage map of *what the peer has already seen* — the memory that
kills redundant delivery.

## 3. The three motions

- **PUSH — gated by confidence.** The edge's push cell must say p(novel) ≥ θ
  (0.40), with a short warmup (first 3 attempts always fire — exploration).
  Confidence in *content* is the tier: **only K and T docs are pushed; doubts
  (D) are never pushed at anyone** — doubt stamped, not lowered. Doubts move
  only by negotiation or explicit pull.
- **PULL — gated by uncertainty.** When the destination lacks ≥ half of the
  source's buffer, it probes one fnv1a-selected entry. The probe is honest and
  blind: it can fetch a doc the destination already has (a redundant pull
  ticks "no" and still marks the map). Pulls may fetch D-tier — asking for
  someone's doubt is allowed; imposing yours is not.
- **NEGOTIATE — mutual proposal.** Both sides propose their oldest not-known
  doc; if the shas match, the doc is shared bidirectionally (both corpora
  guarantee it, both edges mark it, both tick success); if different, strict
  no-op. In practice negotiation is the **ancestor-reconciliation ceremony**:
  strangers discover shared cloth by independently proposing the same oldest
  thing. In the trace, A↔B reconciled its two origin *doubts* by match (tier
  D, cycles 1–2), and when agent C joined, B↔C performed the same rite
  (cycles 11–12) — that is how a child of A became legible to a stranger.

## 4. Learning — three mechanisms, one guarantee

1. **Mark-on-contact.** Every delivery — push, pull, or negotiation — marks
   the sha `known_peer` on that edge. A doc can be redundantly delivered **at
   most once per edge, ever** (POC CLAIM3, mesh-wide). The stranger tax is
   real but bounded: 2 ancestor docs per new direction, once.
2. **Idle decay (λ=0.85) = reflex loosening.** Old failures fade between
   ticks, so a gate bruised by early redundancy reopens as evidence ages
   (A→B: p_novel 0.18 after the ancestor tax → 0.88 by cycle 14). Gates can
   also *rest*: B→C stopped pushing at p_novel 0.17 (cycle 14) — the edge
   refusing to spam is the learning, not a failure of it.
3. **Counters.** Raw successes/attempts are kept beside the smoothed cells —
   the doubt about the doubt. Cells gate; counters testify.

## 5. Quilting: integrating a third agent (observed in the POC)

C joins at cycle 11 as a child of A (inherits the shared cloth; the parent
edge is birth-marked both ways — the gift is pre-known). Four cycles later:
C pulled 6 docs while its uncertainty over B's buffer drained 0.74 → 0.54;
C holds 6 A-docs and 4 B-docs; 3 C-docs climbed up to A; the mature A↔B
edges had **zero** redundant pushes in the whole era (CLAIM2); and edge
successes per cycle rose 2.00 (era 1, two agents) → 6.75 (era 2, three
agents, six edges) — more agents, more flow, no growth in waste (CLAIM5).
The mesh's integration choreography, as observed: *birth-marks first,
doubt-negotiation second, bounded ancestor tax third, pull-burst while
uncertain, push once confident.*

## 6. What this is NOT (honest limits)

- No adversarial peers: an agent that lies (offers docs it doesn't hold) is
  unmodeled. The sha-addressed buffer makes lying *detectable* (offer a sha,
  fail to produce the doc) but the POC has no punishment cell for it yet.
- Append-mostly forever: buffers grow unboundedly. Eviction is Lane C2's
  question (proof vs working set), not this lane's.
- No evidence pooling on negotiation: matched docs are identical by sha, so
  the match itself is the transfer. When both peers hold a doc but their
  *cells* for that question differ, negotiation should max-merge counts
  (never lower — two-ledgers law). Reserved as the next increment.
- Transit redundancy exists and is honest: C pushed A-lineage docs to B that
  B already had via its direct A edge (cycles 11–12). Multi-path delivery
  costs; the mark-on-contact bound keeps the cost once-per-doc-per-edge.

## 7. Next research question

**Should JEV's projector consume edge shapes?** A high-p_novel,
high-neg-hit edge is a trust gradient — the natural prior mass for "which
agent should fire next." Lane D1's normalize-with-floor already projects
turn-odds from cells; folding edge shape into that projection would make
trust *geometric* (curvature in the fabric) rather than a score kept by a
judge. Open: does shape-as-prior double-count evidence the turn-cells
already carry?

---
POC: `poc.py` (299 lines, stdlib, zero RNG — all world bits fnv1a).
Determinism receipt: TRACE FINGERPRINT `397b7b4eb552`, byte-identical on
rerun; six claims asserted in-process, fail-loud per charter law.
