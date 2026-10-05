#!/usr/bin/env python3
"""Eviction-policy POC — Swarm Lane C2: which summaries die when summaries outnumber cells?

C1 compressed non-selected agents into linkable summaries (Tier K knowledge,
Tier D doubts stamped-not-lowered). But the swarm keeps accumulating
summaries. When summaries outnumber live cells, something must be evicted.
C1's warning drives this lane: a summary with a near-miss doubt may be the
ONLY reference for a specific edge case — evict it and that case's evidence
vanishes from the swarm.

This POC simulates 50 summaries over 48 doubt coordinates (8 topics x 6
variants), evicts down to CELLS=20 survivors under 3 policies, and measures
what each policy destroys:

  access     — evict least-cited first (classic recency/citation policy;
               blind to doubt structure)
  diversity  — greedily evict the most-redundant summary (max topic-Jaccard
               to current survivors); blind to citations and doubts
  hybrid     — weighted combo: access + anti-redundancy + UNIQUE-DOUBT
               protection + near-miss bonus (the C1 insight, operationalized)

World coherence: the true watch-probability p is a property of the doubt
COORDINATE (the edge case), never of the summary — all hosts of a coordinate
describe the same world and differ only in evidence depth (n_eff). This
makes same-world priors monotone: eviction can never beat no-eviction
(asserted, fail-loud).

Future agents (40, deterministic) each target one doubt coordinate and try
to reach gate-fire LB95 >= theta. If any host summary of that coordinate
survived, they inherit its Tier-K prior (fewer new ticks); else they start
fresh. We report coverage, mean ticks-to-fire, speedup vs fresh, and — the
C1 risk metric — how many SOLE-REFERENCE doubts (and how many near-miss
ones) each policy destroyed.

NO RNG: every world bit derives from fnv1a(content). Stdlib only.
Run: python3 compression/eviction_policy.py
"""

import hashlib
import json
import math

Z95 = 1.6449          # one-sided 95% z-score (same as C1)
THETA = 0.70          # gate firing threshold
NEAR = 0.05           # "near-miss" doubt: deficit <= NEAR at freeze
N_SUM = 50            # summaries in the pool
CELLS = 20            # live cells; eviction floor (evict 30)
N_FUTURE = 40         # future agents probing the archive
TOPICS = ["relay/alive", "motor/overtemp", "gps/drift", "battery/sag",
          "packet/loss", "tide/rip", "anchor/drag", "compass/dev"]
W_ACCESS, W_DIV, W_UNIQUE, W_NEAR = 1.0, 0.8, 2.5, 1.0   # hybrid weights


def fnv1a(s):
    h = 0x811C9DC5
    for ch in s:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return h


def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


class Sum:
    """One C1-style summary: knowledge prior + one stamped doubt + swarm history."""

    def __init__(self, i):
        h = fnv1a(f"C2-SUMMARY-{i}")
        self.sid = f"C2:{sha(str(i))[:12]}"
        self.topic = TOPICS[h % 8]
        self.coord = f"{self.topic}@v{(h >> 3) % 6}"        # doubt coordinate
        self.access = 1 + (h >> 9) % 9                       # citations received
        self.recency = (h >> 13) % 12                        # rounds since last cite
        # World truth is a property of the COORDINATE (the edge case), not the
        # summary: every host of a coord describes the same world, differing
        # only in evidence depth (n_eff).
        self.p = 0.78 + fnv1a(self.coord) % 17 / 100.0
        self.n_eff = 6 + (h >> 21) % 22
        lb = self.p - Z95 * math.sqrt(self.p * (1 - self.p) / self.n_eff)
        while THETA - lb <= 0 and self.n_eff > 1:            # doubts never fired: deficit > 0
            self.n_eff -= 1
            lb = self.p - Z95 * math.sqrt(self.p * (1 - self.p) / self.n_eff)
        self.deficit = THETA - lb                            # stamped, not lowered
        self.prior = (round(self.p * self.n_eff), self.n_eff)  # Tier K: (s0, n0)
        self.fresh = math.ceil(Z95 ** 2 * self.p * (1 - self.p) / (self.p - THETA) ** 2)
        self.diversity = 0.0                                 # set after pool build


def topic_jacc(a, b):
    ta, tb = {a.topic}, {b.topic}
    return len(ta & tb) / len(ta | tb)


def build_pool():
    pool = [Sum(i) for i in range(N_SUM)]
    hosts = {}
    for s in pool:
        hosts.setdefault(s.coord, []).append(s)
    for s in pool:
        s.unique = len(hosts[s.coord]) == 1                  # sole reference for its edge case
        others = [o for o in pool if o is not s]
        s.diversity = 1 - max(topic_jacc(s, o) for o in others)
    lo, hi = min(s.access for s in pool), max(s.access for s in pool)
    for s in pool:
        s.access_n = (s.access - lo) / (hi - lo)             # static normalization for hybrid
    for c, hs in hosts.items():                              # same-world coherence, fail loud
        assert len({(x.p, x.fresh) for x in hs}) == 1, f"incoherent world at {c}"
    assert all(s.deficit > 0 for s in pool), "doubt stamped not lowered: deficit must be > 0"
    assert all(THETA < s.p <= 1.0 for s in pool), "world must be reachable in expectation"
    return pool, hosts


def ticks_inherited(s):
    """New ticks an agent needs given summary s's Tier-K prior (same-world evidence)."""
    s0, n0 = s.prior
    for n in range(0, s.fresh + 1):
        tot = n0 + n
        phat = (s0 + s.p * n) / tot
        if phat - Z95 * math.sqrt(phat * (1 - phat) / tot) >= THETA:
            return n
    return s.fresh                                           # honest prior is never worse


def evict_access(pool):
    """Least-cited first; ties -> staler first."""
    victims, alive = [], list(pool)
    while len(alive) > CELLS:
        v = min(alive, key=lambda s: (s.access, -s.recency, s.sid))
        alive.remove(v)
        victims.append(v)
    return victims


def evict_diversity(pool):
    """Greedily evict max topic-Jaccard to survivors; ties -> least-cited."""
    victims, alive = [], list(pool)
    while len(alive) > CELLS:
        def red(s):
            m = max(topic_jacc(s, o) for o in alive if o is not s)
            return (m, -s.access, s.sid)
        v = max(alive, key=red)
        alive.remove(v)
        victims.append(v)
    return victims


def evict_hybrid(pool):
    """access + anti-redundancy + unique-doubt protection + near-miss bonus."""
    victims, alive = [], list(pool)
    while len(alive) > CELLS:
        def keep(s):
            m = max(topic_jacc(s, o) for o in alive if o is not s)
            score = (W_ACCESS * s.access_n + W_DIV * (1 - m)
                     + W_UNIQUE * s.unique + (W_NEAR if s.deficit <= NEAR else 0.0))
            return (score, s.sid)
        v = min(alive, key=keep)
        alive.remove(v)
        victims.append(v)
    return victims


def measure(pool, hosts, victims):
    dead = {v.sid for v in victims}
    hits, actual, fresh_all = 0, [], []
    for i in range(N_FUTURE):
        coord = pool[(i * 7) % N_SUM].coord                  # spread probes over coordinates
        candidates = [s for s in hosts[coord] if s.sid not in dead]
        fresh = hosts[coord][0].fresh
        fresh_all.append(fresh)
        if candidates:
            hits += 1
            actual.append(ticks_inherited(max(candidates, key=lambda s: s.n_eff)))
        else:
            actual.append(fresh)                             # inheritance lost: start from scratch
    unique_lost = [s for s in victims if s.unique]
    crit_lost = [s for s in unique_lost if s.deficit <= NEAR]
    return {
        "kept": N_SUM - len(victims), "evicted": len(victims),
        "unique_lost": len(unique_lost), "critical_lost": len(crit_lost),
        "coverage": round(100.0 * hits / N_FUTURE, 1),
        "mean_ticks": round(sum(actual) / N_FUTURE, 1),
        "ticks_saved": round(sum(fresh_all) / N_FUTURE - sum(actual) / N_FUTURE, 1),
    }


def run_all():
    pool, hosts = build_pool()
    base = measure(pool, hosts, [])
    rows = [("none (baseline)", base)]
    for name, fn in [("access", evict_access), ("diversity", evict_diversity),
                     ("hybrid", evict_hybrid)]:
        victims = fn(pool)
        assert len(victims) == N_SUM - CELLS, f"{name}: wrong eviction count"
        assert len({v.sid for v in victims}) == len(victims), f"{name}: duplicate victim"
        m = measure(pool, hosts, victims)
        # eviction can never beat no-eviction (same-world priors are monotone)
        assert m["mean_ticks"] >= base["mean_ticks"] - 1e-9, f"{name}: beat baseline? model bug"
        assert m["coverage"] <= base["coverage"] + 1e-9, f"{name}: beat baseline coverage?"
        rows.append((name, m))
    return rows


def table(rows):
    hdr = (f"{'strategy':<16} {'kept':>4} {'evic':>4} {'uniq_lost':>9} {'crit_lost':>9} "
           f"{'cover%':>7} {'mean_ticks':>10} {'saved':>6}")
    lines = [hdr, "-" * len(hdr)]
    for name, m in rows:
        lines.append(f"{name:<16} {m['kept']:>4} {m['evicted']:>4} {m['unique_lost']:>9} "
                     f"{m['critical_lost']:>9} {m['coverage']:>7} {m['mean_ticks']:>10} "
                     f"{m['ticks_saved']:>6}")
    return "\n".join(lines)


def main():
    r1 = run_all()
    r2 = run_all()                                           # determinism: run the world twice
    assert canonical(r1) == canonical(r2), "NON-DETERMINISTIC: runs diverge"
    digest = sha(canonical(r1))[:16]
    print(table(r1))
    print(f"\nDETERMINISM: OK (two runs byte-identical, results sha256[:16]={digest})")
    by = {n: m for n, m in r1}
    a, d, h, b = by["access"], by["diversity"], by["hybrid"], by["none (baseline)"]
    print(f"\nC2 finding: access loses {a['critical_lost']} critical sole-reference doubts "
          f"(diversity {d['critical_lost']}, hybrid {h['critical_lost']}); "
          f"hybrid keeps {h['coverage']}% coverage at {h['mean_ticks']} mean ticks "
          f"(baseline ceiling {b['mean_ticks']}).")
    return r1


if __name__ == "__main__":
    main()
