"""Smoke tests for vibe-check Phase 2 helpers (stdlib only, no third-party deps)."""

import os
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


if __name__ == "__main__":
    unittest.main()
