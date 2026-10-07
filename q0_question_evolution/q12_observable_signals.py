#!/usr/bin/env python3
"""
Q12 OBSERVABLE SIGNAL AUDIT: q11's law — "the refill signal needs
regime-awareness (which half is alive), which no per-fact reward ledger
contains." Seven consecutive molt negatives (q5-q11) each falsified one
proposed channel. This run does not propose another refill; it audits
WHETHER ANY observable per-cell signal the stack already produces
correlates with post-flip validity among unheld candidate cells.

Claim under test (falsifiable):
  Among unheld candidates at each molt tick, at least one observable
  signal achieves post-flip refill precision >= 0.8 (near-oracle channel
  exists) — signals: reward@20, reward@40, reward@inf, times-held,
  last-held recency, footprint post-flip reward density, and a fnv1a
  placebo control (must sit at baseline to validate the metric).

  Counter-law: no signal clears 0.8 post-flip (placebo at baseline,
  pre-flip sanity check shows the metric CAN detect a good signal —
  reward@20 pre-flip should be near-oracle), then regime information
  exists ONLY in held-set dynamics, never in per-cell candidate
  observables — molts are closed under every observable channel, not
  just reward-ledger channels.

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if a non-placebo signal clears 0.8
post-flip precision with placebo at baseline.
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
WINDOW = 60
AGE_HOLD = 15
STRESS_CAPACITY = 62
EPS = 1e-9

LAYER_NAMES = ["dice", "wiring", "compress", "mutate", "edges", "abstract"]

SIGNALS = ["reward@20", "reward@40", "reward@inf", "times-held",
           "last-held", "fp-density", "placebo"]


def footprint(text: str, max_cells: int = 24) -> frozenset:
    cells = set()
    salt = 0
    while len(cells) < max_cells and salt < 4 * max_cells:
        cells.add(fnv1a(f"{text}#{salt}") % FACTS)
        salt += 1
    return frozenset(cells)


QUESTION_FPS = [footprint(f"q{i}") for i in range(8)]
PEER_FP = footprint("peer-agent-shared-docs")
FP_OF = {}
for i, fp in enumerate(QUESTION_FPS):
    for f in fp:
        FP_OF.setdefault(f, []).append(i)


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
    return frozenset(held)


def run_audit(capacity: int):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    fact_reward = {}     # fact -> [(tick, r)]
    times_held = {}      # fact -> cumulative ticks held (long memory)
    last_held = {}       # fact -> last tick held (long memory)
    molts = []           # (tick, n_dead, per-signal precision dict, quota, baseline)
    for k in range(TICKS):
        for layer in list(stack):
            before = len(held)
            held = run_layer(layer, held, k, capacity)
            benefit[layer] += (len(held) - before) if len(held) >= before else 0
            benefit[layer] -= max(0, before - len(held))

        uni = valid_universe(k)
        for f in held:
            r = 1 if f in uni else 0
            fact_reward.setdefault(f, []).append((k, r))
            times_held[f] = times_held.get(f, 0) + 1
            last_held[f] = k

        if k > 0 and k % META_PERIOD == 0:
            # q8 age-at-zero molt to expose refill capacity (gate identical
            # to q8-q11), then AUDIT signals on the freed quota — but do
            # NOT apply any refill: audit only.
            last_gain = {}
            for f in held:
                ent = fact_reward.get(f, [])
                for (t, r) in reversed(ent):
                    if r:
                        last_gain[f] = t
                        break
            dead = {f for f in held
                    if k - last_gain.get(f, -AGE_HOLD) >= AGE_HOLD}
            if dead and len(held) - len(dead) < capacity:
                quota = capacity - (len(held) - len(dead))
                cands = [f for f in range(FACTS) if f not in held]
                base = sum(1 for f in cands if f in uni) / max(1, len(cands))
                # post-flip reward density per question footprint
                fp_reward = {i: 0 for i in range(len(QUESTION_FPS))}
                for f in held:
                    if f in uni:
                        for i in FP_OF.get(f, []):
                            ent = fact_reward.get(f, [])
                            fp_reward[i] += sum(
                                r for (t, r) in ent if t >= FLIP)
                prec = {}
                for sig in SIGNALS:
                    def score(f, sig=sig):
                        ent = fact_reward.get(f, [])
                        if sig == "reward@20":
                            return sum(r for (t, r) in ent if t > k - 20)
                        if sig == "reward@40":
                            return sum(r for (t, r) in ent if t > k - 40)
                        if sig == "reward@inf":
                            return sum(r for (t, r) in ent)
                        if sig == "times-held":
                            return times_held.get(f, 0)
                        if sig == "last-held":
                            return last_held.get(f, -1)
                        if sig == "fp-density":
                            return sum(fp_reward[i] for i in FP_OF.get(f, []))
                        return fnv1a(canonical(["self", "placebo", f, k]))
                    ranked = sorted(cands, key=lambda f: (-score(f), f))
                    top = ranked[:quota]
                    prec[sig] = sum(1 for f in top if f in uni) / max(1, quota)
                molts.append((k, len(dead), quota, base, prec))
                held = frozenset(held - dead)  # no refill — audit only
            # q4 meta-gate
            active = [(benefit[n], n) for n in stack if n != "dice"]
            active.sort()
            worst_b, worst = active[0]
            if worst_b < 0:
                idx = stack.index(worst)
                archive.append(worst)
                cands2 = [n for n in LAYER_NAMES
                          if n not in stack and n not in archive]
                if cands2:
                    pick = sorted(cands2, key=lambda n: (-benefit[n], n))[0]
                    stack[idx] = pick
                else:
                    del stack[idx]
    return stack, archive, molts


def main():
    print("=" * 62)
    print("Q12: observable per-cell signal audit for post-flip refill")
    print("=" * 62)
    stack, archive, molts = run_audit(STRESS_CAPACITY)
    print(f"final stack {stack} | archived {archive}")
    pre = [m for m in molts if m[0] < FLIP]
    post = [m for m in molts if m[0] >= FLIP]
    print(f"\nmolts: {len(molts)} total ({len(pre)} pre-flip, {len(post)} post-flip)")

    def agg(rows):
        out = {}
        for sig in SIGNALS:
            vals = [r[4][sig] for r in rows]
            out[sig] = (sum(vals) / len(vals)) if vals else float("nan")
        return out

    if pre:
        print("\n--- PRE-FLIP (sanity: metric must detect a good signal) ---")
        a = agg(pre)
        for sig in SIGNALS:
            print(f"  {sig:11s} precision {a[sig]:.3f}")
    print("\n--- POST-FLIP (the audit that matters) ---")
    a = agg(post)
    bases = [r[3] for r in post]
    base = sum(bases) / max(1, len(bases))
    for sig in SIGNALS:
        print(f"  {sig:11s} precision {a[sig]:.3f}  (baseline {base:.3f})")
    for (k, nd, q, b, prec) in post:
        tops = ", ".join(f"{s}={prec[s]:.2f}" for s in SIGNALS)
        print(f"  t={k}: dead {nd}, quota {q}, base {b:.2f} | {tops}")

    placebo_ok = abs(a["placebo"] - base) <= 0.15 + EPS
    winners = [s for s in SIGNALS if s != "placebo" and a[s] >= 0.8]
    sanity_ok = (not pre) or agg(pre)["reward@20"] >= 0.8
    print(f"\nSANITY (pre-flip reward@20 near-oracle >= 0.8): "
          f"{'PASS' if sanity_ok else 'FAIL'}")
    print(f"PLACEBO AT BASELINE (|{a['placebo']:.3f} - {base:.3f}| <= 0.15): "
          f"{'PASS' if placebo_ok else 'FAIL'}")
    print(f"CLAIM (some non-placebo signal >= 0.80 post-flip): "
          f"{'PASS' if winners else 'FAIL'}"
          + (f" -> {winners}" if winners else ""))
    receipt = hashlib.sha256(canonical([
        "q12-observable-audit", stack, archive,
        [(k, nd, q, round(b, 6), {s: round(prec[s], 6) for s in SIGNALS})
         for (k, nd, q, b, prec) in molts],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    ok = bool(winners) and placebo_ok and sanity_ok
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
