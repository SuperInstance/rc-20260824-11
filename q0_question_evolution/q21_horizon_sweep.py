#!/usr/bin/env python3
"""
Q21 HORIZON SWEEP: q18's release gate (skip dice passes on saturation
alert, resume on observable coverage break) is the first cost win in
the arc — 12.25% dice-pass savings at <=1pp coverage cost. But H=5 was
ARBITRARY, and q20 sharpened why it matters: the gate's entire value
is ANTICIPATION (arming at dwell >= DWELL-H+1, BEFORE the flip), so
the horizon length is the load-bearing parameter. q21 sweeps it.

Two opposing forces, both structural:
  - LARGER H arms EARLIER: a dwell is visible sooner, so more dwells
    are caught before they either flip or break (more savings windows).
  - LARGER H commits LONGER: q17 measured recall 0.150 — most dwells
    re-arm without flipping — so a longer skip bleeds dice pressure
    on plateaus the universe never consumes (coverage risk).

H sweep: 3, 5, 8, 12, 16 (DWELL=20 bounds H < 20). Skip length = H
(as in q18: release until the flip is due). Contrast: exogenous
regime at the endo-optimal H (law reproduction — no free savings).

Claims (honest, falsifiable):
  C1 (endo): H=5 is NOT already optimal — some H != 5 achieves
     savings >= savings(5) + 5 passes at <= 1.0pp settled-coverage
     drop. If no H beats H=5 at that margin, FAIL (the arbitrary
     constant was accidentally near-optimal).
  C2 (exo at best endo H): no free savings (drop > 1.0pp or
     savings <= 0) — law reproduced.

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
SAT = 0.60
HS = [3, 5, 8, 12, 16]
EXO_FLIP = TICKS // 2
EXO_H = None  # filled at runtime with best endo H

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


def run(mode: str, horizon: int | None):
    """mode 'endo'|'exo'; horizon None = dead-weight-in-place baseline,
    else the q18 release gate with H=horizon (arm at dwell >=
    DWELL-H+1, skip dice for H ticks, resume on coverage < SAT)."""
    gate = horizon is not None
    H = horizon or 0
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    cov = []
    flips = []
    dice_passes = 0
    armed = 0
    uni = frozenset(range(FACTS // 2))
    dwell = 0
    skip = 0
    for k in range(TICKS):
        if gate and skip == 0 and dwell >= DWELL - H + 1 and dwell < DWELL:
            skip = H
            armed += 1
        if gate and cov and cov[-1] < SAT:
            skip = 0
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
    return stack, archive, cov, flips, dice_passes, armed


def settled(cov, flips):
    post = []
    for f in flips:
        post.extend(cov[f:f + 20])
    s_post = sum(post) / len(post) if post else 0.0
    s_end = sum(cov[-50:]) / 50
    return s_post, s_end


def main():
    print("=" * 62)
    print("Q21: anticipation-horizon sweep of the release gate")
    print("=" * 62)

    _, _, cov_b, flips_b, passes_b, _ = run("endo", None)
    s_post_b, s_end_b = settled(cov_b, flips_b)
    print(f"\n[endo-BASE] flips {len(flips_b)} passes {passes_b} "
          f"post {s_post_b:.4f} end {s_end_b:.4f}")

    results = {}
    for H in HS:
        _, _, cov, flips, passes, armed = run("endo", H)
        s_post, s_end = settled(cov, flips)
        save = passes_b - passes
        drop = (s_post_b - s_post) * 100
        results[H] = (flips, passes, armed, save, drop, s_end)
        print(f"\n[endo-H{H:<2}] flips {len(flips)} armed {armed} "
              f"passes {passes} saved {save:+4d} ({save / TICKS:.2%}) "
              f"drop {drop:+.2f}pp end {s_end:.4f}")

    h5_save, h5_drop = results[5][3], results[5][4]
    eligible = {h: r for h, r in results.items() if r[4] <= 1.0}
    best_h, best = max(eligible.items(), key=lambda kv: kv[1][3]) if eligible else (5, results[5])
    c1 = any(h != 5 and r[3] >= h5_save + 5 and r[4] <= 1.0
             for h, r in results.items())

    _, _, xcov_b, xflips_b, xpasses_b, _ = run("exo", None)
    x_post_b, _ = settled(xcov_b, xflips_b)
    _, _, xcov, xflips, xpasses, xarmed = run("exo", best_h)
    x_post, _ = settled(xcov, xflips)
    x_save = xpasses_b - xpasses
    x_drop = (x_post_b - x_post) * 100
    c2 = not (x_save > 0 and x_drop <= 1.0)
    print(f"\n[exo-H{best_h}] armed {xarmed} saved {x_save} "
          f"drop {x_drop:+.2f}pp (flips {len(xflips)})")

    print(f"\nbest endo H (drop<=1.0pp): H={best_h} saved {best[3]} "
          f"drop {best[4]:+.2f}pp | H=5 saved {h5_save} drop {h5_drop:+.2f}pp")
    print(f"C1 (some H != 5 beats H=5 by >=5 passes at <=1.0pp): "
          f"{'PASS' if c1 else 'FAIL'}")
    print(f"C2 (exo at H={best_h}: no free savings):               "
          f"{'PASS' if c2 else 'FAIL'}")
    ok = c1 and c2

    curve = ", ".join(f"H{h}:{r[3]}/{r[4]:+.2f}pp" for h, r in sorted(results.items()))
    verdict = (
        f"PASS: the anticipation window is tunable — H={best_h} beats the "
        f"arbitrary H=5 ({best[3]} vs {h5_save} saved passes at "
        f"{best[4]:+.2f}pp drop); curve [{curve}]" if ok else
        f"FAIL (honest negative): H=5 already sits at/near the optimum — "
        f"curve [{curve}] — the arbitrary constant was accidentally "
        f"right, or every larger window bleeds coverage on unflipped "
        f"plateaus faster than it saves passes"
    )
    print(verdict)

    receipt = hashlib.sha256(canonical([
        "q21-horizon-sweep",
        {str(h): [len(results[h][0]), results[h][1], results[h][2],
                  f"{results[h][3]}", f"{results[h][4]:.4f}",
                  f"{results[h][5]:.6f}"] for h in sorted(results)},
        f"{h5_save}", f"{best_h}", f"{best[3]}", f"{best[4]:.4f}",
        f"{x_save}", f"{x_drop:.4f}",
        verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
