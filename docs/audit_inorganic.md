# Inorganic concept-book audit

Scope: all 904 entries of `knowledge/concept_book_inorg.json`: the 412 that became graph edges, the 492 the graph build left out, plus the 123 "fragile concept" and 134 "exception" notes. Numbers below are entry indexes (`#n` = `valid_transformations[n]`).

Status (2026-10-13): all sections approved and applied. Adjustments made while applying:
- 368, 780, 827: only the doubtful part was removed (SiX₄ rate order; Sr/Ba oxalate solubility; C₃₆K/C₆₀K colours). The verified reaction stays usable.
- 804: the moist-air equation in the note was unbalanced; it now reads 4KO₂ + 4CO₂ + 2H₂O → 4KHCO₃ + 3O₂.
- 629, 646: the substrate is written first (KI + H₂O₂; the Xe : F₂ ratio moved to the conditions), so the graph edge reads KI → I₂ and Xe → XeF₂.

## A. Wrong chemistry: proposed fixes

| # | Book says | Fix |
|---|---|---|
| 367 | CCl₄ + superheated steam → "CCl₂" + 2HCl | CCl₄ + H₂O → COCl₂ + 2HCl |
| 373, 429 | NCl₃ + H₂O → NH₃ + HCl, "no HOCl" | NCl₃ + 3H₂O → NH₃ + 3HOCl |
| 372 | "BCl₂" hydrolysis | remove (BCl₂ is not a real compound) |
| 316 | NaH + CO → HCOONa + C (book unsure) | NaH + CO₂ → HCOONa |
| 319, 821 | 4NaH + B(OH)₃ → NaBH₄ + 3NaOH | 4NaH + B(OCH₃)₃ → NaBH₄ + 3NaOCH₃ |
| 648 | XeF₂ + 2H₂O → Xe + 4HF + O₂ (F unbalanced) | 2XeF₂ + 2H₂O → 2Xe + 4HF + O₂ |
| 539 | 3BCl₃ + 3NH₄Cl → B₃N₃H₃Cl₃ + 3HCl | … + 9HCl |
| 541 | borazine + 3HCl → B₃N₃H₆Cl₃, "addition at N" | B₃N₃H₉Cl₃; H adds to N, Cl to B |
| 517 | thermite written with Al₂O₃ as reactant | 2Al + Fe₂O₃ → 2Fe + Al₂O₃ |
| 514 | amalgamated Al + H₂O → Al₂O₃ + H₂ | 2Al + 6H₂O → 2Al(OH)₃ + 3H₂ |
| 636, 637 | 2NaX + MnO₂ + 3H₂SO₄ → X₂ + MnSO₄ + Na₂SO₄ + 2H₂O (S unbalanced) | 2H₂SO₄ |
| 526 | borax + 12HF → … (garbled) | Na₂B₄O₇ + 12HF + 2H₂SO₄ → 4BF₃ + 2NaHSO₄ + 7H₂O |
| 530 | LiAlH₄ + AlCl₃ → (AlH₃)n + LiCl + AlCl₃? | 3LiAlH₄ + AlCl₃ → 4AlH₃ + 3LiCl |
| 706 | SO₃²⁻ + Zn + 8H⁺ → H₂S + Zn²⁺ + 3H₂O (charge unbalanced) | 3Zn … 3Zn²⁺ |
| 726 | cacodyl test gives Na₂O | 4CH₃COONa + As₂O₃ → (CH₃)₂As–O–As(CH₃)₂ + 2Na₂CO₃ + 2CO₂ |
| 817 | KBr + ICl → "K[BrCl]" | K[IBrCl] |
| 887 | gunpowder "K₂S? Actually…" | 2KNO₃ + S + 3C → K₂S + N₂ + 3CO₂ |
| 814 | second step 4NaNO₃ → 2Na₂O + 2N₂ + 5O₂ (book unsure) | keep only 2NaNO₃ → 2NaNO₂ + O₂ |
| 253 | KMnO₄ + Mn²⁺ called "autocatalytic" | drop the label (equation is right) |
| 784 | zinc uranyl acetate listed as test for K⁺ | it is the test for Na⁺ (NaZn(UO₂)₃(OAc)₉, yellow) |
| 739 | chromyl chloride: "PbCl₄" doesn't respond | PbCl₂ |
| 646 | XeF₂ made with Xe : F₂ = 1 : 5 | 2 : 1 (excess Xe); 1 : 5 is XeF₄ |
| 704 | HSO₃⁻ solution is neutral | slightly acidic |
| 217 | [Ma₂b₂cd]: 8 geometrical isomers | 6 geometrical, 8 stereoisomers (code-checked) |
| 218 | [M(AA)₂a₂]: 3 geometrical (cis-α, cis-β, trans) | 2 geometrical, 3 stereoisomers (code-checked) |
| 235 | CrCl₃·6H₂O has four hydrate isomers | three |
| 189 | tetrahedral field: e set "points between axes" | e points along the axes; t₂ between them |
| 174 | flexidentate examples NCS⁻/SCN⁻ (those are ambidentate) | CO₃²⁻, SO₄²⁻ (mono- or bidentate) |
| 171 | EDTA³⁻ listed as tetradentate | remove from the list (it is pentadentate, #172) |
| 221 | polymerisation isomer [Pt(NH₃)₃Cl₂][PtCl₄] | [Pt(NH₃)₃Cl]₂[PtCl₄] |
| 185 | ferrocene EAN garbled | 26 − 2 + 2×6 = 36 |
| 23 | (SiH₃)₂O angle ~180°, O sp | ~144° |
| 77 | XeO₃F₂ μ ≠ 0 | μ = 0 (F axial, O equatorial: symmetric) |
| 98 | LiF vs NaCl m.p. garbled | LiCl (605 °C) < NaCl (801 °C): covalent character |
| 139, 140 | PO₄³⁻ "1.25? not sure", ClO₄⁻ no value | P–O 1.25, Cl–O 1.75 |
| 42 | NO bond length 113 pm | 115 pm |
| 347 | CH₃OCH₃ b.p. −5 °C | −24 °C |
| 350 | nitrophenol acidity p > m > o | p > o > m (pKa 7.15, 7.23, 8.4) |
| 365 | Kw(D₂O) = 3.0×10⁻¹⁵ | 1.95×10⁻¹⁵ (NCERT) |
| 665 | element 101 symbol "Uun" | Unu |
| 690 | Hannay–Smith gives 50 % ionic at Δχ = 1.7 | that is Pauling's rule; Hannay–Smith gives 37 % |
| exception 65 | "self-reduction is not used for Hg" | JEE lists Cu, Pb, Hg under self-reduction (2HgO + HgS → 3Hg + SO₂); remove |
| exception 109 | NaHCO₃ "exception" (book says it isn't one) | remove |

## B. Doubtful: the book's claim can't be confirmed

Proposal: keep these in the book but exclude them from generated questions.

- 366: NF₃ + H₂O (drastic) → N₂O₃ + HF
- 405: SeF₆ partial hydrolysis (SeF₆ is usually described as nearly inert)
- 427, 368: hydrolysis rate SiF₄ > SiCl₄ > SiBr₄ > SiI₄
- 561: Si + 2HCl → SiH₂Cl₂ (the usual reaction is Si + 3HCl → SiHCl₃ + H₂)
- 780: SrC₂O₄ "insoluble" in acetic acid
- 827: KC₃₆ blue, KC₆₀ grey
- 499: stainless steel 12–14 % Cr, 2–4 % Ni (common JEE figure is 18 % Cr, 8 % Ni)

## C. Text clean-up only (no chemistry change)

These entries keep their correct statement. Only the leftover thinking text ("? Actually…", "Wait", "MCQ says…", "Passage 3…") is removed:

10, 14, 19, 41, 49, 55, 58, 63, 64, 65, 69, 73, 74, 123, 127, 133, 138, 179, 202, 220, 231, 232, 238, 263, 292, 337, 341, 351, 357, 375, 376, 389, 392, 409, 416, 420, 422, 431, 433, 436, 437, 438, 439, 629, 661, 671, 675, 683, 684, 686, 711, 731, 768, 779, 802, 803, 804, 815, 850, 866, 889, 892, 897, 900, 902; exceptions 48, 73, 92, 104, 127.

Equations in 337, 341 and 866 were checked and balance as written.

## D. Remove, move or merge

- Empty or no content: 129 (AlCl₃ vs AlBr₃ "not in text"), 609 (NCl₃ with no products).
- Organic, so moved to the organic audit: 417 (CH₃Cl SN2), 522 (Friedel–Crafts).
- Duplicates merged (the graph keeps one edge): 469 → 451, 494 → 460, 612 → 376, 608 → 381, 860 → 634, 846 → 558, 820 → 531, 833 → 813, 648/649/650 vs 389/390/391.

## E. Reclassify

- Structure facts that became reaction edges are moved to facts: 102 (Al₂Cl₆), 118 (FeO defect), 361 (NaHCO₃ H-bonding), 521 (Al₂Cl₆).
- Multi-step edges split into single steps: 277 (ZnSO₄·7H₂O), 296 (FeSO₄·7H₂O), 471 (Mond), 472 (van Arkel), 884 (Na → Na₂O → Na₂O₂).

## Code cross-checks that will ship with the engine

- Octahedral isomer counter (brute force over the 24 rotations / 48 symmetry operations). It confirms 216, 219, 220, 231 and 232 and caught 217 and 218.
- Equation balancer (`chem.balance`) runs on every equation the inorganic engine uses.
- VSEPR (steric number → shape) and unpaired-electron or spin-only μ checks for structure and magnetism facts.
