#!/usr/bin/env python3
"""Eviction policy POC — Swarm Lane C2: when summaries outnumber cells.

C1 (compression/poc.py) froze a non-selected agent into ONE linkable summary
doc (tiers K/D/T/P, id = sha256 of the doc). C2 asks the registry question:
when summaries outnumber cells, WHICH summaries are evicted?

The law carried over from C1: **doubts are stamped, not lowered — and a
doubt is a REFERENCE POINT other agents cite.** A summary that is the last
holder of a doubt coordinate (question, watch) is irreplaceable reference
knowledge no matter how cold its access count is. Evicting it does not lose
"bytes" — it loses the only evidence that anyone ever probed that edge.

THE CRITERION (this lane's answer):
  evictability = redundancy, never rank alone.
  A summary is evictable iff some other summary covers what it knows;
  the accessibility score (uses × recency) orders evictions ONLY among
  the redundant. The uniqueness floor protects last holders.

This POC builds 100 seed summaries from simulated agents (no RNG — the
world stream is fnv1a content-derived, fleet law), runs 10 eviction cycles
under three strategies, and measures:
  (a) inheritance speed for future agents (ticks to first gate fire)
  (b) retrieval of useful knowledge (hit rate, ticks saved vs fresh)
  (c) retention of critical edge-case doubts (coordinate coverage,
      near-miss stamps, last-holder destruction events)

Run:  python3 compression/eviction_policy.py [access|diversity|hybrid|full]
See compare_eviction.py for the three-strategy comparison table.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poc import Cell, fnv1a, canonical, sha  # noqa: E402  (C1 machinery)

TICKS = 32        # agent lifetime before compression (C1 law)
CAP_TICKS = 120   # per-task tick budget (censored at this count)
GAMMA = 0.75      # recency decay per round in the access score

COMMON_QS = ["relay/alive?", "pinch/match?", "route/fast?", "cargo/intact?",
             "signal/clear?", "power/steady?"]
RARE_QS = ["listener/veto?", "storm/skip?", "ghost/echo?", "tail/overflow?",
           "beam/clip?"]
ALL_QS = COMMON_QS + RARE_QS
ANSWERS = ("yes", "no")

# base rate of answers[0]; flip = tick where rate inverts (C1's drift world)
WORLDS = {
    "relay/alive?":   (0.85, None),
    "pinch/match?":   (0.70, None),
    "route/fast?":    (0.75, None),
    "cargo/intact?":  (0.90, None),
    "signal/clear?":  (0.65, None),
    "power/steady?":  (0.80, None),
    "listener/veto?": (0.20, 24),   # drifts 0.20 -> 0.80 at tick 24
    "storm/skip?":    (0.55, None),
    "ghost/echo?":    (0.15, None),
    "tail/overflow?": (0.62, None),
    "beam/clip?":     (0.35, None),
}

NEAR_MISS = 0.12  # deficit below this = near-miss doubt (C1's pinch/match was 0.07)


def world_answer(q, t):
    base, flip = WORLDS[q]
    rate = (1.0 - base) if (flip is not None and t >= flip) else base
    bit = fnv1a(f"{q}:{t}") % 10000 / 10000.0
    return ANSWERS[0] if bit < rate else ANSWERS[1]


def ticks_to_fire(cell, theta, q, t0, cap=CAP_TICKS):
    """Ticks from the task's own world stream until the gate fires."""
    for t in range(t0, t0 + cap):
        cell.tick(world_answer(q, t))
        ok, _ = cell.gate(ANSWERS[0], theta)
        if ok:
            return t - t0 + 1
    return cap  # censored: gate never fired inside the budget


# ── deterministic agent designs ──────────────────────────────────────────
def agent_questions(i):
    """Design of agent i: 2–4 common cells; rare questions enter at a 1.5%
    draw (so most rare coordinates end up with 1–4 holders EVER)."""
    d = fnv1a(f"agent:{i}")
    n = 2 + d % 3
    qs = []
    for s in range(n):
        q = COMMON_QS[fnv1a(f"agent:{i}:slot:{s}") % len(COMMON_QS)]
        if q not in qs:
            qs.append(q)
    for q in RARE_QS:
        if fnv1a(f"watch:{i}:{q}") % 1000 < 15:
            qs.append(q)
    return qs


def build_pool(n_total, seed_n=100):
    pool = [agent_questions(i) for i in range(n_total)]
    for q in RARE_QS:  # fail-loud coverage: no rare q may start orphaned
        if not any(q in pool[i] for i in range(seed_n)):
            j = fnv1a(f"cover:{q}") % seed_n
            if q not in pool[j]:
                pool[j].append(q)
    return pool


POOL = build_pool(145)  # 100 seed agents + 45 arrivals (5 per round x 9)


# ── agent -> summary (C1 format, tiers K/D/T light/P) ───────────────────
def build_summary(i):
    cells, doubts, fired = [], [], []
    for q in POOL[i]:
        theta = 0.55 + (fnv1a(f"theta:{i}:{q}") % 30) / 100.0
        cell = Cell(q, ANSWERS)
        fired_at, p_half = None, None
        for t in range(1, TICKS + 1):
            cell.tick(world_answer(q, t))
            if t == TICKS // 2:
                p_half = cell.dist()[ANSWERS[0]]
            if fired_at is None and cell.gate(ANSWERS[0], theta)[0]:
                fired_at = t
        p = cell.dist()[ANSWERS[0]]
        lb = cell.lower_bound(ANSWERS[0])
        n_eff = round(cell.n_eff(), 1)
        if n_eff < 8:
            label = "thin"
        else:
            label = "converged" if abs(p - p_half) < 0.10 else "drifting"
        cells.append({
            "question": q, "answers": list(ANSWERS),
            "counts": [round(c, 4) for c in cell.counts], "n": cell.n,
            "alpha": cell.alpha, "lam": cell.lam, "head": cell.head,
            "p_watch": round(p, 4), "traj": label,
        })
        if fired_at is None:
            doubts.append({  # DOUBT STAMPED, NOT LOWERED (two-ledgers law)
                "question": q, "watch": ANSWERS[0], "p": round(p, 4),
                "lb95": round(lb, 4), "theta": round(theta, 4),
                "deficit": round(theta - lb, 4), "n_eff": n_eff,
            })
        else:
            fired.append({"question": q, "tick": fired_at})
    doc = {"agent": f"sim-{i:03d}", "frozen_tick": TICKS,
           "cells": cells, "doubts": doubts, "fired": fired}
    doc["id"] = sha(canonical(doc))
    return doc


DOCS = {i: build_summary(i) for i in range(len(POOL))}


# ── registry ─────────────────────────────────────────────────────────────
class Registry:
    def __init__(self, capacity):
        self.capacity = capacity
        self.entries = {}  # id -> {doc, uses, last, born}

    def admit(self, doc, rnd):
        self.entries[doc["id"]] = {"doc": doc, "uses": 0, "last": rnd, "born": rnd}

    def evict(self, sid):
        del self.entries[sid]

    def coords(self):
        """(question, watch) -> set of ids whose doubt stamp holds it."""
        out = {}
        for sid, e in self.entries.items():
            for d in e["doc"]["doubts"]:
                out.setdefault((d["question"], d["watch"]), set()).add(sid)
        return out

    def best_for(self, q):
        """Registry summary with the strongest evidence on q (max p_watch)."""
        best = None
        for sid in sorted(self.entries):
            for c in self.entries[sid]["doc"]["cells"]:
                if c["question"] == q:
                    if best is None or c["p_watch"] > best[1]:
                        best = (sid, c["p_watch"])
        return best[0] if best else None

    def touch(self, sid, rnd):
        self.entries[sid]["uses"] += 1
        self.entries[sid]["last"] = rnd


def access_score(e, rnd):
    return e["uses"] * (GAMMA ** (rnd - e["last"]))


def _jac(a, b):
    u = a | b
    return (len(a & b) / len(u)) if u else 0.0


def similarity(doc_a, doc_b):
    """0..1: is doc_a's knowledge covered by doc_b? (questions + doubts)"""
    qa = {c["question"] for c in doc_a["cells"]}
    qb = {c["question"] for c in doc_b["cells"]}
    da = {(d["question"], d["watch"]) for d in doc_a["doubts"]}
    db = {(d["question"], d["watch"]) for d in doc_b["doubts"]}
    return 0.5 * _jac(qa, qb) + 0.5 * _jac(da, db)


def max_redundancy(reg, sid, among):
    doc = reg.entries[sid]["doc"]
    best = 0.0
    for t in among:
        if t != sid:
            s = similarity(doc, reg.entries[t]["doc"])
            if s > best:
                best = s
    return best


# ── eviction strategies: each returns (ids_to_evict, forced_count) ───────
def choose_evictions(reg, need, strategy, rnd):
    if need <= 0:
        return [], 0
    ids = sorted(reg.entries)

    if strategy == "full":  # control: never evict
        return [], 0

    if strategy == "access":
        # classic cache: lowest (uses x recency) goes first; ties -> oldest
        # -> id. BLIND to uniqueness: that blindness is the measured cost.
        order = sorted(ids, key=lambda sid: (
            access_score(reg.entries[sid], rnd),
            reg.entries[sid]["last"], sid))
        return order[:need], 0

    if strategy == "diversity":
        # greedy max-redundancy: evict the summary best covered by the rest.
        # BLIND to access: may evict a hot summary if a sibling covers it.
        alive = set(ids)
        chosen = []
        while len(chosen) < need and alive:
            pick, pick_sim = None, -1.0
            for sid in sorted(alive):  # sorted -> deterministic tie-break
                s = max_redundancy(reg, sid, alive)
                if s > pick_sim + 1e-12:
                    pick, pick_sim = sid, s
            chosen.append(pick)
            alive.discard(pick)
        return chosen, 0

    if strategy == "hybrid":
        # uniqueness floor: last holders of any doubt coordinate are
        # unevictable unless the registry forces it. Among the rest,
        # evict lowest hybrid score (access + non-redundancy).
        coords = reg.coords()
        last_holders = set()
        for holders in coords.values():
            if len(holders) == 1:
                last_holders |= holders
        evictable = [sid for sid in ids if sid not in last_holders]
        if len(evictable) >= need:
            accs = {sid: access_score(reg.entries[sid], rnd) for sid in evictable}
            amax = max(accs.values()) or 1.0
            def hscore(sid):
                acc = accs[sid] / amax
                red = max_redundancy(reg, sid, set(ids))
                return 0.6 * acc + 0.4 * (1.0 - red)
            order = sorted(evictable, key=lambda sid: (hscore(sid), sid))
            return order[:need], 0
        # registry pressure > protection: forced evictions, fewest-unique-first
        forced_need = need - len(evictable)
        def n_unique(sid):
            return sum(1 for h in coords.values() if h == {sid})
        forced_order = sorted(last_holders, key=lambda sid: (
            n_unique(sid), reg.entries[sid]["uses"], sid))
        chosen = evictable + forced_order[:forced_need]
        return chosen, len(forced_order[:forced_need])

    raise ValueError(f"unknown strategy {strategy}")


# ── workload ─────────────────────────────────────────────────────────────
def task_list(n_tasks):
    """Fixed task stream: 82% common / 18% rare worlds, theta in [.50,.74]."""
    tasks = []
    for k in range(n_tasks):
        r = fnv1a(f"task:{k}")
        common = (r % 100) < 82
        qs = COMMON_QS if common else RARE_QS
        tasks.append({
            "k": k, "q": qs[(r >> 8) % len(qs)],
            "theta": round(0.50 + (fnv1a(f"ttheta:{k}") % 25) / 100.0, 2),
            "t0": k * 401 + 1,
        })
    return tasks


def run_task(task, reg, rnd):
    """One future agent against the registry. The fresh run is the
    counterfactual measured on the SAME world stream (fair comparison)."""
    q, theta, t0 = task["q"], task["theta"], task["t0"]
    fresh = Cell(q, ANSWERS)
    fresh_n = ticks_to_fire(fresh, theta, q, t0)
    sid = reg.best_for(q)
    if sid is None:
        return {"k": task["k"], "q": q, "hit": False, "sid": None,
                "fresh": fresh_n, "reg": fresh_n}
    doc = reg.entries[sid]["doc"]
    c = next(x for x in doc["cells"] if x["question"] == q)
    child = Cell(q, ANSWERS, genesis=doc["id"])  # structural provenance
    child.counts = list(c["counts"])             # Tier K prior mass
    child.n = c["n"]
    reg_n = ticks_to_fire(child, theta, q, t0)
    reg.touch(sid, rnd)
    return {"k": task["k"], "q": q, "hit": True, "sid": sid,
            "fresh": fresh_n, "reg": reg_n}


# ── the simulation ───────────────────────────────────────────────────────
def simulate(strategy, capacity=60, rounds=9, per_round=24, arrivals=5, seed_n=100):
    assert "random" not in sys.modules, "fleet law violated: random imported"
    reg = Registry(capacity)
    for i in range(seed_n):
        reg.admit(DOCS[i], 0)
    tasks = task_list((rounds + 1) * per_round)
    results, evict_log = [], []
    arrivals_next = seed_n

    # round 0: warm-up workload (access signal), then THE CULL to capacity
    for j in range(per_round):
        results.append(run_task(tasks[j], reg, 0))
    need = len(reg.entries) - capacity
    chosen, forced = choose_evictions(reg, need, strategy, 0)
    evict_log.append(eviction_record(reg, chosen, strategy, 0))
    for sid in chosen:
        reg.evict(sid)
    if forced:
        evict_log[-1]["forced"] = forced

    for r in range(1, rounds + 1):
        for _ in range(arrivals):
            reg.admit(DOCS[arrivals_next], r)
            arrivals_next += 1
        for j in range(per_round):
            results.append(run_task(tasks[r * per_round + j], reg, r))
        need = len(reg.entries) - capacity
        chosen, forced = choose_evictions(reg, need, strategy, r)
        evict_log.append(eviction_record(reg, chosen, strategy, r))
        for sid in chosen:
            reg.evict(sid)
        if forced:
            evict_log[-1]["forced"] = forced

    return {"strategy": strategy, "results": results, "evict_log": evict_log,
            "final_ids": set(reg.entries)}


def eviction_record(reg, chosen, strategy, rnd):
    """What did this batch destroy? Coords whose holders are ALL evicted
    here = the reference is gone (C1's irreplaceability made measurable)."""
    if not chosen:
        return {"round": rnd, "evicted": [], "destroyed_coords": [],
                "nearmiss_destroyed": [], "forced": 0}
    chosen_set = set(chosen)
    coords = reg.coords()
    destroyed = []
    for coord, holders in sorted(coords.items()):
        if holders and holders <= chosen_set:
            destroyed.append(coord)
    docs = {sid: reg.entries[sid]["doc"] for sid in chosen}
    nearmiss = []
    for coord in destroyed:
        for sid in chosen:
            for d in docs[sid]["doubts"]:
                if (d["question"], d["watch"]) == coord and d["deficit"] < NEAR_MISS:
                    nearmiss.append(coord)
    return {"round": rnd, "evicted": chosen, "destroyed_coords": destroyed,
            "nearmiss_destroyed": nearmiss, "forced": 0}


# ── metrics ──────────────────────────────────────────────────────────────
def all_coords_ever():
    out = {}
    for doc in DOCS.values():
        for d in doc["doubts"]:
            out.setdefault((d["question"], d["watch"]), []).append(d)
    return out


def nearmiss_coords():
    return {c for c, ds in all_coords_ever().items() if min(d["deficit"] for d in ds) < NEAR_MISS}


def metrics(sim, control_results):
    res = sim["results"]
    hits = sum(1 for r in res if r["hit"])
    fresh_total = sum(r["fresh"] for r in res)
    reg_total = sum(r["reg"] for r in res)
    regressions = sum(1 for r, c in zip(res, control_results)
                      if c["hit"] and not r["hit"])

    ace = all_coords_ever()
    final_docs = [DOCS_BY_ID[sid] for sid in sim["final_ids"]]
    final_coords = set()
    for doc in final_docs:
        for d in doc["doubts"]:
            final_coords.add((d["question"], d["watch"]))
    nm = nearmiss_coords()
    ev = sim["evict_log"]
    destroyed = [c for e in ev for c in e["destroyed_coords"]]
    lost_forever = [c for c in destroyed if c not in final_coords]
    qcov = len({q for q in ALL_QS
                if any(c["question"] == q for doc in final_docs for c in doc["cells"])})
    rare_cov = sum(1 for q in RARE_QS
                   if any(c["question"] == q for doc in final_docs for c in doc["cells"]))
    m = {
        "strategy": sim["strategy"],
        "tasks": len(res),
        "hits": hits,
        "hit_rate": round(hits / len(res), 4),
        "mean_fresh_ticks": round(fresh_total / len(res), 2),
        "mean_reg_ticks": round(reg_total / len(res), 2),
        "ticks_saved": fresh_total - reg_total,
        "regressions_vs_control": regressions,
        "doubt_coord_coverage": round(len(final_coords & set(ace)) / len(ace), 4),
        "nearmiss_retained": round(len(final_coords & nm) / len(nm), 4) if nm else None,
        "rare_q_coverage": f"{rare_cov}/{len(RARE_QS)}",
        "question_coverage": f"{qcov}/{len(ALL_QS)}",
        "coords_destroyed_events": len(destroyed),
        "coords_lost_forever": len(lost_forever),
        "nearmiss_destroyed_events": sum(len(e["nearmiss_destroyed"]) for e in ev),
        "forced_evictions": sum(e.get("forced", 0) for e in ev),
        "final_size": len(sim["final_ids"]),
    }
    m["receipt"] = sha(canonical({k: v for k, v in m.items()}))[:16]
    return m


DOCS_BY_ID = {doc["id"]: doc for doc in DOCS.values()}


# ── the re-earning demo: what does a destroyed reference cost to rebuild? ─
def reearn_demo(access_sim):
    """Pick a coordinate destroyed under access-based eviction and measure
    the floor cost for a fresh agent to re-derive the lost evidence."""
    for e in access_sim["evict_log"]:
        for coord in e["destroyed_coords"]:
            q = coord[0]
            lost = None
            for sid in e["evicted"]:
                for d in DOCS_BY_ID[sid]["doubts"]:
                    if (d["question"], d["watch"]) == coord:
                        lost = d
            if lost is None or lost["n_eff"] < 8:
                continue
            probe = Cell(q, ANSWERS)
            ticks = 0
            while ticks < 400:
                ticks += 1
                probe.tick(world_answer(q, ticks))
                lb = probe.lower_bound(ANSWERS[0])
                if lb >= lost["lb95"] and probe.n_eff() >= lost["n_eff"]:
                    return coord, lost, ticks, e["round"]
            return coord, lost, None, e["round"]
    return None, None, None, None


def main():
    strategy = sys.argv[1] if len(sys.argv) > 1 else "hybrid"
    print("═" * 74)
    print(f"ZEROCLAW C2 eviction POC — strategy={strategy}  (pool={len(DOCS)}, "
          f"capacity=60, 10 cycles, no RNG)")
    print("═" * 74)

    control = simulate("full")
    sim = simulate(strategy)
    m = metrics(sim, [r for r in control["results"]])
    mc = metrics(control, control["results"])

    print(f"\n── pool anatomy (145 deterministic agents)")
    rare_holders = {q: sum(1 for i in range(len(POOL)) if q in POOL[i]) for q in RARE_QS}
    for q in RARE_QS:
        print(f"   {q:<16} holders-ever={rare_holders[q]}  "
              f"(rare world rate={WORLDS[q][0]}"
              + (f" flip@{WORLDS[q][1]}" if WORLDS[q][1] else "") + ")")
    nm = nearmiss_coords()
    print(f"   near-miss coords (deficit<{NEAR_MISS}): {len(nm)}")

    print(f"\n── per-cycle eviction record ({strategy})")
    for e in sim["evict_log"]:
        tag = ""
        if e["evicted"]:
            tag = (f"  destroyed {len(e['destroyed_coords'])} coord(s)"
                   + (f"  NEAR-MISS LOST: {e['nearmiss_destroyed']}"
                      if e["nearmiss_destroyed"] else "")
                   + (f"  FORCED={e.get('forced', 0)}" if e.get("forced") else ""))
        print(f"   round {e['round']:>2}: evicted {len(e['evicted']):>2}{tag}")

    print(f"\n── metrics")
    for k, v in m.items():
        if k != "strategy":
            print(f"   {k:<26} {v}")
    print(f"   {'control (no eviction)':<26} hits={mc['hits']}  "
          f"mean_reg={mc['mean_reg_ticks']}  cov={mc['doubt_coord_coverage']}")

    if strategy == "access":
        coord, lost, ticks, rnd = reearn_demo(sim)
        if coord:
            print(f"\n── the C1 insight, measured: a destroyed reference")
            print(f"   coord {coord[0]}/{coord[1]} destroyed at round {rnd}")
            print(f"   lost stamp: deficit={lost['deficit']} lb95={lost['lb95']} "
                  f"n_eff={lost['n_eff']}")
            print(f"   re-earn floor (fresh agent to same evidence): {ticks} ticks"
                  if ticks else "   re-earn floor: >400 ticks (could not re-derive)")
            print(f"   (floor only — a fresh agent must ALSO be selected onto a")
            print(f"    rare world before it can spend those ticks)")

    print("\n" + "═" * 74)
    print(f"RECEIPT: {'PASS' if m['final_size'] <= 60 or strategy == 'full' else 'FAIL'} "
          f"strategy={strategy} hits={m['hits']}/{m['tasks']} "
          f"saved={m['ticks_saved']}t cov={m['doubt_coord_coverage']} "
          f"lost_forever={m['coords_lost_forever']} "
          f"receipt={m['receipt']}")
    print("═" * 74)


if __name__ == "__main__":
    main()
