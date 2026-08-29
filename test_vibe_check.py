"""Smoke tests for vibe-check Phase 2 helpers (stdlib only, no third-party deps)."""

import os
import json
import subprocess
import sys
import tempfile
import unittest

import vibe_check as vc


def _make_report(hard=None, soft=None, **detail):
    """Build a minimal report shaped like run() output for formatter tests."""
    hard_signals = {
        "syntax_errors": 0, "duplicate_blocks": 0, "package_risks": 0,
        "circular_imports": 0, "stubs": 0,
    }
    soft_signals = {
        "comment_buzzwords": 0, "giant_files": 0,
        "unreferenced_definitions": 0, "readme_hype_files": 0,
    }
    hard_signals.update(hard or {})
    soft_signals.update(soft or {})
    report = {
        "syntax": {"errors": []},
        "duplicates": [],
        "package_risks": {"risks": []},
        "structural": {"circular_imports": []},
        "dead_code": {"unreferenced_definitions": []},
        "summary": {"hard_signals": hard_signals, "soft_signals": soft_signals},
    }
    report.update(detail)
    return report


class TestLLMPrompt(unittest.TestCase):
    def test_clean_report(self):
        prompt = vc._generate_llm_prompt(_make_report())
        self.assertIn("No issues detected", prompt)

    def test_findings_rendered(self):
        report = _make_report(
            hard={"syntax_errors": 1, "package_risks": 1},
            soft={"unreferenced_definitions": 1},
            syntax={"errors": [{"file": "app.py", "line": 12, "msg": "invalid syntax"}]},
            package_risks={"risks": [
                {"name": "requets", "reason": "possible typosquat of 'requests'", "severity": "high"}
            ]},
            dead_code={"unreferenced_definitions": [
                {"kind": "function", "name": "old_helper", "file": "util.py", "line": 4}
            ]},
        )
        prompt = vc._generate_llm_prompt(report)
        self.assertIn("High Priority Issues", prompt)
        self.assertIn("Code Quality Improvements", prompt)
        self.assertIn("app.py:12 - invalid syntax", prompt)
        self.assertIn("requets", prompt)
        self.assertIn("old_helper", prompt)
        self.assertIn("Prompt Action Instructions", prompt)


class TestHTMLReport(unittest.TestCase):
    def test_writes_self_contained_html(self):
        report = _make_report(
            hard={"syntax_errors": 1},
            syntax={"errors": [{"file": "weird<name>.py", "line": 1, "msg": "boom"}]},
        )
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "r.html")
            vc._generate_html_report(report, out)
            with open(out, encoding="utf-8") as f:
                content = f.read()
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("Syntax Errors", content)
        # No external network assets.
        self.assertNotIn("http://", content)
        self.assertNotIn("https://", content)
        # The embedded prompt is HTML-escaped, so the raw '<' from the path must not leak.
        self.assertNotIn("weird<name>.py", content)
        self.assertIn("weird&lt;name&gt;.py", content)


class TestReadGuard(unittest.TestCase):
    def test_normal_text(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write("hello")
            self.assertEqual(vc._read(p), "hello")

    def test_oversized_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "big.log")
            with open(p, "wb") as f:
                f.write(b"a" * (vc.MAX_FILE_SIZE_BYTES + 1))
            self.assertIsNone(vc._read(p))

    def test_binary_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "blob.bin")
            with open(p, "wb") as f:
                f.write(b"MZ\x00\x00binary")
            self.assertIsNone(vc._read(p))


# Idiomatic, well-written Python that earlier versions wrongly flagged. Each pattern
# here caused a real false positive on the `requests` source; these tests lock the fixes.
_CLEAN_INIT = '''\
from .core import PublicThing, helper_used_by_callers

__all__ = ["PublicThing", "helper_used_by_callers"]
'''

_CLEAN_CORE = '''\
from __future__ import annotations
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # type-only import: not a runtime dependency, not a cycle
    from .models import Model

try:
    import ujson as _json  # optional dependency
    HAS_UJSON = True
except ImportError:
    import json as _json
    HAS_UJSON = False
else:
    from ujson import dumps as _dumps  # re-import in else of same optional path


class Readable(Protocol):
    def read(self, n: int = ...) -> bytes: ...   # Protocol body is correctly empty


class Base:
    def send(self, req):
        """Subclasses must implement this. Documented abstract method, not a TODO."""
        raise NotImplementedError

    def __init__(self):   # empty dunder is fine
        pass


def helper_used_by_callers(x):
    return x + 1


class PublicThing:
    def run(self) -> None:
        m: "Model" = None  # noqa: used to keep the TYPE_CHECKING import live
        return None
'''

_CLEAN_MODELS = '''\
def make_model():
    # lazy import to avoid an import cycle - must NOT be reported as circular
    from .core import PublicThing
    return PublicThing()


class Model:
    pass
'''


class TestNoFalsePositivesOnCleanRepo(unittest.TestCase):
    """A repo of legitimate idioms must scan with zero hard-signal false positives."""

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _scan_clean(self):
        with tempfile.TemporaryDirectory() as d:
            pkg = os.path.join(d, "mypkg")
            os.makedirs(pkg)
            self._write(os.path.join(d, "requirements.txt"), "ujson\n")
            self._write(os.path.join(pkg, "__init__.py"), _CLEAN_INIT)
            self._write(os.path.join(pkg, "core.py"), _CLEAN_CORE)
            self._write(os.path.join(pkg, "models.py"), _CLEAN_MODELS)
            return vc.run(d)

    def test_no_false_circular_imports(self):
        self.assertEqual(self._scan_clean()["summary"]["hard_signals"]["circular_imports"], 0)

    def test_no_false_package_risks(self):
        # ujson is declared and only used optionally; nothing should be flagged.
        self.assertEqual(self._scan_clean()["summary"]["hard_signals"]["package_risks"], 0)

    def test_no_false_stubs(self):
        # Protocol method, documented NotImplementedError, empty dunder: none are stubs.
        self.assertEqual(self._scan_clean()["summary"]["hard_signals"]["stubs"], 0)

    def test_public_reexports_not_dead(self):
        # PublicThing / helper_used_by_callers are imported in __init__ -> not dead.
        report = self._scan_clean()
        dead = {d["name"] for d in report["dead_code"]["unreferenced_definitions"]}
        self.assertNotIn("PublicThing", dead)
        self.assertNotIn("helper_used_by_callers", dead)


class TestStillCatchesRealProblems(unittest.TestCase):
    """Precision fixes must not blunt recall: genuine defects are still reported."""

    def test_real_stubs_and_syntax(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bad.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def todo():\n    pass\n\n"
                    "def not_done():\n    raise NotImplementedError\n"  # undocumented -> stub
                )
            with open(os.path.join(d, "broken.py"), "w", encoding="utf-8") as f:
                f.write("def oops(:\n    pass\n")
            report = vc.run(d)
            stub_names = {s["name"] for s in report["dead_code"]["stubs"]}
            self.assertIn("todo", stub_names)
            self.assertIn("not_done", stub_names)
            self.assertEqual(report["summary"]["hard_signals"]["syntax_errors"], 1)

    def test_real_circular_import_still_caught(self):
        with tempfile.TemporaryDirectory() as d:
            # genuine top-level cycle: a <-> b
            with open(os.path.join(d, "a.py"), "w", encoding="utf-8") as f:
                f.write("import b\nx = 1\n")
            with open(os.path.join(d, "b.py"), "w", encoding="utf-8") as f:
                f.write("import a\ny = 2\n")
            report = vc.run(d)
            self.assertGreaterEqual(report["summary"]["hard_signals"]["circular_imports"], 1)


class TestReadmeHypeIgnoresCode(unittest.TestCase):
    """Buzzwords inside code spans are specimens, not prose hype: they must not flag.
    Buzzwords in prose still must. This is the precision tuning that lets a README
    list the words it detects without flagging itself."""

    def _hype(self, md):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
                f.write(md)
            return vc.run(d)["summary"]["readme_hype_files"]

    def test_inline_code_buzzwords_not_flagged(self):
        md = "# Tool\n\nCatches fluff like `robust`, `seamless`, `game-changer`.\n"
        self.assertEqual(self._hype(md), 0)

    def test_fenced_code_buzzwords_not_flagged(self):
        md = "# Tool\n\nExample output:\n\n```\nrobust seamless revolutionary\n```\n"
        self.assertEqual(self._hype(md), 0)

    def test_prose_buzzwords_still_flagged(self):
        md = "# Tool\n\nThis revolutionary, robust, seamless game-changer is powerful.\n"
        self.assertEqual(self._hype(md), 1)

class TestFailOnGate(unittest.TestCase):
    """--fail-on hard returns exit 1 when hard signals exist, 0 otherwise.
    Default (no flag) must always return 0 so existing usage never breaks."""

    def _clean_repo(self, d):
        with open(os.path.join(d, "ok.py"), "w", encoding="utf-8") as f:
            f.write("def add(a, b):\n    return a + b\n")

    def _dirty_repo(self, d):
        # a typosquat is a hard signal
        with open(os.path.join(d, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("requets==2.0.0\n")
        with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
            f.write("import requets\nx = 1\n")

    def test_clean_repo_fail_on_hard_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self._clean_repo(d)
            self.assertEqual(vc.main([d, "--fail-on", "hard"]), 0)

    def test_dirty_repo_fail_on_hard_exits_one(self):
        with tempfile.TemporaryDirectory() as d:
            self._dirty_repo(d)
            self.assertEqual(vc.main([d, "--fail-on", "hard"]), 1)

    def test_dirty_repo_default_exits_zero(self):
        with tempfile.TemporaryDirectory() as d:
            self._dirty_repo(d)
            self.assertEqual(vc.main([d]), 0)

class TestTriagePanel(unittest.TestCase):
    """Floor-gate triage: hard axes are absolute, friction is per-KLOC, disposition
    derives from the worst finding. No scalar score."""

    def _triage(self, files):
        with tempfile.TemporaryDirectory() as d:
            for name, body in files.items():
                p = os.path.join(d, name)
                os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(p) else None
                with open(p, "w", encoding="utf-8") as f:
                    f.write(body)
            return vc.run(d)["triage"]

    def test_clean_repo_fast_track(self):
        t = self._triage({"ok.py": "def add(a, b):\n    return a + b\n"})
        self.assertEqual(t["axes"]["integrity"]["status"], "PASS")
        self.assertEqual(t["axes"]["supply_chain"]["status"], "CLEAN")
        self.assertEqual(t["disposition"], "FAST_TRACK")

    def test_syntax_error_fails_integrity(self):
        t = self._triage({"bad.py": "def broken(:\n    pass\n"})
        self.assertEqual(t["axes"]["integrity"]["status"], "FAIL")
        self.assertEqual(t["disposition"], "DEEP_AUDIT_REQUIRED")

    def test_typosquat_fails_supply_chain(self):
        t = self._triage({"requirements.txt": "requets\n", "a.py": "import requets\n"})
        self.assertEqual(t["axes"]["supply_chain"]["status"], "RISK")
        self.assertEqual(t["disposition"], "DEEP_AUDIT_REQUIRED")

    def test_multinode_cycle_is_observation_not_integrity(self):
        # cycles no longer gate Integrity (basket showed pristine libs trip detection);
        # they are reported as observations with a type label.
        t = self._triage({"a.py": "import b\n", "b.py": "import c\n", "c.py": "import a\n"})
        self.assertEqual(t["axes"]["integrity"]["status"], "PASS")
        self.assertEqual(t["observations"]["circular_imports"]["count"], 1)
        self.assertEqual(t["observations"]["circular_imports"]["cycles"][0]["type"], "top_level")

    def test_no_scalar_score_emitted(self):
        t = self._triage({"ok.py": "def add(a, b):\n    return a + b\n"})
        self.assertNotIn("score", t)


    def test_stdlib_name_collision_no_phantom_cycle(self):
        # `from types import X` is stdlib, not a local types.py - must not forge an edge
        t = self._triage({
            "types.py": "from helper import go\ndef f():\n    return 1\n",
            "helper.py": "from types import TracebackType\ndef go():\n    return 2\n",
        })
        self.assertEqual(t["observations"]["circular_imports"]["count"], 0)

    def test_deferred_late_import_labelled(self):
        # a cycle formed by a bottom-of-file import is tagged deferred_late_import
        t = self._triage({
            "a.py": "class A:\n    pass\nfrom b import B  # late\n",
            "b.py": "from a import A\nclass B:\n    pass\n",
        })
        ci = t["observations"]["circular_imports"]
        self.assertEqual(ci["count"], 1)
        self.assertEqual(ci["cycles"][0]["type"], "deferred_late_import")


    def test_dead_code_note_is_honest_about_under_reporting(self):
        # documents the real limitation: imported-but-never-called is NOT caught
        # (imports count as references). The note must say orphan-scanner / under-report.
        t = self._triage({
            "auth.py": "def validate_token():\n    return True\n",
            "route.py": "from auth import validate_token\ndef handler():\n    return 1\n",
        })
        note = t["observations"]["unreferenced_definitions"]["note"].lower()
        self.assertIn("orphan", note)
        self.assertIn("under-report", note)

    def test_giant_files_split_test_and_source(self):
        big = "x = 1\n" * 1100
        t = self._triage({"src.py": big, "tests/test_big.py": big})
        gf = t["observations"]["giant_files"]
        self.assertEqual(gf["source"], 1)
        self.assertEqual(gf["test"], 1)


class TestDupMergeSubset(unittest.TestCase):
    """F3 regression: adjacent windows whose file-sets are in a subset relationship
    must merge into one block, not inflate the duplicate_blocks count."""

    def test_subset_fileset_windows_merge(self):
        # Simulate the click smoking-gun: window at line N hits {A,B,C,D},
        # window at line N+1 hits {A,B,D} — the second is a strict subset.
        # Before the fix these lived in different groups and never merged.
        raw = [
            {
                "fingerprint": "aaa",
                "tokens": 13,
                "occurrences": [
                    {"file": "a.py", "line": 10, "end_line": 13},
                    {"file": "b.py", "line": 20, "end_line": 23},
                    {"file": "c.py", "line": 30, "end_line": 33},
                    {"file": "d.py", "line": 40, "end_line": 43},
                ],
            },
            {
                "fingerprint": "bbb",
                "tokens": 15,
                "occurrences": [
                    {"file": "a.py", "line": 11, "end_line": 14},  # adjacent to aaa in a.py
                    {"file": "b.py", "line": 21, "end_line": 24},  # adjacent to aaa in b.py
                    {"file": "d.py", "line": 41, "end_line": 44},  # adjacent to aaa in d.py
                    # no c.py — strict subset of aaa's files
                ],
            },
        ]
        merged = vc._merge_duplicate_blocks(raw)
        # Must collapse to exactly 1 merged block, not 2
        self.assertEqual(len(merged), 1)
        files_in_result = {o["file"] for o in merged[0]["occurrences"]}
        # Superset of files is preserved
        self.assertEqual(files_in_result, {"a.py", "b.py", "c.py", "d.py"})

    def test_non_overlapping_same_fileset_stays_separate(self):
        # Two blocks in the same files but far apart: must NOT merge.
        raw = [
            {
                "fingerprint": "ccc",
                "tokens": 12,
                "occurrences": [
                    {"file": "x.py", "line": 1, "end_line": 4},
                    {"file": "y.py", "line": 1, "end_line": 4},
                ],
            },
            {
                "fingerprint": "ddd",
                "tokens": 12,
                "occurrences": [
                    {"file": "x.py", "line": 100, "end_line": 103},
                    {"file": "y.py", "line": 100, "end_line": 103},
                ],
            },
        ]
        merged = vc._merge_duplicate_blocks(raw)
        self.assertEqual(len(merged), 2)

    def test_divergent_filesets_no_subset_stay_separate(self):
        # {X,Y} and {X,Z} — neither is a subset; must not merge even if ranges overlap in X.
        raw = [
            {
                "fingerprint": "eee",
                "tokens": 12,
                "occurrences": [
                    {"file": "x.py", "line": 10, "end_line": 13},
                    {"file": "y.py", "line": 10, "end_line": 13},
                ],
            },
            {
                "fingerprint": "fff",
                "tokens": 12,
                "occurrences": [
                    {"file": "x.py", "line": 11, "end_line": 14},
                    {"file": "z.py", "line": 10, "end_line": 13},
                ],
            },
        ]
        merged = vc._merge_duplicate_blocks(raw)
        self.assertEqual(len(merged), 2)


class TestDocsFileExclusion(unittest.TestCase):
    """F4 regression: docs/conf.py and files under docs/ that import doc-toolchain
    packages must not appear in package_risks as undeclared imports."""

    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_conf_py_import_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requests\n")
            self._write(os.path.join(d, "app.py"), "import requests\n")
            # conf.py imports a docs-only package not in requirements.txt
            self._write(os.path.join(d, "conf.py"),
                        "import pallets_sphinx_themes\nproject = 'myapp'\n")
            report = vc.run(d)
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertNotIn("pallets_sphinx_themes", risk_names)

    def test_docs_dir_import_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requests\n")
            self._write(os.path.join(d, "app.py"), "import requests\n")
            self._write(os.path.join(d, "docs", "conf.py"),
                        "import sphinx_rtd_theme\nproject = 'myapp'\n")
            report = vc.run(d)
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertNotIn("sphinx_rtd_theme", risk_names)

    def test_source_undeclared_still_flagged(self):
        # The exclusion must not suppress genuine supply-chain findings in src files.
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requests\n")
            self._write(os.path.join(d, "app.py"),
                        "import requests\nimport mystery_package\n")
            report = vc.run(d)
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertIn("mystery_package", risk_names)


class TestPyprojectBareDeps(unittest.TestCase):
    """Regression from live-repo benchmarking: pyproject.toml dependencies with
    no version specifier (e.g. `"requests-cache",` with no pin at all) were
    silently dropped from the declared set, because the parsing regex required
    a trailing operator character. A correctly-declared, unpinned dependency
    was then flagged as undeclared - a false positive on perfectly normal
    pyproject.toml style."""

    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_bare_dependency_in_main_list_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "pyproject.toml"),
                        '[project]\ndependencies = [\n    "PyGithub>=2.0",\n'
                        '    "requests-cache",\n    "markdown",\n]\n')
            self._write(os.path.join(d, "app.py"),
                        "import requests_cache\nimport markdown\nimport github\n")
            report = vc.run(d)
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertNotIn("requests_cache", risk_names)
            self.assertNotIn("markdown", risk_names)
            self.assertNotIn("github", risk_names)

    def test_bare_dependency_in_optional_table_not_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "pyproject.toml"),
                        '[project.optional-dependencies]\ndev = [\n    "pytest",\n]\n')
            self._write(os.path.join(d, "app.py"), "import pytest\n")
            report = vc.run(d)
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertNotIn("pytest", risk_names)

    def test_unrelated_quoted_strings_not_swept_in(self):
        # description/readme/license text must not be parsed as dependencies -
        # this would silently suppress a genuinely undeclared import of the
        # same name, which is worse than the bug being fixed.
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "pyproject.toml"),
                        '[project]\nname = "myapp"\n'
                        'description = "Scan and analyze things"\n'
                        'readme = "README.md"\ndependencies = ["requests"]\n')
            self._write(os.path.join(d, "app.py"),
                        "import requests\nimport scan\n")
            report = vc.run(d)
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertIn("scan", risk_names)


class TestImportNameAliases(unittest.TestCase):
    """Regression from live-repo benchmarking: these PyPI packages' import name
    differs from the declared name in a way the alias table didn't cover yet,
    so a correctly-declared dependency was flagged as undeclared."""

    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _check(self, declared_line, import_line):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), declared_line + "\n")
            self._write(os.path.join(d, "app.py"), import_line + "\n")
            report = vc.run(d)
            return {r["name"] for r in report["package_risks"].get("risks", [])}

    def test_python_dotenv_aliases_to_dotenv(self):
        self.assertEqual(self._check("python-dotenv==1.0.1", "import dotenv"), set())

    def test_pygithub_aliases_to_github(self):
        self.assertEqual(self._check("PyGithub>=2.0", "import github"), set())

    def test_pyjwt_aliases_to_jwt(self):
        self.assertEqual(self._check("PyJWT>=2.8.0", "import jwt"), set())

    def test_alpaca_py_aliases_to_alpaca(self):
        self.assertEqual(self._check("alpaca-py==0.37.0", "import alpaca"), set())


class TestEmptyManifestHonesty(unittest.TestCase):
    """Regression: a comment-only/empty requirements.txt (e.g. vibe-check's own
    "# Standard library only ...") was treated as a real manifest that was
    found but yielded no dependencies, reporting the misleading
    "not checked: deps file found but no dependencies parsed". It should be
    treated identically to having no manifest at all."""

    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_comment_only_requirements_stdlib_only(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"),
                        "# Standard library only - no pip packages required.\n")
            self._write(os.path.join(d, "app.py"), "import os\nimport json\n")
            report = vc.run(d)
            self.assertEqual(report["package_risks"]["ecosystems"]["python"],
                              "checked (stdlib-only imports, no manifest needed)")

    def test_comment_only_requirements_with_third_party_import(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"),
                        "# Standard library only - no pip packages required.\n")
            self._write(os.path.join(d, "app.py"), "import requests\n")
            report = vc.run(d)
            self.assertEqual(report["package_risks"]["ecosystems"]["python"],
                              "not checked: no requirements.txt / pyproject.toml found")
            risk_names = {r["name"] for r in report["package_risks"].get("risks", [])}
            self.assertEqual(risk_names, set())


class TestVersion(unittest.TestCase):
    def test_version_string_exists(self):
        self.assertTrue(hasattr(vc, "__version__"))
        self.assertRegex(vc.__version__, r"^\d+\.\d+\.\d+")


class TestFailOnSupplyChain(unittest.TestCase):
    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_supply_chain_exits_one_on_risk(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requets==2.0.0\n")
            self._write(os.path.join(d, "app.py"), "import requets\n")
            self.assertEqual(vc.main([d, "--fail-on", "supply-chain"]), 1)

    def test_supply_chain_exits_zero_when_clean(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requests\n")
            self._write(os.path.join(d, "app.py"), "import requests\n")
            self.assertEqual(vc.main([d, "--fail-on", "supply-chain"]), 0)

    def test_supply_chain_does_not_gate_on_other_hard_signals(self):
        # A syntax error is hard but is NOT a package risk — must exit 0.
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "broken.py"), "def oops(:\n    pass\n")
            self.assertEqual(vc.main([d, "--fail-on", "supply-chain"]), 0)


class TestFormatSummary(unittest.TestCase):
    def test_summary_text_contains_key_sections(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ok.py"), "w") as f:
                f.write("def add(a, b):\n    return a + b\n")
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                vc.main([d, "--format", "summary"])
            text = buf.getvalue()
        self.assertIn("Files scanned", text)
        self.assertIn("Hard signals", text)
        self.assertIn("Soft signals", text)
        self.assertIn("Disposition", text)
        # Must not contain JSON syntax
        self.assertNotIn('"syntax_errors"', text)

    def test_summary_marks_baseline_diff(self):
        report = _make_report()
        report["baseline_diff"] = True
        report["repo"] = "/some/repo"
        report["files_scanned"] = 5
        report["triage"] = {"disposition": "FAST_TRACK"}
        text = vc._generate_summary_text(report)
        self.assertIn("delta vs baseline", text)


class TestBaseline(unittest.TestCase):
    @staticmethod
    def _write(path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_same_scan_delta_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requets\n")
            self._write(os.path.join(d, "app.py"), "import requets\n")
            report = vc.run(d)
            delta = vc._diff_reports(report, report)
            self.assertEqual(delta["summary"]["hard_signals"]["package_risks"], 0)
            self.assertTrue(delta["baseline_diff"])

    def test_new_risk_appears_in_delta(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "requirements.txt"), "requests\n")
            self._write(os.path.join(d, "app.py"), "import requests\n")
            old = vc.run(d)

            self._write(os.path.join(d, "bad.py"), "import mystery_pkg\n")
            new = vc.run(d)
            delta = vc._diff_reports(old, new)
            risk_names = {r["name"] for r in delta["package_risks"].get("risks", [])}
            self.assertIn("mystery_pkg", risk_names)
            self.assertEqual(delta["summary"]["hard_signals"]["package_risks"], 1)

    def test_baseline_flag_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            self._write(os.path.join(d, "app.py"), "import requests\n")
            self._write(os.path.join(d, "requirements.txt"), "requests\n")
            baseline_path = os.path.join(d, "baseline.json")
            # First scan: write baseline
            vc.main([d, "--out", baseline_path])
            # Second scan with same repo: zero new findings
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ret = vc.main([d, "--baseline", baseline_path, "--format", "summary"])
            self.assertEqual(ret, 0)
            self.assertIn("delta vs baseline", buf.getvalue())


class TestSummaryLabelAccuracy(unittest.TestCase):
    """The delta summary must label unreferenced defs as diffed ('new only'),
    because _diff_reports diffs them by identity while the other three soft
    rows stay full-scan values. Regression test for the mislabeled header."""

    def test_full_scan_uses_plain_unreferenced_label(self):
        report = _make_report()
        text = vc._generate_summary_text(report)
        self.assertIn("Unreferenced defs:", text)
        self.assertNotIn("Unreferenced (new):", text)

    def test_delta_scan_marks_unreferenced_as_new_only(self):
        report = _make_report()
        report["baseline_diff"] = True
        text = vc._generate_summary_text(report)
        self.assertIn("Unreferenced (new):", text)
        self.assertNotIn("Unreferenced defs:", text)


class TestBrokenPipeHandling(unittest.TestCase):
    """`vibe-check repo | head` must not spew a traceback, and the --fail-on
    exit-code contract must survive the broken pipe."""

    class _ClosedPipe:
        """A stdout stand-in whose writes raise like a closed pipe."""
        def write(self, s):
            raise BrokenPipeError()
        def flush(self):
            pass

    def _dirty_repo(self, d):
        with open(os.path.join(d, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("requets==2.0.0\n")
        with open(os.path.join(d, "app.py"), "w", encoding="utf-8") as f:
            f.write("import requets\nx = 1\n")

    def test_broken_pipe_is_swallowed_and_exit_is_zero_on_clean_repo(self):
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "ok.py"), "w", encoding="utf-8") as f:
                f.write("def add(a, b):\n    return a + b\n")
            with contextlib.redirect_stdout(self._ClosedPipe()):
                ret = vc.main([d])
            self.assertEqual(ret, 0)

    def test_broken_pipe_preserves_fail_on_exit_code(self):
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            self._dirty_repo(d)
            with contextlib.redirect_stdout(self._ClosedPipe()):
                ret = vc.main([d, "--fail-on", "hard"])
            self.assertEqual(ret, 1)


class TestJSPackageRisks(unittest.TestCase):
    """package.json parsing + import diffing for js/ts (mirrors the Python check)."""

    def _scan(self, files):
        with tempfile.TemporaryDirectory() as d:
            for rel, content in files.items():
                p = os.path.join(d, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(content)
            return vc.run(d)

    def test_undeclared_js_import_flagged(self):
        r = self._scan({
            "package.json": '{"name": "app", "dependencies": {"react": "^18.0.0"}}',
            "src/main.ts": 'import axios from "axios";\nimport React from "react";\n',
        })
        risks = {x["name"]: x for x in r["package_risks"]["risks"]}
        self.assertIn("axios", risks)
        self.assertEqual(risks["axios"]["ecosystem"], "js")
        self.assertNotIn("react", risks)

    def test_relative_alias_builtin_and_workspace_imports_never_flagged(self):
        r = self._scan({
            "package.json": '{"name": "root", "dependencies": {}}',
            "packages/core/package.json": '{"name": "@app/core", "dependencies": {}}',
            "src/a.ts": ('import x from "./local";\n'
                         'import y from "@/aliased";\n'
                         'import fs from "node:fs";\n'
                         'import path from "path";\n'
                         'import core from "@app/core";\n'),
        })
        self.assertEqual(r["package_risks"]["risks"], [])
        self.assertEqual(r["package_risks"]["ecosystems"]["js"], "checked")

    def test_devdeps_and_require_covered(self):
        r = self._scan({
            "package.json": '{"name": "app", "devDependencies": {"vitest": "^1.0.0"}}',
            "src/b.js": 'const v = require("vitest");\nconst missing = require("left-pad");\n',
        })
        names = {x["name"] for x in r["package_risks"]["risks"]}
        self.assertEqual(names, {"left-pad"})


class TestJSUnreferencedExports(unittest.TestCase):
    def _scan(self, files):
        with tempfile.TemporaryDirectory() as d:
            for rel, content in files.items():
                p = os.path.join(d, rel)
                os.makedirs(os.path.dirname(p), exist_ok=True)
                with open(p, "w") as f:
                    f.write(content)
            return vc.run(d)

    def test_orphan_export_flagged(self):
        r = self._scan({
            "src/util.ts": "export function orphanHelper(x: number) { return x; }\n",
            "src/other.ts": "export const used = 1;\n",
            "src/main.ts": 'import { used } from "./other";\nconsole.log(used);\n',
        })
        orphans = {o["name"] for o in r["dead_code"]["unreferenced_exports_js"]}
        self.assertIn("orphanHelper", orphans)
        self.assertNotIn("used", orphans)
        self.assertEqual(r["summary"]["soft_signals"]["unreferenced_exports_js"], 1)

    def test_barrel_reexport_counts_as_referenced(self):
        r = self._scan({
            "src/api.ts": "export function publicApi() { return 1; }\n",
            "src/index.ts": 'export { publicApi } from "./api";\n',
        })
        self.assertEqual(r["dead_code"]["unreferenced_exports_js"], [])

    def test_index_test_and_example_files_never_flagged(self):
        r = self._scan({
            "src/index.ts": "export function entry() { return 1; }\n",
            "src/util.test.ts": "export function fixtureHelper() { return 2; }\n",
            "examples/demo.ts": "export function exampleOnly() { return 3; }\n",
        })
        self.assertEqual(r["dead_code"]["unreferenced_exports_js"], [])


class TestEcosystemHonesty(unittest.TestCase):
    """A package_risks count of 0 must never read as 'pass' for an unchecked ecosystem."""

    def test_ts_repo_without_package_json_says_not_checked(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "app.ts"), "w") as f:
                f.write('import axios from "axios";\n')
            r = vc.run(d)
            self.assertTrue(r["package_risks"]["ecosystems"]["js"].startswith("not checked"))
            text = vc._generate_summary_text(r)
            self.assertIn("not checked: js/ts", text)

    def test_checked_repo_has_no_annotation(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "package.json"), "w") as f:
                f.write('{"name": "app", "dependencies": {}}')
            with open(os.path.join(d, "app.ts"), "w") as f:
                f.write("const x = 1;\n")
            r = vc.run(d)
            self.assertEqual(r["package_risks"]["ecosystems"]["js"], "checked")
            self.assertNotIn("not checked", vc._generate_summary_text(r))


class TestDispositionExplanation(unittest.TestCase):
    def test_fast_track_explanation(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "clean.py"), "w") as f:
                f.write("def main():\n    return 1\n")
            r = vc.run(d)
            self.assertEqual(r["triage"]["disposition"], "FAST_TRACK")
            self.assertIn("no integrity or supply-chain signals",
                          r["triage"]["explanation"])
            self.assertIn(r["triage"]["explanation"], vc._generate_summary_text(r))

    def test_deep_audit_explanation_names_blocker(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "broken.py"), "w") as f:
                f.write("def broken(:\n    pass\n")
            r = vc.run(d)
            self.assertEqual(r["triage"]["disposition"], "DEEP_AUDIT_REQUIRED")
            self.assertIn("syntax error", r["triage"]["explanation"])


class TestDemoReportDrift(unittest.TestCase):
    def test_demo_reports_match_generator(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["VIBE_CHECK_DEMO_OUTDIR"] = tmp
            repo = os.path.dirname(__file__) or "."
            proc = subprocess.run(
                [sys.executable, os.path.join(repo, "scripts", "generate_demo_reports.py")],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
            for name in ("clean", "messy", "supply-chain"):
                with open(os.path.join(tmp, "demo", f"{name}.json"), encoding="utf-8") as fh:
                    generated = json.loads(fh.read())
                with open(os.path.join(repo, "demo", f"{name}.json"), encoding="utf-8") as fh:
                    committed = json.loads(fh.read())
                self.assertEqual(
                    generated,
                    committed,
                    "Demo report drift detected.\nRun: python scripts/generate_demo_reports.py",
                )


if __name__ == "__main__":
    unittest.main()
