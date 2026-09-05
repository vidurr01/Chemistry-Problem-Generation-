# Decisions

This file records the reasoning behind meaningful technical choices. Each entry explains why an implementation was chosen, not just what was implemented.

## Use a single per-subject config file

Date: 2026-09-01
Context: the pipeline supports organic, inorganic, and physical chemistry. Each subject needs its own concept book, seed file, norm stats, default chapter, and filtering field.
Decision: `subject_config.py` is the single source of truth for per-subject settings. All entrypoints read from it.
Alternatives: pass every value as a CLI flag, or hard-code each subject in each entrypoint.
Trade-off: a shared config avoids duplicated and drifting settings. It adds one indirection when tracing a value.

## Store per-subject norm stats, not one global set

Date: 2026-09-01
Context: the six difficulty meta-tags are computed as z-scores against a calibration corpus. A global corpus mixes subjects and distorts the baselines.
Decision: each subject has its own `meta_tag_norm_stats_<subject>.json` in `data/seeds/`. `core/meta_tags.py` accepts a `norm_stats_path` so the caller picks the right one.
Alternatives: reuse the organic corpus for every subject.
Trade-off: separate files cost a little storage. They keep each subject's difficulty labels calibrated to its own distribution.

## Use a hard difficulty gate rather than a soft target

Date: 2026-09-01
Context: an item is accepted only when it is both solvable by a strong model and hard for a weak model.
Decision: accept only when the strong solver scores at least 85 and the weak solver scores at most 60, and the verifier passes. Calibrated in `calibration/calibrate_thresholds*.py`.
Alternatives: accept a wide band and sort items afterwards.
Trade-off: the hard gate rejects borderline items. It keeps the accepted set clean for benchmarking.

## Map the four raw archetypes onto subject buckets for calibration

Date: 2026-09-01
Context: the raw JEE Advanced data uses the organic four-taxonomy archetype names. The inorganic and physical calibration scripts expect a six-taxonomy set per subject.
Decision: add a `RAW_ARCHETYPE_FALLBACK` map in `calibrate_thresholds_inorganic.py` and `calibrate_thresholds_physical.py`. Each raw name maps to the nearest subject bucket.
Alternatives: leave the scripts returning an empty sample.
Trade-off: the mapping is a judgement call. Buckets with no raw match warn and are skipped. This lets a re-run produce a stratified sample instead of nothing.

## Real pipeline logic lives in the entrypoints

Date: 2026-09-01
Context: some `core/` modules are reference stubs, while the live generation logic is defined inline in `run_*_final.py`.
Decision: keep the entrypoints as the live source of truth and leave the `core/` modules as reference implementations.
Alternatives: move the logic into `core/` and call it.
Trade-off: the current split is a known debt. The entrypoints work end to end. Consolidating into `core/` is a future refactor, noted in the README.

## Encode files as UTF-8 and reconfigure the console

Date: 2026-09-01
Context: the repository uses box-drawing and arrow characters. The default Windows console code page 1252 cannot encode them.
Decision: open data files with `encoding="utf-8"` and call `sys.stdout.reconfigure(encoding="utf-8")` in scripts that print them.
Alternatives: strip non-ASCII characters.
Trade-off: keeping the characters preserves the diagrams. It requires the reconfigure call in each script that prints them.
