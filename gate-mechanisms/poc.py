#!/usr/bin/env python3
"""ZEROCLAW gate-mechanisms POC — Lane 2 (2026-10-04).

Demonstrates, in one deterministic run (NO RNG anywhere — all stimulus
entropy is fnv1a content-derived, per the exoj UnitTable law):

  1. Threshold gates firing on cell tick-probabilities (G1 excite, G2 inhibit)
  2. A cascade: G1's target is G3's source; G3 fires only after G1, lag >= 1
  3. Negative feedback: G2 (inhibit) closes the loop C2 -> C1, damping
     C1's evidence whenever approach gets confident; per-gate adaptation
     additionally tightens theta on every fire (the reflex dampens itself
     twice: topologically and parametrically).
  4. A bidirectional (sign) gate: G3 transmits the sign of C2's evidence.

Circuit:
  world --ticks--> C1 sees-light --G1 excite(t=.70)--> C2 approach --G3 sign(t=.65)--> C3 commit-move
                        ^                                  |
                        +--------- G2 inhibit(t=.75) ------+   (negative feedback loop)

Exit 0 = all invariants held (fail loud: NO VERIFIED SHA, NO BELIEF).
"""
import hashlib
import json
import sys

T_TICKS = 200          # world ticks per run
WORLD_BIAS = 80        # % of +1 ticks in C1's deterministic stream (out of 100)


def fnv1a(s: str) -> int:
    """32-bit FNV-1a — the deterministic entropy substitute (exoj lineage)."""
    h = 0x811C9DC5
    for b in s.encode():
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def world_tick(question: str, t: int) -> int:
    """Deterministic stimulus: no random, no seed, reproducible bit-for-bit."""
    return 1 if fnv1a(f"{question}:{t}") % 100 < WORLD_BIAS else -1


def sha256_hex(obj) -> str:
    """Receipt over canonical JSON (sorted keys, tight separators)."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class Cell:
    """A question answered over time. Append-only tick ledger, never mutated.

    p = (ups + 1) / (n + 2): Laplace-smoothed mean; 0.5 on an empty ledger;
    in [0,1] by construction (counts, not floats). Commutative tally: tick
    order never changes the aggregate — only arrival time matters.
    """

    def __init__(self, name: str):
        self.name = name
        self.ups = 0            # count of +1 ticks (the ONLY mutable state)
        self.n = 0              # total ticks
        self.ticks = []         # append-only ledger (for the receipt)

    def tick(self, v: int, t: int, why: str):
        assert v in (+1, -1), f"tick value {v} not ±1"
        self.n += 1
        self.ups += 1 if v > 0 else 0
        self.ticks.append({"t": t, "v": v, "why": why})

    @property
    def p(self) -> float:
        return (self.ups + 1) / (self.n + 2)


class Gate:
    """Directed edge with threshold theta, refractory R, adaptation lambda.

    kind: 'excite'  p_src >= theta            -> +1 tick to dst
          'inhibit' p_src >= theta            -> -1 tick to dst
          'sign'    p_src >= theta            -> +1 tick to dst
                    p_src <= 1 - theta        -> -1 tick to dst
    On fire: theta += adapt*(1-theta) (tightens — reflex formation).
    Per tick (no fire): theta relaxes toward theta_base by relax.
    """

    def __init__(self, name, kind, src, dst, theta, refractory=10,
                 adapt=0.06, relax=0.008):
        assert kind in ("excite", "inhibit", "sign")
        self.name, self.kind, self.src, self.dst = name, kind, src, dst
        self.theta_base, self.theta = theta, theta
        self.refractory, self.adapt, self.relax = refractory, adapt, relax
        self.since_fire = refractory   # eligible at t=0
        self.fires = []                # append-only fire ledger
        self.violations = []

    def evaluate(self, t, src_p, out):
        """Called with a SNAPSHOT p (synchronous semantics): emissions from
        all gates this tick are applied after every gate has evaluated, so
        cascade delay is always >= 1 tick per structural depth."""
        self.since_fire += 1
        fired = None
        if self.since_fire >= self.refractory:
            if self.src_p_predicate(src_p):
                fired = +1
            elif self.kind == "sign" and src_p <= 1.0 - self.theta:
                fired = -1
        if fired is None:
            # relax toward base (forgetting) — bounded, never below base
            self.theta = max(self.theta_base,
                             self.theta - self.relax * (self.theta - self.theta_base))
            return
        if self.since_fire < self.refractory:  # unreachable; guard for loud failure
            self.violations.append(f"{self.name} fired inside refractory at t={t}")
        self.since_fire = 0
        self.theta += self.adapt * (1.0 - self.theta)  # tighten from evidence
        self.fires.append({"t": t, "emit": fired, "theta": round(self.theta, 4),
                           "src_p": round(src_p, 4)})
        out.append((self.dst, fired, f"{self.name}:{self.kind}"))

    def src_p_predicate(self, src_p) -> bool:
        return src_p >= self.theta


def run():
    c1 = Cell("sees-light")
    c2 = Cell("approach")
    c3 = Cell("commit-move")
    g1 = Gate("G1", "excite", c1, c2, theta=0.70)
    g2 = Gate("G2", "inhibit", c2, c1, theta=0.75)
    g3 = Gate("G3", "sign", c2, c3, theta=0.65)
    gates = [g1, g2, g3]

    print(f"=== zeroclaw gate-mechanisms POC — {T_TICKS} ticks, deterministic "
          f"(bias={WORLD_BIAS}%, no RNG) ===")
    print(f"circuit: world -> C1 --G1 excite@.70--> C2 --G3 sign@.65--> C3 ; "
          f"C2 --G2 inhibit@.75--> C1 (feedback)")
    header = f"{'t':>4} {'C1.p':>6} {'C2.p':>6} {'C3.p':>6} | {'G1.th':>6} {'G2.th':>6} {'G3.th':>6} | fires this tick"
    print(header)

    for t in range(T_TICKS):
        c1.tick(world_tick("sees-light", t), t, "world")

        # synchronous: evaluate all gates against the pre-fire snapshot
        snap = {c1: c1.p, c2: c2.p, c3: c3.p}
        emissions = []
        fired_names = []
        for g in gates:
            n_before = len(g.fires)
            g.evaluate(t, snap[g.src], emissions)
            if len(g.fires) > n_before:
                fired_names.append(g.name)
        for dst, v, why in emissions:   # apply after evaluation
            dst.tick(v, t, why)

        if t % 10 == 0 or fired_names:
            print(f"{t:>4} {snap[c1]:>6.3f} {snap[c2]:>6.3f} {snap[c3]:>6.3f} | "
                  f"{g1.theta:>6.3f} {g2.theta:>6.3f} {g3.theta:>6.3f} | "
                  f"{','.join(fired_names) or '-'}")

    # ---------------- invariants (fail loud) ----------------
    fails = []
    for g in gates:
        fails += g.violations
        for i in range(1, len(g.fires)):
            if g.fires[i]["t"] - g.fires[i - 1]["t"] < g.refractory:
                fails.append(f"{g.name} refractory violated: "
                             f"{g.fires[i-1]['t']} -> {g.fires[i]['t']}")
    for c in (c1, c2, c3):
        if not 0.0 <= c.p <= 1.0:
            fails.append(f"{c.name} p out of [0,1]: {c.p}")

    if len(g1.fires) < 3:
        fails.append(f"G1 fired only {len(g1.fires)}x (threshold demo failed)")
    if len(g3.fires) < 1:
        fails.append("G3 never fired (cascade demo failed)")
    if len(g2.fires) < 2:
        fails.append(f"G2 fired only {len(g2.fires)}x (negative feedback failed)")

    # cascade lag: every G3 fire must trail a G1 fire by >= 1 tick
    g1_times = [f["t"] for f in g1.fires]
    lags = [g3t - max(t for t in g1_times if t < g3t)
            for g3t in (f["t"] for f in g3.fires) if any(t < g3t for t in g1_times)]
    if not lags or min(lags) < 1:
        fails.append(f"cascade lag invalid: {lags}")
    else:
        print(f"\ncascade: G3 trailed G1 by min {min(lags)} / median "
              f"{sorted(lags)[len(lags)//2]} ticks (emergent, never scheduled)")

    # negative feedback: C1's peak after first G2 fire < peak before it
    if g2.fires:
        t2 = g2.fires[0]["t"]
        # running peak of C1's p over its append-only ledger, before/after the
        # first feedback fire (recomputed from the ledger prefix, not final state)
        def peak(ticks):
            u = n = 0
            best = 0.5
            for tk in ticks:
                n += 1
                u += 1 if tk["v"] > 0 else 0
                best = max(best, (u + 1) / (n + 2))
            return best
        pre, post = peak(c1.ticks[: t2 + 1]), peak(c1.ticks[t2 + 1:])
        print(f"negative feedback: C1 peak before first G2 fire {pre:.3f} vs after {post:.3f}"
              f" (damped={'YES' if post < pre else 'NO'})")
        if post >= pre:
            fails.append(f"feedback did not damp C1 ({pre} -> {post})")
        if g2.theta <= g2.theta_base:
            fails.append(f"G2 theta never tightened from evidence "
                         f"({g2.theta_base} -> {g2.theta})")
        else:
            print(f"adaptation: G2 theta tightened {g2.theta_base:.2f} -> {g2.theta:.3f} "
                  f"(reflex formed from its own firing evidence)")

    # ---------------- receipt ----------------
    receipt = sha256_hex({
        "poc": "gate-mechanisms/v1", "ticks": T_TICKS, "bias": WORLD_BIAS,
        "cells": {c.name: {"ups": c.ups, "n": c.n, "p": c.p} for c in (c1, c2, c3)},
        "gates": {g.name: {"kind": g.kind, "fires": len(g.fires),
                           "theta_end": round(g.theta, 4)} for g in gates},
        "fire_ledger": {g.name: g.fires for g in gates},
    })
    print(f"\nfires: G1={len(g1.fires)} G2={len(g2.fires)} G3={len(g3.fires)}   "
          f"final p: C1={c1.p:.3f} C2={c2.p:.3f} C3={c3.p:.3f}")
    print(f"receipt sha256: {receipt}")

    if fails:
        print("\nFAIL — invariants violated:", file=sys.stderr)
        for f in fails:
            print(f"  - {f}", file=sys.stderr)
        sys.exit(1)
    print("ALL INVARIANTS HELD (threshold, cascade, feedback, adaptation)")
    return receipt


if __name__ == "__main__":
    run()
