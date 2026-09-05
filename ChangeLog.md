# ChangeLog

This file records every repository change. Newest entries go at the top. Each entry lists which files changed, what changed, why when useful, and any behaviour or configuration impact.

## 2026-09-01

### Root cleanup
Removed the stray empty file named `python` from the repository root.
Reason: it was an accidental artifact with zero bytes and no purpose.
Impact: none on behaviour.

Removed `solver_traces.json` from the repository root.
Reason: it was a 103 KB runtime artifact that no script reads. The calibration script reads `calibration/solver_traces.json` instead.
Impact: none. The referenced file in `calibration/` is unchanged.

Removed all `__pycache__` directories.
Reason: they are build artifacts. `.gitignore` already excludes `__pycache__/`.
Impact: none. Python regenerates them on next run.

### Documentation
Added the three maintenance documents required by the repository conventions.
- `ChangeLog.md` records every change. This file.
- `Decisions.md` records why meaningful technical choices were made.
- `Flow.md` describes how the system works and how data moves through it.

Reason: the repository previously kept only the `README.md` design doc. The conventions require all four documents.
Impact: documentation only. No runtime effect.
