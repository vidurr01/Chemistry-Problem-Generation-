# Why the questions are weak, and the redesign plan (2026-11-25)

No code has been changed for this. Part A is the post-mortem, Part B is the plan.

---

## Part A — What went wrong

### The result

All 55 current questions (30 inorganic, 8 organic, 17 physical), graded by hand against real JEE papers:

| | Easy | Medium | Hard | Total |
|---|---|---|---|---|
| Mains | 16 | 18 | 7 | 41 |
| Advanced | 8 | 2 | 0 | 10 |
| Wrong | | | | 4 |

- The pipeline labelled 50 of the 55 as Advanced.
- 5 more inorganic keys hinge on a disputed fact ([Co(H₂O)₆]³⁺ low-spin).
- The 4 wrong ones: physical 022806 (Kc used as Kp), 031247 (data contradict each other), 041311 (the answer is no alkali metal), and organic 032721 (already rejected).
- Best questions: organic 030619 (Baeyer–Villiger trap) and physical 033339 (tangent intercept = ΔS/R). Both got their trap by chance.

### Older vs latest pipeline

11 of the 30 inorganic questions came from older versions (19 Nov, 24 Nov, and one early on 25 Nov before the
batch). All 8 organic and all 17 physical came from the latest version (the physical code last changed 24 Nov).

Latest pipeline only (44 questions):

| | Count |
|---|---|
| Mains | 33 |
| Advanced | 7 |
| Wrong | 4 |

- All 19 inorganic questions from the 25 Nov batch are Mains (7 easy, 12 medium); none reached Advanced.
- The 3 inorganic Advanced-easy questions (161943, 162413, 193519) all came from the older 24 Nov version: "consider
  these 7–8 reactions, count the products that…", where the student must work out many products.
- The fixes made during the 25 Nov batches were about repetition and wording (inorganic) and chemistry scope
  (organic). None of them changed how hard a question is.
- All 4 wrong questions came from the latest pipeline.

Lesson: the old questions did not drag the result down. Inorganic questions got harder when the student had to
work out the products, not when they had to recall properties of products the question already gave. This
is why hidden products come first in the inorganic kinds (Part B, Stage 3).

### The mistakes, most important first

**1. Correctness was made the top goal, and nobody asked whether that goal could reach Advanced.**
- Decision: code computes every answer, so keys are always right.
- What it cost: a question can only ask what the code can compute. Inorganic code knows hybridisation, shape, magnetism, polarity, bond order, basicity and oxidation state, so all 30 inorganic questions are "property of a species". Real Advanced papers: that kind is 20 of 74; the kinds we never built are 33 of 74.
- Why it went unnoticed: the keys were right, so every review looked like progress.

**2. A model ladder was allowed to define "Advanced", and was checked against students only at the very end.**
- "Advanced" = Granite 8B fails, GLM solves. A small model fails on length (10-item lists, 5-formula chains) and on disputed facts. Students fail on ideas.
- The check against students came only on 25 Nov: Jev does not track student difficulty for inorganic; the GLM rule rejects most real hard questions; single verdicts flip 5 of 15 times on identical reruns.
- By then the labels had been treated as the truth for weeks.

**3. Difficulty was expected to come out of random draws plus a filter.**
- A filter can only choose; it cannot make a hard question.
- Inorganic since 24 Nov: 87 drafts too easy, 32 accepted. From the measured bar, only about 13% of drafts were really medium/hard, so most accepted questions are easy ones that got past a noisy filter.
- Organic had almost no gate: 2 rejected as too easy against 18 accepted.

**4. Progress was measured by the pipeline's own numbers, not by the teacher.**
- The last teacher scores are the 10 September questions: an average of 2.1 out of 3, and only 3 of 10 at Advanced. That was the early warning.
- None of the 55 new questions has a teacher score.

**5. Effort went into polishing, not into the design.**
- The 13 review fixes, the wording A/B (₹34.5), the letter format and the prose rewrites all improved correctness or wording.
- The A/B result itself said it: "statement choice is not the lever; our questions only ask properties of species." That was the moment to stop and redesign.

**6. Physical draws stitch random formulas across chapters.**
- On 19 Nov, 15 of 20 draws died as "impossible", and the random draw was kept.
- The ones that survive are contrived (rocket chambers, Arrhenius fractions → bond enthalpy), and stitching is what produced the contradicting data in 031247 and 022806.

**7. "The engine computed it" was treated as proof that the question is right.**
- The engine is right about its own route, not about the question. There is no check that a second route gives the same answer, that units match the reaction order, or that the answer is a real thing (an alkali metal of mass 24.4).

**8. Three separate pipelines, each patched by itself.**
- `inorg_qfirst`, `org_qfirst`, and physical `qfirst` + `qf_*` each grew their own fixes. The shared flaw (no designed hard step) was harder to see, and every fix had to be made three times.

My share: I recommended and built much of the ladder-first loop and the per-subject patches. I should have flagged the ceiling in point 1 much earlier.

### In one line

The engine limits questions to recall-level facts, the filter rewards length over insight, and nobody outside the pipeline checked the output for weeks.

---

## Part B — The plan

### Principles

1. **Design the hard step first.** Every question starts from one decision a student can get wrong; the engine builds the rest.
2. **Difficulty means students, not models.** The teacher's score is the success measure; the ladder is only a cheap pre-filter.
3. **Correct keys stay non-negotiable.** Code still computes every answer; no judge model for correctness.
4. **Build beside the old pipeline.** It stays runnable as the A/B baseline, and the old files are not touched.
5. **Set the bar before paying.** Every pilot has a pass bar and a ₹ cap agreed before it runs.
6. **Novelty rule unchanged.** Hard-step ideas come from chemistry principles and the concept book, never from JEE questions; JEE is only the yardstick.

### What stays, what is rebuilt

**Stays (about 23,000 lines):**
- Engine: `core/engine/**` (physical, organic rules and scope, inorganic properties and species).
- Grading: `answers.py`, `units.py`, `sandbox.py`, `solution_check.py`.
- Plumbing: `llm.py`, `models.py`, `spend_cap.py`, `queues.py`, `tools/results.py`.
- Audits, calibration scripts, tests.
- Concept book and knowledge graph (extended, not recreated).

**Rebuilt as one new shared layer (replaces about 7,000 lines):**
- Inorganic: `inorg_qfirst`, `inorg_system`, `inorg_list`, `inorg_products`.
- Organic: `org_qfirst`, `org_start`.
- Physical: `qfirst`, `qf_draw`, `qf_design`, `qf_writer`, `qf_coder`, `forms_layer`.
- Acceptance: the ladder decision in `flow.py` / `stages.py`, and `refine.py`.

### The new shared pipeline

1. **Pick a hard step** from the subject's list of hard-step kinds (coverage-weighted, as today).
2. **Engine builds the question:** the start, reagents or data, the right answer, and the trap answer that the hard step produces.
3. **Writer model writes the question text** (as now; it never writes the answer).
4. **Code checks** (Stage 1 below).
5. **Trap-hit ladder** (Stage 2 below).
6. **Teacher samples** the accepted questions (Stage 4 below).

Each subject supplies only: its hard-step kinds, its engine builder, and its extra checks.

### Stage 1 — Code checks that stop wrong questions (₹0)

- **Consistency:** if the engine can also derive a given number from the other data, the two must agree (catches 031247).
- **Units and order:** a rate constant's units must match its order; Kc and Kp are never mixed (catches 022806).
- **The answer is real:** an asked-for element, metal or species must exist with that value (catches 041311).
- **Contested facts are tagged in the data** and never asked ([Co(H₂O)₆]³⁺ spin and similar).
- **Duplicates by structure:** canonical SMILES (organic), species set (inorganic), not names.
- **Distractors:** no option may be the plain negation of another.
- **Every step is asked about:** no scheme branch that no statement uses.

These go into the shared layer, so every subject gets them.

### Stage 2 — A difficulty measure that tracks students (about ₹7)

- **Trap hit:** a model's failure counts toward difficulty only if its answer equals the engine's trap answer. Random slips count for nothing.
- **Length caps:** at most 6 items in a list, at most 3 reactions, at most 4 engine steps and 2 chapters in physical.
- **The same gate for all three subjects** (organic gets a real gate).
- **Calibration before adoption:** I hand-label the trap answer for the 17 real Advanced inorganic questions with student data, then run the rule with the existing `calibration/ladder_vs_students_inorganic.py` (last run ≈ ₹6.75).
- **Pass bar (set now):** at least as good as "Granite fails" on the same set: accept ≥ 9 of 12 real medium/hard, ≤ 1 of 5 real easy. If it is not, it is not adopted.

### Stage 3 — Hard-step kinds per subject

**Correction from real student data (`docs/jee_advanced_question_types_2019_2025.md`):** identify-the-product
(B1) is not hard by itself (median 34% full marks, about the same as property questions at 28%). What makes real
questions hard in all three subjects is one hidden step in a short question: inorganic hidden product → amount
(0.25–1.8%), organic amounts through a scheme (7%) and reagent choice (8%), physical trap questions (5%).
Real physical papers almost never join chapters (1 of 77). So kinds are chosen by the trap they can carry, not by
their format; the inorganic order below follows that evidence.

**Inorganic (pilot first). Kinds in build order, each with the trap it carries:**

| # | Kind | The trap (wrong answer the engine also computes) | Real papers: count, students |
|---|---|---|---|
| 1 | Hidden products → count those with a property (several reactions, products not printed; the student works out each product, then counts) | The count with a tempting wrong product (e.g. the product of the usual reagent, not the printed conditions) | B2 7, 4% (n = 1) |
| 2 | Hidden product → amount (moles, mass, volume of a product the question does not name) | The amount from the obvious product, or the wrong n-factor | C 7, 19% (hardest 0.25–1.8%) |
| 3 | Product set by conditions → its property or amount (cold/hot, dilute/concentrated, excess/limited, order of addition) | The answer for the rival product | B2 7, 4% (n = 1) |
| 4 | Reagent choice: which reagent gives this product and not its rival | The reagent that gives the rival product | R 1, 2% (n = 1) |
| 5 | Property of species (today's kind), kept only where a hard step exists (a hidden product, an unusual species) | Today's rival-product false statements | A 20, 28% |
| 6 | Identify the product, qualitative analysis: used as the format for kinds 1–4, not as kinds on their own | — | B1 11, 34%; E 7, 29% |
| later | Metallurgy; coordination isomerism | To be designed | D 7, 8% (n = 3); H 4, 42% |

- **Why hidden products come back first (added after `docs/what_we_tried.md`):** it gave all 3 of the inorganic
  questions graded Advanced on 25 Nov (161943, 162413, 193519, from the 24 Nov version). It was retired on 25 Nov
  as "not a real JEE format", but real papers do ask hidden products followed by a property (B2, 7 questions).
  Its code still exists (`core/pipeline/inorg_products.py`, switched off by `PRODUCTS_SHARE = 0.0` in
  `inorg_qfirst.py`), with the blind product check, so it costs least to bring back and serves as the inorganic
  baseline the other kinds must beat.
- What it lacked: those 3 were Advanced-easy, hard only because of how many products to work out. In the new
  pipeline at least one reaction must carry a designed trap (the trap column), and the trap-hit ladder judges it.
- Length: the old form used 5–8 reactions, but the Stage 2 caps allow at most 3 reactions. Since the long form is
  the one that graded Advanced, its pilot compares 3–4 against 5–6 reactions (bar set before running) and the cap
  for this kind is set from that result.
- New engine work for kind 2: the graph's reactions have products but no balanced equations, and the inorganic engine
  has no amounts maths. Kind 2 needs balanced equations for the reactions it uses (checked by code for atom and
  charge balance) and mole/n-factor maths; the physical engine's titration recipe (`core/engine/physical/advanced.py`,
  with its forgets-n-factor trap) shows the pattern. Kind 3 needs the condition variants below.
- The student numbers are small (B2 and R have one question each with data), so they set the order only.
  A kind stays only if its own pilot passes.
- No "(the S-containing product)" where it gives the answer away.
- Graph work: add condition variants to existing edges (for example Cl₂ + cold/hot NaOH, Cu + dilute/concentrated HNO₃). Each addition is listed for your approval before the graph changes, as before.

**Inorganic variety (so a batch is never one type, even at Advanced level):**
- Several kinds, not one, added in the order above.
- Real Advanced papers mix many kinds (`outputs/jee_adv_inorganic_kinds_2019_2025.json`, 74 questions: property of
  species 20, identify product 11, qualitative analysis 7, hidden product + property 7, amounts 7, metallurgy 7).
  This is a yardstick for variety, not a target mix: we lean toward the hard kinds. Never their content or traps
  (novelty rule).
- Cap: no kind above about 35% of a batch; kinds are coverage-weighted like chapters today.
- Answer formats rotate: single correct, multiple correct, integer, and match-the-column (List I / List II).
- The repetition guards built on 25 Nov (asked species sets, asked fact pairs, condition weighting) carry over to
  every kind.
- Each kind is added only after it passes its own small pilot; the mix grows kind by kind.

**Organic:**
- At least one step must be a selectivity decision where the engine has a rival product it rejects.
- At least one statement must depend on that decision; the standard tests (Lucas, iodoform…) become fillers only.
- The start molecule is chosen so the decision matters (your point that the start sets the difficulty).
- Little graph work: the rules already know which products they reject.

**Physical:**
- The concept twist is chosen first (solution vs solvent mass, Kc vs Kp, ΔCp correction, hidden limiting reagent, common ion), then the formulas that need it.
- This differs from the situation-first idea rejected on 19 Nov (it fixes the concept, not the scenario), and it goes through an A/B against today's random draw. It stays only if it wins.
- Fact questions only where two facts must be combined or there is a known exception; otherwise the 25% fact share is dropped.

### Stage 4 — Teacher in the loop

- After every 10 accepted questions, the teacher scores them: Mains/Advanced, easy/medium/hard, correct or not.
- Success measure: at least 75% of accepted questions at Advanced level, 0 wrong.
- The ladder label is never shown as the final level.

### Order, bars and cost

| Step | What | Pass bar | Cost |
|---|---|---|---|
| 1 | Shared skeleton + Stage 1 checks, run over the 55 current questions | Flags all 4 wrong ones, no false flags on the correct ones | ₹0 |
| 2 | Trap-hit calibration on real JEE | ≥ 9/12 medium/hard, ≤ 1/5 easy | ≈ ₹7 |
| 3 | Inorganic plugin + graph condition variants (approved list) | Tests pass, audits clean | ₹0 |
| 4 | Inorganic pilot: 10 accepted, against 10 from the old pipeline, both scored by the teacher | New: ≥ 7/10 Advanced, 0 wrong; and clearly better than old | Price from the real models first; hard cap |
| 5 | Organic plugin, same pilot | Same bar | Priced first |
| 6 | Physical plugin, same pilot | Same bar | Priced first |
| 7 | Retire the old per-subject pipelines | Only after 4–6 pass | ₹0 |

### Decisions needed from you before coding

1. Pilot order: inorganic first (recommended), or another subject.
2. Whether the teacher can score 20 questions per pilot (10 new + 10 old).
3. The pilot ₹ cap.
4. Whether physical fact questions stay at all.
5. Which inorganic kinds to build first, and the cap per kind (proposed: hidden products → count first, then
   hidden product → amount, product set by conditions, reagent choice; about 35% cap).
