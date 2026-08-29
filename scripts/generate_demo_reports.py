#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import os
import tempfile


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
        out_path = out_dir / OUTPUTS[key].relative_to(ROOT)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
