# Implementation spec — agreed changes (2026-11-25)

Hand this file to the agent that implements the changes. It lists what was agreed in the 25 Nov review
(Vidur's coworker + Claude), why, where in the code, and how to tell it is done. Background:
`docs/redesign_plan_2026-11-25.md` (post-mortem) and `docs/what_we_tried.md`.

---

## 0. Ground rules for the implementing agent

- **Read first:** `docs/ChangeLog.md` (top), `core/pipeline/flow.py` (`_judge`), `core/models.py` (`LADDER`).
- **Shared grading changes (§1–§3) touch `flow.judge`, which all three subjects use.** Confirm with Vidur
  (the author) before merging them; earlier sessions kept subject work out of shared code.
- **One change at a time:** build, test offline, then the next. Run `tools/audit_engine.py --run` and the unit
  tests before any live run, so no paid run rediscovers a known bug.
- **Live runs:** price each call from the real model first, show the estimate in ₹ (state the rate), set a hard
  cap (`generate_questions.py --max-spend`). Run one question, inspect it by hand, fix, repeat.
- **Never drop a question that crashed:** put it in the on-hold queue so it can be re-run.
- **No JEE content in generation:** real JEE questions are a yardstick only, never a template.
- **Unknown species are written `<N>`** (not a bare letter that could read as an element).
- **Git:** tag a rollback point, commit straight to `main`, add a ChangeLog entry per change.
- **Do not reintroduce** what was rejected: a judge model that decides correctness, model councils,
  multi-sample disagreement scoring, student-persona prompts, "evolve the question harder", fact-frequency
  counts from past papers/NCERT, heavy human review.

---

## 1. Why: the four wrong questions, and what let them through

| Question | What was wrong | Root cause |
|---|---|---|
| physical `GEN_20261125T022806` (N₂O₄, key 364.9 K) | Reverse rate constant of a 2nd-order step printed in s⁻¹; the program put k_f/k_b (a K_c) straight into K_p = K_x·P^Δn. With concentration units the answer is ≈310.6 K; with pressure units 364.9 K would be right. | The coder model (GPT-6 Luna) wired steps freely; nothing checked a value's role (K_c vs K_p) or a rate constant's units against its order. |
| physical `GEN_20261125T031247` (Fe²⁺/Ce⁴⁺, key 0.372) | K from rate constants = 7.6 × 10⁷, K from E° = 1.05 × 10¹²: the data contradict. The E°-only route gives ≈2.7 × 10⁻⁵. | Values drawn separately; no check that two routes to one quantity agree. **GLM raised an objection ("data are internally inconsistent") and the pipeline only logged it.** |
| physical `GEN_20261125T041311` (alkali metal, key 24.4) | 24.4 g mol⁻¹ is no alkali metal (Na 23.0, K 39.1). | Numbers picked at random, then solved backwards; no check that the answer is a real element. **Granite wrote "close to Na… answer ~23.0" and was graded as failing.** |
| organic `GEN_20261125T032721` (rejected by hand) | Ag⁺ (Hunsdiecker step) also ionises a 3° benzylic C–Br; Zn dust also attacks the benzylic CH₂Br: no single product. | Engine rule scope gap; fixed 25 Nov. |

**Why the pipeline accepted them:** grading compares each solver's answer with the engine's key by code, and the
key is the only truth. A solver that answers *correctly* against a wrong key is scored as failing, and failing
reads as "hard": all three physical ones were labelled Advanced. Objections and remarks in the working were
never acted on. The solution checks (`core/solution_check.py`, the Haiku solution checker) only confirm that the
written solution agrees with the key.

**Already done (committed, wired in `core/pipeline/qfirst.py:234`):** `core/pipeline/qf_checks.py`
`role_problems` (K_c into a K_p slot), `consistency_problems` (two routes to ΔH°/ΔS° disagree),
`answer_real_problems` (asked element must exist). Tests: `tests/test_qf_trace_checks.py`. They catch all three
physical cases on 65 traced questions with no false flags. **Not covered: a rate constant's units against its
order** (§4).

**Still to decide (ask Vidur):** the three wrong physical questions are still in
`results/generated_questions_physical_final.json`; move them to `results/rejected.json`.

---

## 2. Change A — trace checker on ladder failures (shared, all subjects)

**Goal:** know *why* each ladder model failed, so only real difficulty counts, and flawed questions are caught.

Where: `core/pipeline/flow.py`, `_judge` (after `solve_and_grade`, before the decision), plus a new
`core/pipeline/trace_check.py`.

Logic, per ladder member whose answer does not match the key:

1. **Answer equals a saved wrong turn** (`result.traps[*].wrong_answer`, within `CONSENSUS_TOL`): label `trap`.
   No model call. Counts as a genuine failure (difficulty).
2. **Otherwise run the checker model once** on the stem, the key, the engine trace, and the member's full
   working. It returns exactly one label plus a short quoted reason:
   - `concept` — missed the hidden step / a real concept error. Counts as a genuine failure.
   - `hallucination` — invented or misremembered a fact, misread the question.
   - `too_long` — each step it did was right, but it lost track across too many states/items.
   - `slip` — arithmetic or copying error.
   - `question_flawed` — the member's answer is a defensible reading of a flawed question (e.g. "24.4 is no
     alkali metal, so Na, 23"), or it shows the data contradict, or the units/roles are ambiguous.
3. **Code checks the quote** is really in the working (reuse the quote-check idea from `solution_check.py`).
   A label whose quote is not found is discarded and the member counts as an unexplained failure (not hard).

Decisions:

- `question_flawed` from any member, or a `hallucination` traced to the *question* → **hold the question and
  regenerate** (queue reason `question_flawed`, new in `core/pipeline/queues.py`). The member is not counted as
  failing. "We don't take chances."
- Only `trap` and `concept` count toward "hard". `too_long`, `slip`, `hallucination` (solver's own) do not
  make a question harder; if Granite's only failures are these, treat the question as **not measured as hard**
  (same handling as `too_easy`).
- **The checker never confirms the key.** It can only raise a flag, and a flag means regenerate.
- Store per member: `failure_label`, `failure_quote`, `failure_reason`, beside the existing
  `answer_matches` (raw code fact, never overwritten) and `counts_as_solved`.

Model: a cheap model not used elsewhere in the run (the ladder is IBM, Z.ai, MiniMax; the coder is GPT-6 Luna;
the solution checker is Claude Haiku). Pick one, price it in ₹, and say which.

Done when: offline replay on the three wrong physical questions' stored ladder records labels 031247 and
041311 `question_flawed`; a unit test feeds a working that equals a trap answer and gets `trap` with no model
call; existing tests pass.

---

## 3. Change B — objections and multiple answers (shared)

**Objections hold the question.** Solvers already return `objection` (`core/pipeline/stages.py` ~351, parsed
~416). Today `flow.py` ~496 only prints "kept in the record". Change: an objection of type `chemistry` →
go straight to the `question_flawed` path (hold + regenerate) without a checker call. `wording` objections →
the existing reword path.

**Multiple answers: for grading fairness only, never in the dataset.**
- Each solver gives exactly one final answer (no hedged lists; keep the current one-answer spec).
- When the checker labels a member `question_flawed` because its answer is a defensible alternative, that
  member is not graded as failing (§2), and the question is regenerated with one unambiguous key.
- Never store a second accepted key on a question.

Done when: replaying 031247's record (GLM's objection) holds the question; a test confirms an accepted
question never carries two keys.

---

## 4. Change C — physical: typed quantities and printed units

Keep: three-chapter questions (kinetics + equilibrium + thermodynamics is a common real pattern), the
hidden-step design (`qf_design.py`) and the shortcut check (`qf_shortcut.py`, uncommitted improvements in the
working tree), `fact_share = 0.0`.

Add:
1. **Rate-constant units vs order.** A value produced as a rate constant carries its reaction order; a
   2nd-order constant must be printed in L mol⁻¹ s⁻¹ or atm⁻¹ s⁻¹, never s⁻¹. Refuse the question otherwise.
   Put it next to `role_problems` in `core/pipeline/qf_checks.py`.
2. **Units are written by code, not the writer model.** The unit printed for each given value comes from its
   engine role (and order). The writer may not type units for given values.
3. **K_c → K_p conversion is an engine step.** If a K_c reaches a K_p input, the engine inserts
   K_p = K_c(RT)^Δn (and states R in the question) or refuses; the coder cannot wire it directly.

4. **Check every value the program computes, not only engine-step inputs/outputs (highest priority in §4).**
   Found on a question generated on another laptop (Cu + Ag co-deposition, key 95400 J, labelled
   advanced_medium): 3.05 A for 126 min is 23,058 C, so any Cu/Ag deposit weighs 7.59–25.8 g, but the question
   says 6.62 g. The program split the charge between Cu and Ag in plain Python and got Q_Ag ≈ −1,223 C; the
   question was accepted because MiniMax M3 repeated the same algebra.
   Confirmed in code: `sandbox._make_step` runs `check_kind` only on a step's inputs and its answer;
   `sandbox._search` (the number picker, `qf_numbers.pick_numbers`) accepts the first value set that runs
   without an exception, and the trace holds only step calls (`ctx.calls`). Plain-Python values between steps
   are never checked. Offline probe (scratchpad `cuag_probe.py`, same numbers): the negative share used only in
   plain Python → `ok: True`, answer 93490; the same value passed to `step_234` (Faraday) → refused
   ("input charge must be > 0"). The writer's ranges are not the cause: values are drawn independently by
   design, and the engine is meant to refuse impossible sets.
   **4a. Safety net: check every computed value — BUILT 2026-11-25** (`core/engine/sandbox.py`:
   `value_kind`, `check_value`, `_CheckAssigned`, `_instrumented`; called from `_run_once`).
   - Every name the program assigns is checked after the assignment, on the program's real run only (not
     solve_for trial values, not trap/relevance perturbations).
   - The kind comes from the name: amounts (charge, mass, moles, n, V, P, conc, current, time, …) ≥ 0;
     `alpha…`, `frac…`, `share…` in [0, 1]; `T…`/`temp…` > 0 K; Q tied to an element symbol (Q_Ag) is a
     charge. Names with a change/difference token (dH, delta_n, n_diff, slope, excess) or an unclear one
     (bare Q, q_rev) are not checked.
   - A failure raises "the stated values contradict each other"; `_search` skips that value set.
   - Measured: 26 saved physical programs replay with no false flag (one false flag, `density_alpha`, fixed:
     alpha is a fraction only as the first token). Same Cu/Ag-style program over 20 seeds: old code accepted
     11 impossible value sets, new code 0. Tests `tests/test_sandbox_value_checks.py`.
   - Limit: it depends on names. A program that calls the silver charge `x2` is not checked. 4c closes that.

   **4b. Answer first: aim the answer into answer_range — BUILT 2026-11-25** (`sandbox._aim`, used in
   `_search`). When a drawn set's answer falls outside answer_range, a target is drawn inside the range and one
   range value is solved so the answer hits it (scan its range, bisect); a set the program refuses is not a
   solution, so the solved value also lands where the data are possible. Same test program: draws needed fell
   from a median of about 8 to about 3, all in range, none impossible. `AIM_VALUES = 0` turns it off.

   **4c. Draw the free choices, compute the rest — NOT BUILT (needs prompt changes + one live run).**
   The main fix: impossible data cannot be drawn at all.
   - Writer: a stated value that follows from others (the deposit's mass follows from current, time and
     copper's share of the charge) is marked `derived` and gets no range; the hidden free choice it depends on
     (`share_Cu` in [0, 1]) gets a range instead. `qf_writer.parse_values`/`blank_spec` carry the new field.
   - Coder: writes `derive()` next to `solve()`, computing every derived value from the free choices with
     engine steps only (step inputs are kind-checked, so a negative share cannot pass).
   - Number step (`qf_numbers.pick_numbers` → `sandbox._search`): draw free choices, run `derive()`, print the
     derived values rounded to 3 figures, then run `solve()` on the printed values (the question as the
     student sees it) and apply all existing checks.
   - Done when: the Cu/Ag case written this way never yields a mass outside 7.59–25.8 g over 200 draws, and one
     live physical question (₹ estimate and cap first) is accepted and hand-checked.
   - Longer term: engine steps for splits that recur (mixed deposition, mixture composition), and
     `solve_for()` required for simultaneous equations, so chemistry is not done in free Python (same idea as
     the 19 Nov ban on rounding calls in `sandbox.check_code`).
5. **A solver matching the key never skips validity checks.** All checks in §4 run on every question before
   the ladder, so agreement cannot rescue an impossible question.

Done when: 022806's trace is refused by (1) and by `role_problems`; a test builds the same chain with pressure
units and accepts it with key 364.9 K; a test with the Cu/Ag numbers above is refused by (4) and the same
program with a mass inside 7.59–25.8 g is accepted.

---

## 5. Change D — inorganic: organic-style "states" questions

Evidence: on real JEE Advanced inorganic (2022–25, outside bonding/coordination) the hardest questions are a
hidden step over common facts (2022P1_Q4, 0.25% full marks: Cu²⁺ + excess KI → CuI + I₂, then H₂S → S; the
reflex answer is CuS, 1.9 g — Granite gave exactly 1.9 g ×3). Obscure-fact questions land mid-range (23–42%).

Build:
1. **Readiness audit first (₹0).** Report what the inorganic data lacks for sequential/hidden-product questions:
   balanced equations (none today), amounts/n-factor maths (none; see the titration recipe in
   `core/engine/physical/advanced.py`), product + product reactions (none), condition variants (11 in
   `knowledge/inorg_condition_variants.json`). List proposed additions for Vidur's approval before changing any
   graph file.
2. **Sequential states, capped at 4, enforced in code** (where reactions are picked, not in the prompt).
3. **The asked species is hidden** (no name, no "the S-containing product" giveaway).
4. **At least one reflex-trap step:** either an earlier step consumed what the reflex needs (copper already
   left as CuI, so no CuS), or a step hits a listed exception from
   `knowledge/concept_book_inorg.json` → `interpretive_operators.number_of_exceptions.exceptions`
   (`standard_case` = the reflex = the saved wrong turn; `exception` = the truth). These entries are
   model-written and only partly audited: check each one used.
5. **Ask an amount or a property of the hidden product**, so the reflex gives a different, checkable wrong answer
   (saved as `result.traps` for §2).
6. Baseline: the existing hidden-products code (`core/pipeline/inorg_products.py`, switched off by
   `PRODUCTS_SHARE = 0.0` in `core/pipeline/inorg_qfirst.py:37`). The new kind must beat it in a pilot with the
   bar set before running.

---

## 6. Change E — organic: more than one starting system

Today `core/pipeline/org_qfirst.py` grows one scheme from one start (branches allowed, `MAX_BRANCHES = 2`).
Add schemes with **two starting systems** that are built separately and then react with each other
(e.g. a Grignard from one branch onto a carbonyl from the other; a crossed aldol or an ester from two prepared
partners). The same shape applies to inorganic (a gas from one vessel passed into another solution).

- Cap the total states across both systems (start at 4–5; set it in code).
- Both systems must matter: a wrong turn in either must change the answer.
- First check that the RDKit rules can couple two scheme products; report gaps before building.

---

## 7. Change F — "which of these are correct" format

At least 1 question in every 5 (organic and inorganic) is a statements question: "which of the following
is/are correct" or "how many of the following are correct". Up to ~8 items (real papers use 4–8). Each item is
decided by the engine; none may be the plain negation of another. Physical: only where two facts or an
exception must be combined (low priority).

---

## 8. Open — fact-based questions (do not build without a decision)

Leaning: a **fact probe** that only explains a Granite failure. Ask Granite the bare fact as an open question
("what forms when Cu²⁺ meets excess I⁻?"), graded by code against the engine. Knows every fact but fails the
question → stays a candidate; misses a fact → the failure says nothing about difficulty. **It never labels a
question Advanced.** Whether to build it, and what share fact questions get, is undecided.

---

## 9. Later — plug-and-play structure

One shared skeleton (pick the hard step → engine → writer → code checks → ladder + trace checker), each
subject plugging in its kinds, engine builder and extra checks. Do this **after** §2–§7 are proven. Commit or
set aside the uncommitted work in the tree first (`git status`: inorganic hidden products, physical shortcut
check, run outputs).

---

## 10. Dataset rules (audience: people fine-tuning models on chemistry)

- A wrong key is worse in training data than in a benchmark: correctness first (§2–§4).
- "Hard" means `trap` or `concept` failures only, never length. Keep the state caps; a question that fails only
  as `too_long` is not hard (whether to keep it with a `too_long` tag is Vidur's call; default: leave it out of
  the main release).
- Every accepted question stores its failure labels, so JEE users, fine-tuners and benchmark users can filter.
- The written solution matters as much as the key: every step must agree with the engine trace (extend
  `solution_check.py` coverage where a subject is not yet covered).

---

## Order of work

1. §2 trace checker + §3 objections — offline replay on stored ladder records (₹0), then one live question.
2. §4 physical: 4a and 4b are built; next 4c (derived values), then units/types (₹0 offline, one live run).
3. §5 inorganic readiness audit (₹0), approved data additions, then the pilot.
4. §6 organic two-system schemes, §7 statements format.
5. §8 only after a decision; §9 last.
