#!/usr/bin/env python3
"""
vibe-check: a zero-dependency code "vibe" scanner.

Point it at any repo. It scans for the things that signal AI-generated or
rushed code, and emits a single JSON report you can read or paste alongside
your source when prompting an LLM.

Six checks, all pure stdlib, all offline:
  1. syntax_errors      - files that don't parse (Python: exact; others: skipped)
  2. duplicates         - near-identical code blocks across files
  3. package_risks      - declared-but-unused / used-but-undeclared / typosquats
  4. comment_buzzwords  - marketing fluff in comments ("robust", "seamless"...)
  5. readme_hype        - same buzzword density across README/markdown
  6. structural         - giant files, deep nesting, circular Python imports

Usage:
    python vibe_check.py /path/to/repo
    python vibe_check.py /path/to/repo --files a.py b/c.py   # only these (Horos receipt)
    python vibe_check.py /path/to/repo --out report.json

Horos integration (optional): pass the `selection[].path` list from a Horos
receipt to --files and vibe-check only scans the slice Horos chose.
"""

import argparse
import ast
import hashlib
import html
import json
import os
import re
import sys
from collections import defaultdict

# --- config -----------------------------------------------------------------

BUZZWORDS = [
    "game-changer", "game changer", "revolutionary", "synergy", "leverage",
    "robust", "seamless", "cutting-edge", "state-of-the-art", "blazing",
    "blazingly", "supercharge", "next-generation", "next-gen", "world-class",
    "effortless", "powerful", "elegant", "simply", "just works", "magic",
]
# Common packages whose names get typo-squatted. (name -> set of risky lookalikes)
TYPOSQUAT_TARGETS = {
    "requests": {"request", "requets", "requestss", "reqests"},
    "numpy": {"numpi", "nampy", "numphy"},
    "pandas": {"panda", "pandass", "pandaa"},
    "beautifulsoup4": {"beautifulsoup", "bs4soup"},
    "python-dateutil": {"dateutils"},
    "pillow": {"pil", "pillows"},
    "scikit-learn": {"sklearn-learn", "scikitlearn"},
}
CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".c", ".cpp", ".h"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target"}
GIANT_FILE_LINES = 1000
DEEP_NEST_LEVELS = 5
DUP_WINDOW = 4          # lines per block compared for duplication
DUP_MIN_TOKENS = 12     # ignore trivially short duplicate blocks
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # strict 2MB ceiling per file


# --- helpers ----------------------------------------------------------------

def _iter_files(root, only=None):
    """Yield (abs_path, rel_path) for code/text files, honoring an optional allowlist."""
    only_set = set(only) if only else None
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            abs_p = os.path.join(dirpath, fn)
            rel_p = os.path.relpath(abs_p, root)
            if only_set is not None and rel_p not in only_set:
                continue
            yield abs_p, rel_p


def _read(path):
    """Safely read text from disk, skipping oversized or binary files.

    Returns None for files over MAX_FILE_SIZE_BYTES, files whose first 1KB
    contains a NUL byte (a dependency-free binary signal), or unreadable files.
    Callers already treat None as "nothing to scan", so this degrades cleanly
    and keeps a beginner's messy directory (huge logs, .pyc, images) from
    spiking memory or stalling the AST parser.
    """
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE_BYTES:
            return None
        with open(path, "rb") as f:
            if b"\x00" in f.read(1024):
                return None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _is_test_file(rel_p):
    """True for files pytest/unittest discover by convention. Test code legitimately
    repeats fixtures, imports test-only servers, and defines functions nothing calls -
    so the duplicate, package, and dead-code checks all skip these to avoid false alarms."""
    rp = rel_p.replace("\\", "/")
    base = os.path.basename(rp).lower()
    return (base.startswith("test_")
            or base.endswith(("_test.py", ".test.ts", ".test.js", ".spec.ts", ".spec.js"))
            or "/tests/" in rp or "/test/" in rp
            or rp.startswith("tests/") or rp.startswith("test/")
            or base == "conftest.py")


# --- output formatters ------------------------------------------------------

def _generate_llm_prompt(report):
    """Formats the internal report findings into a structured prompt
    ready for copy-pasting directly into ChatGPT or Claude."""
    summary = report["summary"]
    hard = summary["hard_signals"]
    soft = summary["soft_signals"]

    total_issues = sum(hard.values()) + sum(soft.values())
    if total_issues == 0:
        return "vibe-check scan complete: No issues detected. Your codebase is clean!"

    prompt = []
    prompt.append("### Codebase Analysis Report")
    prompt.append("The following code quality issues and structural debt were detected. ")
    prompt.append("Please analyze these findings and help me refactor the code to address them.\n")

    # Hard Signals Section
    if any(hard.values()):
        prompt.append("#### High Priority Issues")
        if hard.get("syntax_errors", 0) > 0:
            prompt.append("- **Syntax Errors**: Resolve non-parsing files immediately.")
            for err in report["syntax"]["errors"]:
                prompt.append(f"  * {err['file']}:{err['line']} - {err['msg']}")

        if hard.get("duplicate_blocks", 0) > 0:
            prompt.append("- **Duplicate Blocks**: Extract these overlapping lines into shared utility helper functions:")
            for dup in report["duplicates"][:5]:  # limit output to avoid token inflation
                locations = ", ".join(f"{occ['file']} (L{occ['line']}-{occ['end_line']})" for occ in dup["occurrences"])
                prompt.append(f"  * Common logic (fingerprint: {dup['fingerprint']}) found in: {locations}")

        if hard.get("package_risks", 0) > 0:
            prompt.append("- **Package Risks**: Correct undeclared dependencies and check package spelling:")
            for r in report["package_risks"].get("risks", []):
                prompt.append(f"  * {r['name']} - {r['reason']} ({r['severity']} severity)")

        if hard.get("circular_imports", 0) > 0:
            prompt.append("- **Circular Python Imports**: Decouple the following modules to prevent cyclic runtime issues:")
            for cycle in report["structural"]["circular_imports"]:
                prompt.append(f"  * Cycle between {cycle[0]} <-> {cycle[1]}")
        prompt.append("")

    # Soft Signals Section
    if any(soft.values()):
        prompt.append("#### Code Quality Improvements")
        if soft.get("unreferenced_definitions", 0) > 0:
            prompt.append("- **Possibly Dead Code**: These top-level definitions aren't referenced anywhere *in this repo*. If they're part of your public API (imported by external callers), they're fine - otherwise consider removing them:")
            for u in report["dead_code"]["unreferenced_definitions"][:10]:
                prompt.append(f"  * {u['kind']} '{u['name']}' in {u['file']}:{u['line']} has no in-repo references.")
        prompt.append("")

    prompt.append("#### Prompt Action Instructions")
    prompt.append("1. Propose an implementation plan focusing on the High Priority Issues first.")
    prompt.append("2. Avoid introducing new third-party dependencies while resolving them.")
    prompt.append("3. Present the refactored code adjustments cleanly module by module.")

    return "\n".join(prompt)


def _generate_html_report(report, out_path):
    """Outputs a visual dashboard to a local HTML file without using external network assets."""
    summary = report["summary"]
    hard = summary["hard_signals"]
    soft = summary["soft_signals"]

    # Escape the prompt so file paths / messages containing <, >, & render safely.
    prompt_block = html.escape(_generate_llm_prompt(report))

    html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>vibe-check report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f9fafb; color: #111827; padding: 2rem; margin: 0; }}
        .card {{ background: #fff; border-radius: 8px; border: 1px solid #e5e7eb; padding: 1.5rem; margin-bottom: 1.5rem; }}
        h1 {{ margin-top: 0; font-size: 1.5rem; }}
        .badge {{ display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-weight: bold; font-size: 0.75rem; }}
        .badge-hard {{ background: #fee2e2; color: #991b1b; }}
        .badge-soft {{ background: #fef3c7; color: #92400e; }}
        .stat-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
        .stat-box {{ background: #f3f4f6; border-radius: 6px; padding: 1rem; text-align: center; }}
        .stat-val {{ font-size: 1.8rem; font-weight: bold; margin-bottom: 0.25rem; }}
        .stat-lbl {{ font-size: 0.85rem; color: #4b5563; }}
        pre {{ background: #1f2937; color: #f9fafb; padding: 1rem; border-radius: 6px; overflow-x: auto; font-size: 0.85rem; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <div style="max-width: 900px; margin: 0 auto;">
        <h1>vibe-check report</h1>
        <div class="card">
            <h3>Summary of Findings</h3>
            <div class="stat-grid">
                <div class="stat-box">
                    <div class="stat-val">{hard.get("syntax_errors", 0)}</div>
                    <div class="stat-lbl">Syntax Errors</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val">{hard.get("duplicate_blocks", 0)}</div>
                    <div class="stat-lbl">Duplicate Blocks</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val">{hard.get("package_risks", 0)}</div>
                    <div class="stat-lbl">Package Risks</div>
                </div>
                <div class="stat-box">
                    <div class="stat-val">{soft.get("unreferenced_definitions", 0)}</div>
                    <div class="stat-lbl">Dead Code</div>
                </div>
            </div>
        </div>

        <div class="card">
            <h3>Quick Actions</h3>
            <p>Paste the following generated prompt into Claude or ChatGPT to begin refactoring:</p>
            <pre>{prompt_block}</pre>
        </div>
    </div>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_template)


# --- checks -----------------------------------------------------------------

def check_syntax(files):
    """Python: real ast.parse. Other languages: skipped (honestly reported)."""
    errors = []
    skipped_langs = set()
    for abs_p, rel_p in files:
        ext = os.path.splitext(rel_p)[1]
        if ext != ".py":
            if ext in CODE_EXT:
                skipped_langs.add(ext)
            continue
        src = _read(abs_p)
        if src is None:
            continue
        try:
            ast.parse(src)
        except SyntaxError as e:
            errors.append({"file": rel_p, "line": e.lineno or 0, "msg": e.msg})
    return {"errors": errors, "skipped_non_python_extensions": sorted(skipped_langs)}


def check_duplicates(files):
    """Hash sliding windows of normalized lines; report blocks appearing across 2+
    distinct files. Test files are skipped (repeated fixtures are idiomatic, not drift)."""
    seen = defaultdict(list)  # block_hash -> [(rel_p, start_line, end_line, token_count)]
    for abs_p, rel_p in files:
        if os.path.splitext(rel_p)[1] not in CODE_EXT:
            continue
        if _is_test_file(rel_p):
            continue
        src = _read(abs_p)
        if src is None:
            continue
        lines = [ln.strip() for ln in src.splitlines()]
        # drop blank + comment-only lines from the comparison, keep index map
        meaningful = [(i + 1, ln) for i, ln in enumerate(lines)
                      if ln and not ln.startswith(("#", "//", "*", "/*"))]
        for j in range(len(meaningful) - DUP_WINDOW + 1):
            window = meaningful[j:j + DUP_WINDOW]
            blob = "\n".join(ln for _, ln in window)
            tokens = len(blob.split())
            if tokens < DUP_MIN_TOKENS:
                continue
            h = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
            seen[h].append((rel_p, window[0][0], window[-1][0], tokens))
    dups = []
    for h, hits in seen.items():
        # only a real duplicate if it spans 2+ DISTINCT files
        distinct_files = {f for f, _, _, _ in hits}
        if len(distinct_files) >= 2:
            dups.append({
                "fingerprint": h,
                "tokens": hits[0][3],
                "occurrences": [{"file": f, "line": ln, "end_line": el}
                                for f, ln, el, _ in hits],
            })
    dups.sort(key=lambda d: (-len(d["occurrences"]), -d["tokens"]))
    return dups


def _merge_duplicate_blocks(dups):
    """Report-assembly merge: collapse overlapping/adjacent sliding-window hits into
    one finding per contiguous block per occurrence file-set. The fingerprint-based
    detection above is untouched; this only stitches windows back together so a single
    duplicated region reads as one finding instead of N near-identical rows.

    Two window-hits merge when their line ranges overlap or are adjacent in *every*
    file of the shared file-set. Non-contiguous blocks stay distinct."""
    groups = defaultdict(list)
    for d in dups:
        fileset = frozenset(o["file"] for o in d["occurrences"])
        groups[fileset].append(d)

    merged = []
    for fileset, items in groups.items():
        nodes = []
        for d in items:
            ranges = {}  # file -> [start, end]
            for o in d["occurrences"]:
                s, e = o["line"], o.get("end_line", o["line"])
                if o["file"] in ranges:
                    ps, pe = ranges[o["file"]]
                    ranges[o["file"]] = [min(ps, s), max(pe, e)]
                else:
                    ranges[o["file"]] = [s, e]
            nodes.append({"ranges": ranges, "tokens": d["tokens"],
                          "fingerprints": [d["fingerprint"]]})

        def mergeable(a, b):
            for f in fileset:
                as_, ae = a["ranges"][f]
                bs, be = b["ranges"][f]
                if not (as_ <= be + 1 and bs <= ae + 1):
                    return False
            return True

        changed = True
        while changed:
            changed = False
            out = []
            for node in nodes:
                placed = False
                for ex in out:
                    if mergeable(ex, node):
                        for f in fileset:
                            ns, ne = node["ranges"][f]
                            es, ee = ex["ranges"][f]
                            ex["ranges"][f] = [min(es, ns), max(ee, ne)]
                        ex["tokens"] = max(ex["tokens"], node["tokens"])
                        ex["fingerprints"].extend(node["fingerprints"])
                        placed = True
                        changed = True
                        break
                if not placed:
                    out.append(node)
            nodes = out

        for node in nodes:
            occ = [{"file": f, "line": node["ranges"][f][0],
                    "start_line": node["ranges"][f][0], "end_line": node["ranges"][f][1]}
                   for f in sorted(node["ranges"])]
            merged.append({
                "fingerprint": node["fingerprints"][0],
                "fingerprints": sorted(set(node["fingerprints"])),
                "tokens": node["tokens"],
                "occurrences": occ,
            })
    merged.sort(key=lambda d: (-len(d["occurrences"]), -d["tokens"]))
    return merged


def _parse_python_deps(root):
    """Best-effort declared deps from requirements.txt / pyproject.toml anywhere in the
    tree (deps files often live in a source subdir, not the repo root)."""
    declared = set()
    found_any = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "requirements.txt" in filenames:
            found_any = True
            for ln in (_read(os.path.join(dirpath, "requirements.txt")) or "").splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    name = re.split(r"[=<>!~\[ ]", ln, 1)[0].strip()
                    if name:
                        declared.add(name.lower())
        if "pyproject.toml" in filenames:
            found_any = True
            # naive grep for quoted deps; avoids a toml parser dependency
            for m in re.finditer(r'["\']([A-Za-z0-9_.\-]+)\s*[=<>~!\[]',
                                 _read(os.path.join(dirpath, "pyproject.toml")) or ""):
                declared.add(m.group(1).lower())
    return declared, found_any


def _soft_import_nodes(tree):
    """Return (soft_nodes, soft_names) where:
      - soft_nodes: import-statement AST nodes that are NOT hard runtime imports
      - soft_names: top-level module names that appear in ANY soft context in this file

    Soft contexts (don't execute at module load, so they're not hard deps or cycle edges):
      - inside `if TYPE_CHECKING:` blocks - type hints only
      - inside a `try:` whose handler catches ImportError/ModuleNotFoundError - optional deps
      - inside a function/method body - lazy imports, used precisely to break cycles

    soft_names exists because optional modules are often re-imported in a sibling
    guarded block (e.g. `if has_simplejson: from simplejson import ...`). If a module
    is optional anywhere in a file, every import of it in that file is treated as soft.
    Idiomatic, well-written Python relies on all three patterns.
    """
    soft = set()

    def _catches_import_error(handlers):
        for h in handlers:
            t = h.type
            names = []
            if isinstance(t, ast.Name):
                names = [t.id]
            elif isinstance(t, ast.Tuple):
                names = [e.id for e in t.elts if isinstance(e, ast.Name)]
            if not t:  # bare `except:` swallows ImportError too
                return True
            if any(n in ("ImportError", "ModuleNotFoundError") for n in names):
                return True
        return False

    def _is_type_checking_test(test):
        # matches `TYPE_CHECKING` and `typing.TYPE_CHECKING`
        if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
            return True
        if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
            return True
        return False

    def _mark(node):
        for n in ast.walk(node):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                soft.add(n)

    for node in ast.walk(tree):
        # function-local imports (lazy)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for stmt in node.body:
                _mark(stmt)
        # TYPE_CHECKING blocks
        elif isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for stmt in node.body:
                _mark(stmt)
        # try/except ImportError (optional dependency pattern). The else: branch
        # runs only when the try succeeded, so its imports are part of the same
        # optional path (e.g. `try: import x except ImportError: x=None else: import x.y`).
        elif isinstance(node, ast.Try) and _catches_import_error(node.handlers):
            for stmt in node.body:
                _mark(stmt)
            for stmt in node.orelse:
                _mark(stmt)

    # collect top-level module names that are soft anywhere in this file
    soft_names = set()
    for n in soft:
        if isinstance(n, ast.Import):
            for a in n.names:
                soft_names.add(a.name.split(".")[0].lower())
        elif isinstance(n, ast.ImportFrom) and n.module:
            soft_names.add(n.module.split(".")[0].lower())
    return soft, soft_names


def _imported_python_modules(files):
    """Top-level (hard) imports only. Soft imports (TYPE_CHECKING, try/except
    ImportError, function-local) are excluded so optional and type-only deps are
    not mis-flagged as undeclared."""
    imported = set()
    for abs_p, rel_p in files:
        if not rel_p.endswith(".py"):
            continue
        if _is_test_file(rel_p):
            continue  # test-only imports (fixtures, test servers) aren't prod deps
        src = _read(abs_p)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        soft, soft_names = _soft_import_nodes(tree)
        for node in ast.walk(tree):
            if node in soft:
                continue
            if isinstance(node, ast.Import):
                for n in node.names:
                    base = n.name.split(".")[0].lower()
                    if base not in soft_names:
                        imported.add(base)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                base = node.module.split(".")[0].lower()
                if base not in soft_names:
                    imported.add(base)
    return imported


def check_packages(root, files):
    """High-signal offline package checks: imported-but-undeclared (excluding local
    modules) and typosquat names. Avoids low-signal 'declared but unused' noise for
    tooling that is run, not imported (uvicorn, pytest, etc.)."""
    risks = []
    declared, found_any = _parse_python_deps(root)
    if not found_any:
        return {"risks": [], "note": "no requirements.txt / pyproject.toml found in tree"}
    if not declared:
        return {"risks": [], "note": "deps file found but no dependencies parsed"}
    imported = _imported_python_modules(files)

    # Local module names = every .py file's stem anywhere in the repo. These are
    # first-party imports and must never be flagged as undeclared dependencies.
    local_mods = set()
    for _, rel_p in files:
        if rel_p.endswith(".py"):
            local_mods.add(os.path.basename(rel_p)[:-3].lower())
            parts = rel_p.replace("\\", "/").split("/")
            if len(parts) > 1:
                local_mods.add(parts[-2].lower())  # package dir name

    # Known name<->import aliases so we don't false-positive on legit installs.
    alias = {"beautifulsoup4": "bs4", "pillow": "pil", "scikit-learn": "sklearn",
             "python-dateutil": "dateutil", "pyyaml": "yaml", "argon2-cffi": "argon2",
             "psycopg2-binary": "psycopg2", "python-jose": "jose"}
    declared_import_names = {alias.get(d, d.replace("-", "_")) for d in declared}
    stdlib_guess = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()

    # imported-but-undeclared: the genuinely useful supply-chain signal
    for imp in sorted(imported):
        if imp in stdlib_guess or imp in local_mods:
            continue
        if imp in declared_import_names or imp.replace("_", "-") in declared:
            continue
        risks.append({"name": imp, "reason": "imported but not declared as a dependency",
                      "severity": "medium"})

    # typosquat check on declared names
    for d in declared:
        for target, bads in TYPOSQUAT_TARGETS.items():
            if d in bads:
                risks.append({"name": d, "reason": f"possible typosquat of '{target}'",
                              "severity": "high"})
    return {"risks": risks}


def _scan_buzzwords(text):
    low = text.lower()
    counts = {}
    for w in BUZZWORDS:
        c = low.count(w)
        if c:
            counts[w] = counts.get(w, 0) + c
    return counts


# Matches fenced code blocks (``` ... ```) and inline code spans (`...`). Buzzwords
# inside code are nearly always examples, test data, or specimen output - not prose
# hype - so the markdown hype check strips them first. This is a precision tuning:
# a README that *lists* the words it detects must not flag itself for listing them.
_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]+`")

def _strip_code_spans(text):
    """Remove fenced and inline code from markdown before prose analysis."""
    text = _FENCED_CODE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    return text


def check_comment_buzzwords(files):
    total_comments = 0
    agg = defaultdict(int)
    for abs_p, rel_p in files:
        if os.path.splitext(rel_p)[1] not in CODE_EXT:
            continue
        src = _read(abs_p)
        if src is None:
            continue
        for ln in src.splitlines():
            s = ln.strip()
            if s.startswith(("#", "//", "*", "/*")):
                total_comments += 1
                for w, c in _scan_buzzwords(s).items():
                    agg[w] += c
    buzz_total = sum(agg.values())
    return {
        "total_comment_lines": total_comments,
        "buzzword_count": buzz_total,
        "top_buzzwords": dict(sorted(agg.items(), key=lambda kv: -kv[1])[:10]),
    }


def check_readme_hype(root):
    reports = []
    for abs_p, rel_p in _iter_files(root):
        if not rel_p.lower().endswith(".md"):
            continue
        text = _read(abs_p)
        if not text:
            continue
        # Strip code (fenced + inline) so example/specimen buzzwords inside backticks
        # don't read as prose hype. Word count uses the same stripped text so the
        # density denominator stays honest.
        text = _strip_code_spans(text)
        counts = _scan_buzzwords(text)
        words = max(len(text.split()), 1)
        hype = sum(counts.values())
        # hype score: buzzword occurrences per 100 words, clamped to 0..1
        score = min(hype / (words / 100.0) / 10.0, 1.0) if hype else 0.0
        if hype:
            reports.append({"file": rel_p, "hype_score": round(score, 3),
                            "buzzwords": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:5])})
    return reports


def check_structural(root, files):
    giant, deep = [], []
    for abs_p, rel_p in files:
        if os.path.splitext(rel_p)[1] not in CODE_EXT:
            continue
        src = _read(abs_p)
        if src is None:
            continue
        n = len(src.splitlines())
        if n > GIANT_FILE_LINES:
            giant.append({"file": rel_p, "lines": n})
        depth = len(rel_p.replace("\\", "/").split("/")) - 1
        if depth > DEEP_NEST_LEVELS:
            deep.append({"file": rel_p, "depth": depth})

    # circular Python imports within the repo (intra-repo edges only)
    mod_to_file, edges = {}, defaultdict(set)
    py = [(a, r) for a, r in files if r.endswith(".py")]
    for abs_p, rel_p in py:
        mod = rel_p[:-3].replace("\\", "/").replace("/", ".")
        mod_to_file[mod] = rel_p
        mod_to_file[mod.split(".")[-1]] = rel_p  # also bare module name
    for abs_p, rel_p in py:
        src = _read(abs_p)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        this_mod = rel_p[:-3].replace("\\", "/").replace("/", ".")
        soft, _soft_names = _soft_import_nodes(tree)
        for node in ast.walk(tree):
            if node in soft:
                continue  # lazy / type-only / optional imports don't create runtime cycles
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for nm in names:
                for cand in (nm, nm.split(".")[-1]):
                    if cand in mod_to_file:
                        edges[this_mod].add(mod_to_file[cand][:-3].replace("/", "."))
    cycles = []
    for a in edges:
        for b in edges[a]:
            if b != a and a in edges.get(b, set()):
                pair = tuple(sorted((mod_to_file.get(a, a), mod_to_file.get(b, b))))
                if pair not in [tuple(sorted(c)) for c in cycles]:
                    cycles.append([pair[0], pair[1]])
    return {"giant_files": giant, "deep_nesting": deep, "circular_imports": cycles}


def check_dead_code(files):
    """Two Python checks via AST:
      - stubs: functions whose body is only pass / ... / raise NotImplementedError
        / a bare docstring. Unfinished scaffolding an agent left behind.
      - unreferenced: top-level functions/classes defined but never named anywhere
        else in the repo (no route to them). Entrypoints, dunder methods, test
        functions, and decorated callables are whitelisted to avoid false positives
        (frameworks call those, not code).
    """
    py = [(a, r) for a, r in files if r.endswith(".py")]

    defs = []           # {name, file, line, kind, decorated}
    referenced = set()  # every identifier used as a Name or Attribute anywhere
    stubs = []

    for abs_p, rel_p in py:
        src = _read(abs_p)
        if src is None:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        # references: any Name load or attribute access by that identifier
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
            # a name imported elsewhere in the repo (`from .auth import HTTPProxyAuth`)
            # is a real reference / public re-export, even if never called in-tree.
            elif isinstance(node, ast.ImportFrom):
                for n in node.names:
                    referenced.add((n.asname or n.name).split(".")[0])
            elif isinstance(node, ast.Import):
                for n in node.names:
                    referenced.add((n.asname or n.name).split(".")[0])

        # __all__ exports count as references (AST, not regex): a name in __all__ is
        # a public export with no in-repo call site, so it must not read as dead.
        # Precedence: a module that defines __all__ is honored as-is. Only a module
        # WITHOUT __all__ falls back to plain dead-code rules for its top-level defs
        # (we never blanket-exempt __init__.py defs - that would hide real dead code).
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AugAssign):
                targets = [stmt.target]
            else:
                continue
            if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                continue
            val = stmt.value
            if isinstance(val, (ast.List, ast.Tuple)):
                for elt in val.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        referenced.add(elt.value)

        # __all__ exports count as references (AST, not regex): a name in __all__ is
        # a public export with no in-repo call site, so it must not read as dead.
        # Precedence: a module that defines __all__ is honored as-is. Only a module
        # WITHOUT __all__ falls back to plain dead-code rules for its top-level defs
        # (we never blanket-exempt __init__.py defs - that would hide real dead code).
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                targets = stmt.targets
            elif isinstance(stmt, ast.AugAssign):
                targets = [stmt.target]
            else:
                continue
            if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                continue
            val = stmt.value
            if isinstance(val, (ast.List, ast.Tuple)):
                for elt in val.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        referenced.add(elt.value)

        # definitions + stub detection
        # track only MODULE-LEVEL defs for the unreferenced check (methods are
        # called via self/cls and are too false-positive-prone to flag).
        top_level_names = {n.name for n in tree.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

        # Functions inside a Protocol/ABC class have intentionally-empty bodies
        # (`...` defines the interface). Collect them so they're not read as stubs.
        interface_method_nodes = set()
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            base_names = []
            for b in cls.bases:
                if isinstance(b, ast.Name):
                    base_names.append(b.id)
                elif isinstance(b, ast.Attribute):
                    base_names.append(b.attr)
                elif isinstance(b, ast.Subscript):  # Protocol[T]
                    v = b.value
                    if isinstance(v, ast.Name):
                        base_names.append(v.id)
                    elif isinstance(v, ast.Attribute):
                        base_names.append(v.attr)
            if any(n in ("Protocol", "ABC", "ABCMeta") for n in base_names):
                for sub in ast.walk(cls):
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        interface_method_nodes.add(sub)

        # Stubs in test files are test helpers (RegHandle.Close, hook callbacks),
        # not abandoned production scaffolding - don't report them.
        stub_scan_enabled = not _is_test_file(rel_p)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                decorated = bool(node.decorator_list)
                is_top_level = node.name in top_level_names and any(
                    n is node for n in tree.body)
                defs.append({"name": node.name, "file": rel_p, "line": node.lineno,
                             "kind": kind, "decorated": decorated,
                             "top_level": is_top_level})
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and stub_scan_enabled and node not in interface_method_nodes):
                    # decorated empty bodies are idiomatic, not abandoned scaffolding:
                    # @overload / @abstractmethod / @property and Protocol signatures
                    # legitimately use `...` or a docstring as their entire body.
                    deco_names = []
                    for dctr in node.decorator_list:
                        if isinstance(dctr, ast.Name):
                            deco_names.append(dctr.id)
                        elif isinstance(dctr, ast.Attribute):
                            deco_names.append(dctr.attr)
                        elif isinstance(dctr, ast.Call):
                            f = dctr.func
                            if isinstance(f, ast.Name):
                                deco_names.append(f.id)
                            elif isinstance(f, ast.Attribute):
                                deco_names.append(f.attr)
                    is_dunder = node.name.startswith("__") and node.name.endswith("__")
                    # A decorated empty body (@overload / @abstractmethod / @property)
                    # or an empty dunder is correct code, not a TODO an agent abandoned.
                    if deco_names or is_dunder:
                        continue
                    body = node.body
                    has_docstring = (body and isinstance(body[0], ast.Expr)
                                     and isinstance(getattr(body[0], "value", None), ast.Constant)
                                     and isinstance(body[0].value.value, str))
                    real = body[1:] if has_docstring else body
                    is_stub = False
                    if not real:
                        # docstring-only or truly empty. A docstring-only body is a
                        # deliberate placeholder/interface; only flag the truly empty.
                        is_stub = not has_docstring
                    elif len(real) == 1:
                        only = real[0]
                        if isinstance(only, ast.Pass):
                            is_stub = True
                        elif (isinstance(only, ast.Expr)
                              and isinstance(getattr(only, "value", None), ast.Constant)
                              and only.value.value is Ellipsis):
                            is_stub = True
                        elif isinstance(only, ast.Raise):
                            exc = only.exc
                            exc_name = ""
                            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                                exc_name = exc.func.id
                            elif isinstance(exc, ast.Name):
                                exc_name = exc.id
                            # `raise NotImplementedError` with a real docstring is a
                            # deliberate abstract/disabled method (e.g. a base class
                            # meant to be overridden), not an abandoned TODO. Only an
                            # *undocumented* one reads as left-behind scaffolding.
                            if exc_name == "NotImplementedError" and not has_docstring:
                                is_stub = True
                    if is_stub:
                        stubs.append({"name": node.name, "file": rel_p, "line": node.lineno})

    # unreferenced top-level defs (no route to them)
    WHITELIST_NAMES = {"main", "__init__", "__call__", "__enter__", "__exit__",
                       "setup", "teardown", "lifespan"}
    stub_names = {s["name"] for s in stubs}
    unreferenced = []
    for d in defs:
        nm = d["name"]
        if not d.get("top_level"):
            continue  # methods/nested funcs excluded - called via self/cls
        # test files: pytest discovers Test* classes and test_* funcs by name
        # convention, never by code reference. Never flag them as dead.
        if _is_test_file(d["file"]):
            continue
        if nm.startswith("Test"):
            continue  # pytest class convention
        if nm.startswith("test_") or nm.startswith("_") or nm in WHITELIST_NAMES:
            continue
        if d["decorated"]:
            continue  # route handlers, fixtures, CLI commands, etc.
        if nm in stub_names:
            continue  # already reported as a stub (more specific finding)
        if nm not in referenced:
            unreferenced.append({"name": nm, "file": d["file"], "line": d["line"],
                                 "kind": d["kind"]})

    return {"stubs": stubs, "unreferenced_definitions": unreferenced}


# --- main -------------------------------------------------------------------

def run(root, only=None):
    # Horos fallback: --files is optional refinement, never a precondition. When the
    # slice is absent, empty, or resolves to nothing on disk, scan the whole tree.
    # We never exit empty-handed because a Horos slice came back empty.
    scoped = list(only) if only else None
    files = list(_iter_files(root, only=scoped)) if scoped else list(_iter_files(root))
    if scoped and not files:
        files = list(_iter_files(root))
        scoped = None  # the slice resolved to nothing; reflect the full-scan fallback

    report = {
        "repo": os.path.abspath(root),
        "files_scanned": len(files),
        "scoped_to_files": scoped,
        "syntax": check_syntax(files),
        "duplicates": _merge_duplicate_blocks(check_duplicates(files)),
        "package_risks": check_packages(root, files),
        "comment_buzzwords": check_comment_buzzwords(files),
        "readme_hype": check_readme_hype(root),
        "structural": check_structural(root, files),
        "dead_code": check_dead_code(files),
    }

    # Headline numbers, split into hard signals (concrete defects) and soft signals
    # (stylistic / heuristic). The flat keys are retained alongside for backward-compat:
    # the schema is the contract, so existing consumers keep working.
    hard_signals = {
        "syntax_errors": len(report["syntax"]["errors"]),
        "duplicate_blocks": len(report["duplicates"]),
        "package_risks": len(report["package_risks"].get("risks", [])),
        "circular_imports": len(report["structural"]["circular_imports"]),
        "stubs": len(report["dead_code"]["stubs"]),
    }
    soft_signals = {
        "comment_buzzwords": report["comment_buzzwords"]["buzzword_count"],
        "giant_files": len(report["structural"]["giant_files"]),
        "unreferenced_definitions": len(report["dead_code"]["unreferenced_definitions"]),
        "readme_hype_files": len(report["readme_hype"]),
    }
    report["summary"] = {
        "hard_signals": hard_signals,
        "soft_signals": soft_signals,
        # --- flat keys (backward-compat) ---
        "syntax_errors": hard_signals["syntax_errors"],
        "duplicate_blocks": hard_signals["duplicate_blocks"],
        "package_risks": hard_signals["package_risks"],
        "comment_buzzwords": soft_signals["comment_buzzwords"],
        "circular_imports": hard_signals["circular_imports"],
        "giant_files": soft_signals["giant_files"],
        "stubs": hard_signals["stubs"],
        "unreferenced_definitions": soft_signals["unreferenced_definitions"],
        "readme_hype_files": soft_signals["readme_hype_files"],
    }
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Zero-dependency code vibe scanner.")
    p.add_argument("repo", help="path to the repository root")
    p.add_argument("--files", nargs="*", default=None,
                   help="optional allowlist of repo-relative paths (e.g. a Horos receipt selection)")
    p.add_argument("--out", default=None, help="write JSON report to this path instead of stdout")
    p.add_argument("--html", default=None, help="also write a self-contained HTML dashboard to this path")
    p.add_argument("--format", choices=["json", "prompt"], default="json",
                   help="stdout format: 'json' (default) or 'prompt' (copy-paste LLM prompt)")
    args = p.parse_args(argv)

    if not os.path.isdir(args.repo):
        p.error(f"not a directory: {args.repo}")
    report = run(args.repo, only=args.files)

    if args.html:
        _generate_html_report(report, args.html)
        print(f"HTML report written to {args.html}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(json.dumps(report, indent=2))
        print(f"report written to {args.out}")

    # Decide what goes to stdout.
    if args.format == "prompt":
        print(_generate_llm_prompt(report))
    elif args.out:
        # Legacy behavior: when writing JSON to a file, echo the summary, not the full blob.
        print(json.dumps(report["summary"], indent=2))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
