#!/usr/bin/env python3
"""
Q10 PER-CELL LEDGER REFILL: q9's law — footprint-ranked refill carries ~0
signal because "validity is PER-CELL, not per-footprint ... observable
ledger density cannot transfer to unobserved sibling cells." q9 ranked
footprints; the one observable channel it did not try is the fact's OWN
reward history in the persistent per-fact ledger: fact_reward[] survives
eviction (it is keyed by fact, not by hold-state), so a cell that was
held recently and earned reward is individually evidenced, and the
trailing REWARD_WINDOW=20 expiry means pre-flip rewards go stale before
the post-flip molts fire.

Claim under test (honest, falsifiable):
  After each age-at-zero molt (q8 gate, unchanged), refill freed
  capacity with INDIVIDUAL CELLS ranked by the fact's own trailing
  reward ledger (cells with >=1 reward in the window first, then
  zero-signal cells by fnv1a order as fallback filler only if quota
  remains). CELL-REFILL beats NEVER and beats AGE-only and beats q9's
  FOOTPRINT-REFILL on settled post-flip coverage.

  No oracle peek: refill reads only fact_reward (observable) + fnv1a
  filler order; it never reads valid_universe().

Arms (identical until flip at TICKS//2, same q4 meta-gate):
  NEVER   - q5 rule: never re-promote, no molts.
  AGE     - q8 gate, no refill (best prior control).
  FP      - q9 footprint-ranked refill (reproduces q9 arm).
  CELL    - q8 gate + per-cell ledger-ranked refill (new).

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if CELL beats NEVER, AGE, and FP on
settled post-flip coverage AND molts zero pre-flip VALID facts.
"""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import canonical, fnv1a  # noqa: E402

FACTS = 120
TICKS = 300
FLIP = TICKS // 2
META_PERIOD = 30
CAPACITY = 70
WINDOW = 60       # settled post-flip window
REWARD_WINDOW = 20
AGE_HOLD = 15
STRESS_CAPACITY = 62    # q6-q9 stress condition
EPS = 1e-9

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


def valid_universe(k: int) -> frozenset:
    half = FACTS // 2
    if k < FLIP:
        return frozenset(range(half))
    return frozenset(range(half, FACTS))


def run_layer(name, held, k, capacity=CAPACITY):
    before = len(held)
    if name == "dice":
        fp = QUESTION_FPS[fnv1a(canonical(["self", "dice", k])) % len(QUESTION_FPS)]
        held = held | fp
    elif name == "wiring":
        pass
    elif name == "compress":
        if len(held) > capacity:
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
    return frozenset(held), len(held) - before if len(held) >= before else 0, \
        max(0, before - len(held))


def run_arm(gate: str, capacity: int = CAPACITY):
    """gate: 'none' | 'age' | 'fp' | 'cell'"""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}    # fact -> trailing window of (tick, reward); survives eviction
    last_gain = {}
    molts = []
    refills = []        # (tick, n_added, n_valid_added, n_evidenced)
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost

        # observable reward ledger (refill never reads the universe;
        # universe used only for off-line instrumentation)
        uni = valid_universe(k)
        total_r = 0
        for f in held:
            r = 1 if f in uni else 0
            total_r += r
            if r:
                last_gain[f] = k
            fact_reward.setdefault(f, []).append((k, r))
            fr = fact_reward[f]
            while fr and fr[0][0] <= k - REWARD_WINDOW:
                fr.pop(0)

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)

        if k > 0 and k % META_PERIOD == 0:
            if gate in ("age", "fp", "cell") and last_molt_meta != k // META_PERIOD:
                dead = {f for f in held
                        if k - last_gain.get(f, -AGE_HOLD) >= AGE_HOLD}
                if dead:
                    vdead = len(dead & uni)   # instrumentation only
                    held = frozenset(held - dead)
                    molts.append((k, len(dead), vdead))
                    last_molt_meta = k // META_PERIOD
                    if gate in ("fp", "cell") and len(held) < capacity:
                        added = set()
                        quota = capacity - len(held)
                        if gate == "fp":
                            # q9 FOOTPRINT refill (reproduction)
                            fp_scores = []
                            for i, fp in enumerate(QUESTION_FPS):
                                hits = [f for f in (fp & held)
                                        if any(r for (_, r) in fact_reward.get(f, []))]
                                fp_scores.append((len(hits), i))
                            fp_scores.sort(key=lambda t: (-t[0], t[1]))
                            for (_, i) in fp_scores:
                                if quota <= 0:
                                    break
                                if fp_scores and fp_scores[0][0] == 0:
                                    break
                                for f in sorted(fp - held):
                                    if quota <= 0:
                                        break
                                    added.add(f)
                                    quota -= 1
                        else:
                            # Q10 PER-CELL ledger refill:
                            # rank candidate cells by the fact's OWN
                            # trailing reward evidence (observable), then
                            # fnv1a filler for any remaining quota.
                            cands = [f for f in range(FACTS) if f not in held]
                            evidenced = [f for f in cands
                                         if any(r for (_, r) in fact_reward.get(f, []))]
                            evidenced.sort(key=lambda f: (-sum(r for (_, r)
                                                               in fact_reward.get(f, [])), f))
                            for f in evidenced:
                                if quota <= 0:
                                    break
                                added.add(f)
                                quota -= 1
                            if quota > 0:
                                filler = sorted(cands, key=lambda f: fnv1a(
                                    canonical(["self", "fill", f, k])))
                                for f in filler:
                                    if quota <= 0:
                                        break
                                    added.add(f)
                                    quota -= 1
                        if added:
                            vadd = len(added & uni)   # instrumentation only
                            nev = sum(1 for f in added
                                      if any(r for (_, r) in fact_reward.get(f, [])))
                            held = frozenset(held | added)
                            refills.append((k, len(added), vadd, nev))
            # q4 meta-gate (all arms)
            active = [(benefit[n], n) for n in stack if n != "dice"]
            active.sort()
            worst_b, worst = active[0]
            if worst_b < 0:
                idx = stack.index(worst)
                archive.append(worst)
                candidates = [n for n in LAYER_NAMES
                              if n not in stack and n not in archive]
                if candidates:
                    pick = sorted(candidates,
                                  key=lambda n: (-benefit[n], n))[0]
                    stack[idx] = pick
                else:
                    del stack[idx]
    settled = post_flip_cov[-WINDOW:]
    target = 0.9 * (sum(settled) / len(settled))
    recover = next((i for i, c in enumerate(post_flip_cov) if c >= target),
                   len(post_flip_cov))
    return (sum(settled) / len(settled), min(settled),
            stack, archive, molts, refills, recover)


def main():
    print("=" * 62)
    print("Q10: per-cell ledger refill after age-at-zero molt (q9's law)")
    print("=" * 62)

    print(f"\n--- stress condition (q6-q9): capacity {STRESS_CAPACITY}, "
          f"age-hold {AGE_HOLD}, reward-window {REWARD_WINDOW} ---")
    res = {}
    for label, g in (("NEVER", "none"), ("AGE", "age"),
                     ("FP", "fp"), ("CELL", "cell")):
        res[label] = run_arm(g, STRESS_CAPACITY)
        cov, floor, stack, arch, molts, refills, rec = res[label]
        print(f"\n{label:6s}: settled {cov:.3%} | floor {floor:.3%} | "
              f"recover@90% t+{rec} | stack {stack} | archived {arch}")
        print(f"        molts {molts if molts else 'none'}")
        print(f"        refills {refills if refills else 'none'}")

    n_cov = res["NEVER"][0]
    a_cov = res["AGE"][0]
    f_cov = res["FP"][0]
    c_cov, c_floor, c_stack, c_arch, c_molts, c_refills, c_rec = res["CELL"]

    ok_beats_never = c_cov > n_cov
    ok_beats_age = c_cov > a_cov
    ok_beats_fp = c_cov > f_cov
    ok_zero_valid_molt = all(m[2] == 0 for m in c_molts)
    print(f"\nCLAIM 1 (cell-refill beats never on settled coverage): "
          f"{'PASS' if ok_beats_never else 'FAIL'} "
          f"({c_cov:.3%} vs {n_cov:.3%})")
    print(f"CLAIM 2 (cell-refill beats age-only control): "
          f"{'PASS' if ok_beats_age else 'FAIL'} "
          f"({c_cov:.3%} vs {a_cov:.3%})")
    print(f"CLAIM 3 (cell-refill beats q9 footprint refill): "
          f"{'PASS' if ok_beats_fp else 'FAIL'} "
          f"({c_cov:.3%} vs {f_cov:.3%})")
    print(f"CLAIM 4 (zero valid facts molted, all ticks): "
          f"{'PASS' if ok_zero_valid_molt else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "q10-cell-refill", f"{n_cov:.6f}", f"{a_cov:.6f}", f"{f_cov:.6f}",
        f"{c_cov:.6f}", f"{res['NEVER'][1]:.6f}", f"{c_floor:.6f}",
        res["NEVER"][2], res["CELL"][2],
        [(k, dn, vd) for (k, dn, vd) in res["NEVER"][4]],
        [(k, an, va, ev) for (k, an, va, ev) in c_refills],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = (ok_beats_never and ok_beats_age and ok_beats_fp
          and ok_zero_valid_molt)
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
