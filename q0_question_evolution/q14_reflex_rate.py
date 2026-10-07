#!/usr/bin/env python3
"""
Q14 REFLEX DICE PRESSURE: q6-q13 closed molts under every observable
refill source; the surviving law is that the DICE layer itself is the
post-flip recovery channel (it re-admits valid footprints from inside
the held set faster than any refill). Nothing tested yet GATES that
channel: dice pressure is constant in every prior run.

Claim under test (honest, falsifiable):
  A reflex gate on dice pressure — reading ONLY the observable total-
  reward ledger (the same channel the molt gates read) — beats constant
  dice pressure on settled post-flip coverage under a regime flip.

  Mechanism (charter direction 3: gates firing pipelines on tick
  thresholds; reflex formation = thresholds that tighten from
  evidence):
    - Baseline: dice fires once per tick (constant, like all prior runs).
    - Reflex arm: maintain a trailing reward peak over REFLEX_WINDOW
      ticks. When current EMA(reward, alpha) drops below
      (1 - DIP_FRAC) * peak, the gate fires EXTRA dice passes
      (up to MAX_EXTRA per tick) — widening exploration under decay.
      As EMA recovers, the threshold TIGHTENS from evidence: extra
      passes decay one per tick (muscle-memory-like release), returning
      to the constant baseline. No oracle peek: the gate reads only
      reward_hist, never valid_universe().

  If q7's law (reward recovers t+0, so no dip-shape gate gets a signal)
  dominates, this FAILS honestly — that is itself the verdict: even the
  surviving recovery channel cannot be reflex-gated from the ledger.

Arms (identical ticks, identical fnv1a quantum stream, same q4 meta-gate):
  FIXED  - one dice pass per tick, always.
  REFLEX - baseline one pass; extra passes gated as above.

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if REFLEX beats FIXED on settled
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
WINDOW = 60       # settled post-flip window
REFLEX_WINDOW = 20
DIP_FRAC = 0.05   # q6/q7 observed ~10% transient dip; gate at half that
EMA_ALPHA = 0.5
MAX_EXTRA = 3
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
        # dice_pass 0 = the baseline draw (same quantum slot as all
        # prior runs); passes 1..N draw extra, stream-indexed footprints.
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


def run_arm(reflex: bool, capacity: int = CAPACITY, dip_frac: float = DIP_FRAC):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    reward_hist = []          # (tick, total_reward) — the ONLY gate input
    ema = None
    extra = 0                 # current extra dice passes (tightens -1/tick)
    extra_fire_log = []       # (tick, extra_fired, ema, peak, threshold)
    post_flip_cov = []
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        # dice pressure for this tick
        dice_passes = 1 + (extra if reflex else 0)
        for layer in list(stack):
            if layer == "dice":
                for p in range(dice_passes):
                    held, gained, lost = run_layer(layer, held, k, capacity, p)
                    benefit[layer] += gained - lost
                    tick_gained += gained
                    tick_lost += lost
            else:
                held, gained, lost = run_layer(layer, held, k, capacity)
                benefit[layer] += gained - lost
                tick_gained += gained
                tick_lost += lost

        # observable reward ledger (environment confirms valid held facts)
        uni = valid_universe(k)
        total_r = sum(1 for f in held if f in uni)
        reward_hist.append((k, total_r))
        ema = total_r if ema is None else (1 - EMA_ALPHA) * ema + EMA_ALPHA * total_r

        # reflex gate: extra passes fire on dip, tighten one per tick on recovery
        if reflex:
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
            # q4 meta-gate (both arms), identical to q6-q13
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
            stack, archive, extra_fire_log, recover)


def main():
    print("=" * 62)
    print("Q14: reflex dice pressure under regime flip (ledger-gated)")
    print("=" * 62)

    print(f"\n--- condition A: q5 constants (capacity {CAPACITY}, "
          f"dip {DIP_FRAC}) ---")
    f_cov, f_floor, f_stack, f_arch, f_fire, f_rec = run_arm(False)
    r_cov, r_floor, r_stack, r_arch, r_fire, r_rec = run_arm(True)

    print(f"\nFIXED : settled post-flip coverage {f_cov:.3%} | floor "
          f"{f_floor:.3%} | recover@90% t+{f_rec} | stack {f_stack} "
          f"| archived {f_arch}")
    print(f"REFLEX: settled post-flip coverage {r_cov:.3%} | floor "
          f"{r_floor:.3%} | recover@90% t+{r_rec} | stack {r_stack} "
          f"| archived {r_arch}")
    n_fire = len([1 for (k, e, *_ ) in r_fire if e > 0])
    pre_fire = len([1 for (k, *_ ) in r_fire if k < FLIP])
    print(f"reflex ticks with extra passes: {n_fire} "
          f"(pre-flip: {pre_fire}) | sample: {r_fire[:6]}")

    print(f"\n--- condition B: stress (capacity {STRESS_CAPACITY}, "
          f"dip {STRESS_DIP}) ---")
    sf_cov, sf_floor, sf_stack, sf_arch, sf_fire, sf_rec = run_arm(
        False, STRESS_CAPACITY, STRESS_DIP)
    sr_cov, sr_floor, sr_stack, sr_arch, sr_fire, sr_rec = run_arm(
        True, STRESS_CAPACITY, STRESS_DIP)

    print(f"\nFIXED : settled post-flip coverage {sf_cov:.3%} | floor "
          f"{sf_floor:.3%} | recover@90% t+{sf_rec} | stack {sf_stack} "
          f"| archived {sf_arch}")
    print(f"REFLEX: settled post-flip coverage {sr_cov:.3%} | floor "
          f"{sr_floor:.3%} | recover@90% t+{sr_rec} | stack {sr_stack} "
          f"| archived {sr_arch}")
    sn_fire = len([1 for (k, e, *_ ) in sr_fire if e > 0])
    spre_fire = len([1 for (k, *_ ) in sr_fire if k < FLIP])
    print(f"reflex ticks with extra passes: {sn_fire} "
          f"(pre-flip: {spre_fire}) | sample: {sr_fire[:6]}")

    a_ok = r_cov > f_cov + EPS
    b_ok = sr_cov > sf_cov + EPS
    print(f"\nCLAIM A (q5 constants): reflex beats fixed -> "
          f"{'PASS' if a_ok else 'FAIL'} ({r_cov:.3%} vs {f_cov:.3%})")
    print(f"CLAIM B (stress capacity): reflex beats fixed -> "
          f"{'PASS' if b_ok else 'FAIL'} ({sr_cov:.3%} vs {sf_cov:.3%})")
    receipt = hashlib.sha256(canonical([
        "q14-reflex-rate", f"{f_cov:.6f}", f"{r_cov:.6f}",
        f"{sf_cov:.6f}", f"{sr_cov:.6f}",
        f"{f_floor:.6f}", f"{r_floor:.6f}",
        f"{sf_floor:.6f}", f"{sr_floor:.6f}",
        f_stack, r_stack, sf_stack, sr_stack,
        [(k, e) for (k, e, *_ ) in r_fire], [(k, e) for (k, e, *_ ) in sr_fire],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = a_ok and b_ok
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
