#!/usr/bin/env python3
"""dice_variants_deep.py — Swarm Lane D2 (B-run): the moth quantum, deepened.

NOTE: a sibling A-run writes jev-selection/dice_variants.py (N=10 abstract
scenario benchmark). This B-run keeps its artifacts distinct — no clobbering
(fleet law: archive, don't destroy). The two runs are complementary: A-run
benchmarks variant families on abstract truths; B-run plugs the variants
into the REAL J1 projector and audits the entropy source itself.

J1 (poc.py) fixed the collapse: u = fnv1a(receipt)/2^32 → CDF walk → one
agent fires. This lane asks: does the DICE strategy matter for the swarm's
long-term health? Four families, one frozen projector (J1's mesh, imported
not re-implemented), every bit fnv1a over sha-receipted content:

  1. single   — one fnv1a draw over the sha-receipted odds (J1 baseline)
  2. temp(T)  — J_T ∝ J^(1/T): T<1 sharpens (exploit), T>1 flattens (explore)
  3. bestofK  — K fair draws from J, fire the highest-odds agent drawn
                (order-statistics bias; no tilt on J itself)
     plus rejection sampling, proven ≡ direct sampling for finite targets
  4. div(λ)   — tilt odds by turn-ledger deficit: starved agents get dice
                help, bounded by λ (tilt ∈ [1, 1+λ]); λ=1 gentle, λ=3 strong

TWO LAWS (earned below, not asserted):
  D2-1  RECEIPT WHAT YOU ROLL — any tilt enters through a receipted
        effective distribution; the draw targets the eff receipt. JEV's
        projection stays pure; the dice may tilt, but the tilt is visible.
  D2-2  EVERY DIE GETS ITS OWN SHA RECEIPT — fnv1a over a k-appended FROZEN
        receipt is serially correlated (audit [A]: lag1≈+0.30, chi2 marginal
        fail); fnv1a over sha-preprocessed die content is clean. J1's live
        pattern (k=1 on a per-round receipt) was never exposed; any
        multi-draw or k-sweep pattern is, and must preprocess through sha.

No RNG: every draw is fnv1a over canonical content (exoj lineage). Stdlib
only. Run: python3 jev-selection/dice_variants_deep.py
"""

import importlib.util
import math
import sys
from itertools import product
from pathlib import Path

_here = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("jev_poc", _here / "poc.py")
jev = importlib.util.module_from_spec(_spec)          # J1 imported, not copied
_spec.loader.exec_module(jev)

AGENTS = jev.AGENTS
N = jev.N
fnv1a, sha, canonical = jev.fnv1a, jev.sha, jev.canonical

EPS = 1e-9
CHI2_DF15_001 = 30.578    # chi-square critical values, hardcoded (no scipy)
CHI2_DF4_001 = 13.277
GAMMA_TURN = 0.97         # turn-ledger decay ≈ 23-round memory (half-life)

STRATEGIES = ("single", "T=0.5", "T=2.0", "best2", "best3", "div1", "div3")

# hand-authored stress input: the dice layer's contract is ANY distribution J
SKEW = {"AG-SENSE": 0.62, "AG-PINCH": 0.16, "AG-RELAY": 0.10,
        "AG-MOLT": 0.07, "AG-COMPRESS": 0.05}

# decisive regime-change stress input (the J1 t=40 mesh flips only ~2pt at
# the top — too mild to stress dice recovery; contract here is ANY distribution)
POSTFLIP = {"AG-SENSE": 0.08, "AG-PINCH": 0.12, "AG-RELAY": 0.08,
            "AG-MOLT": 0.17, "AG-COMPRESS": 0.55}


# ── draw primitives (J1 moth_quantum lineage) ──────────────────────────────

def u_of(rcpt: str, k: int) -> float:
    """One fnv1a uniform in [0,1): the J1 formula, exposed for the audit."""
    return (fnv1a(canonical([rcpt, k])) & 0xFFFFFFFF) / 2**32


def die_receipt(er: str, k: int, sub: int = 0) -> str:
    """D2-2: every die gets its own sha receipt. fnv1a over a k-appended
    FROZEN receipt is serially correlated (audit [A]); sha-preprocessing the
    die index decorrelates it. Still pure fnv1a lineage at the mix step."""
    return sha(canonical([er, "die", k, sub]))


def lse_normalize(logs: dict) -> dict:
    top = max(logs.values())
    e = {a: math.exp(logs[a] - top) for a in AGENTS}
    z = sum(e.values())
    return {a: e[a] / z for a in AGENTS}


# ── the four families: effective distributions ─────────────────────────────

def temp_scale(J: dict, T: float) -> dict:
    """J_T ∝ J^(1/T).  T→0: argmax.  T→∞: uniform."""
    return lse_normalize({a: math.log(J[a] + EPS) / T for a in AGENTS})


def bestof_eff(J: dict, K: int) -> dict:
    """Exact effective policy of best-of-K: enumerate all N^K draw tuples,
    winner = max J (ties → canonical agent order). N=5, K≤3 ⇒ ≤125 tuples."""
    eff = {a: 0.0 for a in AGENTS}
    key = lambda a: (J[a], -AGENTS.index(a))
    for tup in product(AGENTS, repeat=K):
        p = 1.0
        for a in tup:
            p *= J[a]
        eff[max(tup, key=key)] += p
    z = sum(eff.values())
    assert abs(z - 1.0) < 1e-9, f"bestof_eff not a distribution (Σ={z})"
    return {a: eff[a] / z for a in AGENTS}


def bestof2_closed(J: dict) -> dict:
    """Closed form cross-check for K=2:
    P(a) = 1−(1−J_a)² − 2·J_a·Σ_{J_b>J_a} J_b   (drawn ≥once, minus losses)."""
    eff = {}
    for a in AGENTS:
        higher = sum(J[b] for b in AGENTS if J[b] > J[a])
        eff[a] = 1.0 - (1.0 - J[a])**2 - 2.0 * J[a] * higher
    z = sum(eff.values())
    assert abs(z - 1.0) < 1e-9, f"closed form off (Σ={z})"
    return {a: eff[a] / z for a in AGENTS}


def diversity_tilt(J: dict, ctx: dict, lam: float):
    """tilt_a = 1 + λ·(1 − T_a/max T): never-fired agents weigh up to (1+λ)×.
    T_a = decayed turn counts (the D1 turn-ledger, minimal form). λ is the
    fairness dial: 0 = pure JEV contract, 1 = gentle welfare, 3 = strong."""
    m = max(ctx.values())
    if m <= 0.0:
        return dict(J), {a: 1.0 for a in AGENTS}      # no history → no tilt
    tilt = {a: 1.0 + lam * (1.0 - ctx[a] / m) for a in AGENTS}
    raw = {a: J[a] * tilt[a] for a in AGENTS}
    z = sum(raw.values())
    return {a: raw[a] / z for a in AGENTS}, tilt


def eff_dist(strategy: str, J: dict, ctx: dict) -> dict:
    if strategy == "single":
        return dict(J)
    if strategy.startswith("T="):
        return temp_scale(J, float(strategy[2:]))
    if strategy.startswith("best"):
        return bestof_eff(J, int(strategy[-1]))
    if strategy.startswith("div"):
        return diversity_tilt(J, ctx, float(strategy[3:]))[0]
    raise ValueError(f"unknown strategy {strategy}")


def eff_receipt(strategy: str, rcpt: str, eff: dict) -> str:
    """D2-1: receipt what you roll — the draw targets the eff receipt."""
    return sha(canonical([rcpt, strategy, [f"{eff[a]:.9f}" for a in AGENTS]]))


def fire(strategy: str, J: dict, rcpt: str, k: int, ctx: dict) -> str:
    """The moth quantum under a strategy. Deterministic in (rcpt, k, ctx, J).
    k = which die this is (experiment index / round); each die rolls against
    its own receipt, so repeated experiments never reuse a die (D2-2)."""
    eff = eff_dist(strategy, J, ctx)
    er = eff_receipt(strategy, rcpt, eff)
    dr = die_receipt(er, k)
    if strategy.startswith("best"):
        K = int(strategy[-1])
        drawn = [jev.moth_quantum(J, die_receipt(er, k, i), 1)
                 for i in range(1, K + 1)]
        return max(drawn, key=lambda a: (J[a], -AGENTS.index(a)))
    return jev.moth_quantum(eff, dr, 1)               # draw against eff


def rejection_fire(target: dict, J: dict, er: str, i: int):
    """Classic rejection sampling: proposal J, target J_T. Bounded 64 tries,
    then direct target draw (fail-safe, still deterministic). Every proposal
    and accept die gets its own sha receipt (D2-2)."""
    M = max((target[a] + EPS) / (J[a] + EPS) for a in AGENTS)
    for attempt in range(1, 65):
        a = jev.moth_quantum(J, die_receipt(er, i, attempt), 1)
        u = u_of(die_receipt(er, i, attempt + 1000), 1)
        if u * M * (J[a] + EPS) <= (target[a] + EPS):
            return a, attempt
    return jev.moth_quantum(target, die_receipt(er, i), 1), 65


# ── simulation harness ──────────────────────────────────────────────────────

def run_sim(J_of_round, rounds: int, strategy: str, regime: str):
    ctx = {a: 0.0 for a in AGENTS}
    hist = []
    for r in range(1, rounds + 1):
        J = J_of_round(r)
        rcpt = sha(canonical(["D2-sim", regime, r, [f"{J[a]:.9f}" for a in AGENTS]]))
        a = fire(strategy, J, rcpt, 1, ctx)
        for b in AGENTS:
            ctx[b] *= GAMMA_TURN
        ctx[a] += 1.0
        hist.append(a)
    return hist, ctx


def worst_gap(hist: list, a: str) -> int:
    idx = [i for i, x in enumerate(hist) if x == a]
    if not idx:
        return len(hist)
    g = idx[0]
    for p, c in zip(idx, idx[1:]):
        g = max(g, c - p - 1)
    return max(g, len(hist) - 1 - idx[-1])


def recovery_rounds(hist: list, new_top: str, flip_at: int, window: int = 50) -> int:
    """Rounds past the flip until the trailing-window mode == new top."""
    for r in range(flip_at + window, len(hist) + 1):
        w = hist[r - window:r]
        top = max(AGENTS, key=lambda a: (w.count(a), -AGENTS.index(a)))
        if top == new_top:
            return r - flip_at
    return 10**9


def metrics(hist: list, target: dict):
    n = len(hist)
    counts = {a: hist.count(a) for a in AGENTS}
    fid = max(abs(100.0 * counts[a] / n - 100.0 * target[a]) for a in AGENTS)
    ent = -sum((counts[a] / n) * math.log2(counts[a] / n)
               for a in AGENTS if counts[a] > 0)
    gap = max(worst_gap(hist, a) for a in AGENTS)
    return counts, fid, ent, gap


def pct(J): return " ".join(f"{100*J[a]:>6.1f}" for a in AGENTS)
HDR = " ".join(f"{a.replace('AG-', ''):>6}" for a in AGENTS)


# ── [A] entropy source audit: is fnv1a enough at the dice? ─────────────────

def chi2_uniform(us, bins=16):
    n, exp = len(us), len(us) / bins
    c = [0] * bins
    for u in us:
        c[min(int(u * bins), bins - 1)] += 1
    return sum((ci - exp) ** 2 / exp for ci in c)


def lag1(us):
    n, mu = len(us), sum(us) / len(us)
    num = sum((us[i] - mu) * (us[i + 1] - mu) for i in range(n - 1))
    return num / sum((x - mu) ** 2 for x in us)


def section_A(rcpt):
    K = 4096
    print("\n[A] ENTROPY SOURCE — fnv1a audit at the dice "
          f"({K} draws, chi2 crit df15/α.01={CHI2_DF15_001}, |r|<0.05)")
    streams = [
        ("fnv1a(receipt:k)  [J1 k-sweep pattern]",
         [u_of(rcpt, k) for k in range(1, K + 1)]),
        ("fnv1a(str(k))     [raw ints — cautionary]",
         [(fnv1a(str(k)) & 0xFFFFFFFF) / 2**32 for k in range(1, K + 1)]),
        ("die_receipt(k)    [D2-2 sha-preprocessed]",
         [u_of(die_receipt(rcpt, k), 1) for k in range(1, K + 1)]),
    ]
    results = {}
    for name, us in streams:
        c2, r = chi2_uniform(us), lag1(us)
        ok = c2 < CHI2_DF15_001 and abs(r) < 0.05
        results[name] = (c2, r, ok)
        print(f"    {name:<38} chi2={c2:>7.2f}  lag1={r:+.4f}  "
              f"{'OK' if ok else 'SKEW — FAIL LOUD'}")
    # CDF bucket bias: does the walk itself favor agents at a uniform J?
    Ju = {a: 1.0 / N for a in AGENTS}
    counts = {a: 0 for a in AGENTS}
    for k in range(1, K + 1):
        counts[jev.moth_quantum(Ju, die_receipt(rcpt, k), 1)] += 1
    c2b = sum((counts[a] - K / N) ** 2 / (K / N) for a in AGENTS)
    ok_b = c2b < CHI2_DF4_001
    print(f"    CDF walk @ uniform J (chi2 crit df4/α.01={CHI2_DF4_001}):     "
          f"chi2={c2b:>7.2f}  {'OK' if ok_b else 'BIASED — FAIL LOUD'}")
    print("    counts: " + " ".join(f"{a.replace('AG-', '')}={counts[a]}" for a in AGENTS))
    print("    → D2-2 law: the k-sweep pattern correlates (r≈+0.30); D2 dice")
    print("      sha-preprocess every die. J1 live pattern (k=1, per-round")
    print("      receipt) was never exposed — no J1 bug, a J1 EDGE CONDITION.")
    return results["die_receipt(k)    [D2-2 sha-preprocessed]"][2] and ok_b


# ── [B] strategy gallery on the frozen J1 mesh ─────────────────────────────

def pool_scaled(cells, wscale):
    """J1's geometric pool, weights scaled — for the temp ≡ pool proof."""
    logs = {a: 0.0 for a in AGENTS}
    for q, _, _ in jev.CELL_SPECS:
        cell = cells[q]
        s, w = jev.simplex_point(cell), jev.confidence(cell) * wscale
        for a in AGENTS:
            logs[a] += w * math.log((s[a] + jev.EPS) / (1.0 + jev.N * jev.EPS))
    return lse_normalize(logs)


def section_B(J20, cells20, rcpt20):
    print("\n[B] STRATEGY GALLERY — frozen J1 mesh (t=20), effective firing odds")
    print(f"    {'strategy':<10} {HDR}   note")
    cold = {a: 0.0 for a in AGENTS}
    effs = {s: eff_dist(s, J20, cold) for s in STRATEGIES}
    notes = {"single": "J itself (literal odds)",
             "T=0.5": "sharpen: exploit", "T=2.0": "flatten: explore",
             "best2": "order-statistics bias", "best3": "stronger bias",
             "div1": "cold turn-ledger: tilt=1 ⇒ J",
             "div3": "cold turn-ledger: tilt=1 ⇒ J"}
    for s in STRATEGIES:
        print(f"    {s:<10} {pct(effs[s])}   {notes[s]}")

    # proof 1 — temperature at the dice ≡ cell-weight scaling in the pool.
    # Exact identity in reals (J ∝ Π s̃^w ⇒ J^(1/T) ∝ Π s̃^(w/T)); the two
    # float paths differ by ~1e-10, so the receipt bar is 1e-9, not 1e-12.
    d1 = max(abs(temp_scale(J20, 0.5)[a] - pool_scaled(cells20, 2.0)[a]) for a in AGENTS)
    d2 = max(abs(temp_scale(J20, 2.0)[a] - pool_scaled(cells20, 0.5)[a]) for a in AGENTS)
    eq_temp = d1 < 1e-9 and d2 < 1e-9
    print(f"\n    proof[temp]: J^(1/T) ≡ pool with weights w·(1/T):  "
          f"max|Δ| T=0.5:{d1:.2e}  T=2.0:{d2:.2e}  "
          f"{'IDENTICAL' if eq_temp else 'MISMATCH — FAIL LOUD'}")

    # proof 2 — bestof2 enumeration ≡ closed form
    d3 = max(abs(bestof_eff(J20, 2)[a] - bestof2_closed(J20)[a]) for a in AGENTS)
    eq_best = d3 < 1e-12
    print(f"    proof[best2]: enumeration ≡ closed form:            max|Δ| {d3:.2e}  "
          f"{'IDENTICAL' if eq_best else 'MISMATCH — FAIL LOUD'}")

    # proof 3 — rejection sampling ≡ direct sampling (finite, normalized)
    target = temp_scale(J20, 2.0)
    er = sha(canonical([rcpt20, "rejection", "T=2.0"]))
    K = 2000
    acc = {a: 0 for a in AGENTS}
    tries = 0
    for i in range(1, K + 1):
        a, att = rejection_fire(target, J20, er, i)
        acc[a] += 1
        tries += att
    M = max((target[a] + EPS) / (J20[a] + EPS) for a in AGENTS)
    dev_rej = max(abs(100 * acc[a] / K - 100 * target[a]) for a in AGENTS)
    eq_rej = dev_rej < 6.0
    print(f"    proof[rejection]: 2000 accepted draws vs direct J_T:  max|Δ| "
          f"{dev_rej:.1f}pt  accept-rate={K / tries:.3f} (theory 1/M={1 / M:.3f})  "
          f"{'EQUIVALENT' if eq_rej else 'DRIFT — FAIL LOUD'}")

    # proof 4 — bestof2 exact policy vs 4000 empirical draws (D2-2 dice)
    K = 4000
    acc = {a: 0 for a in AGENTS}
    ctx = {a: 0.0 for a in AGENTS}
    for i in range(1, K + 1):
        acc[fire("best2", J20, rcpt20, i, ctx)] += 1
    dev_best = max(abs(100 * acc[a] / K - 100 * effs["best2"][a]) for a in AGENTS)
    eq_best_emp = dev_best < 6.0
    print(f"    proof[best2-emp]: 4000 draws vs exact policy:         max|Δ| "
          f"{dev_best:.1f}pt  {'OK' if eq_best_emp else 'DRIFT — FAIL LOUD'}")

    # diversity rescue demo — real ctx from 100 rounds of single-draw under SKEW
    hist100, ctx100 = run_sim(lambda r: SKEW, 100, "single", "ctx-demo")
    print(f"\n    div tilt after 100 skew rounds (SENSE-dominated), λ=1 vs λ=3:")
    print(f"      agent      T_a    tilt(λ=1)  tilt(λ=3)    J   →eff(λ=1) →eff(λ=3)")
    _, tilt1 = diversity_tilt(SKEW, ctx100, 1.0)
    eff3, tilt3 = diversity_tilt(SKEW, ctx100, 3.0)
    eff1, _ = diversity_tilt(SKEW, ctx100, 1.0)
    for a in AGENTS:
        print(f"      {a.replace('AG-', ''):<9} {ctx100[a]:>6.2f}  {tilt1[a]:>8.3f} "
              f"{tilt3[a]:>9.3f}  {100*SKEW[a]:>4.0f}%  {100*eff1[a]:>7.1f}% "
              f"{100*eff3[a]:>8.1f}%")
    print("      starved agent's dice help is bounded: never more than (1+λ)× odds")

    return eq_temp and eq_best and eq_rej and eq_best_emp, dev_rej, dev_best


# ── [C] long-term health: three regimes × seven strategies ─────────────────

def section_C(J20):
    ROUNDS, FLIP = 400, 200
    regimes = [
        ("stationary", lambda r: J20, J20, None),
        ("skew-stress", lambda r: SKEW, SKEW, None),
        ("world-flip", lambda r: (J20 if r <= FLIP else POSTFLIP),
         {a: 0.5 * (J20[a] + POSTFLIP[a]) for a in AGENTS}, "AG-COMPRESS"),
    ]
    fid_ok, rec = True, {}
    tails = {}
    for name, J_of, target, new_top in regimes:
        tl = " (target = ½(pre+post))" if name == "world-flip" else ""
        print(f"\n[C] REGIME {name} — {ROUNDS} rounds{tl}")
        print(f"    projected J: {pct(target)}")
        print(f"    {'strategy':<10} {HDR}  {'fid(pt)':>7} {'H(bits)':>7} {'gap':>4}")
        for s in STRATEGIES:
            hist, _ = run_sim(J_of, ROUNDS, s, name)
            counts, fid, ent, gap = metrics(hist, target)
            print(f"    {s:<10} {pct({a: counts[a] / ROUNDS for a in AGENTS})}  "
                  f"{fid:>7.1f} {ent:>7.2f} {gap:>4}")
            if name == "stationary" and s == "single":
                fid_ok &= fid < 8.0
            if name == "skew-stress" and s in ("single", "div1", "div3"):
                tails[s] = worst_gap(hist, "AG-COMPRESS")
            if name == "world-flip":
                rec[s] = recovery_rounds(hist, new_top, FLIP)
        if name == "skew-stress":
            print(f"    tail agent COMPRESS worst starvation gap: "
                  f"single={tails['single']}  div1={tails['div1']} "
                  f"div3={tails['div3']} "
                  f"(div3 cuts {100 * (1 - tails['div3'] / tails['single']):.0f}%)")
        if name == "world-flip":
            print(f"    recovery (rounds past flip until 50-window mode==COMPRESS):")
            print("      " + "  ".join(f"{s}:{rec[s]}" for s in STRATEGIES))
    return fid_ok, rec, tails


# ── run ─────────────────────────────────────────────────────────────────────

def run_all():
    print("=" * 88)
    print("dice_variants_deep POC — Lane D2 B-run: the moth quantum, deepened")
    print("(4 dice families · 1 frozen J1 projector · entropy audit · no RNG)")
    print("=" * 88)

    # frozen projector from J1: warm mesh at t=20
    J20, _, cells20 = jev.build_and_run(20)
    rcpt20 = jev.receipt(J20, cells20, 20)
    print(f"frozen mesh t=20: {pct(J20)}   receipt {rcpt20[:16]}…")

    okA = section_A(rcpt20)
    okB, dev_rej, dev_best = section_B(J20, cells20, rcpt20)
    fid_ok, rec, tails = section_C(J20)

    rec_ok = all(v <= 80 for v in rec.values())
    rescue_ok = tails["div3"] <= 0.6 * tails["single"]
    print("\n[D] VERDICT")
    print(f"    [A] sha-preprocessed dice pass uniformity+serial; walk unbiased: "
          f"{'PASS' if okA else 'FAIL LOUD'}")
    print(f"    [B] temp≡pool-weights, best2 exact, rejection≡direct:      "
          f"{'PASS' if okB else 'FAIL LOUD'}")
    print(f"    [C] single-draw fidelity to J (<8pt, stationary):          "
          f"{'PASS' if fid_ok else 'FAIL LOUD'}")
    print(f"    [C] flip recovery ≤80 rounds for every strategy:           "
          f"{'PASS' if rec_ok else 'FAIL LOUD'}")
    print(f"    [C] div3 cuts tail starvation ≥40% under skew:             "
          f"{'PASS' if rescue_ok else 'FAIL LOUD'}")
    ok = okA and okB and fid_ok and rec_ok and rescue_ok
    print(f"\n    {'ALL CHECKS PASS' if ok else 'FAIL LOUD'} — "
          "single draw is the contract default; tilt only through a receipted "
          "effective distribution (D2-1); every die gets its own sha receipt "
          "(D2-2).")
    return ok


def main():
    import contextlib
    import io
    b1, b2 = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(b1):
        ok1 = run_all()
    with contextlib.redirect_stdout(b2):
        ok2 = run_all()
    same = b1.getvalue() == b2.getvalue() and ok1 == ok2
    sys.stdout.write(b1.getvalue())
    print(f"\n[0] determinism: two full in-process runs byte-identical={same} "
          f"(output sha={sha(b1.getvalue())[:16]}…)")
    assert same and ok1, "FAIL LOUD: nondeterminism or failed checks"
    return 0


if __name__ == "__main__":
    sys.exit(main())
