#!/usr/bin/env python3
"""
Q11 LEDGER MEMORY HORIZON: q10's law — "per-cell ledger evidence decays on
the same clock as the age sensor's hold, so refill signal and molt timing
are structurally misaligned — a refill that could win must read evidence
that outlives the window (longer ledger memory) or molts stay out."

q10's CELL refill (91.7%) beat AGE (86.7%) but lost to NEVER (96.7%):
post-window refills were 0-2 valid because the trailing REWARD_WINDOW=20
expires the evidence before molts at t>=120 fire.

Claim under test (honest, falsifiable):
  If the refill reads a LONGER ledger memory (horizon H >= 40 ticks,
  outliving the META_PERIOD=30 molt cadence), post-flip molts refill
  with still-evidenced valid cells and CELL@H beats NEVER (96.7%) on
  settled post-flip coverage.

  Counter-hypothesis the same run adjudicates: longer memory also
  preserves PRE-flip evidence for now-dead facts (0-59 were valid
  pre-flip), so a horizon that outlives the window also outlives the
  regime — stale evidence misranks dead cells above fresh ones and
  CELL@H degrades toward or below CELL@20. If BOTH hold, the law is:
  no single horizon works both ways (fresh AND durable) across a flip.

Arms: NEVER, CELL@20 (q10 reproduction), CELL@40, CELL@60, CELL@INF.
Same q8 age-at-zero molt gate, same q4 meta-swap, identical stacks
until the flip. Refill reads only the per-fact reward ledger at its
own horizon + fnv1a filler; never reads valid_universe().

        "stale" in refills carries the falsifier: pre-flip evidence on
  now-dead facts. If stale rises with H and coverage falls, the
  counter-law holds. If some H beats NEVER, q10's fix works.

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if some CELL@H (H>=40) beats
NEVER on settled post-flip coverage.
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
REWARD_WINDOW = 20   # default trailing append window; per-arm retention
                        # scales with the refill horizon H (see run_arm)
AGE_HOLD = 15
STRESS_CAPACITY = 62
EPS = 1e-9

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]

HORIZONS = [20, 40, 60, "inf"]   # refill ranking horizons; 20 == q10 repro


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


def evidenced_reward(entries, k, horizon):
    """Reward mass visible to the refill at horizon H."""
    lo = k - horizon if horizon != "inf" else -(10 ** 9)
    return sum(r for (t, r) in entries if t > lo)


def run_arm(gate: str, horizon, capacity: int = CAPACITY):
    """gate: 'none' | 'cell'. horizon: int ticks or 'inf' (refill ranking)."""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    # retention scales with the horizon: the ledger must actually HOLD
    # H ticks of history for a H-horizon refill to read it. H=20 is the
    # q10 reproduction (identical retention).
    retention = 20 if horizon is None else (horizon if horizon != "inf" else 10 ** 9)
    trim_to = min(retention, REWARD_WINDOW) if retention == 20 else retention
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}    # fact -> trailing REWARD_WINDOW entries (q10 mechanics)
    last_gain = {}
    molts = []
    refills = []        # (tick, n_added, n_valid_added, n_evidenced_now,
                        #           n_evidenced_stale_pre_flip)
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost

        uni = valid_universe(k)
        for f in held:
            r = 1 if f in uni else 0
            if r:
                last_gain[f] = k
            fact_reward.setdefault(f, []).append((k, r))
            fr = fact_reward[f]
            while fr and fr[0][0] <= k - trim_to:
                fr.pop(0)

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)

        if k > 0 and k % META_PERIOD == 0:
            if gate == "cell" and last_molt_meta != k // META_PERIOD:
                dead = {f for f in held
                        if k - last_gain.get(f, -AGE_HOLD) >= AGE_HOLD}
                if dead:
                    vdead = len(dead & uni)   # instrumentation only
                    held = frozenset(held - dead)
                    molts.append((k, len(dead), vdead))
                    last_molt_meta = k // META_PERIOD
                    if len(held) < capacity:
                        added = set()
                        quota = capacity - len(held)
                        # Q11 per-cell refill ranked at horizon H
                        cands = [f for f in range(FACTS) if f not in held]
                        scored = []
                        for f in cands:
                            ev = evidenced_reward(fact_reward.get(f, []), k, horizon)
                            if ev > 0:
                                scored.append((ev, f))
                        scored.sort(key=lambda t: (-t[0], t[1]))
                        for (_, f) in scored:
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
                            # stale = evidenced pre-flip reward on a now-dead fact
                            stale = sum(
                                1 for f in added
                                if f not in uni and any(
                                    t < FLIP and r
                                    for (t, r) in fact_reward.get(f, [])))
                            nev = sum(
                                1 for f in added
                                if evidenced_reward(
                                    fact_reward.get(f, []), k, horizon) > 0)
                            held = frozenset(held | added)
                            refills.append((k, len(added), vadd, nev, stale))
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
    print("Q11: ledger memory horizon for per-cell refill (q10's law)")
    print("=" * 62)

    print(f"\n--- stress condition (q6-q10): capacity {STRESS_CAPACITY}, "
          f"age-hold {AGE_HOLD}, reward-window {REWARD_WINDOW}, "
          f"molt cadence {META_PERIOD} ---")
    res = {}
    res["NEVER"] = run_arm("none", None, STRESS_CAPACITY)
    cov, floor, stack, arch, molts, refills, rec = res["NEVER"]
    print(f"\n{'NEVER':9s}: settled {cov:.3%} | floor {floor:.3%} | "
          f"recover@90% t+{rec} | stack {stack} | archived {arch}")
    for h in HORIZONS:
        label = f"CELL@{h}"
        res[label] = run_arm("cell", h, STRESS_CAPACITY)
        cov, floor, stack, arch, molts, refills, rec = res[label]
        print(f"\n{label:9s}: settled {cov:.3%} | floor {floor:.3%} | "
              f"recover@90% t+{rec} | stack {stack} | archived {arch}")
        print(f"          molts {molts if molts else 'none'}")
        for r in refills:
            k, n, v, ev, stale = r
            print(f"          refill t={k}: +{n} cells, {v} valid, "
                  f"{ev} evidenced@H, {stale} stale-pre-flip")

    n_cov = res["NEVER"][0]
    long_covs = {f"CELL@{h}": res[f"CELL@{h}"][0] for h in HORIZONS if h != 20}
    ok_zero_valid_molt = all(
        all(m[2] == 0 for m in res[f"CELL@{h}"][4]) for h in HORIZONS)
    winner = max(long_covs, key=long_covs.get)
    ok_horizon_beats_never = long_covs[winner] > n_cov
    monotone_fresh_beats_long = (res["CELL@20"][0]
                                 >= max(long_covs.values()))
    print(f"\nCLAIM 1 (some horizon H>=40 beats NEVER {n_cov:.3%}): "
          f"{'PASS' if ok_horizon_beats_never else 'FAIL'} "
          f"(best {winner} {long_covs[winner]:.3%})")
    print(f"CLAIM 2 (zero valid facts molted, all horizons): "
          f"{'PASS' if ok_zero_valid_molt else 'FAIL'}")
    print(f"OBSERVATION A (memory that outlives the window also outlives "
          f"the regime — fresh CELL@20 >= all longer horizons): "
          f"{'CONFIRMED' if monotone_fresh_beats_long else 'REFUTED'} "
          f"(CELL@20 {res['CELL@20'][0]:.3%} vs long max "
          f"{max(long_covs.values()):.3%})")
    receipt = hashlib.sha256(canonical([
        "q11-ledger-horizon", f"{n_cov:.6f}",
        [f"{res[f'CELL@{h}'][0]:.6f}" for h in HORIZONS],
        res["NEVER"][2],
        [res[f"CELL@{h}"][2] for h in HORIZONS],
        [[(k, n, v, ev, st) for (k, n, v, ev, st) in res[f"CELL@{h}"][5]]
         for h in HORIZONS],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = ok_horizon_beats_never and ok_zero_valid_molt
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
