# Contributing to vibe-check

Thanks for your interest. vibe-check is a deliberately small tool with a deliberately narrow scope.
Read this before opening a PR — most rejections come from scope disagreement, not code quality.

## Identity constraints (non-negotiable)

These are not preferences. They are what the tool *is*:

| Constraint | Why |
|---|---|
| **One file.** `vibe_check.py` is the entire tool. | Readable in one sitting. Zero install friction. |
| **Zero dependencies.** Python stdlib only. | No `pip install`, no version conflicts, no supply-chain surface. |
| **No network calls.** All checks are offline and deterministic. | Same repo in, same report out. Always. |
| **No auto-fix.** vibe-check observes; it does not modify. | Fixing belongs to the agent consuming the report. |
| **No config files.** No `.vibecheck.toml`, no rule packs, no plugins. | Config files are how single-file tools die. |
| **No LLM-in-the-loop scoring.** | The determinism is the product. |

PRs that add a dependency, make a network call, split the tool into multiple files, or add
auto-fix behavior will be declined regardless of implementation quality. The answer is no by design.

## What good PRs look like

### False-positive fixes
The highest-value contribution. A false positive (a finding that is technically true but
practically noise) erodes trust faster than a missed finding. To propose a fix:

1. Open an issue first using the [false positive template](.github/ISSUE_TEMPLATE/false-positive.yml).
2. Include a **minimal reproducer** — the smallest Python snippet that triggers the FP.
3. Explain what the correct behavior is and why the current behavior is wrong.
4. The fix should tighten precision without reducing recall on the existing test suite.

### False-negative fixes
Missed findings that a reasonable engineer would expect vibe-check to catch. Same bar:
minimal repro, explain the expected behavior, add a regression test.

### New checks
New checks are welcome if they satisfy all of:
- Zero dependencies (stdlib only)
- Offline and deterministic
- High precision (favors missing a marginal case over a false alarm)
- Python AST-based or language-agnostic (not heuristic regexes on non-Python)
- Adds a test that would have caught a regression

Checks that require network access, third-party parsers, or produce frequent false positives
on idiomatic code will not be merged.

## Running the tests

```
python test_vibe_check.py
```

No setup required. The test suite is stdlib-only and runs offline. All 65 tests should pass.

## PR checklist

- [ ] `python test_vibe_check.py` passes (zero failures)
- [ ] New behavior is covered by a test
- [ ] No new imports outside Python stdlib
- [ ] If adding a check: explain the FP/FN tradeoff in the PR description
- [ ] If fixing a FP: include the minimal repro as a test case

## What we will not add (please don't PR these)

- Config files / `.vibecheck.toml` / rule packs
- Plugin systems or extension hooks
- Network features (PyPI liveness, download counts, CVE lookups)
- LLM-in-the-loop scoring or AI-assisted analysis
- Auto-fix / code modification
- A second source file
- Support for languages that require a non-stdlib parser

These refusals are not temporary — they are the product's identity.
