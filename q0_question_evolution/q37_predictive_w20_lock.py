#!/usr/bin/env python3
"""
Q37: WHY DOES W20 COLLAPSE ALL CLOSED-LOOP TARGETS TO ONE ORBIT
(TARGET-INSENSITIVE CONVERGENCE, q36), AND CAN A PREDICTIVE
CONTROLLER (ERROR INTEGRATED OVER A 2W HORIZON) BREAK THE LOCK TO
HIT ARBITRARY TARGETS AT W20?
q36 found: at W=20/step 0.20, every target 9-13 converges to the
SAME trace (10 flips, 64a94184) — controllability without
steerability — while W=40 spreads (10..13) and W=10 jumps to 14.
q36's hypothesis: period-locking of the s-dial to the flip cadence
(s oscillation period vs dwell DWELL=20).

Arms (frozen 8x24 space, q22 limit gate armed exactly as q25-q36,
CAPACITY=70, 400 ticks):
  NOGATE       - anchor, byte-comparable to q27-q36 (8 flips,
                 end50 0.648000)
  BASE         - q22 gate, unbiased compress (7 flips, drop
                 <=1.0pp)
  FIXED(1.0)   - full per-cell protection, q33-q36 signature
                 (16 flips, end50 0.6760)
  CL(t,20)     - q36 parity reactive controller at W20: err =
                 t*W/T - window_flips, s +- step, targets 9-13.
  PRED(t,20)   - predictive controller at W20, error integrated
                 over a 2W horizon: err = t*(2W)/T - flips in the
                 last 2W ticks, s +- step per window, s0=1.0,
                 targets 9-13. Integral horizon spans the whole
                 dwell cycle (DWELL=20), so the controller sees a
                 full flip period instead of half of one.

Claims (honest, falsifiable):
  C1 (the lock reproduces): all five CL(t,20) arms land the same
     flip count and identical held-set trace (q36's collapse,
     ~10 flips / 64a94184). If they diverge, the lock is not
     reproducible and this experiment's premise is void.
  C2 (prediction breaks the lock): the PRED arms' realized
     cadences SPREAD across targets (>= 3 distinct flip counts
     over targets 9-13) AND >= 3 targets land within +-1 flip of
     their request. PASS = steerability restored at W20; FAIL =
     the lock survives integral error (structural target-
     insensitivity, not a horizon artifact).
  C3 (anchors + determinism): NOGATE reproduces the frozen anchor
     (8 flips, supply 98, end50 0.648000); BASE holds the q22 law
     (drop <= 1.0pp, savings >= 70%); FIXED(1.0) matches the
     q33-q36 signature (16 flips, end50 0.6760); CL and PRED arms
     rerun twice are byte-identical; PRED traces differ across
     targets (else C2's "spread" would be vacuous).

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
W = 20
STEP = 0.20


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


def run(mode, strength=None, target=None, s0=None, window=W, horizon=None):
    """mode: None = no gate; 'skip' = q22 unbiased; 'wdial' = fixed
    per-cell weight dial at `strength`; 'cl' = reactive controller
    (err over one window); 'pred' = predictive controller (err
    integrated over `horizon` ticks = 2W default)."""
    step = STEP
    horiz = horizon if horizon is not None else 2 * window
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
    flip_marks = []          # (tick, kind) for horizon accounting
    for k in range(TICKS):
        if mode in ("cl", "pred") and k > 0 and k % window == 0:
            if mode == "cl":
                err = target * window / TICKS - len(
                    [1 for t, _ in flip_marks if k - window <= t < k])
            else:
                err = target * horiz / TICKS - len(
                    [1 for t, _ in flip_marks if k - horiz <= t < k])
            if err > 0:
                s = min(1.0, s + step)
            elif err < 0:
                s = max(0.0, s - step)
            s_hist.append((k, round(s, 2)))
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
                    if mode in ("wdial", "cl", "pred") and armed_now and s > 0.0:
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
            flip_marks.append((k + 1, "flip"))
            uni = _other_half(uni)
            dwell = 0
    end = sum(cov[-50:]) / 50
    return dict(end=end, flips=len(flips), passes=dict(passes), armed=armed,
                cells_saved=cells_saved, supply=len(supply_union),
                n_q=len(fps), cov=cov, flips_at=flips,
                trace=trace.hexdigest(), s_hist=s_hist, s_end=round(s, 2))


def main():
    print("=" * 62)
    print("Q37: why does W20 collapse all CL targets to one orbit —")
    print("can a predictive controller (err integrated over 2W,")
    print("spanning the full DWELL=20 flip period) break the lock")
    print("and steer cadence target-by-target at W20?")
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

    cl = {t: run("cl", target=t, s0=1.0, window=W) for t in TARGETS}
    pred = {t: run("pred", target=t, s0=1.0, window=W) for t in TARGETS}

    for tag, d in (("CL ", cl), ("PRED", pred)):
        for t in TARGETS:
            r = d[t]
            path = " ".join(f"{sv:.2f}" for _, sv in r["s_hist"][:10])
            print(f"[{tag} t{t:<2d} W20] flips {r['flips']:2d} "
                  f"end50 {r['end']:.4f} s_end {r['s_end']:.2f} "
                  f"path {path} trace8 {r['trace'][:8]}")

    # determinism: rerun samples
    det_pairs = [(cl[11], run("cl", target=11, s0=1.0, window=W)),
                 (pred[9], run("pred", target=9, s0=1.0, window=W)),
                 (pred[13], run("pred", target=13, s0=1.0, window=W))]
    det_ok = all(a["trace"] == b["trace"] and a["flips"] == b["flips"]
                 for a, b in det_pairs)

    # C1: the lock reproduces — all CL(.,20) arms identical
    cl_traces = {r["trace"] for r in cl.values()}
    cl_flips = {r["flips"] for r in cl.values()}
    c1 = len(cl_traces) == 1 and len(cl_flips) == 1

    # C2: prediction restores steerability
    pred_flips = sorted({r["flips"] for r in pred.values()})
    n_distinct = len(pred_flips)
    hits = sum(1 for t in TARGETS if abs(pred[t]["flips"] - t) <= 1)
    c2 = n_distinct >= 3 and hits >= 3

    # C3: anchors + determinism + PRED non-vacuous spread
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    law_ok = base_drop <= 1.0 and base_save >= 70.0
    f1_ok = (fixed1["flips"] == 16 and abs(fixed1["end"] - 0.6760) < 1e-9)
    pred_spread = len({r["trace"] for r in pred.values()}) >= 3
    c3 = anchor_ok and law_ok and f1_ok and det_ok and pred_spread

    print("\n" + "-" * 62)
    print(f"C1 lock reproduces at W20 (CL traces {len(cl_traces)}, flips "
          f"{sorted(cl_flips)}):                              "
          f"{'PASS' if c1 else 'FAIL'}")
    print(f"C2 PRED spreads ({n_distinct} distinct flip counts {pred_flips}) "
          f"and homes targets (hits {hits}/5 >=3):            "
          f"{'PASS' if c2 else 'FAIL'}")
    print(f"C3 anchors ({anchor_ok}) + q22 law ({law_ok}) + FIXED(1) sig "
          f"({f1_ok}) + det ({det_ok}) + PRED spread "
          f"({pred_spread}): {'PASS' if c3 else 'FAIL'}")

    s_path_cl = " ".join(f"{sv:.2f}" for _, sv in cl[11]["s_hist"])
    s_path_pd = " ".join(f"{sv:.2f}" for _, sv in pred[11]["s_hist"])
    if c1 and c2 and c3:
        verdict = (
            f"PREDICTION BREAKS THE W20 LOCK (anchors intact): the "
            f"reactive controller reproduces q36's collapse exactly "
            f"({sorted(cl_flips)[0]} flips, one trace) — its one-window "
            f"error signal is aliased to half the flip period (W=DWELL), "
            f"so every target reads the same sign sequence and the dial "
            f"locks to one orbit (s-path {s_path_cl}). Integrating error "
            f"over 2W (a full dwell period) de-aliases the signal: PRED "
            f"realizes {pred_flips} across targets 9-13 with {hits}/5 "
            f"within +-1, and the s-paths diverge ({s_path_pd}). Law: "
            f"the q36 target-insensitivity was a SAMPLING artifact of "
            f"the controller, not of the plant — steerability at W20 "
            f"requires the control horizon to span the flip period; "
            f"Nyquist for tick-stacks: sample the error at >= 2x the "
            f"event you are regulating."
        )
    elif c1 and not c2 and c3:
        verdict = (
            f"THE LOCK SURVIVES INTEGRAL ERROR (anchors intact): the "
            f"reactive collapse reproduces ({sorted(cl_flips)[0]} flips, "
            f"one trace), and the 2W-horizon predictive controller STILL "
            f"fails to steer ({pred_flips} distinct, {hits}/5 homed; "
            f"s-path {s_path_pd}). The target-insensitivity at W20 is "
            f"structural — the held-set path-dependence (q34/q35) "
            f"dominates any linear error feedback at this window: the "
            f"plant's gain from s to cadence is effectively zero along "
            f"the locked orbit, so no scalar dial schedule computed "
            f"from flip counts alone can separate targets. Steering "
            f"cadence at W20 needs state feedback (held-set composition), "
            f"not a smarter error integral."
        )
    else:
        verdict = (
            "PREMISE OR ANCHORS BROKE: numbers reported as-is, no law "
            "claimed beyond what holds. If C1 failed, q36's collapse is "
            "not reproducible — investigate harness drift first."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q37-predictive-w20-lock",
        [nogate["flips"], f"{nogate['end']:.6f}"],
        [base["flips"], f"{base['end']:.6f}"],
        [fixed1["flips"], f"{fixed1['end']:.6f}", fixed1["trace"][:12]],
        [[t, cl[t]["flips"], cl[t]["trace"][:12]] for t in TARGETS],
        [[t, pred[t]["flips"], f"{pred[t]['end']:.6f}",
          pred[t]["s_end"], pred[t]["trace"][:12]] for t in TARGETS],
        [c1, c2, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c2 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
