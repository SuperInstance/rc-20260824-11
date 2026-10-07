#!/usr/bin/env python3
"""
Q15 REFLEX AS ENERGY ECONOMIZER: q6-q14 closed the coverage axis —
constant full dice pressure recovers to the 96.667% ceiling at t+0
after a flip, so no gate can ADD coverage. But every prior arm paid
ONE dice pass EVERY tick. The untested axis is COST: can a reflex
gate buy the same ceiling coverage for FEWER total dice passes?

Claim under test (honest, falsifiable):
  A sparse-baseline + reflex arm — dice fires only every SPARSE_EVERY
  ticks at baseline, but the q14 ledger gate (EMA vs trailing-20 peak,
  DIP_FRAC) fires extra passes on dips, tightening -1/tick on recovery
  — matches the settled post-flip coverage of the FIXED full-pressure
  arm while spending strictly fewer total dice passes.

  If the ceiling depends on the constant full cadence (each missed
  baseline tick loses re-admission opportunities under hash-eviction),
  this FAILS honestly — ceiling coverage may be inseparable from
  full-rate pressure, and the cost axis closes too.

Arms (identical fnv1a quantum stream, same q4 meta-gate):
  FIXED  - one dice pass per tick, always (the q5-q14 champion).
  SPARSE+REFLEX - baseline pass every SPARSE_EVERY=2 ticks; gate as
    q14 (MAX_EXTRA=3) reading only reward_hist, never valid_universe.

PASS = sparse+reflex coverage >= FIXED - EPS AND total dice passes
strictly fewer. Deterministic, no RNG, stdlib only, fnv1a quantum,
byte-identical replay, receipt sha256.
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
WINDOW = 60
REFLEX_WINDOW = 20
DIP_FRAC = 0.05
EMA_ALPHA = 0.5
MAX_EXTRA = 3
SPARSE_EVERY = 2
STRESS_CAPACITY = 62
STRESS_DIP = 0.02
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


def run_layer(name, held, k, capacity=CAPACITY, dice_pass=0):
    before = len(held)
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(
            ["self", "dice", k] if dice_pass == 0
            else ["self", "diceX", k, dice_pass])) % len(QUESTION_FPS)]
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


def run_arm(mode: str, capacity: int = CAPACITY, dip_frac: float = DIP_FRAC):
    # mode: "fixed" (pass every tick) or "sparse" (baseline every
    # SPARSE_EVERY ticks + q14 reflex gate on top)
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    reward_hist = []
    ema = None
    extra = 0
    extra_fire_log = []
    post_flip_cov = []
    total_dice_passes = 0
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        if mode == "fixed":
            dice_passes = 1
        else:
            base = 1 if k % SPARSE_EVERY == 0 else 0
            dice_passes = base + extra
        for layer in list(stack):
            if layer == "dice":
                for p in range(dice_passes):
                    held, gained, lost = run_layer(layer, held, k, capacity, p)
                    benefit[layer] += gained - lost
                    tick_gained += gained
                    tick_lost += lost
                    total_dice_passes += 1
            else:
                held, gained, lost = run_layer(layer, held, k, capacity)
                benefit[layer] += gained - lost
                tick_gained += gained
                tick_lost += lost

        uni = valid_universe(k)
        total_r = sum(1 for f in held if f in uni)
        reward_hist.append((k, total_r))
        ema = total_r if ema is None else (1 - EMA_ALPHA) * ema + EMA_ALPHA * total_r

        if mode == "sparse":
            hist = [r for (t, r) in reward_hist
                    if k - REFLEX_WINDOW < t <= k]
            peak = max(hist) if hist else 0
            threshold = (1 - dip_frac) * peak
            fired = extra
            if peak > 0 and ema < threshold and extra < MAX_EXTRA:
                extra += 1
            elif extra > 0:
                extra -= 1
            fired = extra - fired
            if fired or extra:
                extra_fire_log.append((k, extra, round(ema, 2), round(peak, 2),
                                       round(threshold, 2)))

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)

        if k > 0 and k % META_PERIOD == 0:
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
            stack, archive, extra_fire_log, recover, total_dice_passes)


def main():
    print("=" * 62)
    print("Q15: reflex gate as energy economizer (cost axis)")
    print("=" * 62)

    print(f"\n--- condition A: q5 constants (capacity {CAPACITY}, "
          f"dip {DIP_FRAC}, sparse every {SPARSE_EVERY}) ---")
    f_cov, f_floor, f_stack, f_arch, _, f_rec, f_pass = run_arm("fixed")
    s_cov, s_floor, s_stack, s_arch, s_fire, s_rec, s_pass = run_arm("sparse")

    print(f"\nFIXED        : settled {f_cov:.3%} | floor {f_floor:.3%} | "
          f"recover@90% t+{f_rec} | passes {f_pass} | stack {f_stack} "
          f"| archived {f_arch}")
    print(f"SPARSE+REFLEX: settled {s_cov:.3%} | floor {s_floor:.3%} | "
          f"recover@90% t+{s_rec} | passes {s_pass} | stack {s_stack} "
          f"| archived {s_arch}")
    n_fire = len([1 for (k, e, *_) in s_fire if e > 0])
    pre_fire = len([1 for (k, *_) in s_fire if k < FLIP])
    post_fire = n_fire - pre_fire
    print(f"reflex ticks with extra passes: {n_fire} (pre-flip {pre_fire}, "
          f"post-flip {post_fire}) | sample: {s_fire[:6]}")

    print(f"\n--- condition B: stress (capacity {STRESS_CAPACITY}, "
          f"dip {STRESS_DIP}) ---")
    sf_cov, sf_floor, sf_stack, sf_arch, _, sf_rec, sf_pass = run_arm(
        "fixed", STRESS_CAPACITY, STRESS_DIP)
    ss_cov, ss_floor, ss_stack, ss_arch, ss_fire, ss_rec, ss_pass = run_arm(
        "sparse", STRESS_CAPACITY, STRESS_DIP)

    print(f"\nFIXED        : settled {sf_cov:.3%} | floor {sf_floor:.3%} | "
          f"recover@90% t+{sf_rec} | passes {sf_pass} | stack {sf_stack} "
          f"| archived {sf_arch}")
    print(f"SPARSE+REFLEX: settled {ss_cov:.3%} | floor {ss_floor:.3%} | "
          f"recover@90% t+{ss_rec} | passes {ss_pass} | stack {ss_stack} "
          f"| archived {ss_arch}")
    sn_fire = len([1 for (k, e, *_) in ss_fire if e > 0])
    spre_fire = len([1 for (k, *_) in ss_fire if k < FLIP])
    print(f"reflex ticks with extra passes: {sn_fire} (pre-flip "
          f"{spre_fire}) | sample: {ss_fire[:6]}")

    a_ok = (s_cov >= f_cov - EPS) and (s_pass < f_pass)
    b_ok = (ss_cov >= sf_cov - EPS) and (ss_pass < sf_pass)
    print(f"\nCLAIM A (q5 constants): sparse+reflex matches coverage at "
          f"fewer passes -> {'PASS' if a_ok else 'FAIL'} "
          f"({s_cov:.3%} vs {f_cov:.3%}, {s_pass} vs {f_pass} passes)")
    print(f"CLAIM B (stress): sparse+reflex matches coverage at fewer "
          f"passes -> {'PASS' if b_ok else 'FAIL'} "
          f"({ss_cov:.3%} vs {sf_cov:.3%}, {ss_pass} vs {sf_pass} passes)")
    receipt = hashlib.sha256(canonical([
        "q15-reflex-energy", f"{f_cov:.6f}", f"{s_cov:.6f}",
        f"{sf_cov:.6f}", f"{ss_cov:.6f}",
        f"{f_floor:.6f}", f"{s_floor:.6f}",
        f"{sf_floor:.6f}", f"{ss_floor:.6f}",
        f_pass, s_pass, sf_pass, ss_pass,
        f_stack, s_stack, sf_stack, ss_stack,
        [(k, e) for (k, e, *_) in s_fire], [(k, e) for (k, e, *_) in ss_fire],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = a_ok and b_ok
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
