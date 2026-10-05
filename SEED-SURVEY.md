# SEED-SURVEY.md — Run 1 (2026-10-04, ZeroClaw builder)

Survey of the seed repos backing the developmental-GAN loop. Every claim below
was verified on this box today by running the named command (receipts inline).
"RUNS" = executed successfully during this survey. "Aspirational" = prose or
stubs not exercised here.

## Seed 1: SuperInstance/exoj — the shells (local `~/projects/exoj`, tag v0.1.0)

**Runs today (verified):**
- `npm test` → `node --test lab/*.test.mjs` — **28/28 pass** (gan.test.mjs,
  live-fallback.test.mjs, readme-pin.test.mjs), ~89 ms.
- `npm run gate` / smoke referenced in package.json; CI (forge.yml) exists.

**What it is (verified from code, not prose):**
- `core.mjs`: hex-lattice `Cell` class + `ExoJ` field — cells carry soft
  γ/η amplitudes (conservation γ̄+η̄ ≤ 1), sha256-chained canonical-JSON
  proof objects. Exports: `Cell`, `ExoJ`, `canonicalJSON`, `sha256Hex`,
  `hexRing`, `normalizeView`.
- `gan/unitTable.mjs`: `UnitTable` — deterministic masses via `fnv1a`
  (NO RNG) — this is the closest existing ancestor of
  ticks-as-probabilities.
- `live.mjs`, `selflocal.mjs`, `atlas.mjs`, experiments e_x0–e_x8: a
  research spine with pre-registered decision rules (receipts dated before
  runs, per README charter).
- Law files live and current: `LEGIBILITY.md`, `ANTI-ENTROPY-LOG.md`
  (append-only fault ledger; F1/F2 recorded found+fixed).

**Seam to a central agent:** `core.mjs` exports + `receipts.mjs`
content-addressed proofs. A central agent can import `@superinstance/exoj`,
drive `ExoJ` fields, and verify receipts.

**Aspirational (not exercised here):** atlas sweep protocols, e_x8
gate-sweep conclusions, `claude/live-fold` / `claude/self-localizing` /
`forge-adopt-v0` branches (exist remotely; unsurveyed beyond names).

## Seed 2: SuperInstance/quilt-pincher — the muscle (local `~/projects/quilt-pincher`)

**Runs today (verified):**
- `npm test` → `tsx --test test/*.test.ts` — **39/39 pass** (14 suites),
  ~5.1 s.

**What it is (verified from code):**
- Full Quilt-cell reflex engine: pinch (formula cell) → vector match
  (program cell) → veto (listener cell), <50 ms target, LLM as compiler
  only. Three platform sheets: `cloudSheet`, `workstationSheet`
  (+`SqliteReflexStore`), `esp32Sheet` (+`buildNail`/`ESP32Engine`).
- **Critical seam already exists:** `src/adapters/zeroclaw-spec.ts` —
  `loadZeroclawSpecs` / `parseZeroclawSpec` / `ZeroclawSpec`, exported from
  the package index. Pincher already knows how to load reflex specs from
  this repo (zeroclaw) by name.
- HDC layer present: `HDCEmbedder`, `Hyper` vectors, `exoj-field.ts`
  (`ExoJFieldState`) — pincher already projects exoj field state into
  hypervectors. The two seeds are pre-wired at the HDC/exoj-field seam.

**Aspirational (not exercised here):** ESP32 no_std port (docs/ESP32_PORT.md),
federation/R2 mirroring, sqlite-vec workstation store, dependabot/feature
branches (`fb2-zeroclaw-synapse`, `fb3-serve-ledger`, `fb2-origin-row-payload`
— names suggest prior zeroclaw↔pincher wiring attempts; unsurveyed).

## npm `@superinstance/*` artifacts

exoj package.json declares `@superinstance/exoj` v0.1.0 with published
`files` (core/live/receipts/selflocal/smoke/experiments/lab). Not installed
or exercised in this survey run — verify against the registry in Run 2
before depending on the published artifact vs the local clone.

## Verdict for the loop (where the seams connect)

1. Both seeds run green TODAY on this box (28/28 and 39/39).
2. The thinnest vertical slice for Run 2 is nearly free: zeroclaw already
   has a spec adapter consumer in pincher (`loadZeroclawSpecs`) and an
   exoj-field projection (`ExoJFieldState`). The spec format is verified in
   code (Run 1): grammar `zeroclaw-reflex-spec/v1` — JSON with `id, intent,
   trigger, context_sha256, model, payload{delta_path, output_sha256,
   content, bytes}, cites[], provenance{compiledBy: 'zeroclaw',
   parentOrder}`; payload stays DATA (wrapped as a literal), never executed
   as code. The slice = zeroclaw publishes a real spec file in that exact
   format, pincher loads it, pinches, returns the payload — end-to-end,
   receipted with real output.
3. Ticks-as-probabilities lineage: exoj `UnitTable` (fnv1a deterministic
   masses, no RNG) is the seed of the no-RNG tick ledger; pincher match
   thresholds are the seed of gates firing pipelines.

*No files outside this repo were modified. Survey receipts: test outputs
quoted verbatim above, run 2026-10-04 ~16:2x AKDT.*
