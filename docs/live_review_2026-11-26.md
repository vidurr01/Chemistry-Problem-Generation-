# Live review log (started 2026-11-26)

## Remaining work and decisions (reviewer, 2026-11-26, after commit 1700a59)

**To do (agreed):**
1. **Physical: stated values computed from free choices** (spec §4c). The picker draws what is physically free
   (current, time, copper's share of the charge) and computes the stated values from them with engine steps, so
   impossible data cannot be drawn at all; the value checks (§4a) stay as the safety net.
2. **Inorganic graph audit** (spec §5): list every reaction whose product depends on an unstated condition (SO₂ vs
   H₂SO₃, NO₂ vs HNO₂, H₂O vs O₂, P₄ + NaOH) and pin the condition or split it into condition variants. The list is
   approved by the author before any graph file changes.
3. **Organic hidden-intermediate questions**: an intermediate whose identity the student must deduce (from a
   molecular formula, a test result or a stereo outcome) instead of every reagent being handed over; the likely route
   from Advanced-easy to medium.
4. **Organic two starting systems that react with each other** (spec §6), with a cap on total steps; first check that
   the engine rules can couple two scheme products.
5. **Physical P1–P3**: P1 the hidden step must not be announced by its data (Cp values plus "assume heat capacities
   constant"); P2 "given f, find a whole n" questions pick n first and compute f (same idea as item 1); P3 prefer
   formula draws where one formula's result feeds the next over draws that only share a quantity.

**Decided — not to do:**
- **Every organic branch need not be asked about.** A branch no statement uses is acceptable (reviewer; supersedes
  the redesign plan's "every step is asked about").
- **Difficulty labels stay as they are.** They come from the ladder calibrated on real JEE Advanced and Mains data;
  there is no data showing they should be lowered. Hand grades in this log are one reviewer's view, not a measurement.
- **Physical prompts stay as they are** (real JEE level examples per twist). Organic and inorganic are not to be
  styled after physical, nor physical after them. Noted idea for later: physical combined with organic or inorganic
  in one question (a cross-subject question) could make tougher questions.

**Later (spec §8–§9), explained:**
- **Fact probe** (§8): when Granite fails an inorganic question, ask it each fact the question uses as a bare open
  question ("what forms when Cu²⁺ meets excess I⁻?"), graded by code against the engine. Knows every fact but still
  fails → the difficulty is in combining them (a real signal); misses a fact → the failure only shows a knowledge gap.
  It never labels a question Advanced by itself. Undecided whether to build it.
- **Plug-and-play structure** (§9, from the reviewer's 25 Nov list): one shared pipeline skeleton (pick the hard step →
  engine → writer → code checks → ladder + trace checker) with each subject plugging in only its question kinds, its
  engine builder and its extra checks, instead of three separate pipelines patched one by one. After the kinds above
  are proven.

---

One question per subject, graded by hand, after the changes of `docs/implementation_spec_2026-11-25.md`. Each round
records what came out, what went wrong, what was fixed at once, and what is proposed (to discuss before building).
Nothing is committed until a round shows the changes work. Spend at ₹88/$.

---

## Round 1 — 2026-11-26

Code in this round (uncommitted): trace checker + objection hold (§2–§3), rate-unit check (§4.1), value checks and
answer aiming (§4a/4b, committed `aa5fc0e`), physical back to 3–5 formulas. Engine audit: 0 flags.
Logs: `outputs/live_20261126/{physical,organic,inorganic}_1.log`.

### Results

| Subject | Outcome | Spend | Pipeline label | Hand grade (reviewer's scale) | Key |
|---|---|---|---|---|---|
| Physical `GEN_20261125T193315` | accepted | $0.156 (₹13.8) | advanced_medium | Advanced easy–medium | right (205.4, checked by hand) |
| Organic `GEN_20261125T193638` | accepted | $0.058 (₹5.1) | advanced | Advanced easy at most | right (ABC) |
| Inorganic | nothing accepted | $0.016 (₹1.4) | — | — | — |

**Physical** — NH₃ synthesis: log K vs 1/T intercept (about 656 K) → ΔS° → ΔC_p correction to 298 K → S°(NH₃).
Granite and GLM both gave 187 (the uncorrected value): the hidden step works as a trap. Weakness: the question hands
over every C_p and says "assuming the molar heat capacities are independent of temperature", which announces the
correction. Every piece is a known pattern; the join is the rarer part.

**Organic** — 4-(2-bromoethyl)acetophenone → mCPBA (Baeyer–Villiger, aryl acetate) → NaI → NaCN; branch AgNO₂.
Only statement D (Q is an ester, so 2,4-DNP negative) turns on a real step. A (nitrile from NaCN), B (nitro from
AgNO₂) and C (iodoform on the start) are rote facts. The NaI step is decoration: NaCN acts on the bromide directly.

**Inorganic** — 10 draws: 6 "no reaction system left"; 2 species-list counts solved by Granite (too easy); the same
P₄ + NaOH system drawn twice, both times refused by the blind letter check (X = PH₃ vs NaH₂PO₂).

**Trace checker** — 3 members checked: Granite (physical) `concept`, correct reason (missed the ΔC_p correction);
Granite (organic) `concept`, correct (missed Baeyer–Villiger); GLM (physical) `unchecked` (reply cut off at 1500 tokens).
No question was held. It did not change any acceptance in this round.

### Fixed at once (uncommitted)

1. **False "value unused" rejected a right physical question twice** (draw 1, He⁺: given revolutions per second,
   find the angular momentum). The value was the target of a whole-number search for n; ±0.1 % gave the same n and
   ±2 % found no whole n, so it looked unused. `sandbox._input_role`: a non-whole value whose nudge the program refuses
   counts as used. Test `WholeNumberTarget` (fails on the old code).
2. **Trace checker cut off** — `trace_check.MAX_TOKENS` 1500 → 4000.

### Proposed (discuss before building)

Physical
- **P1. The hidden step is announced by its data.** Same issue as 25 Nov run 5. The design prompt already says "give
  such data one level earlier"; here it was not followed. Options: a writer rule plus a check that flags phrases
  like "assume ΔC_p / heat capacities independent of T" next to the hidden step's data; or let the shortcut check's
  coder see the stem and say whether the step is announced.
- **P2. "Given f, find a whole n" questions** cannot be drawn at random (198 of 200 value sets failed). Pick the whole
  number first and compute the stated value from it: the same idea as spec §4c (derived values).
- **P3. Prefer chained formula draws** (one formula's result is another's input) over draws that only share a
  quantity. Today ~52 of 300 draws line up as a chain by chance.

Organic
- **O1. Decorative steps.** Code check: remove each reaction step in turn; if no statement's truth changes, the step
  is decoration → rewrite or redraw.
- **O2. Rote statements.** At most one statement may be a rote fact (nitrile from CN⁻, iodoform on a methyl ketone);
  the rest must turn on a selectivity decision or a hidden intermediate.

Inorganic
- **I1. Reaction systems exhausted** (6 of 10 draws empty, free but wasted): the pool minus everything tried or solved
  is empty. Widen the pool (condition variants) or let systems whose question was too easy come back with a
  different asked property.
- **I2. Species-list counts are recall** (Granite solved both). Lower `LIST_SHARE` or require a hidden product in
  the list.
- **I3. The same refused system is drawn again** in one run: add a letter-check failure to `adapter._bad_system`.
- **I4. Hidden products is off** (`PRODUCTS_SHARE = 0.0`), though it gave the only inorganic Advanced questions
  (24 Nov, hp_3, hp_6). Turn it on as the baseline (spec §5).

All subjects
- **L1. Labels are still generous.** Both accepted questions are labelled Advanced / Advanced-medium; by hand they
  are Advanced easy(–medium). The label is the first ladder model that solves it; the trace checker only filters
  failures. Options: keep labels but show the hand grade as the truth, or map "GLM first" to Advanced-easy.

### Built after round 1 (author's choice: inorganic I1–I4 first; uncommitted)

Measured first: with every exclusion, the reaction-system draw finds 4 distinct systems and fails 27 of 40 draws;
with none, the graph offers ~27 in all. Exclusions that empty it together: systems Granite solved (19) and species
already asked (9 sets). Kinds, accepted/judged over all logged attempts: hidden products 18/33, list 14/56,
system 11/56.

- **I4** `inorg_qfirst` shares: products 0.0 → 0.5, system 0.7 → 0.3, list 0.3 → 0.2. Note: above the redesign
  plan's "no kind over ~35 %" variety cap; revisit once a batch shows the spread.
- **I1** an empty system draw becomes a hidden-products draw in the same slot, and the run skips systems after that.
- **I2** lower list share (above); "a hidden product in the list" not built.
- **I3** `_with_twins`: refusing an edge refuses every edge with the same start and product (P4_to_PH3_p /
  P4_to_PH3_p_2), in the run and from the memory file. Test `InorganicTwins`.
- Test change: `tests/test_inorg_qfirst.py` system-only helpers turn the new products fallback off. Inorganic tests:
  91 pass.

---

## Round 2 — inorganic only (2026-11-26)

Log `outputs/live_20261126/inorganic_2.log`; $0.0084 (₹0.74); nothing accepted. The fallback worked (no reaction
system left → hidden products).

| Draws | What happened |
|---|---|
| 5 hidden products | refused by the blind product check: H₂SO₃ vs SO₂, Na₂ZnO₂ vs [Zn(OH)₄]²⁻, NO₂ vs HNO₂, H₂O vs O₂, BO₂⁻ vs NaBO₂ |
| 3 hidden products judged | 2 solved by Granite (too easy); 1 (draw 9) rejected by the new trace rule — see below |
| 3 species lists | all solved by Granite (too easy) |

**Draw 9 was a good question and the new rule wrongly rejected it.** Seven reactions, count paramagnetic products;
key 2 (Fe₂O₃ from FeS₂, FeO from FeC₂O₄), checked by hand. Each reaction carries a trap; Granite (answer 6) fell
into three: dichromate "reduced to Cr³⁺" (it is only KCl metathesis), Co kept at +2 (nitrite gives Co³⁺), Mn stopped
at Mn⁴⁺ (bismuthate gives MnO₄⁻). GLM solved it. The checker called Granite's wrong products "hallucination", so it
counted as not hard. **Fixed:** the checker prompt now says a wrong answer to what the question asks the solver to
work out (a product, an oxidation state, which reaction occurs) is "concept"; "hallucination" is only misreading or
inventing what the question states, or a fact the key step does not depend on. Re-check of the same working: concept.

### Findings (pipeline, not luck)

- **Product-check refusals are partly false.** Na₂ZnO₂ vs [Zn(OH)₄]²⁻, BO₂⁻ vs NaBO₂ and H₂SO₃ vs SO₂ name the same
  species in another form; NO₂ vs HNO₂ and H₂O vs O₂ look like real condition ambiguity in the graph. Proposed:
  (a) accept a disagreement when both formulas are the same species (salt vs ion, hydrated vs oxide form, same
  element and oxidation state) and the asked property cannot differ; (b) audit the graph for ambiguous conditions
  (spec §5 readiness audit) and pin or split them, with the author's approval.
  **(a) BUILT** (author's choice): `inorg_products.other_form` — accepted when the formulas differ only by
  alkali-metal spectator ions and whole H₂O, the named element keeps its oxidation state, and the asked property
  (engine) is the same for both. Round 2's refusals now: Na₂ZnO₂ vs [Zn(OH)₄]²⁻ and BO₂⁻ vs NaBO₂ accepted; SO₂ vs
  H₂SO₃ (bent vs pyramidal, geometry asked), NO₂ vs HNO₂ (N +4 vs +3) and H₂O vs O₂ still refused; Cu(OH)₂ vs
  [Cu(NH₃)₄]SO₄ still refused. Test `ProductOtherForm`; inorganic tests 103 pass. (b) graph audit not started.
- **Species lists are recall** (Granite: 3/3 this round, 2/2 round 1). Proposed: drop the kind or keep it as rare
  filler.
---

## Round 3 — inorganic only (2026-11-26)

Log `outputs/live_20261126/inorganic_3.log`; $0.0109 (₹0.96); **accepted** `GEN_20261125T201137`, pipeline label
advanced.

Seven reactions, count the paramagnetic products; key 4, checked by hand: NiS (d⁸), FeCl₂ (from FeCl₃ + H₂), Mn²⁺
(KMnO₄ + H₂O₂, acid) and Fe₂O₃ (FeCl₂ + O₂) paramagnetic; N₂ (NH₃ burnt), [Co(NH₃)₆]³⁺ (low-spin d⁶) and K₂Cr₂O₇
diamagnetic. Granite 6 (a saved trap answer: code labelled it `trap`, no checker call); GLM 4; Granite solved
after the insight hint.

Hand grade: **Advanced easy**. Every reaction is a standard NCERT outcome; the traps (NH₃ burnt gives N₂ not NO;
Co³⁺ low spin; dichromate + KCl is no redox) are known patterns. Part of the difficulty is the length (seven
reactions, one slip changes the count), which is the kind of difficulty the reviewer does not want to reward.

Other draws: 2 species lists and 2 hidden-products sets solved by Granite; SO₂ vs H₂SO₃ refused again (the same
ambiguous reaction as round 2).

### Findings
- **Species lists: Granite solved 8 of 8 across rounds 1–3.** Proposed: stop drawing them (share 0).
- **Reactions repeat across questions**: NH₃ burnt, Na₂Cr₂O₇ + KCl and KMnO₄-type rows appeared in round 2 draw 9
  and round 3. `asked_reaction_sets` stops the same set, not the same rows. Proposed: limit a row to one accepted
  question in N.
- **The ambiguous SO₂/H₂SO₃ reaction comes back every run**: `_bad_products` is per run. Proposed: remember refused
  product rows across runs (as the system memory does), and fix the reaction in the graph audit.
- **Length drives part of the difficulty**: proposed cap of 5 reactions with at least 2 designed traps, so the hard
  part is the traps, not the count (the spec's 3–4 vs 5–6 pilot).

### Built after round 3 (author's choice; uncommitted)

- **Species lists off**: `inorg_qfirst.LIST_SHARE` 0.2 → 0.0; hidden products 0.5 → 0.7 (systems 0.3).
- **4–5 reactions**: `inorg_products.N_MIN, N_MAX` 6, 8 → 4, 5; `MIN_TRAP_ROWS` stays 2.
- **Row reuse**: `inorg_products.MAX_ROW_USES = 2` — a reaction already in 2 accepted questions is not drawn
  (measured: CuCl₂ → [CuCl₄]²⁻ was in 6 of 18 accepted, Ag + CN⁻ in 5).
- **Refused reactions remembered across runs**: product-check refusals (not failed calls) go to the system memory
  file (`outputs/inorg_system_memory.json`, `unconfirmed_edges`, marked `from: hidden_products`); the products draw
  excludes them and their duplicates.
- Draw check (60 seeds, real graph): 60/60 found; 36 with 5 reactions, 24 with 4; 51 with 2 traps, 9 with 3;
  22 rows blocked by reuse, 12 refused. Inorganic tests: 103 pass.

### JEE Advanced wording (reviewer's request; uncommitted)

The reviewer: the questions do not read like JEE Advanced. Real examples for style were already allowed by the author
on 25 Nov ("show real examples, never a copy; content from our engine"); physical used them, organic and inorganic
did not.
- **Organic**: new `core/pipeline/style_examples.py`. The writer (`org_qfirst.write_question`) sees 3 real JEE Advanced
  stems of the same answer format (from `data/jee_advanced`, text-only) "for wording and style only", and is told to
  word the question as a real paper does. `org_qfirst.evaluate` sends back a draft that shares a 10-word run with
  a shown stem.
- **Inorganic** (no model writes these): hidden-products wording rewritten in JEE register — "Consider the following
  reactions:", "(i) … → (product containing Fe)", "The total number of reactions in which the indicated product is
  paramagnetic is ____." (was "In each, look at the product that contains the named element (balanced equations are
  not needed)" / "… in which that product is …").
- Tests: `StyleExamples`; organic + inorganic tests 132 pass. Not yet seen in a live question.

---

## Round 4 — organic + inorganic with JEE wording and the inorganic fixes (2026-11-26)

Logs `outputs/live_20261126/{organic_2,inorganic_4}.log`. Both accepted; both keys right (checked by hand).

| | Question | Spend | Label | Hand grade |
|---|---|---|---|---|
| Organic `GEN_20261125T203341` | 4-propargylbenzaldehyde → NaBH₄ → SOCl₂ → AgNO₂ / NaCN → HBr (2 equiv); key AB | $0.062 (₹5.4) | advanced | Advanced easy at most |
| Inorganic `GEN_20261125T203449` | 4 reactions, square pyramidal: BrF₅ (excess F₂), XeOF₄ (limited water) vs NH₃, XeF₄ (1:5); key 2 | $0.0055 (₹0.5) | advanced | Advanced easy, close to medium |

**Wording: better.** Organic reads like a paper ("Which of the following statement(s) is(are) correct?", plain
statements; the copy check did not fire). Inorganic reads like a paper. The scheme lines (`P --[NaBH₄]--> Q`) are
still code-printed plain text, not a paper's arrows.

**Inorganic: the new shape works.** Four reactions, two traps, all set by conditions (excess vs limited F₂, limited vs
complete hydrolysis, Xe : F₂ ratio). Short, and the difficulty is the conditions, not the length. Granite gave 3, a
saved trap answer.

**Organic: rote statements again.** A (nitro from AgNO₂) and B (nitrile from NaCN) are the same two rote facts as
round 1's question; only C/D (HBr ×2 on the alkyne, sp³ count) need work. Strong case for **O2** (at most one rote
statement) and for spreading branch reagents (AgNO₂ and NaCN appear in both accepted organic questions).

### Built after round 4 (author's choice: organic O1–O2; uncommitted)

- **O2 rote statements**: `org_qfirst.MAX_ROTE_PER_4 = 1` — at most one statement in four that no wrong turn flips;
  `evaluate` sends the draft back otherwise; the writer prompt says so. (Rounds 1 and 4 had two each.)
- **Reagent reuse**: `MAX_EDGE_USES = 2`, `overused_edges()` — a reaction already in 2 accepted organic questions is
  not drawn. Measured: AgNO₂ → nitro in 6 of 10 accepted; Br₂/H₂O, CH₃COCl and HBr in 4. Today 11 reactions are
  excluded; 20 of 20 test draws still found a scheme.
- **O1 decorative steps**: `decorative_steps()` — a step is decoration when every child comes out the same with its
  reagent on the step's parent (engine rules); such schemes are not drawn. Round 1's NaI step is flagged; test
  `OrganicDecorativeStep`.
- Test change: `tests/test_org_qfirst.hinge_claims` now builds three decisive statements and one filler (was two
  and two). Organic tests 29 pass.

---

## Round 5 — organic with O1–O2 and the reagent limit (2026-11-26)

Log `outputs/live_20261126/organic_3.log`; $0.0765 (₹6.7); **accepted** `GEN_20261125T210609`, label advanced.
(The first attempt was cut off when the session ended, after the start pick; re-run.)

P = 4-[4-(hydroxymethyl)phenyl]butan-2-one → Na/CH₃I (benzylic methyl ether) → Ph₃P=CH₂ → mCPBA (epoxide) →
CH₃NH₂ (opens at the CH₂: tertiary alcohol T); branch: methoxymercuration (Markovnikov: U = ArCH₂CH₂C(CH₃)₂OCH₃);
branch: CH₃OH/HCl (ketal V). Key ABD, checked by hand: T tertiary → Lucas immediate (A); U has no stereocentre
(B true, C false); Q still CH₃CO– → iodoform (D).

- The rote limit fired once (draft 1 had two statements no step decides) and the writer fixed it.
- No overused reagent: Wittig, epoxidation, amine opening, oxymercuration, ketal. Three statements turn on real
  decisions (epoxide regiochemistry, Markovnikov).
- Hand grade **Advanced easy–medium**: the best organic question of the review.
- Flaws: branch V is asked about by no statement (spec Stage 1 "every step is asked about" is not built); Lucas on
  an amino alcohol is arguable.

- **Easy hidden-products sets**: 2 of 3 judged were solved by Granite. Hard ones need several trap reactions
  (draw 9 had ~4); proposed: require at least 3 reactions whose obvious product is wrong (`MIN_TRAP_ROWS` is 2).

### Did the changes help?

No wrong question in this round, and the trace checker's two labels were right. But the changes so far are about
correctness and honest grading; they do not change how questions are designed, so question quality is about where it
was (physical decent, organic easy, inorganic none). The design proposals above (P1, O1–O2, I1–I4) are where quality
can move.
