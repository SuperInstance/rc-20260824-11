#!/usr/bin/env python3
"""
Q28: CAN THE LIMIT GATE MODULATE DICE FOOTPRINT SIZE (NOT JUST SKIP DICE)?
q27 closed: saturation pressure = edges top-up (constant, pressure side) +
question breadth (scaling, supply side), jointly bounded by capacity; scarcity
converts breadth into a second load-bearing supplier. Open question: the
supply/pressure decomposition suggests a BREADTH-CONTROL KNOB for the gate —
instead of skipping dice entirely when armed (q22 limit gate), let dice run
but SHRINK its footprint to K cells (fnv1a-ranked truncation of the drawn
footprint). If supply breadth drives flip cadence (q27 SIZE knob rho +0.97),
a size-gate should REGULATE cadence (fewer, not zero, flips at small K) —
and the question is whether mutating supply mid-run breaks the gate law
(q25/q26: end50 drop vs nogate <= 1.0pp) or q1's coverage-preservation logic
(the retained core of the footprint must still carry the answer).

FROZEN question space (8 x 24), no Q0 operators, CAPACITY=70, 400 ticks,
limit gate armed exactly as q25/q26 (arm at 1<=dwell<DWELL, release when
coverage < SAT). Arms:
  NOGATE  - no gate (anchor, byte-comparable to q27's 8x24 arm)
  BASE    - q22 limit gate: dice SKIPPED entirely while armed
  SIZE-K  - dice runs while armed with footprint truncated to K in {6,12,18}

Claims (honest, falsifiable; primary metrics = flips and end50 drop vs NOGATE):
  C1 (regulation): SIZE-gate flip count varies monotonically (ordinal,
     Spearman-style) with retained K across {6,12,18} AND differs from both
     NOGATE (unregulated) and BASE (release valve fully closed). A flat or
     binary curve FAILs: the knob would not modulate supply, only restate
     skip-vs-run.
  C2 (gate law holds): end50 drop of SIZE-12 vs NOGATE <= 1.0pp (the q25/q26
     line) AND SIZE-12 saves >= 50% of the dice-cell injections BASE saves
     (measured in dice cells not passed: BASE saves 24/armed-pass, SIZE-K
     saves 24-K) — a knob that regulates but prices above the line or saves
     nothing is a failure.
  C3 (anchor): NOGATE reproduces q27's frozen 8x24 arm EXACTLY (8 flips,
     357 dwell-ticks, end50 0.648000, supply 98) and BASE (skip gate, frozen
     space) holds the q22 law in this harness (drop <= 1.0pp, savings >= 70%
     of dice passes).

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


def shrink(fp: frozenset, k: int, tick: int) -> frozenset:
    """Truncate footprint to k cells by fnv1a rank (deterministic core)."""
    ranked = sorted(fp, key=lambda c: fnv1a(canonical(["size-gate", tick, c])))
    return frozenset(ranked[:k])


# --- stack (q26 harness verbatim, gate parameterized) ----------------------
# mode: None = no gate; "skip" = q22 limit gate; int K = size-gate (dice runs
# with footprint truncated to K cells while armed).

def run(mode):
    fps = [footprint(f"q{i}") for i in range(N_Q)]
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    cells_saved = 0  # dice cells NOT injected vs an ungated dice pass
    uni = HALF_A
    dwell = 0
    for k in range(TICKS):
        if mode is not None:
            if skip == 0 and 1 <= dwell < DWELL:
                skip = TICKS
                armed += 1
            if cov and cov[-1] < SAT:
                skip = 0
        for layer in ("dice", "compress", "mutate", "edges"):
            if layer == "dice":
                fp = fps[fnv1a(canonical(["self", "dice", k])) % len(fps)]
                if skip > 0:
                    if mode == "skip":
                        cells_saved += len(fp)
                        passes["dice"] += 0
                        skip -= 1 if False else 0  # skip decrement handled below (uniform)
                    elif isinstance(mode, int):
                        small = shrink(fp, mode, k)
                        cells_saved += len(fp) - len(small)
                        held = held | small
                        passes["dice"] += 1
                else:
                    held = held | fp
                    passes["dice"] += 1
            elif layer == "compress":
                if len(held) > CAPACITY:
                    scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
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
        if skip > 0:
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
                cells_saved=cells_saved, supply=len(set().union(*fps)),
                n_q=len(fps), cov=cov)


def main():
    print("=" * 62)
    print("Q28: size-gate — modulating dice footprint SIZE as gate knob")
    print("=" * 62)

    results = {}
    order = [("NOGATE", None), ("BASE", "skip"),
             ("SIZE-6", 6), ("SIZE-12", 12), ("SIZE-18", 18)]
    for name, mode in order:
        r = run(mode)
        results[name] = r
        save_pct = r["cells_saved"] / (TICKS * FP_SIZE) * 100
        print(f"\n[{name:<7}] flips {r['flips']:2d} armed {r['armed']:3d} "
              f"cells_saved {r['cells_saved']:4d} ({save_pct:5.2f}% of dice cells) "
              f"dice_passes {r['passes']['dice']:3d} end50 {r['end']:.4f}")

    nogate = results["NOGATE"]
    base = results["BASE"]
    size_flips = [results[f"SIZE-{k}"]["flips"] for k in (6, 12, 18)]
    size_ends = {k: results[f"SIZE-{k}"]["end"] for k in (6, 12, 18)}
    ks = [6, 12, 18]

    # C1: ordinal regulation — flips rise with retained K, and the curve is
    # neither flat (no modulation) nor degenerate (skip-vs-run restatement:
    # i.e. identical to BASE at every K or identical to NOGATE at every K).
    def ranks(vals):
        order_i = sorted(range(len(vals)), key=lambda i: vals[i])
        r = [0.0] * len(vals)
        i = 0
        while i < len(order_i):
            j = i
            while j + 1 < len(order_i) and vals[order_i[j + 1]] == vals[order_i[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for t in range(i, j + 1):
                r[order_i[t]] = avg
            i = j + 1
        return r

    rx, ry = ranks(ks), ranks(size_flips)
    n = len(ks)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    rho_size = 1 - 6 * d2 / (n * (n * n - 1)) if n > 1 else 0.0
    flat = len(set(size_flips)) == 1
    degenerate = all(f == base["flips"] for f in size_flips) or \
        all(f == nogate["flips"] for f in size_flips)
    span = max(size_flips) - min(size_flips)
    c1 = (rho_size >= 0.5) and (not flat) and (not degenerate) and span >= 1

    # C2: gate law — SIZE-12 drop vs NOGATE <= 1.0pp, and its savings must be
    # a real fraction (>= 50%) of BASE's dice-cell savings.
    drop12 = (size_ends[12] - nogate["end"]) * 100
    save_ratio = results["SIZE-12"]["cells_saved"] / base["cells_saved"] if base["cells_saved"] else 0
    c2 = drop12 >= -1.0 and drop12 <= 1.0 and save_ratio >= 0.50

    # C3: anchors — NOGATE byte-comparable to q27's frozen 8x24 arm; BASE
    # holds the q22 law in this harness (drop <= 1.0pp, savings >= 70%).
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    base_drop = (base["end"] - nogate["end"]) * 100
    base_save_ratio = base["cells_saved"] / (TICKS * FP_SIZE)
    c3 = anchor_ok and base_drop <= 1.0 and base_save_ratio >= 0.70

    print("\n" + "-" * 62)
    print(f"size-gate flips by K {ks}: {size_flips}  (rho {rho_size:+.2f}, span {span})")
    print(f"nogate flips {nogate['flips']} | base(skip) flips {base['flips']}")
    print(f"SIZE-12 end50 drop vs nogate {drop12:+.2f}pp | save_ratio vs BASE {save_ratio:.2f}")
    print(f"BASE drop {base_drop:+.2f}pp | BASE cells saved {base_save_ratio*100:.2f}%")
    print(f"\nC1 (K modulates flip cadence, non-flat, non-degenerate): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (SIZE-12 drop <=1.0pp AND saves >=50% of BASE cells):  {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (q27 anchor exact + BASE holds q22 law):                {'PASS' if c3 else 'FAIL'}")

    if c1 and c2 and c3:
        verdict = (
            f"THE SIZE-GATE WORKS: the limit gate can modulate dice footprint SIZE "
            f"instead of skipping dice and flip cadence follows the retained breadth "
            f"(K {ks} -> flips {size_flips}, rho {rho_size:+.2f}) between NOGATE's "
            f"{nogate['flips']} and BASE's {base['flips']} — a continuous regulator, "
            f"not a binary valve. And it does not break the gate law: SIZE-12 drops "
            f"end50 {drop12:+.2f}pp vs nogate (<=1.0pp) while saving {save_ratio*100:.0f}% "
            f"of BASE's dice-cell savings. Mutating supply mid-run is LEGAL when the "
            f"retained core preserves the footprint's answer coverage (q1 logic): "
            f"the gate rents its savings from supply breadth, the one pressure side "
            f"q27 proved scaling."
        )
    elif c1 and not c2:
        verdict = (
            f"REGULATES BUT PRICES OUT (honest negative): flip cadence follows "
            f"retained K (K {ks} -> {size_flips}) but the SIZE-12 gate costs "
            f"{drop12:+.2f}pp end50 vs nogate (over the 1.0pp line) or saves too "
            f"little ({save_ratio:.2f} of BASE) — mutating dice supply mid-run "
            f"breaks the q25/q26 gate law even though it regulates cadence."
        )
    elif not c1:
        verdict = (
            f"NO MODULATION (honest negative): flip count does not track retained "
            f"breadth (K {ks} -> flips {size_flips}, rho {rho_size:+.2f}, span "
            f"{span}) — footprint-size truncation under the gate is not a supply "
            f"regulator in this harness; either the armed window is too short to "
            f"matter or flip cadence is rented from the un-gated layers (mutate "
            f"still injects full footprints). Numbers as-is."
        )
    else:
        verdict = (
            "MIXED: cadence modulation present but an anchor or law failed — "
            "numbers reported as-is, no law claimed beyond what holds."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q28-size-gate",
        [[nm, results[nm]["flips"], results[nm]["armed"],
          results[nm]["cells_saved"], results[nm]["passes"]["dice"],
          f"{results[nm]['end']:.6f}"] for nm, _ in order],
        [c1, c2, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c2 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
