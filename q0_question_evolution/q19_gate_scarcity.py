#!/usr/bin/env python3
"""
Q19 PLATEAU GATE UNDER SCARCITY: q18 was the first gate win in the arc —
in the ENDOGENOUS regime the plateau-release gate (skip dice for H ticks
after the observable saturation alert, resume when coverage < SAT) saved
12.25% of dice passes at +0.17pp settled coverage. But q18 ran at
CAPACITY 70, comfortably above the plateau held-set size, so the release
never risked eviction-induced coverage loss. q15/q14 showed the cost axis
behaves differently under STRESS (capacity 62 at FACTS=120). q19 asks the
natural follow-up: does the q18 win SURVIVE SCARCITY?

Mechanism under test — release under capacity stress:
  As capacity shrinks, hash-eviction churn grows and the plateau
  coverage falls toward/below SAT. Two failure modes are possible:
  (a) coverage plateaus BELOW SAT -> dwell never arms -> no alerts ->
      no savings (the q17 saturation-parameterization problem returns);
  (b) coverage plateaus above SAT but eviction churn makes the post-skip
      rebuild slower -> savings still accrue but coverage drops >1pp.
  Either would falsify robustness; only savings>0 at <=1.0pp drop at
  EVERY tested capacity passes.

Arms: endogenous regime, capacities {70 (q18 repro), 60, 52, 45},
each BASE vs RELEASE. Contrast: exogenous at every capacity (the gate
should never fire — coverage never dwells without a reactive universe).

Claims (honest, falsifiable):
  C1 (endo, all caps): savings > 0 AND settled post-flip coverage
     within 1.0pp of BASE at EVERY capacity.
  C2 (exo, all caps): no free savings anywhere (law reproduction).

Deterministic, no RNG, stdlib only, fnv1a, receipt sha256.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 400
DWELL = 20
LEAD = 5
HORIZON = 5
EXO_FLIP = TICKS // 2
CAPACITIES = [70, 60, 52, 45]

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]

# SAT is re-parameterized per capacity from a pre-run plateau probe
# (observable, no oracle): measure BASE plateau mean coverage, then set
# SAT = max(0.10, plateau_mean - 0.05) rounded to 2dp. This mirrors the
# q17 lesson (SAT must sit under the observed plateau) and keeps the
# gate honest when scarcity drags the plateau down.
PROBE_TICKS = 150


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


def run_layer(name, held, k, capacity):
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
    elif name == "compress":
        if len(held) > capacity:
            scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
            held = frozenset(sorted(scored[:capacity]))
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


def probe_plateau(capacity):
    """BASE run, exogenous-free (no flips before probe end matters:
    use endo with DWELL never reached by forcing huge DWELL) to read
    the observable plateau coverage at this capacity."""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    held = frozenset()
    cov = []
    uni = HALF_A
    for k in range(PROBE_TICKS):
        for layer in stack:
            held = run_layer(layer, held, k, capacity)
        cov.append(len(held & uni) / len(uni))
        if k > 0 and k % 30 == 0:
            active = [(0, n) for n in stack if n != "dice"]
            # benefit accounting neutral in probe: keep stack fixed
            _ = active, archive
    tail = cov[-50:]
    return sum(tail) / len(tail)


def run(mode, gate, capacity, sat):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    cov = []
    flips = []
    dice_passes = 0
    uni = HALF_A
    dwell = 0
    skip = 0
    for k in range(TICKS):
        if gate and skip == 0 and dwell >= DWELL - HORIZON + 1 and dwell < DWELL:
            skip = HORIZON
        if gate and cov and cov[-1] < sat:
            skip = 0
        if not (gate and skip > 0):
            held = run_layer("dice", held, k, capacity)
            dice_passes += 1
        if gate and skip > 0:
            skip -= 1
        for layer in ("wiring", "compress", "mutate", "edges"):
            held = run_layer(layer, held, k, capacity)
        c = len(held & uni) / len(uni)
        cov.append(c)
        if mode == "exo":
            if k == EXO_FLIP - 1:
                flips.append(k + 1)
                uni = _other_half(uni)
        else:
            dwell = dwell + 1 if c >= sat else 0
            if dwell >= DWELL:
                flips.append(k + 1)
                uni = _other_half(uni)
                dwell = 0
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
    post = []
    for f in flips:
        post.extend(cov[f:f + 20])
    s_post = sum(post) / len(post) if post else 0.0
    s_end = sum(cov[-50:]) / 50
    return s_post, s_end


def main():
    print("=" * 62)
    print("Q19: plateau-release gate under capacity scarcity")
    print("=" * 62)

    receipt_parts = {}
    all_c1 = True
    all_c2 = True

    for cap in CAPACITIES:
        plateau = probe_plateau(cap)
        sat = round(max(0.10, plateau - 0.05), 2)
        print(f"\n--- capacity {cap}: probe plateau {plateau:.3f} -> SAT {sat} ---")
        results = {}
        for mode in ("endo", "exo"):
            for gate in (False, True):
                stack, archive, cov, flips, passes = run(mode, gate, cap, sat)
                s_post, s_end = settled(cov, flips)
                arm = f"{mode}-{'RELEASE' if gate else 'BASE'}"
                results[arm] = (flips, passes, s_post, s_end)
                print(f"[{arm}] flips {len(flips)} | passes {passes}/{TICKS} | "
                      f"post-flip {s_post:.4f} | final-50 {s_end:.4f}")

        eb, er = results["endo-BASE"], results["endo-RELEASE"]
        xb, xr = results["exo-BASE"], results["exo-RELEASE"]
        save_e = eb[1] - er[1]
        drop_e = (eb[2] - er[2]) * 100
        save_x = xb[1] - xr[1]
        drop_x = (xb[2] - xr[2]) * 100

        c1 = save_e > 0 and drop_e <= 1.0
        c2 = not (save_x > 0 and drop_x <= 1.0)
        all_c1 = all_c1 and c1
        all_c2 = all_c2 and c2
        print(f"C1 cap {cap}: {'PASS' if c1 else 'FAIL'} — saved {save_e} passes, "
              f"coverage {drop_e:+.2f}pp")
        print(f"C2 cap {cap}: {'PASS' if c2 else 'FAIL'} — saved {save_x} passes, "
              f"coverage {drop_x:+.2f}pp")
        receipt_parts[f"cap{cap}"] = [
            f"sat{sat}", f"plateau{plateau:.4f}",
            [[results[a][0], results[a][1],
              f"{results[a][2]:.6f}", f"{results[a][3]:.6f}"]
             for a in sorted(results)],
        ]

    ok = all_c1 and all_c2
    verdict = (
        "PASS: the q18 plateau-release win is robust to scarcity — "
        "savings>0 at <=1pp coverage cost at every tested capacity, "
        "and never free under exogenous flips"
        if ok else
        "FAIL: the q18 win does not survive scarcity at some capacity "
        "(no savings, or coverage cost >1pp, or the exo contrast broke) "
        "— the release gate is capacity-brittle")
    print(f"\n{verdict}")

    parts = {k: receipt_parts[k] for k in sorted(receipt_parts)}
    receipt = hashlib.sha256(canonical([
        "q19-plateau-release-scarcity",
        parts,
        f"{all_c1}", f"{all_c2}", verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
