#!/usr/bin/env python3
"""ZEROCLAW agent-mutation M2 — LINEAGE UNDER SELECTION (2026-10-04).
Q (DESIGN.md #6): the world flips every generation; each generation mutates
the coupled (lam, rho) pair. Does accumulated mutation wisdom COMPOUND
(mutations shrink; lineage holds vs resets) or RESET (each flip restarts)?
Schedule: good t=1..50 | bad t=51..100 | good t=101..150. Tracks, same
deterministic ticks: LINEAGE (child = parent.clone_at(mutated genome);
ledgers inherited, re-tallied under new lam), INDEP (fresh v0 each gen),
FRESH-G (lineage genome, fresh runtime — isolates genome vs ledger).
mutation_size = L1 genome distance from parent; mutation_accuracy =
fraction of single gene moves that beat the unmutated parent on the child's
window. Mutation evidence = onset probe (clone stepped PROBE ticks into the
NEW regime; drift = |overall_p - recent_p| of the sense cell). No RNG
anywhere (fleet law); the world is fnv1a content-derived."""
import hashlib, json, sys

GOOD_BIAS, BAD_BIAS = 80, 20             # % +1 world ticks per regime
WINS = [(1, 50), (51, 100), (101, 150)]   # gen windows (good, bad, good)
PROBE, RECENT = 10, 20
TRIGGER = 0.20                           # drift that means "world flipped"
LAM_FLOOR, RHO_BASE, RHO_CAP, RHO_GAIN = 0.30, 0.02, 0.12, 0.10
STAB_LAM, STAB_RHO = 0.10, 0.015         # tighten half-steps (d < TRIGGER)

def canon(obj): return json.dumps(obj, sort_keys=True, separators=(",", ":"))
def sha(obj): return hashlib.sha256(canon(obj).encode()).hexdigest()[:16]
def regime(t): return 1 if (t <= 50 or t >= 101) else -1

def world_tick(t):
    h, bias = 0x811C9DC5, GOOD_BIAS if regime(t) > 0 else BAD_BIAS
    for b in f"is-light-good:{t}".encode():
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return 1 if h % 100 < bias else -1

def genome_v0():
    gates = [{"name": n, "src": s, "dst": d, "kind": k, "theta_base": th,
              "R": R, "lam_adapt": 0.06, "rho": 0.02}
             for n, s, d, k, th, R in
             (("G1", "C1", "C2", "excite", 0.62, 4),
              ("G2", "C2", "C1", "inhibit", 0.70, 6),
              ("G3", "C2", "C3", "sign", 0.66, 5))]
    return {"schema": "zeroclaw-agent-genome/v1",
            "cells": [{"name": c, "question": q, "lam": 1.0}
                      for c, q in (("C1", "is-light-good"), ("C2", "approach"),
                                   ("C3", "commit-move"))], "gates": gates}

def genome_id(g): return "agnt-" + hashlib.sha256(canon(g).encode()).hexdigest()[:12]

def l1_distance(a, b):
    """mutation_size: L1 over mutable genes (cell lam + gate rho)."""
    lam = {c["name"]: c["lam"] for c in a["cells"]}
    lam2 = {c["name"]: c["lam"] for c in b["cells"]}
    rho = {g["name"]: g["rho"] for g in a["gates"]}
    rho2 = {g["name"]: g["rho"] for g in b["gates"]}
    return round(sum(abs(lam[n] - lam2[n]) for n in lam)
                 + sum(abs(rho[n] - rho2[n]) for n in rho), 4)

class Cell:
    """Decayed pseudo-counts over an append-only raw tick ledger; p is a
    Beta/Dirichlet posterior from ticks. lam is a read-out policy; decay
    advances with TIME; a new lam re-tallies the SAME ledger."""

    def __init__(self, name, question, lam):
        self.name, self.question, self.lam = name, question, lam
        self.ups = self.downs = 0.0
        self.ticks = []

    def decay(self):
        self.ups *= self.lam
        self.downs *= self.lam

    def tick(self, v, t, why):
        self.ups, self.downs = ((self.ups + 1.0, self.downs) if v > 0
                                else (self.ups, self.downs + 1.0))
        self.ticks.append({"t": t, "v": v, "why": why})

    def rebuild_from_ledger(self, lam):
        by_t = {}
        for r in self.ticks:
            by_t.setdefault(r["t"], []).append(r)
        self.ups = self.downs = 0.0
        self.lam, self.ticks = lam, []
        for t in sorted(by_t):
            self.decay()
            for r in by_t[t]:
                self.tick(r["v"], r["t"], r["why"])

    @property
    def p(self):
        return (self.ups + 1.0) / (self.ups + self.downs + 2.0)

    def recent_p(self, k):
        tail = [r["v"] for r in self.ticks[-k:]] or [0]
        return (sum(1 for v in tail if v > 0) + 1) / (len(tail) + 2)

class Gate:
    def __init__(self, cfg):
        self.cfg, self.name = cfg, cfg["name"]
        self.theta, self.last_fire, self.fires = float(cfg["theta_base"]), -10**9, 0

    def step(self, src_p, t, dst, events):
        self.theta -= self.cfg["rho"] * (self.theta - self.cfg["theta_base"])
        if t - self.last_fire <= self.cfg["R"]:
            return
        k, emit = self.cfg["kind"], None
        if src_p >= self.theta:
            emit = -1 if k == "inhibit" else +1
        elif k == "sign" and src_p <= 1.0 - self.theta:
            emit = -1
        if emit is None:
            return
        self.fires += 1
        self.last_fire = t
        self.theta += self.cfg["lam_adapt"] * (1.0 - self.theta)
        dst.tick(emit, t, f"{self.name}:{k}")
        events.append({"t": t, "gate": self.name, "emit": emit})

class Agent:
    def __init__(self, genome):
        self.genome = genome
        self.cells = {c["name"]: Cell(c["name"], c["question"], c["lam"])
                      for c in genome["cells"]}
        self.gates = [Gate(dict(g)) for g in genome["gates"]]

    def clone_at(self, genome):
        """Child FROM live state: ledgers inherited+re-tallied, runtime kept."""
        child = Agent(genome)
        for name, live in self.cells.items():
            c = child.cells[name]
            c.ups, c.downs, c.ticks = live.ups, live.downs, list(live.ticks)
            if abs(c.lam - live.lam) > 1e-12:
                c.rebuild_from_ledger(c.lam)
        live_g = {g.name: g for g in self.gates}
        for g in child.gates:
            if g.name in live_g:
                lg = live_g[g.name]
                g.theta, g.fires, g.last_fire = lg.theta, lg.fires, lg.last_fire
        return child

    def step(self, t):
        events = []
        for c in self.cells.values():
            c.decay()                     # time advances for EVERY cell
        self.cells["C1"].tick(world_tick(t), t, "world")
        snap = {n: c.p for n, c in self.cells.items()}
        for g in self.gates:
            g.step(snap[g.cfg["src"]], t, self.cells[g.cfg["dst"]], events)
        return events

def run_window(agent, t0, t1):
    """Mission: G3 +1 fires (commit votes) track the TRUE regime."""
    good = bad = 0
    for t in range(t0, t1 + 1):
        for e in agent.step(t):
            if e["gate"] == "G3" and e["emit"] > 0:
                good, bad = ((good + 1, bad) if regime(t) > 0
                             else (good, bad + 1))
    return {"good": good, "bad": bad, "score": good - bad}

def probe_drift(parent, t_next):
    """Clone runs PROBE ticks into the NEW regime; sense-cell drift = evidence."""
    clone = parent.clone_at(parent.genome)
    for t in range(t_next, t_next + PROBE):
        clone.step(t)
    c1 = clone.cells["C1"]
    return {"drift": round(abs(c1.p - c1.recent_p(RECENT)), 4),
            "overall_p": round(c1.p, 4), "recent_p": round(c1.recent_p(RECENT), 4)}

def _apply(items, key, targets, moves):
    for it, nt in zip(items, targets):
        nt = round(nt, 4)
        if abs(nt - it[key]) > 1e-9:
            moves.append({"gene": f"{key}:{it['name']}", "from": it[key], "to": nt})
            it[key] = nt

def coupled_mutate(genome, ev):
    """Coupled lam+rho (M1 law: forgetting needs gate re-opening). Widen
    never tightens: monotone clamps to a drift-proportional band."""
    d, g2, moves = ev["drift"], json.loads(canon(genome)), []
    if d >= TRIGGER:   # flip sensed -> widen forgetting, both genes together
        lam_t, rho_t = max(LAM_FLOOR, 1.0 - d), min(RHO_CAP, RHO_BASE + d * RHO_GAIN)
        why = "flip-sensed:widen"
        _apply(g2["cells"], "lam", [min(c["lam"], lam_t) for c in g2["cells"]], moves)
        _apply(g2["gates"], "rho", [max(g["rho"], rho_t) for g in g2["gates"]], moves)
    else:              # stable -> re-tighten toward v0 by half-steps
        why = "stable:tighten"
        _apply(g2["cells"], "lam", [min(1.0, c["lam"] + STAB_LAM) for c in g2["cells"]], moves)
        _apply(g2["gates"], "rho", [max(RHO_BASE, g["rho"] - STAB_RHO) for g in g2["gates"]], moves)
    return g2, moves, why

def mutation_accuracy(parent, moves, t0, t1):
    """Per-move counterfactual: does THIS move alone beat the unmutated
    parent? (A coupled set can win jointly while most moves lose alone.)"""
    base = run_window(parent.clone_at(parent.genome), t0, t1)["score"]
    helped = 0
    for m in moves:
        g1 = json.loads(canon(parent.genome))
        kind, name = m["gene"].split(":")
        pool = g1["cells"] if kind == "lam" else g1["gates"]
        next(it for it in pool if it["name"] == name)[kind] = m["to"]
        helped += run_window(parent.clone_at(g1), t0, t1)["score"] > base
    return {"base": base, "helped": helped, "n": len(moves),
            "accuracy": round(helped / len(moves), 4) if moves else None}

def run_track():
    """Pure (fresh agents inside) — callable twice for determinism."""
    log, lineage = [], Agent(genome_v0())   # gen-0: fresh, good world
    for gi, (t0, t1) in enumerate(WINS):
        row = {"gen": gi, "window": [t0, t1],
               "regime": "good" if regime(t0) > 0 else "bad", "genome": genome_id(lineage.genome),
               "lineage": run_window(lineage, t0, t1),
               "independent": run_window(Agent(genome_v0()), t0, t1),
               "fresh_genome": run_window(Agent(json.loads(canon(lineage.genome))), t0, t1)}
        log.append(row)
        if gi == len(WINS) - 1:
            break
        ev = probe_drift(lineage, WINS[gi + 1][0])
        child_g, moves, why = coupled_mutate(lineage.genome, ev)
        acc = mutation_accuracy(lineage, moves, *WINS[gi + 1])
        cont = run_window(lineage.clone_at(lineage.genome), *WINS[gi + 1])
        child_sim = run_window(lineage.clone_at(child_g), *WINS[gi + 1])
        flip = ev["drift"] >= TRIGGER
        assert not flip or len(moves) == 0 or child_sim["score"] > cont["score"], \
            f"FAIL: flip mutation didn't beat parent-continue ({child_sim['score']} vs {cont['score']})"
        assert flip or child_sim["score"] >= cont["score"], \
            "FAIL: tighten mutation regressed the lineage"
        row["boundary"] = {"probe": ev, "why": why, "moves": moves,
                           "mutation_size": l1_distance(lineage.genome, child_g),
                           "accuracy": acc, "parent_continue": cont,
                           "child_sim": child_sim, "child_genome": genome_id(child_g)}
        lineage = lineage.clone_at(child_g)   # the selected child runs next
    return log

def main():
    print("=" * 74)
    print("ZEROCLAW M2 — LINEAGE UNDER SELECTION (no RNG) | flips at t=51, t=101")
    print("=" * 74)
    log = run_track()
    tot = {k: sum(r[k]["score"] for r in log) for k in ("lineage", "independent", "fresh_genome")}
    for row in log:
        w0, w1 = row["window"]
        print(f"\n== GEN-{row['gen']}  t={w0}..{w1} ({row['regime']})  genome {row['genome']}")
        for k, lbl in (("lineage", "LINEAGE  (inherited)"),
                       ("fresh_genome", "FRESH-G  (genome, fresh runtime)"),
                       ("independent", "INDEP    (fresh v0)")):
            s = row[k]
            print(f"   {lbl:<32} good={s['good']:>2} bad={s['bad']:>2} score={s['score']:+d}")
        b = row.get("boundary")
        if not b:
            continue
        p = b["probe"]
        print(f"   -- boundary probe: drift={p['drift']:.3f} (overall={p['overall_p']:.3f} "
              f"recent={p['recent_p']:.3f}) -> {b['why']}")
        print(f"      mutation_size (L1 from parent) = {b['mutation_size']}")
        acc = b["accuracy"]
        if b["moves"]:
            print("      moves: " + " ".join(f"{m['gene']}:{m['from']}->{m['to']}" for m in b["moves"]))
            print(f"      mutation_accuracy = {acc['helped']}/{acc['n']} = {acc['accuracy']} "
                  f"(per-move counterfactual; unmutated parent: {acc['base']:+d})")
        else:
            print("      moves: NONE — pre-adapted (child genome == parent)")
        pc, cs = b["parent_continue"], b["child_sim"]
        print(f"      next-window preview: unmutated parent {pc['score']:+d} vs mutated "
              f"child {cs['score']:+d} -> gen-{row['gen'] + 1} runs {b['child_genome']}")
    sizes = [r["boundary"]["mutation_size"] for r in log[:-1]]
    accs = [r["boundary"]["accuracy"]["accuracy"] for r in log[:-1]]
    flips = log[1:]   # windows that STARTED with a flip
    print("\n" + "=" * 74)
    print(f"mutation_size per generation (child's L1 from parent): {sizes}")
    print(f"mutation_accuracy per generation: {accs} (single moves that help alone)")
    print(f"flipped-window totals — lineage {sum(r['lineage']['score'] for r in flips):+d} | "
          f"fresh-genome {sum(r['fresh_genome']['score'] for r in flips):+d} | "
          f"independent {sum(r['independent']['score'] for r in flips):+d}")
    print(f"all-window totals — lineage {tot['lineage']:+d} | fresh-genome {tot['fresh_genome']:+d} | "
          f"independent {tot['independent']:+d}")
    parts = []
    if sizes[-1] < sizes[0]:
        parts.append(f"GENOME WISDOM COMPOUNDS — mutation size shrank ({sizes[0]} -> {sizes[-1]}): "
                     "the lineage pre-adapted into the forgetful band")
    else:
        parts.append("GENOME DID NOT PRE-ADAPT — sizes did not shrink")
    if all(r["boundary"]["child_sim"]["score"] > r["boundary"]["parent_continue"]["score"]
           for r in log[:-1] if r["boundary"]["moves"]):
        parts.append("every flip-sensed mutation beat the unmutated parent")
    if tot["lineage"] < tot["independent"]:
        parts.append(f"LEDGER BAGGAGE: lineage {tot['lineage']:+d} < resets "
                     f"{tot['independent']:+d}; fresh-genome {tot['fresh_genome']:+d} "
                     "— flip-specialist genomes pay a standing tax in stable regimes")
    else:
        parts.append("lineage held vs fresh resets")
    print("VERDICT: " + "; ".join(parts) + ".")
    receipt = sha(log)
    assert sha(run_track()) == receipt, "FAIL: nondeterministic run"
    print(f"DETERMINISM: second full run bit-identical (receipt {receipt})")
    print("EXIT 0 — invariants held")
    return 0

if __name__ == "__main__":
    sys.exit(main())
