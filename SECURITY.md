# Security Policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting: **Security tab -> Report a
vulnerability** on this repository. Please do not open public issues for
security reports.

## Scope

vibe-check runs offline, has zero dependencies, and makes no network calls.
The realistic security surface is:

1. **Malicious pull requests** against this repo (especially anything touching
   `.github/workflows/`, adding a dependency, or adding a network call — all
   three are declared out of scope in CONTRIBUTING.md, so any diff containing
   them is treated as hostile until proven otherwise).
2. **Compromise of the CI pipeline.** Mitigations in place: the workflow token
   is read-only (`permissions: contents: read`) and all actions are pinned to
   full commit SHAs.
3. **A hostile scanned repository.** vibe-check parses untrusted input by
   design — any repo someone points it at. Crafted file contents that crash
   the scanner, hang it, or make it emit wildly wrong results are valid
   security reports, because people gate CI with this tool's exit code.

## Response

This is a solo-maintainer project. You will get an acknowledgment within
7 days and a best-effort fix timeline in that acknowledgment.
