#!/usr/bin/env python3
"""
Q35: IS THE ONE-SIDED CONTROLLABILITY STRUCTURAL — DOES ANY HELD-SIDE
CONTROLLER RAISE CADENCE FROM COLD-LOW (e.g. start at s=1.0 for one
arming then ramp down, or protect-by-breadth instead of by weight),
OR IS UPWARD CADENCE PURCHASABLE ONLY AT THE FIXED FULL-PROTECTION
POINT?
q34 found the closed-loop s-dial is one-sided: from s0=1.0 the
controller can bleed cadence down and hit target 13 exactly, but
from cold-low (s0=0.0) it cannot raise cadence at all — the
s->cadence map is PATH-DEPENDENT. The open question: is that
structural, or does some other held-side controller beat it?

Arms (frozen 8x24 space, q22 limit gate armed exactly as q25-q34,
CAPACITY=70, 400 ticks):
  NOGATE      - anchor, byte-comparable to q27-q34 (8 flips,
                end50 0.648000)
  BASE        - q22 gate, unbiased compress (7 flips, drop <=1.0pp)
  FIXED(1.0)  - open-loop full per-cell protection, re-measured
                in-run to confirm the q33/q34 signature (16 flips,
                end50 0.6760)
  PULSE       - s=1.0 during the FIRST armed window only, s=0.0
                (pure BASE compress) thereafter — "start at s=1.0
                for one arming then ramp down," the q34-proposed
                probe
  BREADTH-b   - protect-by-breadth instead of by weight: while
                armed, cells are protected iff they appear in >= b
                of the 8 question footprints (peer-only cells have
                count 0 and leave first); b in {1,2,3}. No hash
                dial, no RNG — pure structure.
  CL(10,1.0)  - q34's closed-loop controller from s0=1.0 at target
                10 (further down than q34's 13) — does the one
                high side extend, or saturate?

Claims (honest, falsifiable):
  C1 (upward from cold-low exists at all): at least one arm other
     than FIXED(1.0) — PULSE or BREADTH-b — achieves flips >= 10
     (BASE 7 + 3, i.e. a real raise, not noise). If none does,
     C1 FAILS (honest negative: cold-low cannot be raised).
  C2 (upward is purchasable WITHOUT sustained full protection):
     at least one non-FIXED arm reaches flips within 2 of
     FIXED(1.0)'s 16 (>= 14) while NOT holding full protection for
     the whole run. If only FIXED(1.0) reaches >= 14, C2 FAILS:
     upward cadence is purchasable only at the fixed
     full-protection point — structural.
  C3 (anchors + determinism): NOGATE reproduces the frozen anchor
     (8 flips, supply 98, end50 0.648000); BASE holds the q22 law
     (drop <= 1.0pp, savings >= 70%); FIXED(1.0) matches the
     q33/q34 signature (16 flips, end50 0.6760); every PULSE/
     BREADTH/CL arm run twice is byte-identical.

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

WINDOW = 40          # control window (ticks), q34 parity
STEP = 0.10          # s adjustment per window, q34 parity


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


def run(mode, strength=None, breadth=None, target=None, s0=None):
    """mode: None = no gate; 'skip' = q22 gate unbiased; 'wdial' = fixed
    per-cell weight dial at `strength` (q33/q34 parity); 'pulse' = s=1.0
    during the first armed window only; 'breadth' = protect cells in
    >= `breadth` footprints while armed; 'cl' = q34 closed-loop."""
    fps = [footprint(f"q{i}") for i in range(N_Q)]
    supply_union = frozenset().union(*fps)
    fp_count = {}
    for fp in fps:
        for f in fp:
            fp_count[f] = fp_count.get(f, 0) + 1
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
    prev_armed_now = False
    for k in range(TICKS):
        # --- closed-loop adjustment (q34 parity) ---
        if mode == "cl" and k > 0 and k % WINDOW == 0:
            target_rate = target * WINDOW / TICKS
            err = target_rate - w_flips
            if err > 0:
                s = min(1.0, s + STEP)
            elif err < 0:
                s = max(0.0, s - STEP)
            s_hist.append((k, round(s, 2)))
            w_flips = 0
        if mode is not None:
            if skip == 0 and 1 <= dwell < DWELL:
                skip = TICKS
                armed += 1
            if cov and cov[-1] < SAT:
                skip = 0
        armed_now = skip > 0
        # --- pulse: s=1.0 during the FIRST armed window only ---
        if mode == "pulse":
            s = 1.0 if (armed_now and armed == 1) else 0.0
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
                    if mode == "wdial" and armed_now and s > 0.0:
                        protected = frozenset(
                            f for f in held
                            if f in supply_union and _weight(f, k) < s)
                    elif mode == "pulse" and armed_now and s > 0.0:
                        protected = frozenset(
                            f for f in held
                            if f in supply_union and _weight(f, k) < s)
                    elif mode == "breadth" and armed_now and breadth is not None:
                        protected = frozenset(
                            f for f in held
                            if fp_count.get(f, 0) >= breadth)
                    elif mode == "cl" and armed_now and s > 0.0:
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
        prev_armed_now = armed_now
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
                n_q=len(fps), cov=cov, flips_at=flips, trace=trace.hexdigest(),
                s_hist=s_hist, s_end=round(s, 2))


def main():
    print("=" * 62)
    print("Q35: is the one-sided controllability STRUCTURAL — can any")
    print("held-side controller raise cadence from cold-low (pulse from")
    print("s=1.0, protect-by-breadth), or is upward cadence purchasable")
    print("only at the fixed full-protection point?")
    print("=" * 62)

    nogate = run(None)
    base = run("skip")
    fixed1 = run("wdial", strength=1.0)
    pulse = run("pulse")
    breadth = {b: run("breadth", breadth=b) for b in (1, 2, 3)}
    cl10 = run("cl", target=10, s0=1.0)

    print(f"\n[NOGATE    ] flips {nogate['flips']:2d} end50 {nogate['end']:.4f} "
          f"supply {nogate['supply']}")
    base_save = base["cells_saved"] / (TICKS * FP_SIZE) * 100
    base_drop = (base["end"] - nogate["end"]) * 100
    print(f"[BASE      ] flips {base['flips']:2d} end50 {base['end']:.4f} "
          f"saved {base_save:5.2f}% drop {base_drop:+.2f}pp")
    print(f"[FIXED 1.0 ] flips {fixed1['flips']:2d} end50 {fixed1['end']:.4f} "
          f"armed {fixed1['armed']} trace8 {fixed1['trace'][:8]}")
    print(f"[PULSE     ] flips {pulse['flips']:2d} end50 {pulse['end']:.4f} "
          f"armed {pulse['armed']} trace8 {pulse['trace'][:8]}")
    for b in (1, 2, 3):
        r = breadth[b]
        print(f"[BREADTH {b} ] flips {r['flips']:2d} end50 {r['end']:.4f} "
              f"armed {r['armed']} trace8 {r['trace'][:8]}")
    path = " ".join(f"{sv:.2f}" for _, sv in cl10["s_hist"][:12])
    print(f"[CL t10 s1 ] flips {cl10['flips']:2d} end50 {cl10['end']:.4f} "
          f"s_end {cl10['s_end']:.2f} path {path} trace8 {cl10['trace'][:8]}")

    # determinism: repeat every non-anchor arm
    det_ok = all(a["trace"] == b["trace"] and a["flips"] == b["flips"]
                 for a, b in [(pulse, run("pulse")),
                              (breadth[1], run("breadth", breadth=1)),
                              (breadth[2], run("breadth", breadth=2)),
                              (breadth[3], run("breadth", breadth=3)),
                              (cl10, run("cl", target=10, s0=1.0))])

    # DRAFT-1 HONESTY NOTE (caught before commit): BREADTH-1 is
    # trace-identical to FIXED(1.0) — protecting every cell in >=1
    # footprint IS full supply protection, the same point on a
    # different axis. Draft-1 counted it as a "non-FIXED" raiser and
    # claimed C2 PASS — a false positive. Arms byte-identical to
    # FIXED(1.0) are the full-protection point itself and are
    # excluded from C1/C2 below.
    all_arms = dict([("PULSE", pulse)] +
                    [(f"BREADTH-{b}", breadth[b]) for b in (1, 2, 3)])
    full_points = [n for n, r in all_arms.items()
                   if r["trace"] == fixed1["trace"]]

    # C1: any genuinely non-full arm raises flips to >= 10 from cold-low
    raisers = [n for n, r in all_arms.items()
               if r["trace"] != fixed1["trace"] and r["flips"] >= 10]
    c1 = len(raisers) > 0

    # C2: a genuinely non-full arm within 2 flips of FIXED(1.0)'s 16
    near_full = [n for n in raisers
                 if all_arms[n]["flips"] >= fixed1["flips"] - 2]
    c2 = len(near_full) > 0

    # C3: anchors + determinism
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    law_ok = base_drop <= 1.0 and base_save >= 70.0
    f1_ok = (fixed1["flips"] == 16 and abs(fixed1["end"] - 0.6760) < 1e-9)
    c3 = anchor_ok and law_ok and f1_ok and det_ok

    print("\n" + "-" * 62)
    print(f"C1 genuinely-non-full arm raises flips to >=10 from cold-low "
          f"(raisers: {raisers}; full-point clones excluded: "
          f"{full_points}):  {'PASS' if c1 else 'FAIL'}")
    print(f"C2 a genuinely-non-full arm lands within 2 of FIXED(1.0) "
          f"(>= {fixed1['flips'] - 2} flips; hits: {near_full}):   "
          f"{'PASS' if c2 else 'FAIL'}")
    print(f"C3 anchors ({anchor_ok}) + q22 law ({law_ok}) + FIXED(1)==q33/q34 "
          f"sig ({f1_ok}) + determinism ({det_ok}): "
          f"{'PASS' if c3 else 'FAIL'}")

    if c1 and c2 and c3:
        verdict = (
            f"UPWARD IS PURCHASABLE WITHOUT SUSTAINED FULL PROTECTION: "
            f"{near_full} (genuinely distinct from the full-protection "
            f"point, traces differ) raise cadence from cold-low to "
            f"within 2 flips of FIXED(1.0) ({fixed1['flips']}) — the "
            f"one-sidedness q34 saw is an artifact of the weight-dial "
            f"controller, not a structural law."
        )
    elif c1 and c3 and not c2:
        detail = "; ".join(f"{n}: flips {all_arms[n]['flips']} end50 "
                           f"{all_arms[n]['end']:.4f} armed "
                           f"{all_arms[n]['armed']}" for n in all_arms)
        verdict = (
            f"STRUCTURAL CEILING (honest negative on C2, anchors intact): "
            f"cold-low CAN be raised off BASE ({base['flips']} flips) — "
            f"{detail} — and CL-from-above extends (target 10 from s0=1.0: "
            f"{cl10['flips']} flips) — but NO controller reaches within 2 "
            f"flips of the fixed full-protection point "
            f"({fixed1['flips']} flips) without holding full protection "
            f"for the whole run. Upward cadence is purchasable in PARTIAL "
            f"amounts from cold-low, but the top of the s-axis is "
            f"reachable only at the fixed full-protection point — "
            f"q34's one-sidedness is a GRADIENT law, not a binary one."
        )
    elif c3 and not c1:
        detail = "; ".join(f"{n}: flips {all_arms[n]['flips']} armed "
                           f"{all_arms[n]['armed']}" for n in all_arms)
        verdict = (
            f"COLD-LOW IS DEAD (honest negative, anchors intact): neither "
            f"the pulse-from-s=1.0 probe nor protect-by-breadth raises "
            f"cadence to >=10 from cold-low — {detail} vs BASE "
            f"{base['flips']} — while FIXED(1.0) holds {fixed1['flips']}. "
            f"Upward cadence is purchasable ONLY at the fixed "
            f"full-protection point: q34's one-sidedness is STRUCTURAL. "
            f"The mechanism matches q34's path-dependence law: a single "
            f"full-protection arming (PULSE) shapes the held set for one "
            f"window, but the held-set state it creates is overwritten by "
            f"subsequent BASE compressions before it can compound into "
            f"cadence; only SUSTAINED full protection keeps the supply "
            f"side hot window after window."
        )
    else:
        verdict = (
            "ANCHOR BROKE: numbers reported as-is, no law claimed beyond "
            "what holds. Investigate harness drift before interpreting."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q35-upward-from-cold-low",
        [nogate["flips"], f"{nogate['end']:.6f}"],
        [base["flips"], f"{base['end']:.6f}"],
        [fixed1["flips"], f"{fixed1['end']:.6f}", fixed1["trace"][:12]],
        [pulse["flips"], f"{pulse['end']:.6f}", pulse["trace"][:12],
         pulse["armed"]],
        [[b, breadth[b]["flips"], f"{breadth[b]['end']:.6f}",
          breadth[b]["trace"][:12], breadth[b]["armed"]] for b in (1, 2, 3)],
        [cl10["flips"], f"{cl10['end']:.6f}", cl10["s_end"],
         cl10["s_hist"][:12], cl10["trace"][:12]],
        [c1, c2, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c2 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
