#!/usr/bin/env python3
"""
Q8 MOLT ON PER-FACT AGE-AT-ZERO: q7's law — in a stack that regains
total reward within the same tick after a flip (recover@90% t+0), NO
dip-shape gate (depth, duration, or combination) on the AGGREGATE
reward ledger can distinguish regime death from a growth transient:
pre-flip dips are long sustained growth ramps, and post-flip death is
invisible once new-regime facts arrive.

Claim under test (honest, falsifiable):
  The aggregate ledger hides death because per-fact signals CANCEL.
  The per-fact ledger does not: a fact that has earned ZERO reward for
  AGE_HOLD consecutive ticks is dead weight regardless of stack totals.
  Moving the molt signal from aggregate dip-shape to per-fact
  age-at-zero (k - last_reward_tick(f) >= AGE_HOLD) fires ZERO
  pre-flip molts on valid facts (pre-flip valid facts earn reward
  every tick they are held, so their age-at-zero is 0 by construction;
  only never-valid strays age out), and post-flip it molts exactly the
  dead first-regime facts, freeing q6/q7 stress capacity for the new
  regime: AGE beats NEVER on settled post-flip coverage.

  No oracle peek: the gate reads only the same per-fact reward ledger
  q6/q7 already instrument, never valid_universe(). AGE_HOLD=15 sits
  between single-tick noise and the 150-tick regime length.

Arms (identical until flip at TICKS//2, same q4 meta-gate after):
  NEVER   - q5 rule: never re-promote, no molts.
  DURATION- q7 gate (dip-duration, hold 10) — best-known control.
  AGE     - per-fact age-at-zero gate (hold 15).

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if AGE beats NEVER on settled
post-flip coverage AND molts zero pre-flip VALID facts.
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
COLLAPSE_FRAC = 0.30
STRESS_CAPACITY = 62    # q6/q7 stress: stale facts genuinely crowd
STRESS_COLLAPSE = 0.05
DIP_HOLD = 10           # q7 duration control
AGE_HOLD = 15           # per-fact zero-reward age before molt
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
    """gate: 'none' | 'duration' | 'age'"""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}    # fact -> trailing window of (tick, reward)
    last_gain = {}      # fact -> last tick with reward 1 (observable)
    reward_hist = []
    molts = []          # (tick, n_dropped, n_valid_dropped)
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost
            tick_gained += gained
            tick_lost += lost

        # observable reward ledger (same as q6/q7 — never reads universe
        # for gating; universe used only for off-line instrumentation)
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
            if gate != "none" and last_molt_meta != k // META_PERIOD:
                fire = False
                if gate == "duration":
                    hist = [r for (t, r) in reward_hist if t <= k - META_PERIOD]
                    peak = max(hist) if hist else 0
                    if hist and peak > 0:
                        thr = (1 - collapse_frac) * peak
                        recent = [r for (t, r) in reward_hist]
                        tail = recent[k - DIP_HOLD:k]
                        fire = len(tail) == DIP_HOLD and all(r < thr for r in tail)
                if fire:
                    dead = {f for f in held
                            if sum(r for (_, r) in fact_reward[f]) == 0}
                    if dead:
                        vdead = len(dead & uni)   # instrumentation only
                        held = frozenset(held - dead)
                        molts.append((k, len(dead), vdead))
                        last_molt_meta = k // META_PERIOD
                elif gate == "age":
                    # per-fact age-at-zero: sustained zero-reward facts only
                    dead = {f for f in held
                            if k - last_gain.get(f, -AGE_HOLD) >= AGE_HOLD}
                    if dead:
                        vdead = len(dead & uni)   # instrumentation only
                        held = frozenset(held - dead)
                        molts.append((k, len(dead), vdead))
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
    print("Q8: molt gate on per-fact AGE-AT-ZERO (q7's law)")
    print("=" * 62)

    print(f"\n--- stress condition (q6/q7): capacity {STRESS_CAPACITY}, "
          f"depth {STRESS_COLLAPSE}, dip-hold {DIP_HOLD}, age-hold {AGE_HOLD} ---")
    res = {}
    for label, g in (("NEVER", "none"), ("DURATION", "duration"), ("AGE", "age")):
        res[label] = run_arm(g, STRESS_CAPACITY, STRESS_COLLAPSE)
        cov, floor, stack, arch, molts, rec = res[label]
        print(f"\n{label:8s}: settled {cov:.3%} | floor {floor:.3%} | "
              f"recover@90% t+{rec} | stack {stack} | archived {arch}")
        print(f"          molts {molts if molts else 'none'}")

    n_cov = res["NEVER"][0]
    d_cov = res["DURATION"][0]
    a_cov, a_floor, a_stack, a_arch, a_molts, a_rec = res["AGE"]

    ok_age_beats_never = a_cov > n_cov
    ok_age_beats_duration = a_cov > d_cov
    ok_zero_valid = all(m[2] == 0 for m in a_molts)
    print(f"\nCLAIM 1 (age beats never on settled coverage): "
          f"{'PASS' if ok_age_beats_never else 'FAIL'} "
          f"({a_cov:.3%} vs {n_cov:.3%})")
    print(f"CLAIM 2 (age beats duration control): "
          f"{'PASS' if ok_age_beats_duration else 'FAIL'} "
          f"({a_cov:.3%} vs {d_cov:.3%})")
    print(f"CLAIM 3 (zero valid facts molted, all ticks): "
          f"{'PASS' if ok_zero_valid else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "q8-age-molt", f"{n_cov:.6f}", f"{d_cov:.6f}", f"{a_cov:.6f}",
        f"{res['NEVER'][1]:.6f}", f"{res['DURATION'][1]:.6f}", f"{a_floor:.6f}",
        res["NEVER"][2], res["DURATION"][2], a_stack,
        [(k, dn, vd) for (k, dn, vd) in res["NEVER"][4]],
        [(k, dn, vd) for (k, dn, vd) in res["DURATION"][4]],
        [(k, dn, vd) for (k, dn, vd) in a_molts],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = ok_age_beats_never and ok_age_beats_duration and ok_zero_valid
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
