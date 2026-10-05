# Q0 — Question Space Evolution

## Problem
All existing swarm layers (J1-J2, C1-C2, D2, M1-M2, Q2) operate within a FIXED question space.
Agents compete for attention on predefined questions. None of them can change WHAT the questions are.

This is like having a chess engine that can only make moves but can't change the rules.

## Insight
The swarm should develop a meta-layer that evolves the problem space itself.
Not by changing parameters of existing questions, but by:
1. **Merging** related questions (discovering they're the same question differently posed)
2. **Splitting** ambiguous questions (discovering one question hides multiple)
3. **Abstraction** (replacing specific questions with general ones)
4. **Reconstruction** (combining unrelated questions into novel formulations)

## Mechanism

### 4 Operators on Question Space (Q0)

```
Q0_question = (question_text, cell_sha, history_sha, importance_score)

Operators:
1. MERGE(q1, q2) → q_merged    (if similarity > threshold)
2. SPLIT(q) → {q1, q2, ...}    (if variance > threshold)  
3. ABSTRACT(q, hierarchy_level) → q_abstract    (generalization)
4. RECONSTRUCT(q1, q2, relationship) → q_new    (creative synthesis)
```

### How It Works

1. **Monitoring**: Q0 agents observe the question space usage patterns
   - Track which questions are asked, answered, compressed, evicted
   - Detect clusters of related questions
   - Identify high-variance questions that might be ambiguous

2. **Evolution proposals**: Q0 agents propose new question topologies
   - "These 3 questions are really the same question" → MERGE
   - "This question has bimodal answer distribution" → SPLIT
   - "We're asking too many similar questions" → ABSTRACT to level N

3. **Selection**: JEV doesn't just pick which agent to run, it picks which QUESTION
   - But now the question LIST can evolve
   - New questions compete for insertion into the question space
   - Old questions compete for retention (replaceability criterion)

4. **Ledger**: The question topology evolution is itself ledgered
   - SHA chain: each topology change has a receipt
   - Like M2 lineage but for the question space, not individual agents
   - Q0 has its own "genome" (the topology) and "ledger" (usage history)

## Key Difference from Existing Layers

| Layer | What it optimizes | Fixed/Variable |
|-------|-------------------|----------------|
| J1/J2 | Agent selection | Questions fixed |
| C1/C2 | Answer compression | Questions fixed |
| D2 | Selection stochasticity | Questions fixed |
| M1/M2 | Agent evolution | Questions fixed |
| Q2 | Inter-agent relationships | Questions fixed |
| **Q0** | **Question space topology** | **Questions evolve** |

## Why This Matters

1. **Humans do this constantly**: When learning, we don't just answer questions — we change what questions we ask. A child doesn't answer "why is the sky blue?" — they ask "what is color?"

2. **Narrow AI trap**: Most AI systems are brilliant at fixed question spaces. But real intelligence requires evolving what you're thinking about.

3. **Swarm advantage**: Individual agents are narrow. But the SWARM can discover that the collective narrowness has structure. The question space is a higher-order phenomenon.

4. **Emergent creativity**: If the swarm can RECONSTRUCT questions from unrelated domains, it can generate novel research directions, novel problems to solve.

## POC Design

```python
# p0_question_evolution.py
# Deterministic (no RNG), fnv1a lineage

# Simplified model:
# - 3 question families (A, B, C) with 10-20 variations each
# - 5 agents, each expert on one family
# - Q0 agents monitor usage and propose topology changes
# - Measure: can Q0 discover that family A questions are redundant with family B?
# - Expected: Q0 merges overlapping families, reducing question space by 30-50%
#   while maintaining or improving solution coverage

# 4 operators tested independently and together
# Metrics:
# - Question space reduction (% of questions eliminated via merge/abstract)
# - Coverage preservation (% of original answer space still reachable)
# - Novelty generation (new questions created via reconstruction)
# - Adaptation speed (how fast does Q0 respond to new data patterns)
```

## Follow-up to M2

M2 showed: genome compounding + ledger resetting
Q0 extends this: question compounding + question topology evolution

The swarm doesn't just evolve its mind (M1/M2) — it evolves its curiosity (Q0).
