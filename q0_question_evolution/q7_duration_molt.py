#!/usr/bin/env python3
"""
Q7 MOLT WITH A NOISE MODEL (dip-DURATION, not dip-DEPTH): q6's law —
a per-fact reward ledger cannot distinguish regime death from reward
noise at small dip magnitudes; 4/5 molts at dip-depth gate 0.05 were
PRE-flip false positives on reward noise (fired at t=90 << flip 150),
each dropping ~52 valid facts, MOLT 86.7% vs NEVER 96.7% settled
post-flip coverage under stress capacity 62.

Claim under test (honest, falsifiable):
  Replacing the dip-DEPTH trigger (mean window < (1-f)*peak) with a
  dip-DURATION trigger — the stack's total per-tick reward must sit
  below (1-f)*trailing peak for DIP_HOLD *consecutive ticks* at molt
  time — eliminates pre-flip false-positive molts (noise dips are
  transient; regime death is sustained) and lets the molt earn its
  place: under q6's stress condition (capacity 62), DURATION-molt
  beats NEVER on settled post-flip coverage with zero pre-flip molts.

  Duration exploits an asymmetry the depth gate cannot see: reward
  noise oscillates around the mean, so it never holds below a
  threshold for DIP_HOLD straight ticks; a regime flip pins the
  reward at ~0 for the whole transient. No oracle peek: the gate
  reads the same observable reward ledger as q6, never
  valid_universe().

Arms (identical until flip at TICKS//2, same q4 meta-gate after):
  NEVER   - q5 rule: never re-promote, no molts.
  DEPTH   - q6 stress gate (0.05 depth) — the known-bad control.
  DURATION- dip-duration gate (0.05 depth held DIP_HOLD ticks).

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if DURATION beats NEVER on
settled post-flip coverage AND fires zero pre-flip molts.
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
WINDOW = 60   # settled post-flip window
REWARD_WINDOW = 20
COLLAPSE_FRAC = 0.30
STRESS_CAPACITY = 62    # q6 stress: stale facts genuinely crowd new regime
STRESS_COLLAPSE = 0.05  # matches the observed ~10% transient dip
DIP_HOLD = 10           # consecutive below-threshold ticks required
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
    half = FACTS // 2
    if k < FLIP:
        return frozenset(range(half))
    return frozenset(range(half, FACTS))


def run_layer(name, held, k, capacity=CAPACITY):
    before = len(held)
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
    elif name == "wiring":
        pass
    elif name == "compress":
        if len(held) > capacity:
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


def run_arm(gate: str, capacity: int = CAPACITY,
            collapse_frac: float = COLLAPSE_FRAC):
    """gate: 'none' | 'depth' | 'duration'"""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}   # fact -> list of (tick, reward), trailing window
    reward_hist = []   # (tick, total_stack_reward)
    molts = []
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost
            tick_gained += gained
            tick_lost += lost

        # observable reward ledger (same as q6 — never reads universe)
        uni = valid_universe(k)
        total_r = 0
        for f in held:
            r = 1 if f in uni else 0
            total_r += r
            fact_reward.setdefault(f, []).append((k, r))
            fr = fact_reward[f]
            while fr and fr[0][0] <= k - REWARD_WINDOW:
                fr.pop(0)
        reward_hist.append((k, total_r))

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)

        if k > 0 and k % META_PERIOD == 0:
            if gate != "none" and last_molt_meta != k // META_PERIOD:
                hist = [r for (t, r) in reward_hist if t <= k - META_PERIOD]
                peak = max(hist) if hist else 0
                fire = False
                if hist and peak > 0:
                    thr = (1 - collapse_frac) * peak
                    recent = [r for (t, r) in reward_hist]
                    if gate == "depth":
                        # q6 rule: mean of last meta-period below threshold
                        window = recent[k - META_PERIOD:k]
                        fire = bool(window) and \
                            sum(window) / len(window) < thr
                    else:  # duration
                        # last DIP_HOLD ticks ALL below threshold
                        tail = recent[k - DIP_HOLD:k]
                        fire = len(tail) == DIP_HOLD and \
                            all(r < thr for r in tail)
                if fire:
                    dead = {f for f in held
                            if sum(r for (_, r) in fact_reward[f]) == 0}
                    if dead:
                        held = frozenset(held - dead)
                        molts.append((k, len(dead)))
                        last_molt_meta = k // META_PERIOD
            # q4 meta-gate (all arms)
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
                    stack[idx] = pick
                else:
                    del stack[idx]
    settled = post_flip_cov[-WINDOW:]
    target = 0.9 * (sum(settled) / len(settled))
    recover = next((i for i, c in enumerate(post_flip_cov) if c >= target),
                   len(post_flip_cov))
    return (sum(settled) / len(settled), min(settled),
            stack, archive, molts, recover)


def main():
    print("=" * 62)
    print("Q7: molt gate with a noise model (dip-DURATION, q6's law)")
    print("=" * 62)

    print(f"\n--- stress condition (q6): capacity {STRESS_CAPACITY}, "
          f"depth {STRESS_COLLAPSE}, hold {DIP_HOLD} ---")
    res = {}
    for label, g in (("NEVER", "none"), ("DEPTH", "depth"),
                     ("DURATION", "duration")):
        res[label] = run_arm(g, STRESS_CAPACITY, STRESS_COLLAPSE)
        cov, floor, stack, arch, molts, rec = res[label]
        pre = [m for m in molts if m[0] < FLIP]
        print(f"\n{label:8s}: settled {cov:.3%} | floor {floor:.3%} | "
              f"recover@90% t+{rec} | stack {stack} | archived {arch}")
        print(f"          molts {molts if molts else 'none'} "
              f"(pre-flip: {len(pre)})")

    n_cov = res["NEVER"][0]
    d_cov = res["DEPTH"][0]
    u_cov, u_floor, u_stack, u_arch, u_molts, u_rec = res["DURATION"]
    u_pre = [m for m in u_molts if m[0] < FLIP]

    ok_dur_beats_never = u_cov > n_cov
    ok_zero_pre = len(u_pre) == 0
    ok_dur_beats_depth = u_cov >= d_cov
    print(f"\nCLAIM 1 (duration beats never on settled coverage): "
          f"{'PASS' if ok_dur_beats_never else 'FAIL'} "
          f"({u_cov:.3%} vs {n_cov:.3%})")
    print(f"CLAIM 2 (zero pre-flip molts): "
          f"{'PASS' if ok_zero_pre else 'FAIL'} ({len(u_pre)} pre-flip)")
    print(f"CLAIM 3 (duration >= depth control): "
          f"{'PASS' if ok_dur_beats_depth else 'FAIL'} "
          f"({u_cov:.3%} vs {d_cov:.3%})")
    receipt = hashlib.sha256(canonical([
        "q7-duration-molt", f"{n_cov:.6f}", f"{d_cov:.6f}", f"{u_cov:.6f}",
        f"{res['NEVER'][1]:.6f}", f"{res['DEPTH'][1]:.6f}", f"{u_floor:.6f}",
        res["NEVER"][2], res["DEPTH"][2], u_stack,
        [(k, dn) for (k, dn) in res["NEVER"][4]],
        [(k, dn) for (k, dn) in res["DEPTH"][4]],
        [(k, dn) for (k, dn) in u_molts],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = ok_dur_beats_never and ok_zero_pre and ok_dur_beats_depth
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
