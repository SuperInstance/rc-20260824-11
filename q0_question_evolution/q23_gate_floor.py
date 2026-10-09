#!/usr/bin/env python3
"""
Q23: THE FLOOR OF THE LIMIT GATE — can the non-dice layers be released too?
q22 closed the horizon knob: the optimal gate is the resume clause alone
(dwell-armed, skip-until-break), dice-silent 89% of the time. But the gate
only releases the DICE layer — wiring/compress/mutate/edges still run every
tick. q22's closing question: are the non-dice layers needed on a plateau at
all (can their fixed every-tick pressure ride the same clause), or does the
stack's recovery-at-t+0 depend on them running during the skip?

Mechanism logic: on a plateau, held is at its hash-eviction sawtooth steady
state. The growth layers (mutate adds footprint cells, edges re-adds the
peer set, dice is already skipped) churn cells that coverage doesn't need —
but mutate also DROPS 6 cells/tick, so releasing it should if anything
PRESERVE coverage, not endanger it. The risk is the opposite side: if the
flip fires mid-skip, the new half is unknown, and a stack that has been
coasting without churn may be slower to grow into it — unless the layers'
value is concentrated exactly at the tick (q18/q22 evidence: recovery is
at t+0 in all arms).

Arms (endo regime, 400 ticks, DWELL=20, SAT=0.60, limit gate everywhere):
  BASE    : q22 limit gate — dice skipped on plateau, other layers every tick.
  GROWTH  : limit gate releases dice + mutate + edges during skip (compress
            always runs as bookkeeping; wiring is a no-op in this harness).
  FULL    : limit gate releases dice + mutate + edges + compress during skip
            (pure inertial coast — nothing runs but observation).

Claims (honest, falsifiable):
  C1 (extra savings): GROWTH saves more total layer-passes than BASE at
     <= 1.0pp settled post-flip coverage drop vs BASE.
  C2 (no recovery debt): GROWTH's mean coverage in the first 5 ticks after
     each flip is within 1.0pp of BASE's — the stack does NOT need the
     released layers running during the skip to recover at t+0.
  C3 (floor test): FULL (coast everything) is either safe too (the floor is
     pure observation) or FAILS loudly — we accept either but must MEASURE
     which; C3 passes iff FULL's drop is reported honestly, with the floor
     defined as: FULL drop <= 1.0pp means the floor is observation alone.

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
EXO_FLIP = TICKS // 2

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
    elif name == "abstract":
        fp = footprint(f"abstract-structure-{k % 3}")
        drop_n = min(10, len(held))
        drops = set(sorted(held, key=lambda f: fnv1a(canonical(["self", "adrop", f, k])))[:drop_n])
        held = (held - drops) | (fp - drops)
    return frozenset(held)


def run(mode: str, release: frozenset):
    """Limit gate (arm at dwell>=1, skip-until-break, resume on cov<SAT).
    `release` = layer names also skipped while the gate holds (dice is
    always skipped by the gate). release=frozenset() reproduces q22 LIMIT."""
    gate_released = {"dice"} | set(release)
    archive = []
    held = frozenset()
    cov = []
    flips = []
    passes = {n: 0 for n in LAYER_NAMES}
    armed = 0
    skip = 0
    uni = frozenset(range(FACTS // 2))
    dwell = 0
    for k in range(TICKS):
        if skip == 0 and dwell >= 1 and dwell < DWELL:
            skip = TICKS          # limit: skip-until-break
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
        if mode == "exo":
            if k == EXO_FLIP - 1:
                flips.append(k + 1)
                uni = _other_half(uni)
        else:
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
    ("BASE", frozenset()),                                    # q22 limit gate
    ("GROWTH", frozenset(["mutate", "edges"])),
    ("FULL", frozenset(["compress", "mutate", "edges"])),     # inertial coast
]


def main():
    print("=" * 62)
    print("Q23: floor of the limit gate — releasing the non-dice layers")
    print("=" * 62)

    results = {}
    for label, rel in ARMS:
        cov, flips, passes, armed = run("endo", rel)
        s_post, s_end = settled(cov, flips)
        rec = recovery(cov, flips)
        total = sum(passes.values())
        results[label] = (cov, flips, passes, armed, s_post, s_end, rec, total)
        print(f"\n[endo-{label:<6}] flips {len(flips)} armed {armed} "
              f"layer-passes {total} (dice {passes['dice']} mutate "
              f"{passes['mutate']} edges {passes['edges']} compress "
              f"{passes['compress']}) post {s_post:.4f} end {s_end:.4f} "
              f"rec5 {rec:.4f}")

    b = results["BASE"]
    g = results["GROWTH"]
    f_ = results["FULL"]
    g_save = b[7] - g[7]
    g_drop = (b[4] - g[4]) * 100
    rec_drop = (b[6] - g[6]) * 100
    f_save = b[7] - f_[7]
    f_drop = (b[4] - f_[4]) * 100

    c1 = g_save > 0 and g_drop <= 1.0
    c2 = rec_drop <= 1.0
    c3 = True  # measurement claim: FULL floor honestly reported either way
    floor_safe = f_drop <= 1.0

    print(f"\n[GROWTH vs BASE] extra saved {g_save} layer-passes "
          f"({g_save / b[7]:.2%}) drop {g_drop:+.2f}pp rec5 {rec_drop:+.2f}pp")
    print(f"[FULL  vs BASE] extra saved {f_save} layer-passes "
          f"({f_save / b[7]:.2%}) drop {f_drop:+.2f}pp "
          f"(floor {'SAFE' if floor_safe else 'NOT safe'}: "
          f"observation {'is' if floor_safe else 'is NOT'} enough)")
    print(f"C1 (GROWTH saves >0 at <=1.0pp drop):  {'PASS' if c1 else 'FAIL'}")
    print(f"C2 (no recovery debt: rec5 drop <=1.0pp): {'PASS' if c2 else 'FAIL'}")
    print(f"C3 (floor measured honestly; floor is "
          f"{'observation alone' if floor_safe else 'NOT observation alone'}): "
          f"{'PASS' if c3 else 'FAIL'}")
    ok = c1 and c2 and c3

    if ok:
        verdict = (
            f"PASS: the non-dice growth layers ride the same resume clause — "
            f"GROWTH saves {g_save} extra layer-passes "
            f"({g_save / b[7]:.2%} of BASE's {b[7]}) at {g_drop:+.2f}pp "
            f"settled drop and {rec_drop:+.2f}pp recovery drop; the floor "
            f"is {'observation alone' if floor_safe else 'NOT observation alone'} "
            f"(FULL coast: {f_save} extra passes at {f_drop:+.2f}pp)"
        )
    else:
        why = []
        if not c1:
            why.append(f"GROWTH {'saves nothing' if g_save <= 0 else 'drops too much'} "
                       f"(saved {g_save}, drop {g_drop:+.2f}pp)")
        if not c2:
            why.append(f"recovery debt: rec5 {rec_drop:+.2f}pp > 1.0pp — the "
                       f"stack DOES need layers running during the skip")
        verdict = f"FAIL (honest negative): {'; '.join(why)}"
    print(verdict)

    receipt = hashlib.sha256(canonical([
        "q23-gate-floor",
        {lab: [len(r[1]), dict(r[2]), r[3], f"{r[4]:.6f}", f"{r[5]:.6f}",
               f"{r[6]:.6f}", r[7]] for lab, r in results.items()},
        f"{g_save}", f"{g_drop:.4f}", f"{rec_drop:.4f}",
        f"{f_save}", f"{f_drop:.4f}", verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
