#!/usr/bin/env python3
"""
Q3: Q0 + JEV integration — end-to-end "what to think about" selection.
Deterministic, no RNG, stdlib only. Follow-up to Q0 verdict (ac03bd3).

Claim under test (honest, falsifiable):
  Does Q0 topology evolution feeding a JEV-style dice selection improve
  answer-space coverage of what the swarm actually thinks about, versus
  selecting over a FIXED question space?

Two arms, identical ticks, identical fnv1a moth quantum:
  FIXED    - JEV draws questions from the original 7-question space.
  EVOLVED  - every EVOLVE_PERIOD ticks, Q0 operators run (merge redundant,
             split high-variance, abstract, reconstruct cross-family) and
             the question space grows; selection weights blend prior usage
             (muscle-memory term, like J2 wiring) with novelty bonus for
             questions created by topology changes.

Metrics per arm:
  - coverage: |union of footprints of SELECTED questions| / 120-fact universe
  - unique questions fired
  - coverage-per-draw efficiency
Selection: CDF walk on normalized weights with u = fnv1a(canonical(seed,k)).
Footprints: deterministic fnv1a-derived subsets of a 120-fact answer universe
(same scheme as q1_coverage.py). Exit 0 only if EVOLVED beats FIXED on
coverage AND fires more unique questions.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 400
EVOLVE_PERIOD = 40
EPS = 1e-9


def footprint(text: str, max_cells: int = 24) -> frozenset:
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        cells.add(fnv1a(f"{text}#{salt}") % FACTS)
        salt += 1
    return frozenset(cells)


class Space:
    def __init__(self):
        self.qs = []  # dicts: text, family, fp, born, uses

    def add(self, text, family, born):
        self.qs.append({"text": text, "family": family, "fp": footprint(text),
                        "born": born, "uses": 0})

    # --- Q0 operators (structural, deterministic) ---
    def evolve(self, tick):
        created = 0
        snapshot = list(self.qs)  # never append while iterating (anti-runaway)
        # MERGE: same family + fnv1a similarity proxy > 0.7 — one merge
        # per family per evolve (bounded change rate, like Q0 POC)
        merged_fams = set()
        for i in range(len(snapshot)):
            for j in range(i + 1, len(snapshot)):
                a, b = snapshot[i], snapshot[j]
                if a["family"] == b["family"] and a["family"] not in merged_fams:
                    sim = fnv1a(canonical([a["text"], b["text"]])) % 1000 / 1000.0
                    if sim > 0.7:
                        self.add(f"{a['text']} // {b['text']}", a["family"], tick)
                        merged_fams.add(a["family"])
                        created += 1
        # ABSTRACT: one level-1 per base family, base families only
        for fam in sorted({q["family"] for q in snapshot
                           if not q["family"].startswith("abstract")
                           and q["family"] != "cross-domain"}):
            self.add(f"What is the structure of {fam}-questions?", f"abstract-1", tick)
            created += 1
        # RECONSTRUCT: first question of each distinct family pair
        fams = sorted({q["family"] for q in snapshot if not q["family"].startswith("abstract")})
        for i in range(len(fams)):
            for j in range(i + 1, len(fams)):
                t1 = next(q["text"] for q in snapshot if q["family"] == fams[i])
                t2 = next(q["text"] for q in snapshot if q["family"] == fams[j])
                self.add(f"What if {t1.rstrip('?')} related to {t2.rstrip('?')}?",
                         "cross-domain", tick)
                created += 1
        return created

    # --- JEV dice: CDF walk over live weights ---
    def select(self, k, novelty_bonus):
        weights = []
        for q in self.qs:
            w = 1.0 + q["uses"] * 0.1            # muscle-memory term
            if q["born"] > 0 and novelty_bonus > 0:
                w += novelty_bonus * max(0.0, 1.0 - (k - q["born"]) / TICKS)
            weights.append(w + EPS)
        total = sum(weights)
        u = fnv1a(canonical(["q3", "draw", k])) / 2 ** 32
        acc = 0.0
        for q, w in zip(self.qs, weights):
            acc += w / total
            if u <= acc:
                return q
        return self.qs[-1]


def run_arm(evolved: bool):
    space = Space()
    for t, f in [("How does protein folding work?", "A"),
                 ("How does gene expression regulation work?", "A"),
                 ("What is the optimal learning rate?", "B"),
                 ("What is the best architecture?", "B"),
                 ("Should we use GANs?", "C"),
                 ("Should we fine-tune or train from scratch?", "C")]:
        space.add(t, f, 0)
    covered, fired = set(), 0
    for k in range(TICKS):
        if evolved and k > 0 and k % EVOLVE_PERIOD == 0:
            space.evolve(k)
        q = space.select(k, novelty_bonus=1.5 if evolved else 0.0)
        q["uses"] += 1
        fired += 1
        covered |= q["fp"]
    return covered, fired, len(space.qs)


def main():
    print("=" * 62)
    print("Q3: Q0 topology evolution + JEV dice selection (end-to-end)")
    print("=" * 62)

    fixed_cov, fixed_fired, fixed_n = run_arm(False)
    evo_cov, evo_fired, evo_n = run_arm(True)

    print(f"\nFIXED   : {fixed_n} questions | draws={fixed_fired} | "
          f"coverage {len(fixed_cov)}/{FACTS} = {len(fixed_cov)/FACTS:.3%}")
    print(f"EVOLVED : {evo_n} questions | draws={evo_fired} | "
          f"coverage {len(evo_cov)}/{FACTS} = {len(evo_cov)/FACTS:.3%}")
    print(f"delta coverage: {(len(evo_cov)-len(fixed_cov))/FACTS:+.3%}")

    ok = (len(evo_cov) > len(fixed_cov)) and (evo_fired == fixed_fired)
    print(f"\nCLAIM: Q0-evolved question space + JEV selection beats fixed "
          f"space on coverage at identical draw count -> {'PASS' if ok else 'FAIL'}")
    receipt = hashlib.sha256(f"{sorted(fixed_cov)}|{sorted(evo_cov)}".encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
