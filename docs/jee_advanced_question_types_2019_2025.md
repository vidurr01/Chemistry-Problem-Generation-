# What real JEE Advanced chemistry asks (2019–2025)

Labelled by hand on 2026-11-25 from `data/jee_advanced/2019.json` … `2025.json`.

**Yardstick only.** This tells us what kinds of questions to aim for and how hard each kind is for students.
Nothing from these questions (content, traps, situations) goes into generation (novelty rule).

Label files:
- Inorganic: `outputs/jee_adv_inorganic_kinds_2019_2025.json` (labelled earlier the same day)
- Organic: `outputs/jee_adv_organic_kinds_2019_2025.json`
- Physical: `outputs/jee_adv_physical_kinds_2019_2025.json`

"Students" below = the median % of candidates who got full marks, from the 2022–2025 data (2019–2021 has none).
**Lower % = harder.**

---

## Inorganic (74 unique questions)

| Kind | What it asks | Count | Students (median % full marks) | n |
|---|---|---|---|---|
| A | Property of named species (shape, hybridisation, magnetism, MO) | 20 | 28% | 13 |
| B1 | Identify the product of a described reaction | 11 | 34% | 9 |
| E | Qualitative analysis (tests, precipitates, group reagents) | 7 | 29% | 2 |
| B2 | Hidden product(s), then a property of them | 7 | 4% | 1 |
| C | Amounts / moles from a reaction | 7 | 19% (0.25%–43%) | 5 |
| D | Metallurgy / extraction | 7 | 8% | 3 |
| F | Descriptive facts and trends | 5 | — | 0 |
| G | Solid state | 5 | 32% | 3 |
| H | Isomerism / coordination structure | 4 | 42% | 2 |
| R | Choice of reagent | 1 | 2% | 1 |

- The hardest real inorganic questions: a hidden product followed by an amount (Cu²⁺ + KI → then H₂S → mass of S, 0.25%;
  P₄ + NaOH → PH₃ → CuSO₄ needed, 1.8%), reagent choice (BN, 1.6%), metallurgy statements (5.5%, 8.3%), and an
  11-species hybridisation count with unusual species (6.8%).
- **Identify-the-product (B1) is not hard by itself** (median 34%). It is about as easy as property questions (28%).

## Organic (83 unique questions)

| Kind | What it asks | Count | Students | n |
|---|---|---|---|---|
| O1 | Reaction scheme → identify products / statements about them (incl. List-I/II matching) | 27 | 35% (1.7%–58%) | 18 |
| O3 | Amounts through a scheme (yield, mass, % composition, Carius/Dumas) | 14 | 7% | 9 |
| O2 | Scheme → count something in a product (atoms, CH₂, sp² C, unsaturation) | 10 | 19% | 6 |
| O5 | Isomer / stereo counting and relationships | 9 | 16% | 2 |
| O8 | Descriptive facts (biomolecules, polymers) | 8 | 17% | 5 |
| O4 | Choose the reagent / sequence / starting material | 6 | 8% | 3 |
| O6 | Compare acidity, basicity, reactivity | 6 | 30% | 1 |
| O7 | Deduce a structure from tests and clues | 3 | 34% (0.2%–52%) | 3 |

- Hardest: amounts through a scheme (O3, 7%) and reagent choice (O4, 8%). Counting in a product (O2, 19%) is next.
- O1, the kind our organic pipeline makes, has a median of 35%, but it ranges from 1.7% to 58%. The hard O1
  questions are hard because of the chemistry inside the scheme (cumene → acetone → trichloroacetone → haloform,
  1.7%), not because of the format.
- The puzzle-style structure deduction (C₉H₁₈O₂ with iodoform clues) scored 0.2%, the lowest of all organic.

## Physical (77 unique questions)

| Kind | What it asks | Count | Students | n |
|---|---|---|---|---|
| P1 | Direct calculation, standard formulas | 27 | 26% | 13 |
| P3 | Read a graph, figure or table, then derive | 18 | 28% | 7 |
| P2 | Short calculation with one hidden trap or deduction | 16 | 5% | 10 |
| P4 | Conceptual statements (mostly multiple correct) | 12 | 9% | 6 |
| P6 | Descriptive facts (surface chemistry, colloids) | 3 | 23% | 2 |
| P5 | Two chapters linked in one calculation | 1 | — | 0 |

- **The hardest physical questions are short, with one trap:** pH of a very weak acid where water's own H⁺ matters
  (1.3%), work done when water is electrolysed (moles of gas formed, 3–4%), buffer after mixing four species (2.6%),
  PbSO₄ solubility with HSO₄⁻ equilibrium (3.2%), E° of MnO₄⁻/Mn by adding free energies (15%).
- **Long chains joining chapters almost never appear:** 1 of 77 (fuel cell work → adiabatic compression, 2020).
  This is what our physical pipeline mostly makes.

---

## What this means for our questions

| Our current kind | Real-paper kind | How common in real papers | Students |
|---|---|---|---|
| Inorganic species lists, reaction systems | A, B2 | 27 of 74 | A 28% (B2 n=1) |
| Organic scheme + statements | O1 | 27 of 83 | 35% |
| Physical chains across chapters | P5 | 1 of 77 | — |
| Physical fact questions | P6 | 3 of 77 | 23% |

1. **Difficulty comes from one trap, not from length or joined chapters.** In every subject the hardest kind is
   short with a hidden step: physical P2 (5%), organic amounts through a scheme (7%), inorganic hidden product →
   amount (0.25–1.8%).
2. **Our physical design is the furthest from real papers.** Real papers almost never join chapters; we nearly
   always do.
3. **The question kind alone does not make a question hard.** Identify-the-product (B1, 34%) and scheme statements
   (O1, 35%) are medium kinds; their hard examples are hard because of one specific step inside.
4. **Hard kinds to consider building:** amounts after a hidden product (inorganic C with B2), amounts through a
   scheme (organic O3), reagent choice (O4, R), counting in a product (O2), and physical trap questions (P2).

## Caveats

- Small numbers: only 2022–2025 has student data, and several kinds have n = 1–3.
- Year effect: 2022 was a hard paper overall, and many of the lowest % come from it.
- Format effect: multiple-correct questions have partial marking, so "% full marks" is lower for them.
- Data errors: 2025 Paper 2 Q8–Q16 repeat Paper 1 with different %; I counted them once and averaged the two %.
  2022P1 Q16/Q17 store counts, not % (excluded). 2023P1 Q15 is a mathematics question (excluded).
- I labelled 2022–2025 with the % visible, so the trap labels (P2) may be biased. A blind re-label by someone else
  would settle that.
- Some question texts are images or were cut in the data; those were labelled from the sub-topic.
