#!/usr/bin/env python3
"""
Q5 LAYER REVIVAL: q4's swarm-self retires layers permanently (archive-by-
rename, never re-promoted) and won 93.3% vs 65.1% in a STABLE regime. But
the M-series verdicts showed world flips reset ledger wisdom. The same
question applies one level up: does the never-re-promote rule cost
coverage when a REGIME FLIP makes an archived layer valuable again?

Deterministic, no RNG, stdlib only. Same conventions as q1-q4:
fnv1a quantum, byte-identical replay, receipt sha256.

Claim under test (honest, falsifiable):
  Under a mid-run regime flip (the fact universe rotates: facts valid
  before the flip become worthless after it), an architecture whose
  meta-gate may RE-PROMOTE an archived layer when the active stack
  stagnates (trailing benefit negative for a full meta-period) achieves
  higher settled post-flip coverage than the q4 rule (never re-promote),
  at identical ticks and identical fnv1a quantum stream.

Arms (both self-evolving, identical until the flip at TICKS//2):
  NEVER - q4 rule: archived layers stay archived forever.
  REVIVE- when the active non-dice stack's trailing benefit over the
          last META_PERIOD ticks is negative (stagnation under a flipped
          universe), re-promote the archived layer with the best
          lifetime benefit into the worst active slot. Bounded: one
          revival candidate per meta-tick, same as q4's one swap.

Exit 0 only if REVIVE beats NEVER on settled post-flip coverage.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 300
FLIP = TICKS // 2
META_PERIOD = 30
CAPACITY = 70
WINDOW = 60  # settled post-flip window
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


def valid_universe(k: int) -> frozenset:
    """Regime: first-half facts valid before the flip, second-half after."""
    half = FACTS // 2
    if k < FLIP:
        return frozenset(range(half))
    return frozenset(range(half, FACTS))


def run_layer(name, held, k):
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


def run_arm(revive: bool):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]  # initial arch
    archive = []  # retired layers (archive-by-rename)
    benefit = {n: 0 for n in LAYER_NAMES}  # lifetime tick sums per layer
    trailing = []  # (tick, gained, lost) ledger for stack-level stagnation
    held = frozenset()
    cov_trace = []
    post_flip_cov = []
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k)
            benefit[layer] += gained - lost
            tick_gained += gained
            tick_lost += lost
        # coverage counts only the currently valid half of the universe
        cov = len(held & valid_universe(k)) / (FACTS // 2)
        cov_trace.append(cov)
        if k >= FLIP:
            post_flip_cov.append(cov)
        trailing.append((k, tick_gained, tick_lost, cov))
        if k > 0 and k % META_PERIOD == 0:
            # stack-level stagnation over the trailing meta-period,
            # measured on REGIME-VALID coverage (raw set growth can mask
            # regime loss: dice keeps adding now-worthless facts).
            window = [e for e in trailing if e[0] > k - META_PERIOD]
            stag = window[-1][3] - window[0][3] < 0
            if revive and stag and archive:
                # re-promote best archived layer into worst active slot
                worst = min((n for n in stack if n != "dice"),
                            key=lambda n: benefit[n])
                pick = sorted(archive, key=lambda n: (-benefit[n], n))[0]
                if benefit[pick] > benefit[worst]:
                    stack[stack.index(worst)] = pick
                    archive.remove(pick)
                continue
            # q4 meta-gate (both arms): retire worst negative-benefit layer
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
    settled = post_flip_cov[-WINDOW:]
    return (sum(settled) / len(settled), min(settled),
            stack, archive)


def main():
    print("=" * 62)
    print("Q5: layer revival under regime flip (architectural wisdom)")
    print("=" * 62)

    never_cov, never_floor, never_stack, never_arch = run_arm(False)
    rev_cov, rev_floor, rev_stack, rev_arch = run_arm(True)

    print(f"\nNEVER : settled post-flip coverage {never_cov:.3%} | floor "
          f"{never_floor:.3%} | stack {never_stack} | archived {never_arch}")
    print(f"REVIVE: settled post-flip coverage {rev_cov:.3%} | floor "
          f"{rev_floor:.3%} | stack {rev_stack} | archived {rev_arch}")

    ok = rev_cov > never_cov
    print(f"\nCLAIM: stagnation-gated archive revival beats never-re-promote "
          f"post-flip -> {'PASS' if ok else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "q5-layer-revival", f"{never_cov:.6f}", f"{rev_cov:.6f}",
        f"{never_floor:.6f}", f"{rev_floor:.6f}",
        never_stack, rev_stack, never_arch, rev_arch,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
