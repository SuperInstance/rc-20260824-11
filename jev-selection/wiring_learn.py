#!/usr/bin/env python3
"""jev-selection/wiring_learn.py — Swarm Lane J2: learn the wiring from the loop.

J1 hand-wrote W_m (answer -> row over agents) and proved the mesh. J2 removes
the hand: each wiring row is a Dirichlet posterior over a |answers|x|agents|
contingency table, updated by the selection-outcome loop itself —

    tick t:  cells observe the world            (fnv1a draws — no RNG)
             Jhat = mesh(cells, learned rows)   (J1 mechanism, math unchanged)
             moth quantum fires one agent       (recorded collapse)
             outcome: the TRUE correct agent g(z_t) is revealed
             every cell's table counts (its answer y_m, the correct agent)

    W_m(y)[a] = (c[y][a] + alpha) / (sum_a' c[y][a'] + N*alpha)
    update:   decay all counts by lam, land the observation   (Lane-1 mechanism)

World: hidden state z_t in {0,1,2}; cell m observes z through its own
confusion matrix (cells differ in informativeness); the correct agent is
g(z). The Bayes-optimal wiring row*(y) = P(g(z)=a | y_m=y) is closed-form
from the confusion matrix — it gives both the ceiling (J_ideal mesh) and the
convergence target. Quality = argmax(Jhat) == g(z_t). A frozen random-start
wiring runs as the no-learning baseline.

Run: python3 jev-selection/wiring_learn.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cell-internals"))
from poc import Cell, canonical, fnv1a, sha  # noqa: E402

AGENTS = ("AG-SENSE", "AG-PINCH", "AG-RELAY", "AG-MOLT", "AG-COMPRESS")
N = len(AGENTS)
K = 3                                   # answers per cell = hidden states
EPS, N0 = 1e-9, 8.0                     # doubt floor + cell-confidence prior (J1)
ALPHA_W, LAM_W = 0.25, 0.99             # wiring posterior: Dirichlet prior, decay
TICKS, WINDOW = 100, 20

CELL_SPECS = (("relay/load?", 0.80), ("pinch/grip?", 0.70), ("molt/stage?", 0.55))
G = ("AG-PINCH", "AG-RELAY", "AG-MOLT")     # hidden law: state -> correct agent


# ── the world: hidden state, noisy observations, true correct agent ─────────
def hidden_state(t: int) -> int:
    return fnv1a(f"state:{t}") % K


def observe(m: int, z: int, t: int) -> int:
    """Cell m observes state z through its confusion matrix (fnv1a draw)."""
    main = CELL_SPECS[m][1]
    probs = [main if i == z else (1.0 - main) / (K - 1) for i in range(K)]
    bit = fnv1a(f"{CELL_SPECS[m][0]}:{t}") % 10000 / 10000.0
    acc = 0.0
    for i, p in enumerate(probs):
        acc += p
        if bit < acc:
            return i
    return K - 1


def ideal_rows(m: int) -> list:
    """Bayes wiring, closed form: row*(y)[a] = P(g(z)=a | y_m=y)."""
    main = CELL_SPECS[m][1]
    rows = []
    for y in range(K):
        row = [0.0] * N
        for z in range(K):
            py = main if z == y else (1.0 - main) / (K - 1)
            row[AGENTS.index(G[z])] += py / K          # uniform state prior
        tot = sum(row)
        rows.append([v / tot for v in row])
    return rows


# ── the learned wiring: |answers|x|agents| contingency tables ───────────────
class Wiring:
    """Dirichlet posterior per row over "given answer y, who was correct".
    Same update mechanism as a Lane-1 cell: decay all counts, land the
    observation, project the posterior mean on demand. Starts 'random':
    fnv1a noise pseudo-counts (deterministic, replay-stable, uninformative)."""

    def __init__(self, question: str, seed: str):
        self.question = question
        self.counts = [[(fnv1a(f"{seed}:{y}:{a}") % 100 + 1) / 100.0
                        for a in range(N)] for y in range(K)]
        self.n = 0

    def tick(self, y: int, agent: str) -> None:
        self.counts = [[c * LAM_W for c in row] for row in self.counts]
        self.counts[y][AGENTS.index(agent)] += 1.0
        self.n += 1

    def row(self, y: int) -> list:
        tot = sum(self.counts[y]) + ALPHA_W * N
        return [(c + ALPHA_W) / tot for c in self.counts[y]]


class FrozenWiring(Wiring):
    """The random start, never taught — the no-learning baseline."""

    def tick(self, y: int, agent: str) -> None:
        raise AssertionError("baseline wiring must never learn")


class IdealWiring:
    """The Bayes-optimal rows — what the loop is trying to earn."""

    def __init__(self, rows: list):
        self.rows = rows

    def row(self, y: int) -> list:
        return self.rows[y]


# ── the mesh (J1, math unchanged) + the moth quantum ────────────────────────
def mesh(cells: list, wirings: list) -> list:
    logs = [0.0] * N
    for cell, wr in zip(cells, wirings):
        p = cell.dist()
        s = [0.0] * N
        for y, name in enumerate(cell.answers):
            py, row = p[name], wr.row(y)
            for i in range(N):
                s[i] += py * row[i]
        w = cell.n_eff() / (cell.n_eff() + N0)
        for i in range(N):
            logs[i] += w * math.log((s[i] + EPS) / (1.0 + N * EPS))
    top = max(logs)
    e = [math.exp(v - top) for v in logs]
    J = [v / sum(e) for v in e]
    assert abs(sum(J) - 1.0) < 1e-12, f"J off simplex: |sum-1|={abs(sum(J) - 1.0)}"
    return J


def receipt(J: list, cells: list, t: int, tag: str) -> str:
    return sha(canonical([[c.head for c in cells], t, [f"{v:.9f}" for v in J], tag]))


def moth(J: list, rcpt: str, k: int) -> str:
    u = (fnv1a(canonical([rcpt, k])) & 0xFFFFFFFF) / 2**32
    acc = 0.0
    for i, a in enumerate(AGENTS):
        acc += J[i]
        if u < acc:
            return a
    return AGENTS[-1]


def linf(u: list, v: list) -> float:
    return max(abs(a - b) for a, b in zip(u, v))


# ── one run of the selection-outcome loop ───────────────────────────────────
def experiment(update: bool, tag: str):
    cells = [Cell(q, tuple(f"y{i}" for i in range(K)), alpha=0.5, lam=0.60)
             for q, _ in CELL_SPECS]
    learned = [Wiring(q, f"j2init:{q}") for q, _ in CELL_SPECS]
    ideals = [IdealWiring(ideal_rows(m)) for m in range(len(CELL_SPECS))]
    trace = []
    for t in range(1, TICKS + 1):
        z, obs = hidden_state(t), []
        for m in range(len(CELL_SPECS)):
            y = observe(m, z, t)
            cells[m].tick(f"y{y}")
            obs.append(y)
        J_hat, J_id = mesh(cells, learned), mesh(cells, ideals)
        fired = moth(J_hat, receipt(J_hat, cells, t, f"{tag}:fire"), t)
        correct = G[z]
        top = AGENTS[max(range(N), key=lambda i: J_hat[i])]
        trace.append({
            "t": t, "correct": correct, "fired": fired, "top": top, "J": J_hat,
            "ok": top == correct, "fired_ok": fired == correct,
            "ok_ideal": AGENTS[max(range(N), key=lambda i: J_id[i])] == correct,
            "err": linf(J_hat, J_id),
        })
        if update:
            for m in range(len(CELL_SPECS)):
                learned[m].tick(obs[m], correct)
    for c in cells:
        assert c.verify_chain(), f"cell chain failed: {c.question}"
    return trace, learned, ideals


def window(trace: list, key: str, t_end: int) -> float:
    seg = [r[key] for r in trace[max(0, t_end - WINDOW):t_end]]
    return sum(seg) / max(len(seg), 1)


def pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def main() -> int:
    print("=" * 78)
    print("jev-selection J2 — wiring learned from the selection-outcome loop")
    print(f"N={N} agents, M={len(CELL_SPECS)} cells (|answers|={K}), {TICKS} ticks, "
          f"row = Dirichlet posterior (alpha={ALPHA_W}, lam={LAM_W})")
    print("=" * 78)

    trace, learned, ideals = experiment(update=True, tag="A")
    trace2, _, _ = experiment(update=True, tag="A")            # determinism replay
    base, _, _ = experiment(update=False, tag="base")          # never taught

    def payload(tr):
        return [[r["t"], r["correct"], r["fired"], r["top"],
                 [f"{v:.12f}" for v in r["J"]], f"{r['err']:.12f}"] for r in tr]
    det = canonical(payload(trace)) == canonical(payload(trace2))

    ceil_final = window(trace, "ok_ideal", TICKS)
    learn_win, base_win = window(trace, "ok", TICKS), window(base, "ok", TICKS)
    err_final = sum(r["err"] for r in trace[-WINDOW:]) / WINDOW
    conv = next((t for t in range(1, TICKS + 1)
                 if window(trace, "ok", t) >= 0.9 * ceil_final), None)
    doubt = min(trace[-1]["J"])
    cum = lambda tr, key: sum(r[key] for r in tr) / len(tr)   # noqa: E731
    mass = sum(r["J"][AGENTS.index(r["correct"])] for r in trace) / TICKS

    print(f"\nconvergence trace (window={WINDOW} trailing ticks)")
    print(f"  {'t':>4}  {'correct':<8} {'top(Jhat)':<8} {'ok':<5} {'firedok':<7} "
          f"{'learned':>7} {'ceiling':>7} {'Linf err':>8}")
    for r in trace:
        if r["t"] == 1 or r["t"] % 10 == 0:
            print(f"  {r['t']:>4}  {r['correct'].replace('AG-',''):<8} "
                  f"{r['top'].replace('AG-',''):<8} {str(r['ok']):<5} "
                  f"{str(r['fired_ok']):<7} {pct(window(trace, 'ok', r['t']))} "
                  f"{pct(window(trace, 'ok_ideal', r['t']))} {r['err']:>8.4f}")

    print("\nlearned vs ideal rows — cell 'relay/load?': P(correct agent | answer)")
    for y in range(K):
        lr = " ".join(f"{a.replace('AG-','')[:4]}={v:.2f}" for a, v in zip(AGENTS, learned[0].row(y)))
        ir = " ".join(f"{a.replace('AG-','')[:4]}={v:.2f}" for a, v in zip(AGENTS, ideals[0].row(y)))
        print(f"  y{y}  learned {lr}")
        print(f"      ideal   {ir}")

    print("\nsummary")
    print(f"  selection quality (argmax Jhat == correct), last {WINDOW} ticks:")
    print(f"    frozen random wiring (baseline) : {pct(base_win)}")
    print(f"    learned wiring                  : {pct(learn_win)}")
    print(f"    ceiling (Bayes ideal wiring)    : {pct(ceil_final)}")
    cum_fired = cum(trace, "fired_ok")
    print(f"  fired-agent quality (moth draw)   : {pct(window(trace, 'fired_ok', TICKS))}"
          f" window, {pct(cum_fired)} cumulative")
    print(f"    cumulative over all {TICKS} ticks       : baseline {pct(cum(base, 'ok'))}, "
          f"learned {pct(cum(trace, 'ok'))}, ceiling {pct(cum(trace, 'ok_ideal'))}")
    freq = {a: sum(r["fired"] == a for r in trace) / TICKS for a in AGENTS}
    mmass = {a: sum(r["J"][i] for r in trace) / TICKS for i, a in enumerate(AGENTS)}
    drift = max(abs(freq[a] - mmass[a]) for a in AGENTS)
    print(f"    moth draws sample the odds: P(fired=correct)={100 * cum_fired:.1f}% vs mean "
          f"Jhat mass on correct={100 * mass:.1f}% (soft evidence); "
          f"literal-odds drift max_a|freq-mass| = {drift:.4f}")
    print(f"  mesh convergence: mean Linf(Jhat, J_ideal) last {WINDOW} = {err_final:.4f}")
    print(f"  convergence speed: 90% of ceiling at t = {conv if conv else f'never (>{TICKS})'}")
    print(f"  doubt stamped: floor odds of never-correct agents = {100 * doubt:.3f}% (> 0)")
    print(f"  determinism: two full runs byte-identical = {det}")

    ok = (det
          and learn_win > base_win + 0.15          # learning beats no-learning
          and learn_win >= 0.85 * ceil_final       # learned reaches the Bayes mesh
          and err_final < 0.20                     # Jhat converged onto J_ideal
          and drift < 0.05                         # percentages stay literal (J1 law)
          and doubt > 0.0)                         # doubt floor never collapsed
    print(f"\n{'ALL CHECKS PASS' if ok else 'FAIL LOUD'} — "
          f"wiring is learned from outcomes, not hand-written.")
    assert ok
    return 0


if __name__ == "__main__":
    sys.exit(main())
