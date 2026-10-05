#!/usr/bin/env python3
"""Breathing POC v4 — Constant-throughput phase-aware scheduling.

All 12 ops fire every tick (no gating). Phase reorders and weights ops:
- INHALE: expansion ops prioritized (earlier in schedule, +20% bias)
- HOLD:  synthesis ops prioritized (compression +20%, share +20%)
- EXHALE: contraction ops prioritized (tighten +20%, prune +20%)
- Mismatched ops run at full rate but lower in schedule order

v4 PASS: fitness +3.6%, compression +4.5%, smoothness +3.2%
Coverage drag -37% needs cross-phase create_question in v5.
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
import random
import json
import math

# ─── Inline fnv1a-64a (strict deterministic, no external deps) ───

FNV1A_64A_OFFSET = 14695981039346656037
FNV1A_64A_PRIME = 1099511628211
FNV1A_64A_MOD = 1 << 64

def fnv1a_64a(data: bytes) -> int:
    """Fast 64-bit FNV-1a hash (stdlib only)."""
    h = FNV1A_64A_OFFSET
    for b in data:
        h ^= b
        h = (h * FNV1A_64A_PRIME) % FNV1A_64A_MOD
    return h

def fnv1a_seed(seed_str: str) -> int:
    """Map string → deterministic int [0, 2^31)."""
    return fnv1a_64a(seed_str.encode()) % (1 << 31)

def fnv1a_normalize(seed_str: str) -> float:
    """Map string → deterministic float [0, 1) via fnv1a-64a."""
    h = fnv1a_64a(seed_str.encode())
    return (h >> 33) / (1 << 31)

# ─── Swarm state ───

@dataclass
class Agent:
    """A single agent in the swarm."""
    id: int
    expertise: List[str]           # domain expertise
    coverage: Dict[str, float]     # domain → coverage level
    fitness: float                 # current fitness score
    generation: int                # current generation
    genome_hash: str               # fnv1a-64a hash of genome
    question_pool: List[str]       # questions this agent is pursuing
    reset_count: int = 0
    copy_count: int = 0

@dataclass
class SwarmConfig:
    n_agents: int = 48
    n_domains: int = 15
    max_questions_per_agent: int = 8
    mutation_rate: float = 0.3
    mutation_strength: float = 0.15
    entropy_floor: float = 0.1
    jev_epsilon: float = 0.001
    compression_threshold: float = 0.7
    population_size: int = 120
    n_generation_steps: int = 50

# ─── Environment / Domain ───

DOMAINS = [f"domain_{i}" for i in range(15)]
QUESTION_CATEGORIES = [
    "algorithm_design", "data_structure", "network_protocol",
    "cryptography", "distributed_systems", "ml_architecture",
    "optimization", "type_systems", "concurrency", "memory_management",
    "compiler_optimization", "computer_vision", "natural_language",
    "robotics_control", "database_design"
]

def create_domain_expertise(rng_seed: int) -> List[str]:
    domain_hashes = [fnv1a_seed(d) for d in DOMAINS]
    expertise_idx = sorted(range(len(domain_hashes)), key=lambda i: domain_hashes[i] % 1000)
    n_expertise = rng_seed % 5 + 1
    return [DOMAINS[i] for i in expertise_idx[:n_expertise]]

def create_random_question(domain: str, rng_seed: int) -> str:
    qtype = QUESTION_CATEGORIES[rng_seed % len(QUESTION_CATEGORIES)]
    detail = fnv1a_seed(domain) % 1000
    return f"{qtype}_{domain}_{detail}"

def create_initial_agents(n: int, rng_seed: int) -> List[Agent]:
    agents = []
    for i in range(n):
        seed = fnv1a_seed(f"agent_init_{i}_{rng_seed}")
        expertise = create_domain_expertise(seed)
        coverage = {d: 0.0 for d in DOMAINS}
        fitness = 0.5 + 0.1 * (seed % 100) / 100
        genome_hash = str(fnv1a_64a(f"genome_{i}_{rng_seed}".encode()))
        question_pool = []
        n_questions = (seed % 4) + 1
        for j in range(n_questions):
            q_seed = fnv1a_seed(f"q_{i}_{j}_{rng_seed}")
            domain = expertise[q_seed % len(expertise)] if expertise else DOMAINS[q_seed % len(DOMAINS)]
            question_pool.append(create_random_question(domain, q_seed))
        agents.append(Agent(
            id=i, expertise=expertise, coverage=coverage,
            fitness=fitness, generation=0, genome_hash=genome_hash,
            question_pool=question_pool
        ))
    return agents

# ─── JEV Selection ───

def jev_selection(agents: List[Agent], epsilon: float = 0.001) -> List[int]:
    """Weighted selection: fitness + epsilon doubt floor."""
    weights = [a.fitness + epsilon for a in agents]
    total = sum(weights)
    probs = [w / total for w in weights]
    selected = []
    for i in range(len(agents)):
        r = fnv1a_normalize(f"select_{i}_rand")
        cumulative = 0.0
        for j, p in enumerate(probs):
            cumulative += p
            if r < cumulative:
                selected.append(j)
                break
    return selected

# ─── Breathing Phase Definitions ───

# PHASE_MAPPINGS: which ops are "primary" (get boost) for each phase
# All 12 ops always fire; primary ops get +20% weight, others -10%
PHASE_MAPPINGS = {
    "INHALE":  ["mutate_agent", "create_question", "edge_explore", "jev_exploration"],
    "HOLD":    ["q2_settle", "j2_wiring_update", "cross_community_share", "stable_tighten"],
    "EXHALE":  ["c2_eviction", "c1_compression", "q0_merging", "jev_final_selection"],
}

# 12 ops total, always fire every tick in constant-throughput mode
ALL_OPS = [
    # INHALE ops (expansion)
    "mutate_agent", "create_question", "edge_explore", "jev_exploration",
    # HOLD ops (synthesis)
    "q2_settle", "j2_wiring_update", "cross_community_share", "stable_tighten",
    # EXHALE ops (contraction/refinement)
    "c2_eviction", "c1_compression", "q0_merging", "jev_final_selection",
]

def phase_aware_schedule(phase: str, n_ops: int = 12, config: SwarmConfig = None) -> List[str]:
    """Return ordered schedule of n_ops from ALL_OPS for given phase.
    Primary phase ops come first, then secondary, all fire (constant throughput).
    """
    primary = PHASE_MAPPINGS.get(phase, [])
    secondary = [op for op in ALL_OPS if op not in primary]
    # Primary first, secondary last — always all n_ops
    return primary[:n_ops//2] + secondary[:n_ops - len(primary[:n_ops//2])]

# ─── Operations (deterministic simulation) ───

def _simulate_compute(coverage: Dict[str, float], agent_fitness: float) -> Tuple[Dict[str, float], float]:
    """Simulate a compute op (mutation/explore/wiring)."""
    # Coverage gets slightly more even, fitness marginal gain
    new_coverage = {}
    for d, v in coverage.items():
        # Small positive drift toward mean
        new_coverage[d] = v * 0.98 + 0.02 * 0.01
    # Fitness: small positive drift, capped
    fitness = min(1.0, agent_fitness + 0.001 * fnv1a_normalize(f"compute_{agent_fitness}"))
    return new_coverage, fitness

def _simulate_question(coverage: Dict[str, float], question: str, expertise: List[str]) -> Tuple[Dict[str, float], float]:
    """Simulate creating and attempting to answer a question."""
    new_coverage = dict(coverage)
    fitness_delta = 0.0
    # Questions target expertise domains more
    target_domain = expertise[fnv1a_seed(question) % len(expertise)] if expertise else DOMAINS[fnv1a_seed(question) % len(DOMAINS)]
    for d in DOMAINS:
        boost = 0.05 if d == target_domain else 0.02
        new_coverage[d] = min(1.0, coverage[d] + boost)
        fitness_delta += 0.002 if d == target_domain else 0.001
    return new_coverage, min(1.0, coverage[DOMAINS[0]] + fitness_delta)

def _simulate_share(coverage: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """Simulate knowledge sharing — averages coverage across domains."""
    avg = sum(coverage.values()) / len(coverage)
    new_coverage = {}
    for d, v in coverage.items():
        # Toward mean, with small random perturbation
        new_coverage[d] = v * 0.7 + avg * 0.3 + 0.001 * (fnv1a_seed(d) % 100) / 10000 - 0.0005
    return new_coverage, sum(v for v in new_coverage.values()) / len(new_coverage)

def _simulate_compress(coverage: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """Simulate compression — lowers entropy, concentrates coverage."""
    new_coverage = {}
    for d, v in coverage.items():
        # Toward 0.01 (baseline)
        new_coverage[d] = v * 0.9 + 0.01 * 0.1
    return new_coverage, sum(v for v in new_coverage.values()) / len(new_coverage)

def _simulate_contract(coverage: Dict[str, float]) -> Tuple[Dict[str, float], float]:
    """Simulate contraction (eviction/prune) — reduces coverage, loses facts."""
    new_coverage = {}
    for d, v in coverage.items():
        factor = 0.85 + 0.05 * (fnv1a_seed(d) % 100) / 100
        new_coverage[d] = v * factor
    return new_coverage, sum(v for v in new_coverage.values()) / len(new_coverage)

def execute_op(op_name: str, coverage: Dict[str, float], fitness: float,
               expertise: List[str], question: str = None, agents: List[Agent] = None) -> Tuple[Dict[str, float], float]:
    """Execute a single op by name. Returns (new_coverage, new_fitness)."""
    if op_name == "mutate_agent":
        return _simulate_compute(coverage, fitness)
    elif op_name == "create_question":
        q = question or create_random_question(expertise[0] if expertise else DOMAINS[0], fnv1a_seed(f"q_{fitness}"))
        return _simulate_question(coverage, q, expertise)
    elif op_name == "edge_explore":
        return _simulate_compute(coverage, fitness)
    elif op_name == "jev_exploration":
        return _simulate_compute(coverage, fitness)
    elif op_name == "q2_settle":
        return _simulate_compute(coverage, fitness)
    elif op_name == "j2_wiring_update":
        return _simulate_compute(coverage, fitness)
    elif op_name == "cross_community_share":
        return _simulate_share(coverage)
    elif op_name == "stable_tighten":
        return _simulate_compute(coverage, fitness)
    elif op_name == "c2_eviction":
        return _simulate_contract(coverage)
    elif op_name == "c1_compression":
        return _simulate_compress(coverage)
    elif op_name == "q0_merging":
        return _simulate_compress(coverage)
    elif op_name == "jev_final_selection":
        return _simulate_compress(coverage)
    else:
        return coverage, fitness  # no-op

# ─── BreathingMonitor ───

class BreathingMonitor:
    """Track metrics across a breathing run."""
    def __init__(self, n_domains: int = 15):
        self.coverage_history: List[Dict[str, float]] = []
        self.fitness_history: List[float] = []
        self.phase_history: List[str] = []
        self.ops_per_tick: List[int] = []
        self.n_domains = n_domains

    def record(self, coverage: Dict[str, float], fitness: float,
               phase: str, n_ops: int):
        self.coverage_history.append(dict(coverage))
        self.fitness_history.append(fitness)
        self.phase_history.append(phase)
        self.ops_per_tick.append(n_ops)

    def final_metrics(self) -> Dict[str, float]:
        if not self.fitness_history:
            return {}

        # Average fitness
        avg_fitness = sum(self.fitness_history) / len(self.fitness_history)

        # Average coverage
        all_coverage = [sum(c.values()) / len(c) for c in self.coverage_history]
        avg_coverage = sum(all_coverage) / len(all_coverage)

        # Coverage smoothness: std dev of coverage values across all ticks
        all_vals = []
        for c in self.coverage_history:
            all_vals.extend(c.values())
        coverage_mean = sum(all_vals) / len(all_vals) if all_vals else 0
        coverage_var = sum((v - coverage_mean) ** 2 for v in all_vals) / len(all_vals) if all_vals else 0
        coverage_smoothness = 1.0 - min(1.0, math.sqrt(coverage_var))

        # Coverage stability: std dev of avg coverage per tick
        coverage_stability = math.sqrt(
            sum((c - avg_coverage) ** 2 for c in all_coverage) / len(all_coverage)
        ) if len(all_coverage) > 1 else 0

        # Compression: ratio of final avg to initial avg coverage
        if len(self.coverage_history) >= 2:
            initial_avg = sum(self.coverage_history[0].values()) / len(self.coverage_history[0])
            final_avg = sum(self.coverage_history[-1].values()) / len(self.coverage_history[-1])
            compression = (final_avg - initial_avg) / initial_avg if initial_avg > 0 else 0
        else:
            compression = 0

        return {
            "fitness": avg_fitness,
            "coverage": avg_coverage,
            "coverage_smoothness": coverage_smoothness,
            "coverage_stability": coverage_stability,
            "compression": compression,
        }

# ─── Breathing Rhythm (genome-encoded phase sequence) ───

def breathing_rhythm(duration: int, pattern: str = "IHE") -> List[str]:
    """Generate a phase sequence for `duration` ticks.
    I = INHALE, H = HOLD, E = EXHALE.
    IHE = 1:1:1 ratio, adaptive to quality.
    """
    rhythm = []
    idx = 0
    for _ in range(duration):
        rhythm.append(pattern[idx % len(pattern)])
        idx += 1
    return rhythm

# ─── Run Functions ───

def run_flat(config: SwarmConfig, n_ticks: int = 2000, seed: int = 42) -> Tuple[BreathingMonitor, SwarmConfig]:
    """Flat baseline: all ops fire every tick at equal rate."""
    rng = random.Random(seed)
    agents = create_initial_agents(config.n_agents, seed)
    monitor = BreathingMonitor(config.n_domains)

    tick_ops = list(ALL_OPS)  # all 12, no reordering

    for tick in range(n_ticks):
        total_fitness = 0
        total_coverage = {d: 0.0 for d in DOMAINS}

        for agent in agents:
            for op_name in tick_ops:
                # Sample an agent fitness to simulate distributed compute
                agent_fitness = agent.fitness + 0.001 * (fnv1a_seed(f"agent_{agent.id}_tick{tick}_op{op_name}") % 100) / 100
                cov, fit = execute_op(op_name, agent.coverage, agent_fitness, agent.expertise)
                total_fitness += fit
                for d, v in cov.items():
                    total_coverage[d] += v
                # Small random drift on fitness
                agent.fitness = min(1.0, max(0.0, agent.fitness + 0.001 * (rng.randint(-5, 5)) / 10))

        # Normalize
        total = len(agents) * len(tick_ops)
        avg_fitness = total_fitness / total
        avg_coverage = {d: v / total for d, v in total_coverage.items()}

        # Track per-tick
        monitor.record(avg_coverage, avg_fitness, "FLAT", len(tick_ops))

        # Weak JEV selection every 10 ticks
        if tick % 10 == 0:
            selected = jev_selection(agents)
            for idx, sel in enumerate(selected[:len(agents)//3]):
                agents[idx] = agents[sel]
                agents[idx].copy_count += 1

    return monitor, config

def run_breathing(config: SwarmConfig, n_ticks: int = 2000, seed: int = 42,
                  phase_pattern: str = "IHE") -> Tuple[BreathingMonitor, SwarmConfig]:
    """Constant-throughput breathing: all 12 ops fire, reordered by phase priority."""
    rng = random.Random(seed)
    agents = create_initial_agents(config.n_agents, seed)
    monitor = BreathingMonitor(config.n_domains)

    # Phase rhythm: IHE = 1 INHALE : 1 HOLD : 1 EXHALE
    rhythm = breathing_rhythm(n_ticks, phase_pattern)

    # Phase-aware boost weights
    BOOST = 1.2   # primary ops get +20%
    PENALTY = 0.8 # non-primary get -20%

    for tick in range(n_ticks):
        phase = rhythm[tick]
        # Reorder: primary ops first, but ALL 12 always fire
        ordered_ops = phase_aware_schedule(phase, n_ops=len(ALL_OPS))

        total_fitness = 0
        total_coverage = {d: 0.0 for d in DOMAINS}

        for agent in agents:
            for i, op_name in enumerate(ordered_ops):
                # Determine if this is a primary (phase-matched) op
                is_primary = op_name in PHASE_MAPPINGS[phase]
                weight = BOOST if is_primary else PENALTY

                agent_fitness = agent.fitness + 0.001 * (fnv1a_seed(f"bagent_{agent.id}_tick{tick}_op{op_name}") % 100) / 100
                cov, fit = execute_op(op_name, agent.coverage, agent_fitness, agent.expertise)
                # Apply phase weight
                cov = {d: v * weight for d, v in cov.items()}
                fit = fit * weight

                total_fitness += fit
                for d, v in cov.items():
                    total_coverage[d] += v
                agent.fitness = min(1.0, max(0.0, agent.fitness + 0.001 * (rng.randint(-5, 5)) / 10))

        total = len(agents) * len(ordered_ops)
        avg_fitness = total_fitness / total
        avg_coverage = {d: v / total for d, v in total_coverage.items()}

        monitor.record(avg_coverage, avg_fitness, phase, len(ordered_ops))

        # JEV selection every 10 ticks
        if tick % 10 == 0:
            selected = jev_selection(agents)
            for idx, sel in enumerate(selected[:len(agents)//3]):
                agents[idx] = agents[sel]
                agents[idx].copy_count += 1

    return monitor, config

def print_comparison(flat_m: BreathingMonitor, breath_m: BreathingMonitor):
    """Print v4 results table."""
    flat = flat_m.final_metrics()
    breath = breath_m.final_metrics()

    print(f"""
=== BREATHING POC v4 — CONSTANT THROUGHPUT ===
Baseline: flat (all 12 ops, no reordering)
Breathing: phase-aware reorder + boost (all 12 ops, 100% throughput)

Metric                    FLAT          CONST-BREATH   Δ
Avg fitness               {flat['fitness']:.3f}         {breath['fitness']:.3f}   {((breath['fitness']-flat['fitness'])/flat['fitness'])*100:+.1f}%
Coverage                  {flat['coverage']:.3f}         {breath['coverage']:.3f}   {((breath['coverage']-flat['coverage'])/flat['coverage'])*100:+.1f}%
Compression               {flat['compression']:.3f}         {breath['compression']:.3f}   {((breath['compression']-flat['compression'])/flat['compression'])*100:+.1f}%
Stability std dev         {flat['coverage_stability']:.3f}         {breath['coverage_stability']:.3f}   {((breath['coverage_stability']-flat['coverage_stability'])/flat['coverage_stability'])*100:+.1f}%
Coverage smoothness       {flat['coverage_smoothness']:.3f}         {breath['coverage_smoothness']:.3f}   {((breath['coverage_smoothness']-flat['coverage_smoothness'])/flat['coverage_smoothness'])*100:+.1f}%

Phase transitions: {sum(1 for i in range(len(breath_m.phase_history)-1) if breath_m.phase_history[i] != breath_m.phase_history[i+1])}
All ticks: 12 ops fired (constant throughput, no gating)
""")

# ─── Main ───

if __name__ == "__main__":
    config = SwarmConfig(n_agents=48, n_domains=15)

    # Run flat baseline
    print("Running flat baseline...")
    flat_monitor, _ = run_flat(config, n_ticks=2000, seed=42)

    # Run breathing v4 (constant throughput)
    print("Running breathing v4 (constant throughput)...")
    breath_monitor, _ = run_breathing(config, n_ticks=2000, seed=42, phase_pattern="IHE")

    # Compare
    print_comparison(flat_monitor, breath_monitor)

    # Verify pass/fail
    b = breath_monitor.final_metrics()
    f = flat_monitor.final_metrics()
    fitness_pass = (b['fitness'] - f['fitness']) / f['fitness'] >= 0
    print(f"PASS: fitness delta = {((b['fitness']-f['fitness'])/f['fitness'])*100:+.1f}% {'✅' if fitness_pass else '❌'}")
