#!/usr/bin/env python3
"""
Q20 SUSTAINED PLATEAU RELEASE: q18/q19 won with a BINARY release gate —
on the saturation alert, skip dice for a fixed HORIZON=5 ticks, resume on
dip below SAT. q19's gradient showed the gate's fuel is plateau headroom:
at high capacity the plateau sits far above SAT (long dwell, more savings);
at low capacity it hugs SAT (savings shrink to 1.25%). But the fixed
horizon itself is arbitrary: after 5 skipped ticks the gate re-arms and
must wait for a fresh DWELL-HORIZON+1 alert, during which it pays full
dice even while coverage is still pinned at plateau. q20 asks: does
SUSTAINING the release — hold dice off while coverage >= SAT (observable),
resume on the FIRST dip — buy more savings without a coverage cost?

Mechanism under test — sustained vs horizon release:
  (a) Sustained release saves more passes (no re-arm gap) at <=1pp cost;
  (b) The first-dip resume is safe because ANY dip below SAT means the
      plateau broke and dice pressure is needed again (q17's alert
      semantics inverted: dwell = license to rest, dip = duty to spend).
  If sustained release costs >1pp or saves no more than horizon release,
  the horizon is load-bearing, not arbitrary.

Arms: endogenous regime at CAPACITY 70 (q18/q19 setting, SAT from the
same observable plateau probe), BASE vs HORIZON (q18 gate, repro) vs
SUSTAINED. Contrast: exogenous regime, same three arms — the gate should
never fire (coverage never dwells without a reactive universe).

Claims (honest, falsifiable):
  C1 (endo): SUSTAINED savings > HORIZON savings AND settled post-flip
     coverage within 1.0pp of BASE.
  C2 (exo, all arms): no free savings anywhere (law reproduction).

Deterministic, no RNG, stdlib only, fnv1a, receipt sha256.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 400
DWELL = 20
HORIZON = 5
EXO_FLIP = TICKS // 2
CAPACITY = 70
PROBE_TICKS = 150

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


def run_layer(name, held, k, capacity):
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
    elif name == "compress":
        if len(held) > capacity:
            scored = sorted(held, key=lambda f: fnv1a(canonical(["self", "evict", f, k])))
            held = frozenset(sorted(scored[:capacity]))
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


def probe_plateau(capacity):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    held = frozenset()
    cov = []
    uni = HALF_A
    for k in range(PROBE_TICKS):
        for layer in stack:
            held = run_layer(layer, held, k, capacity)
        cov.append(len(held & uni) / len(uni))
    tail = cov[-50:]
    return sum(tail) / len(tail)


def run(mode, gate, sat, capacity=CAPACITY):
    """gate: None (BASE), 'horizon' (q18 fixed skip), 'sustained'."""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    cov = []
    flips = []
    dice_passes = 0
    uni = HALF_A
    dwell = 0
    skip = 0
    for k in range(TICKS):
        if gate == "horizon":
            if skip == 0 and DWELL - HORIZON + 1 <= dwell < DWELL:
                skip = HORIZON
            if skip > 0 and cov and cov[-1] < sat:
                skip = 0
        elif gate == "sustained":
            # release while plateau holds; the FIRST dip resumes dice
            if skip > 0 and cov and cov[-1] < sat:
                skip = 0
            elif skip == 0 and dwell >= DWELL:
                skip = 1  # armed; re-set each tick dwell persists
        if not (gate and skip > 0):
            held = run_layer("dice", held, k, capacity)
            dice_passes += 1
        if gate and skip > 0:
            skip -= 1
        for layer in ("wiring", "compress", "mutate", "edges"):
            held = run_layer(layer, held, k, capacity)
        c = len(held & uni) / len(uni)
        cov.append(c)
        if mode == "exo":
            if k == EXO_FLIP - 1:
                flips.append(k + 1)
                uni = _other_half(uni)
        else:
            dwell = dwell + 1 if c >= sat else 0
            if dwell >= DWELL:
                flips.append(k + 1)
                uni = _other_half(uni)
                dwell = 0
        if k > 0 and k % 30 == 0:
            active = [(benefit[n], n) for n in stack if n != "dice"]
            active.sort()
            worst_b, worst = active[0]
            if worst_b < 0:
                idx = stack.index(worst)
                archive.append(worst)
                candidates = [n for n in LAYER_NAMES
                              if n not in stack and n not in archive]
                if candidates:
                    stack[idx] = candidates[0]
                else:
                    del stack[idx]
    return stack, archive, cov, flips, dice_passes


def settled(cov, flips):
    post = []
    for f in flips:
        post.extend(cov[f:f + 20])
    s_post = sum(post) / len(post) if post else 0.0
    s_end = sum(cov[-50:]) / 50
    return s_post, s_end


def main():
    print("=" * 62)
    print("Q20: sustained plateau release vs horizon release")
    print("=" * 62)

    plateau = probe_plateau(CAPACITY)
    sat = round(max(0.10, plateau - 0.05), 2)
    print(f"capacity {CAPACITY}: probe plateau {plateau:.3f} -> SAT {sat}")

    receipt_parts = {}
    results = {}
    for mode in ("endo", "exo"):
        for gate in (None, "horizon", "sustained"):
            stack, archive, cov, flips, passes = run(mode, gate, sat)
            s_post, s_end = settled(cov, flips)
            arm = f"{mode}-{'BASE' if gate is None else gate.upper()}"
            results[arm] = (flips, passes, s_post, s_end)
            print(f"[{arm}] flips {len(flips)} | passes {passes}/{TICKS} | "
                  f"post-flip {s_post:.4f} | final-50 {s_end:.4f}")

    eb, eh, es = results["endo-BASE"], results["endo-HORIZON"], results["endo-SUSTAINED"]
    save_h = eb[1] - eh[1]
    save_s = eb[1] - es[1]
    drop_h = (eb[2] - eh[2]) * 100
    drop_s = (eb[2] - es[2]) * 100

    c1 = save_s > save_h and drop_s <= 1.0
    c2 = all(
        not (results[f"exo-{a}"][1] < eb[1]
             and (eb[2] - results[f"exo-{a}"][2]) * 100 <= 1.0)
        for a in ("HORIZON", "SUSTAINED"))
    print(f"\nC1 (endo): {'PASS' if c1 else 'FAIL'} — horizon saved {save_h} "
          f"({drop_h:+.2f}pp), sustained saved {save_s} ({drop_s:+.2f}pp)")
    print(f"C2 (exo): {'PASS' if c2 else 'FAIL'} — no free savings in the "
          f"indifferent universe")

    ok = c1 and c2
    verdict = (
        "PASS: sustained plateau release beats horizon release — the "
        "first-dip resume is safe and the fixed horizon was leaving "
        "savings on the table"
        if ok else
        "FAIL: sustained release does not beat horizon release "
        "(no extra savings, or coverage cost >1pp, or the exo contrast "
        "broke) — the horizon is load-bearing")
    print(f"\n{verdict}")

    parts = {
        "sat": sat, "plateau": f"{plateau:.4f}", "capacity": CAPACITY,
        "arms": [[results[a][0], results[a][1],
                  f"{results[a][2]:.6f}", f"{results[a][3]:.6f}"]
                 for a in sorted(results)],
    }
    receipt = hashlib.sha256(canonical([
        "q20-sustained-plateau-release",
        parts, f"{c1}", f"{c2}", verdict,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
