#!/usr/bin/env python3
"""
Q31: CAN THE LIMIT GATE BIAS EVICTION WHILE ARMED — RETAIN BREADTH-DONATING
CELLS — TO BUY CADENCE OR COVERAGE WITHOUT TOUCHING SUPPLY?
q30 closed the supply-throttle direction at every K: cadence regulation and
coverage preservation are the SAME quantity at the margin — every supply
throttle (skip, bare-K, joint-K, floor-union-K) taxes exactly the tracking
that produces both flips and coverage. Open question (q30): the next free
lunch, if one exists, is on the HELD side — can the limit gate bias EVICTION
while armed (compress prefers retaining breadth-donating cells) to buy
cadence or coverage without touching supply?

This experiment tests exactly that. FROZEN question space (8 x 24), no Q0
operators, CAPACITY=70, 400 ticks, limit gate armed exactly as q25-q30 (arm
at 1<=dwell<DWELL, release when coverage < SAT). Supply layers untouched
while armed: dice is skipped (q22 law), mutate/edges run FULL — only the
compress layer's eviction ORDER changes during the armed window.

Breadth-donating cell = a cell in the union of the question footprints
(q27/q29's supply side: question breadth is what keeps the plateau above
SAT against compression). While armed, BIAS evicts non-supply cells first
(peer-only cells); BASE evicts by fnv1a rank alone (no preference).

Arms:
  NOGATE - no gate (anchor, byte-comparable to q27/q28/q29/q30's frozen arm)
  BASE   - q22 limit gate verbatim: dice SKIPPED while armed, compress
           unbiased (this is q30's BASE, the frontier)
  BIAS   - q22 limit gate, but while armed compress prefers retaining
           supply cells: evict candidates sorted by (not-in-supply, fnv1a
           rank) — non-supply (peer-only) cells leave first, supply cells
           are protected until the supply pool itself is undersized.

Claims (honest, falsifiable; primary metrics = flips and end50 drop vs NOGATE):
  C1 (the buy): BIAS keeps the q22 law intact (dice-cell savings >= 70%,
     end50 drop within 1.0pp of NOGATE) AND buys something real over BASE:
     end50 drop at least 0.20pp BETTER than BASE's, or flips closer to
     NOGATE's cadence by >= 2 (tracking restored, not starved). No buy, no
     PASS — a silent tie is a FAIL receipt (the knob does nothing).
  C2 (mechanism law): if BIAS fails C1, the honest negative — the held-side
     bias is either inert (compress at CAPACITY=70 rarely faces a
     supply-vs-peer choice while armed) or harmful (protecting supply
     evicts the peer top-up that q24 found is the saturation PRESSURE —
     buying breadth by evicting pressure). Report which, with numbers.
  C3 (anchor): NOGATE reproduces q27/q28/q29/q30's frozen 8x24 arm EXACTLY
     (8 flips, supply 98, end50 0.648000) and BASE holds the q22 law in
     this harness (drop <= 1.0pp, dice-cell savings >= 70%).

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


# --- stack (q30 harness verbatim; BIAS mode = armed eviction preference ---
# mode: None = no gate; "skip" = q22 limit gate (dice skipped, compress
# unbiased); "bias" = q22 limit gate, and while armed compress evicts
# non-supply (peer-only) cells FIRST: candidates sorted by
# (not-in-supply, fnv1a rank). Supply layers run FULL while armed.

def run(mode):
    fps = [footprint(f"q{i}") for i in range(N_Q)]
    supply_union = frozenset().union(*fps)
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    cells_saved = 0
    evictions_bias_persistent = 0  # evictions during armed windows (bias mode)
    evictions_base_armed = 0       # evictions during armed windows (skip mode)
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
                    if mode == "bias" and armed_now:
                        # breadth-biased eviction: non-supply cells leave
                        # first; supply cells protected by preference, not
                        # absolutely (they can still go if only supply
                        # remains over capacity).
                        scored = sorted(
                            held,
                            key=lambda f: (0 if f in supply_union else 1,
                                           fnv1a(canonical(["self", "evict", f, k]))))
                        evictions_bias_persistent += len(held) - CAPACITY
                    else:
                        scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
                        if mode == "skip" and armed_now:
                            evictions_base_armed += len(held) - CAPACITY
                    held = frozenset(sorted(scored[:CAPACITY]))
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
                n_q=len(fps), cov=cov,
                armed_evictions=(evictions_bias_persistent if mode == "bias"
                                 else evictions_base_armed))


def main():
    print("=" * 62)
    print("Q31: armed eviction bias — compress prefers retaining")
    print("breadth-donating (supply) cells while the limit gate is armed")
    print("=" * 62)

    results = {}
    order = [("NOGATE", None), ("BASE", "skip"), ("BIAS", "bias")]
    for name, mode in order:
        r = run(mode)
        results[name] = r
        save_pct = r["cells_saved"] / (TICKS * FP_SIZE) * 100
        print(f"\n[{name:<8}] flips {r['flips']:2d} armed {r['armed']:3d} "
              f"cells_saved {r['cells_saved']:4d} ({save_pct:5.2f}%) "
              f"armed_evictions {r['armed_evictions']:3d} end50 {r['end']:.4f}")

    nogate = results["NOGATE"]
    base = results["BASE"]
    bias = results["BIAS"]

    base_drop = (base["end"] - nogate["end"]) * 100
    bias_drop = (bias["end"] - nogate["end"]) * 100
    base_save_ratio = base["cells_saved"] / (TICKS * FP_SIZE)
    bias_save_ratio = bias["cells_saved"] / (TICKS * FP_SIZE)

    law_intact = bias_save_ratio >= 0.70 and -1.0 <= bias_drop <= 1.0
    buys_coverage = bias_drop >= base_drop + 0.20
    buys_cadence = abs(bias["flips"] - nogate["flips"]) <= abs(base["flips"] - nogate["flips"]) - 2
    c1 = law_intact and (buys_coverage or buys_cadence)

    c2 = True  # mechanism reported as-is below

    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    c3 = anchor_ok and base_drop <= 1.0 and base_save_ratio >= 0.70

    print("\n" + "-" * 62)
    print(f"nogate flips {nogate['flips']} | base flips {base['flips']} | bias flips {bias['flips']}")
    print(f"BASE drop {base_drop:+.2f}pp saves {base_save_ratio*100:.2f}%")
    print(f"BIAS drop {bias_drop:+.2f}pp saves {bias_save_ratio*100:.2f}% "
          f"(buy: coverage {bias_drop - base_drop:+.2f}pp, cadence {bias['flips'] - base['flips']:+d} flips)")
    print(f"BIAS armed evictions {bias['armed_evictions']} vs BASE armed evictions {base['armed_evictions']}")
    print(f"\nC1 (law intact + real buy over BASE >=0.20pp or >=2 flips):   {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (mechanism reported as-is):                              {'PASS'}")
    print(f"C3 (q27-q30 anchor exact + BASE holds q22 law):              {'PASS' if c3 else 'FAIL'}")

    if bias["armed_evictions"] == 0 and not c1:
        mech = ("INERT: the bias never had a choice to make — compress "
                f"evicted {bias['armed_evictions']} cells during armed "
                "windows at CAPACITY=70 in this harness, so the eviction "
                "ORDER is unexercised while armed; the held side does not "
                "reach the capacity boundary during skips")
    elif not c1:
        mech = ("HARMFUL/INSUFFICIENT: the bias is exercised "
                f"({bias['armed_evictions']} armed evictions) but buys "
                f"{bias_drop - base_drop:+.2f}pp coverage and "
                f"{bias['flips'] - base['flips']:+d} flips — protecting "
                "supply cells during armed windows either changes nothing "
                "the mutation layer does not already restore, or evicts "
                "the peer top-up (q24's saturation PRESSURE) to buy "
                "breadth, paying pressure for breadth")
    else:
        mech = (f"BOUGHT: coverage {bias_drop - base_drop:+.2f}pp vs BASE, "
                f"cadence {bias['flips']} vs BASE {base['flips']} vs nogate {nogate['flips']}")

    if c1 and c3:
        verdict = (
            f"THE HELD SIDE PAYS: armed eviction bias toward breadth-"
            f"donating (supply) cells keeps the q22 law (drop {bias_drop:+.2f}pp, "
            f"saves {bias_save_ratio*100:.2f}%) AND buys a real margin over "
            f"BASE — {mech}. First knob inside the gate law that buys "
            "something without touching supply."
        )
    elif not c1 and c3:
        verdict = (
            f"NO FREE LUNCH ON THE HELD SIDE EITHER (honest negative): "
            f"{mech}. BASE drop {base_drop:+.2f}pp, BIAS drop {bias_drop:+.2f}pp, "
            f"flips nogate/base/bias {nogate['flips']}/{base['flips']}/{bias['flips']}. "
            "Refines q30: the gate's held-side is not a second wallet — "
            "either compress never faces the supply-vs-peer choice while "
            "armed (inert order), or protecting breadth evicts exactly the "
            "peer pressure (q24) that makes the plateau answer. Both sides "
            "of the ledger — supply and held — are the same money."
        )
    else:
        verdict = (
            "ANCHOR BROKE: numbers reported as-is, no law claimed beyond "
            "what holds. Investigate harness drift before interpreting."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q31-armed-eviction-bias",
        [[nm, results[nm]["flips"], results[nm]["armed"],
          results[nm]["cells_saved"], results[nm]["armed_evictions"],
          results[nm]["passes"]["dice"],
          f"{results[nm]['end']:.6f}"] for nm, _ in order],
        [c1, True, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
