#!/usr/bin/env python3
"""
Q2: Human-Surprise Test for Q0 question-topology discoveries
Deterministic, no RNG, stdlib only. Follow-up to Q0 verdict (ac03bd3).

Claim under test (honest, falsifiable):
  Q0's MERGE operator sometimes links questions a human similarity judge
  would NOT link (surprising links), and those links are not noise — they
  carry measurable answer-footprint overlap beyond chance.

Method:
  1. Question corpus: 16 questions across 4 obvious human families
     (proteins, ML-training, deployment, funding). Human similarity
     ground truth = same_family flag (a conservative human proxy: humans
     notice family identity; cross-family links are "surprising").
  2. Machine affinity: for each pair, two deterministic signals —
     (a) lexical: Jaccard over stemmed-ish token sets
     (b) footprint: |fp_a ∩ fp_b| / |fp_a ∪ fp_b| (Jaccard over answer cells)
  3. Q0-merge rule: merge the single best pair per family by combined
     affinity, ALLOWING cross-family merges (that's where surprise lives).
  4. SURPRISE = a merge where human_same_family == False but footprint
     overlap alone >= FP_MIN (0.10). Report which pairs, and whether their
     footprint overlap exceeds the corpus-wide cross-family baseline.
Exit 0 only if: at least 2 surprising merges found AND every surprising
merge's footprint overlap >= 1.5x the all-pairs cross-family baseline.
"""

import hashlib
import sys
from itertools import combinations

FNV1A_OFFSET = 0xcbf29ce484222325
FNV1A_PRIME = 0x00000100000001B3
FACTS = 120
FP_MAX = 24
FP_MIN = 0.10          # min footprint Jaccard for a surprising link
BASELINE_MULT = 1.5    # surprise must beat baseline by this factor
STOP = {"a", "an", "the", "is", "are", "do", "does", "we", "should", "or",
        "to", "from", "for", "of", "and", "in", "on", "how", "what", "work",
        "best", "optimal"}


def fnv1a(data: bytes) -> int:
    h = FNV1A_OFFSET
    for b in data:
        h = (h ^ b) * FNV1A_PRIME & 0xFFFFFFFFFFFFFFFF
    return h


def footprint(text: str) -> frozenset:
    cells, salt = set(), 0
    while len(cells) < FP_MAX and salt < 4 * FP_MAX:
        cells.add(fnv1a(f"{text}#{salt}".encode()) % FACTS)
        salt += 1
    return frozenset(cells)


def toks(text: str) -> set:
    return {t.strip("?.,!").lower() for t in text.split()} - STOP


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


CORPUS = [
    ("How does protein folding work?", "protein"),
    ("How does protein structure prediction work?", "protein"),
    ("How does gene expression misfold and aggregate?", "protein"),
    ("How do chaperones assist protein folding?", "protein"),
    ("What is the optimal learning rate schedule?", "mltrain"),
    ("How should we initialize model weights?", "mltrain"),
    ("Does curriculum ordering speed up training?", "mltrain"),
    ("How does overfitting emerge during training?", "mltrain"),
    ("How do we version and roll back a deployment?", "deploy"),
    ("What causes cascading failures in serving?", "deploy"),
    ("How do we canary a risky model release?", "deploy"),
    ("What saturates first under load scaling?", "deploy"),
    ("When should we raise a priced round?", "funding"),
    ("How does runway constrain hiring pace?", "funding"),
    ("What dilution do repeat SAFEs cause?", "funding"),
    ("When does revenue make fundraising optional?", "funding"),
]


class Q:
    def __init__(self, text, family):
        self.text, self.family = text, family
        self.sha = hashlib.sha256(text.encode()).hexdigest()[:12]
        self.tok, self.fp = toks(text), footprint(text)


def main() -> int:
    qs = [Q(t, f) for t, f in CORPUS]
    print(f"corpus: {len(qs)} questions, families={sorted({q.family for q in qs})}")

    # Corpus-wide baseline: mean footprint Jaccard over ALL cross-family pairs
    cross = [(a, b) for a, b in combinations(qs, 2) if a.family != b.family]
    cross_fps = [jaccard(a.fp, b.fp) for a, b in cross]
    baseline = sum(cross_fps) / len(cross_fps)
    print(f"cross-family baseline footprint Jaccard: {baseline:.4f} "
          f"(over {len(cross)} pairs)")

    # Score every pair; machine affinity = lexical + footprint
    scored = []
    for a, b in combinations(qs, 2):
        lex, fp = jaccard(a.tok, b.tok), jaccard(a.fp, b.fp)
        scored.append((lex + fp, lex, fp, a, b, a.family == b.family))
    scored.sort(key=lambda s: (-s[0], s[3].sha, s[4].sha))

    # Q0 merge: best pair per family-of-a, bounded to 4 merges (one per family)
    merges, used = [], set()
    for fam in sorted({q.family for q in qs}):
        for tot, lex, fp, a, b, same in scored:
            if a.family == fam and a.sha not in used and b.sha not in used:
                merges.append((tot, lex, fp, a, b, same))
                used |= {a.sha, b.sha}
                break

    print(f"\nQ0 merges ({len(merges)}):")
    surprising = []
    for tot, lex, fp, a, b, same in merges:
        tag = "SAME-FAMILY" if same else "SURPRISING"
        print(f"  [{tag}] {a.sha}+{b.sha} affinity={tot:.3f} "
              f"(lex={lex:.3f} fp={fp:.3f})")
        print(f"      '{a.text}'  +  '{b.text}'")
        if not same and fp >= FP_MIN:
            surprising.append((fp, a, b))

    print(f"\nsurprising merges (cross-family, fp>={FP_MIN}): {len(surprising)}")
    for fp, a, b in surprising:
        ratio = fp / baseline if baseline else float("inf")
        verdict = "PASS" if ratio >= BASELINE_MULT else "WEAK"
        print(f"  fp={fp:.3f} = {ratio:.2f}x baseline [{verdict}] "
              f"{a.family}+{b.family}")
        print(f"      '{a.text}'  +  '{b.text}'")

    n_surprise = len(surprising)
    all_strong = all(fp / (baseline or 1e-9) >= BASELINE_MULT
                     for fp, _, _ in surprising)
    ok = n_surprise >= 2 and all_strong
    print(f"\ncriterion: >=2 surprising merges ({n_surprise}) AND all "
          f">={BASELINE_MULT}x baseline ({all_strong}) -> "
          f"{'PASS' if ok else 'FAIL'}")

    # Receipt: sha256 over the printed merge decisions
    blob = "\n".join(f"{a.sha}+{b.sha}:{fp:.4f}:{same}"
                     for _, _, fp, a, b, same in sorted(merges,
                                                        key=lambda m: m[3].sha))
    receipt = hashlib.sha256(blob.encode()).hexdigest()[:12]
    print(f"receipt: {receipt}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
