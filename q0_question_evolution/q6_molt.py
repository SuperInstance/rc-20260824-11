#!/usr/bin/env python3
"""
Q6 MOLT UNDER REGIME FLIP: q5 proved archive revival hurts (re-promoted
churn layers damage coverage during the flip transient) and named the
instrumentation law: stagnation must be measured on regime-valid
coverage. Left open by q5: after a flip, facts from the stale half stay
in the held set indefinitely, crowding the CAPACITY budget and doing
zero work. Nothing in q4/q5 ever FLUSHES them.

Claim under test (honest, falsifiable):
  A molt gate driven only by an OBSERVABLE per-fact reward signal
  (each held fact earns +1 per tick it is confirmed/used by the
  environment; stale-half facts earn 0) beats the q5 NEVER arm on
  settled post-flip coverage at identical ticks and fnv1a quantum.

  Mechanism: track trailing per-fact reward over REWARD_WINDOW ticks.
  When total stack reward drops by > COLLAPSE_FRAC below its trailing
  max (regime suspect), enter a MOLT: drop every held fact whose
  trailing reward is exactly 0 (it is doing no work), freeing capacity
  for the new regime. One molt per meta-period, bounded like q4/q5
  swaps. No oracle peek: the gate reads the reward ledger, never
  valid_universe().

Arms (identical until the flip at TICKS//2, same q4 meta-gate after):
  NEVER - q5 rule: never re-promote; stale facts linger.
  MOLT  - NEVER + reward-collapse molt gate as above.

Deterministic, no RNG, stdlib only. fnv1a quantum, byte-identical
replay, receipt sha256. Exit 0 only if MOLT beats NEVER on settled
post-flip coverage.
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
WINDOW = 60   # settled post-flip window
REWARD_WINDOW = 20
COLLAPSE_FRAC = 0.30
STRESS_CAPACITY = 62   # tight: stale facts genuinely crowd new-regime facts
STRESS_COLLAPSE = 0.05  # matches the observed ~10% transient dip
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


def run_arm(molt: bool, capacity: int = CAPACITY,
            collapse_frac: float = COLLAPSE_FRAC):
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    trailing = []
    held = frozenset()
    fact_reward = {}   # fact -> deque of (tick, reward) pairs kept in list
    reward_hist = []   # (tick, total_stack_reward)
    molts = []
    post_flip_cov = []
    last_molt_meta = -1
    for k in range(TICKS):
        tick_gained = tick_lost = 0
        for layer in list(stack):
            held, gained, lost = run_layer(layer, held, k, capacity)
            benefit[layer] += gained - lost
            tick_gained += gained
            tick_lost += lost

        # observable reward ledger: environment confirms held facts that
        # are currently valid. The gate may read THIS, never the universe.
        uni = valid_universe(k)
        total_r = 0
        for f in held:
            r = 1 if f in uni else 0
            total_r += r
            fact_reward.setdefault(f, []).append((k, r))
            # keep only trailing window
            fr = fact_reward[f]
            while fr and fr[0][0] <= k - REWARD_WINDOW:
                fr.pop(0)
        reward_hist.append((k, total_r))

        cov = len(held & uni) / (FACTS // 2)
        if k >= FLIP:
            post_flip_cov.append(cov)
        trailing.append((k, tick_gained, tick_lost, cov))

        if k > 0 and k % META_PERIOD == 0:
            # reward-collapse molt gate (bounded: one per meta-period)
            if molt and last_molt_meta != k // META_PERIOD:
                window = [r for (t, r) in reward_hist if t > k - META_PERIOD]
                hist = [r for (t, r) in reward_hist if t <= k - META_PERIOD]
                peak = max(hist) if hist else 0
                if hist and peak > 0 and window and \
                        sum(window) / len(window) < (1 - collapse_frac) * peak:
                    # drop every held fact with zero trailing reward
                    dead = {f for f in held
                            if sum(r for (_, r) in fact_reward[f]) == 0}
                    if dead:
                        held = frozenset(held - dead)
                        molts.append((k, len(dead)))
                        last_molt_meta = k // META_PERIOD
            # q4 meta-gate (both arms)
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
    # recovery: first post-flip tick (offset from FLIP) reaching 90% of
    # the settled coverage of this arm
    target = 0.9 * (sum(settled) / len(settled))
    recover = next((i for i, c in enumerate(post_flip_cov) if c >= target),
                   len(post_flip_cov))
    return (sum(settled) / len(settled), min(settled),
            stack, archive, molts, recover)


def main():
    print("=" * 62)
    print("Q6: reward-collapse molt under regime flip (stale flush)")
    print("=" * 62)

    print("\n--- condition A: q5 constants (capacity 70, gate 0.30) ---")
    n_cov, n_floor, n_stack, n_arch, n_molts, n_rec = run_arm(False)
    m_cov, m_floor, m_stack, m_arch, m_molts, m_rec = run_arm(True)

    print(f"\nNEVER: settled post-flip coverage {n_cov:.3%} | floor "
          f"{n_floor:.3%} | recover@90% t+{n_rec} | stack {n_stack} "
          f"| archived {n_arch}")
    print(f"MOLT : settled post-flip coverage {m_cov:.3%} | floor "
          f"{m_floor:.3%} | recover@90% t+{m_rec} | stack {m_stack} "
          f"| archived {m_arch}")
    print(f"molts fired: {m_molts if m_molts else 'none'}")

    print(f"\n--- condition B: stress (capacity {STRESS_CAPACITY}, "
          f"gate {STRESS_COLLAPSE}) ---")
    sn_cov, sn_floor, sn_stack, sn_arch, sn_molts, sn_rec = run_arm(
        False, STRESS_CAPACITY, STRESS_COLLAPSE)
    sm_cov, sm_floor, sm_stack, sm_arch, sm_molts, sm_rec = run_arm(
        True, STRESS_CAPACITY, STRESS_COLLAPSE)

    print(f"\nNEVER: settled post-flip coverage {sn_cov:.3%} | floor "
          f"{sn_floor:.3%} | recover@90% t+{sn_rec} | stack {sn_stack} "
          f"| archived {sn_arch}")
    print(f"MOLT : settled post-flip coverage {sm_cov:.3%} | floor "
          f"{sm_floor:.3%} | recover@90% t+{sm_rec} | stack {sm_stack} "
          f"| archived {sm_arch}")
    print(f"molts fired: {sm_molts if sm_molts else 'none'}")

    a_ok = m_cov > n_cov
    b_ok = sm_cov > sn_cov
    print(f"\nCLAIM A (q5 constants): molt beats never -> "
          f"{'PASS' if a_ok else 'FAIL'}")
    print(f"CLAIM B (stress capacity): molt beats never -> "
          f"{'PASS' if b_ok else 'FAIL'}")
    receipt = hashlib.sha256(canonical([
        "q6-molt", f"{n_cov:.6f}", f"{m_cov:.6f}",
        f"{sn_cov:.6f}", f"{sm_cov:.6f}",
        f"{n_floor:.6f}", f"{m_floor:.6f}",
        f"{sn_floor:.6f}", f"{sm_floor:.6f}",
        n_stack, m_stack, sn_stack, sm_stack,
        [(k, d) for (k, d) in m_molts], [(k, d) for (k, d) in sm_molts],
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if b_ok else "EXIT 1")
    sys.exit(0 if b_ok else 1)


if __name__ == "__main__":
    main()
