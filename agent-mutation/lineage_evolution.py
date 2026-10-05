#!/usr/bin/env python3
"""ZEROCLAW agent-mutation M2 — LINEAGE UNDER SELECTION (2026-10-04).

Research question (DESIGN.md #6): when the world flips every generation and
each generation mutates the coupled (lam, rho) pair, does accumulated
mutation wisdom COMPOUND (child pre-adapted; mutations shrink / stay
accurate; lineage holds or beats resets) or RESET (each flip restarts)?

Schedule: good t=1..50 | bad t=51..100 | good t=101..150 (flips at 51, 101).
  gen-0 fresh v0 in good world -> boundary -> coupled mutation -> gen-1 in
  bad world (inherits parent's raw tick ledgers, re-tallied under new lam)
  -> boundary -> coupled mutation -> gen-2 in good world.

Tracks, same deterministic ticks:
  LINEAGE       child = parent.clone_at(mutated genome) each generation
  INDEPENDENT   fresh v0 genome + fresh posteriors every generation
  PARENT-CONT   the unmutated lineage parent left running (mutation's null)

Per generation: mutation_size = L1 genome distance from parent;
mutation_accuracy = fraction of individual gene moves that beat the
unmutated parent on the child's own window (per-move counterfactual).
Mutation evidence = onset probe (clone stepped PROBE ticks into the NEW
regime; drift d = |overall_p - recent_p| of the sense cell). No RNG
anywhere (fleet law); the world stream is fnv1a content-derived.
"""
import hashlib
import json
import sys

GOOD_BIAS, BAD_BIAS = 80, 20            # % of +1 world ticks per regime
WINS = [(1, 50), (51, 100), (101, 150)]  # gen-0/1/2 windows (good,bad,good)
PROBE, RECENT = 10, 20                  # onset-probe ticks; recent-p window
TRIGGER = 0.20                          # drift that means "the world flipped"
LAM_FLOOR, RHO_BASE, RHO_CAP, RHO_GAIN = 0.30, 0.02, 0.12, 0.10
STAB_LAM, STAB_RHO = 0.10, 0.015        # stabilize half-steps (d < TRIGGER)


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for b in s.encode():
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha(obj) -> str:
    return hashlib.sha256(canon(obj).encode()).hexdigest()[:16]


def regime(t: int) -> int:              # +1 good, -1 bad
    return 1 if (t <= 50 or t >= 101) else -1


def world_tick(t: int) -> int:
    bias = GOOD_BIAS if regime(t) > 0 else BAD_BIAS
    return 1 if fnv1a(f"is-light-good:{t}") % 100 < bias else -1


def genome_v0() -> dict:
    return {
        "schema": "zeroclaw-agent-genome/v1",
        "cells": [{"name": "C1", "question": "is-light-good", "lam": 1.0},
                  {"name": "C2", "question": "approach", "lam": 1.0},
                  {"name": "C3", "question": "commit-move", "lam": 1.0}],
        "gates": [{"name": "G1", "src": "C1", "dst": "C2", "kind": "excite",
                   "theta_base": 0.62, "R": 4, "lam_adapt": 0.06, "rho": 0.02},
                  {"name": "G2", "src": "C2", "dst": "C1", "kind": "inhibit",
                   "theta_base": 0.70, "R": 6, "lam_adapt": 0.06, "rho": 0.02},
                  {"name": "G3", "src": "C2", "dst": "C3", "kind": "sign",
                   "theta_base": 0.66, "R": 5, "lam_adapt": 0.06, "rho": 0.02}],
    }


def genome_id(g: dict) -> str:
    return "agnt-" + hashlib.sha256(canon(g).encode()).hexdigest()[:12]


def l1_distance(a: dict, b: dict) -> float:
    """mutation_size: L1 over the mutable genes (cell lam + gate rho)."""
    la = {c["name"]: c["lam"] for c in a["cells"]}
    lb = {c["name"]: c["lam"] for c in b["cells"]}
    ra = {g["name"]: g["rho"] for g in a["gates"]}
    rb = {g["name"]: g["rho"] for g in b["gates"]}
    return round(sum(abs(la[n] - lb[n]) for n in la)
                 + sum(abs(ra[n] - rb[n]) for n in ra), 4)


class Cell:
    """Question + decayed pseudo-counts over an append-only raw tick ledger.
    p = (ups+1)/(ups+downs+2): a Beta/Dirichlet posterior from ticks. lam is
    a read-out policy: decay advances with TIME; a new lam re-tallies the
    SAME ledger (the ledger is truth; history is never rewritten)."""

    def __init__(self, name, question, lam):
        self.name, self.question, self.lam = name, question, lam
        self.ups = self.downs = 0.0
        self.ticks = []

    def decay(self):
        self.ups *= self.lam
        self.downs *= self.lam

    def tick(self, v, t, why):
        if v > 0:
            self.ups += 1.0
        else:
            self.downs += 1.0
        self.ticks.append({"t": t, "v": v, "why": why})

    def rebuild_from_ledger(self, lam):
        raw, by_t = self.ticks, {}
        self.ups = self.downs = 0.0
        self.lam, self.ticks = lam, []
        for r in raw:
            by_t.setdefault(r["t"], []).append(r)
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
        self.theta = float(cfg["theta_base"])
        self.last_fire, self.fires = -10**9, 0

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

    def clone_at(self, genome) -> "Agent":
        """Child FROM live state: ledgers inherited (re-tallied under a new
        lam), gate runtime inherited. Raw ledger never rewritten."""
        child = Agent(genome)
        for name, live in self.cells.items():
            c = child.cells[name]
            c.ups, c.downs, c.ticks = live.ups, live.downs, list(live.ticks)
            if abs(c.lam - live.lam) > 1e-12:
                c.rebuild_from_ledger(c.lam)
        live_g = {g.name: g for g in self.gates}
        for g in child.gates:
            if g.name in live_g:
                for a in ("theta", "fires", "last_fire"):
                    setattr(g, a, getattr(live_g[g.name], a))
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


def run_window(agent, t0, t1) -> dict:
    """Mission: G3 +1 fires (commit votes) must track the TRUE regime."""
    good = bad = 0
    for t in range(t0, t1 + 1):
        for e in agent.step(t):
            if e["gate"] == "G3" and e["emit"] > 0:
                good, bad = (good + 1, bad) if regime(t) > 0 else (good, bad + 1)
    return {"good": good, "bad": bad, "score": good - bad}


def probe_drift(parent, t_next) -> dict:
    """Onset probe: clone runs PROBE ticks into the NEW regime; sense-cell
    drift is the flip evidence (MicroMoth: sense before you commit)."""
    clone = parent.clone_at(parent.genome)
    for t in range(t_next, t_next + PROBE):
        clone.step(t)
    c1 = clone.cells["C1"]
    return {"drift": round(abs(c1.p - c1.recent_p(RECENT)), 4),
            "overall_p": round(c1.p, 4), "recent_p": round(c1.recent_p(RECENT), 4)}


def coupled_mutate(genome, ev):
    """Coupled lam+rho update (M1 law: forgetting needs gate re-opening; and
    widening never tightens — monotone clamps to a drift-proportional band)."""
    d, g2, moves = ev["drift"], json.loads(canon(genome)), []
    if d >= TRIGGER:      # flip sensed -> widen forgetting (both together)
        lam_t = round(max(LAM_FLOOR, 1.0 - d), 4)
        rho_t = round(min(RHO_CAP, RHO_BASE + d * RHO_GAIN), 4)
        why = "flip-sensed:widen"
    else:                 # world looks stable -> re-tighten toward v0
        lam_t, rho_t, why = None, None, "stable:tighten"
    for c in g2["cells"]:
        nl = lam_t if lam_t is not None else round(min(1.0, c["lam"] + STAB_LAM), 4)
        if (lam_t is not None and nl < c["lam"] - 1e-9) or \
           (lam_t is None and nl > c["lam"] + 1e-9):
            moves.append({"gene": f"lam:{c['name']}", "from": c["lam"], "to": nl})
            c["lam"] = nl
    for gt in g2["gates"]:
        nr = rho_t if rho_t is not None else round(max(RHO_BASE, gt["rho"] - STAB_RHO), 4)
        if (rho_t is not None and nr > gt["rho"] + 1e-9) or \
           (rho_t is None and nr < gt["rho"] - 1e-9):
            moves.append({"gene": f"rho:{gt['name']}", "from": gt["rho"], "to": nr})
            gt["rho"] = nr
    return g2, moves, why


def mutation_accuracy(parent, moves, t0, t1) -> dict:
    """Per-move counterfactual on the child's own window: does THIS move
    alone beat the unmutated parent? Fraction that help = accuracy."""
    base = run_window(parent.clone_at(parent.genome), t0, t1)["score"]
    helped = 0
    for m in moves:
        g1 = json.loads(canon(parent.genome))
        kind, name = m["gene"].split(":")
        if kind == "lam":
            next(c for c in g1["cells"] if c["name"] == name)["lam"] = m["to"]
        else:
            next(g for g in g1["gates"] if g["name"] == name)["rho"] = m["to"]
        helped += run_window(parent.clone_at(g1), t0, t1)["score"] > base
    return {"base": base, "helped": helped, "n": len(moves),
            "accuracy": round(helped / len(moves), 4) if moves else None}


def run_track():
    """Pure experiment (fresh agents inside) — callable twice for determinism."""
    log, lineage = [], Agent(genome_v0())   # gen-0: fresh, good world
    for gi, (t0, t1) in enumerate(WINS):
        lin = run_window(lineage, t0, t1)
        ind = run_window(Agent(genome_v0()), t0, t1)  # fresh reset, same ticks
        row = {"gen": gi, "window": [t0, t1],
               "regime": "good" if regime(t0) > 0 else "bad",
               "genome": genome_id(lineage.genome),
               "lineage": lin, "independent": ind}
        log.append(row)
        if gi == len(WINS) - 1:
            break
        ev = probe_drift(lineage, WINS[gi + 1][0])
        child_g, moves, why = coupled_mutate(lineage.genome, ev)
        acc = mutation_accuracy(lineage, moves, *WINS[gi + 1])
        cont = run_window(lineage.clone_at(lineage.genome), *WINS[gi + 1])
        size = l1_distance(lineage.genome, child_g)
        child_sim = run_window(lineage.clone_at(child_g), *WINS[gi + 1])
        if ev["drift"] >= TRIGGER:      # flip-sensed mutation must earn its keep
            assert size == 0 or child_sim["score"] > cont["score"], \
                f"FAIL: flip-sensed mutation did not beat parent-continue " \
                f"({child_sim['score']} vs {cont['score']})"
        assert child_sim["score"] >= cont["score"] or ev["drift"] < TRIGGER, \
            "FAIL: stabilize mutation regressed the lineage"
        row["boundary"] = {"probe": ev, "why": why, "moves": moves,
                           "mutation_size": size, "accuracy": acc,
                           "parent_continue": cont, "child_sim": child_sim,
                           "child_genome": genome_id(child_g)}
        lineage = lineage.clone_at(child_g)  # the selected child runs next
    return log


def main() -> int:
    print("=" * 74)
    print("ZEROCLAW agent-mutation M2 — LINEAGE UNDER SELECTION (no RNG)")
    print("world: good t=1..50 | bad t=51..100 | good t=101..150")
    print("=" * 74)
    log = run_track()
    lin_tot = ind_tot = 0
    for row in log:
        w0, w1 = row["window"]
        lin, ind = row["lineage"], row["independent"]
        lin_tot += lin["score"]
        ind_tot += ind["score"]
        print(f"\n== GEN-{row['gen']}  t={w0}..{w1} ({row['regime']})  "
              f"genome {row['genome']}")
        print(f"   LINEAGE      good={lin['good']:>2} bad={lin['bad']:>2} "
              f"score={lin['score']:+d}")
        print(f"   INDEPENDENT  good={ind['good']:>2} bad={ind['bad']:>2} "
              f"score={ind['score']:+d}")
        b = row.get("boundary")
        if not b:
            continue
        p = b["probe"]
        print(f"   -- boundary onset-probe: drift={p['drift']:.3f} "
              f"(overall={p['overall_p']:.3f} recent={p['recent_p']:.3f}) "
              f"-> {b['why']}")
        print(f"      mutation_size (L1 from parent) = {b['mutation_size']}")
        acc = b["accuracy"]
        if b["moves"]:
            detail = " ".join(f"{m['gene']}:{m['from']}->{m['to']}"
                              for m in b["moves"])
            print(f"      moves: {detail}")
            print(f"      mutation_accuracy = {acc['helped']}/{acc['n']} "
                  f"= {acc['accuracy']}  (per-move counterfactual; "
                  f"parent-continue base {acc['base']:+d})")
        else:
            print("      moves: NONE — pre-adapted (child genome == parent)")
        pc, cs = b["parent_continue"], b["child_sim"]
        print(f"      next-window preview: parent-continue {pc['score']:+d} "
              f"vs mutated child {cs['score']:+d} -> gen-{row['gen'] + 1} "
              f"runs {b['child_genome']}")
    flips = [(r, r["boundary"]) for r in log[:-1]]
    sizes = [b["mutation_size"] for _, b in flips]
    accs = [b["accuracy"]["accuracy"] for _, b in flips]
    print("\n" + "=" * 74)
    print(f"mutation_size per generation: {sizes}")
    print(f"mutation_accuracy per generation: {accs} "
          f"(None = no move needed: pre-adapted)")
    print(f"flipped-window totals — lineage "
          f"{sum(r['lineage']['score'] for r, _ in flips):+d} vs independent "
          f"{sum(r['independent']['score'] for r, _ in flips):+d}")
    print(f"all-window totals — lineage {lin_tot:+d} vs "
          f"independent {ind_tot:+d}")
    shrink, beats = sizes[-1] < sizes[0], lin_tot >= ind_tot
    verdict = ("COMPOUND — mutations shrank across flips (pre-adaptation) "
               "AND the lineage held or beat fresh resets"
               if shrink and beats else
               "RESET-flavored — mutation size did not shrink, or the "
               "lineage lost to fresh resets (numbers above are the story)")
    print(f"VERDICT: {verdict}")
    receipt = sha(log)
    assert sha(run_track()) == receipt, "FAIL: nondeterministic run"
    print(f"DETERMINISM: second full run bit-identical (receipt {receipt})")
    print("EXIT 0 — invariants held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
