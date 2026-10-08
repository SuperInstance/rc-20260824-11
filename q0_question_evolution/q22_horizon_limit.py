#!/usr/bin/env python3
"""
Q22 LIMIT CASE: q21 swept the release gate's horizon H in {3,5,8,12,16}
and found savings scale monotonically (8.5%..58.0% at <=1.0pp drop,
C1 PASS everywhere) — with H=16 the best. q21's own closing question:
is the RESUME CLAUSE ALONE (dwell-armed at dwell>=1, skip-until-break,
i.e. H=DWELL=20, the limit) the optimum — and does the savings curve
saturate or INVERT as H -> DWELL?

Two opposing forces at the boundary:
  - At H=DWELL the gate arms on the FIRST saturated tick (dwell>=1),
    so every plateau — flipping or not — opens a skip window: maximum
    savings windows (q17 recall 0.150 means ~85% re-arm without flip).
  - The resume-on-break clause (cov < SAT -> skip=0) is the only thing
    holding coverage; q21 credited IT, not the horizon, with safety.
    At the limit this is tested hardest: the stack's dice layer is
    silent for the ENTIRE plateau unless coverage visibly breaks.

Contrast arm: exogenous regime at the limit gate — the gate never
arms without a reactive universe (law reproduction; q21 showed exo
arms 0 times even at H=16).

Claims (honest, falsifiable):
  C1 (saturation vs inversion): the savings curve does NOT invert at
     the boundary — the limit gate (H=DWELL, skip-until-break) saves
     >= savings(H=16) at <= 1.0pp settled-coverage drop. If savings
     fall below H=16's, or drop exceeds 1.0pp, FAIL.
  C2 (no cliff): the limit gate's settled post-flip coverage drop vs
     baseline stays <= 1.0pp (the resume clause holds at the limit).
  C3 (exo): exogenous regime saves nothing under the limit gate.

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
HS = [16, 18, 19]          # q21's boundary approach
LIMIT = DWELL              # H = 20: arm at dwell>=1, skip-until-break
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


def run(mode: str, horizon: int | None):
    """mode 'endo'|'exo'; horizon None = baseline. horizon == DWELL is
    the LIMIT gate: arm at dwell >= 1, skip has NO fixed length (only
    the resume-on-break clause can end it). Otherwise q18 gate with H."""
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
        arm_threshold = 1 if H == DWELL else DWELL - H + 1
        if gate and skip == 0 and dwell >= arm_threshold and dwell < DWELL:
            skip = H if H < DWELL else TICKS  # limit: skip-until-break
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
    print("Q22: H->DWELL limit — resume clause alone")
    print("=" * 62)

    _, _, cov_b, flips_b, passes_b, _ = run("endo", None)
    s_post_b, s_end_b = settled(cov_b, flips_b)
    print(f"\n[endo-BASE] flips {len(flips_b)} passes {passes_b} "
          f"post {s_post_b:.4f} end {s_end_b:.4f}")

    results = {}
    for label, H in [(f"H{H}", H) for H in HS] + [("LIMIT", LIMIT)]:
        _, _, cov, flips, passes, armed = run("endo", H)
        s_post, s_end = settled(cov, flips)
        save = passes_b - passes
        drop = (s_post_b - s_post) * 100
        results[label] = (flips, passes, armed, save, drop, s_end)
        print(f"\n[endo-{label:<5}] flips {len(flips)} armed {armed} "
              f"passes {passes} saved {save:+4d} ({save / TICKS:.2%}) "
              f"drop {drop:+.2f}pp end {s_end:.4f}")

    lim_flips, lim_passes, lim_armed, lim_save, lim_drop, lim_end = results["LIMIT"]
    h16_save, h16_drop = results["H16"][3], results["H16"][4]
    c1 = lim_save >= h16_save and lim_drop <= 1.0
    c2 = lim_drop <= 1.0
    c3_save = lim_drop_exo = None
    _, _, xcov_b, xflips_b, xpasses_b, _ = run("exo", None)
    x_post_b, _ = settled(xcov_b, xflips_b)
    _, _, xcov, xflips, xpasses, xarmed = run("exo", LIMIT)
    x_post, _ = settled(xcov, xflips)
    x_save = xpasses_b - xpasses
    x_drop = (x_post_b - x_post) * 100
    c3 = not (x_save > 0 and x_drop <= 1.0)
    print(f"\n[exo-LIMIT] armed {xarmed} saved {x_save} "
          f"drop {x_drop:+.2f}pp (flips {len(xflips)})")

    print(f"\n[limit vs H16] saved {lim_save} vs {h16_save} | "
          f"drop {lim_drop:+.2f}pp vs {h16_drop:+.2f}pp")
    print(f"C1 (no inversion: LIMIT saves >= H16 at <=1.0pp): "
          f"{'PASS' if c1 else 'FAIL'}")
    print(f"C2 (no cliff: LIMIT drop <= 1.0pp):              "
          f"{'PASS' if c2 else 'FAIL'}")
    print(f"C3 (exo: no free savings at LIMIT):              "
          f"{'PASS' if c3 else 'FAIL'}")
    ok = c1 and c2 and c3

    curve = ", ".join(f"{lab}:{r[3]}/{r[4]:+.2f}pp" for lab, r in sorted(results.items()))
    if ok:
        verdict = (
            f"PASS: the savings curve does not invert at the boundary — "
            f"the limit gate (H=DWELL, resume clause alone) saves "
            f"{lim_save} ({lim_save / TICKS:.2%}) vs H16's {h16_save} "
            f"({h16_save / TICKS:.2%}) at {lim_drop:+.2f}pp; curve "
            f"[{curve}] — the resume-on-break clause, not the horizon, "
            f"is the whole safety story"
        )
    else:
        why = []
        if lim_save < h16_save:
            why.append(f"savings INVERT at the boundary ({lim_save} < "
                       f"H16's {h16_save})")
        if lim_drop > 1.0:
            why.append(f"coverage CLIFF at the boundary ({lim_drop:+.2f}pp "
                       f"> 1.0pp — the resume clause does NOT hold when "
                       f"the dice layer is silent for whole plateaus)")
        verdict = (f"FAIL (honest negative): {'; '.join(why)}; curve "
                   f"[{curve}]")
    print(verdict)

    receipt = hashlib.sha256(canonical([
        "q22-horizon-limit",
        {lab: [len(r[0]), r[1], r[2], f"{r[3]}", f"{r[4]:.4f}",
               f"{r[5]:.6f}"] for lab, r in sorted(results.items())},
        f"{h16_save}", f"{lim_save}", f"{lim_drop:.4f}",
        f"{x_save}", f"{x_drop:.4f}",
        verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
