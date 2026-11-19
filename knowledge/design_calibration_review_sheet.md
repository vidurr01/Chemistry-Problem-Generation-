# Reverse-design review sheet (physical, 2026-11-17)

Each design was checked against its real question and official answer by Claude (AI assistant).
Suggestion per design below; `python tools/calibrate_design.py accept` records them as the author's review.

## 2012P1_Q40: OK
Question: 29.2% (w/w) HCl stock solution has a density of 1.25 g mL⁻¹. The molecular weight of HCl is 36.5 g mol⁻¹. The volume (mL) of stock solution required to prepare a 200 mL solution of 0.4 M HCl is:
Official answer: 8
Design: system: A concentrated stock solution of hydrochloric acid (HCl) diluted with water to prepare a target dilute solution.
- link: The molarity of the stock solution ($M_1$), which connects the concentration percentage/density equation to the dilution equation ($M_1V_1 = M_2V_2$).
- route: Formula 1 takes the density, weight percentage, and molar mass of HCl to give the stock solution molarity; Formula 2 takes this stock molarity alongside target molarity and target volume to give the required stock volume.
- asked: Volume of stock solution required, in mL
Note: describes the question faithfully

## 2013P1_Q36: OK
Question: The atomic masses of He and Ne are 4 and 20 a.m.u. respectively. The value of the de Broglie wavelength of He gas at -73°C is 'M' times that of the de Broglie wavelength of Ne at 727°C. M is
Official answer: 5
Design: system: Helium gas at -73°C and Neon gas at 727°C behaving as ideal monoatomic gases.
- link: Momentum $p$ links de Broglie's equation to the kinetic energy derived from temperature via $p = \sqrt{2m(KE)} = \sqrt{3mkT}$.
- route: Formula 2 calculates the average kinetic energy from temperature, which determines the momentum for each gas; Formula 1 uses this momentum and mass to calculate the ratio of de Broglie wavelengths.
- asked: ratio of de Broglie wavelength of He to that of Ne (dimensionless ratio M)
Note: describes the question faithfully

## 2014P1_Q38: OK
Question: MX2 dissociates in M²⁺ and X⁻ ions in an aqueous solution, with a degree of dissociation (α) of 0.5. The ratio of the observed depression of freezing point of the aqueous solution to the value of the depression of freezing point in the absence of ionic dissociation is
Official answer: 2
Design: system: An aqueous solution containing electrolyte MX2 that dissociates into M²⁺ and 2X⁻ ions at a given degree of dissociation.
- link: The requested ratio of observed freezing point depression to that without dissociation is identical to the van 't Hoff factor i.
- route: Formula 1 takes n = 3 and α = 0.5 to compute the van 't Hoff factor i; Formula 2 connects this factor directly as the ratio of depression of freezing points (ΔT_f(observed) / ΔT_f(normal) = i).
- asked: the ratio of the observed depression of freezing point to the depression of freezing point in the absence of dissociation (dimensionless)
Note: describes the question faithfully

## 2015P1_Q28: OK
Question: All the energy released from the reaction X→Y. ΔrG° = -193 kJ mol⁻¹ is used for oxidizing M+ as M+ → M3+ + 2e− E° = -0.25 V. Under standard conditions, the number of moles of M+ oxidized when one mole of X is converted to Y is [F = 96500 C mol⁻¹]
Official answer: 4
Design: system: A coupled system under standard conditions where the free energy released from a spontaneous reaction X → Y is entirely utilized to drive the non-spontaneous oxidation M⁺ → M³⁺ + 2e⁻.
- link: The molar Gibbs energy required to oxidize M⁺ (ΔrG°₂), calculated from its standard electrode potential via ΔG° = −nFE°, links the electrochemical half-reaction to the energy balance with reaction X → Y.
- route: Formula 1: Takes standard cell potential E° and number of transferred electrons (n = 2) to calculate the Gibbs energy change per mole of M⁺ oxidized (ΔrG°₂). Formula 2: Takes the driving reaction's released free energy |ΔrG°₁| and the energy required per mole of M⁺ (ΔrG°₂) to determine the number of moles of M⁺ oxidized.
- asked: Number of moles of M⁺ oxidized per mole of X converted to Y, dimensionless (moles)
Note: describes the question faithfully

## 2015P2_Q27: OK
Question: The molar conductivity of a solution of a weak acid HX (0.01 M) is 10 times smaller than the molar conductivity of a solution of a weak acid HY (0.10 M). If λx° ≈ λy°, the difference in their pKa values, pKa(HX) - pKa(HY), is (consider degree of ionization of both acids to be << 1)
Official answer: 3
Design: system: Aqueous solutions of two weak monoprotic acids, HX (0.01 M) and HY (0.10 M), at the same temperature with negligible degree of ionization.
- link: The degree of dissociation α links molar conductivity (Λm / Λ°m) to the acid dissociation constant Ka (via Ostwald's dilution law Ka ≈ Cα²).
- route: Formula 1 (α = Λm/Λ°m): takes the ratio of molar conductivities and equal limiting molar conductivities to give the ratio of degrees of dissociation α(HX)/α(HY) = 1/10. Formula 2 (Ka = Cα²): takes the concentration ratio and α ratio to give the ratio Ka(HX)/Ka(HY) = 10⁻³, which directly yields pKa(HX) - pKa(HY).
- asked: difference in pKa values, pKa(HX) - pKa(HY), dimensionless
Note: describes the question faithfully

## 2016P1_Q32: OK
Question: The mole fraction of a solute in a solution is 0.1. At 298 K, molarity of this solution is the same as its molality. Density of this solution at 298 K is 2.0 g cm⁻³. The ratio of the molecular weights of the solute and solvent, (MW_solute / MW_solvent), is
Official answer: 9
Design: system: A binary solution of a solute and a solvent at 298 K with a defined density and mole fraction.
- link: Equating the general expressions of molarity and molality via the condition molarity = molality, which eliminates the absolute molar amounts and directly links density to the molar mass ratio.
- route: Formula 1 and Formula 2 are equated using the condition M = m, taking mole fractions and solution density to directly solve for the ratio MW_solute / MW_solvent.
- asked: ratio of the molecular weights of solute and solvent (MW_solute / MW_solvent), unitless
Note: describes the question faithfully

## 2016P1_Q33: OK
Question: The diffusion coefficient of an ideal gas is proportional to its mean free path and mean speed. The absolute temperature of an ideal gas is increased 4 times and its pressure is increased 2 times. As a result, the diffusion coefficient of this gas increases x times. The value of x is
Official answer: 4
Design: system: An ideal gas undergoing changes in absolute temperature and pressure.
- link: Temperature ($T$) and pressure ($P$) simultaneously control both the mean free path ($\lambda \propto T/P$) and mean speed ($\bar{u} \propto \sqrt{T}$), which multiply to determine the diffusion coefficient ($D$).
- route: Formula 1: takes temperature and pressure factors to find the scaling factor of mean free path ($\lambda \propto T/P$). Formula 2: takes temperature factor to find the scaling factor of mean speed ($\bar{u} \propto \sqrt{T}$), then multiplies them to give the scaling factor of the diffusion coefficient ($D \propto T^{3/2}/P$).
- asked: the factor $x$ by which the diffusion coefficient increases, dimensionless
Note: describes the question faithfully

## 2017P1_Q26: OK
Question: The conductance of a 0.0015 M aqueous solution of a weak monobasic acid was determined by using a conductivity cell of cell constant 1000 m−1. The conductance of the solution was found to be 5 × 10−7 S. The degree of dissociation of acid is 0.01. The value of limiting molar conductivity of the acid,…
Official answer: 6
Design: system: Dilute aqueous solution of a weak monobasic acid in a conductivity cell.
- link: none
- route: Formula 1 (κ = G × G*) takes conductance and cell constant to yield conductivity κ; Formula 2 (Λm = κ / c) takes conductivity and concentration to yield molar conductivity Λm; Formula 3 (Λ°m = Λm / α) takes molar conductivity and degree of dissociation to yield limiting molar conductivity Λ°m.
- asked: limiting molar conductivity of the acid, in S m² mol⁻¹
Note: describes the question faithfully

## 2017P1_Q27: OK
Question: A 10 L container contains a mixture of 1 mole each of A and B. The following reaction is allowed to take place: 2A(g) + B(g) ⇌ C(g) + D(g). At equilibrium, 0.1 mole of D is formed. The equilibrium constant Kc is
Official answer: 0.014
Design: system: Gaseous equilibrium 2A(g) + B(g) ⇌ C(g) + D(g) in a rigid 10 L container at a constant temperature.
- link: The equilibrium molar concentrations of all species connect the ICE stoichiometric calculation (Formula 1) to the equilibrium constant expression (Formula 2).
- route: Formula 1 takes initial moles of A, B, and equilibrium moles of D to give the equilibrium moles of A, B, and C; Formula 2 takes these equilibrium moles and the container volume to calculate Kc.
- asked: The equilibrium constant Kc
Note: describes the question faithfully

## 2018P2_Q10: OK
Question: The surface of copper gets tarnished by the formation of copper oxide. N2 gas was passed to prevent the oxide formation during heating of copper at 1250 K. However, the N2 gas contains 1 mole % of water vapour as impurity. The water vapour oxidises copper as per the reaction given below: 2Cu(s) + H2…
Official answer: -14.60
Design: system: Oxidation of copper by trace water vapor in an inert nitrogen carrier gas at 1250 K forming solid cuprous oxide and hydrogen gas.
- link: The boundary condition preventing oxidation corresponds to the reaction reaching thermodynamic equilibrium, where the reaction quotient equals the equilibrium constant.
- route: Formula 1: Takes the standard Gibbs energies of the formation reactions and subtracts them via Hess's law to give the net reaction's ΔG°. Formula 2: Takes the net ΔG°, temperature, and gas constant to calculate ln(K). Formula 3: Takes K and the partial pressure of water vapor (from total pressure and mole percent) to find the minimum ln(p_H2).
- asked: The value of ln(p_H2) where p_H2 is in bar, dimensionless
Note: describes the question faithfully

## 2018P2_Q11: OK
Question: Consider the following reversible reaction, A(g) + B(g) ⇌ AB(g). The activation energy of the backward reaction exceeds that of the forward reaction by 2RT (in J mol−1). If the pre-exponential factor of the forward reaction is 4 times that of the reverse reaction, the absolute value of ΔG° (in J mol…
Official answer: 8500.00
Design: system: A reversible gas-phase reaction A(g) + B(g) ⇌ AB(g) at 300 K governed by Arrhenius kinetics and thermodynamics.
- link: The equilibrium constant K connects Arrhenius rate parameters (via K = k_f / k_b) to the thermodynamic standard Gibbs energy change ΔG°.
- route: Formula 1 takes the ratio of pre-exponential factors (A_f/A_b) and the activation energy difference (E_a,b - E_a,f) to compute the equilibrium constant K; Formula 2 takes K and RT to compute ΔG°.
- asked: Absolute value of standard Gibbs free energy change |ΔG°| in J mol⁻¹
Note: describes the question faithfully

## 2018P2_Q12: BAD
Question: Consider an electrochemical cell: A(s) | An+(aq, 2M) || B2n+(aq, 1M) | B(s). The value of ΔH° for the cell reaction is twice that of ΔG° at 300 K. If the emf of the cell is zero, the ΔS° (in J K−1 mol−1) of the cell reaction per mole of B formed at 300 K is (Given: ln(2)=0.7, R=8.3 J K−1 mol−1)
Official answer: -11.62
Design: system: Electrochemical cell 2A(s) + B2n+(aq, 1 M) -> 2An+(aq, 2 M) + B(s) at 300 K.
- link: The reaction quotient Q relates cell potential to standard potential via the Nernst equation, connecting E° directly to ΔG° via ΔG° = -nFE°.
- route: Nernst equation: takes concentrations and E = 0 to give E° (or directly gives ΔG° via RT ln Q); Gibbs-Helmholtz relation: takes ΔH° = 2ΔG° and T = 300 K to give ΔS° = -ΔG°/T.
- asked: ΔS° of the cell reaction per mole of B formed at 300 K, in J K−1 mol−1
Note: the route has a sign error: from ΔH° = 2ΔG° it follows ΔS° = ΔG°/T, not −ΔG°/T (the official answer −11.62 needs ΔS° = ΔG°/T)

## 2019P1_Q14: OK
Question: On dissolving 0.5 g of a non-volatile non-ionic solute to 39 g of benzene, its vapour pressure decreases from 650 mm Hg to 640 mm Hg. The depression of freezing point of benzene (in K) upon addition of the solute is (Given data: Molar mass and molal freezing point depression constant of benzene are …
Official answer: 1.02
Design: system: A solution prepared by dissolving a non-volatile, non-ionic solute in pure benzene solvent.
- link: The molar mass of the solute (M₂), which connects Raoult's law for relative lowering of vapour pressure to molality in the freezing point depression formula.
- route: Formula 1: takes vapor pressure of pure solvent, vapor pressure of solution, mass of solute, mass of solvent, and molar mass of solvent to give the molar mass of the solute. Formula 2: takes mass of solute, mass of solvent, and the calculated molar mass of solute to give molality. Formula 3: takes molality, van 't Hoff factor, and the molal depression constant to give the depression of freezing point.
- asked: depression of freezing point of benzene, in K
Note: describes the question faithfully

## 2019P1_Q15: OK
Question: For the following reaction, the equilibrium constant Ke at 298 K is 1.6×10^17: Fe²⁺(aq) + S²⁻(aq) ⇌ FeS(s). When equal volumes of 0.06 M Fe²⁺(aq) and 0.2 M S²⁻(aq) solutions are mixed, the equilibrium concentration of Fe²⁺(aq) is found to be Y×10⁻¹⁷ M. The value of Y is
Official answer: 8.93
Design: system: Aqueous precipitation equilibrium of Fe²⁺ and S²⁻ forming solid FeS at 298 K after mixing equal volumes of their solutions.
- link: The post-mixing excess concentration of S²⁻ acts as the connecting link to determine the tiny residual equilibrium concentration of Fe²⁺ using the inverted equilibrium relation.
- route: Formula 1: Takes initial concentrations and 1:1 mixing to give the unreacted excess concentration of S²⁻ in the final total volume; Formula 2: Takes the formation equilibrium constant (Ke) and the excess [S²⁻] to give the equilibrium concentration of Fe²⁺.
- asked: The coefficient Y in the equilibrium concentration of Fe²⁺ expressed as Y × 10⁻¹⁷ M
Note: describes the question faithfully

## 2019P1_Q16: OK
Question: For the reaction, the rate law is Rate = k[A]^x[B]^y[C]^z. Data from experiments: (1) [A]=0.2, [B]=0.1, [C]=0.1, rate=6.0×10^-5; (2) [A]=0.2, [B]=0.2, [C]=0.1, rate=6.0×10^-5; (3) [A]=0.2, [B]=0.1, [C]=0.2, rate=1.2×10^-4; (4) [A]=0.3, [B]=0.1, [C]=0.1, rate=9.0×10^-5. The rate of the reaction for […
Official answer: 6.75
Design: system: A chemical reaction involving reactants A, B, and C obeying a general rate law with unknown partial orders x, y, and z.
- link: The reaction orders (x, y, z) deduced by comparing experimental runs are used to scale the rate from a reference run to the target concentration set.
- route: Formula 1 takes initial rates and concentrations from paired experimental runs where only one reactant varies to determine the individual reaction orders (x=1, y=0, z=1). Formula 2 takes the determined orders, reference concentrations and rate, and the new concentrations to calculate the new reaction rate.
- asked: The coefficient Y in the reaction rate Y × 10^-5 mol L^-1 s^-1 (dimensionless number).
Note: describes the question faithfully

## 2020P1_Q13: OK
Question: 5.00 mL of 0.10 M oxalic acid solution taken in a conical flask is titrated against NaOH from a burette using phenolphthalein indicator. The volume of NaOH required for the appearance of permanent faint pink color is tabulated below for five experiments. What is the concentration, in molarity, of th…
Official answer: 0.11
Design: system: Oxalic acid (diprotic acid) titrated with sodium hydroxide (monoprotic base) in an aqueous solution using phenolphthalein indicator at room temperature.
- link: The n-factor of oxalic acid (equal to 2) and the concordant titer volume from the experimental data table join the molar concentration to the equivalence law.
- route: Formula 1: takes the molarity, volume, and n-factor of oxalic acid to give the milliequivalents of acid neutralized. Formula 2: takes the milliequivalents of acid and the concordant volume of NaOH to give the molarity of the NaOH solution.
- asked: Concentration of the NaOH solution, in molarity (M)
Note: describes the question faithfully

## 2020P1_Q15: OK
Question: Consider a 70% efficient hydrogen-oxygen fuel cell working under standard conditions at 1 bar and 298 K. Its cell reaction is H2(g) + ½O2(g) → H2O(l). The work derived from the cell on the consumption of 1.0×10⁻³ mol of H2(g) is used to compress 1.00 mol of a monoatomic ideal gas in a thermally insu…
Official answer: 13.32
Design: system: A standard H2-O2 fuel cell operating at 1 bar and 298 K connected to an adiabatic container holding a monoatomic ideal gas.
- link: The electrical work obtained from the fuel cell (scaled by its 70% efficiency) equals the adiabatic compression work done on the ideal gas, which in turn equals its change in internal energy (w = ΔU).
- route: Formula 1 takes the standard electrode potentials of cathode and anode to give E°cell. Formula 2 takes E°cell and n = 2 to give ΔG°. Formula 3 takes ΔG°, the moles of H2 consumed, and the 70% efficiency to give the actual useful work done on the gas. Formula 4 takes this work along with n_gas = 1.00 mol and Cv = (3/2)R for a monoatomic gas to give the temperature change ΔT.
- asked: change in the temperature of the ideal gas, in K
Note: describes the question faithfully

## 2020P1_Q16: BAD
Question: Aluminium reacts with sulfuric acid to form aluminium sulfate and hydrogen. What is the volume of hydrogen gas in litre (L) produced at 300 K and 1.0 atm pressure, when 5.4 g of aluminium and 50.0 mL of 5.0 M sulfuric acid are combined for the reaction? (Use molar mass of aluminium as 27.0 g mol⁻¹, …
Official answer: 6.15
Design: system: Reaction of solid aluminium with aqueous sulfuric acid producing aluminium sulfate and hydrogen gas at 300 K and 1.0 atm.
- link: The moles of H₂ produced are determined by the limiting reagent, which links the reaction stoichiometry to the ideal gas law.
- route: 1. Molar mass and mass of Al give moles of Al. 2. Molarity and volume give moles of H₂SO₄. 3. Stoichiometry of 2Al + 3H₂SO₄ → Al₂(SO₄)₃ + 3H₂ gives the limiting reagent (Al). 4. Limiting reagent moles give moles of H₂. 5. Ideal gas equation converts moles of H₂ to volume at specified T and P.
- asked: volume of hydrogen gas, in litre (L)
Note: names the wrong limiting reagent: 0.25 mol H₂SO₄ against 0.20 mol Al (needs 0.30) makes H₂SO₄ limiting, which gives the official 6.15 L; the design says Al

## 2020P1_Q17: OK
Question: ²³⁸₉₂U is known to undergo radioactive decay to form ²⁰⁶₈₂Pb by emitting alpha and beta particles. A rock initially contained 68×10⁻⁶ g of ²³⁸₉₂U. If the number of alpha particles that it would emit during its radioactive decay of ²³⁸₉₂U to ²⁰⁶₈₂Pb in three half-lives is Z×10¹⁸, then what is the val…
Official answer: 1.20
Design: system: Radioactive decay of a uranium-238 sample to lead-206 via alpha and beta emission over three half-lives.
- link: The stoichiometric number of alpha particles emitted per uranium nucleus (8) multiplies the amount of uranium nuclei that decayed.
- route: Formula 2 gives the number of alpha particles emitted per decayed U-238 nucleus from mass number differences; Formula 1 gives the fraction of uranium decayed after 3 half-lives (7/8); Formula 3 combines initial mass, molar mass, Avogadro's constant, decayed fraction, and alpha multiplier to give the total number of alpha particles emitted.
- asked: Value of Z (where the total number of emitted alpha particles is Z × 10¹⁸), unitless
Note: describes the question faithfully

## 2020P2_Q17: OK
Question: Tin is obtained from cassiterite by reduction with coke. Use the data given below to determine the minimum temperature (in K) at which the reduction of cassiterite by coke would take place. At 298 K: ΔH°(SnO2(s)) = -581.0 kJ mol⁻¹, ΔH°(CO2(g)) = -394.0 kJ mol⁻¹, S°(SnO2(s)) = 56.0 J K⁻¹ mol⁻¹, S°(Sn…
Official answer: 935
Design: system: Reduction of solid cassiterite (SnO2) by solid carbon (coke) to produce solid tin (Sn) and carbon dioxide gas (CO2).
- link: none
- route: Formula 1 takes stoichiometric coefficients and standard formation enthalpies to yield standard reaction enthalpy ΔrH°; Formula 2 takes stoichiometric coefficients and standard molar entropies to yield standard reaction entropy ΔrS°; Formula 3 takes ΔrH° and ΔrS° to compute the equilibrium crossover temperature T = ΔrH° / ΔrS° where ΔrG° = 0.
- asked: Minimum temperature at which the reduction of cassiterite by coke takes place, in K
Note: describes the question faithfully

## 2021P1_Q10: OK
Question: The boiling point of water in a 0.1 molal silver nitrate solution (solution A) is x °C. To this solution A, an equal volume of 0.1 molal aqueous barium chloride solution is added to make a new solution B. The difference in the boiling points of water in the two solutions A and B is y × 10⁻² °C. (Ass…
Official answer: 2.5
Design: system: Aqueous solutions of silver nitrate and barium chloride mixed in equal volumes, undergoing precipitation of silver chloride to form a mixed electrolyte solution.
- link: The stoichiometry of the precipitation reaction determines the remaining and newly formed ion concentrations (and thus the total effective molality) in solution B.
- route: Formula 2 calculates the boiling point elevation of solution A using its initial molality and van 't Hoff factor; Formula 1 uses stoichiometry to find the molar amounts of remaining Ba²⁺, NO₃⁻, and unreacted Cl⁻ ions after AgCl precipitation upon mixing equal volumes; Formula 2 calculates the new boiling point elevation of solution B and determines the absolute difference |y|.
- asked: The absolute value of y, where the boiling point difference between solutions A and B is |y| × 10⁻² °C.
Note: describes the question faithfully

## 2021P2_Q7: OK
Question: At 298 K the limiting molar conductivity of a weak monobasic acid is 4×10² S cm² mol⁻¹. At 298 K for an aqueous solution of the acid the degree of dissociation is α and the molar conductivity is y×10² S cm² mol⁻¹. At 298 K upon 20 times dilution with water, the molar conductivity of the solution bec…
Official answer: 0.22
Design: system: Aqueous solution of a weak monobasic acid at 298 K undergoing 20-fold dilution with water.
- link: The acid dissociation constant (K_a) remains invariant before and after dilution, linking the two states via Ostwald's dilution law.
- route: Formula 1 gives initial α = y/4 and diluted α' = 3y/4 = 3α. Formula 2 equates K_a for both states: Cα²/(1 - α) = (C/20)(3α)²/(1 - 3α) to solve directly for α.
- asked: Degree of dissociation (α) of the initial solution, dimensionless
Note: describes the question faithfully

## 2021P2_Q11: OK
Question: A sample (5.6 g) containing iron is completely dissolved in cold dilute HCl to prepare a 250 mL of solution. Titration of 25.0 mL of this solution requires 12.5 mL of 0.03 M KMnO4 solution to reach the end point. Number of moles of Fe2+ present in 250 mL solution is x × 10⁻² (consider complete disso…
Official answer: 1.875
Design: system: Iron dissolved in cold dilute HCl forming Fe²⁺ (FeCl₂) solution, titrated against acidic KMnO₄.
- link: The n-factor of KMnO₄ in acidic medium (5) and Fe²⁺ to Fe³⁺ (1) connects the molarity of KMnO₄ to the equivalents and moles of Fe²⁺.
- route: Formula 1 calculates milliequivalents of KMnO₄ using its volume and normality (5 × molarity). Formula 2 divides milliequivalents by the n-factor of Fe²⁺ (1) and scales up by the aliquot factor (250 mL / 25 mL) to find total moles of Fe²⁺.
- asked: value of x representing moles of Fe²⁺ in 250 mL solution as x × 10⁻²
Note: describes the question faithfully

## 2021P2_Q18: OK
Question: Consider a helium (He) atom that absorbs a photon of wavelength 330 nm. The change in the velocity (in cm s⁻¹) of He atom after the photon absorption is (Assume: Momentum is conserved when photon is absorbed. Use: Planck constant = 6.6×10⁻³⁴ J s, Avogadro number = 6×10²³ mol⁻¹, Molar mass of He = 4 …
Official answer: 30
Design: system: A single helium atom absorbing a photon of a specific wavelength in vacuum under conservation of momentum.
- link: The momentum of the absorbed photon ($p = h/\lambda$) is entirely transferred to the helium atom as $\Delta p = m \Delta v$.
- route: Formula 1 gives the photon's momentum from Planck constant and wavelength; Formula 2 computes the single atom mass from molar mass and Avogadro's number, then yields $\Delta v$ from momentum conservation.
- asked: Change in velocity of the helium atom in cm s⁻¹
Note: describes the question faithfully

## 2022P1_Q1: OK
Question: 2 mol of Hg(g) is combusted in a fixed volume bomb calorimeter with excess of O2 at 298 K and 1 atm into HgO(s). During the reaction, temperature increases from 298.0 K to 312.8 K. If heat capacity of the bomb calorimeter and enthalpy of formation of Hg(g) are 20.00 kJ K⁻¹ and 61.32 kJ mol⁻¹ at 298 …
Official answer: 90.39
Design: system: Combustion of Hg(g) with excess O2(g) to form HgO(s) in a rigid bomb calorimeter.
- link: The internal energy change of combustion connects the calorimetric heat absorption to the reaction enthalpy via the change in gaseous moles (Δn_g).
- route: Formula 1 takes calorimeter heat capacity and temperature rise to yield heat absorbed; Formula 2 takes heat absorbed and moles of Hg(g) to give Δ_rU; Formula 3 takes Δ_rU, Δn_g, and T to yield Δ_rH; Formula 4 takes Δ_rH and Δ_fH of Hg(g) to determine Δ_fH of HgO(s).
- asked: absolute value of the standard molar enthalpy of formation of HgO(s) at 298 K, in kJ mol⁻¹
Note: describes the question faithfully

## 2022P2_Q2: OK
Question: An aqueous solution is prepared by dissolving 0.1 mol of an ionic salt in 1.8 kg of water at 35°C. The salt remains 90% dissociated in the solution. The vapour pressure of the solution is 59.724 mm of Hg. Vapour pressure of water at 35°C is 60.000 mm of Hg. The number of ions present per formula uni…
Official answer: 5
Design: system: An aqueous solution of a partially dissociated ionic salt in water at 35°C.
- link: The van 't Hoff factor i connects colligative relative lowering of vapour pressure to the degree of dissociation and formula unit stoichiometry.
- route: Formula 1 (RLVP with i: (P° - P)/P° = (i * n_solute) / (n_solvent + i * n_solute) or dilute approximation) takes pure solvent vapour pressure, solution vapour pressure, and solvent mass to give the van 't Hoff factor i; Formula 2 (dissociation: i = 1 + (n - 1)α) takes i and the degree of dissociation α to give the number of ions per formula unit n.
- asked: number of ions present per formula unit of the ionic salt, unitless
Note: describes the question faithfully

## 2023P1_Q9: OK
Question: A gas has a compressibility factor of 0.5 and a molar volume of 0.4 dm³ mol⁻¹ at a temperature of 800 K and pressure x atm. If it shows ideal gas behaviour at the same temperature and pressure, the molar volume will be y dm³ mol⁻¹. The value of x/y is [Use R = 8×10⁻² L atm K⁻¹ mol⁻¹]
Official answer: 100
Design: system: A real gas existing at 800 K and pressure x atm with compressibility factor 0.5, compared to an ideal gas at the same temperature and pressure.
- link: The compressibility factor definition relates real molar volume to ideal molar volume via Z = V_m(real) / V_m(ideal) under identical T and P conditions.
- route: Formula 1 gives pressure x using Z, V_m(real), R, and T; Formula 2 gives ideal molar volume y using R, T, and pressure x.
- asked: The value of x/y
Note: describes the question faithfully

## 2023P2_Q11: OK
Question: For He+, a transition takes place from the orbit of radius 105.8 pm to the orbit of radius 26.45 pm. The wavelength (in nm) of the emitted photon during the transition is ____. [Use: Bohr radius a = 52.9 pm, Rydberg constant RH = 2.2×10⁻¹⁸ J, h = 6.6×10⁻³⁴ J s, c = 3×10⁸ m s⁻¹]
Official answer: 30
Design: system: He+ single-electron ion undergoing an electronic transition between two Bohr orbits.
- link: The principal quantum numbers (n1 and n2) link the Bohr radius formula to the Rydberg transition wavelength formula.
- route: Formula 1: takes given orbital radii and atomic number (Z=2) to give initial and final principal quantum numbers (n2=2, n1=1). Formula 2: takes quantum numbers, Z, and fundamental constants to calculate photon wavelength.
- asked: wavelength of the emitted photon, in nm
Note: describes the question faithfully

## 2023P2_Q12: OK
Question: 50 mL of 0.2 mol urea solution (density = 1.012 g mL⁻¹ at 300 K) is mixed with 250 mL of a solution containing 0.06 g of urea. Both the solutions were prepared in the same solvent. The osmotic pressure (in Torr) of the resulting solution at 300 K is ____. [Use: Molar mass of urea = 60 g mol⁻¹; R = 6…
Official answer: 682
Design: system: A mixture of two aqueous urea solutions at 300 K under ideal mixing conditions.
- link: The total molarity (C) of the combined solution serves as the link between the solute amounts/volumes and the osmotic pressure equation.
- route: Moles of urea from solution 1 and solution 2 -> total moles and total volume -> mixture molarity C; then mixture molarity C -> osmotic pressure π via π = CRT.
- asked: osmotic pressure of the resulting solution, in Torr
Note: describes the question faithfully

## 2024P2_Q8: OK
Question: To form a complete monolayer of acetic acid on 1g of charcoal, 100 mL of 0.5 M acetic acid was used. Some of the acetic acid remained unadsorbed. To neutralize the unadsorbed acetic acid, 40 mL of 1 M NaOH solution was required. If each molecule of acetic acid occupies P × 10⁻²³ m² surface area on c…
Official answer: 2500
Design: system: Acetic acid monolayer adsorption on charcoal surface from aqueous solution, with remaining unadsorbed acid neutralized by aqueous NaOH.
- link: The moles of acetic acid actually adsorbed on the charcoal surface bridges the solution-phase back-titration stoichiometry with the surface area calculation.
- route: Formula 1: takes initial moles of acetic acid and moles of NaOH used to neutralize unadsorbed acid, gives moles (and then total number of molecules) of adsorbed acetic acid. Formula 2: takes total surface area of charcoal and total adsorbed molecules, gives cross-sectional surface area per molecule (and thus the coefficient P).
- asked: value of P (where area per molecule = P × 10⁻²³ m²), dimensionless
Note: describes the question faithfully
