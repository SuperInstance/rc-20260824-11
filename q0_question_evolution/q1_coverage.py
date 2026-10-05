#!/usr/bin/env python3
"""
Q1: Answer-Space Coverage Preservation under Q0 topology changes
Deterministic, no RNG, stdlib only. Follow-up to Q0 verdict (ac03bd3).

Claim under test (honest, falsifiable):
  When questions MERGE or SPLIT, is the answer space they cover preserved?

Two strategies compared:
  NAIVE    - each question's answer footprint is regenerated from its own
             text/sha (as Q0 POC implies). Splitting re-derives footprints
             from the new sub-question texts; merging derives from merged text.
  INHERITED- footprints are carried explicitly: a merge inherits the UNION of
             its inputs' footprints; a split's parts partition the parent's
             footprint.

Ground truth: a fixed universe of answer facts (cells). Each original
question's footprint is a deterministic fnv1a-derived subset. Coverage of the
whole question space = union of all live footprints. We report:
  - preservation ratio = |new_union ∩ old_union| / |old_union|
  - lost facts (per operator), gained (novel) facts
Exit code 0 only if INHERITED preserves 100% and NAIVE measurably loses.
"""

import hashlib
import sys

FNV1A_OFFSET = 0xcbf29ce484222325
FNV1A_PRIME = 0x00000100000001B3


def fnv1a(data: bytes) -> int:
    h = FNV1A_OFFSET
    for b in data:
        h = (h ^ b) * FNV1A_PRIME & 0xFFFFFFFFFFFFFFFF
    return h


FACTS = 120  # ground-truth answer universe size


def footprint_from_text(text: str, max_cells: int = 24) -> frozenset:
    """Deterministic answer footprint: fnv1a stream over the question text."""
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        h = fnv1a(f"{text}#{salt}".encode())
        cells.add(h % FACTS)
        salt += 1
    return frozenset(cells)


class Q:
    __slots__ = ("text", "family", "sha", "fp", "origin")

    def __init__(self, text, family, fp, origin):
        self.text = text
        self.family = family
        self.sha = hashlib.sha256(text.encode()).hexdigest()[:12]
        self.fp = frozenset(fp)
        self.origin = origin  # "original" | "merged" | "split"

    def __repr__(self):
        return f"<{self.origin}:{self.sha}:{len(self.fp)}fp>"


def make_originals():
    specs = [
        ("How does protein folding work?", "A"),
        ("How does protein structure prediction work?", "A"),
        ("How does gene expression regulation work?", "A"),
        ("What is the optimal learning rate?", "B"),
        ("What is the best architecture?", "B"),
        ("Should we use GANs?", "C"),
        ("Should we fine-tune or train from scratch?", "C"),
    ]
    return [Q(t, f, footprint_from_text(t), "original") for t, f in specs]


def naive_merge(q1: Q, q2: Q) -> Q:
    text = f"{q1.text} // {q2.text}"
    return Q(text, q1.family, footprint_from_text(text), "merged")


def inherited_merge(q1: Q, q2: Q) -> Q:
    text = f"{q1.text} // {q2.text}"
    return Q(text, q1.family, q1.fp | q2.fp, "merged")


def split_parts(q: Q) -> list:
    chunks = [c.strip() for c in q.text.replace("?", "").split(", ") if c.strip()]
    if len(chunks) < 2:  # no comma: split on words into two halves
        w = q.text.split()
        mid = len(w) // 2
        chunks = [" ".join(w[:mid]), " ".join(w[mid:])]
    return [f"Part {i+1}: {c}" for i, c in enumerate(chunks)]


def naive_split(q: Q) -> list:
    return [Q(t, q.family, footprint_from_text(t), "split") for t in split_parts(q)]


def inherited_split(q: Q) -> list:
    """Partition parent footprint round-robin over parts (deterministic order)."""
    parts = split_parts(q)
    ordered = sorted(q.fp)
    buckets = [set() for _ in parts]
    for i, cell in enumerate(ordered):
        buckets[i % len(parts)].add(cell)
    return [Q(t, q.family, buckets[i], "split") for i, t in enumerate(parts)]


def union(qs) -> frozenset:
    u = set()
    for q in qs:
        u |= q.fp
    return frozenset(u)


def coverage_report(label, before: frozenset, after: frozenset):
    preserved = before & after
    lost = sorted(before - after)
    gained = sorted(after - before)
    ratio = len(preserved) / len(before)
    print(f"\n[{label}] coverage: {len(before)} -> {len(after)} facts")
    print(f"[{label}] preservation = {ratio:.3%}  lost={len(lost)} gained={len(gained)}")
    return ratio, lost, gained


def run(strategy: str):
    originals = make_originals()
    before_union = union(originals)

    # Topology changes (fixed, mirroring Q0 operators):
    # merge the two redundant family-A questions; split the comma-heavy
    # family-C question; drop originals that were consumed.
    a_qs = [q for q in originals if q.family == "A"][:2]
    c_split = [q for q in originals if q.text.startswith("Should we fine-tune")][0]

    live = [q for q in originals if q not in a_qs and q is not c_split]

    if strategy == "naive":
        merged = naive_merge(a_qs[0], a_qs[1])
        parts = naive_split(c_split)
    else:
        merged = inherited_merge(a_qs[0], a_qs[1])
        parts = inherited_split(c_split)

    live = live + [merged] + parts
    after_union = union(live)
    return coverage_report(strategy.upper(), before_union, after_union)


def main():
    print("=" * 62)
    print("Q1: Answer-space coverage preservation under MERGE/SPLIT")
    print("=" * 62)

    naive_ratio, naive_lost, _ = run("naive")
    inh_ratio, inh_lost, inh_gained = run("inherited")

    print("\n" + "-" * 62)
    print(f"NAIVE     preservation: {naive_ratio:.3%} (lost facts: {naive_lost})")
    print(f"INHERITED preservation: {inh_ratio:.3%} (lost: {len(inh_lost)}, gained/novel: {len(inh_gained)})")

    ok = (inh_ratio == 1.0) and (naive_ratio < 1.0)
    verdict = "PASS" if ok else "FAIL"
    print(f"\nCLAIM: footprint inheritance preserves answer coverage where naive regeneration does not -> {verdict}")

    # Determinism receipt: hash of both coverage unions.
    receipt_src = f"{naive_ratio:.6f}|{inh_ratio:.6f}".encode()
    receipt = hashlib.sha256(receipt_src).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
