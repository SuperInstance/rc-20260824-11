#!/usr/bin/env python3
"""
Q26: IS THE +1.13pp EVOLUTION COST REAL, OR A MERGE-UNION SIZE ARTIFACT?
q25 closed: INHERITED GATE saves 336/400 dice passes (84.0%) but drops end50
coverage +1.13pp vs its own nogate — just over the 1.0pp line, the first
perturbation to push the limit gate's cost over. q25's open question: is that
a REAL cost of topology evolution, or an artifact of merge-union SIZE — the
merged question inherits the UNION of two 24-cell footprints (48 cells),
doubling its share of capacity pressure at CAPACITY=70, so compression evicts
more of the *other* questions' cells (breadth loss) than evolution itself
demands?

Decomposition — three inherited-merge strategies, everything else identical
to q25's INHERITED arm (MERGE at t=120, SPLIT at t=280, limit gate everywhere,
each arm GATE vs NOGATE so drop is measured within-arm):
  UNION    - q25's arm (merged fp = a|b, 48 cells). Anchor: reproduces q25.
  CAPPED   - union deterministically truncated back to 24 cells (fnv1a rank,
             same size a parent had). Size artifact hypothesis: if CAPPED's
             gate drop falls <= 1.0pp where UNION's doesn't, size (capacity
             pressure), not evolution, paid q25's +1.13pp.
  INTERSEC - a|b reduced to its 24-cell core (intersection-first, topped up
             by fnv1a rank if short). Sharper information claim: the merged
             question needs only the cells both parents shared.

Claims (honest, falsifiable; primary metric = end50 drop of GATE vs NOGATE
within each strategy, q25's own metric):
  C1 (size artifact): CAPPED gate drop <= 1.0pp AND UNION drop > 1.0pp
     (reproducing q25) — the overage is rented from footprint size, not
     evolution; a FAIL here with CAPPED also >1.0pp means the cost is real
     evolution cost and q25's law stands as measured.
  C2 (anchor): UNION reproduces q25's numbers — saves > 0 dice passes, drop
     in (0.9, 1.4)pp band, byte-comparable harness.
  C3 (information, secondary): INTERSEC vs CAPPED end50 (gate arms): if the
     shared-core footprint holds coverage within 1.0pp of CAPPED, merge does
     not need the union's full breadth — a compression law for Q0's MERGE
     operator. Measured honestly either way.

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

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]

MERGE_AT = 120
SPLIT_AT = 280


def footprint(text: str, max_cells: int = FP_SIZE) -> frozenset:
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        cells.add(fnv1a(f"{text}#{salt}") % FACTS)
        salt += 1
    return frozenset(cells)


def cap24(cells: frozenset, salt: str) -> frozenset:
    """Deterministically truncate to FP_SIZE by fnv1a rank."""
    ranked = sorted(cells, key=lambda c: fnv1a(canonical([salt, c])))
    return frozenset(ranked[:FP_SIZE])


PEER_FP = footprint("peer-agent-shared-docs")

HALF_A = frozenset(range(FACTS // 2))
HALF_B = frozenset(range(FACTS // 2, FACTS))


def _other_half(uni):
    return HALF_B if uni == HALF_A else HALF_A


# --- merge strategies ------------------------------------------------------

def merge_union(a, b, _k):
    return a | b


def merge_capped(a, b, k):
    return cap24(a | b, f"capped-merge-{k}")


def merge_intersec(a, b, k):
    core = a & b
    if len(core) >= FP_SIZE:
        return cap24(core, f"core-merge-{k}")
    ranked = sorted((a | b) - core, key=lambda c: fnv1a(canonical([f"topup-{k}", c])))
    return frozenset(set(core) | set(ranked[: FP_SIZE - len(core)]))


MERGERS = {"union": merge_union, "capped": merge_capped, "intersec": merge_intersec}


def split_fps(fps):
    ordered = sorted(fps)
    b0 = {c for i, c in enumerate(ordered) if i % 2 == 0}
    b1 = {c for i, c in enumerate(ordered) if i % 2 == 1}
    return frozenset(b0), frozenset(b1)


def evolve(fps: list, k: int, merger) -> list:
    if k == MERGE_AT:
        i = fnv1a(canonical(["q25", "merge", k])) % len(fps)
        j = fnv1a(canonical(["q25", "merge2", k])) % (len(fps) - 1)
        if j >= i:
            j += 1
        merged = merger(fps[i], fps[j], k)
        return [f for n, f in enumerate(fps) if n not in (i, j)] + [merged]
    if k == SPLIT_AT:
        i = fnv1a(canonical(["q25", "split", k])) % len(fps)
        p0, p1 = split_fps(fps[i])
        return [f for n, f in enumerate(fps) if n != i] + [p0, p1]
    return fps


# --- stack (q25 harness verbatim, merger parameterized) --------------------

def run(merger, gate: bool):
    fps = [footprint(f"q{i}") for i in range(8)]
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    uni = HALF_A
    dwell = 0
    for k in range(TICKS):
        fps = evolve(fps, k, merger)
        if gate:
            if skip == 0 and 1 <= dwell < DWELL:
                skip = TICKS
                armed += 1
            if cov and cov[-1] < SAT:
                skip = 0
        for layer in ("dice", "compress", "mutate", "edges"):
            if skip > 0 and layer == "dice":
                continue
            if layer == "dice":
                fp = fps[fnv1a(canonical(["self", "dice", k])) % len(fps)]
                held = held | fp
            elif layer == "compress":
                if len(held) > CAPACITY:
                    scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
                    held = frozenset(sorted(scored[:CAPACITY]))
            elif layer == "mutate":
                fp = fps[fnv1a(canonical(["self", "mut", k])) % len(fps)]
                drop_n = min(6, len(held))
                drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "drop", f, k])))[:drop_n])
                held = (held - drops) | (fp - drops)
            elif layer == "edges":
                held = held | PEER_FP
            passes[layer] += 1
        if skip > 0:
            skip -= 1
        c = len(held & uni) / len(uni)
        cov.append(c)
        dwell = dwell + 1 if c >= SAT else 0
        if dwell >= DWELL:
            flips.append(k + 1)
            uni = _other_half(uni)
            dwell = 0
    return cov, flips, passes, armed


def arm(name, gate):
    cov, flips, passes, armed = run(MERGERS[name], gate)
    end = sum(cov[-50:]) / 50
    post_vals = []
    for f in flips:
        post_vals.extend(cov[f:f + 20])
    post = sum(post_vals) / len(post_vals) if post_vals else 0.0
    return dict(name=name, gate=gate, end=end, post=post,
                flips=len(flips), passes=passes, armed=armed)


def main():
    print("=" * 62)
    print("Q26: merge-union size artifact vs real evolution cost")
    print("=" * 62)

    results = {}
    for name in ("union", "capped", "intersec"):
        for gate in (False, True):
            r = arm(name, gate)
            key = f"{name.upper()}-{'GATE' if gate else 'NOGATE'}"
            results[key] = r
            print(f"\n[{key:<16}] flips {r['flips']} armed {r['armed']} "
                  f"dice {r['passes']['dice']} post {r['post']:.4f} "
                  f"end {r['end']:.4f}")

    def drop_of(name):
        g = results[f"{name.upper()}-GATE"]
        n = results[f"{name.upper()}-NOGATE"]
        save = n["passes"]["dice"] - g["passes"]["dice"]
        drop = (n["end"] - g["end"]) * 100
        return save, drop

    u_save, u_drop = drop_of("union")
    c_save, c_drop = drop_of("capped")
    i_save, i_drop = drop_of("intersec")

    ic_delta = (results["CAPPED-GATE"]["end"] - results["INTERSEC-GATE"]["end"]) * 100

    c1 = c_drop <= 1.0 and u_drop > 1.0
    c2 = u_save > 0 and 0.9 <= u_drop <= 1.4
    c3 = abs(ic_delta) <= 1.0

    print("\n" + "-" * 62)
    print(f"[UNION    gate vs nogate] saved {u_save} end50 drop {u_drop:+.2f}pp (q25 anchor)")
    print(f"[CAPPED   gate vs nogate] saved {c_save} end50 drop {c_drop:+.2f}pp")
    print(f"[INTERSEC gate vs nogate] saved {i_save} end50 drop {i_drop:+.2f}pp")
    print(f"[INTERSEC vs CAPPED gate]  end50 delta {ic_delta:+.2f}pp (shared-core sufficiency)")

    print(f"\nC1 (size artifact: capped<=1.0pp where union>1.0pp): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (UNION reproduces q25 band 0.9-1.4pp): {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (shared core holds within 1.0pp): {'PASS' if c3 else 'FAIL (honest negative)'}")

    if c1:
        verdict = (
            f"SIZE ARTIFACT CONFIRMED: capping the merged footprint back to "
            f"{FP_SIZE} cells brings the limit gate's end50 drop to {c_drop:+.2f}pp "
            f"(<= 1.0pp, saving {c_save} passes) where q25's 48-cell union paid "
            f"{u_drop:+.2f}pp — the overage was capacity pressure, not evolution; "
            f"the gate law survives Q0 when MERGE preserves footprint SIZE. "
            f"Shared-core: {'suffices' if c3 else 'does not suffice'} ({ic_delta:+.2f}pp)."
        )
    else:
        verdict = (
            f"REAL EVOLUTION COST (honest): capped-merge gate drop {c_drop:+.2f}pp "
            f"vs union {u_drop:+.2f}pp — size normalization does not rescue the "
            f"gate under live topology evolution; q25's measurement stands as a "
            f"true cost of evolving the question space mid-run."
        )

    ok = c1 and c2
    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q26-merge-union-size-artifact",
        {k: [r["flips"], dict(r["passes"]), r["armed"],
             f"{r['post']:.6f}", f"{r['end']:.6f}"]
         for k, r in sorted(results.items())},
        [u_save, f"{u_drop:.4f}"], [c_save, f"{c_drop:.4f}"],
        [i_save, f"{i_drop:.4f}"], f"{ic_delta:.4f}", verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
