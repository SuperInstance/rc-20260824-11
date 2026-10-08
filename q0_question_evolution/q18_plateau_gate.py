#!/usr/bin/env python3
"""
Q18 PLATEAU GATE: q17 was the first positive in the gate arc — under
ENDGENOUS flips (the universe flips only after the stack's coverage of
the live half dwells >= SAT), the observable saturation alert achieves
precision 0.667 vs hash-placebo 0.000. q18 asks the verdict's named
follow-up: can a gate EXPLOIT that anticipation to beat
dead-weight-in-place (constant full dice pressure)?

Mechanism under test — PRE-FLIP DICE PRESSURE RELEASE:
  The endogenous universe flips BECAUSE the stack saturated the live
  half. In the H ticks between alert (dwell DWELL-H+1, observable) and
  the flip, the held set on the live half is already at plateau: dice
  passes there buy nothing new on the dying half, and every cell the
  dice adds to the dying half is about to be devalued. So on alert,
  SKIP dice passes for H ticks (release), resume at the flip the tick
  coverage drops below SAT (observable). If anticipation is real, the
  released stack should save passes at (near-)zero settled-coverage
  cost — beating dead-weight-in-place on cost, the axis q15 lost on.

Contrast arm: the same release gate in the EXOGENOUS regime, where
q16/q17 proved anticipation is ~placebo — the release there should
cost coverage or save nothing (law reproduction).

Claims (honest, falsifiable):
  C1 (endo): released passes < baseline passes (savings > 0) AND
     settled post-flip coverage within 1.0pp of dead-weight-in-place.
  C2 (exo): the same gate does NOT achieve savings-at-no-cost
     (law: release without anticipation is a tax, q15-style).

Deterministic, no RNG, stdlib only, fnv1a, receipt sha256.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 400
CAPACITY = 70
DWELL = 20
LEAD = 5            # alert fires DWELL-LEAD ticks into a dwell
SAT = 0.60
HORIZON = 5
EXO_FLIP = TICKS // 2

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

HALF_A = frozenset(range(FACTS // 2))
HALF_B = frozenset(range(FACTS // 2, FACTS))


def _other_half(uni):
    return HALF_B if uni == HALF_A else HALF_A


def run_layer(name, held, k):
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
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
    return frozenset(held)


def run(mode: str, gate: bool):
    """mode: 'endo' (reactive universe) | 'exo' (fixed flip at TICKS//2).
    gate: False = dead-weight-in-place (dice every tick);
          True  = release: skip dice for H ticks after each alert,
                  resume when coverage < SAT (observable)."""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    cov = []
    flips = []
    dice_passes = 0
    uni = frozenset(range(FACTS // 2))
    dwell = 0
    skip = 0  # ticks of dice pressure remaining to skip (gate)
    for k in range(TICKS):
        if gate and skip == 0 and dwell >= DWELL - HORIZON + 1 and dwell < DWELL:
            skip = HORIZON  # release until the flip is due
        if gate and cov and cov[-1] < SAT:
            skip = 0  # coverage broke: resume full pressure immediately
        if not (gate and skip > 0):
            held = run_layer("dice", held, k)
            dice_passes += 1
        if gate and skip > 0:
            skip -= 1
        for layer in ("wiring", "compress", "mutate", "edges"):
            held = run_layer(layer, held, k)
        c = len(held & uni) / len(uni)
        cov.append(c)
        if mode == "exo":
            if k == EXO_FLIP - 1:
                flips.append(k + 1)
                uni = _other_half(uni)
        else:
            dwell = dwell + 1 if c >= SAT else 0
            if dwell >= DWELL:
                flips.append(k + 1)
                uni = _other_half(uni)
                dwell = 0
        # q5-style meta gate (archival only, repro parity)
        if k > 0 and k % 30 == 0:
            active = [(benefit[n], n) for n in stack if n != "dice"]
            active.sort()
            worst_b, worst = active[0]
            if worst_b < 0:
                idx = stack.index(worst)
                archive.append(worst)
                candidates = [n for n in LAYER_NAMES
                              if n not in stack and n not in archive]
                if candidates:
                    stack[idx] = candidates[0]
                else:
                    del stack[idx]
    return stack, archive, cov, flips, dice_passes


def settled(cov, flips):
    """Mean coverage over the 20 ticks after each flip (post-flip
    settled window), and mean over the last 50 ticks."""
    post = []
    for f in flips:
        post.extend(cov[f:f + 20])
    s_post = sum(post) / len(post) if post else 0.0
    s_end = sum(cov[-50:]) / 50
    return s_post, s_end


def main():
    print("=" * 62)
    print("Q18: plateau-anticipation dice release vs dead-weight")
    print("=" * 62)

    results = {}
    for mode in ("endo", "exo"):
        for gate in (False, True):
            stack, archive, cov, flips, passes = run(mode, gate)
            s_post, s_end = settled(cov, flips)
            arm = f"{mode}-{'RELEASE' if gate else 'BASE'}"
            results[arm] = (flips, passes, s_post, s_end)
            print(f"\n[{arm}] flips {len(flips)} at {flips[:10]}")
            print(f"[{arm}] dice passes {passes}/{TICKS}")
            print(f"[{arm}] post-flip settled {s_post:.4f} | "
                  f"final-50 {s_end:.4f}")

    eb, er = results["endo-BASE"], results["endo-RELEASE"]
    xb, xr = results["exo-BASE"], results["exo-RELEASE"]
    save_e = eb[1] - er[1]
    drop_e = (eb[2] - er[2]) * 100  # percentage points
    save_x = xb[1] - xr[1]
    drop_x = (xb[2] - xr[2]) * 100

    c1 = save_e > 0 and drop_e <= 1.0
    c2 = not (save_x > 0 and drop_x <= 1.0)

    print(f"\nC1 (endo: savings>0 at <=1.0pp coverage drop): "
          f"{'PASS' if c1 else 'FAIL'} — saved {save_e} passes, "
          f"coverage {drop_e:+.2f}pp")
    print(f"C2 (exo: no free savings — law reproduced):      "
          f"{'PASS' if c2 else 'FAIL'} — saved {save_x} passes, "
          f"coverage {drop_x:+.2f}pp")
    ok = c1 and c2

    verdict = (
        "PASS: plateau anticipation is exploitable — releasing dice "
        "pressure between the observable saturation alert and the "
        "endogenous flip saves passes at <=1pp settled-coverage cost, "
        "and the same release is not free under exogenous flips"
        if ok else
        "FAIL: the anticipation signal does not convert into a "
        "cost win (or the exogenous contrast breaks) — dead-weight-"
        "in-place remains unbeaten even in the endogenous regime")
    print(verdict)

    receipt = hashlib.sha256(canonical([
        "q18-plateau-release",
        {a: [results[a][0], results[a][1],
             f"{results[a][2]:.6f}", f"{results[a][3]:.6f}"]
         for a in sorted(results)},
        f"{save_e}", f"{drop_e:.4f}", f"{save_x}", f"{drop_x:.4f}",
        verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
