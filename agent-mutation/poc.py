#!/usr/bin/env python3
"""ZEROCLAW agent-mutation POC — Swarm Lane M1 (2026-10-04).

Casey's swarm verdict (VERDICTS.md 16:52): "Agent mutation mid-process: each
agent generates at least one new agent design that might be better for the
next step." This POC answers the three M1 questions with a RUNNING agent:

  Q1  What is a new agent design, as a data structure?
      -> AgentGenome: cells (question + decay lam) + gates (wiring) as one
         canonical, content-addressed JSON object. The design IS the genome.
  Q2  How does it differ from the current agent?
      -> A Mutation Delta: operator * evidence -> (genome', delta-record).
         Measurably different = structural (gene-set symmetric difference
         >= 1, genome sha differs) AND behavioral (MicroMoth simulation on
         the same deterministic future stream: fire-sets diverge, mission
         score differs).
  Q3  How is the mutation recorded?
      -> Three layers: (1) chained append-only mutations.jsonl — every
         candidate, selected or stamped (doubt stamped, not lowered);
         (2) the winning child encoded as zeroclaw-reflex-spec/v1 — the
         format pincher's loadZeroclawSpecs/parseZeroclawSpec consumes;
         (3) the i2i ledger receipt (booked from the shell after the run).

NO RNG anywhere (fleet law): the world stream is fnv1a content-derived, and
every mutation is triggered by a diagnostic over the agent's own tick
ledger — the agent mutates from what it lived, not from dice. Dice (moth
quantum / JEV odds) are M2's lane.

Circuit (Lane 2 lineage):      C1 --G1 excite--> C2 --G3 sign--> C3
                                ^                  |
                                +-- G2 inhibit ----+        (negative feedback)
World: 80% +1 ticks until T_FLIP, then 20% +1 (regime goes bad).
Mission: G3 positive fires (commit votes) must track the TRUE regime.
Parent pathology (demonstrated): frozen memory (lam=1.0) + its own feedback
loop keep committing after the world turned bad.

Exit 0 = all invariants held (fail loud: NO VERIFIED SHA, NO BELIEF).
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "out"
SPECS = OUT / "specs"
MUTATIONS = OUT / "mutations.jsonl"

# ---- CONFIG (deterministic world; no seeds, no random) --------------------
T_FLIP = 100            # tick where the world regime flips good -> bad
T_MID = 140             # mid-process: mutation generated HERE from live state
T_END = 200             # end of MicroMoth simulation window
GOOD_BIAS = 80          # % of +1 world ticks in the good regime
BAD_BIAS = 20           # % of +1 world ticks in the bad regime

RECENT_WINDOW = 20      # ticks in the drift diagnostic
DRIFT_TRIGGER = 0.20    # |overall_p - recent_p| that triggers forget-widening
FORGET_LAM = 0.80       # lam proposed by forget-widening (window ~5 ticks:
                         # forgets the flip, still accumulates evidence
                         # between R-spaced gate fires)
FORGET_RHO = 0.05       # coupled: theta-relaxation rate proposed alongside
                         # lam (a forgetful cell needs gates whose thresholds
                         # re-open as fast as its evidence evaporates — an
                         # uncoupled lam-only mutation was falsified: the
                         # child went silent in a good-regime probe)/
HABITUATE_MIN_FIRES = 12
HABITUATE_MIN_UTIL = 0.30
HABITUATE_STEP = 0.10
SPROUT_CONF = 0.80      # terminal-cell confidence that triggers sprout-feedback
SPROUT_THETA, SPROUT_R = 0.75, 8

MISSION = "commit votes (G3 +1 fires) must track the true regime"


def fnv1a(s: str) -> int:
    """32-bit FNV-1a — deterministic entropy (exoj UnitTable lineage)."""
    h = 0x811C9DC5
    for b in s.encode():
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha256_hex(obj) -> str:
    import hashlib
    return hashlib.sha256(canon(obj).encode()).hexdigest()


def world_tick(t: int, bias: int = None) -> int:
    """Deterministic world; bias override exists for counterfactual probes
    (MicroMoth is a simulation — it may ask 'what if the world were good?')."""
    if bias is None:
        bias = GOOD_BIAS if t < T_FLIP else BAD_BIAS
    return 1 if fnv1a(f"is-light-good:{t}") % 100 < bias else -1


def regime(t: int) -> int:
    return 1 if t < T_FLIP else -1


# ---- Q1: the agent design as a data structure ------------------------------

def genome_v0() -> dict:
    """Parent genome: the Lane-2 circuit promoted to a first-class design."""
    return {
        "schema": "zeroclaw-agent-genome/v1",
        "cells": [
            {"name": "C1", "question": "is-light-good", "lam": 1.0},
            {"name": "C2", "question": "approach", "lam": 1.0},
            {"name": "C3", "question": "commit-move", "lam": 1.0},
        ],
        "gates": [
            {"name": "G1", "src": "C1", "dst": "C2", "kind": "excite",
             "theta_base": 0.62, "R": 4, "lam_adapt": 0.06, "rho": 0.02},
            {"name": "G2", "src": "C2", "dst": "C1", "kind": "inhibit",
             "theta_base": 0.70, "R": 6, "lam_adapt": 0.06, "rho": 0.02},
            {"name": "G3", "src": "C2", "dst": "C3", "kind": "sign",
             "theta_base": 0.66, "R": 5, "lam_adapt": 0.06, "rho": 0.02},
        ],
    }


def genome_id(g: dict) -> str:
    """Content-addressed identity: the design's name IS its hash."""
    return "agnt-" + sha256_hex(g)[:12]


def gene_vector(g: dict) -> set:
    """Canonical gene set for structural comparison (order-free)."""
    genes = {f"cell:{c['name']}:{c['question']}:lam={c['lam']:.2f}" for c in g["cells"]}
    for gt in g["gates"]:
        genes.add(
            f"gate:{gt['name']}:{gt['src']}>{gt['dst']}:{gt['kind']}:"
            f"th={gt['theta_base']:.2f}:R={gt['R']}:la={gt['lam_adapt']}:rho={gt['rho']}"
        )
    return genes


def gene_distance(a: dict, b: dict) -> int:
    """Structural uniqueness metric: symmetric difference of gene sets."""
    return len(gene_vector(a) ^ gene_vector(b))


# ---- runtime (Lane 1 cells + Lane 2 gates) ---------------------------------

class Cell:
    """Lane-1 cell: question + decayed pseudo-counts over an append-only
    raw tick ledger. lam is a READ-OUT POLICY: decay advances with TIME
    (Agent.step decays every cell each tick), so a cell that stops receiving
    input still forgets — frozen confidence is exactly the pathology this
    lane mutates against. Changing lam re-tallies the SAME ledger
    (rebuild_from_ledger) — the ledger is the truth."""

    def __init__(self, name, question, lam):
        self.name, self.question, self.lam = name, question, lam
        self.ups = 0.0
        self.downs = 0.0
        self.ticks = []  # append-only raw ledger: {"t", "v", "why"}

    def decay(self):
        """Time advances one tick: evidence ages even with no new input."""
        self.ups *= self.lam
        self.downs *= self.lam

    def tick(self, v: int, t: int, why: str):
        """A tick lands (no decay here — decay is time's job, done by Agent)."""
        assert v in (+1, -1)
        if v > 0:
            self.ups += 1.0
        else:
            self.downs += 1.0
        self.ticks.append({"t": t, "v": v, "why": why})

    def rebuild_from_ledger(self, lam: float):
        """Honest lam change: replay raw ticks under the new read-out policy,
        decaying once per elapsed tick (grouped by t)."""
        raw = self.ticks
        self.ups, self.downs, self.lam, self.ticks = 0.0, 0.0, lam, []
        rows_by_t = {}
        for r in raw:
            rows_by_t.setdefault(r["t"], []).append(r)
        for t in sorted(rows_by_t):
            self.decay()
            for r in rows_by_t[t]:
                self.tick(r["v"], r["t"], r["why"])

    @property
    def p(self) -> float:
        return (self.ups + 1.0) / (self.ups + self.downs + 2.0)

    def recent_p(self, k: int) -> float:
        tail = [r["v"] for r in self.ticks[-k:]]
        if not tail:
            return 0.5
        return (sum(1 for v in tail if v > 0) + 1) / (len(tail) + 2)


class Gate:
    """Lane-2 gate: threshold + refractory + theta adaptation."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.name = cfg["name"]
        self.theta = float(cfg["theta_base"])
        self.last_fire = -10**9
        self.fires = 0
        self.opportunities = 0

    def step(self, src_p: float, t: int, dst: Cell, events: list):
        """Evaluate on a snapshot p; fire at most one tick into dst."""
        self.theta -= self.cfg["rho"] * (self.theta - self.cfg["theta_base"])
        if t - self.last_fire <= self.cfg["R"]:
            return
        self.opportunities += 1
        emit = None
        if self.cfg["kind"] == "excite" and src_p >= self.theta:
            emit = +1
        elif self.cfg["kind"] == "inhibit" and src_p >= self.theta:
            emit = -1
        elif self.cfg["kind"] == "sign":
            if src_p >= self.theta:
                emit = +1
            elif src_p <= 1.0 - self.theta:
                emit = -1
        if emit is None:
            return
        self.fires += 1
        self.last_fire = t
        self.theta += self.cfg["lam_adapt"] * (1.0 - self.theta)
        dst.tick(emit, t, f"{self.name}:{self.cfg['kind']}")
        events.append({"t": t, "gate": self.name, "emit": emit})


class Agent:
    """A live agent: genome (design) + runtime state (earned from the world)."""

    def __init__(self, genome: dict):
        self.genome = genome
        self.cells = {c["name"]: Cell(c["name"], c["question"], c["lam"])
                      for c in genome["cells"]}
        self.gates = [Gate(dict(g)) for g in genome["gates"]]

    def clone_at(self, genome: dict) -> "Agent":
        """MicroMoth: spawn a candidate FROM the live state. Cells whose lam
        changed re-tally their own raw ledger under the new policy; gates
        inherit runtime theta/fires. The raw ledger is never rewritten."""
        child = Agent(genome)
        for name, live in self.cells.items():
            c = child.cells[name]
            c.ups, c.downs, c.ticks = live.ups, live.downs, list(live.ticks)
            if abs(c.lam - live.lam) > 1e-12:
                c.rebuild_from_ledger(c.lam)
        live_g = {g.name: g for g in self.gates}
        for g in child.gates:
            if g.name in live_g:
                g.theta = live_g[g.name].theta
                g.fires = live_g[g.name].fires
                g.last_fire = live_g[g.name].last_fire
                g.opportunities = live_g[g.name].opportunities
        return child

    def step(self, t: int, bias: int = None) -> list:
        events = []
        for c in self.cells.values():
            c.decay()                       # time advances for EVERY cell
        self.cells["C1"].tick(world_tick(t, bias), t, "world")
        snap = {n: c.p for n, c in self.cells.items()}  # synchronous snapshot
        for g in self.gates:
            g.step(snap[g.cfg["src"]], t, self.cells[g.cfg["dst"]], events)
        return events


def run_window(agent: Agent, t0: int, t1: int, bias: int = None) -> dict:
    """Run a window; return per-gate fire sets + mission score.

    Mission: every G3 +1 fire is a commit vote; it is GOOD in the good
    regime (t < T_FLIP) and BAD in the bad regime. score = good - bad.
    bias forces a counterfactual regime (probe lane: is a quiet child
    actually better, or just lobotomized?).
    """
    fires = {}
    good = bad = 0
    for t in range(t0, t1 + 1):
        for e in agent.step(t, bias):
            fires.setdefault(e["gate"], set()).add((e["t"], e["emit"]))
            if e["gate"] == "G3" and e["emit"] > 0:
                true_regime = (regime(t) if bias is None
                               else (1 if bias == GOOD_BIAS else -1))
                if true_regime > 0:
                    good += 1
                else:
                    bad += 1
    return {"fires": fires, "good": good, "bad": bad, "score": good - bad}


# ---- mid-process diagnostics (evidence; the mutation source — NO RNG) ------

def diagnostics(agent: Agent, t: int) -> dict:
    c1 = agent.cells["C1"]
    g1 = next(g for g in agent.gates if g.name == "G1")
    c3 = agent.cells["C3"]
    util = (g1.fires / g1.opportunities) if g1.opportunities else 0.0
    return {
        "t": t,
        "sense_overall_p": round(c1.p, 4),
        "sense_recent_p": round(c1.recent_p(RECENT_WINDOW), 4),
        "sense_drift": round(abs(c1.p - c1.recent_p(RECENT_WINDOW)), 4),
        "g1_fires": g1.fires,
        "g1_utilization": round(util, 4),
        "terminal_p": round(c3.p, 4),
    }


# ---- Q2: mutation operators (pure: genome x evidence -> genome' + delta) ---

def descendants(genome: dict, root: str) -> set:
    seen, frontier = {root}, [root]
    while frontier:
        cur = frontier.pop()
        for g in genome["gates"]:
            if g["src"] == cur and g["dst"] not in seen:
                seen.add(g["dst"])
                frontier.append(g["dst"])
    return seen


def op_forget_widening(g: dict, ev: dict):
    """Sense drift => the world changed. Forgetting is a read-out policy,
    so widen decay (lower lam) on the sense cell and every cell downstream
    — AND COUPLE it: gates reading forgetful cells get faster theta
    relaxation (rho up). Single-gene lam-only was falsified by the
    good-regime probe: habituated thresholds starve the memory and the
    child never commits again (lobotomized, not better)."""
    if ev["sense_drift"] < DRIFT_TRIGGER:
        return None
    targets = sorted(descendants(g, "C1"))
    g2 = json.loads(canon(g))
    delta = []
    for c in g2["cells"]:
        if c["name"] in targets and c["lam"] > FORGET_LAM:
            delta.append({"path": f"cells[{c['name']}].lam",
                          "from": c["lam"], "to": FORGET_LAM})
            c["lam"] = FORGET_LAM
    for gt in g2["gates"]:
        if gt["src"] in targets and gt["rho"] < FORGET_RHO:
            delta.append({"path": f"gates[{gt['name']}].rho",
                          "from": gt["rho"], "to": FORGET_RHO})
            gt["rho"] = FORGET_RHO
    if not delta:
        return None
    why = {"diagnostic": "sense-drift", "drift": ev["sense_drift"],
           "overall_p": ev["sense_overall_p"], "recent_p": ev["sense_recent_p"],
           "targets": targets, "coupled": "lam+rho"}
    return g2, delta, why


def op_habituate(g: dict, ev: dict):
    """G1 over-fires => raise its base threshold (Lane 2 habituation, made
    hereditable: the change lands in the genome, not just runtime theta)."""
    if ev["g1_fires"] < HABITUATE_MIN_FIRES or ev["g1_utilization"] < HABITUATE_MIN_UTIL:
        return None
    g2 = json.loads(canon(g))
    for gt in g2["gates"]:
        if gt["name"] == "G1":
            new = min(0.90, round(gt["theta_base"] + HABITUATE_STEP, 2))
            if new == gt["theta_base"]:
                return None
            delta = [{"path": "gates[G1].theta_base",
                      "from": gt["theta_base"], "to": new}]
            gt["theta_base"] = new
            why = {"diagnostic": "g1-overfire", "fires": ev["g1_fires"],
                   "utilization": ev["g1_utilization"]}
            return g2, delta, why
    return None


def op_sprout_feedback(g: dict, ev: dict):
    """Terminal cell confident => sprout a second negative-feedback edge
    terminal -> sense (Lane 2 showed feedback dampens; this makes the loop
    GROW). Hebbian co-fire sprouting is the M2 follow-up."""
    if ev["terminal_p"] < SPROUT_CONF:
        return None
    if any(gt["src"] == "C3" and gt["dst"] == "C1" for gt in g["gates"]):
        return None
    g2 = json.loads(canon(g))
    cfg = {"name": "G4-sprout", "src": "C3", "dst": "C1", "kind": "inhibit",
           "theta_base": SPROUT_THETA, "R": SPROUT_R,
           "lam_adapt": 0.06, "rho": 0.02}
    g2["gates"].append(cfg)
    delta = [{"path": "gates[]", "op": "+G4-sprout", "cfg": cfg}]
    why = {"diagnostic": "terminal-confident", "terminal_p": ev["terminal_p"]}
    return g2, delta, why


OPERATORS = [("forget-widening", op_forget_widening),
             ("habituate", op_habituate),
             ("sprout-feedback", op_sprout_feedback)]


# ---- Q3 layer 1: chained append-only mutation ledger -----------------------

def write_ledger(rows: list) -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    prev = "0" * 64
    with open(MUTATIONS, "w") as f:
        for r in rows:
            r["prev_row_sha"] = prev
            r["row_sha"] = sha256_hex([prev, {k: v for k, v in r.items()
                                              if k != "row_sha"}])
            f.write(canon(r) + "\n")
            prev = r["row_sha"]
    return prev  # chain head


def verify_ledger() -> str:
    prev = "0" * 64
    with open(MUTATIONS) as f:
        for line in f:
            r = json.loads(line)
            expect = sha256_hex([prev, {k: v for k, v in r.items()
                                        if k != "row_sha"}])
            assert r["prev_row_sha"] == prev, "chain break: prev mismatch"
            assert r["row_sha"] == expect, f"chain break at row {r['row']}"
            prev = r["row_sha"]
    return prev


# ---- Q3 layer 2: encode the winning child as zeroclaw-reflex-spec/v1 -------

def emit_spec(child: dict, parent_id: str, ev: dict, sims: dict,
              delta_path: str, context_sha: str) -> dict:
    content = canon(child)
    import hashlib
    out_sha = hashlib.sha256(content.encode()).hexdigest()
    return {
        "id": f"mut-{ev['t']}-{genome_id(child)[:16]}",
        "intent": ("swarm-m1 mid-process mutation: child agent genome "
                   "proposed as better for the next step"),
        "trigger": f"swarm:step:commit-mission:t>{ev['t']}",
        "context_sha256": context_sha,  # cache-integrity: valid ONLY for this state
        "model": "zeroclaw/agent-mutation/poc.py",
        "payload": {
            "delta_path": delta_path,
            "output_sha256": out_sha,
            "content": content,
            "bytes": len(content.encode()),
        },
        "cites": [
            f"evidence:{ev['sense_drift']}:drift(C1)",
            f"sim:parent:{sims['parent']['score']}:child:{sims['child']['score']}",
            "circuit:lane2:excite-inhibit-sign",
        ],
        "provenance": {"compiledBy": "zeroclaw", "parentOrder": parent_id},
    }


def py_parse_spec_check(spec: dict):
    """Mirror of pincher parseZeroclawSpec's validation rules (the real TS
    parser is run separately as the cross-repo receipt)."""
    for k in ("id", "intent", "trigger", "context_sha256", "model",
              "payload", "cites", "provenance"):
        assert k in spec, f"spec missing field {k}"
    assert spec["provenance"]["compiledBy"] == "zeroclaw"
    assert len(spec["payload"]["output_sha256"]) == 64
    assert spec["payload"]["bytes"] == len(spec["payload"]["content"].encode())


# ---- the run ---------------------------------------------------------------

def main() -> int:
    print("=" * 74)
    print("ZEROCLAW agent-mutation POC — Swarm M1  (deterministic, no RNG)")
    print(f"mission: {MISSION}")
    print("=" * 74)

    # 1. Live parent run, mid-process.
    parent = Agent(genome_v0())
    for t in range(1, T_MID + 1):
        parent.step(t)
    parent_id = genome_id(parent.genome)
    print(f"\n[1] parent ran live t=1..{T_MID}; genome {parent_id}")
    print("    cells: " + "  ".join(
        f"{n}.p={c.p:.3f}(n={len(c.ticks)})" for n, c in parent.cells.items()))
    print("    gates: " + "  ".join(
        f"{g.name}:{g.fires}f/th={g.theta:.3f}" for g in parent.gates))

    # 2. Mid-process diagnostics — the evidence that triggers mutation.
    ev = diagnostics(parent, T_MID)
    print(f"\n[2] diagnostics @t={T_MID}: {canon(ev)}")
    assert ev["sense_drift"] >= DRIFT_TRIGGER, \
        "world flip did not register as drift — constants drifted, re-tune"

    # 3. Generate candidate designs (each from evidence, not dice).
    context_sha = sha256_hex({
        "t": T_MID,
        "cells": {n: {"ups": c.ups, "downs": c.downs, "n": len(c.ticks)}
                  for n, c in parent.cells.items()},
        "gates": {g.name: {"theta": g.theta, "fires": g.fires}
                  for g in parent.gates},
    })
    candidates = []
    for op_name, fn in OPERATORS:
        out = fn(parent.genome, ev)
        if out is None:
            print(f"    (operator {op_name}: not triggered — honest no-op)")
            continue
        g2, delta, why = out
        candidates.append({"operator": op_name, "genome": g2,
                           "delta": delta, "why": why})
        print(f"    candidate {op_name}: {len(delta)} gene change(s)")
    assert candidates, "FAIL: no operator triggered — no mutation generated"

    # 4. MicroMoth: simulate every candidate on the SAME deterministic
    #    future stream, cloned from the live state. Play before execution.
    base = run_window(parent.clone_at(parent.genome), T_MID + 1, T_END)
    print(f"\n[4] MicroMoth sim window t={T_MID + 1}..{T_END} (bad regime)")
    print(f"    parent baseline: good={base['good']} bad={base['bad']} "
          f"score={base['score']}")
    for cand in candidates:
        sim = run_window(parent.clone_at(cand["genome"]), T_MID + 1, T_END)
        cand["sim"] = sim
        cand["jaccard_g3"] = 1.0 - (len(sim["fires"].get("G3", set())
                                         & base["fires"].get("G3", set())) /
                                    max(1, len(sim["fires"].get("G3", set())
                                               | base["fires"].get("G3", set()))))
        print(f"    {cand['operator']:<16} good={sim['good']} "
              f"bad={sim['bad']} score={sim['score']} "
              f"G3-fire-Jaccard-dist={cand['jaccard_g3']:.3f}")

    # 5. Selection by simulation (JEV's dice come in M2; this is the preview).
    #    Rank: score desc, then canonical genome asc (full determinism).
    ranked = sorted(candidates,
                    key=lambda c: (-c["sim"]["score"], canon(c["genome"])))
    winner = ranked[0]
    print(f"\n[5] selected: {winner['operator']} -> child "
          f"{genome_id(winner['genome'])}")
    assert winner["sim"]["score"] > base["score"], \
        "FAIL: no candidate beat the parent — mutation not justified"
    assert winner["sim"]["bad"] < base["bad"], \
        "FAIL: winner did not reduce wrong commits"

    # 5b. Counterfactual probe (falsification lane): a quiet child must not
    #     be a dead child. In a forced GOOD regime the winner must still
    #     commit — and the frozen parent must over-commit there too is NOT
    #     required; only aliveness is asserted.
    probe_w = run_window(parent.clone_at(winner["genome"]),
                         T_MID + 1, T_MID + 40, bias=GOOD_BIAS)
    probe_p = run_window(parent.clone_at(parent.genome),
                         T_MID + 1, T_MID + 40, bias=GOOD_BIAS)
    print(f"\n[5b] counterfactual good-regime probe (t={T_MID + 1}..{T_MID + 40}):")
    print(f"     parent: good={probe_p['good']} bad={probe_p['bad']} "
          f"| winner: good={probe_w['good']} bad={probe_w['bad']}")
    assert probe_w["good"] >= 1, \
        "FAIL: winner never commits in a good regime — lobotomized, not better"

    # 6. Uniqueness, measurably: structural AND behavioral.
    child = winner["genome"]
    child_id = genome_id(child)
    d_parent = gene_distance(parent.genome, child)
    assert d_parent >= 1, "FAIL: child structurally identical to parent"
    assert child_id != parent_id, "FAIL: child hash equals parent"
    assert winner["jaccard_g3"] > 0.0, "FAIL: child behaves identically (G3)"
    print(f"[6] uniqueness vs parent: gene-distance={d_parent} "
          f"(sha {parent_id[:16]}.. != {child_id[:16]}..), "
          f"behavior G3-Jaccard-dist={winner['jaccard_g3']:.3f}, "
          f"score {base['score']} -> {winner['sim']['score']}")
    for other in ranked[1:]:
        assert gene_distance(child, other["genome"]) >= 1, \
            "FAIL: sibling candidates not mutually unique"

    # 7. Ledger layer 1: chain every candidate — selected AND stamped losers
    #    (doubt stamped, not lowered: losers compress to documentation).
    rows = []
    for i, cand in enumerate(ranked):
        sel = cand is winner
        rows.append({
            "row": i + 1,
            "t": T_MID,
            "operator": cand["operator"],
            "parent": parent_id,
            "child": genome_id(cand["genome"]),
            "why": cand["why"],
            "delta": cand["delta"],
            "sim": {"good": cand["sim"]["good"], "bad": cand["sim"]["bad"],
                    "score": cand["sim"]["score"],
                    "parent_score": base["score"]},
            "selected": sel,
            "why_not": None if sel else
            "score did not beat parent enough / lost ranking; compressed to "
            "documentation (doubt stamped, not lowered)",
        })
    head = write_ledger(rows)
    assert verify_ledger() == head, "FAIL: mutation ledger chain broke"
    print(f"[7] mutation ledger: {len(rows)} rows chained, head {head[:16]}.., "
          f"replay-verified ({sum(1 for r in rows if not r['selected'])} "
          f"losers stamped)")

    # 8. Ledger layer 2: the child as zeroclaw-reflex-spec/v1 (pincher's food).
    SPECS.mkdir(parents=True, exist_ok=True)
    spec = emit_spec(child, parent_id, ev,
                     {"parent": base, "child": winner["sim"]},
                     delta_path=f"agent-mutation/out/mutations.jsonl#row"
                                f"{rows[[r['selected'] for r in rows].index(True) + 1]['row']}",
                     context_sha=context_sha)
    py_parse_spec_check(spec)
    spec_path = SPECS / f"{spec['id']}.json"
    spec_path.write_text(canon(spec) + "\n")
    print(f"[8] reflex-spec/v1: {spec_path.name} "
          f"(payload_sha={spec['payload']['output_sha256'][:16]}.., "
          f"py-parse OK — run pincher parseZeroclawSpec for the cross receipt)")

    receipt = sha256_hex({
        "t_mid": T_MID, "parent": parent_id, "child": child_id,
        "operator": winner["operator"], "parent_score": base["score"],
        "child_score": winner["sim"]["score"], "ledger_head": head,
        "spec_sha256": spec["payload"]["output_sha256"],
    })
    print("\n" + "=" * 74)
    print(f"RECEIPT {receipt}")
    print(f"ALL INVARIANTS HELD — mutation generated, simulated, selected,")
    print(f"recorded (chained ledger + reflex-spec/v1). Exit 0.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
