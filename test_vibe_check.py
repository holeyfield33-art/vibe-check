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


if __name__ == "__main__":
    unittest.main()
