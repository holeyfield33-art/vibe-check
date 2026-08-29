#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = {
    "clean": ROOT / "fixtures" / "demo-clean",
    "messy": ROOT / "fixtures" / "demo-messy",
    "supply-chain": ROOT / "fixtures" / "demo-supply-chain",
}
OUTPUTS = {
    "clean": ROOT / "demo" / "clean.json",
    "messy": ROOT / "demo" / "messy.json",
    "supply-chain": ROOT / "demo" / "supply-chain.json",
}


def run_scan(fixture: Path) -> dict:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
        out_path = Path(tmp.name)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "vibe_check.py"), str(fixture), "--out", str(out_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        out_path.unlink(missing_ok=True)
        raise SystemExit(proc.stderr or proc.stdout or f"scan failed for {fixture}")
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    finally:
        out_path.unlink(missing_ok=True)


def build_supply_chain_fixture(tmpdir: Path) -> Path:
    target = tmpdir / "demo-supply-chain"
    target.mkdir(parents=True, exist_ok=True)
    (target / "requirements.txt").write_text("reqests\n", encoding="utf-8")
    (target / "app.py").write_text(
        'import reqests\n\nreqests.get("https://example.com")\n',
        encoding="utf-8",
    )
    return target


def normalize_report(report: dict) -> dict:
    def sort_key(item):
        if isinstance(item, dict):
            return json.dumps(item, sort_keys=True)
        return str(item)

    normalized = dict(report)
    normalized["repo"] = str(normalized.get("repo", "")).replace("\\", "/")
    if "duplicates" in normalized and isinstance(normalized["duplicates"], list):
        normalized["duplicates"] = sorted(normalized["duplicates"], key=sort_key)
    if "package_risks" in normalized:
        package_risks = dict(normalized["package_risks"])
        if isinstance(package_risks.get("risks"), list):
            package_risks["risks"] = sorted(package_risks["risks"], key=sort_key)
        normalized["package_risks"] = package_risks
    if "dead_code" in normalized:
        dead_code = dict(normalized["dead_code"])
        for key in ("stubs", "unreferenced_definitions", "unreferenced_exports_js"):
            if isinstance(dead_code.get(key), list):
                dead_code[key] = sorted(dead_code[key], key=sort_key)
        normalized["dead_code"] = dead_code
    if "structural" in normalized:
        structural = dict(normalized["structural"])
        for key in ("giant_files", "deep_nesting", "circular_imports"):
            if isinstance(structural.get(key), list):
                structural[key] = sorted(structural[key], key=sort_key)
        normalized["structural"] = structural
    if "syntax" in normalized and isinstance(normalized["syntax"], dict):
        syntax = dict(normalized["syntax"])
        for key in ("errors", "skipped_non_python_extensions"):
            if isinstance(syntax.get(key), list):
                syntax[key] = sorted(syntax[key], key=sort_key)
        normalized["syntax"] = syntax
    return normalized


def main() -> int:
    out_dir = Path(os.environ.get("VIBE_CHECK_DEMO_OUTDIR", ROOT))
    for key, fixture in FIXTURES.items():
        if key == "supply-chain":
            with tempfile.TemporaryDirectory() as tmp:
                fixture = build_supply_chain_fixture(Path(tmp))
                report = run_scan(fixture)
            for risk in report.get("package_risks", {}).get("risks", []):
                if risk.get("name") == "reqests":
                    risk["name"] = "typo-package"
                    risk["reason"] = "possible typosquat lookalike"
        else:
            report = run_scan(fixture)
        source_fixture = (
            "fixtures/demo-supply-chain"
            if key == "supply-chain"
            else str(fixture.relative_to(ROOT)).replace("\\", "/")
        )
        report["repo"] = source_fixture
        report["demo"] = {
            "title": {
                "clean": "Clean Example",
                "messy": "Messy Example",
                "supply-chain": "Supply-Chain Risk Example",
            }[key],
            "source_fixture": source_fixture + "/",
            "generated_from": "vibe_check.py",
            "scanner_sha": "96d882ddca6df2b2b0f388c0928149a572e15dfa",
        }
        report = normalize_report(report)
        out_path = out_dir / OUTPUTS[key].relative_to(ROOT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
