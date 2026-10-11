#!/usr/bin/env python3
"""
Q36: IS THE REACHABLE CADENCE SET UNDER ARMED CONTROL EXACTLY
{7..13} U {16}, AND DOES THE 13-FLOOR HAVE THE SAME
PATH-DEPENDENCE MECHANISM — CAN ANY CONTROLLER FROM ABOVE REACH
10-12 (FASTER STEP, SMALLER WINDOW), OR IS THE BLEED SIDE
QUANTIZED BY ARMING-WINDOW GRANULARITY?
q35 closed the upward side: cold-low cannot be raised except at
the fixed full-protection point (16 flips), and the CL controller
from s0=1.0 saturates at 13 (targets 13 and 10 both land 13).
The open question: is {7..13} U {16} the WHOLE reachable set, and
is the 13-floor structural (path-dependence) or an artifact of
the control granularity (WINDOW=40, STEP=0.10, q34 parity)?

Arms (frozen 8x24 space, q22 limit gate armed exactly as q25-q35,
CAPACITY=70, 400 ticks):
  NOGATE        - anchor, byte-comparable to q27-q35 (8 flips,
                  end50 0.648000)
  BASE          - q22 gate, unbiased compress (7 flips, drop
                  <=1.0pp)
  FIXED(1.0)    - full per-cell protection, q33-q35 signature
                  (16 flips, end50 0.6760)
  CL(t,W,S)     - q34/q35 closed-loop controller from s0=1.0,
                  err = t*W/TICKS - window_flips, s +- S per
                  window, clamped [0,1]. Grid: targets t in
                  {9, 10, 11, 12, 13} x (W, S) in {(40, 0.10)
                  q34 parity, (20, 0.20) 2x finer window + 2x
                  step, (10, 0.40) 4x finer window + 4x step}.

Claims (honest, falsifiable):
  C1 (the gap is real): NO CL arm from s0=1.0 lands its realized
     cadence strictly inside 9..12 (i.e. the set {9,10,11,12} is
     unreachable from above). If any arm lands in 9..12, C1 FAILS
     and the reachable set is denser than {7..13} U {16}.
  C2 (granularity is not the mechanism): if C1 holds, the finest
     grid (W=10, S=0.40) still floors at 13-or-above / or bleeds
     to <= 8 (below the gap, through it only by OVERSHOOT —
     landing at 7/8 means the controller stepped over the gap,
     which still proves no stable stop inside 9..12). Quantization
     by window would predict a finer window CAN stop inside the
     gap; if none of the three grids stops there, granularity is
     ruled out and the floor is path-dependent (held-set state,
     not control clock). PASS = no grid stops inside 9..12; FAIL
     = some grid stops there.
     [C1 and C2 are the same observable; kept separate for
     honesty: C1 over ALL arms, C2 over grid granularity.]
  C3 (anchors + determinism): NOGATE reproduces the frozen anchor
     (8 flips, supply 98, end50 0.648000); BASE holds the q22 law
     (drop <= 1.0pp, savings >= 70%); FIXED(1.0) matches the
     q33/q34/q35 signature (16 flips, end50 0.6760); every CL arm
     run twice is byte-identical.

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
FP_SIZE = 24
N_Q = 8

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]

TARGETS = (9, 10, 11, 12, 13)
GRIDS = ((40, 0.10), (20, 0.20), (10, 0.40))
WINDOW = 40                    # q34 parity default window
STEP_FOR = {40: 0.10, 20: 0.20, 10: 0.40}


def footprint(text: str, max_cells: int = FP_SIZE) -> frozenset:
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        cells.add(fnv1a(f"{text}#{salt}") % FACTS)
        salt += 1
    return frozenset(cells)


PEER_FP = footprint("peer-agent-shared-docs")

HALF_A = frozenset(range(FACTS // 2))
HALF_B = frozenset(range(FACTS // 2, FACTS))


def _other_half(uni):
    return HALF_B if uni == HALF_A else HALF_A


def _rank(f, k):
    return fnv1a(canonical(["self", "evict", f, k]))


def _weight(f, k):
    return fnv1a(canonical(["self", "prot", f, k])) / 0x100000000


def run(mode, strength=None, target=None, s0=None, window=WINDOW):
    """mode: None = no gate; 'skip' = q22 unbiased; 'wdial' = fixed
    per-cell weight dial at `strength`; 'cl' = closed-loop with the
    given window/step (step derived from the grid, passed in)."""
    step = STEP_FOR[window]
    fps = [footprint(f"q{i}") for i in range(N_Q)]
    supply_union = frozenset().union(*fps)
    held = frozenset()
    cov = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    cells_saved = 0
    trace = hashlib.sha256()
    uni = HALF_A
    dwell = 0
    flips = []
    s = float(strength if strength is not None else (s0 if s0 is not None else 0.0))
    s_hist = []
    w_flips = 0
    for k in range(TICKS):
        if mode == "cl" and k > 0 and k % window == 0:
            target_rate = target * window / TICKS
            err = target_rate - w_flips
            if err > 0:
                s = min(1.0, s + step)
            elif err < 0:
                s = max(0.0, s - step)
            s_hist.append((k, round(s, 2)))
            w_flips = 0
        if mode is not None:
            if skip == 0 and 1 <= dwell < DWELL:
                skip = TICKS
                armed += 1
            if cov and cov[-1] < SAT:
                skip = 0
        armed_now = skip > 0
        for layer in ("dice", "compress", "mutate", "edges"):
            if layer == "dice":
                fp = fps[fnv1a(canonical(["self", "dice", k])) % len(fps)]
                if armed_now:
                    cells_saved += len(fp)
                else:
                    held = held | fp
                    passes["dice"] += 1
            elif layer == "compress":
                if len(held) > CAPACITY:
                    protected = frozenset()
                    if mode in ("wdial", "cl") and armed_now and s > 0.0:
                        protected = frozenset(
                            f for f in held
                            if f in supply_union and _weight(f, k) < s)
                    if protected:
                        unprotected = held - protected
                        queue = (sorted(protected, key=lambda f: _rank(f, k))
                                 + sorted(unprotected,
                                          key=lambda f: _rank(f, k)))
                    else:
                        queue = sorted(held, key=lambda f: _rank(f, k))
                    held = frozenset(queue[:CAPACITY])
                passes["compress"] += 1
            elif layer == "mutate":
                fp = fps[fnv1a(canonical(["self", "mut", k])) % len(fps)]
                drop_n = min(6, len(held))
                drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "drop", f, k])))[:drop_n])
                held = (held - drops) | (fp - drops)
                passes["mutate"] += 1
            elif layer == "edges":
                held = held | PEER_FP
                passes["edges"] += 1
        if armed_now:
            skip -= 1
        trace.update(canonical(sorted(held)).encode())
        c = len(held & uni) / len(uni)
        cov.append(c)
        dwell = dwell + 1 if c >= SAT else 0
        if dwell >= DWELL:
            flips.append(k + 1)
            uni = _other_half(uni)
            dwell = 0
            w_flips += 1
    end = sum(cov[-50:]) / 50
    return dict(end=end, flips=len(flips), passes=dict(passes), armed=armed,
                cells_saved=cells_saved, supply=len(supply_union),
                n_q=len(fps), cov=cov, flips_at=flips,
                trace=trace.hexdigest(), s_hist=s_hist, s_end=round(s, 2))


def main():
    print("=" * 62)
    print("Q36: is the reachable cadence set under armed control exactly")
    print("{7..13} U {16} — can ANY controller from above reach 10-12")
    print("(finer window W=20/10, faster step 0.20/0.40), or is the")
    print("13-floor path-dependent rather than quantized by arming-")
    print("window granularity?")
    print("=" * 62)

    nogate = run(None)
    base = run("skip")
    fixed1 = run("wdial", strength=1.0)

    print(f"\n[NOGATE    ] flips {nogate['flips']:2d} end50 {nogate['end']:.4f} "
          f"supply {nogate['supply']}")
    base_save = base["cells_saved"] / (TICKS * FP_SIZE) * 100
    base_drop = (base["end"] - nogate["end"]) * 100
    print(f"[BASE      ] flips {base['flips']:2d} end50 {base['end']:.4f} "
          f"saved {base_save:5.2f}% drop {base_drop:+.2f}pp")
    print(f"[FIXED 1.0 ] flips {fixed1['flips']:2d} end50 {fixed1['end']:.4f} "
          f"armed {fixed1['armed']} trace8 {fixed1['trace'][:8]}")

    cl = {}
    for (w, st) in GRIDS:
        for t in TARGETS:
            r = run("cl", target=t, s0=1.0, window=w)
            cl[(t, w)] = r
            path = " ".join(f"{sv:.2f}" for _, sv in r["s_hist"][:10])
            print(f"[CL t{t:<2d} W{w:<2d}] flips {r['flips']:2d} "
                  f"end50 {r['end']:.4f} s_end {r['s_end']:.2f} "
                  f"path {path} trace8 {r['trace'][:8]}")

    # determinism: repeat a sample of CL arms across all grids
    det_pairs = [(cl[(10, 40)], run("cl", target=10, s0=1.0, window=40)),
                 (cl[(11, 20)], run("cl", target=11, s0=1.0, window=20)),
                 (cl[(9, 10)], run("cl", target=9, s0=1.0, window=10)),
                 (cl[(12, 10)], run("cl", target=12, s0=1.0, window=10))]
    det_ok = all(a["trace"] == b["trace"] and a["flips"] == b["flips"]
                 for a, b in det_pairs)

    # C1: no arm from s0=1.0 stops with realized cadence in 9..12
    in_gap = [(t, w) for (t, w), r in cl.items() if 9 <= r["flips"] <= 12]
    c1 = len(in_gap) == 0

    # C2: granularity ruled out — no grid, however fine, stops in the gap
    gap_by_grid = {w: [t for (t, ww), r in cl.items()
                       if ww == w and 9 <= r["flips"] <= 12]
                   for (w, _) in GRIDS}
    c2 = all(len(v) == 0 for v in gap_by_grid.values())

    # C3: anchors + determinism
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    law_ok = base_drop <= 1.0 and base_save >= 70.0
    f1_ok = (fixed1["flips"] == 16 and abs(fixed1["end"] - 0.6760) < 1e-9)
    c3 = anchor_ok and law_ok and f1_ok and det_ok

    print("\n" + "-" * 62)
    print(f"C1 no CL arm from s0=1.0 lands in 9..12 (in-gap arms: "
          f"{in_gap}):                       "
          f"{'PASS' if c1 else 'FAIL'}")
    print(f"C2 no grid (W40/W20/W10) stops inside the gap (per-grid: "
          f"{gap_by_grid}):          {'PASS' if c2 else 'FAIL'}")
    print(f"C3 anchors ({anchor_ok}) + q22 law ({law_ok}) + FIXED(1)==q33-35 "
          f"sig ({f1_ok}) + determinism ({det_ok}): "
          f"{'PASS' if c3 else 'FAIL'}")

    reached = sorted({r["flips"] for r in cl.values()})
    if c1 and c2 and c3:
        verdict = (
            f"THE GAP IS REAL AND NOT GRAVITY-QUANTIZED: across "
            f"{len(cl)} closed-loop arms from s0=1.0 (targets 9-13 x "
            f"W/S 40/0.10, 20/0.20, 10/0.40) the realized cadence set is "
            f"{reached} — nothing stops inside 9..12 at ANY control "
            f"granularity. The 13-floor survives a 4x-finer control "
            f"clock, so arming-window quantization is ruled out: the "
            f"floor is PATH-DEPENDENT, the same mechanism as q34/q35 — "
            f"cadence below 13 requires a held-set history that only "
            f"unbiased (cold-low) compression writes, and a controller "
            f"entering from s0=1.0 can only bleed DOWN THROUGH the gap "
            f"(overshoot to <= 8) or stop at 13, never settle inside it. "
            f"Reachable set under armed control: {sorted(reached + [16])} "
            f"(16 = the fixed full-protection point, q35)."
        )
    elif not (c1 and c2) and c3:
        hit = in_gap[0] if in_gap else None
        verdict = (
            f"THE GAP IS CROSSED AT FINER GRANULARITY (anchors intact): "
            f"arm {hit} lands {cl[hit]['flips']} flips — inside 9..12 — "
            f"so the q35 13-floor was an artifact of the W=40 control "
            f"clock, not a structural law. The reachable cadence set is "
            f"denser than {{7..13}} U {{16}}: {sorted(reached + [16])}. "
            f"Cadence IS continuously reachable from above once the "
            f"controller can re-decide within a single arming window."
        )
    else:
        verdict = (
            "ANCHOR BROKE: numbers reported as-is, no law claimed beyond "
            "what holds. Investigate harness drift before interpreting."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q36-cadence-gap-granularity",
        [nogate["flips"], f"{nogate['end']:.6f}"],
        [base["flips"], f"{base['end']:.6f}"],
        [fixed1["flips"], f"{fixed1['end']:.6f}", fixed1["trace"][:12]],
        [[t, w, cl[(t, w)]["flips"], f"{cl[(t, w)]['end']:.6f}",
          cl[(t, w)]["s_end"], cl[(t, w)]["trace"][:12]]
         for (w, _) in GRIDS for t in TARGETS],
        [c1, c2, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c2 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
