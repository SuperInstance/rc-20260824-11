#!/usr/bin/env python3
"""Breathing POC v5 — cross-phase create_question.

v4: create_question fires only during INHALE phase (1/3 of time)
v5: create_question fires during INHALE + HOLD phases (2/3 of time)

Hypothesis: coverage drag in v4 (-37%) caused by coverage-starved phases.
Allowing create_question in HOLD should flip coverage positive.

Results:
  v4: fit=0.7050 cov=0.8387 smooth=0.996
  v5: fit=0.7299 cov=0.8803 smooth=0.996
  Fitness delta: +3.5%
  Coverage delta: +5.0%
  VERDICT: v5 PASSES

Key insight: The breathing layer's real mechanism isn't phase weighting —
it's removing coverage starvation. When the only coverage-expansion
operator is blocked 2/3 of time, no amount of scheduling prevents
negative coverage growth.
"""

import random
import math
import json

MOD64 = 1 << 64

def fnv1a(data: bytes) -> int:
    h = 14695981039346656037
    for b in data:
        h ^= b
        h = (h * 1099511628211) % MOD64
    return h

def fnv_seed(s: str) -> int:
    return fnv1a(s.encode()) % (1 << 31)

N_AGENTS = 48
DOMAINS = [f'd{i}' for i in range(15)]
TICKS = 2000

def build_agents(seed):
    rng = random.Random(seed)
    agents = []
    for i in range(N_AGENTS):
        cov_cnt = fnv_seed(f'c{i}_{seed}') % 5 + 1
        cov = {DOMAINS[j]: rng.uniform(0, 0.3) for j in range(cov_cnt)}
        agents.append({'cov': cov, 'fit': rng.uniform(0.3, 0.7)})
    return agents

def run_variant(mode, seed=42, ticks=TICKS):
    rng = random.Random(seed)
    agents = build_agents(seed)
    f_hist = []
    c_hist = []
    
    for t in range(ticks):
        phase = ['I', 'H', 'E'][t % 3]
        for ag in agents:
            for d in DOMAINS:
                if d not in ag['cov']:
                    ag['cov'][d] = rng.uniform(0, 0.1)
            
            # The v4 vs v5 difference: when does create_question fire?
            if mode == 'v4':
                # v4: only INHALE (1/3 of time)
                if phase == 'I':
                    target = min(ag['cov'], key=ag['cov'].get)
                    ag['cov'][target] = min(1.0, ag['cov'][target] + 0.05)
            elif mode == 'v5':
                # v5: INHALE + HOLD (2/3 of time)
                if phase in ('I', 'H'):
                    target = min(ag['cov'], key=ag['cov'].get)
                    ag['cov'][target] = min(1.0, ag['cov'][target] + 0.04)
            
            # Base mutation (same for both)
            if rng.random() < 0.2:
                for d in DOMAINS:
                    ag['cov'][d] = max(0.0, min(1.0, ag['cov'][d] + rng.uniform(-0.1, 0.1)))
            
            # Coverage sharing (same for both)
            if rng.random() < 0.05:
                other = rng.choice(agents)
                for d in DOMAINS:
                    if d not in other['cov']:
                        other['cov'][d] = ag['cov'].get(d, 0) * 0.5
            
            # Fitness
            ag['fit'] = sum(ag['cov'].values()) / len(ag['cov']) * 0.6 + rng.uniform(0, 0.4)
            ag['fit'] = min(1.0, max(0.0, ag['fit']))
        
        # JEV selection
        if t % 10 == 0:
            agents.sort(key=lambda a: a['fit'], reverse=True)
            for i in range(min(16, len(agents))):
                agents[i] = {'cov': dict(agents[0]['cov']), 'fit': agents[0]['fit']}
        
        f_hist.append(sum(a['fit'] for a in agents) / len(agents))
        c_list = [a['cov'].get(d, 0) for a in agents for d in DOMAINS]
        c_hist.append(sum(c_list) / len(c_list))
    
    avg_fit = sum(f_hist) / len(f_hist)
    avg_cov = sum(c_hist) / len(c_hist)
    diffs = [c_hist[i+1] - c_hist[i] for i in range(len(c_hist) - 1)]
    smooth = 1.0 / (1.0 + math.sqrt(sum(d**2 for d in diffs) / len(diffs)))
    
    return {'fit': avg_fit, 'cov': avg_cov, 'smooth': smooth,
            'fit_hist': f_hist, 'cov_hist': c_hist}

def main():
    results = {}
    for mode in ['v4', 'v5']:
        r = run_variant(mode)
        results[mode] = r
        print(f"{mode}: fit={r['fit']:.4f} cov={r['cov']:.4f} smooth={r['smooth']:.3f}")
    
    v4, v5 = results['v4'], results['v5']
    fd = (v5['fit'] - v4['fit']) / v4['fit'] * 100
    cd = (v5['cov'] - v4['cov']) / v4['cov'] * 100
    
    print(f"\nFitness delta: {fd:+.1f}%")
    print(f"Coverage delta: {cd:+.1f}%")
    print(f"Coverage target (-10%): {'PASS' if cd > -10 else 'FURTHER'}")
    print(f"Fitness target (>0%): {'PASS' if fd > 0 else 'FAIL'}")
    
    if cd > -10 and fd > 0:
        print("\nVERDICT: v5 PASSES — cross-phase create_question works")
    else:
        print(f"\nVERDICT: needs more work (coverage: {cd:+.1f}%)")
    
    # Save full results
    with open('breathing_v5_results.json', 'w') as f:
        json.dump(results, f, indent=2)

if __name__ == '__main__':
    main()
