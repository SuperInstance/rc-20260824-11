#!/usr/bin/env python3
"""Compare eviction strategies — Swarm Lane C2.

Runs the SAME deterministic workload (240 tasks over 10 registry cycles,
pool of 145 summaries, capacity 60) under four policies:

  full       control — no eviction ever (upper bound; registry unbounded)
  access     classic cache law: lowest uses x recency goes first
  diversity  greedy max-redundancy: the best-covered summary goes first
  hybrid     uniqueness floor (last holders of doubt coords are unevictable)
             + access/recency score among the redundant

Measures, per policy:
  (a) inheritance speed   — mean registry ticks to first gate fire
  (b) useful retrieval    — hit rate, ticks saved vs fresh, regressions
  (c) edge-case survival  — doubt-coordinate coverage, near-miss retention,
                            rare-question coverage, last-holder destructions

Deterministic replay: every policy runs TWICE; receipts must match
bit-for-bit, and the fresh counterfactual must be identical across all
policies (same world, same tasks). NO RNG anywhere — fnv1a lineage only.

Run: python3 compression/compare_eviction.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eviction_policy import (  # noqa: E402
    ALL_QS, RARE_QS, DOCS, nearmiss_coords, all_coords_ever, metrics,
    simulate, DOCS_BY_ID,
)

STRATEGIES = ["full", "access", "diversity", "hybrid"]
COLS = [
    ("strategy", "<10"), ("size", ">4"), ("hits", ">5"),
    ("hit%", ">6"), ("meanT", ">6"), ("saved", ">6"), ("regr", ">4"),
    ("cov%", ">6"), ("near%", ">6"), ("rareQ", ">6"), ("dark", ">4"),
    ("lost", ">4"), ("forced", ">6"),
]


def row(m):
    return (
        m["strategy"], m["final_size"], m["hits"],
        round(100 * m["hit_rate"]), m["mean_reg_ticks"], m["ticks_saved"],
        m["regressions_vs_control"], round(100 * m["doubt_coord_coverage"]),
        round(100 * (m["nearmiss_retained"] if m["nearmiss_retained"] is not None else 1.0)),
        m["rare_q_coverage"], m["coord_dark_rounds"],
        m["coords_lost_forever"], m["forced_evictions"],
    )


def main():
    assert "random" not in sys.modules, "fleet law violated: random imported"

    print("═" * 96)
    print("ZEROCLAW C2 — summary-eviction strategy comparison")
    print(f"pool={len(DOCS)} summaries (100 seed + 45 arrivals)  capacity=30  "
          f"cycles=10  tasks=240  world=fnv1a (deterministic)")
    print("═" * 96)

    ace = all_coords_ever()
    nm = nearmiss_coords()
    rare_holders = {q: sum(1 for doc in DOCS.values()
                           if any(c["question"] == q for c in doc["cells"]))
                    for q in RARE_QS}
    print(f"doubt coordinates ever stamped: {len(ace)}   "
          f"near-miss (deficit<0.12): {len(nm)}")
    print("rare-question holders-ever: " +
          ", ".join(f"{q.split('/')[0]}={n}" for q, n in rare_holders.items()))
    print()

    runs = {}
    for s in STRATEGIES:
        sim = simulate(s)
        ctrl = runs["full"]["sim"]["results"] if s != "full" else sim["results"]
        runs[s] = {"sim": sim, "m": metrics(sim, ctrl)}

    # deterministic replay: run each again, receipts must be identical
    replay_ok = True
    for s in STRATEGIES:
        sim2 = simulate(s)
        m2 = metrics(sim2, runs["full"]["sim"]["results"] if s != "full" else sim2["results"])
        if m2["receipt"] != runs[s]["m"]["receipt"]:
            replay_ok = False
            print(f"REPLAY MISMATCH for {s}: {m2['receipt']} != {runs[s]['m']['receipt']}")
    assert replay_ok, "FAIL: deterministic replay broken"
    print("[replay] all 4 strategies re-run: receipts bit-identical ✓")

    # fresh counterfactual identical across strategies (same task stream)
    fresh_lists = [[r["fresh"] for r in runs[s]["sim"]["results"]] for s in STRATEGIES]
    assert all(fl == fresh_lists[0] for fl in fresh_lists), \
        "FAIL: fresh counterfactual diverged across strategies"
    print("[world ] fresh counterfactual identical across all strategies ✓\n")

    header = " ".join(f"{c:>6}" if c != "strategy" else f"{c:<10}" for c, _ in COLS)
    print(header)
    print("-" * len(header))
    for s in STRATEGIES:
        vals = row(runs[s]["m"])
        line = f"{vals[0]:<10}" + " ".join(f"{v:>6}" for v in vals[1:])
        print(line)
    print("-" * len(header))
    print("(size=final registry  hits=inheritances/240  meanT=mean ticks to fire  "
          "saved=ticks saved vs fresh\n regr=fresh-where-control-inherited  "
          "cov%=doubt-coordinate coverage  near%=near-miss retention\n "
          "rareQ=rare questions still covered  dark=coord-rounds with ZERO "
          "registry holders\n lost=coords destroyed & never recovered  "
          "forced=uniqueness-floor breaches)\n")

    f, a, d, h = (runs[s]["m"] for s in STRATEGIES)  # full, access, diversity, hybrid
    # invariant: with LB95-ranked inheritance, an unbounded registry is an
    # upper bound on ticks saved (subset registry -> weaker-or-equal priors)
    for s in STRATEGIES[1:]:
        assert runs[s]["m"]["ticks_saved"] <= f["ticks_saved"] + 0, \
            f"FAIL: {s} saved more ticks than the unbounded control"
    print(f"[bound  ] every evicted registry saves <= control ticks ✓\n")

    print("── reading")
    print(f"  access    : saved {a['ticks_saved']}t (control {f['ticks_saved']}t), "
          f"{a['coord_dark_rounds']} dark coord-rounds, "
          f"{a['coords_destroyed_events']} destruction event(s), "
          f"{a['coords_lost_forever']} lost forever "
          f"(near-miss destroyed: {a['nearmiss_destroyed_events']})")
    print(f"  diversity : coverage {d['doubt_coord_coverage']:.0%}, "
          f"dark {d['coord_dark_rounds']}, rare {d['rare_q_coverage']}, "
          f"regressions {d['regressions_vs_control']}, saved {d['ticks_saved']}t")
    print(f"  hybrid    : coverage {h['doubt_coord_coverage']:.0%}, "
          f"dark {h['coord_dark_rounds']}, rare {h['rare_q_coverage']}, "
          f"regressions {h['regressions_vs_control']}, saved {h['ticks_saved']}t, "
          f"forced {h['forced_evictions']}")

    verdict = []
    if h["coord_dark_rounds"] < a["coord_dark_rounds"]:
        verdict.append(f"uniqueness floor works: hybrid ran {a['coord_dark_rounds'] - h['coord_dark_rounds']} "
                       "fewer dark coord-rounds than access")
    if a["coord_dark_rounds"] > 0 or a["coords_lost_forever"] > 0:
        verdict.append("access-based eviction goes dark on coordinates it "
                       "cannot see — the loss is invisible in every access "
                       "metric (uses, recency) by construction")
    if h["ticks_saved"] == f["ticks_saved"] and h["regressions_vs_control"] == 0:
        verdict.append("hybrid matches the unbounded control on speed-side "
                       "metrics at 30/145 the size — the floor cost nothing")
    if d["regressions_vs_control"] > 0 or d["ticks_saved"] < h["ticks_saved"]:
        verdict.append("pure diversity pays speed for coverage; hybrid pays "
                       "nothing")
    if h["forced_evictions"] == 0:
        verdict.append("zero forced breaches at 4.8x oversubscription: the "
                       "uniqueness floor is affordable, not aspirational")
    print("\n── verdict")
    for v in verdict:
        print(f"  - {v}")

    combined = {s: runs[s]["m"]["receipt"] for s in STRATEGIES}
    print("\n" + "═" * 96)
    print(f"RECEIPT: PASS  receipts full={combined['full']} access={combined['access']} "
          f"diversity={combined['diversity']} hybrid={combined['hybrid']} "
          f"replay=bit-identical world=fnv1a-lineage rng=none")
    print("═" * 96)


if __name__ == "__main__":
    main()
