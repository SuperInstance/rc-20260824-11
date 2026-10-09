#!/usr/bin/env python3
"""
Q24: WHICH GROWTH LAYER HOLDS THE LINE — mutate, edges, or the split?
q23's law: the limit gate's savings are RENTED from the non-dice growth
layers' every-tick pressure — releasing dice+mutate+edges (GROWTH) drops
settled post-flip coverage -4.62pp and recovery -5.20pp, because mutate and
edges are what MAINTAIN coverage during a dice skip. q24 asks the obvious
decomposition: is one of the two the load-bearing layer (release it, keep
the other) or is the SPLIT load-bearing (mutate adds what edges would lose,
edges re-adds what mutate would drop)?

Mechanism hypotheses, stated before the run:
  - MUTATE-ONLY release: mutate is a net-zero-size churner (adds a
    footprint, drops 6 cells). Releasing it preserves held size but stops
    footprint rotation — if hash-eviction trims cells mutate would have
    rotated back in, coverage decays and the resume clause churns (q23's
    GROWTH failure mode).
  - EDGES-ONLY release: edges re-adds PEER_FP every tick — a fixed
    top-up. Releasing it removes a constant inflow of peer cells that
    compete for capacity with dice/mutate footprints; if edges is dead
    weight, this arm should SAVE passes at <= 1.0pp drop (a new win).
  - BOTH (q23 GROWTH reproduction): sanity anchor, expected FAIL.

Arms (endo regime, 400 ticks, DWELL=20, SAT=0.60, limit gate everywhere,
dice always gate-released):
  BASE   : q22 limit gate — dice skipped on plateau, mutate+edges run.
  NOMUT  : gate also releases mutate during skip.
  NOEDG  : gate also releases edges during skip.
  BOTH   : gate releases mutate+edges (q23 GROWTH reproduction anchor).

Claims (honest, falsifiable):
  C1 (a single release is safe): at least one of NOMUT / NOEDG saves
     more layer-passes than BASE at <= 1.0pp settled post-flip drop
     AND <= 1.0pp rec5 drop. If both qualify, the larger saver wins C1.
  C2 (the split question): if exactly one arm qualifies and the other
     does not, the split is NOT load-bearing — one layer suffices and
     the qualifying layer's partner is dead weight during skips.
     If both qualify, the split is decomposable. If neither qualifies,
     the split IS load-bearing (each covers what the other loses).
     C2 passes iff the classification is reported honestly from measured
     arms (it is a measurement claim, like q23's C3).
  C3 (anchor reproduction): BOTH reproduces q23's GROWTH failure
     (drop > 1.0pp or rec5 drop > 1.0pp) — guards against silent drift.

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


QUESTION_FPS = [footprint(f"q{i}") for i in range(8)]
PEER_FP = footprint("peer-agent-shared-docs")

HALF_A = frozenset(range(FACTS // 2))
HALF_B = frozenset(range(FACTS // 2, FACTS))


def _other_half(uni):
    return HALF_B if uni == HALF_A else HALF_A


def run_layer(name, held, k):
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
    elif name == "compress":
        if len(held) > CAPACITY:
            scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
            held = frozenset(sorted(scored[:CAPACITY]))
    elif name == "mutate":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "mut", k])) % len(QUESTION_FPS)]
        drop_n = min(6, len(held))
        drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "drop", f, k])))[:drop_n])
        held = (held - drops) | (fp - drops)
    elif name == "edges":
        held = held | PEER_FP
    return frozenset(held)


def run(release: frozenset):
    """Limit gate (arm at dwell>=1, skip-until-break, resume on cov<SAT).
    `release` = layer names also skipped while the gate holds (dice always)."""
    gate_released = {"dice"} | set(release)
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    uni = frozenset(range(FACTS // 2))
    dwell = 0
    for k in range(TICKS):
        if skip == 0 and 1 <= dwell < DWELL:
            skip = TICKS
            armed += 1
        if cov and cov[-1] < SAT:
            skip = 0
        for layer in ("dice", "compress", "mutate", "edges"):
            if skip > 0 and layer in gate_released:
                continue
            held = run_layer(layer, held, k)
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


ARMS = [
    ("BASE", frozenset()),
    ("NOMUT", frozenset(["mutate"])),
    ("NOEDG", frozenset(["edges"])),
    ("BOTH", frozenset(["mutate", "edges"])),   # q23 GROWTH anchor
]


def main():
    print("=" * 62)
    print("Q24: which growth layer holds the line during a dice skip")
    print("=" * 62)

    results = {}
    for label, rel in ARMS:
        cov, flips, passes, armed = run(rel)
        s_post, s_end = settled(cov, flips)
        rec = recovery(cov, flips)
        total = sum(passes.values())
        results[label] = (cov, flips, passes, armed, s_post, s_end, rec, total)
        print(f"\n[endo-{label:<5}] flips {len(flips)} armed {armed} "
              f"layer-passes {total} (dice {passes['dice']} mutate "
              f"{passes['mutate']} edges {passes['edges']} compress "
              f"{passes['compress']}) post {s_post:.4f} end {s_end:.4f} "
              f"rec5 {rec:.4f}")

    b = results["BASE"]
    stats = {}
    for label in ("NOMUT", "NOEDG", "BOTH"):
        r = results[label]
        save = b[7] - r[7]
        drop = (b[4] - r[4]) * 100
        rec_drop = (b[6] - r[6]) * 100
        safe = drop <= 1.0 and rec_drop <= 1.0 and save > 0
        stats[label] = (save, drop, rec_drop, safe)
        print(f"\n[{label} vs BASE] saved {save} layer-passes "
              f"({save / b[7]:.2%}) drop {drop:+.2f}pp rec5 {rec_drop:+.2f}pp "
              f"-> {'SAFE' if safe else 'UNSAFE'}")

    nomut_safe = stats["NOMUT"][3]
    noedg_safe = stats["NOEDG"][3]
    both_anchor_failed = not stats["BOTH"][3]

    c1 = nomut_safe or noedg_safe
    if nomut_safe and noedg_safe:
        split = "DECOMPOSABLE (both single releases safe — neither layer alone holds the line)"
    elif nomut_safe or noedg_safe:
        who = "mutate" if nomut_safe else "edges"
        other = "edges" if nomut_safe else "mutate"
        split = (f"NOT load-bearing — {who} is load-bearing; {other} is "
                 f"releasable dead weight during skips")
    else:
        split = "LOAD-BEARING (each layer covers what the other loses)"
    c2 = True  # measurement claim: classification from measured arms
    c3 = both_anchor_failed
    ok = c1 and c2 and c3

    print(f"\nC1 (a single release is safe): {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (split classified honestly): PASS ({split})")
    print(f"C3 (BOTH anchor reproduces q23 GROWTH failure): "
          f"{'PASS' if c3 else 'FAIL'}")

    best = None
    for label in ("NOMUT", "NOEDG"):
        if stats[label][3]:
            if best is None or stats[label][0] > stats[best][0]:
                best = label
    if ok:
        verdict = (
            f"PASS: {best} releases its layer during dice skips and holds the "
            f"line — saves {stats[best][0]} layer-passes "
            f"({stats[best][0] / b[7]:.2%} of BASE's {b[7]}) at "
            f"{stats[best][1]:+.2f}pp settled drop and "
            f"{stats[best][2]:+.2f}pp rec5 drop; the split is {split}"
        )
    else:
        why = []
        if not c1:
            why.append("neither single release is safe")
        if not c3:
            why.append("BOTH anchor did not reproduce q23's failure — drift")
        verdict = f"FAIL (honest negative): {'; '.join(why)} — the split is {split}"
    print(verdict)

    receipt = hashlib.sha256(canonical([
        "q24-which-growth-layer",
        {lab: [len(r[1]), dict(r[2]), r[3], f"{r[4]:.6f}", f"{r[5]:.6f}",
               f"{r[6]:.6f}", r[7]] for lab, r in results.items()},
        {lab: [s[0], f"{s[1]:.4f}", f"{s[2]:.4f}", s[3]]
         for lab, s in stats.items()},
        split, verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
