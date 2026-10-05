#!/usr/bin/env python3
"""Quilted Relationships POC — Swarm Q2 (S5): push/pull edges in a mesh, not a tree.

A relationship is a DIRECTED EDGE with state — the geometry:
  context_buffer: ordered list of {source_agent_id, doc_sha, compression_tier}
    (oldest first = age desc, fnv1a tiebreak; append-mostly ledger);
  three edge cells (Lane-1 decayed pseudo-counts): push-novel?, pull-novel?,
    negotiate-hit? — the edge's SHAPE; counters keep the raw evidence.
Gates: PUSH on CONFIDENCE (p(novel)>=theta after warmup; tier!=D — doubts are
never pushed, only negotiated/pulled); PULL on UNCERTAINTY (dest lacks >= half
of source buffer); NEGOTIATE (both propose oldest not-known doc; sha match =>
bidirectional share; mismatch => no-op).
Learning: mark-on-contact (redundantly delivered doc is marked known_peer —
never twice on that edge); idle decay lam forgives old failure, gates reopen
(reflex loosening). NO RNG — every world bit is fnv1a(content). Stdlib only.
Run: python3 quilted-relationships/poc.py
"""

import hashlib, json, sys

LAM, ALPHA, Z95 = 0.85, 0.5, 1.6449
THETA_PUSH, THETA_UNC, WARMUP = 0.40, 0.50, 3
CYCLES, SPAWN = 14, 11            # era1: cycles 1-10 (A,B) | era2: 11-14 (+C)
TRACE, WINS = [], {}              # WINS[cycle] = edge successes that cycle


def say(line=""):
    TRACE.append(line)
    print(line)


def fnv1a(s):
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def canon(v):
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()[:12]


class Cell:
    def __init__(self, q, answers):
        self.q, self.answers = q, list(answers)
        self.counts = [0.0] * len(answers)
        self.n = 0

    def tick(self, ans):
        self.counts = [c * LAM for c in self.counts]
        self.counts[self.answers.index(ans)] += 1.0
        self.n += 1

    def idle(self):                            # reflex loosening between ticks
        self.counts = [c * LAM for c in self.counts]

    def p(self, ans):
        i = self.answers.index(ans)
        return (self.counts[i] + ALPHA) / (sum(self.counts) + ALPHA * len(self.answers))

    def lb(self, ans):
        p = self.p(ans)
        return p - Z95 * (p * (1 - p) / max(self.n, 1)) ** 0.5


def make_doc(minter, q, tier, counts, n, cyc, tag=""):
    body = {"minter": minter, "q": q, "tier": tier, "counts": counts,
            "n": n, "cyc": cyc, "tag": tag}
    body["sha"] = sha(canon(body))
    return body


class Edge:
    def __init__(self, src, dst):
        self.src, self.dst = src, dst
        self.buf = []
        ks = ("push", "pull", "neg")
        self.cells = {k: Cell(f"{k} success?", ["yes", "no"]) for k in ks}
        self.ok = dict.fromkeys(ks, 0)
        self.n = dict.fromkeys(ks, 0)
        self.push_log = []                     # (cycle, success)
        self.pull_unc0 = None                  # first-measured uncertainty
        self.redundant = []                    # (cycle, sha) receipt list

    def offer(self, doc):                      # oldest first, fnv1a tiebreak
        self.buf.append({"source": doc["minter"], "sha": doc["sha"],
                         "tier": doc["tier"], "age": doc["cyc"], "known": False})
        self.buf.sort(key=lambda e: (e["age"], fnv1a(e["sha"])))

    def mark(self, s):
        for e in self.buf:
            if e["sha"] == s:
                e["known"] = True

    def oldest(self, skip_doubts):
        for e in self.buf:                     # already age-ordered
            if not e["known"] and not (skip_doubts and e["tier"] == "D"):
                return e
        return None

    def uncertainty(self, dst):
        have = sum(1 for e in self.buf if e["sha"] in dst.corpus)
        return 1.0 - have / len(self.buf) if self.buf else 0.0

    def shape(self):
        return tuple(round(self.cells[k].p("yes"), 2) for k in ("push", "pull", "neg"))


class Agent:
    def __init__(self, aid, q, answers):
        self.aid, self.cell = aid, Cell(q, answers)
        self.corpus = {}                       # sha -> doc

    def mint(self, cyc):
        ans = self.cell.answers[fnv1a(f"{self.aid}|{self.cell.q}|block{cyc // 3}") % 2]
        self.cell.tick(ans)
        top = max(self.cell.answers, key=lambda a: self.cell.p(a))
        tier = "D" if self.cell.n < 2 else ("K" if self.cell.lb(top) >= 0.50 else "T")
        d = make_doc(self.aid, self.cell.q, tier,
                     [round(c, 4) for c in self.cell.counts], self.cell.n, cyc)
        self.corpus[d["sha"]] = d
        for e in EDGES.values():
            if e.src is self: e.offer(d)
        return d


EDGES, AGENTS = {}, {}       # (src.aid,dst.aid)->Edge ; aid->Agent


def edge(x, y):
    return EDGES[(x.aid, y.aid)]


def link(x, y, premark=()):
    for a, b in ((x, y), (y, x)):
        e = EDGES[(a.aid, b.aid)] = Edge(a, b)
        for d in sorted(a.corpus.values(), key=lambda d: d["sha"]):
            e.offer(d)
    for s in premark:                          # birth gifts: both sides know
        edge(x, y).mark(s); edge(y, x).mark(s)


def negotiate(x, y, cyc):
    ex, ey = edge(x, y), edge(y, x)
    px, py = ex.oldest(False), ey.oldest(False)
    if not (px and py):
        return
    ex.n["neg"] += 1
    ey.n["neg"] += 1
    if px["sha"] == py["sha"]:
        x.corpus.setdefault(px["sha"], y.corpus[px["sha"]])
        y.corpus.setdefault(px["sha"], x.corpus[px["sha"]])
        ex.mark(px["sha"])
        ey.mark(px["sha"])
        for e in (ex, ey):
            e.cells["neg"].tick("yes"); e.ok["neg"] += 1
        WINS[cyc] = WINS.get(cyc, 0) + 2       # one success per directed edge
        say(f"    NEGOTIATE {x.aid}<->{y.aid}: both propose {px['sha']} MATCH"
            f" -> bidirectional share (tier {px['tier']})")
    else:
        ex.cells["neg"].tick("no")
        ey.cells["neg"].tick("no")
        say(f"    NEGOTIATE {x.aid}<->{y.aid}: {px['sha']} vs {py['sha']} MISMATCH -> no-op")


def flow(x, y, cyc):
    """One motion on directed edge x->y: y may pull, x may push."""
    e = edge(x, y)
    unc = e.uncertainty(y)
    if unc >= THETA_UNC:                       # PULL: high uncertainty
        if e.pull_unc0 is None: e.pull_unc0 = unc
        e.n["pull"] += 1
        ent = e.buf[fnv1a(f"pull|{y.aid}|{x.aid}|{cyc}") % len(e.buf)]
        if ent["sha"] not in y.corpus:
            y.corpus[ent["sha"]] = x.corpus[ent["sha"]]
            e.cells["pull"].tick("yes"); e.ok["pull"] += 1
            e.mark(ent["sha"]); WINS[cyc] = WINS.get(cyc, 0) + 1
            say(f"    PULL  {y.aid} <- {x.aid}: {ent['sha']} (tier {ent['tier']}) NOVEL  unc={unc:.2f}")
        else:
            e.cells["pull"].tick("no"); e.mark(ent["sha"])
            say(f"    PULL  {y.aid} <- {x.aid}: {ent['sha']} redundant  unc={unc:.2f}")
    pc = e.cells["push"]
    if pc.n < WARMUP or pc.p("yes") >= THETA_PUSH:   # PUSH: confidence
        cand = e.oldest(True)
        if cand:
            e.n["push"] += 1
            if cand["sha"] not in y.corpus:
                y.corpus[cand["sha"]] = x.corpus[cand["sha"]]
                pc.tick("yes"); e.ok["push"] += 1
                e.push_log.append((cyc, True)); e.mark(cand["sha"])
                WINS[cyc] = WINS.get(cyc, 0) + 1
                say(f"    PUSH  {x.aid} -> {y.aid}: {cand['sha']} (tier {cand['tier']}) NOVEL  p_novel={pc.p('yes'):.2f}")
            else:
                pc.tick("no"); e.mark(cand["sha"])
                e.push_log.append((cyc, False))
                e.redundant.append((cyc, cand["sha"]))
                say(f"    PUSH  {x.aid} -> {y.aid}: {cand['sha']} REDUNDANT (mark)  p_novel={pc.p('yes'):.2f}")
    else:
        say(f"    PUSH  {x.aid} -> {y.aid}: gate rests (p_novel={pc.p('yes'):.2f} < {THETA_PUSH})")


def main():
    seeds = [make_doc("P0", "origin", "D", [0.0, 0.0], 0, 0, tag=t) for t in ("s1", "s2")]  # origin doubts
    anc = [make_doc("P0", "origin-era", "K", [7.0, 1.0], 8, 0, tag=t) for t in ("a1", "a2")]  # parent knowledge
    cloth = seeds + anc
    A = AGENTS["A"] = Agent("A", "terrain", ["rocky", "sandy"])
    B = AGENTS["B"] = Agent("B", "weather", ["wet", "dry"])
    for ag in (A, B):
        for d in cloth: ag.corpus[d["sha"]] = d
    link(A, B)
    say("GENESIS: A(terrain) + B(weather) share parent cloth: " + ", ".join(f"{d['sha']}/{d['tier']}" for d in sorted(cloth, key=lambda d: d["sha"])))
    say("A answers {rocky,sandy} vs B answers {wet,dry} — different knowledge")

    for cyc in range(1, CYCLES + 1):
        if cyc == SPAWN:                       # agent 3: child of A
            C = AGENTS["C"] = Agent("C", "flora", ["lush", "sparse"])
            for d in cloth: C.corpus[d["sha"]] = d   # gift: seeds + ancestors
            link(A, C, premark=[d["sha"] for d in cloth])
            link(B, C)
            say(f"\n=== CYCLE {cyc} === AGENT C JOINS THE MESH (child of A; 6 directed edges)")
        else:
            say(f"\n=== CYCLE {cyc} ===")
        ags = sorted(AGENTS.values(), key=lambda a: a.aid)
        for ag in ags:                         # world tick + doc mint
            ag.mint(cyc)
        for a1, a2 in [(x, y) for i, x in enumerate(ags) for y in ags[i + 1:]]:
            flow(a1, a2, cyc)                  # motions first: pay the tax,
            flow(a2, a1, cyc)
            negotiate(a1, a2, cyc)             # then reconcile what's left
        for e in EDGES.values():
            for c in e.cells.values():
                c.idle()
        say("  buffers: " + " ".join(f"{k[0]}->{k[1]}={len(v.buf)}"
                                    for k, v in sorted(EDGES.items())))

    say("\n=== EDGE LEDGERS (the geometry) ===")
    for k in sorted(EDGES):
        e = EDGES[k]
        say(f"{k[0]}->{k[1]}: push {e.ok['push']}/{e.n['push']}  pull {e.ok['pull']}/{e.n['pull']}"
            f"  neg {e.ok['neg']}/{e.n['neg']}  buf={len(e.buf)}  shape(psh,pll,neg)={e.shape()}"
            f"  redundant_at={[r[0] for r in e.redundant]}")

    # --- claims (fail loud: charter law)
    def window(e, c1, c2):
        rows = [r for r in e.push_log if c1 <= r[0] <= c2]
        return (sum(1 for _, s in rows if s), len(rows)) if rows else (0, 0)

    ok = True
    e1s, e1n = window(edge(A, B), 1, 5)
    e2s, e2n = window(edge(A, B), 6, CYCLES)
    r = e1n and e2n and e1s / e1n < e2s / e2n
    say(f"CLAIM1 edge cell learns (A->B push success): c1-5 {e1s}/{e1n} -> c6+ {e2s}/{e2n}  [{'OK' if r else 'FAIL'}]")
    ok &= bool(r)
    era2_red_AB = sum(1 for k in (("A", "B"), ("B", "A"))
                      for c, _ in EDGES[k].redundant if c >= SPAWN)
    r = era2_red_AB == 0
    say(f"CLAIM2 mature edges stay clean: era2 redundant pushes on A<->B = {era2_red_AB}  [{'OK' if r else 'FAIL'}]")
    ok &= bool(r)
    seen, tax_ok = {}, True
    for k in sorted(EDGES):
        for _, s in EDGES[k].redundant:
            seen[(k, s)] = seen.get((k, s), 0) + 1
            if seen[(k, s)] > 1:
                tax_ok = False
    say(f"CLAIM3 bounded stranger tax: no doc redundantly pushed twice on any edge  [{'OK' if tax_ok else 'FAIL'}]")
    ok &= tax_ok
    Cc = AGENTS["C"]
    pulls_C = edge(B, C).ok["pull"] + edge(A, C).ok["pull"]
    unc0 = edge(B, C).pull_unc0 if edge(B, C).pull_unc0 is not None else 1.0
    unc1 = edge(B, C).uncertainty(Cc)
    r = pulls_C >= 3 and unc0 - unc1 >= 0.15
    say(f"CLAIM4 pull-when-uncertain: C pulled {pulls_C} docs; uncertainty over B's buffer {unc0:.2f} -> {unc1:.2f}  [{'OK' if r else 'FAIL'}]")
    ok &= bool(r)
    e1 = sum(WINS.get(c, 0) for c in range(1, SPAWN))
    e2 = sum(WINS.get(c, 0) for c in range(SPAWN, CYCLES + 1))
    r = e2 / (CYCLES - SPAWN + 1) > e1 / (SPAWN - 1)
    say(f"CLAIM5 improved sharing (edge successes/cycle): era1 {e1}/{SPAWN - 1}={e1 / (SPAWN - 1):.2f} -> era2 {e2}/{CYCLES - SPAWN + 1}={e2 / (CYCLES - SPAWN + 1):.2f}  [{'OK' if r else 'FAIL'}]")
    ok &= bool(r)
    a_docs = sum(1 for d in Cc.corpus.values() if d["minter"] == "A")
    b_docs = sum(1 for d in Cc.corpus.values() if d["minter"] == "B")
    c_up = sum(1 for d in A.corpus.values() if d["minter"] == "C")
    r = a_docs >= 4 and b_docs >= 4 and c_up >= 2
    say(f"CLAIM6 C woven in: holds {a_docs} A-docs + {b_docs} B-docs; {c_up} C-docs reached A  [{'OK' if r else 'FAIL'}]")
    ok &= bool(r)
    say("\ncorpus sizes: " + " ".join(f"{k}={len(v.corpus)}" for k, v in sorted(AGENTS.items())))
    say(f"TRACE FINGERPRINT {sha(chr(10).join(TRACE))}")
    if not ok:
        say("VERDICT: FAIL — a claim broke")
        sys.exit(1)
    say("VERDICT: PASS — all claims hold; determinism = identical fingerprint on rerun")


if __name__ == "__main__":
    main()
