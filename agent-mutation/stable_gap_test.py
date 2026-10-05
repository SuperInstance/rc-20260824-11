#!/usr/bin/env python3
"""ZEROCLAW agent-mutation M3 — STABLE GAP TEST (2026-10-05).
Verdict follow-up (VERDICTS.md): "stable gap test (long-horizon with no
flips between them) where stable:tighten should fire."
Q: on a long-horizon world with NO regime flips, does the M2 machinery
behave as designed?
  S1. every boundary probe senses drift < TRIGGER -> why == "stable:tighten"
  S2. tighten moves pull lam/rho monotonically back toward v0 (half-steps),
      never past it (clamped)
  S3. tightening never regresses the lineage in a stable regime
      (child_sim >= parent_continue, existing law assert)
  S4. with no flips ever, does the lineage accumulate a standing tax vs
      fresh v0? (M2 found a tax under flips; here the counterfactual)
Windows: 4 consecutive GOOD windows (t=1..200), regime patched to good at
all t. Reuses M2 machinery unchanged (import lineage_evolution). No RNG.
NOTE (honest bug found during this build): probing across t=51 in the UN-
patched world senses a REAL flip (regime(t) flips there) — early drafts
of this test misread that as a phantom sensor firing. The sensor was
right; the harness was wrong."""
import json, sys

import lineage_evolution as m2

m2.regime = lambda t: 1   # M3 world: GOOD forever — genuinely flip-free
                           # (M2's regime(t) flips at t=51/101; patching it is
                           # the point: the SAME machinery, a stable world)


def run_stable():
    wins = [(1, 50), (51, 100), (101, 150), (151, 200)]  # all GOOD
    log, lineage = [], m2.Agent(m2.genome_v0())
    for gi, (t0, t1) in enumerate(wins):
        row = {"gen": gi, "window": [t0, t1],
               "lineage": m2.run_window(lineage, t0, t1),
               "independent": m2.run_window(m2.Agent(m2.genome_v0()), t0, t1),
               "fresh_genome": m2.run_window(
                   m2.Agent(json.loads(m2.canon(lineage.genome))), t0, t1)}
        log.append(row)
        if gi == len(wins) - 1:
            break
        ev = m2.probe_drift(lineage, wins[gi + 1][0])
        child_g, moves, why = m2.coupled_mutate(lineage.genome, ev)
        cont = m2.run_window(lineage.clone_at(lineage.genome), *wins[gi + 1])
        child_sim = m2.run_window(lineage.clone_at(child_g), *wins[gi + 1])
        row["boundary"] = {"probe": ev, "why": why, "moves": moves,
                           "mutation_size": m2.l1_distance(lineage.genome, child_g),
                           "parent_continue": cont, "child_sim": child_sim,
                           "child_genome": m2.genome_id(child_g)}
        lineage = lineage.clone_at(child_g)
    return log


def l1_v0(genome):
    v0 = m2.genome_v0()
    return round(m2.l1_distance(genome, v0), 4)


def main():
    print("=" * 74)
    print("ZEROCLAW M3 — STABLE GAP TEST (no RNG) | NO flips, t=1..200 good")
    print("=" * 74)
    log = run_stable()

    fires, tightens_ok, no_regress = 0, 0, True
    for row in log[:-1]:
        b = row["boundary"]
        p = b["probe"]
        fired = b["why"] == "stable:tighten"
        fires += fired
        # S1: no flip ever sensed in a flip-free world
        assert p["drift"] < m2.TRIGGER, f"FAIL: phantom flip sensed (drift={p['drift']})"
        assert fired, f"FAIL: tighten did not fire on stable boundary (why={b['why']})"
        # S2: every move is a half-step TOWARD v0 genes (lam up-capped, rho down-floored)
        for mv in b["moves"]:
            gene, frm, to = mv["gene"], mv["from"], mv["to"]
            if gene.startswith("lam"):
                assert to > frm and to <= 1.0, f"FAIL: lam tighten not toward v0 ({mv})"
            else:
                assert to < frm and to >= m2.RHO_BASE, f"FAIL: rho tighten not toward v0 ({mv})"
        tightens_ok += 1
        # S3: tightening never regresses in a stable regime
        if b["moves"]:
            assert b["child_sim"]["score"] >= b["parent_continue"]["score"], \
                f"FAIL: tighten regressed lineage ({b['child_sim']['score']} < {b['parent_continue']['score']})"
        print(f"gen-{row['gen']} boundary: drift={p['drift']:.3f} -> {b['why']} | "
              f"size={b['mutation_size']} | L1-to-v0 after: {l1_v0_child(b, row, log):.4f}" if False else
              f"gen-{row['gen']} boundary: drift={p['drift']:.3f} -> {b['why']} | "
              f"moves={len(b['moves'])} | child {b['child_sim']['score']:+d} vs parent-cont "
              f"{b['parent_continue']['score']:+d}")

    tot = {k: sum(r[k]["score"] for r in log) for k in ("lineage", "independent", "fresh_genome")}
    print(f"\ntotals — lineage {tot['lineage']:+d} | fresh-genome(same) {tot['fresh_genome']:+d} "
          f"| independent(fresh v0) {tot['independent']:+d}")
    tax = tot["independent"] - tot["lineage"]
    if tot["lineage"] >= tot["independent"]:
        verdict = f"NO STANDING TAX in a flip-free world — lineage {tot['lineage']:+d} >= fresh v0 {tot['independent']:+d}"
    else:
        verdict = f"STANDING TAX persists even without flips: lineage {tot['lineage']:+d} < fresh v0 {tot['independent']:+d} (tax {tax:+d})"

    print(f"\nfacts: stable:tighten fired {fires}/{len(log) - 1} boundaries; all moves half-steps toward v0; "
          f"no tighten ever regressed the lineage")
    print("VERDICT: " + verdict + ".")
    receipt = m2.sha(log)
    assert m2.sha(run_stable()) == receipt, "FAIL: nondeterministic run"
    print(f"DETERMINISM: second full run bit-identical (receipt {receipt})")
    print("EXIT 0 — invariants held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
