#!/usr/bin/env python3
"""cell-internals POC — ticks-as-probabilities, the minimal cell.

A cell records ticks (observed answers to its one question), keeps decayed
pseudo-counts, and projects a Dirichlet-posterior-mean distribution on demand.
Gates fire on the one-sided 95% lower bound, so thresholds tighten as
1/sqrt(N_eff) — reflex formation in its minimal form.

NO RNG: tick streams are derived deterministically from fnv1a(content) —
all entropy is content-derived (exoj law). Stdlib only.

Run: python3 cell-internals/poc.py
"""

import hashlib
import json
import math

GENESIS = "CELL-GENESIS"
Z95 = 1.6449  # one-sided 95% z-score


def fnv1a(s: str) -> int:
    """fnv-1a 32-bit — the deterministic entropy substitute (exoj gan/unitTable)."""
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def canonical(value) -> str:
    """Canonical JSON (sorted keys, no whitespace) — exoj core.mjs law."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Cell:
    """Minimal cell: one question, decayed pseudo-counts, hash-chained tick ledger."""

    def __init__(self, question: str, answers: tuple, alpha: float = 0.5, lam: float = 1.0):
        self.question = question
        self.answers = tuple(answers)
        self.alpha = alpha
        self.lam = lam
        self.counts = [0.0] * len(self.answers)
        self.n = 0
        self.head = sha(GENESIS)
        self.ledger = []  # (n, answer, row_hash) — replayable proof

    def tick(self, answer: str) -> None:
        """One observed answer: decay all counts, land the tick, chain the proof."""
        self.counts = [c * self.lam for c in self.counts]
        self.counts[self.answers.index(answer)] += 1.0
        self.n += 1
        row = sha(canonical([self.head, self.n, answer]))
        self.ledger.append((self.n, answer, row))
        self.head = row

    # ---- projections (pure; never mutate the ledger) ----

    def dist(self) -> dict:
        """Dirichlet posterior mean over answers."""
        total = sum(self.counts) + self.alpha * len(self.answers)
        return {a: (c + self.alpha) / total for a, c in zip(self.answers, self.counts)}

    def n_eff(self) -> float:
        """Effective sample size of the decayed ledger."""
        return sum(self.counts)

    def lower_bound(self, answer: str, z: float = Z95) -> float:
        """One-sided 95% posterior lower bound (Dirichlet variance, normal approx)."""
        p = self.dist()[answer]
        a = self.counts[self.answers.index(answer)] + self.alpha
        a0 = sum(self.counts) + self.alpha * len(self.answers)
        var = a * (a0 - a) / (a0 * a0 * (a0 + 1.0))
        return p - z * math.sqrt(max(var, 0.0))

    def gate(self, answer: str, fire: float) -> tuple:
        """Gate: fires iff LB(answer) >= fire. Returns (fired, lb, margin)."""
        lb = self.lower_bound(answer)
        return lb >= fire, lb, self.dist()[answer] - lb

    def verify_chain(self) -> bool:
        """Replay the ledger, re-derive every row hash. NO VERIFIED SHA, NO BELIEF."""
        head = sha(GENESIS)
        for n, answer, row in self.ledger:
            expect = sha(canonical([head, n, answer]))
            if expect != row:
                return False
            head = row
        return head == self.head


def world_rate(question: str, t: int, flip_at: int | None = None) -> float:
    """Deterministic 'world': the true rate for each question, per tick.
    Cell 1's world flips at flip_at to demonstrate decay adaptation."""
    base = {"relay/alive?": 0.8, "pinch/match?": 0.65, "listener/veto?": 0.2}[question]
    if flip_at is not None and t >= flip_at:
        base = 1.0 - base
    return base


def world_answer(question: str, answers: tuple, t: int, flip_at: int | None = None) -> str:
    """Draw answer t deterministically: fnv1a(question:t) vs the world rate.
    No RNG module — content-derived bits only."""
    bit = fnv1a(f"{question}:{t}") % 10000 / 10000.0
    return answers[0] if bit < world_rate(question, t, flip_at) else answers[1]


def run_cell(question, answers, ticks=16, lam=1.0, flip_at=None, fire=0.5, watch=None):
    watch = watch or answers[0]
    cell = Cell(question, answers, alpha=0.5, lam=lam)
    print(f"\n── cell '{question}'  answers={answers}  lam={lam}  gate: LB({watch!r})>={fire}")
    print(f"   {'n':>2}  {'tick':>5}  {'p(watch)':>8}  {'LB95':>7}  {'N_eff':>6}  gate")
    fired = []
    for t in range(1, ticks + 1):
        a = world_answer(question, answers, t, flip_at)
        cell.tick(a)
        p, lb, ne = cell.dist()[watch], cell.lower_bound(watch), cell.n_eff()
        ok, _, _ = cell.gate(watch, fire)
        fired.append(ok)
        mark = "FIRE" if ok else "hold"
        print(f"   {cell.n:>2}  {a:>5}  {p:>8.3f}  {lb:>7.3f}  {ne:>6.1f}  {mark}")
    true = world_rate(question, ticks, flip_at)
    print(f"   → final p(watch)={cell.dist()[watch]:.3f}  (world rate now {true:.2f})  "
          f"chain verified: {cell.verify_chain()}")
    return cell


def main():
    print("=" * 72)
    print("cell-internals POC — ticks → decayed counts → Dirichlet mean → gated fire")
    print("=" * 72)

    # Cell 1: stationary world, no decay — clean convergence + gate tightening.
    c1 = run_cell("relay/alive?", ("yes", "no"), ticks=16, lam=1.0, fire=0.5, watch="yes")

    # Cell 2: stationary world, decay — bounded-memory convergence.
    c2 = run_cell("pinch/match?", ("hit", "miss"), ticks=16, lam=0.85, fire=0.4, watch="hit")

    # Cell 3: WORLD FLIPS at tick 9 — lam=1.0 frozen vs lam=0.60 adapts.
    c3 = run_cell("listener/veto?", ("veto", "calm"), ticks=16, lam=1.0,
                  flip_at=9, fire=0.3, watch="veto")
    c4 = run_cell("listener/veto?", ("veto", "calm"), ticks=16, lam=0.60,
                  flip_at=9, fire=0.3, watch="veto")

    print("\n── reflex formation (threshold tightening) for cell 1")
    for t in (1, 4, 8, 16):
        c = Cell("relay/alive?", ("yes", "no"))
        for i in range(1, t + 1):
            c.tick(world_answer("relay/alive?", ("yes", "no"), i))
        print(f"   after {t:>2} ticks: p={c.dist()['yes']:.3f}  "
              f"uncertainty margin p−LB = {c.dist()['yes'] - c.lower_bound('yes'):.3f}")

    print("\n── ledger is the belief: chain heads")
    for c in (c1, c2, c3, c4):
        assert c.verify_chain(), f"chain FAILED for {c.question}"
        print(f"   {c.question:<16} lam={c.lam:<4} n={c.n:>2}  head={c.head[:16]}…  VERIFIED")

    print("\nAll chains verified. Cells converge, adapt, and gates tighten from evidence.")


if __name__ == "__main__":
    main()
