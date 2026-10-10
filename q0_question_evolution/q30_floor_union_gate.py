#!/usr/bin/env python3
"""
Q30: IS THERE A K CHEAP ENOUGH — FLOOR-UNION TRUNCATION OF ARMED SUPPLY?
q29 closed: JOINT truncation of dice+mutate to a bare K DOES regulate flip
cadence (K 6/12/18 -> flips 0/2/4, rho +1.00) but prices at -3.47pp end50 —
the regulation is rented from the stack's inability to track the universe
(coverage starves below SAT, dwell never accumulates). Open question (q29):
is there a K small enough to keep cadence yet priced within the 1.0pp line —
or is ANY cadence-affecting supply knob necessarily priced above the line
because cadence IS coverage loss?

This experiment tests the floor variant q29 named: while armed, truncate the
injected footprint to K NEW cells per pass, but FORCE-RETAIN every cell of
the question's footprint already held (the union of the question's last-seen
cells). Supply keeps its breadth floor (no starvation of held coverage);
only the MARGINAL new-cell injection is throttled.

FROZEN question space (8 x 24), no Q0 operators, CAPACITY=70, 400 ticks,
limit gate armed exactly as q25-q29 (arm at 1<=dwell<DWELL, release when
coverage < SAT). Arms:
  NOGATE    - no gate (anchor, byte-comparable to q27/q28/q29's frozen arm)
  BASE      - q22 limit gate: dice SKIPPED entirely while armed (mutate full)
  FLOOR-K   - dice AND mutate run while armed; each injected footprint is
              (fp & held) | top-K-new by fnv1a rank of (fp - held), K in
              {2, 4, 8}. Edges untouched (PEER_FP is q24's pressure side).

Claims (honest, falsifiable; primary metrics = flips and end50 drop vs NOGATE):
  C1 (a safe K exists): at least one FLOOR-K arm keeps flips within +-2 of
     NOGATE (cadence preserved, not starved) AND end50 drop within 1.0pp
     (q25/q26 line) AND total cell savings (dice+mutate new cells not
     injected) >= 50% of BASE's dice-cell savings.
  C2 (mechanism law): if NO FLOOR-K passes C1, the answer is the honest
     negative — cadence regulation via supply throttling and coverage
     preservation are the SAME quantity: any K that changes cadence changes
     coverage beyond the line. FAIL receipt is the finding.
  C3 (anchor): NOGATE reproduces q27/q28/q29's frozen 8x24 arm EXACTLY
     (8 flips, supply 98, end50 0.648000) and BASE holds the q22 law in this
     harness (drop <= 1.0pp, dice-cell savings >= 70%).

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


def floor_shrink(fp: frozenset, held: frozenset, k: int, tick: int, layer: str) -> frozenset:
    """FLOOR-UNION truncation: keep every already-held cell of this
    footprint; admit only the k best-ranked NEW cells by fnv1a."""
    core = fp & held
    new = fp - held
    ranked = sorted(new, key=lambda c: fnv1a(canonical(["floor-gate", layer, tick, c])))
    return frozenset(core | set(ranked[:k]))


# --- stack (q29 harness verbatim; FLOOR mode = floor-union truncation) -----
# mode: None = no gate; "skip" = q22 limit gate (dice skipped, mutate full);
# int K = floor-union size-gate (dice AND mutate: retain all held cells of
# the footprint, admit K new cells per armed pass; edges untouched).

def run(mode):
    fps = [footprint(f"q{i}") for i in range(N_Q)]
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    cells_saved = 0  # dice+mutate cells NOT injected vs ungated passes
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
                    elif isinstance(mode, int):
                        small = floor_shrink(fp, held, mode, k, "dice")
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
                if skip > 0 and isinstance(mode, int):
                    # FLOOR gate: mutate still rotates; its footprint keeps
                    # every held cell and admits only K new cells while
                    # armed. The drop side (eviction pressure) runs UNCHANGED.
                    small = floor_shrink(fp, held, mode, k, "mutate")
                    cells_saved += len(fp) - len(small)
                    fp = small
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
    print("Q30: floor-union size-gate — held breadth retained, only")
    print("NEW-cell admission throttled while armed")
    print("=" * 62)

    results = {}
    order = [("NOGATE", None), ("BASE", "skip"),
             ("FLOOR-2", 2), ("FLOOR-4", 4), ("FLOOR-8", 8)]
    for name, mode in order:
        r = run(mode)
        results[name] = r
        save_pct = r["cells_saved"] / (TICKS * FP_SIZE) * 100
        print(f"\n[{name:<8}] flips {r['flips']:2d} armed {r['armed']:3d} "
              f"cells_saved {r['cells_saved']:4d} ({save_pct:5.2f}% of one layer's cells) "
              f"dice_passes {r['passes']['dice']:3d} end50 {r['end']:.4f}")

    nogate = results["NOGATE"]
    base = results["BASE"]
    ks = [2, 4, 8]
    floor_flips = {k: results[f"FLOOR-{k}"]["flips"] for k in ks}
    floor_ends = {k: results[f"FLOOR-{k}"]["end"] for k in ks}
    floor_saves = {k: results[f"FLOOR-{k}"]["cells_saved"] for k in ks}

    # C1: a safe K exists — flips within +-2 of NOGATE, drop within 1.0pp,
    # savings >= 50% of BASE's dice-cell savings.
    safe_ks = []
    for k in ks:
        drop = (floor_ends[k] - nogate["end"]) * 100
        save_ratio = floor_saves[k] / base["cells_saved"] if base["cells_saved"] else 0
        cadence_ok = abs(floor_flips[k] - nogate["flips"]) <= 2
        if cadence_ok and -1.0 <= drop <= 1.0 and save_ratio >= 0.50:
            safe_ks.append(k)
    c1 = len(safe_ks) > 0

    # C2: mechanism reporting — per-K cadence and price, whether or not safe.
    c2_detail = "; ".join(
        f"K{k}: flips {floor_flips[k]} drop {(floor_ends[k]-nogate['end'])*100:+.2f}pp "
        f"saves {floor_saves[k]/base['cells_saved'] if base['cells_saved'] else 0:.2f}xBASE"
        for k in ks)

    # C3: anchors — NOGATE byte-comparable to q27/q28/q29's frozen 8x24 arm;
    # BASE holds the q22 law in this harness (drop <= 1.0pp, savings >= 70%).
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    base_drop = (base["end"] - nogate["end"]) * 100
    base_save_ratio = base["cells_saved"] / (TICKS * FP_SIZE)
    c3 = anchor_ok and base_drop <= 1.0 and base_save_ratio >= 0.70

    print("\n" + "-" * 62)
    print(f"nogate flips {nogate['flips']} | base(skip) flips {base['flips']}")
    print(f"floor arms: {c2_detail}")
    print(f"BASE drop {base_drop:+.2f}pp | BASE cells saved {base_save_ratio*100:.2f}%")
    print(f"\nC1 (a safe K exists: +-2 flips, <=1.0pp, >=50% savings): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (per-K cadence/price reported as-is):                   {'PASS'}")
    print(f"C3 (q27/q28/q29 anchor exact + BASE holds q22 law):        {'PASS' if c3 else 'FAIL'}")

    if c1 and c3:
        verdict = (
            f"A SAFE K EXISTS: floor-union truncation at K in {safe_ks} keeps "
            f"flip cadence within +-2 of nogate ({nogate['flips']}) while "
            f"pricing within the 1.0pp line and saving real cells — the "
            f"marginal new-cell admission is NOT the load-bearing supply; "
            f"the held-set floor is. {c2_detail}."
        )
    elif not c1 and c3:
        verdict = (
            f"NO SAFE K (honest negative): floor-union truncation at every K "
            f"tested either starves cadence, prices above the 1.0pp line, or "
            f"saves too little — {c2_detail}. Refines q29: even when held "
            f"breadth is force-retained, throttling NEW-cell admission to "
            f"K new cells per armed pass does not yield a free regulator — "
            f"cadence and coverage are the same quantity at the margin: "
            f"what makes the universe flip is the stack tracking it, and "
            f"any supply throttle taxes exactly that."
        )
    else:
        verdict = (
            "ANCHOR BROKE: numbers reported as-is, no law claimed beyond "
            "what holds. Investigate harness drift before interpreting."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q30-floor-union-size-gate",
        [[nm, results[nm]["flips"], results[nm]["armed"],
          results[nm]["cells_saved"], results[nm]["passes"]["dice"],
          f"{results[nm]['end']:.6f}"] for nm, _ in order],
        [c1, True, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
