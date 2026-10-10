#!/usr/bin/env python3
"""
Q29: DOES JOINT SUPPLY MODULATION REGULATE CADENCE (ALL INJECTORS, SAME K)?
q28 closed: truncating DICE's footprint alone to K during the armed window is
NOT a supply regulator (flips 10/8/10 at K 6/12/18 — flat around nogate's 8;
rho +0.12) because the cadence pressure is rented from the un-gated injectors:
mutate still injects FULL 24-cell footprints every tick and edges still tops
up PEER_FP. Law: supply breadth is a property of the WHOLE injection schedule
(dice+mutate+edges jointly). Open question (q28): gate ALL injection layers'
footprint size together during the armed window — dice AND mutate truncated to
the same K (edges left constant, its PEER_FP is q24's doubly-load-bearing
pressure side, not a supply knob) — does JOINT supply modulation regulate flip
cadence, or does held-level eviction pressure dominate regardless of injector
footprints?

FROZEN question space (8 x 24), no Q0 operators, CAPACITY=70, 400 ticks,
limit gate armed exactly as q25/q26/q28 (arm at 1<=dwell<DWELL, release when
coverage < SAT). Arms:
  NOGATE   - no gate (anchor, byte-comparable to q27/q28's frozen 8x24 arm)
  BASE     - q22 limit gate: dice SKIPPED entirely while armed (mutate full)
  JOINT-K  - dice AND mutate run while armed, both footprints fnv1a-truncated
             to K cells, K in {6,12,18}

Claims (honest, falsifiable; primary metrics = flips and end50 drop vs NOGATE):
  C1 (regulation): JOINT-gate flip count varies monotonically (ordinal,
     Spearman-style rho >= 0.5) with retained K across {6,12,18} AND is not
     flat (span >= 1) AND is not a restatement of skip-vs-run (identical to
     BASE or to NOGATE at every K). q28's solo-dice arm FAILED exactly this —
     the joint arm is the test of q28's law that supply is schedule-wide.
  C2 (gate law holds): JOINT-12 end50 drop vs NOGATE <= 1.0pp (q25/q26 line)
     AND JOINT-12 total cell savings (dice+mutate cells not injected while
     armed) >= 50% of BASE's dice-cell savings — a knob that breaks the law
     or saves nothing is a failure even if it regulates.
  C3 (anchor): NOGATE reproduces q27/q28's frozen 8x24 arm EXACTLY (8 flips,
     supply 98, end50 0.648000) and BASE holds the q22 law in this harness
     (drop <= 1.0pp, dice-cell savings >= 70% of all dice cells).

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


def shrink(fp: frozenset, k: int, tick: int, layer: str) -> frozenset:
    """Truncate footprint to k cells by fnv1a rank (deterministic core)."""
    ranked = sorted(fp, key=lambda c: fnv1a(canonical(["joint-gate", layer, tick, c])))
    return frozenset(ranked[:k])


# --- stack (q28 harness verbatim; JOINT mode truncates dice AND mutate) ----
# mode: None = no gate; "skip" = q22 limit gate (dice skipped, mutate full);
# int K = joint size-gate (dice AND mutate footprints truncated to K while
# armed; edges untouched — PEER_FP is the pressure side per q24/q27).

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
                        small = shrink(fp, mode, k, "dice")
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
                    # JOINT gate: mutate still rotates but with a truncated
                    # footprint — the drop side (eviction pressure on held)
                    # runs UNCHANGED, only the supply side shrinks.
                    fp = shrink(fp, mode, k, "mutate")
                    cells_saved += len(fps[fnv1a(canonical(["self", "mut", k])) % len(fps)]) - len(fp)
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
    print("Q29: joint size-gate — ALL supply injectors truncated to same K")
    print("=" * 62)

    results = {}
    order = [("NOGATE", None), ("BASE", "skip"),
             ("JOINT-6", 6), ("JOINT-12", 12), ("JOINT-18", 18)]
    for name, mode in order:
        r = run(mode)
        results[name] = r
        save_pct = r["cells_saved"] / (TICKS * FP_SIZE) * 100
        print(f"\n[{name:<8}] flips {r['flips']:2d} armed {r['armed']:3d} "
              f"cells_saved {r['cells_saved']:4d} ({save_pct:5.2f}% of one layer's cells) "
              f"dice_passes {r['passes']['dice']:3d} end50 {r['end']:.4f}")

    nogate = results["NOGATE"]
    base = results["BASE"]
    joint_flips = [results[f"JOINT-{k}"]["flips"] for k in (6, 12, 18)]
    joint_ends = {k: results[f"JOINT-{k}"]["end"] for k in (6, 12, 18)}
    ks = [6, 12, 18]

    # C1: ordinal regulation across K, non-flat, non-degenerate.
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

    rx, ry = ranks(ks), ranks(joint_flips)
    n = len(ks)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    rho_joint = 1 - 6 * d2 / (n * (n * n - 1)) if n > 1 else 0.0
    flat = len(set(joint_flips)) == 1
    degenerate = all(f == base["flips"] for f in joint_flips) or \
        all(f == nogate["flips"] for f in joint_flips)
    span = max(joint_flips) - min(joint_flips)
    c1 = (rho_joint >= 0.5) and (not flat) and (not degenerate) and span >= 1

    # C2: gate law — JOINT-12 drop vs NOGATE <= 1.0pp, and joint savings
    # (dice+mutate) must be a real fraction (>= 50%) of BASE's dice-cell
    # savings.
    drop12 = (joint_ends[12] - nogate["end"]) * 100
    save_ratio = results["JOINT-12"]["cells_saved"] / base["cells_saved"] if base["cells_saved"] else 0
    c2 = drop12 >= -1.0 and drop12 <= 1.0 and save_ratio >= 0.50

    # C3: anchors — NOGATE byte-comparable to q27/q28's frozen 8x24 arm;
    # BASE holds the q22 law in this harness (drop <= 1.0pp, savings >= 70%).
    anchor_ok = (nogate["flips"] == 8 and nogate["supply"] == 98
                 and abs(nogate["end"] - 0.648000) < 1e-9)
    base_drop = (base["end"] - nogate["end"]) * 100
    base_save_ratio = base["cells_saved"] / (TICKS * FP_SIZE)
    c3 = anchor_ok and base_drop <= 1.0 and base_save_ratio >= 0.70

    print("\n" + "-" * 62)
    print(f"joint-gate flips by K {ks}: {joint_flips}  (rho {rho_joint:+.2f}, span {span})")
    print(f"nogate flips {nogate['flips']} | base(skip) flips {base['flips']}")
    print(f"JOINT-12 end50 drop vs nogate {drop12:+.2f}pp | save_ratio vs BASE {save_ratio:.2f}")
    print(f"BASE drop {base_drop:+.2f}pp | BASE cells saved {base_save_ratio*100:.2f}%")
    print(f"\nC1 (K jointly modulates flip cadence, non-flat, non-degen): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (JOINT-12 drop <=1.0pp AND saves >=50% of BASE cells):    {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (q27/q28 anchor exact + BASE holds q22 law):              {'PASS' if c3 else 'FAIL'}")

    if c1 and c2 and c3:
        verdict = (
            f"JOINT SUPPLY MODULATION WORKS: gating ALL supply injectors "
            f"(dice AND mutate) at the same retained K regulates flip cadence "
            f"(K {ks} -> flips {joint_flips}, rho {rho_joint:+.2f}) where q28's "
            f"solo-dice gate was flat (10/8/10) — supply breadth is indeed a "
            f"schedule-wide property. And the gate law holds: JOINT-12 drops "
            f"end50 {drop12:+.2f}pp (<=1.0pp) while saving {save_ratio:.2f}x "
            f"BASE's dice-cell savings across two layers."
        )
    elif c1 and not c2:
        verdict = (
            f"REGULATES BUT PRICES OUT (honest negative): joint flip cadence "
            f"tracks retained K (K {ks} -> {joint_flips}, rho {rho_joint:+.2f}) "
            f"but JOINT-12 costs {drop12:+.2f}pp end50 vs nogate (over the "
            f"1.0pp line) or saves too little ({save_ratio:.2f} of BASE) — "
            f"joint truncation regulates but breaks the q25/q26 gate law."
        )
    elif not c1:
        verdict = (
            f"HELD-LEVEL PRESSURE DOMINATES (honest negative): even gating "
            f"both supply injectors jointly, flip count does not track retained "
            f"breadth (K {ks} -> flips {joint_flips}, rho {rho_joint:+.2f}, "
            f"span {span}) — flip cadence is set by held-level eviction "
            f"dynamics (capacity pressure + edges' constant PEER_FP top-up), "
            f"not by injector footprint size at the margin. q28's law refines: "
            f"supply breadth is schedule-wide as a LEVEL, but its marginal "
            f"footprint size is not the cadence knob. Numbers as-is."
        )
    else:
        verdict = (
            "MIXED: cadence modulation present but an anchor or law failed — "
            "numbers reported as-is, no law claimed beyond what holds."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q29-joint-size-gate",
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
