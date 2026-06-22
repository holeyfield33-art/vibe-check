# vibe-check

A zero-dependency code scanner that flags the things that signal AI-generated or
rushed code. Point it at any repo, get one JSON report. No install, no API keys,
no network, just Python stdlib.

```
python vibe_check.py /path/to/your/repo
```

## Why

If you build with AI assistants, your repos accumulate a specific kind of debt:
code that looks right but is not. A function quietly copy-pasted into three
files. An import that was never added to requirements.txt. A typo'd package
name. A README that reads like a press release. vibe-check catches these in
one pass so you (or your LLM) can see them before they bite.

It is deliberately small enough to read in one sitting. One file. Standard
library only. Runs offline.

## What it checks

| Check | What it catches |
| --- | --- |
| **syntax_errors** | Python files that do not parse (exact, via ast). Other languages are reported as skipped. |
| **duplicates** | Identical code blocks spanning two or more files (test files excluded, repeated fixtures are not drift). |
| **package_risks** | Imports missing from your declared dependencies, and dependency names that look like typosquats of popular packages. |
| **comment_buzzwords** | Marketing fluff in comments (robust, seamless, game-changer, and so on). |
| **readme_hype** | A 0-1 hype score for your markdown, based on buzzword density. |
| **structural** | Giant files (>1000 lines), deep nesting (>5 levels), and circular imports between your own modules. |
| **dead_code** | Stub functions (just pass / ... / raise NotImplementedError) and top-level functions/classes that nothing in the repo references. |

Every check is offline and deterministic, same repo in, same report out.

## Usage

Scan a whole repo:

```
python vibe_check.py /path/to/repo
```

Scan only specific files (and write the report to disk):

```
python vibe_check.py /path/to/repo --files src/a.py src/b.py --out report.json
```

The report is JSON on stdout (or to --out). A summary block at the top gives
you the headline counts at a glance:

```json
"summary": {
  "syntax_errors": 0,
  "duplicate_blocks": 2,
  "package_risks": 0,
  "comment_buzzwords": 0,
  "circular_imports": 0,
  "giant_files": 0,
  "stubs": 0,
  "unreferenced_definitions": 1
}
```

## Demo

This repo includes a runnable demo script at [demo.sh](demo.sh). It creates a
small sample project with intentionally planted issues, then runs vibe-check on
that sample so you can see the scanner catch real findings.

Run the demo:

```
bash demo.sh
```

If you just want the machine-readable output from the demo sample:

```
python vibe_check.py ./sample-project --out sample-report.json
```

Expected summary from the planted sample is similar to:

```json
{
  "syntax_errors": 1,
  "duplicate_blocks": 2,
  "package_risks": 2,
  "comment_buzzwords": 5,
  "circular_imports": 0,
  "giant_files": 0,
  "stubs": 0,
  "unreferenced_definitions": 2
}
```

Record a terminal cast for docs or social:

```
asciinema rec vibe-check-demo.cast -c "bash demo.sh"
```

Then upload the .cast to asciinema.org and embed it in this README, or convert
to a looping GIF:

```
agg vibe-check-demo.cast demo.gif
```

Embed template (replace YOUR_CAST_ID):

```html
<script id="asciicast-YOUR_CAST_ID" src="https://asciinema.org/a/YOUR_CAST_ID.js" async></script>
```

## Using it with an LLM

The whole point is to feed the report into your prompt alongside your code, so
the model knows what to watch for:

> Here are the files I am working on, plus a vibe-check report. Note the duplicate
> block between sync.py and tools.py before you suggest changes.

The model gets awareness of code quality without you having to spot it yourself.

## Optional: pair it with Horos

[Horos](https://horos.onrender.com/) is a deterministic context router. Give it a
repo and a task, and it returns the exact minimal set of files relevant to that
task, with a signed receipt. vibe-check accepts that file list directly:

```
# Horos tells you WHICH files matter for a task.
# vibe-check tells you WHAT IS WRONG with them.
python vibe_check.py /path/to/repo --files $(cat horos_receipt_paths.txt)
```

Horos answers what to look at. vibe-check answers what to watch out for.
Together they hand an LLM a small, relevant, quality-annotated slice of your repo
instead of the whole thing. Horos is entirely optional, vibe-check works
standalone on any repo.

## Scope and honesty

- **Python gets the deepest checks** (real AST parsing, import graph, dependency
cross-reference). JavaScript/TypeScript and other languages get the
language-agnostic checks (duplicates, buzzwords, file size, nesting). Syntax
checking for non-Python files is skipped and reported as skipped, never faked.
- **Package risk is offline by design.** It does not call PyPI or npm. It checks
what it can prove locally: imports vs. declared deps, and typosquat lookalikes.
It will not tell you a package is abandoned or trending. That needs the network
and is out of scope.
- **It favors precision over recall.** Defaults are tuned to avoid crying wolf.
It would rather miss a marginal case than bury a real one in noise.

## License

MIT.
