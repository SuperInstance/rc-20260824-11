#!/usr/bin/env python3
"""
Q13 FOOTPRINT-GRANULAR REFILL: q12's law — after a regime flip, the
information distinguishing regimes lives ONLY in held-set dynamics
(the dice keeps re-adding now-valid footprints from inside the held
set), never in any per-cell observable of unheld candidates (best
per-cell signal 0.600 vs 0.518 baseline). q9 killed CELL-granular
footprint refill because validity is per-cell and footprint cells are
hash-scattered across both regimes — a footprint's held cells earning
reward said nothing about which of its UNHELD cells are valid.

Claim under test (honest, falsifiable):
  The held-set channel q12 identified CAN drive refill if the refill
  operates at FOOTPRINT granularity, not cell granularity: after an
  age-at-zero molt (q8 gate), rank footprints by their HELD cells'
  post-flip reward density (recent window, no oracle) and refill the
  freed quota in whole-footprint units — the ~50% straddling invalid
  cells admitted with each footprint are exactly the cells the
  surviving validity-blind hash-eviction layer is already proven to
  trim (q8 NEVER settles at 96.7%). FPGRAN beats NEVER on settled
  post-flip coverage.

  Counter-law: hash-scatter dilutes footprint density ranking too
  (every footprint straddles both halves ~50/50, so density variance
  across footprints is sampling noise), OR the admitted strays cost
  more eviction churn than the molt freed — then no granularity of
  refill beats dead-weight-in-place and molts stay out for good.

Arms (identical q8 harness, stress capacity 62):
  NEVER - no molts (q5 rule; best known: 96.7%).
  FPGRAN - q8 age-at-zero molt + whole-footprint refill ranked by
           held-cell recent reward density (window 20, observable
           ledger only, never reads valid_universe for gating).

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if FPGRAN beats NEVER on settled
post-flip coverage.
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
WINDOW = 60      # settled post-flip window
REWARD_WINDOW = 20
AGE_HOLD = 15
STRESS_CAPACITY = 62
DENSITY_WINDOW = 20   # trailing ticks of held-cell reward per footprint
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
ALL_FPS = QUESTION_FPS + [PEER_FP]


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


def run_arm(gate: str, capacity: int = STRESS_CAPACITY):
    """gate: 'none' (NEVER) | 'fpgran' (age molt + footprint refill)"""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}    # fact -> trailing window of (tick, reward)
    last_gain = {}
    molts = []          # (tick, n_dead, n_valid_dead, refill_n, refill_valid,
                        #  fp_rank_detail)
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost

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

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)

        if k > 0 and k % META_PERIOD == 0:
            if gate == "fpgran" and last_molt_meta != k // META_PERIOD:
                dead = {f for f in held
                        if k - last_gain.get(f, -AGE_HOLD) >= AGE_HOLD}
                if dead:
                    vdead = len(dead & uni)
                    held = frozenset(held - dead)
                    # footprint density: reward earned by each footprint's
                    # HELD cells (pre-molt set) over trailing window —
                    # observable only, from the ledger.
                    fp_density = {}
                    for i, fp in enumerate(ALL_FPS):
                        s = 0
                        for f in fp & dead.__class__(held):  # held ∩ fp
                            ent = fact_reward.get(f, [])
                            s += sum(r for (t, r) in ent if t > k - DENSITY_WINDOW)
                        fp_density[i] = s
                    ranked = sorted(range(len(ALL_FPS)),
                                    key=lambda i: (-fp_density[i], i))
                    quota = max(0, capacity - len(held))
                    refill = set()
                    detail = []
                    for i in ranked:
                        if len(refill) >= quota:
                            break
                        add = set(ALL_FPS[i]) - held - refill
                        refill |= add
                        detail.append((i, fp_density[i], len(add)))
                    held = frozenset(held | refill)
                    molts.append((k, len(dead), vdead, len(refill),
                                  len(refill & uni), detail))
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
    print("Q13: footprint-granular refill (q12 held-set channel)")
    print("=" * 62)
    print(f"--- stress condition: capacity {STRESS_CAPACITY}, age-hold "
          f"{AGE_HOLD}, density window {DENSITY_WINDOW} ---")
    res = {}
    for label, g in (("NEVER", "none"), ("FPGRAN", "fpgran")):
        res[label] = run_arm(g)
        cov, floor, stack, arch, molts, rec = res[label]
        print(f"\n{label:6s}: settled {cov:.3%} | floor {floor:.3%} | "
              f"recover@90% t+{rec} | stack {stack} | archived {arch}")
        for (k, dn, vd, rn, rv, detail) in molts:
            top = ", ".join(f"fp{i}:d{d}:+{n}" for (i, d, n) in detail[:4])
            print(f"       t={k}: molted {dn} (valid {vd}), refilled {rn} "
                  f"(valid {rv}) | {top}")

    n_cov = res["NEVER"][0]
    f_cov, f_floor, f_stack, f_arch, f_molts, f_rec = res["FPGRAN"]
    ok_beats = f_cov > n_cov
    ok_zero_valid_molted = all(m[2] == 0 for m in f_molts)
    print(f"\nCLAIM 1 (FPGRAN beats NEVER on settled coverage): "
          f"{'PASS' if ok_beats else 'FAIL'} ({f_cov:.3%} vs {n_cov:.3%})")
    print(f"CLAIM 2 (zero valid facts molted): "
          f"{'PASS' if ok_zero_valid_molted else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "q13-fpgran-refill", f"{n_cov:.6f}", f"{f_cov:.6f}",
        f"{res['NEVER'][1]:.6f}", f"{f_floor:.6f}",
        res["NEVER"][2], f_stack,
        [(k, dn, vd, rn, rv, [(i, d, n) for (i, d, n) in detail])
         for (k, dn, vd, rn, rv, detail) in res["NEVER"][4]],
        [(k, dn, vd, rn, rv, [(i, d, n) for (i, d, n) in detail])
         for (k, dn, vd, rn, rv, detail) in f_molts],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = ok_beats and ok_zero_valid_molted
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
