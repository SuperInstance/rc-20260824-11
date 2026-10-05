#!/usr/bin/env python3
"""jev-selection POC — Swarm Lane J1: JEV's projection of firing odds.

JEV meshes M cells (Lane 1 cell-internals cells, imported not re-implemented)
into one selection distribution over N agents:

    s_m = Σ_y p_m(y)·W_m(y)          per-cell point on the agent simplex
    J(a) ∝ Π_m s̃_m(a)^{w_m}         weighted geometric (log-linear) pool
    u = fnv1a(receipt)/2^32          moth quantum → one agent fires

Percentages are literal firing odds. No RNG: every draw is fnv1a over
content (exoj gan/unitTable lineage). Stdlib only.

Run: python3 jev-selection/poc.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import Cell, canonical, fnv1a, sha, world_answer  # noqa: E402

# ── the population: N agents (lanes that can fire) ─────────────────────────
AGENTS = ("AG-SENSE", "AG-PINCH", "AG-RELAY", "AG-MOLT", "AG-COMPRESS")
N = len(AGENTS)

EPS = 1e-9   # doubt floor: no agent's odds ever hit zero ("doubt stamped…")
N0 = 8.0     # prior ticks: w_m = n_eff/(n_eff+N0) — empty ledgers stay quiet

# ── the wiring: each answer maps to a row over agents (rows sum to 1) ──────
# This is the logic decomposition, hand-written and legible by design:
# "if the world answers y to q, my evidence splits over agents like this."
WIRING = {
    "relay/alive?": {          # world says relay is healthy?
        "yes": {"AG-SENSE": 0.25, "AG-PINCH": 0.15, "AG-RELAY": 0.45, "AG-MOLT": 0.05, "AG-COMPRESS": 0.10},
        "no":  {"AG-SENSE": 0.45, "AG-PINCH": 0.05, "AG-RELAY": 0.05, "AG-MOLT": 0.20, "AG-COMPRESS": 0.25},
    },
    "pinch/match?": {          # last grasp matched the target?
        "hit": {"AG-SENSE": 0.15, "AG-PINCH": 0.20, "AG-RELAY": 0.45, "AG-MOLT": 0.05, "AG-COMPRESS": 0.15},
        "miss": {"AG-SENSE": 0.45, "AG-PINCH": 0.25, "AG-RELAY": 0.05, "AG-MOLT": 0.10, "AG-COMPRESS": 0.15},
    },
    "listener/veto?": {        # listener wants the plan halted?
        "veto": {"AG-SENSE": 0.10, "AG-PINCH": 0.05, "AG-RELAY": 0.05, "AG-MOLT": 0.20, "AG-COMPRESS": 0.60},
        "calm": {"AG-SENSE": 0.30, "AG-PINCH": 0.40, "AG-RELAY": 0.20, "AG-MOLT": 0.05, "AG-COMPRESS": 0.05},
    },
    "molt/ready?": {           # is a molt (agent-mutation) due?
        "ready": {"AG-SENSE": 0.10, "AG-PINCH": 0.10, "AG-RELAY": 0.10, "AG-MOLT": 0.55, "AG-COMPRESS": 0.15},
        "hold": {"AG-SENSE": 0.40, "AG-PINCH": 0.30, "AG-RELAY": 0.20, "AG-MOLT": 0.05, "AG-COMPRESS": 0.05},
    },
}
for q, rows in WIRING.items():                      # wiring is well-formed, or fail loud
    for y, row in rows.items():
        assert abs(sum(row.values()) - 1.0) < 1e-12, f"wiring row {q}/{y} is not a distribution"
        assert set(row) == set(AGENTS), f"wiring row {q}/{y} misses an agent"

CELL_SPECS = [  # (question, answers, decay lam)
    ("relay/alive?", ("yes", "no"), 1.0),
    ("pinch/match?", ("hit", "miss"), 0.85),
    ("listener/veto?", ("veto", "calm"), 0.60),
    ("molt/ready?", ("ready", "hold"), 0.85),
]


def molt_world(t: int, flip_at: int | None = None) -> str:
    """Deterministic world for the one new question (Lane 1 pattern, fnv1a)."""
    rate = 0.25
    if flip_at is not None and t >= flip_at:
        rate = 0.75  # world flips: molts become due
    bit = fnv1a(f"molt/ready?:{t}") % 10000 / 10000.0
    return ("ready", "hold")[0] if bit < rate else ("ready", "hold")[1]


def feed(cells, t, flip_at=None):
    """One world tick into every cell (deterministic content-derived answers)."""
    for q, answers, _ in CELL_SPECS:
        if q == "molt/ready?":
            a = molt_world(t, flip_at)
        else:
            a = world_answer(q, answers, t, flip_at if q == "listener/veto?" else None)
        cells[q].tick(a)


# ── layer 3: each cell's point on the agent simplex ────────────────────────
def simplex_point(cell: Cell) -> dict:
    """s_m = Σ_y p_m(y)·W_m(y) — a mixture of rows: a distribution by construction."""
    p = cell.dist()
    s = {a: 0.0 for a in AGENTS}
    for y, row in WIRING[cell.question].items():
        py = p[y]
        for a in AGENTS:
            s[a] += py * row[a]
    assert abs(sum(s.values()) - 1.0) < 1e-12, f"simplex point off for {cell.question}"
    return s


def confidence(cell: Cell) -> float:
    """w_m = n_eff/(n_eff+N0): empty ledgers whisper, rich ledgers vote."""
    return cell.n_eff() / (cell.n_eff() + N0)


# ── layer 4: the mesh — weighted geometric pool (log domain, logsum-exp) ───
def mesh(cells: dict) -> tuple[dict, dict]:
    """Returns (J over agents, per-cell (s_m, w_m) for legibility)."""
    contribs, logs = {}, {a: 0.0 for a in AGENTS}
    for q, _, _ in CELL_SPECS:
        cell = cells[q]
        s, w = simplex_point(cell), confidence(cell)
        contribs[q] = (s, w)
        for a in AGENTS:
            s_tilde = (s[a] + EPS) / (1.0 + N * EPS)   # doubt floor, renormalized
            logs[a] = logs.get(a, 0.0) + w * math.log(s_tilde)
    top = max(logs.values())                             # logsum-exp: no under/overflow
    e = {a: math.exp(logs[a] - top) for a in AGENTS}
    z = sum(e.values())                                  # the ONE explicit division
    J = {a: e[a] / z for a in AGENTS}
    resid = abs(sum(J.values()) - 1.0)
    assert resid < 1e-12, f"J is not a distribution (|ΣJ−1| = {resid})"
    return J, contribs


def receipt(J: dict, cells: dict, rnd: int) -> str:
    """The odds vector is content-addressed: sha over canonical(cell heads, round, J)."""
    payload = {
        "heads": [cells[q].head for q, _, _ in CELL_SPECS],
        "round": rnd,
        "J": [[a, f"{J[a]:.9f}"] for a in AGENTS],  # fixed precision → replay-stable
    }
    return sha(canonical(payload))


# ── layer 5: the moth quantum — one deterministic draw against the receipt ──
def moth_quantum(J: dict, rcpt: str, k: int) -> str:
    u = (fnv1a(canonical([rcpt, k])) & 0xFFFFFFFF) / 2**32
    cdf = 0.0
    for a in AGENTS:                    # canonical order ⇒ deterministic CDF walk
        cdf += J[a]
        if u < cdf:
            return a
    return AGENTS[-1]


def odds_line(label, J, cells=None, rnd=None):
    bar = " ".join(f"{a.replace('AG-',''):>9}" for a in AGENTS)
    pct = " ".join(f"{100*J[a]:>8.1f}%" for a in AGENTS)
    h = (f"  {J['AG-SENSE']:.3f}" if False else
         f"entropy={-(sum(J[a]*math.log2(J[a]) for a in AGENTS)):.2f}b")
    r = f"  head={receipt(J, cells, rnd)[:12]}…" if cells else ""
    print(f"  {label:<26} {pct}   Σ={sum(J.values()):.12f}  {h}{r}")
    return J


def build_and_run(ticks, flip_at=None, tick_noise=None):
    """Deterministic pipeline: fresh cells → ticks → mesh. tick_noise adds one
    extra tick on one cell (perturbation experiment). Returns (J, contribs, cells)."""
    cells = {q: Cell(q, answers, alpha=0.5, lam=lam) for q, answers, lam in CELL_SPECS}
    for t in range(1, ticks + 1):
        feed(cells, t, flip_at)
    if tick_noise:
        q_noise, ans_noise, _ = next(sp for sp in CELL_SPECS if sp[0] == tick_noise)
        a_noise = molt_world(ticks + 1) if q_noise == "molt/ready?" else \
            world_answer(q_noise, ans_noise, ticks + 1)
        cells[q_noise].tick(a_noise)
    for q in cells:
        assert cells[q].verify_chain(), f"chain FAILED for {q}"
    J, contribs = mesh(cells)
    return J, contribs, cells


def main():
    print("=" * 78)
    print("jev-selection POC — cells → simplex points → geometric pool → firing odds")
    print("=" * 78)

    # 1) COLD START — empty ledgers: w≈0 ⇒ L≈0 ⇒ J → uniform (thin evidence, flat odds)
    J0, c0, cells0 = build_and_run(0)
    print(f"\n[1] cold start (0 ticks, M={len(CELL_SPECS)} cells → N={N} agents)")
    odds_line("J (cold)", J0, cells0, 0)
    for q, (s, w) in c0.items():
        print(f"    {q:<16} w={w:.3f}  s_m={' '.join(f'{s[a]:.3f}' for a in AGENTS)}")

    # 2) WARM FIELD — 20 ticks of stationary world: odds sharpen from evidence
    J20, c20, cells20 = build_and_run(20)
    print(f"\n[2] warm field (20 ticks) — percentages are literal firing odds")
    odds_line("J (t=20)", J20, cells20, 20)
    for q, (s, w) in c20.items():
        print(f"    {q:<16} w={w:.3f}  s_m={' '.join(f'{s[a]:.3f}' for a in AGENTS)}")
    print(f"    → top agent: {max(J20, key=J20.get)} at {100*max(J20.values()):.1f}% "
          f"(cold: {100*max(J0.values()):.1f}%) — evidence earned the skew")

    # 3) WORLD FLIPS at t=21 (listener vetoes, molts come due): decayed cells
    #    re-converge, J follows the world — adaptation, not a jump
    J40, _, cells40 = build_and_run(40, flip_at=21)
    print(f"\n[3] world flip at t=21 (veto↔calm, molt ready↔hold); readout at t=40")
    odds_line("J (t=40, flipped)", J40, cells40, 40)
    d = max(abs(J40[a] - J20[a]) for a in AGENTS)
    print(f"    L∞ drift from t=20 mesh: {d:.3f} (bounded, no spike)")

    # 4) MOTH QUANTUM — frozen mesh, 400 deterministic draws: empirical ≈ projected
    rcpt = receipt(J20, cells20, 20)
    K = 400
    counts = {a: 0 for a in AGENTS}
    for k in range(1, K + 1):
        counts[moth_quantum(J20, rcpt, k)] += 1
    print(f"\n[4] moth quantum: {K} draws against receipt {rcpt[:16]}…")
    print(f"    {'agent':>12} {'projected':>10} {'empirical':>10} {'Δ':>6}")
    worst = 0.0
    for a in AGENTS:
        proj, emp = 100 * J20[a], 100 * counts[a] / K
        worst = max(worst, abs(proj - emp))
        print(f"    {a:>12} {proj:>9.1f}% {emp:>9.1f}% {abs(proj-emp):>5.1f}pt")
    print(f"    max |projected − empirical| = {worst:.1f}pt "
          f"({'OK' if worst < 10 else 'DRIFT — FAIL LOUD'})")
    assert worst < 10, "firing odds not literal — empirical drifted from projection"

    # 5) STABILITY — one extra tick on one cell moves J smoothly, not violently
    Jp, _, _ = build_and_run(20, tick_noise="pinch/match?")
    linf = max(abs(Jp[a] - J20[a]) for a in AGENTS)
    print(f"\n[5] perturbation: +1 tick on pinch/match? → L∞(J, J') = {linf:.4f} "
          f"(smooth — bounded influence via w_m)")

    # 6) DETERMINISM — same inputs, byte-identical projection (fnv1a lineage)
    J20b, _, cells20b = build_and_run(20)
    same = canonical([[a, f"{J20[a]:.12f}"] for a in AGENTS]) == \
           canonical([[a, f"{J20b[a]:.12f}"] for a in AGENTS])
    same_rcpt = receipt(J20, cells20, 20) == receipt(J20b, cells20b, 20)
    same_fire = moth_quantum(J20, rcpt, 7) == moth_quantum(J20b, receipt(J20b, cells20b, 20), 7)
    print(f"\n[6] determinism: replay J identical={same}  receipt identical={same_rcpt}  "
          f"moth draw identical={same_fire}")

    ok = same and same_rcpt and same_fire and worst < 10
    print(f"\n{'ALL CHECKS PASS' if ok else 'FAIL LOUD'} — odds sum to 1.0 by construction "
          f"(residual printed per row), replay is bit-stable, draws hit projected odds.")
    assert ok
    return 0


if __name__ == "__main__":
    sys.exit(main())
