# Changelog

All notable changes to vibe-check are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [1.1.0] — 2026-07-04

JS/TS supply-chain and dead-export coverage, plus honesty fixes for mixed-language repos.

### Added
- **package_risks: JS/TS ecosystem.** Parses `dependencies` / `devDependencies` / `peerDependencies` / `optionalDependencies` from every `package.json` in the tree (monorepo-aware; workspace package names are first-party) and diffs against `import`/`export ... from`, `require()`, and dynamic `import()` specifiers. Node builtins, relative paths, path aliases, and URL imports are excluded. Comments and template literals are stripped first so code *examples* embedded in strings never become supply-chain flags.
- **dead_code: `unreferenced_exports_js`.** Grep-based orphan scan for named JS/TS value exports (function/class/const) whose identifier appears in no other file. Precision guards: barrel/index files, `export *` re-export targets, tests, examples, benchmarks, configs, `.d.ts`, and components referenced from markup (`.mdx`, `.astro`, `.vue`, `.svelte`) are never flagged. Basket-validated: zod went 106 → 2 findings after tuning.
- **Ecosystem honesty contract.** `package_risks.ecosystems` reports checked / not-checked per ecosystem, and the `--format summary` package-risk row is annotated (e.g. `0  (not checked: js/ts)`) whenever a present language could not be verified. A stdlib-only repo with no manifest reports *checked*, not unchecked — there is nothing to declare.
- **Triage `explanation`.** One plain-language line under the disposition (e.g. `FAST_TRACK — no integrity or supply-chain signals blocking review`) so output is readable without knowing the tool.

### Changed
- Imports in `examples/`, `bench/`, `fixtures/`, `__mocks__/`, and `playground/` directories are no longer treated as production dependencies (both ecosystems), matching the existing tests/docs exclusions. Validated against click, requests-era fixtures, zod, and vercel/ai.

### Fixed
- **`package_risks`: unversioned `pyproject.toml` dependencies were silently dropped.** The parser required a trailing version operator (`>=`, `[`, etc.), so a bare entry like `"requests-cache",` with no pin at all never entered the declared set — then got flagged as undeclared even though it was correctly declared. Found via a 37-repo real-world benchmark. Now matched by a second, narrowly-scoped pattern (quoted token immediately followed by `,` or `]`) that doesn't sweep up unrelated strings like `description` or `license` values.
- **`package_risks`: missing Python import-name aliases.** Added `python-dotenv`→`dotenv`, `PyGithub`→`github`, `PyJWT`→`jwt`, `alpaca-py`→`alpaca` to the existing alias table — same class of mismatch as `beautifulsoup4`→`bs4`, just not covered yet. Also found via the same benchmark.
- **`package_risks`: an empty/comment-only `requirements.txt` or `pyproject.toml` reported "not checked" on itself.** `found_any` was set as soon as the manifest file was found on disk, not when it actually contained a parseable dependency — vibe-check's own comment-only `requirements.txt` tripped this, reporting `not checked: deps file found but no dependencies parsed` instead of the correct `checked (stdlib-only imports, no manifest needed)`. `found_any` now only flips true when a dependency name is actually parsed, so an empty manifest is treated the same as no manifest.

### Added
- **`action.yml`: `disposition` output.** Exposes the triage disposition (`FAST_TRACK` / `STANDARD_TRIAGE` / `DEEP_AUDIT_REQUIRED`) as a step output so a consuming workflow can branch on it directly instead of parsing the JSON report.
- **`action.yml`: falls back to `python` when `python3` is unavailable**, for self-hosted runners without a `python3` alias.

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
