#!/usr/bin/env python3
"""
Q16 QUESTION-TOPOLOGY CHURN AS FLIP PREDICTOR: q6-q15 closed the reward
ledger as a gate signal in both directions — coverage (q14) and cost
(q15) — because the ledger's only dip is the growth transient, and the
dice layer rebuilds post-flip coverage at t+0 before any gated extra
pass can matter. The ONE observable channel never audited is the
QUESTION SPACE itself: Q0 (ac03bd3) showed the swarm can evolve its
question topology (merge/split/abstract/reconstruct). If topology
churn — question-pair reward correlations snapping to 1 (MERGE-like)
or single-question reward distributions splitting (SPLIT-like) —
spikes BEFORE a regime flip, a topology gate could spend dice pressure
anticipatorily, a thing no reward-ledger gate can do.

Claim under test (honest, falsifiable):
  In the q5-champion stack (fixed full dice pressure), observable
  per-question reward structure shows a churn spike (MERGE events +
  SPLIT events per trailing window) that anticipates the flip:
  churn precision for "flip within H=10 ticks" beats a hash placebo
  by >= 0.20 absolute at matched alert volume.

  If churn is only coincident-with or posterior-to the flip (rewards
  move when the universe moves, not before), this FAILS honestly and
  the topology channel closes the same way the ledger channel did:
  NO observable channel in the stack anticipates the flip, because
  the flip is exogenous and every observable derives from reward.

Signal (all from the observable per-question reward ledger, no oracle):
  r_i(k) = |held ∩ fp_i ∩ uni(k)|  (answers of question i that paid).
  MERGE event: trailing-W corr(r_i, r_j) crosses above 0.95.
  SPLIT event: r_i's trailing bimodality (dip of midpoint density vs
  cluster means, 2-means on the window) crosses above 0.5.
Placebo: same event counts sampled at hash-shuffled ticks.

Deterministic, no RNG, stdlib only, fnv1a quantum, byte-identical
replay, receipt sha256.
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
CHURN_WINDOW = 40
HORIZON = 10
CORR_TH = 0.95
BIMODAL_TH = 0.5
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
    return frozenset(held)


def run_stack():
    """q5-champion fixed arm; returns per-question reward series."""
    stack = ["dice", "wiring", "compress", "mutate", "edges"]
    archive = []
    benefit = {n: 0 for n in LAYER_NAMES}
    held = frozenset()
    q_rewards = [[] for _ in QUESTION_FPS]  # r_i(k) series
    for k in range(TICKS):
        before = len(held)
        for layer in list(stack):
            held = run_layer(layer, held, k)
        benefit_delta = len(held) - before
        # attribute tick gain to layers crudely is not needed; use net
        # benefit per layer approximated as in q15 (dice keeps its own)
        # — for the meta-gate we reuse q15's per-layer accounting via
        # a simplified net split: all net gain credited to dice, none
        # else (stack order is what matters for reproduction).
        benefit["dice"] += benefit_delta
        uni = valid_universe(k)
        for i, fp in enumerate(QUESTION_FPS):
            q_rewards[i].append(len(held & fp & uni))
        if k > 0 and k % META_PERIOD == 0:
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
    return stack, archive, q_rewards


def corr(a, b):
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va < EPS or vb < EPS:
        return 1.0 if abs(ma - mb) < EPS and va < EPS and vb < EPS else 0.0
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    return cov / ((va * vb) ** 0.5)


def bimodality(xs):
    """Simple 2-means dip statistic on a small window."""
    n = len(xs)
    if n < 4:
        return 0.0
    lo = min(xs)
    hi = max(xs)
    if hi - lo < EPS:
        return 0.0
    # 2-means, deterministic init at quartiles
    c0, c1 = lo + 0.25 * (hi - lo), lo + 0.75 * (hi - lo)
    for _ in range(20):
        a = [x for x in xs if abs(x - c0) <= abs(x - c1)]
        b = [x for x in xs if abs(x - c0) > abs(x - c1)]
        if not a or not b:
            return 0.0
        c0n, c1n = sum(a) / len(a), sum(b) / len(b)
        if abs(c0n - c0) < EPS and abs(c1n - c1) < EPS:
            break
        c0, c1 = c0n, c1n
    mid = (c0 + c1) / 2
    mid_d = sum(1 for x in xs if abs(x - mid) <= abs(x - c0) * 0.5) / n
    return 1.0 - 2.0 * mid_d  # 1 = cleanly split, 0 = unimodal


def churn_events(q_rewards):
    """Walk ticks; emit (kind, tick) when corr/bimodality crosses up."""
    events = []
    nq = len(q_rewards)
    prev_pair_state = {}
    prev_split_state = [False] * nq
    for k in range(CHURN_WINDOW, TICKS):
        win = slice(k - CHURN_WINDOW, k)
        for i in range(nq):
            for j in range(i + 1, nq):
                c = corr(q_rewards[i][win], q_rewards[j][win])
                key = (i, j)
                above = c > CORR_TH
                if above and not prev_pair_state.get(key, False):
                    events.append(("merge", k, i, j))
                prev_pair_state[key] = above
            b = bimodality(q_rewards[i][win])
            above_b = b > BIMODAL_TH
            if above_b and not prev_split_state[i]:
                events.append(("split", k, i))
            prev_split_state[i] = above_b
    return events


def main():
    print("=" * 62)
    print("Q16: question-topology churn as flip predictor")
    print("=" * 62)

    stack, archive, q_rewards = run_stack()
    print(f"\nstack {stack} | archived {archive}")
    for i, fp in enumerate(QUESTION_FPS):
        pre = q_rewards[i][FLIP - 5:FLIP]
        post = q_rewards[i][FLIP:FLIP + 5]
        print(f"  q{i}: pre-flip r {sum(pre)/5:.1f} -> post-flip r "
              f"{sum(post)/5:.1f}")

    events = churn_events(q_rewards)
    pre = [e for e in events if e[1] < FLIP]
    post = [e for e in events if e[1] >= FLIP]
    n_merge = len([e for e in events if e[0] == "merge"])
    n_split = len([e for e in events if e[0] == "split"])
    print(f"\nevents total {len(events)}: {n_merge} merge, {n_split} split")
    print(f"pre-flip events {len(pre)} | post-flip events {len(post)}")
    # anticipatory events: those in [FLIP-HORIZON, FLIP)
    anticipatory = [e for e in events if FLIP - HORIZON <= e[1] < FLIP]
    print(f"anticipatory (flip-{HORIZON}..flip-1): {len(anticipatory)}")
    for e in (pre[:8] if pre else []):
        print(f"  pre : {e[0]} @t={e[1]} {e[2:]}")
    for e in (post[:8] if post else []):
        print(f"  post: {e[0]} @t={e[1]} {e[2:]}")

    # Precision of a churn ALERT for "flip within H ticks", and recall.
    # Alert policy: any event tick t is an alert; positive class =
    # ticks in [FLIP-HORIZON, FLIP).
    alert_ticks = sorted({e[1] for e in events})
    tp = len([t for t in alert_ticks if FLIP - HORIZON <= t < FLIP])
    prec = tp / len(alert_ticks) if alert_ticks else 0.0
    pos_total = HORIZON
    rec = tp / pos_total

    # Placebo: same number of alert ticks, hash-chosen.
    m = len(alert_ticks)
    placebo_ticks = sorted({fnv1a(canonical(["q16-placebo", s])) % TICKS
                            for s in range(4 * m + 8)})[:m]
    ptp = len([t for t in placebo_ticks if FLIP - HORIZON <= t < FLIP])
    pprec = ptp / m if m else 0.0
    print(f"\ntopology alerts: {m} | precision {prec:.3f} | recall {rec:.3f}")
    print(f"hash placebo   : {m} ticks | precision {pprec:.3f}")
    print(f"placebo ticks: {placebo_ticks}")

    ok = (prec - pprec) >= 0.20 and tp > 0
    verdict = ("PASS: question-topology churn anticipates the flip"
               if ok else
               "FAIL: churn is coincident/post-flip only — the flip is "
               "exogenous; every question's reward moves when the "
               "universe moves, never before")
    print(f"\nCLAIM: precision edge >= 0.20 over placebo -> "
          f"{'PASS' if ok else 'FAIL'} ({prec:.3f} vs {pprec:.3f})")
    receipt = hashlib.sha256(canonical([
        "q16-topology-churn", stack, archive,
        n_merge, n_split, len(pre), len(post), len(anticipatory),
        m, f"{prec:.6f}", f"{pprec:.6f}", f"{rec:.6f}",
        [(e[0], e[1]) for e in events],
        placebo_ticks,
    ]).encode()).hexdigest()[:12]
    print(f"receipt {receipt}")
    print("EXIT 0" if ok else "EXIT 1")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
