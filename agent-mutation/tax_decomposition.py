#!/usr/bin/env python3
"""ZEROCLAW agent-mutation M4 — TAX DECOMPOSITION (2026-10-05).
M3 open finding: in a FLIP-FREE world the lineage still pays a standing tax
(lineage +34 < fresh v0 +36) even though the genome is already back in the
v0 band and stable:tighten fired with zero moves. So the tax is NOT in the
genome. Where is it?
  A. CELL LEDGER baggage — inherited pseudo-counts (ups/downs/ticks) bias
     posterior p away from what a fresh cell would believe.
  B. GATE RUNTIME baggage — inherited theta (raised past theta_base by past
     lam_adapt) + last_fire/fire history changes firing cadence.
Method: transplant arms. Each boundary, take the lineage child and build
variants that inherit only-ledger, only-gates, both (=lineage), neither
(=fresh runtime). Score each on the SAME next window. Decomposition:
  tax_total   = fresh_runtime - lineage
  tax_ledger  = fresh_runtime - only_gates      (ledger removed)
  tax_gates   = fresh_runtime - only_ledger     (gates removed)
Cross-check: tax_ledger + tax_gates ~ tax_total if components are additive.
No RNG. World patched GOOD forever (same M3 harness law: regime patched at
use-time, M2 machinery untouched).
"""
import json, sys

import lineage_evolution as m2

m2.regime = lambda t: 1  # M3/M4 world: GOOD forever (genuinely flip-free)


def agent_with_runtime(genome, ledger_from=None, gates_from=None):
    """Agent with `genome`; cell ledgers copied from ledger_from; gate
    runtime (theta/fires/last_fire) copied from gates_from. clone_at
    semantics, per-component."""
    a = m2.Agent(genome)
    if ledger_from is not None:
        for name, live in ledger_from.cells.items():
            c = a.cells[name]
            c.ups, c.downs, c.ticks = live.ups, live.downs, list(live.ticks)
            if abs(c.lam - live.lam) > 1e-12:
                c.rebuild_from_ledger(c.lam)
    if gates_from is not None:
        live_g = {g.name: g for g in gates_from.gates}
        for g in a.gates:
            if g.name in live_g:
                lg = live_g[g.name]
                g.theta, g.fires, g.last_fire = lg.theta, lg.fires, lg.last_fire
    return a


def run_decomp():
    wins = [(1, 50), (51, 100), (101, 150), (151, 200)]
    log, lineage = [], m2.Agent(m2.genome_v0())
    for gi, (t0, t1) in enumerate(wins):
        row = {"gen": gi, "window": [t0, t1],
               "lineage": m2.run_window(lineage, t0, t1),
               "fresh_v0": m2.run_window(m2.Agent(m2.genome_v0()), t0, t1)}
        if gi == len(wins) - 1:
            log.append(row)
            break
        # evolve exactly as M3 (stable:tighten path; M3 showed zero moves)
        ev = m2.probe_drift(lineage, wins[gi + 1][0])
        child_g, moves, why = m2.coupled_mutate(lineage.genome, ev)
        child = lineage.clone_at(child_g)
        w0, w1 = wins[gi + 1]
        row["boundary"] = {
            "probe": ev, "why": why, "moves": len(moves),
            "lineage":   m2.run_window(child.clone_at(child_g), w0, w1)["score"],
            "fresh_rt":  m2.run_window(agent_with_runtime(child_g), w0, w1)["score"],
            "led_only":  m2.run_window(agent_with_runtime(child_g, ledger_from=lineage), w0, w1)["score"],
            "gates_only": m2.run_window(agent_with_runtime(child_g, gates_from=lineage), w0, w1)["score"],
        }
        log.append(row)
        lineage = child
    return log


def main():
    print("=" * 74)
    print("ZEROCLAW M4 — TAX DECOMPOSITION (no RNG) | flip-free world, t=1..200")
    print("=" * 74)
    log = run_decomp()
    tot = {k: sum(r.get("boundary", {}).get(k, 0) for r in log)
           for k in ("lineage", "fresh_rt", "led_only", "gates_only")}
    tot["fresh_v0"] = sum(r["fresh_v0"]["score"] for r in log)
    tot["lineage_track"] = sum(r["lineage"]["score"] for r in log)
    print(f"\nnext-window transplant totals over 3 boundaries:")
    print(f"  lineage (ledger+gates inherited) {tot['lineage']:+d}")
    print(f"  ledger-only                      {tot['led_only']:+d}")
    print(f"  gates-only                       {tot['gates_only']:+d}")
    print(f"  fresh runtime (neither)          {tot['fresh_rt']:+d}")
    print(f"\nfull-track totals: lineage {tot['lineage_track']:+d} vs fresh v0 {tot['fresh_v0']:+d}")
    tax_total = tot["fresh_rt"] - tot["lineage"]
    tax_ledger = tot["fresh_rt"] - tot["led_only"]
    tax_gates = tot["fresh_rt"] - tot["gates_only"]
    print(f"\ndecomposition (positive = component costs points):")
    print(f"  tax_total  = {tax_total:+d}")
    print(f"  tax_ledger = {tax_ledger:+d}   (removing ledger recovers this)")
    print(f"  tax_gates  = {tax_gates:+d}   (removing gate runtime recovers this)")
    print(f"  additivity check: tax_ledger + tax_gates = {tax_ledger + tax_gates:+d} vs total {tax_total:+d}")
    parts = []
    if tax_ledger > 0 and tax_gates <= 0:
        parts.append("TAX IS LEDGER-BORNE: inherited pseudo-counts alone carry the flip-free standing tax")
    elif tax_gates > 0 and tax_ledger <= 0:
        parts.append("TAX IS GATE-BORNE: inherited theta/fire history alone carries the tax")
    elif tax_ledger > 0 and tax_gates > 0:
        parts.append("TAX IS MIXED: both ledger and gate runtime contribute")
    else:
        parts.append("NO COMPONENT TAX FOUND: transplants did not reproduce the M3 gap (falsifies the decomposition — investigate harness)")
    if abs((tax_ledger + tax_gates) - tax_total) <= abs(tax_total):
        parts.append("components approximately additive")
    else:
        parts.append("components NON-additive (interference between ledger and gate state)")
    print("VERDICT: " + "; ".join(parts) + ".")
    receipt = m2.sha(log)
    assert m2.sha(run_decomp()) == receipt, "FAIL: nondeterministic run"
    print(f"DETERMINISM: second full run bit-identical (receipt {receipt})")
    print("EXIT 0 — invariants held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
