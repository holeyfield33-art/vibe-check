# Interpreting a vibe-check Report

vibe-check is a review-priority tool, not a quality score, trust score, or AI-likelihood detector.  
It answers one question: **how carefully does a human need to look at this repository?**

The output is deterministic, offline, and deliberately narrow. Two hard axes gate the disposition. Everything else is reported as unbanded observations for human or LLM judgment.

Python receives the deepest checks (full AST for syntax, imports, dead code, structure). JS/TS coverage is more limited (package.json parsing and a grep-based export scan). A zero in any category only means nothing was flagged for what was actually checked — ecosystems or languages that could not be verified are reported honestly.

## Disposition

| Disposition | Meaning | When it appears | What a human should do next |
|---|---|---|---|
| **FAST_TRACK** | No hard signals | Both Integrity and Supply Chain axes are clean | Proceed with normal review. Soft observations (duplicates, stubs, etc.) are still present if they exist — treat them as context, not blockers. |
| **STANDARD_TRIAGE** | One hard axis raised | Either Integrity **or** Supply Chain has a finding, but not both | Inspect the raised axis first. Confirm the syntax error or the package risk is real and actionable. Soft observations remain informational. |
| **DEEP_AUDIT_REQUIRED** | Integrity failed or both axes raised | Syntax error(s) present, or both Integrity and Supply Chain are raised | Treat as a priority review. A file that does not parse is broken. Supply-chain risks (undeclared imports or typosquat lookalikes) should be verified before merge. |

### Hard axes (only these gate the disposition)

- **Integrity** — syntax errors only. A Python file that does not parse is a hard failure. Non-Python files are reported as skipped, never faked.
- **Supply chain** — undeclared imports (Python or JS/TS) and dependency names that look like typosquats of popular packages. These are concrete enough to warrant verification.

Both clean → `FAST_TRACK`  
One raised → `STANDARD_TRIAGE`  
Integrity failed or both raised → `DEEP_AUDIT_REQUIRED`

`--fail-on hard` gates only on these two axes (syntax errors and package risks). Other findings never fail the build by themselves.

## Unbanded observations (do not gate the disposition)

These are facts with honest caveats. They do not change the disposition:

- **Duplicates** — identical code blocks across files (test files excluded). May indicate real duplication or intentional library structure.
- **Stubs / unreferenced definitions** — functions or classes that are just `pass` / `...` / `raise NotImplementedError`, or top-level names nothing else references. Often intentional scaffolding.
- **Structural** — giant files (>1000 lines), deep nesting (>5 levels), circular imports.
- **Comment buzzwords / README hype** — marketing language density. Informational only.

vibe-check reports them and tells you how much to trust each signal, but it does not pretend they block review.

### Common false-positive patterns

- Imports in `examples/`, `fixtures/`, `tests/`, `docs/`, or playground directories (intentionally excluded from package-risk checks).
- Alias mismatches that were later added to the alias table (e.g. `python-dotenv` → `dotenv`).
- Barrel/index re-exports and test/example files (never flagged as unreferenced JS/TS exports).
- Legitimate long test files or intentional stubs.

If you hit a clear false positive, open an issue with a minimal reproducer.

## Practical next steps by disposition

### FAST_TRACK
1. Skim soft observations if any exist.
2. Continue normal development or review.
3. Optional: feed the report into an LLM prompt for awareness of duplicates or dead code.

### STANDARD_TRIAGE
1. Open the raised axis first (syntax error or package risk).
2. Confirm it is real (not a false positive from an excluded path or alias).
3. Fix or explicitly accept before merging if using `--fail-on`.
4. Review soft observations as secondary context.

### DEEP_AUDIT_REQUIRED
1. Fix syntax errors first — a file that does not parse is broken.
2. Verify every supply-chain finding (undeclared import or possible typosquat).
3. Only after hard axes are addressed, look at soft observations.
4. Consider re-running with `--baseline` on subsequent changes so only *new* debt fails CI.

## Using the report with an LLM

Run with `--format prompt` to get a ready-to-paste block, or manually include the JSON/summary:

> Here are the files I am working on, plus a vibe-check report. Note the [specific finding] before you suggest changes.

The model gets awareness of concrete signals without you having to spot them first.

## CI and baselines

- `--fail-on hard` fails only on Integrity or Supply Chain issues (syntax errors and package risks).
- `--fail-on supply-chain` is the narrowest gate.
- `--baseline baseline.json` reports only *new* findings relative to a stored report (useful for “don’t add debt”).

## What this tool does not do

- It does not score overall quality, trustworthiness, or likelihood of being AI-generated.
- It does not auto-fix.
- It does not make network calls or look up CVEs.
- It does not require configuration files or plugins.

Same repository in, same report out.

---

*This guide reflects the behavior documented in the project README and CONTRIBUTING.md as of the current main branch. The disposition is a review priority, not a verdict.*
