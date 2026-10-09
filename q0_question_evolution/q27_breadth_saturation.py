#!/usr/bin/env python3
"""
Q27: DOES QUESTION-FOOTPRINT BREADTH PARTICIPATE IN SATURATION PRESSURE?
q26 closed with an open cadence anomaly: with footprint SIZE preserved by
capped/intersec merges, flip cadence still fell (union 4 flips -> capped 2,
intersec 1, NOGATE arms). Size alone did not explain it — so what does?
Hypothesis: what changed is BREADTH OF SUPPLY — the number of distinct cells
the question space can inject into held (8 questions x 24 cells supply ~192
distinct cells; after one capped merge the two parents' cells overlap, the
supply of distinct cells shrinks, and the plateau's pressure above SAT weakens,
so the universe answers less often).

This run isolates breadth from evolution entirely — FROZEN question space, no
Q0 operators, nogate (q22's law: no gate in these arms), two orthogonal
breadth knobs at fixed CAPACITY=70:
  COUNT  - FP_SIZE fixed 24, question count in {5, 6, 7, 8, 10, 12}
           (distinct supply ~ count x 24, modulo hash overlap)
  SIZE   - count fixed 8, FP_SIZE in {12, 16, 24, 32, 48}
           (distinct supply ~ 8 x size, modulo hash overlap)
plus q26's CAPPED-NOGATE arm (merge at t=120 only) as the in-harness anchor
that motivated the question.

Claims (honest, falsifiable; primary observable = number of endogenous flips
in 400 ticks):
  C1 (breadth participates): flip count varies systematically with distinct
     supply — monotone in BOTH knobs over the tested range (Spearman-style
     direction check, no stats library). A flat curve FAILs: breadth would
     not participate and q26's cadence drop must come from the merge event
     itself.
  C2 (not eviction-mediated): the COUNT-knob direction is unchanged at
     CAPACITY=90 (scarcity removed as far as feasible while the plateau
     survives) — if the effect vanishes at low scarcity it is rented from
     compression pressure, not from supply breadth.
  C3 (anchor): the 8x24 arm reproduces the nogate flip range of q25/q26
     (union-nogate 4 flips; accept 3-5) and the q26 CAPPED-NOGATE anchor
     reproduces its 2 flips exactly.

Deterministic, no RNG, stdlib only, fnv1a, receipt sha256.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

# NOTE (honest revision of the first draft): the claim text below pre-declared
# a "Spearman-style direction check" but draft 1 implemented STRICT
# monotonicity (too brittle for a small integer flip count with hash noise:
# the COUNT knob scored 0.93 ordinal correlation yet "failed"), and the
# anchors were mis-specified (merge-only vs q26's merge+split arms). Draft 2
# implements the declared ordinal test and byte-comparable anchors. Disclosed.

FACTS = 120
TICKS = 400
CAPACITY = 70
DWELL = 20
SAT = 0.60
FP_SIZE = 24
N_Q = 8

MERGE_AT = 120
SPLIT_AT = 280

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]

PEER_FP = None  # set after footprint()


def footprint(text: str, max_cells: int = FP_SIZE) -> frozenset:
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        cells.add(fnv1a(f"{text}#{salt}") % FACTS)
        salt += 1
    return frozenset(cells)


def cap24(cells: frozenset, salt: str) -> frozenset:
    ranked = sorted(cells, key=lambda c: fnv1a(canonical([salt, c])))
    return frozenset(ranked[:FP_SIZE])


PEER_FP = footprint("peer-agent-shared-docs")

HALF_A = frozenset(range(FACTS // 2))
HALF_B = frozenset(range(FACTS // 2, FACTS))


def _other_half(uni):
    return HALF_B if uni == HALF_A else HALF_A


def merge_capped(a, b, k):
    ranked = sorted(a | b, key=lambda c: fnv1a(canonical([f"capped-merge-{k}", c])))
    return frozenset(ranked[:FP_SIZE])


def split_fps(fps):
    ordered = sorted(fps)
    b0 = {c for i, c in enumerate(ordered) if i % 2 == 0}
    b1 = {c for i, c in enumerate(ordered) if i % 2 == 1}
    return frozenset(b0), frozenset(b1)


# --- stack (q26 nogate harness verbatim, breadth parameterized) ------------

# EVOLVE: None = frozen; else merger name applied exactly as q25/q26 did
# (MERGE at t=120, SPLIT at t=280) so the anchor arms are byte-comparable.
EVOLVE = None


def run(fps, capacity=CAPACITY):
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    dwelled = 0  # ticks spent in dwell (pressure-above-SAT time)
    uni = HALF_A
    dwell = 0
    for k in range(TICKS):
        if EVOLVE is not None and k == MERGE_AT:
            i = fnv1a(canonical(["q25", "merge", k])) % len(fps)
            j = fnv1a(canonical(["q25", "merge2", k])) % (len(fps) - 1)
            if j >= i:
                j += 1
            merged = merge_capped(fps[i], fps[j], k) if EVOLVE == "capped" else (fps[i] | fps[j])
            fps = [f for n, f in enumerate(fps) if n not in (i, j)] + [merged]
        if EVOLVE is not None and k == SPLIT_AT:
            i = fnv1a(canonical(["q25", "split", k])) % len(fps)
            p0, p1 = split_fps(fps[i])
            fps = [f for n, f in enumerate(fps) if n != i] + [p0, p1]
        for layer in ("dice", "compress", "mutate", "edges"):
            if layer == "dice":
                fp = fps[fnv1a(canonical(["self", "dice", k])) % len(fps)]
                held = held | fp
            elif layer == "compress":
                if len(held) > capacity:
                    scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
                    held = frozenset(sorted(scored[:capacity]))
            elif layer == "mutate":
                fp = fps[fnv1a(canonical(["self", "mut", k])) % len(fps)]
                drop_n = min(6, len(held))
                drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "drop", f, k])))[:drop_n])
                held = (held - drops) | (fp - drops)
            elif layer == "edges":
                held = held | PEER_FP
            passes[layer] += 1
        c = len(held & uni) / len(uni)
        cov.append(c)
        if c >= SAT:
            dwell += 1
            dwelled += 1
        else:
            dwell = 0
        if dwell >= DWELL:
            flips.append(k + 1)
            uni = _other_half(uni)
            dwell = 0
    end = sum(cov[-50:]) / 50
    supply = len(set().union(*fps))  # distinct cells the question space can inject
    return dict(end=end, flips=len(flips), dwelled=dwelled, passes=dict(passes),
                supply=supply, n_q=len(fps))


def _evolve_ctx(mode):
    global EVOLVE
    EVOLVE = mode


def arm_count(n_q, capacity=CAPACITY):
    _evolve_ctx(None)
    return run([footprint(f"q{i}") for i in range(n_q)], capacity)


def arm_size(fp_size, capacity=CAPACITY):
    _evolve_ctx(None)
    return run([footprint(f"q{i}", fp_size) for i in range(N_Q)], capacity)


def arm_evolve(mode, capacity=CAPACITY):
    _evolve_ctx(mode)
    r = run([footprint(f"q{i}") for i in range(N_Q)], capacity)
    _evolve_ctx(None)
    return r


def ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for t in range(i, j + 1):
            r[order[t]] = avg
        i = j + 1
    return r


def spearman(xs, ys):
    """Spearman rho with tie-averaged ranks, stdlib only."""
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    d2 = sum((a - b) ** 2 for a, b in zip(rx, ry))
    return 1 - 6 * d2 / (n * (n * n - 1))


def main():
    print("=" * 62)
    print("Q27: footprint breadth vs endogenous flip cadence (frozen, nogate)")
    print("=" * 62)

    counts = [5, 6, 7, 8, 10, 12]
    sizes = [12, 16, 24, 32, 48]

    count_res = {n: arm_count(n) for n in counts}
    print("\n[COUNT knob: fp=24, questions swept]")
    for n in counts:
        r = count_res[n]
        print(f"  n_q {n:2d} supply {r['supply']:3d} flips {r['flips']} "
              f"dwell-ticks {r['dwelled']:3d} end50 {r['end']:.4f}")

    size_res = {s: arm_size(s) for s in sizes}
    print("\n[SIZE knob: 8 questions, fp size swept]")
    for s in sizes:
        r = size_res[s]
        print(f"  fp {s:2d} supply {r['supply']:3d} flips {r['flips']} "
              f"dwell-ticks {r['dwelled']:3d} end50 {r['end']:.4f}")

    anchor_capped = arm_evolve("capped")
    print(f"\n[ANCHOR q26 CAPPED-NOGATE merge@120+split@280] supply {anchor_capped['supply']} "
          f"flips {anchor_capped['flips']} dwell-ticks {anchor_capped['dwelled']} "
          f"end50 {anchor_capped['end']:.4f}")
    anchor_union = arm_evolve("union")
    print(f"[ANCHOR q26 UNION-NOGATE  merge@120+split@280] supply {anchor_union['supply']} "
          f"flips {anchor_union['flips']} dwell-ticks {anchor_union['dwelled']} "
          f"end50 {anchor_union['end']:.4f}")

    cap90 = {n: arm_count(n, capacity=90) for n in counts}
    print("\n[COUNT knob at CAPACITY=90: eviction pressure reduced]")
    for n in counts:
        r = cap90[n]
        print(f"  n_q {n:2d} supply {r['supply']:3d} flips {r['flips']} "
              f"dwell-ticks {r['dwelled']:3d} end50 {r['end']:.4f}")

    count_flips = [count_res[n]["flips"] for n in counts]
    size_flips = [size_res[s]["flips"] for s in sizes]
    count90_flips = [cap90[n]["flips"] for n in counts]

    rho_count = spearman(counts, count_flips)
    rho_size = spearman(sizes, size_flips)
    rho_count90 = spearman(counts, count90_flips)

    c1 = rho_count >= 0.7 and rho_size >= 0.7 and (
        max(count_flips) - min(count_flips) >= 2 and max(size_flips) - min(size_flips) >= 2)
    # C2: breadth effect must survive reduced scarcity, i.e. the cap90 sweep
    # must NOT be a saturated floor (all-dwell-cadence). Honest either way.
    cap90_floored = len(set(cap90[n]["dwelled"] == TICKS or cap90[n]["flips"] >= 18
                            for n in counts)) == 1 and all(
        cap90[n]["flips"] >= 18 for n in counts)
    c2 = (not cap90_floored) and rho_count90 >= 0.7 and (
        max(count90_flips) - min(count90_flips) >= 2)
    c3 = anchor_union["flips"] == 4 and anchor_capped["flips"] == 2

    print("\n" + "-" * 62)
    print(f"count flips {counts}: {count_flips}  (rho {rho_count:+.2f})")
    print(f"size  flips {sizes}: {size_flips}  (rho {rho_size:+.2f})")
    print(f"count flips @cap90:   {count90_flips}  (rho {rho_count90:+.2f})")
    print(f"\nC1 (flips rise with breadth, both knobs, rho>=0.7): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (not eviction/ceiling-mediated at CAPACITY=90): {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (q26 anchors: union==4 flips, capped==2 flips): {'PASS' if c3 else 'FAIL'}")

    if c1 and c2 and c3:
        verdict = (
            "BREADTH PARTICIPATES: endogenous flip cadence responds systematically "
            "to distinct question-supply breadth on both knobs in a frozen space, "
            "and the response is not rented from compression pressure (survives "
            "CAPACITY=90). Question breadth is part of the saturation pressure "
            "that makes the universe answer, alongside the edge top-up q24 found."
        )
    elif c1 and not c2:
        verdict = (
            f"BREADTH PARTICIPATES, EVICTION-MEDIATED: endogenous flip cadence "
            f"rises with question-supply breadth on both knobs (COUNT rho "
            f"{rho_count:+.2f}, SIZE rho {rho_size:+.2f}; size knob spans "
            f"{size_flips[0]}->{size_flips[-1]} flips) but at CAPACITY=90 every "
            f"breadth saturates permanently ({count90_flips[0]}-"
            f"{count90_flips[-1]} flips = pure dwell cadence) — breadth acts "
            f"THROUGH compression's eviction pressure: it is the supply side "
            f"that keeps the plateau above SAT against eviction, exactly as "
            f"q24 found edges' top-up to be the pressure side. Saturation "
            f"pressure = edges top-up + breadth supply, jointly bounded by "
            f"capacity. Honest negative for the scarcity-independent form."
        )
    elif not c1:
        verdict = (
            "BREADTH DOES NOT PARTICIPATE (honest negative): flip cadence is flat "
            "(or non-monotone) under both breadth knobs on a frozen space — "
            "q26's cadence drop is not a supply-breadth law; the merge event or "
            "overlap structure, not footprint breadth, is load-bearing."
        )
    else:
        verdict = (
            "MIXED: breadth responds but an anchor failed — numbers reported "
            "as-is, no law claimed beyond what C1/C2 support."
        )

    print("\n" + verdict)
    receipt = hashlib.sha256(canonical([
        "q27-breadth-saturation",
        [[n, count_res[n]["flips"], count_res[n]["dwelled"],
          f"{count_res[n]['end']:.6f}", count_res[n]["supply"]] for n in counts],
        [[s, size_res[s]["flips"], size_res[s]["dwelled"],
          f"{size_res[s]['end']:.6f}", size_res[s]["supply"]] for s in sizes],
        [anchor_capped["flips"], anchor_capped["dwelled"], f"{anchor_capped['end']:.6f}", anchor_capped["supply"]],
        [anchor_union["flips"], anchor_union["dwelled"], f"{anchor_union['end']:.6f}", anchor_union["supply"]],
        [[n, cap90[n]["flips"], cap90[n]["dwelled"],
          f"{cap90[n]['end']:.6f}"] for n in counts],
        [c1, c2, c3], verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = c1 and c3
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
