# Inorganic pipeline: plan (draft, 2026-11-17)

Goal: JEE Advanced inorganic questions (multiple correct, single correct, integer count, numerical) made by
the same question-first pipeline as physical, with every answer fixed by code, not by a model.

## Status (2026-11-19)
- Step 1 (property functions) is done: `core/engine/inorganic/properties.py`, tested in `tests/test_engine_inorganic.py`.
- Changes since this plan was drafted, which the inorganic pipeline follows: the ladder is Granite 4.2 8B →
  GLM-5.3-Flash → MiniMax M3 with the calculator forced; there is no mismatch verifier (answers graded by code;
  a ladder that agrees on another answer sends the question to the `ladder_consensus` review queue); labels are
  GLM-first advanced, top-first advanced_medium, none hard_advanced; one draft per draw; the designer chooses the
  twist and may leave out one formula; a cut-off design is finished; failed calls go on hold, never dropped.
- The concept-book audit (docs/audit_inorganic.md) is approved and applied (2026-10-13).

## What carries over unchanged
Draw → Jev fit → design (hidden link, checklist) → writer → checks → Jev coherence and level → ladder
(Llama 3.3 70B, GLM, Luna) → verifier → Jev refinement → solution → save. The family roster, the router
(OpenRouter first), records (`served_by`), step_by_step.py and every calibration tool, re-run on the 167
real JEE Advanced inorganic questions.

Note (2026-11-18): physical now writes every number as a blank with a range; GPT-6 Luna writes the solving
program from the blanks and code picks the numbers (`docs/PIPELINE.md`). How that carries over to inorganic's
numerical format is to be decided when inorganic is built.

## What is new: the inorganic "engine" (the answer key)
Physical has formulas the code runs; inorganic needs the same: a source of truth for every option.

1. **Reaction graph** (already in the repo: 354 species, 407 reactions, `knowledge/reaction_graph_inorg.json`).
   Chains of 2-4 reactions give "identify X, Y, Z" questions and statements about products
   ("Y is paramagnetic"), whose truth comes from the graph plus the property functions below.
2. **Property functions** (new code, exact, unit-tested): oxidation state; d-electron count; unpaired
   electrons and spin-only magnetic moment (high/low spin by ligand); hybridisation and shape (VSEPR,
   standard coordination geometries); bond order and magnetism from MO (diatomics); CFSE; number of
   geometric and optical isomers for the standard complex types. These make integer-count questions
   ("how many of the following are paramagnetic") and the truth of each MSQ/MCQ statement.
3. **Fact tables** (`core/engine/facts.py`, as physical's fact questions): what code cannot compute
   (colours, uses, named processes), each table checked against the concept book.
4. **Numericals**: stoichiometry and titrations reuse physical's engine steps.

## How a question is checked
The writer names species and statements with placeholders; the engine evaluates every statement (true or
false) and every count, so the answer key is code's. Checks: each option's truth is computed (none left to a
model), at least one option is a trap a careful student could fall for (a known exception: e.g. high vs low
spin), the asked species is not named in the text. Then the ladder solves from the text alone, as now.

## Order of work
1. Property functions + tests (offline, no API cost).
2. Inorganic adapter: draws (graph chains, property sets), writer prompt for MSQ/MCQ/count, statement
   evaluation (offline).
3. Step-by-step run of one question (needs OpenRouter credit).
4. Calibrations on the real inorganic questions: fit, coherence, level, ladder separation (needs credit).
5. Organic, on the same pattern (its own graph and a structure engine).

## Open questions
- Which species and properties first (coordination compounds and p-block are the most asked).
- Whether the ladder's calibration on physical holds for inorganic (step 4 measures it).
