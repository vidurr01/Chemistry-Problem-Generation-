# What we tried, what worked, what didn't (2026-09-01 → 2026-11-25)

One page built from `docs/ChangeLog.md` (every change, by date), `docs/Decisions.md` (why) and the result files
named below. For the detail of any line, search the ChangeLog for its date and words.

**Status column:** Kept = in the pipeline now. Dropped = removed. Off = built but switched off. Open = never decided.

**Where it stands today (hand grading of the 55 current questions, `docs/redesign_plan_2026-11-25.md`):**
41 Mains, 10 Advanced (8 easy, 2 medium, 0 hard), 4 wrong. The pipeline had labelled 50 of 55 Advanced.

---

## 1. The overall shape of the pipeline

| When | Tried | Result | Status |
|---|---|---|---|
| Sept | A model writes the question and the answer; a verifier model and weak/strong solvers check it | The verifier failed on every call (its model echoed the prompt). 10 inorganic questions scored by hand: 3 Advanced, 5 between Mains and Advanced, 2 Mains (mean 2.1 of 3), one with a wrong assumption (`results/generated_questions_inorganic_final.json`). Higher level than today's, but nothing guaranteed the keys | Dropped 13 Oct |
| 13 Oct | Engine first: code computes every answer; questions are chains walked through the knowledge graph | Keys became reliable. Questions were plug-in chains; runs kept finding grading bugs | Engine kept; chain-walk generation dropped 15 Nov |
| 15–19 Nov | Physical "question first": random formulas → designer → writer with blanks → coder program → code picks the numbers | 7 of 28 draws became a question (25%). Review on 16 Nov: 3 of 11 accepted were real Advanced | Kept (to be rebuilt) |
| 19–24 Nov | Same pattern for organic (reaction schemes) and inorganic (graph walks, lists, hidden products, reaction systems) | Correct keys after many fixes; questions mostly Mains (see sections 4–5) | Kept (to be rebuilt) |

## 2. Measuring difficulty

| When | Tried | Result | Status | Evidence |
|---|---|---|---|---|
| Oct | Council of 3 models voting | Replaced by a ladder (cheaper; each step called only if the ones below fail) | Dropped 14 Oct | Decisions: "A difficulty ladder instead of a council vote" |
| Sept–19 Nov | Verifier model decides "solved", slips, wrong keys | Wrong calls: counted a wrong Llama answer as solved (run 7), called a right key wrong (flask, 50.31 mL) | Dropped 19 Nov; code grades only | Decisions: "No mismatch verifier" |
| Oct–19 Nov | Ladder bottom: Llama 3.3 → Phi-4 → Llama → Granite 4.2 8B | Granite fails 32% of easy Mains, 52% of Advanced | Kept (Granite) | `calibration/ladder_separation.py` |
| 19 Nov | Ladder top: GPT-6 Luna → MiniMax M3 | Luna also wrote the key, so its "solve" was the key agreeing with itself | Kept (MiniMax) | ChangeLog 19 Nov |
| 19 Nov | Force the solvers to call the calculator | Unforced Llama called it 0/5 times; forced 5/5 | Kept | ChangeLog 19 Nov |
| 25 Nov | Inorganic rule "GLM solves = too easy", checked on 17 real questions with student results | Would reject 8 of 12 real medium/hard questions | Dropped; "Granite fails" is the bar | `calibration/ladder_vs_students_inorganic.json` |
| 25 Nov | Granite on real Mains inorganic | Solves 7/10 Mains, only 3/12 real Advanced medium/hard. But 3 in 10 Mains still pass as hard | Kept | `calibration/ladder_vs_students_inorganic_mains.json` |
| 25 Nov | Same question judged twice | Verdict flipped on 5 of 15 identical questions | Open: one verdict is noisy | ChangeLog 25 Nov (statement A/B run 4) |
| 16–22 Nov | Jev level check (organic, physical) as a gate | Organic floor first calibrated on numericals only; 25 of 49 had no structures; recalibrated 22 Nov | Kept | `knowledge/level_calibration_organic.json` |
| 25 Nov (finding) | — | The ladder rewards length, not one trap; real hard questions are short with one hidden step | Fix planned: trap-hit ladder | `docs/jee_advanced_question_types_2019_2025.md` |

## 3. Physical

| When | Tried | Result | Status |
|---|---|---|---|
| 16 Nov | Writer states its own numbers | Impossible values (purity 72264%, negative amounts) | Dropped: blanks, code picks the numbers |
| 16 Nov | Jev formula-fit floor 0.60 | Turned away 5 of 10 real 3-formula sets | Changed to calibrated 0.504 |
| 19 Nov | Fit check A/B (on vs off, 10 draws each, ₹69) | Built 3/10 vs 2/10; the score did not predict success | Kept, unproven |
| 19 Nov | Draw weighted by rare shared quantities | No real gain (Jev median 0.31 vs 0.34) | Dropped |
| 19 Nov | Situation first (a model invents the system, then formulas) | Median 0.38 vs 0.34 random, 0.66 real; exotic systems | Dropped (author kept random draw) |
| 16 Nov | Uncalibrated Jev design checks (50% cut-off) | Rejected 3 of 4 designs, good ones too | Off |
| 16–18 Nov | Jev coherence check, calibrated | 95th percentile: rejects 9/77 real, catches 14/14 bad; 99th: rejects 2/77, catches 14/14 | Open: current vs looser never decided |
| 19 Nov | At least 2 typical mistakes per question | Commonest way a draw died | Changed to 1 |
| 19→22 Nov | Writer retries: 3 → 1 → 2 | Of 21 draws, none was rescued by a rewrite; later 2 allowed | Kept (2) |
| 19 Nov | Designer may drop one of 4–5 formulas | Half of draws died at design | Kept |
| 16–17 Nov | Coders: DeepSeek V4 Flash, Qwen3 Coder Next, Codestral, GPT-6 Luna | Empty replies; 502 errors; basic code errors; Luna reached the official answer on real questions | Kept (Luna) |
| 25 Nov (finding) | Chains joining chapters | Real papers do this in 1 of 77 questions; 3 of our 17 physical keys are wrong | To be rebuilt (trap first) |

## 4. Organic

| When | Tried | Result | Status |
|---|---|---|---|
| 20 Nov | Graph cleanup | 199 → 179 edges (20 wrong or duplicate deleted, 12 fixed) | Kept |
| 20 Nov | 5–8 step schemes with branches (the author's direction) | Real scheme-statement questions are medium (35% full marks); length did not make ours hard | To be rebuilt |
| 20–24 Nov | Rules that model the textbook substrate only, scope as a block list | Wrong keys accepted in runs 3, 6, 8, 9 and 18 (one-site reactions, PCl₅ on phenol, conjugated addition, stereocentre count); all removed | Changed: only approved-scope edges are drawn |
| 24 Nov | Chemoselectivity audit (155 edges × 638 molecules) | 2 rule bugs, 47 scope gaps closed | Kept |
| 24 Nov | Blind step check by GPT-6 Luna | Caught 11 of 12 bad steps; flagged 10 of 150 good (half were engine errors) | Kept as a gate |
| 24 Nov | Start picker refuses groups that react with each other | Most held schemes came from such starts | Kept |
| 24 Nov | Up to 3 schemes per picked start | Picker cost per run down 4× | Kept |
| 24 Nov | "Hinge" rule: 2 decisive statements from 2 different steps | Run 10 tested one decision twice | Kept |
| 22→25 Nov | Scope limits added one live run at a time, then the reagent × group table | Held steps still drawable: 53 of 81 → 2 | Kept |

## 5. Inorganic

| When | Tried | Result | Status |
|---|---|---|---|
| 13 Oct, 24 Nov | Concept-book audits | 44 wrong entries fixed; 134 exception notes reviewed | Kept |
| 19 Nov | Graph walk of 2–4 reactions, property statements | Shallow (first live question: B is +3 in both) | Replaced |
| 24 Nov | Species lists, one condition | Granite solved 6 of 8 | Changed to two conditions (author) |
| 24 Nov | "Hidden products" count (5–8 reactions, one property) | Gave the only 3 inorganic Advanced questions in today's grading | Dropped 25 Nov as "not a real format"; on today's grading, dropping it looks wrong. Back in the redesign plan as the first inorganic kind |
| 25 Nov | One reaction system with products as letters | All 19 questions from the 25 Nov batch are Mains | To be rebuilt |
| 25 Nov | Statement A/B (rival-product traps, two-letter statements, model menu, rewording; ₹35) | With equal wording, rival traps made no difference; no arm reached the 49% bar | Rival traps kept for students only |
| 25 Nov | d-block draw (50% share) | Only 14 metal systems; most metal salts have one kind of fact | Off |
| 25 Nov | Graph enrichment by Gemini 3.1 Pro | ₹48 against a ₹5 estimate; about 50 good entries, nothing added | Dropped; spend cap tool added |
| 24 Nov | Blind graph audit (381 edges) and property audit (371 properties) | About 13 graph errors; 28 edges blocked; 10 property disagreements ruled | Kept |
| 24–25 Nov | Engine fixes from reviews | CrO₅ keyed +10, interhalogens, metal hydrides wrong; fixed | Kept |
| 25 Nov | Filters and repeat guards | "Already tried" filter never matched; duplicate check ran after paying; repeats of species and facts | Fixed |
| 25 Nov (finding) | — | 5 keys rest on [Co(H₂O)₆]³⁺ low-spin, a contested fact | To tag as contested |

## 6. Lessons about how we worked

- **Estimates were low.** Graph enrichment cost 10× its estimate, the real-question check 3×; one physical run overshot its cap.
- **Stored JEE keys are not always right.** 8 corrected in 2023–24 (14 Oct); 5 more inorganic keys wrong or doubtful (25 Nov); `data/jee_mains` needs cleaning (13 of 23 MCQs unusable).
- **Questions were scored by hand only once (September, 10 inorganic).** Everything since was judged by models and,
  on 25 Nov, by me. Those September questions, written by a model, were rated higher than today's; the engine made
  keys reliable but narrowed what could be asked.
- **Fixes came one live run at a time** (organic scope, inorganic filters); planned layers were built late.
- **Measuring against real students worked.** The 25 Nov checks against student results changed three decisions in a day.

## 7. Still open

- Coherence cut-off: current (95th) or looser (99th).
- The d-block draw: off until metal salts have more kinds of fact.
- 50 good graph-enrichment proposals in `outputs/inorg_reagent_proposals.json`, never added.
- The plan's open decisions (`docs/redesign_plan_2026-11-25.md`, end).
