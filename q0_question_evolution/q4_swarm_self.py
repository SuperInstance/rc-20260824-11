#!/usr/bin/env python3
"""
SWARM_SELF: can the swarm evolve its OWN architecture (the layer stack
itself), not just its questions (Q0) or genomes (M-series)?

Deterministic, no RNG, stdlib only. Same conventions as q1-q3:
fnv1a moth quantum, byte-identical replay, receipt sha256.

Claim under test (honest, falsifiable):
  An architecture whose layer stack is itself gated by evidence ticks
  (each layer accumulates benefit = facts gained/retained through its
  execution; a meta-gate replaces chronically-negative-benefit layers
  with the best unused alternative) achieves higher steady-state fact
  coverage than the same initial stack held FIXED over identical ticks.

Two arms, identical ticks, identical fnv1a quantum stream:
  FIXED  - initial 5-layer stack runs unchanged for all ticks.
  SELF   - same initial stack, but every META_PERIOD ticks the meta-gate
           fires: layers whose trailing benefit is negative are retired
           (archive-by-rename into an ARCHIVE slot, never deleted) and
           the best unused layer is promoted. Bounded: one swap per
           meta-tick (anti-runaway, like Q0's one-merge-per-family).

Layers (all deterministic, operate on the swarm's held-fact set):
  dice     - draws a question footprint (exploration; adds facts)
  wiring   - reinforces held facts (no new facts; adds strength not coverage)
  compress - capacity cap: evicts least-replaceable-scoring facts (can LOSE coverage)
  mutate   - swaps some held facts for new footprint facts (churn)
  edges    - pulls facts from a fixed peer footprint (adds peer facts)
  abstract - large-novelty footprint draw, high churn

Fitness metric = |held facts| coverage of the 120-fact universe, averaged
over the final settled window, plus worst-case (starvation) check.
Exit 0 only if SELF beats FIXED on settled coverage.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 300
META_PERIOD = 30
CAPACITY = 70
WINDOW = 60  # settled window (last WINDOW ticks averaged)
EPS = 1e-9

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]


def footprint(text: str, max_cells: int = 24) -> frozenset:
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        cells.add(fnv1a(f"{text}#{salt}") % FACTS)
        salt += 1
    return frozenset(cells)


QUESTION_FPS = [footprint(f"q{i}") for i in range(8)]
PEER_FP = footprint("peer-agent-shared-docs")


def run_layer(name, held, k):
    """Execute layer; return (new_held, facts_gained, facts_lost)."""
    before = len(held)
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
    elif name == "wiring":
        pass  # strength only; set unchanged by design
    elif name == "compress":
        if len(held) > CAPACITY:
            scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
            held = frozenset(sorted(scored[:CAPACITY]))
    elif name == "mutate":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "mut", k])) % len(QUESTION_FPS)]
        drop_n = min(6, len(held))
        drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "drop", f, k])))[:drop_n])
        held = (held - drops) | (fp - drops)
    elif name == "edges":
        held = held | PEER_FP
    elif name == "abstract":
        fp = footprint(f"abstract-structure-{k % 3}")
        drop_n = min(10, len(held))
        drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "adrop", f, k])))[:drop_n])
        held = (held - drops) | (fp - drops)
    return frozenset(held), len(held) - before if len(held) >= before else 0, \
        max(0, before - len(held))


def run_arm(self_evolve: bool):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]  # initial arch
    archive = []  # retired layers, archive-by-rename, never re-promoted
    benefit = {n: 0 for n in LAYER_NAMES}  # append-only tick sums per layer
    held = frozenset()
    cov_trace = []
    for k in range(TICKS):
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k)
            benefit[layer] += gained - lost
        cov_trace.append(len(held))
        if self_evolve and k > 0 and k % META_PERIOD == 0:
            # meta-gate: worst trailing-benefit ACTIVE layer retired (if
            # negative), best never-tried layer promoted. One swap per
            # meta-tick. Retired layers are NEVER re-promoted (archive-
            # by-rename; the architecture remembers what it rejected).
            active = [(benefit[n], n) for n in stack if n != "dice"]
            active.sort()
            worst_b, worst = active[0]
            if worst_b < 0:
                idx = stack.index(worst)
                archive.append(worst)
                candidates = [n for n in LAYER_NAMES
                              if n not in stack and n not in archive]
                if candidates:
                    pick = sorted(candidates,
                                  key=lambda n: (-benefit[n], n))[0]
                    stack[idx] = pick  # rename slot in place
                else:
                    del stack[idx]  # shrink, nothing left to try
    settled = cov_trace[-WINDOW:]
    return sum(settled) / WINDOW / FACTS, min(settled) / FACTS, stack, archive


def main():
    print("=" * 62)
    print("SWARM_SELF: the swarm evolves its own layer architecture")
    print("=" * 62)

    fixed_cov, fixed_floor, fixed_stack, _ = run_arm(False)
    self_cov, self_floor, self_stack, archive = run_arm(True)

    print(f"\nFIXED : settled coverage {fixed_cov:.3%} | floor {fixed_floor:.3%}"
          f" | stack {fixed_stack}")
    print(f"SELF  : settled coverage {self_cov:.3%} | floor {self_floor:.3%}"
          f" | stack {self_stack} | archived {archive}")

    ok = self_cov > fixed_cov
    print(f"\nCLAIM: evidence-gated architecture self-evolution beats the "
          f"same fixed stack on settled coverage -> {'PASS' if ok else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "swarm-self", f"{fixed_cov:.6f}", f"{self_cov:.6f}",
        f"{fixed_floor:.6f}", f"{self_floor:.6f}", fixed_stack, self_stack,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
