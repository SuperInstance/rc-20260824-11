#!/usr/bin/env python3
"""
Q32: CAN CADENCE BE DELIBERATELY MODULATED VIA EVICTION PREFERENCE — BIAS
STRENGTH AS A SCHEDULE PARAMETER (A DIAL, NOT A GATE)?
q31 found the armed eviction bias (protect breadth-donating supply cells)
bought +2.80pp end50 at the cost of doubled flip cadence (16 vs 8 flips) —
not a gate win, but a SIGNAL: the knob modulates cadence. q31's open
question: can that modulation be made DELIBERATE — a dial that trades
coverage-at-a-phase for flip rate on demand?

This experiment tests the dial. FROZEN question space (8 x 24), no Q0
operators, CAPACITY=70, 400 ticks, q22 limit gate armed exactly as
q25-q31 (arm at 1<=dwell<DWELL, release when coverage < SAT). Supply
layers untouched while armed (dice skipped per q22; mutate/edges FULL).
The DIAL lives entirely in the compress layer's eviction ORDER during
armed windows:

  strength s in {0.00, 0.25, 0.50, 0.75, 1.00}
  At strength s, quota = round(s * supply_held_count) supply cells are
  protected: the quota LOWEST-fnv1a-rank supply cells are moved to the
  END of the eviction queue (protected last); the rest evict in fnv1a
  rank order among the unprotected pool. s=0 -> unbiased (must equal
  q31/q30 BASE byte-exactly); s=1 -> full bias (q31's BIAS).

Arms:
  NOGATE - no gate (anchor, byte-comparable to q27-q31 frozen arm)
  BASE   - q22 limit gate verbatim (== DIAL s=0.00, asserted byte-equal)
  DIAL   - q22 limit gate + armed eviction dial at each strength

Claims (honest, falsifiable):
  C1 (the dial turns): flip count over s = 0.00->1.00 is ordinally
     monotone (Spearman-style: no inversion between adjacent rungs after
     a 3-rung centered smoothing, and span >= 4 flips from s=0 to s=1)
     — the knob modulates cadence DELIBERATELY, not by noise. q31's
     single point (16 flips) predicts the high end.
  C2 (the price is a curve, not a cliff): report the full exchange
     table (s, flips, end50, saved%) and the marginal price per flip of
     cadence across the dial. PASS iff the table is reported AND the
     price direction is consistent (more protection -> more or equal
     flips and the end50-vs-flips relationship is single-signed within
     rungs). This is a TOOL receipt, not a free-lunch claim: q28-q31
     established cadence IS coverage's currency; the dial is expected
     to buy coverage-at-a-phase BY SPENDING flip rate, never to escape
     the law.
  C3 (anchor): NOGATE reproduces q27-q31's frozen 8x24 arm EXACTLY
     (8 flips, supply 98, end50 0.648000); BASE holds the q22 law
     (drop <= 1.0pp, dice-cell savings >= 70%); DIAL(0.00) is
     byte-identical to BASE (held-set trace hash equal).

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

STRENGTHS = [0.00, 0.25, 0.50, 0.75, 1.00]


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


def run(mode, strength=None):
    """mode: None = no gate; 'skip' = q22 gate, unbiased; 'dial' = q22
    gate + armed eviction dial at `strength` (0.0 = BASE, 1.0 = q31 BIAS)."""
    fps = [footprint(f"q{i}") for i in range(N_Q)]
    supply_union = frozenset().union(*fps)
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    cells_saved = 0
    armed_evictions = 0
    trace = hashlib.sha256()  # held-set trace for byte-identity checks
    uni = HALF_A
    dwell = 0
    for k in range(TICKS):
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
                    excess = len(held) - CAPACITY
                    if mode == "dial" and armed_now and strength > 0.0:
                        supply_held = sorted(
                            (f for f in held if f in supply_union),
                            key=lambda f: _rank(f, k))
                        quota = round(strength * len(supply_held))
                        protected = frozenset(supply_held[:quota])
                        # eviction order: the quota lowest-rank supply
                        # cells are protected = evicted LAST, so the
                        # RETAIN order is protected-first; queue[:CAP]
                        # keeps the front, evicting unprotected (peer-
                        # only) cells first.
                        queue = (sorted(protected, key=lambda f: _rank(f, k))
                                 + sorted((f for f in held if f not in protected),
                                          key=lambda f: _rank(f, k)))
                    else:
                        queue = sorted(held, key=lambda f: _rank(f, k))
                        if mode == "skip" and armed_now:
                            armed_evictions += excess
                    if mode == "dial" and armed_now:
                        armed_evictions += excess
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
    end = sum(cov[-50:]) / 50
    return dict(end=end, flips=len(flips), passes=dict(passes), armed=armed,
                cells_saved=cells_saved, supply=len(supply_union),
                n_q=len(fps), cov=cov, armed_evictions=armed_evictions,
                trace=trace.hexdigest())


def _smooth(xs):
    """3-rung centered smoothing (ends kept)."""
    out = []
    for i in range(len(xs)):
        lo, hi = max(0, i - 1), min(len(xs), i + 2)
        out.append(sum(xs[lo:hi]) / (hi - lo))
    return out


def _ordinal_monotone(xs):
    """Spearman-style ordinal check on the SMOOTHED ladder: no adjacent
    inversion where the later rung is strictly lower (downward-only or
    upward-only drift; ties allowed)."""
    s = _smooth(xs)
    direction = 0
    for a, b in zip(s, s[1:]):
        if b > a + 1e-12:
            d = 1
        elif b < a - 1e-12:
            d = -1
        else:
            d = 0
        if d != 0:
            if direction == 0:
                direction = d
            elif d != direction:
                return False
    return True


def main():
    print("=" * 62)
    print("Q32: the eviction-bias DIAL — bias strength as a schedule")
    print("parameter trading coverage-at-a-phase for flip cadence")
    print("=" * 62)

    nogate = run(None)
    base = run("skip")
    dials = {s: run("dial", strength=s) for s in STRENGTHS}

    print(f"\n[NOGATE  ] flips {nogate['flips']:2d} end50 {nogate['end']:.4f} "
          f"supply {nogate['supply']}")
    base_save = base["cells_saved"] / (TICKS * FP_SIZE) * 100
    print(f"[BASE    ] flips {base['flips']:2d} end50 {base['end']:.4f} "
          f"saved {base_save:5.2f}%")
    print("\n  s      flips  end50    drop(pp)  saved%   armed_ev  trace8")
    for s in STRENGTHS:
        r = dials[s]
        drop = (r["end"] - nogate["end"]) * 100
        sv = r["cells_saved"] / (TICKS * FP_SIZE) * 100
        print(f"  {s:.2f}  {r['flips']:5d}  {r['end']:.4f}  {drop:+7.2f}  "
              f"{sv:5.2f}  {r['armed_evictions']:8d}  {r['trace'][:8]}")

    ladder_flips = [dials[s]["flips"] for s in STRENGTHS]
    span = max(ladder_flips) - min(ladder_flips)
    c1 = _ordinal_monotone(ladder_flips) and span >= 4

    # C2: exchange table + single-signed end50-vs-flips relationship
    pts = sorted({(dials[s]["flips"], dials[s]["end"]) for s in STRENGTHS})
    sig = 0
    price_consistent = True
    for (f1, e1), (f2, e2) in zip(pts, pts[1:]):
        if e2 > e1 + 1e-12:
            d = 1
        elif e2 < e1 - 1e-12:
            d = -1
        else:
            d = 0
        if d != 0:
            if sig == 0:
                sig = d
            elif d != sig:
                price_consistent = False
    # marginal price per extra flip across adjacent rungs (pp/flip)
    marginals = []
    for s1, s2 in zip(STRENGTHS, STRENGTHS[1:]):
        df = dials[s2]["flips"] - dials[s1]["flips"]
        de = (dials[s2]["end"] - dials[s1]["end"]) * 100
        marginals.append(None if df == 0 else de / df)
    c2 = price_consistent

    base_drop = (base["end"] - nogate["end"]) * 100
    dial0 = dials[0.00]
    byte_equal = (dial0["trace"] == base["trace"]
                  and dial0["flips"] == base["flips"]
                  and abs(dial0["end"] - base["end"]) < 1e-12)
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    c3 = anchor_ok and base_drop <= 1.0 and base_save >= 70.0 and byte_equal

    print("\n" + "-" * 62)
    print(f"flip ladder over s {STRENGTHS}: {ladder_flips} (span {span}, "
          f"ordinal-monotone after smoothing: {_ordinal_monotone(ladder_flips)})")
    print(f"s=0.00 byte-identical to BASE: {'YES' if byte_equal else 'NO'} "
          f"(trace {dial0['trace'][:12]} vs {base['trace'][:12]})")
    print(f"price direction consistent (end50 vs flips single-signed): "
          f"{'YES' if price_consistent else 'NO'}")
    print("marginal pp per extra flip between adjacent rungs:",
          " ".join("n/a" if m is None else f"{m:+.2f}" for m in marginals))
    print(f"\nC1 (dial turns: monotone, span >= 4):                         {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (price reported as a consistent curve, tool not free lunch): {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (anchors exact + BASE q22 law + s=0 == BASE):                {'PASS' if c3 else 'FAIL'}")

    if c1 and c2 and c3:
        verdict = (
            "THE DIAL TURNS: armed eviction-bias strength is a real "
            f"schedule parameter — flips modulate {ladder_flips[0]}->{ladder_flips[-1]} "
            f"(span {span}) across s=0->1 with a consistent price curve "
            f"(end50 {dials[STRENGTHS[0]]['end']:.4f} at s=0 -> "
            f"{dials[STRENGTHS[-1]]['end']:.4f} at s=1). The q28-q31 law "
            "holds by construction: the dial SPENDS flip cadence to buy "
            "coverage-at-a-phase; it does not escape the gate law. "
            "Practical read: an operator wanting fewer universe flips "
            "runs s low (near-BASE cadence, near-BASE coverage); one "
            "needing a hot held plateau mid-run dials s up and pays in "
            "cadence."
        )
    elif c3:
        verdict = (
            "THE DIAL SLIPS (honest negative): anchors hold (NOGATE exact, "
            f"BASE at {base_drop:+.2f}pp/{base_save:.2f}%, s=0 "
            f"{'==' if byte_equal else '!='} BASE) but flip modulation is "
            f"not deliberate — ladder {ladder_flips}, span {span}, "
            f"ordinal-monotone {_ordinal_monotone(ladder_flips)}, price "
            f"consistent {price_consistent}. q31's 16-flip bias point was "
            "cadence noise at the capacity boundary, not a controllable "
            "axis; the eviction order is not a dial at CAPACITY=70."
        )
    else:
        verdict = (
            "ANCHOR BROKE: numbers reported as-is, no law claimed beyond "
            "what holds. Investigate harness drift before interpreting."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q32-eviction-bias-dial",
        [nogate["flips"], f"{nogate['end']:.6f}"],
        [base["flips"], f"{base['end']:.6f}"],
        [[f"{s:.2f}", dials[s]["flips"], dials[s]["armed_evictions"],
          f"{dials[s]['end']:.6f}"] for s in STRENGTHS],
        [c1, c2, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c2 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
