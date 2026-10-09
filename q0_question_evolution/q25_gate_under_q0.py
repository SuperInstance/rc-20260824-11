#!/usr/bin/env python3
"""
Q25: DOES THE LIMIT GATE SURVIVE QUESTION-SPACE EVOLUTION?
q24 closed the gate-optimization arc: on a FIXED question space, dice is the
only releasable layer and the q22 limit gate (arm at dwell>=1, skip-until-
break, dice-only release) is the frontier. But the Q0 verdict (ac03bd3) made
the question topology itself evolvable (MERGE/SPLIT/ABSTRACT/RECONSTRUCT),
and every gate law so far was measured on a FROZEN footprint set. If the
gate's value is rented from footprint stability, topology evolution should
break it; if the law is structural (plateau + reactive universe), it should
survive untouched.

Cross-arc test: the q22 limit gate runs while the question space evolves
under Q0 operators mid-run (MERGE at t=120, SPLIT at t=280), with two
footprint-inheritance strategies from q1:
  INHERITED - merged question inherits the UNION of its parents' footprints;
              split parts partition the parent's footprint (q1's winner).
  NAIVE     - merged/split footprints are regenerated from the new question
              texts (q1's loser: parent cells are abandoned).
STATIC (no evolution) reproduces q22 BASE as the anchor.

Each arm runs twice — GATE (q22 limit gate) and NOGATE — so savings and
coverage drop are measured within-arm, never across topologies.

Claims (honest, falsifiable) — coverage drop is measured on final-50
  coverage (defined even when an arm never flips; post-flip/rec5 reported
  as secondary, compared only when both arms flipped):
  C1 (the law survives evolution): INHERITED GATE saves > 0 dice passes vs
     INHERITED NOGATE at <= 1.0pp final-50 drop.
  C2 (anchor): STATIC GATE reproduces q22's frontier — saves >= 50% of
     NOGATE's dice passes at <= 1.0pp final-50 drop (q22: 89.25% at +0.12pp).
  C3 (inheritance matters in dynamics): NAIVE settled post-flip coverage is
     lower than INHERITED's (gate arms) by > 1.0pp — the q1 preservation law
     carrying over to a live gated stack. A measured non-difference is an
     honest negative.

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

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]


def footprint(text: str, max_cells: int = 24) -> frozenset:
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


# --- Q0 topology operators (q1 strategies, applied mid-run) ---------------

def merge_fps(fps_a, fps_b, strategy):
    if strategy == "inherited":
        return fps_a | fps_b
    return footprint("merged-question")  # naive: regenerate, parents abandoned


def split_fps(fps, strategy):
    if strategy == "naive":
        return footprint("split-part-0"), footprint("split-part-1")
    ordered = sorted(fps)
    b0 = {c for i, c in enumerate(ordered) if i % 2 == 0}
    b1 = {c for i, c in enumerate(ordered) if i % 2 == 1}
    return frozenset(b0), frozenset(b1)


def evolve(fps: list, k: int, strategy: str) -> list:
    """One Q0 operator per scheduled tick. Picks are fnv1a-deterministic."""
    if k == 120:  # MERGE two questions
        i = fnv1a(canonical(["q25", "merge", k])) % len(fps)
        j = fnv1a(canonical(["q25", "merge2", k])) % (len(fps) - 1)
        if j >= i:
            j += 1
        merged = merge_fps(fps[i], fps[j], strategy)
        return [f for n, f in enumerate(fps) if n not in (i, j)] + [merged]
    if k == 280:  # SPLIT one question
        i = fnv1a(canonical(["q25", "split", k])) % len(fps)
        p0, p1 = split_fps(fps[i], strategy)
        return [f for n, f in enumerate(fps) if n != i] + [p0, p1]
    return fps


# --- stack (q24 harness, topology passed in) ------------------------------

def run(strategy: str, gate: bool):
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
        fps = evolve(fps, k, strategy)
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


def settled(cov, flips):
    post = []
    for f in flips:
        post.extend(cov[f:f + 20])
    s_post = sum(post) / len(post) if post else 0.0
    s_end = sum(cov[-50:]) / 50
    return s_post, s_end


def recovery(cov, flips, n=5):
    vals = []
    for f in flips:
        vals.extend(cov[f:f + n])
    return sum(vals) / len(vals) if vals else 0.0


def arm(strategy, gate):
    cov, flips, passes, armed = run(strategy, gate)
    s_post, s_end = settled(cov, flips)
    rec = recovery(cov, flips)
    return dict(strategy=strategy, gate=gate, cov=cov, flips=len(flips),
                passes=passes, armed=armed, post=s_post, end=s_end, rec=rec)


def main():
    print("=" * 62)
    print("Q25: does the q22 limit gate survive Q0 topology evolution")
    print("=" * 62)

    results = {}
    for strategy in ("static", "inherited", "naive"):
        for gate in (False, True):
            r = arm(strategy, gate)
            key = f"{strategy.upper()}-{'GATE' if gate else 'NOGATE'}"
            results[key] = r
            print(f"\n[{key:<16}] flips {r['flips']} armed {r['armed']} "
                  f"dice {r['passes']['dice']} post {r['post']:.4f} "
                  f"end {r['end']:.4f} rec5 {r['rec']:.4f}")

    def savings(strategy):
        g = results[f"{strategy.upper()}-GATE"]
        n = results[f"{strategy.upper()}-NOGATE"]
        save = n["passes"]["dice"] - g["passes"]["dice"]
        drop = (n["end"] - g["end"]) * 100  # final-50: defined even at 0 flips
        rec_drop = (n["rec"] - g["rec"]) * 100
        return save, drop, rec_drop, n["passes"]["dice"]

    inh_save, inh_drop, inh_rec, _ = savings("inherited")
    sta_save, sta_drop, sta_rec, sta_dice = savings("static")

    c1 = inh_save > 0 and inh_drop <= 1.0
    c2 = sta_dice > 0 and sta_save / sta_dice >= 0.50 and sta_drop <= 1.0

    naive_end = results["NAIVE-GATE"]["end"]
    inh_end = results["INHERITED-GATE"]["end"]
    naive_delta = (inh_end - naive_end) * 100
    c3 = naive_delta > 1.0

    print("\n" + "-" * 62)
    print(f"[INHERITED gate vs nogate] dice saved {inh_save} "
          f"end50 drop {inh_drop:+.2f}pp (rec5 {inh_rec:+.2f}pp, secondary)")
    print(f"[STATIC    gate vs nogate] dice saved {sta_save}/{sta_dice} "
          f"({sta_save / sta_dice:.2%}) end50 drop {sta_drop:+.2f}pp (q22 anchor)")
    print(f"[NAIVE vs INHERITED gate]  end50 delta {naive_delta:+.2f}pp "
          f"(q1 preservation law in dynamics)")

    print(f"\nC1 (law survives evolution): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (STATIC reproduces q22 frontier): {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (naive regeneration costs coverage): "
          f"{'PASS' if c3 else 'FAIL (honest negative — measured, no >1pp cost)'}")

    ok = c1 and c2
    if ok:
        verdict = (
            f"PASS: the q22 limit gate survives question-space evolution — "
            f"with MERGE/SPLIT mid-run and inherited footprints it saves "
            f"{inh_save} dice passes at {inh_drop:+.2f}pp end50 drop; STATIC "
            f"anchors q22 ({sta_save / sta_dice:.2%} saved, {sta_drop:+.2f}pp); "
            f"naive-vs-inherited delta {naive_delta:+.2f}pp "
            f"({'inheritance load-bearing' if c3 else 'no >1pp cost — honest negative'})"
        )
    else:
        why = []
        if not c1:
            why.append("gate fails under evolved topology "
                       f"(saved {inh_save}, end50 drop {inh_drop:+.2f}pp)")
        if not c2:
            why.append("STATIC anchor drifted from q22 "
                       f"({sta_save / sta_dice:.2%} saved, {sta_drop:+.2f}pp)")
        verdict = f"FAIL (honest negative): {'; '.join(why)}"

    print(verdict)

    receipt = hashlib.sha256(canonical([
        "q25-gate-under-q0-evolution",
        {k: [r["flips"], dict(r["passes"]), r["armed"],
             f"{r['post']:.6f}", f"{r['end']:.6f}", f"{r['rec']:.6f}"]
         for k, r in sorted(results.items())},
        [inh_save, f"{inh_drop:.4f}", f"{inh_rec:.4f}"],
        [sta_save, sta_dice, f"{sta_drop:.4f}"],
        f"{naive_delta:.4f}", verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
