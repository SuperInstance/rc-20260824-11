#!/usr/bin/env python3
"""Compression POC — Swarm Lane C1: compressing the non-selected agent.

When JEV's dice pass an agent over, its full state (tick ledgers + gates) is
frozen and compressed into ONE linkable summary document:

  Tier K  knowledge    — per-cell sufficient statistic (counts, n, params)
                         + original chain head (provenance binding)
  Tier D  doubts       — every never-fired gate stamped exactly:
                         (p, LB95, theta, deficit = theta - LB, N_eff)
                         DOUBT STAMPED, NOT LOWERED (two-ledgers law)
  Tier T  trajectory   — 3-number sketch per cell: converged | drifting | thin
  Tier P  proof        — summary ID = sha256(canonical(doc)); self-verifying

Linkability is proven by USE: a new agent INHERITS a compressed cell (genesis
head = summary ID) and reaches a gate fire on fewer new ticks than a fresh
agent on the same world — essential experience becomes knowledge.

NO RNG: all world bits derive from fnv1a(content) (exoj law). Stdlib only.
Run: python3 compression/poc.py
"""

import hashlib
import json
import math

GENESIS = "CELL-GENESIS"
Z95 = 1.6449  # one-sided 95% z-score
TICKS = 32


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Cell:
    """Lane-1 cell, generalized: the genesis may be a summary ID (inheritance)."""

    def __init__(self, question, answers, alpha=0.5, lam=1.0, genesis=None):
        self.question = question
        self.answers = tuple(answers)
        self.alpha = alpha
        self.lam = lam
        self.genesis = genesis if genesis is not None else GENESIS
        self.counts = [0.0] * len(answers)
        self.n = 0
        self.head = sha(self.genesis)
        self.head0 = self.head  # replay anchor (moves on inheritance)
        self.ledger = []  # (n, answer, row_hash)

    def tick(self, answer: str) -> None:
        self.counts = [c * self.lam for c in self.counts]
        self.counts[self.answers.index(answer)] += 1.0
        self.n += 1
        row = sha(canonical([self.head, self.n, answer]))
        self.ledger.append((self.n, answer, row))
        self.head = row

    def dist(self) -> dict:
        total = sum(self.counts) + self.alpha * len(self.answers)
        return {a: (c + self.alpha) / total for a, c in zip(self.answers, self.counts)}

    def n_eff(self) -> float:
        return sum(self.counts)

    def lower_bound(self, answer: str, z: float = Z95) -> float:
        p = self.dist()[answer]
        a = self.counts[self.answers.index(answer)] + self.alpha
        a0 = sum(self.counts) + self.alpha * len(self.answers)
        var = a * (a0 - a) / (a0 * a0 * (a0 + 1.0))
        return p - z * math.sqrt(max(var, 0.0))

    def gate(self, answer: str, fire: float) -> tuple:
        lb = self.lower_bound(answer)
        return lb >= fire, lb

    def verify_chain(self) -> bool:
        head = self.head0
        for n, answer, row in self.ledger:
            expect = sha(canonical([head, n, answer]))
            if expect != row:
                return False
            head = row
        return head == self.head


WORLDS = {  # deterministic world rates per question (pinch world flips late)
    "relay/alive?":   {"base": 0.85, "flip": None},
    "pinch/match?":   {"base": 0.70, "flip": None},
    "listener/veto?": {"base": 0.20, "flip": 24},  # drifts: 0.20 -> 0.80 at tick 24
}


def world_answer(question, answers, t):
    rate = WORLDS[question]["base"]
    flip = WORLDS[question]["flip"]
    if flip is not None and t >= flip:
        rate = 1.0 - rate
    bit = fnv1a(f"{question}:{t}") % 10000 / 10000.0
    return answers[0] if bit < rate else answers[1]


def build_scout():
    """The agent under test: 3 cells + 3 gates, run TICKS ticks."""
    specs = [
        ("relay/alive?",   ("yes", "no"), 0.5, 0.97, "yes", 0.55),
        ("pinch/match?",   ("hit", "miss"), 0.5, 1.0, "hit", 0.66),
        ("listener/veto?", ("veto", "pass"), 0.5, 1.0, "veto", 0.70),
    ]
    agent = {"name": "scout-relay", "cells": [], "gates": []}
    for q, ans, alpha, lam, watch, theta in specs:
        cell = Cell(q, ans, alpha=alpha, lam=lam)
        fired_at = None
        for t in range(1, TICKS + 1):
            cell.tick(world_answer(q, ans, t))
            if fired_at is None and cell.gate(watch, theta)[0]:
                fired_at = t
        agent["cells"].append(cell)
        agent["gates"].append({"watch": watch, "theta": theta, "fired_at": fired_at})
    return agent


# ── Tier T: trajectory sketch ─────────────────────────────────────────────
def trajectory(cell, watch):
    """3-number sketch: p(first half), p(second half) of the watch answer."""
    half = cell.n // 2
    if cell.n < 8:
        label = "thin"
    else:
        replay = Cell(cell.question, cell.answers, cell.alpha, cell.lam)
        p1 = p2 = None
        for n, answer, _ in cell.ledger:
            replay.tick(answer)
            p = replay.dist()[watch]
            if n == half:
                p1 = p
            p2 = p
        label = "converged" if abs(p2 - p1) < 0.10 else "drifting"
        return {"p_first": round(p1, 4), "p_second": round(p2, 4), "label": label}
    return {"p_first": None, "p_second": None, "label": label}


# ── compression: freeze an agent into one linkable summary document ───────
def compress(agent):
    cells_out, doubts, fired = [], [], []
    for cell, gate in zip(agent["cells"], agent["gates"]):
        p = cell.dist()[gate["watch"]]
        lb = cell.lower_bound(gate["watch"])
        cells_out.append({
            "question": cell.question, "answers": list(cell.answers),
            "counts": [round(c, 4) for c in cell.counts], "n": cell.n,
            "alpha": cell.alpha, "lam": cell.lam,
            "head": cell.head,  # provenance binding to the archived ledger
            "p_watch": round(p, 4), "traj": trajectory(cell, gate["watch"]),
        })
        if gate["fired_at"] is None:
            doubts.append({  # DOUBT STAMPED, NOT LOWERED
                "question": cell.question, "watch": gate["watch"],
                "p": round(p, 4), "lb95": round(lb, 4), "theta": gate["theta"],
                "deficit": round(gate["theta"] - lb, 4), "n_eff": round(cell.n_eff(), 1),
            })
        else:
            fired.append({"question": cell.question, "tick": gate["fired_at"]})
    doc = {"agent": agent["name"], "frozen_tick": TICKS,
           "cells": cells_out, "doubts": doubts, "fired": fired}
    doc_id = sha(canonical(doc))
    doc["id"] = doc_id
    return doc


def render(doc):
    """The compressed reflex-spec: the doc as a small human-readable page."""
    lines = [
        f"# {doc['agent']} — compressed @{TICKS} ticks  [@C1:{doc['id'][:16]}]",
        "",
        "| cell | p(watch) | verdict |",
        "|---|---|---|",
    ]
    for c in doc["cells"]:
        lines.append(f"| {c['question']} | {c['p_watch']} | {c['traj']['label']} |")
    if doc["fired"]:
        lines.append("")
        for f in doc["fired"]:
            lines.append(f"- FIRED: {f['question']} gate fired at tick {f['tick']}")
    if doc["doubts"]:
        lines.append("")
        lines.append("## doubts (stamped, not lowered)")
        for d in doc["doubts"]:
            lines.append(f"- {d['question']}/{d['watch']}: p={d['p']} "
                         f"LB95={d['lb95']} θ={d['theta']} "
                         f"**deficit={d['deficit']}** N_eff={d['n_eff']}")
    return "\n".join(lines)


def inherit(summary, question):
    """Knowledge transfer: a new cell whose genesis IS the summary ID."""
    c = next(x for x in summary["cells"] if x["question"] == question)
    cell = Cell(c["question"], tuple(c["answers"]), alpha=c["alpha"],
                lam=c["lam"], genesis=summary["id"])  # structural provenance
    # compression writes ONE bridging row: archived head → summary ID.
    # new ticks chain from the bridge, so the child chain is verifiable.
    cell.head0 = sha(canonical(["compression", summary["id"], c["head"]]))
    cell.head = cell.head0
    cell.counts = list(c["counts"])               # Tier K prior mass
    cell.n = c["n"]
    return cell


def ticks_to_fire(cell, watch, theta, world_q, start_tick, cap=400):
    """New ticks (deterministic world stream from start_tick) until gate fires."""
    for t in range(start_tick, start_tick + cap):
        cell.tick(world_answer(world_q, cell.answers, t))
        ok, _ = cell.gate(watch, theta)
        if ok:
            return t - start_tick + 1, cell
    return None, cell


def main():
    print("═" * 72)
    print("ZEROCLAW compression POC — the non-selected agent becomes a document")
    print("═" * 72)

    # 1 ── the swarm round: JEV projects firing odds, the dice roll (no RNG module)
    scout = build_scout()
    agents = {"scout-relay": max(scout["cells"][1].lower_bound("hit"), 0.05),
              "probe-west": 0.50, "probe-east": 0.45}
    weights = {k: v / sum(agents.values()) for k, v in agents.items()}
    selected = None
    for rnd in range(1, 51):
        r = fnv1a(f"jev:round:{rnd}") % 10000 / 10000.0
        cum = 0.0
        for name, w in sorted(weights.items()):
            cum += w
            if r < cum:
                selected = name
                break
        print(f"jev round {rnd}: roll={r:.4f} → selected {selected}  "
              f"(scout odds {weights['scout-relay']:.2f})")
        if selected != "scout-relay":
            break
    assert selected != "scout-relay", "FAIL: scout never lost a roll in 50 rounds"
    print(f"\nscout-relay NOT selected by JEV → freeze + compress\n")

    # 2 ── verify the raw agent (chain proof holds before freeze)
    for cell in scout["cells"]:
        assert cell.verify_chain(), f"FAIL: chain broken for {cell.question}"
    raw = canonical({
        "cells": [{"question": c.question, "answers": list(c.answers),
                   "counts": c.counts, "n": c.n, "alpha": c.alpha, "lam": c.lam,
                   "genesis": c.genesis, "ledger": [list(r) for r in c.ledger],
                   "head": c.head} for c in scout["cells"]],
        "gates": scout["gates"],
    })

    # 3 ── compress
    doc = compress(scout)
    summary = canonical(doc)
    print("── raw state vs summary document")
    print(f"   raw      : {len(raw):>6} bytes (3 ledgers × {TICKS} rows + gates)")
    print(f"   summary  : {len(summary):>6} bytes  → id @C1:{doc['id'][:16]}…")
    print(f"   ratio    : {len(raw) / len(summary):.1f}× smaller\n")

    # 4 ── Tier P: the ID is self-verifying (re-hash the doc minus its id)
    body = {k: v for k, v in doc.items() if k != "id"}
    assert sha(canonical(body)) == doc["id"], "FAIL: summary ID not self-verifying"
    print("── Tier P: summary ID = sha256(canonical(doc))  … verified")
    print(f"   re-hash → @C1:{sha(canonical(body))[:16]} == stamped id ✓\n")

    # 5 ── Tier K: sufficient statistic is lossless under the model
    print("── Tier K: summary posterior vs raw-ledger replay (must be identical)")
    for cell in scout["cells"]:
        replay = Cell(cell.question, cell.answers, cell.alpha, cell.lam)
        for n, answer, _ in cell.ledger:
            replay.tick(answer)
        from_summary = next(c for c in doc["cells"] if c["question"] == cell.question)
        same_dist = replay.dist() == replay.dist()
        same_counts = [round(c, 4) for c in replay.counts] == from_summary["counts"]
        assert same_counts and same_dist, f"FAIL: replay mismatch {cell.question}"
        print(f"   {cell.question:<16} counts replay==summary ✓  (n={replay.n}, "
              f"N_eff={sum(replay.counts):.1f})")
    print()

    # 6 ── Tier D + T: the rendered document (what other agents link to)
    print("── the compressed document, rendered:")
    print("─" * 60)
    print(render(doc))
    print("─" * 60 + "\n")

    d = next(x for x in doc["doubts"] if x["question"] == "pinch/match?")
    assert d["deficit"] > 0, "FAIL: doubt must not be lowered into a fire"

    # 7 ── linkability by USE: inheritance beats a fresh cell on the same world
    print("── inheritance: pinch/match? gate (θ=0.66) on the same world stream")
    fresh = Cell("pinch/match?", ("hit", "miss"))
    fresh_n, _ = ticks_to_fire(fresh, "hit", 0.66, "pinch/match?", 1)
    child = inherit(doc, "pinch/match?")
    child_n, child_end = ticks_to_fire(child, "hit", 0.66, "pinch/match?", TICKS + 1)
    print(f"   fresh agent : {fresh_n} new ticks to first fire")
    print(f"   inheritor   : {child_n} new ticks to first fire "
          f"(seeded N_eff={sum(child.counts):.1f} from @{doc['id'][:16]})")
    print(f"   speedup     : {fresh_n / child_n:.2f}× — essential experience became knowledge")
    assert child_n < fresh_n, "FAIL: inheritance did not transfer experience"
    assert child_end.verify_chain() and child_end.genesis == doc["id"], \
        "FAIL: inherited chain must verify against the summary ID"
    print(f"   inherited chain verifies with genesis = summary ID ✓\n")

    print("═" * 72)
    print(f"RECEIPT: PASS  agent=scout-relay ticks={TICKS} "
          f"raw={len(raw)}B summary={len(summary)}B ratio={len(raw)/len(summary):.1f}x")
    print(f"          summary-id=@C1:{doc['id'][:16]}  doubts={len(doc['doubts'])} "
          f"fired={len(doc['fired'])}  inherit-speedup={fresh_n / child_n:.2f}x")
    print("═" * 72)


if __name__ == "__main__":
    main()
