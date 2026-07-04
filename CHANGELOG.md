# Changelog

All notable changes to vibe-check are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.0.0] — 2026-07-04

Initial public release.

### Checks shipped
- **syntax_errors** — Python files that do not parse (exact, via `ast`). Non-Python languages reported as skipped, never faked.
- **duplicates** — Identical code blocks spanning two or more files. Test files excluded. Sliding-window fingerprinting with contiguous-block merge.
- **package_risks** — Undeclared imports (imported but not in requirements.txt / pyproject.toml) and typosquat lookalikes of popular packages. Offline only.
- **comment_buzzwords** — Marketing fluff in comments (`robust`, `seamless`, `game-changer`, and so on).
- **readme_hype** — 0–1 hype score for markdown files, based on buzzword density. Code spans stripped before scoring.
- **structural** — Giant files (>1000 lines), deep nesting (>5 directory levels), circular Python imports. Cycles labelled `deferred_late_import` vs `top_level`.
- **dead_code** — Stub functions (body is only `pass` / `...` / `raise NotImplementedError`) and top-level definitions that nothing in the repo references.

### Output formats
- `--format json` (default) — machine-readable full report
- `--format summary` — human-readable terminal table (counts + disposition)
- `--format prompt` — copy-paste LLM prompt, grouped by priority
- `--format triage` — the two-axis triage panel only
- `--html PATH` — self-contained offline HTML dashboard
- `--out PATH` — write JSON report to disk

### CI integration
- `--fail-on hard` — exit 1 if any hard signal is found
- `--fail-on supply-chain` — exit 1 if any package risk is found (narrowest gate)
- `--baseline REPORT_JSON` — report only *new* findings vs a stored report (turns scanner into a "don't add debt" habit)

### Triage model
Two hard axes (Integrity: PASS/FAIL; Supply Chain: CLEAN/RISK) gate the disposition. All other findings (duplication, stubs, dead code, giant files, hype) are unbanded observations — surfaced for a human or LLM to interpret, never used to classify the repo.

### Precision improvements over development
- Soft imports (`TYPE_CHECKING`, `try/except ImportError`, function-local) excluded from package risk and circular import detection
- `__all__` exports counted as references (public API, not dead code)
- Protocol/ABC method bodies (`...`) not flagged as stubs
- Decorated functions (route handlers, CLI commands, fixtures) not flagged as unreferenced
- Relative imports resolve correctly; stdlib name collisions (local `types.py`, `http.py`) do not forge phantom cycle edges
- Docs files (`docs/`, `conf.py`) excluded from package risk check (doc-toolchain deps live in optional dep groups)
- Duplicate block merger uses subset+overlap condition to stitch adjacent windows with different-but-related file-sets

---

## Prior development (pre-release)

Key precision milestones reached before 1.0.0:

- Circular import detection: removed from Integrity gate after basket validation showed pristine libraries (click, werkzeug) trip detection on platform-guarded or deferred imports. Now an observation.
- Duplication scoring: removed band thresholds after basket validation (idna 0% .. httpx 24%) showed duplication tracks library architecture (API surface vs logic density), not review burden.
- README hype: code spans stripped before buzzword scoring so a README that *lists* the words it detects does not flag itself.
