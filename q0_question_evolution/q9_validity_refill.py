#!/usr/bin/env python3
"""
Q9 VALIDITY-AWARE REFILL: q8's law — the age-at-zero molt is a PERFECT
death sensor (zero valid facts molted at any tick) yet still LOSES to
NEVER (86.7% vs 96.7% settled post-flip coverage) because the refill
path is validity-blind: freed capacity is re-churned by dice footprints
+ mutate/edges hash-eviction and settles at 52/60 valid vs NEVER's
58/60. Molts need either validity-aware refill or nothing.

Claim under test (honest, falsifiable):
  Refill can be made validity-aware WITHOUT an oracle peek by ranking
  question footprints by OBSERVED reward density (the same per-fact
  reward ledger q6-q8 already instrument): a footprint whose held facts
  earn reward now is a same-regime footprint, so its UNHELD cells are
  the best refill candidates. After each molt, refill freed capacity
  from top-ranked footprints' unheld cells before the stack's next
  churn pass. AGE+REFILL beats NEVER and AGE-only on settled post-flip
  coverage.

  No oracle peek: the refill ranks and candidates read only the
  observable reward ledger, never valid_universe().

Arms (identical until flip at TICKS//2, same q4 meta-gate after):
  NEVER  - q5 rule: never re-promote, no molts.
  AGE    - q8 gate (age-at-zero, hold 15), no refill — best control.
  REFILL - q8 gate + validity-aware refill.

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if REFILL beats NEVER AND AGE on
settled post-flip coverage AND molts zero pre-flip VALID facts.
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
WINDOW = 60    # settled post-flip window
REWARD_WINDOW = 20
AGE_HOLD = 15
STRESS_CAPACITY = 62    # q6-q8 stress: stale facts genuinely crowd
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


def run_arm(gate: str, capacity: int = CAPACITY):
    """gate: 'none' | 'age' | 'refill'"""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}    # fact -> trailing window of (tick, reward)
    last_gain = {}
    reward_hist = []
    molts = []          # (tick, n_dropped, n_valid_dropped)
    refills = []        # (tick, n_added, n_valid_added)  [instrumentation]
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost
            tick_gained += gained
            tick_lost += lost

        # observable reward ledger (gating/refill never read the universe;
        # universe used only for off-line instrumentation)
        uni = valid_universe(k)
        total_r = 0
        for f in held:
            r = 1 if f in uni else 0
            total_r += r
            if r:
                last_gain[f] = k
            fact_reward.setdefault(f, []).append((k, r))
            fr = fact_reward[f]
            while fr and fr[0][0] <= k - REWARD_WINDOW:
                fr.pop(0)
        reward_hist.append((k, total_r))

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)

        if k > 0 and k % META_PERIOD == 0:
            if gate in ("age", "refill") and last_molt_meta != k // META_PERIOD:
                dead = {f for f in held
                        if k - last_gain.get(f, -AGE_HOLD) >= AGE_HOLD}
                if dead:
                    vdead = len(dead & uni)   # instrumentation only
                    held = frozenset(held - dead)
                    molts.append((k, len(dead), vdead))
                    last_molt_meta = k // META_PERIOD
                    if gate == "refill" and len(held) < capacity:
                        # VALIDITY-AWARE REFILL (observable inputs only):
                        # rank question footprints by recent reward density
                        # among currently-held facts, then add unheld cells
                        # of top footprints up to freed capacity.
                        fp_scores = []
                        for i, fp in enumerate(QUESTION_FPS):
                            hits = [f for f in (fp & held)
                                    if any(r for (_, r) in fact_reward.get(f, []))]
                            fp_scores.append((len(hits), i))
                        fp_scores.sort(key=lambda t: (-t[0], t[1]))
                        added = set()
                        quota = capacity - len(held)
                        for (_, i) in fp_scores:
                            if quota <= 0:
                                break
                            if fp_scores and fp_scores[0][0] == 0:
                                break   # no rewarded footprint: no refill
                            for f in sorted(fp - held):
                                if quota <= 0:
                                    break
                                added.add(f)
                                quota -= 1
                        if added:
                            vadd = len(added & uni)   # instrumentation only
                            held = frozenset(held | added)
                            refills.append((k, len(added), vadd))
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
            stack, archive, molts, refills, recover)


def main():
    print("=" * 62)
    print("Q9: validity-aware refill after age-at-zero molt (q8's law)")
    print("=" * 62)

    print(f"\n--- stress condition (q6-q8): capacity {STRESS_CAPACITY}, "
          f"age-hold {AGE_HOLD} ---")
    res = {}
    for label, g in (("NEVER", "none"), ("AGE", "age"), ("REFILL", "refill")):
        res[label] = run_arm(g, STRESS_CAPACITY)
        cov, floor, stack, arch, molts, refills, rec = res[label]
        print(f"\n{label:6s}: settled {cov:.3%} | floor {floor:.3%} | "
              f"recover@90% t+{rec} | stack {stack} | archived {arch}")
        print(f"        molts {molts if molts else 'none'}")
        print(f"        refills {refills if refills else 'none'}")

    n_cov = res["NEVER"][0]
    a_cov = res["AGE"][0]
    r_cov, r_floor, r_stack, r_arch, r_molts, r_refills, r_rec = res["REFILL"]

    ok_beats_never = r_cov > n_cov
    ok_beats_age = r_cov > a_cov
    ok_zero_valid_molt = all(m[2] == 0 for m in r_molts)
    print(f"\nCLAIM 1 (refill beats never on settled coverage): "
          f"{'PASS' if ok_beats_never else 'FAIL'} "
          f"({r_cov:.3%} vs {n_cov:.3%})")
    print(f"CLAIM 2 (refill beats age-only control): "
          f"{'PASS' if ok_beats_age else 'FAIL'} "
          f"({r_cov:.3%} vs {a_cov:.3%})")
    print(f"CLAIM 3 (zero valid facts molted, all ticks): "
          f"{'PASS' if ok_zero_valid_molt else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "q9-validity-refill", f"{n_cov:.6f}", f"{a_cov:.6f}", f"{r_cov:.6f}",
        f"{res['NEVER'][1]:.6f}", f"{res['AGE'][1]:.6f}", f"{r_floor:.6f}",
        res["NEVER"][2], res["AGE"][2], r_stack,
        [(k, dn, vd) for (k, dn, vd) in res["NEVER"][4]],
        [(k, dn, vd) for (k, dn, vd) in res["AGE"][4]],
        [(k, dn, vd) for (k, dn, vd) in r_molts],
        [(k, an, va) for (k, an, va) in r_refills],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = ok_beats_never and ok_beats_age and ok_zero_valid_molt
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
