#!/usr/bin/env python3
# TICKBOARD v0.1 — product-surface POC for the ZeroClaw cells-as-ticks paradigm.
#
# What this is: the thinnest product surface for "cells as probabilities
# recorded as ticks over time, gates firing pipelines, thresholds tightening
# into reflexes." A terminal decision-support board where:
#   - a CELL is a question whose answer is a probability computed from an
#     append-only tick ledger (evidence rows) — never sampled, never RNG;
#   - a GATE fires a PIPELINE (real side effect) when the cell's probability
#     crosses a threshold BY ENOUGH MARGIN;
#   - the margin required SHRINKS as the cell accumulates ticks — early
#     fires need overwhelming evidence (SLOW), reflexed cells fire fast
#     (FAST). Muscle memory, in one function.
#   - every event is sha256-chained into a ledger file (exoj lineage:
#     canonical JSON + chained prev-hash). The ledger IS the proof object.
#
# Runs on system python3, stdlib only, zero RNG (jitter is fnv1a-derived).
# Usage: python3 demo.py            # selftest + night-shift replay
#        python3 demo.py --quiet    # suppress board frames

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
os.makedirs(OUT, exist_ok=True)

# ---------------- no-RNG law ----------------

def fnv1a(s):
    """fnv-1a 32-bit — the deterministic entropy substitute (exoj unitTable lineage)."""
    h = 0x811C9DC5
    for ch in s.encode():
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h

def jitter(name, lo, hi):
    """Deterministic 'noise' in [lo, hi) derived from content, never sampled."""
    return lo + (hi - lo) * (fnv1a(name) / 2**32)

# ---------------- sha-chained ledger (exoj lineage) ----------------

def cjson(v):
    """Canonical JSON: sorted keys, compact — same law as exoj core.mjs."""
    if isinstance(v, dict):
        return "{" + ",".join(json.dumps(k) + ":" + cjson(v[k]) for k in sorted(v)) + "}"
    if isinstance(v, list):
        return "[" + ",".join(cjson(x) for x in v) + "]"
    return json.dumps(v, separators=(",", ":"))

def sha256_hex(s):
    return hashlib.sha256(s.encode()).hexdigest()

class Ledger:
    """Append-only event log; each row chained to the previous row's hash."""

    def __init__(self, path, genesis="TICKBOARD-GENESIS"):
        self.path = path
        self.prev = genesis
        self.rows = []
        # start clean each demo run (deterministic receipt, not an accident)
        with open(path, "w") as f:
            pass

    def append(self, row):
        row = dict(row)
        row["seq"] = len(self.rows)
        h = sha256_hex(cjson([self.prev, row]))
        row["hash"] = h
        self.rows.append(row)
        self.prev = h
        with open(self.path, "a") as f:
            f.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        return h

    def verify(self):
        prev = "TICKBOARD-GENESIS"
        for i, row in enumerate(self.rows):
            body = {k: v for k, v in row.items() if k != "hash"}
            if row["seq"] != i:
                return False, f"seq gap at row {i}"
            if sha256_hex(cjson([prev, body])) != row["hash"]:
                return False, f"chain break at row {i}"
            prev = row["hash"]
        return True, f"chain intact ({len(self.rows)} rows, head {self.prev[:12]})"

# ---------------- the paradigm core ----------------

class Cell:
    """A question whose answer is a probability computed from ticks.

    p(t) = recency-weighted mean of tick values (decay^age). One bad tick
    barely moves a well-evidenced cell; sustained evidence moves it fast.
    vol = mean |Δ| of recent ticks — the probability DECOMPOSES into
    (level, volatility): what it says, and how much it's still churning.
    """

    def __init__(self, cid, question, decay=0.80):
        self.id = cid
        self.question = question
        self.decay = decay
        self.ticks = []  # each: {"t":int,"source":str,"value":float,"note":str}

    def tick(self, t, source, value, note=""):
        self.ticks.append({"t": t, "source": source, "value": round(value, 4), "note": note})

    @property
    def n(self):
        return len(self.ticks)

    def p(self):
        if not self.ticks:
            return 0.5
        num = den = 0.0
        for age, tk in enumerate(reversed(self.ticks)):
            w = self.decay ** age
            num += w * tk["value"]
            den += w
        return num / den

    def vol(self, k=6):
        recent = [tk["value"] for tk in self.ticks[-k:]]
        if len(recent) < 2:
            return 0.0
        return sum(abs(a - b) for a, b in zip(recent, recent[1:])) / (len(recent) - 1)

    def spark(self, width=14):
        blocks = "▁▂▃▄▅▆▇█"
        vals = [tk["value"] for tk in self.ticks[-width:]]
        if not vals:
            return ""
        return "".join(blocks[min(7, int(v * 8))] for v in vals)


class Gate:
    """Fires a pipeline when p crosses `threshold` with enough margin.

    margin_required(n) = base * k/(k+n)  — TIGHTENS with evidence.
      n=0   -> base      (a newborn cell must be overwhelming to act)
      n>>k  -> ~base*k/n (a reflexed cell acts on thin new evidence)
    tier: margin_required <= 0.10 -> FAST, <= 0.25 -> MEDIUM, else SLOW.
    Hysteresis (the veto analog): after firing, the gate stays OPEN until p
    recovers past the threshold, then re-arms. No flap-paging.
    """

    def __init__(self, cell_id, direction, threshold, action,
                 base_margin=0.45, reflex_k=8.0, min_margin=0.05):
        self.cell_id = cell_id
        self.direction = direction  # 'below' | 'above'
        self.threshold = threshold
        self.action = action
        self.base_margin = base_margin
        self.reflex_k = reflex_k
        self.min_margin = min_margin
        self.state = "ARMED"  # ARMED -> FIRED -> (recover) -> ARMED
        self.fires = []       # (t, tier, margin_required, p)

    def margin_required(self, n):
        return max(self.min_margin, self.base_margin * self.reflex_k / (self.reflex_k + n))

    def evaluate(self, t, cell):
        p, n = cell.p(), cell.n
        m = self.margin_required(n)
        crossed = (p <= self.threshold - m) if self.direction == "below" \
            else (p >= self.threshold + m)
        if self.state == "FIRED":
            recovered = (p >= self.threshold) if self.direction == "below" \
                else (p <= self.threshold)
            if recovered:
                self.state = "ARMED"
            return None
        if self.state == "ARMED" and crossed:
            tier = "FAST" if m <= 0.10 else ("MEDIUM" if m <= 0.25 else "SLOW")
            self.state = "FIRED"
            self.fires.append((t, tier, round(m, 3), round(p, 3)))
            return {"t": t, "tier": tier, "margin": round(m, 3), "p": round(p, 3)}
        return None


class Pipeline:
    """What a gate firing DOES. In the POC: real, safe side effects on disk."""

    def __init__(self, name, outdir):
        self.name = name
        self.log = os.path.join(outdir, "runbook.log")

    def fire(self, t, gate, detail):
        line = (f"[t+{t:02d}m] PIPELINE {self.name} fired by gate "
                f"{gate.cell_id}.{gate.direction}({gate.threshold}) "
                f"tier={detail['tier']} p={detail['p']} margin_req={detail['margin']}\n")
        with open(self.log, "a") as f:
            f.write(line)
        return line.strip()


class Board:
    def __init__(self, ledger):
        self.cells = {}
        self.gates = []
        self.pipelines = {}
        self.ledger = ledger
        self.fire_log = []

    def cell(self, cid, question, **kw):
        self.cells[cid] = Cell(cid, question, **kw)
        self.ledger.append({"kind": "declare", "cell": cid, "question": question})

    def gate(self, gate, pipeline_name, pipeline):
        self.gates.append(gate)
        self.pipelines[gate.action] = pipeline
        self.ledger.append({"kind": "gate", "cell": gate.cell_id, "direction": gate.direction,
                            "threshold": gate.threshold, "action": pipeline_name,
                            "base_margin": gate.base_margin, "reflex_k": gate.reflex_k})

    def observe(self, cid, t, source, value, note=""):
        cell = self.cells[cid]
        v = round(value, 4)
        cell.tick(t, source, v, note)
        self.ledger.append({"kind": "tick", "cell": cid, "t": t, "source": source, "value": v})
        for g in self.gates:
            if g.cell_id != cid:
                continue
            detail = g.evaluate(t, cell)
            if detail:
                line = self.pipelines[g.action].fire(t, g, detail)
                self.fire_log.append(line)
                self.ledger.append({"kind": "fire", "cell": cid, "t": t, "action": g.action,
                                    "tier": detail["tier"], "p": detail["p"],
                                    "margin_required": detail["margin"],
                                    "ticks_seen": cell.n})

    def render(self, t):
        L = ["─" * 74,
             f"TICKBOARD · night-shift replay · t+{t:02d}m   ledger head {self.ledger.prev[:12]}"]
        L.append(f"  {'cell':<20}{'p(t)':>6}  {'ticks(old→new)':<16}{'vol':>5}  gate")
        for cid, c in self.cells.items():
            gs = [g for g in self.gates if g.cell_id == cid]
            gtxt = "; ".join(
                f"{g.direction} {g.threshold:.2f} → {g.action}"
                + ("" if not g.fires else " " + " ".join(f"FIRED@t{f[0]}:{f[1]}" for f in g.fires))
                for g in gs
            ) or "—"
            L.append(f"  {cid:<20}{c.p():>6.2f}  {c.spark():<16}{c.vol():>5.2f}  {gtxt}")
        if self.fire_log:
            L.append("  gate log:")
            for fl in self.fire_log[-4:]:
                L.append("   " + fl)
        return "\n".join(L)

# ---------------- deterministic night-shift scenario ----------------
# Sim time: minutes. Four questions an operator (or a supervisor agent)
# actually holds during a night shift over a build lane.

def scenario_value(cell_id, t):
    j = jitter(f"{cell_id}#{t}", -0.03, 0.03)  # deterministic jitter, no RNG

    if cell_id == "relay.healthy":
        if t in (8,):                 # single-tick blip on a young cell
            return 0.44
        if 9 <= t <= 13:
            return 0.90 + j
        if 14 <= t <= 26:             # sustained degradation
            return max(0.05, 0.92 - 0.075 * (t - 13)) + j
        if 27 <= t <= 31:             # recovery
            return min(0.95, 0.55 + 0.10 * (t - 26)) + j
        if 32 <= t <= 35:             # rapid re-degradation on a reflexed cell
            return max(0.05, 0.50 - 0.15 * (t - 31)) + j
        return 0.95 + j

    if cell_id == "tests.green":
        return 0.96 + j               # green all night

    if cell_id == "ledger.reachable":  # flappy — must NOT page (hysteresis)
        return (0.85 + j) if fnv1a(f"flap#{t}") % 2 == 0 else (0.25 + j)

    if cell_id == "agent.drift":      # slow drift upward
        return min(0.95, 0.12 + 0.025 * t) + j

    raise KeyError(cell_id)


SOURCES = {
    "relay.healthy": "http-check",
    "tests.green": "ci-run",
    "ledger.reachable": "ping",
    "agent.drift": "verdict-scan",
}

def run_night_shift(quiet=False):
    ledger = Ledger(os.path.join(OUT, "night-shift.ledger.jsonl"))
    board = Board(ledger)

    # The operator declares questions (cells) and intents (gates + pipelines).
    board.cell("relay.healthy", "is the workers relay serving 2xx?")
    board.cell("tests.green", "is the lane's test suite green?")
    board.cell("ledger.reachable", "is the i2i ledger reachable?")
    board.cell("agent.drift", "is the builder agent behaving (not drifting)?")

    board.gate(Gate("relay.healthy", "below", 0.50, "page"),
               "page-runbook", Pipeline("page-runbook", OUT))
    board.gate(Gate("tests.green", "below", 0.70, "page"),
               "page-runbook", Pipeline("page-runbook", OUT))
    board.gate(Gate("ledger.reachable", "below", 0.30, "note"),
               "note-only", Pipeline("note-only", OUT))
    board.gate(Gate("agent.drift", "above", 0.60, "snapshot"),
               "snapshot-review", Pipeline("snapshot-review", OUT))

    frames_every = 6
    print("TICKBOARD v0.1 — night-shift replay (36 min of evidence, deterministic)")
    print("cells declared: 4   gates armed: 4   pipelines: page-runbook, note-only, snapshot-review")
    print()
    for t in range(0, 36):
        for cid in board.cells:
            board.observe(cid, t, SOURCES[cid], scenario_value(cid, t))
        if not quiet and (t + 1) % frames_every == 0:
            print(board.render(t))
            print()
    if quiet:
        print(board.render(35))
        print()

    ok, msg = ledger.verify()
    print(f"ledger verify: {'OK' if ok else 'FAIL'} — {msg}")
    print(f"ledger file:   {ledger.path} ({os.path.getsize(ledger.path)} bytes)")
    print(f"runbook side effects:")
    for line in board.fire_log:
        print("  " + line)
    return board, ledger, ok


# ---------------- selftest ----------------

def selftest():
    # canonical JSON is deterministic
    assert cjson({"b": 1, "a": [2, {"z": 0.5}]}) == '{"a":[2,{"z":0.5}],"b":1}'
    # fnv1a is stable and content-derived
    assert fnv1a("mass:relay") == fnv1a("mass:relay") != fnv1a("mass:tests")
    # margin tightens monotonically with evidence, floors at min_margin
    g = Gate("x", "below", 0.5, "a", base_margin=0.45, reflex_k=8.0, min_margin=0.05)
    ms = [g.margin_required(n) for n in range(0, 100, 5)]
    assert all(a >= b for a, b in zip(ms, ms[1:])) and ms[-1] == 0.05
    # ledger chain detects tampering
    led = Ledger(os.path.join(OUT, "selftest.ledger.jsonl"))
    led.append({"kind": "tick", "cell": "x", "value": 0.5})
    led.rows[0]["value"] = 0.9  # tamper
    ok, _ = led.verify()
    assert not ok
    # a single blip barely moves a well-evidenced cell; sustained evidence does
    c = Cell("c", "q", decay=0.80)
    for i in range(12):
        c.tick(i, "s", 0.95)
    c.tick(12, "s", 0.30)
    assert c.p() > 0.70, c.p()
    for i, v in enumerate([0.5, 0.3, 0.15, 0.05, 0.05, 0.05, 0.05, 0.05]):
        c.tick(13 + i, "s", v)
    assert c.p() < 0.30, c.p()
    print("selftest: 5/5 OK (cjson, fnv1a, margin law, tamper detection, evidence aggregation)")


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv
    selftest()
    print()
    board, ledger, chain_ok = run_night_shift(quiet=quiet)
    sys.exit(0 if chain_ok else 1)
