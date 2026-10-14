# How JEE Advanced uses formulas (physical chemistry, 2012–2025)

Read by hand, 2026-10-14: all 162 Physical Chemistry questions in `data/jee_advanced/*.json`
(question text + solution summary). Of these, 85 unique questions are computational (the rest are
statement/concept MSQs or exact repeats). Each is classified by how the formulas are used.
A question can show two patterns; it is counted under its main one.

## Counts (85 computational questions)

| Pattern | How the formula is used | Count | Share |
|---|---|---|---|
| Forward chain | givens → formula → next formula → asked quantity, in order | 28 | 33 % |
| Inverse | the asked quantity is an INPUT of a formula; the output is given (find x in a Nernst equation, the age from a Pb/U ratio, the current for 1 mol Cr³⁺) | 14 | 16 % |
| Two states / ratio | the same formula for two systems or conditions; the answer is their ratio or difference (Ka(HX)/Ka(HY) from conductivities, t₁/₈ : t₁/₁₀, λ(He)/λ(Ne), ΔT_b before and after mixing) | 17 | 20 % |
| Simultaneous / coupled | two unknowns tied by two formulas or two linked equilibria (salt of a weak acid at a fixed pH, PbSO₄ in H₂SO₄ with K_a2, two compositions of an ideal solution, m + n + p from Kohlrausch) | 11 | 13 % |
| Condition / threshold | find the value at which something becomes zero, equal or just possible (graphite ⇌ diamond pressure, minimum p(H₂) to stop oxidation, minimum [H⁺] to stop ZnS precipitating, equal work of two processes) | 6 | 7 % |
| Graph | a linearised formula read off a plot (vdW PV vs 1/V, ln K vs 1/T slope and intercept, pK_b from a titration curve) | 7 | 8 % |
| Symbolic / rearrangement | the answer is an expression or a coefficient of the rearranged formula (K_p in terms of β, the vdW cubic's coefficients, P/S of 1/Λm vs cΛm) | 6 | 7 % |
| Calculus | the formula is integrated (S_β − S_α at 300 K from ∫ΔC_p/T dT; ΔG = ∫V dP) | 3 | 4 % (calculus also hides in several "condition" items) |

So about two thirds of real Advanced computational questions do NOT run the formulas forward
in chain order. Our engine builds only forward chains. Cross-topic links (kinetics → equilibrium
via K = k_f/k_b, nuclear → gas pressure, electrochemistry → adiabatic work) occur in all patterns.

## Does the pattern change difficulty for the ladder's bottom step?

Calibrated Advanced physical questions (2021–2025, 24 unique computational items), Phi-4:

| Pattern | Items | Phi-4 fails |
|---|---|---|
| Forward | 9 | 2 (22 %) |
| Not forward (inverse, two-state, simultaneous, symbolic) | 15 | 8 (53 %) |

GLM-5.3 fails 33 % and 20 % (it slips on forward arithmetic), consistent with GLM not separating
easy from hard. The sample is small, but the direction is clear: the non-forward patterns are
what the bottom step finds hard, and they are what our generated questions lack.

## Per-question classification (computational items)

Forward: 2012P2_Q28, 2012P2_Q30, 2013P1_Q29, 2013P2_Q21, 2014P1_Q40, 2015P2_Q38, 2016P1_Q20,
2017P1_Q26, 2017P1_Q27, 2017P1_Q36, 2019P1_Q14, 2019P1_Q15, 2019P2_Q10, 2019P2_Q13, 2020P1_Q5,
2020P1_Q13, 2020P1_Q15, 2020P1_Q16, 2020P1_Q17, 2020P2_Q15, 2020P2_Q17, 2021P1_Q9, 2021P2_Q11/12,
2021P2_Q18, 2022P1_Q1, 2022P1_Q3, 2023P2_Q12, 2024P2_Q8, 2025_Q11.

Inverse: 2012P1_Q40, 2012P2_Q25, 2012P2_Q29, 2014P2_Q23, 2016P2_Q21, 2018P1_Q8, 2019P1_Q16,
2022P1_Q2, 2022P2_Q2, 2023P2_Q11, 2024P1_Q1, 2024P2_Q11, 2025_Q8, 2013P1_Q21.

Two states / ratio: 2012P1_Q36, 2013P1_Q31, 2013P1_Q36, 2014P1_Q38, 2014P2_Q31, 2015P2_Q27,
2015P2_Q28, 2015P2_Q37, 2016P1_Q33, 2017P1_Q32, 2018P1_Q12, 2018P2_Q11, 2020P1_Q14, 2021P1_Q10,
2023P1_Q6, 2023P1_Q9, 2024P2_Q9.

Simultaneous / coupled: 2015P1_Q28, 2016P1_Q32, 2018P1_Q9, 2018P1_Q10, 2018P1_Q11, 2020P2_Q14,
2021P2_Q7/8, 2022P2_Q1, 2022P2_Q3, 2025_Q9, 2023P1_Q12.

Condition / threshold: 2017P2_Q20, 2018P2_Q10, 2018P2_Q12, 2020P2_Q18, 2021P2_Q17, 2023P1_Q11.

Graph: 2012P1_Q24, 2020P2_Q13, 2021P1_Q7, 2021P1_Q8, 2023P1_Q10, 2024P1_Q8, 2023P1_Q5.

Symbolic / rearrangement: 2012P1_Q22, 2016P2_Q33, 2017P2_Q19, 2024P1_Q9, 2025_Q10, 2014P1_Q36.

Calculus: 2023P2_Q14, 2023P2_Q15, 2016P1_Q19 (radial probability; qualitative).
