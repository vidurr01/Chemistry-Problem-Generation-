"""
JEE Advanced physical chemistry (2012-2025) mapped onto the engine, by hand (2026-10-14).

For each computational question: the formulas its solution uses, in solution order, as engine
steps (concept-book tx ids, see core/engine/physical) or MISSING:<formula> when the engine has
no such step; and how the question USES them (forward, or modified: inverse, two-state ratio,
simultaneous, condition, graph, symbolic, calculus, tree = two branches merging).

    python docs/advanced_formula_map.py      # checks the chains and writes the table to
                                             # docs/advanced_formula_map.md
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# qid: (steps in solution order, modification, note)
MAP = {
    "2012P1_Q22": ([64, "MISSING:KE = ½mv² from mvr = nh/2π"], "symbolic", "KE as an expression in a₀"),
    "2012P1_Q24": ([103], "graph", "vdW with b = 0 linearised: PV vs 1/V, slope = −a"),
    "2012P1_Q36": ([209], "two-state ratio", "t(1/8)/t(1/10) from the same first-order law"),
    "2012P1_Q40": ([19, 23], "inverse", "target 0.4 M × 200 mL given; the stock volume V₁ is asked"),
    "2012P2_Q25": ([142], "inverse", "ΔH given; one bond enthalpy (C≡C) is the unknown"),
    "2012P2_Q28": ([262, "MISSING:molality -> mole fraction (21 inverted)", 255], "inverse",
                   "ΔT_b given -> molality (262 run backwards) -> lowering of vapour pressure"),
    "2012P2_Q29": ([241, 193], "inverse", "E of a concentration cell given -> unknown concentration S -> K_sp"),
    "2012P2_Q30": ([138], "forward", "ΔG = −nFE"),
    "2013P1_Q21": (["MISSING:t75 = 2 t50 => first order", "MISSING:order from a [Q]-t graph"], "graph",
                   "order read from a time ratio and a plot"),
    "2013P1_Q29": ([139, "MISSING:per gram (÷ M)"], "forward", "ΔcH from ΔfH, then per gram"),
    "2013P1_Q31": (["MISSING:rate ∝ [H⁺] (acid catalysis)", 175], "two-state ratio",
                   "rate(weak)/rate(strong) = 1/100 -> [H⁺] -> K_a (175 inverted); kinetics × ionic"),
    "2013P1_Q36": ([73, 101], "two-state ratio", "λ(He)/λ(Ne) at two temperatures"),
    "2013P2_Q21": ([195], "forward", "solubility with a common ion"),
    "2014P1_Q38": ([267, 263], "two-state ratio", "ΔT_f with dissociation / without = i"),
    "2014P1_Q40": ([20], "forward", "molarity -> molality, with 'volume of solution = volume of solvent'"),
    "2014P2_Q23": ([202], "forward", "order from the rate factor on doubling"),
    "2014P2_Q31": ([95, "MISSING:d/(L − d) = r₁/r₂ (meeting point)"], "inverse", "Graham ratio set into a distance equation"),
    "2015P1_Q28": ([138, "MISSING:energy balance between two processes"], "simultaneous",
                   "ΔG of one reaction drives the oxidation of M⁺: moles = ΔG₁/ΔG₂"),
    "2015P2_Q27": ([251, 173], "two-state ratio",
                   "Λm(HX)/Λm(HY) = 1/10 -> α ratio -> K_a ratio (173 inverted) -> pK_a difference"),
    "2015P2_Q28": ([224, 88], "two-state ratio", "U-238 -> Pb-206 + 8α: moles of gas before/after -> P ratio"),
    "2015P2_Q37": ([148, 144], "two-state difference", "heat of HCl + NaOH minus CH₃COOH + NaOH -> ΔH of dissociation"),
    "2015P2_Q38": ([187, 185], "forward", "WA + SB -> buffer ratio -> pH"),
    "2016P1_Q20": ([118, "MISSING:q = −w (isothermal ideal gas)", 130], "forward", "irreversible isothermal: w -> q -> ΔS_surr"),
    "2016P1_Q32": ([21, "MISSING:molarity from mole fraction and density"], "simultaneous",
                   "molarity = molality is the condition; M_solute/M_solvent is the unknown"),
    "2016P1_Q33": (["MISSING:mean free path ∝ T/P", 99], "two-state ratio", "D ∝ λ·ū: factor when T ×4 and P ×2"),
    "2016P2_Q21": ([239], "inverse", "E_cell given; x in [M²⁺]/[M⁴⁺] = 10ˣ is the unknown"),
    "2016P2_Q33": ([160], "symbolic", "K_p of X₂ ⇌ 2X in terms of β"),
    "2017P1_Q26": ([247, 248, 251], "inverse", "conductance -> κ -> Λm; α given, Λ°m asked (251 inverted)"),
    "2017P1_Q27": (["MISSING:ICE from extent", 152], "forward", "K_c from an extent of reaction"),
    "2017P1_Q32": ([65], "two-state ratio", "ΔE(2->4)/ΔE(2->6)"),
    "2017P1_Q36": ([1, "MISSING:molality from moles and solvent mass", 263], "forward", "mass -> moles -> molality -> ΔT_f"),
    "2017P2_Q19": ([239, "MISSING:ΔG = −nFE (non-standard)"], "symbolic", "ΔG as an expression in R, T, F"),
    "2017P2_Q20": (["MISSING:ΔG = ΔG° + VΔP"], "condition", "pressure at which graphite ⇌ diamond (ΔG = 0); ∫V dP"),
    "2018P1_Q8": ([239], "inverse", "E_cell given; [Mg²⁺] = x is the unknown"),
    "2018P1_Q9": ([88, 88], "simultaneous", "two compartments; equal P and T after the partition slides"),
    "2018P1_Q10": ([257, 257], "simultaneous", "two compositions: P°_B from one, x_A/x_B from the other"),
    "2018P1_Q11": (["MISSING:solubility of a salt of a weak acid at fixed pH (K_sp with K_a)"], "simultaneous",
                   "coupled K_sp and K_a"),
    "2018P1_Q12": ([262, 262, 267], "two-state ratio", "two solvents (K_b ratio from a plot), α of dimerisation (267 inverted)"),
    "2018P2_Q10": (["MISSING:Hess on ΔG°", 135], "condition", "minimum p(H₂): ΔG = 0 at the boundary, K = pH₂/pH₂O"),
    "2018P2_Q11": (["MISSING:Arrhenius k = A e^(−Ea/RT) for forward and backward", 210, 135], "two-state ratio",
                   "A ratio and Ea difference -> K = k_f/k_b -> ΔG° (135 inverted)"),
    "2018P2_Q12": ([239, 138, 132], "condition", "E = 0 gives E°; ΔH = 2ΔG; ΔS from 132 rearranged"),
    "2019P1_Q14": ([256, "MISSING:molality from masses and M", 263], "forward", "lowering -> M -> molality -> ΔT_f"),
    "2019P1_Q15": ([11, "MISSING:K for FeS(s) formation (1/[Fe²⁺][S²⁻])"], "forward", "excess S²⁻ after mixing -> [Fe²⁺]"),
    "2019P1_Q16": ([202, 202, 202, "MISSING:rate = k[A]^x[B]^y[C]^z"], "inverse", "orders from a table, then a new rate"),
    "2019P2_Q10": (["MISSING:moles from mole fraction and solvent mass", 10, "MISSING:molarity from moles and volume"],
                   "forward", "mole fraction + density -> molarity"),
    "2019P2_Q13": ([208], "inverse", "k and the final total pressure given; the time is asked"),
    "2020P1_Q5": ([205, 218], "forward", "2X + Y with rate = k[X]: stoichiometric factor 2 in −d[X]/dt"),
    "2020P1_Q13": ([35, 36], "forward", "titration: eq of acid -> N of NaOH"),
    "2020P1_Q14": ([135, 135], "two-state ratio", "ΔG° at 1000 K over ΔG° at 2000 K, K read from a plot (135 inverted)"),
    "2020P1_Q15": ([238, 138, 137, "MISSING:adiabatic w = nC_vΔT (115 inverted)"], "inverse",
                   "fuel-cell work (70 %) compresses a gas adiabatically: ΔT asked"),
    "2020P1_Q16": ([0, 13, 14, 11, 88], "forward", "limiting reagent -> H₂ moles -> V = nRT/P (88 inverted)"),
    "2020P1_Q17": ([209, 224, 3], "forward", "fraction decayed in 3 t½ × 8 α per U -> number of α"),
    "2020P2_Q13": ([191], "graph", "pK_b at half-equivalence read from a titration curve"),
    "2020P2_Q14": ([257, 257], "simultaneous", "two compositions, two total pressures -> P°_B"),
    "2020P2_Q15": (["MISSING:Coulomb PE of H atoms"], "forward", "−ke²/r per atom, ×2, ×N_A"),
    "2020P2_Q17": ([139, 131, 133], "tree", "ΔH from ΔfH AND ΔS from S° (two branches) -> T = ΔH/ΔS"),
    "2020P2_Q18": (["MISSING:[S²⁻] = K₁K₂[H₂S]/[H⁺]²", "MISSING:K_sp threshold"], "condition",
                   "minimum [H⁺] that keeps Q(ZnS) below K_sp"),
    "2021P1_Q7": ([315], "graph", "ΔH° from the slope of ln K vs 1/T"),
    "2021P1_Q8": (["MISSING:ΔS° from the intercept"], "graph", "ΔS° from the intercept of ln K vs 1/T"),
    "2021P1_Q9": ([262], "forward", "ΔT_b of 0.1 m AgNO₃ (i = 2)"),
    "2021P1_Q10": ([11, 262, 262], "two-state difference", "mixing AgNO₃ and BaCl₂ precipitates AgCl: ΔT_b before − after"),
    "2021P2_Q7": ([251, 173, 251, 173], "simultaneous", "Λm and 3Λm after 20× dilution, same K_a -> α"),
    "2021P2_Q11": ([35, "MISSING:eq -> moles (n-factor 1 for Fe²⁺)", "MISSING:aliquot ×10"], "forward",
                   "KMnO₄ titration of an aliquot -> moles Fe²⁺ in 250 mL -> % Fe"),
    "2021P2_Q17": ([119, 117], "condition", "adiabatic work = isothermal work -> ln(V₃/V₂)"),
    "2021P2_Q18": ([73, "MISSING:Δv = p/m"], "forward", "photon momentum h/λ -> Δv of He"),
    "2022P1_Q1": ([148, "MISSING:q per mole -> ΔU", 113, "MISSING:Hess with ΔfH(Hg, g)"], "forward",
                  "bomb calorimeter -> ΔU -> ΔH -> ΔfH(HgO) (Hess inverted)"),
    "2022P1_Q2": ([138, 138, 138, "MISSING:Hess on ΔG°", 138], "inverse", "E°(MnO₄⁻/Mn) from three other E° via ΔG°"),
    "2022P1_Q3": (["MISSING:neutralisation H₂CO₃ + NaOH", 185], "forward", "mixture -> HCO₃⁻/CO₃²⁻ buffer -> pH (pK_a2)"),
    "2022P2_Q1": (["MISSING:HSO₄⁻ equilibrium sets [SO₄²⁻]", 195], "simultaneous", "K_a2 of H₂SO₄ with K_sp(PbSO₄)"),
    "2022P2_Q2": ([255, 267], "inverse", "ΔP given -> i (255 inverted) -> n ions (267 inverted)"),
    "2022P2_Q3": ([250, 250, 250], "simultaneous", "three Kohlrausch equations -> m, n, p"),
    "2023P1_Q5": ([251, 173], "symbolic", "1/Λm vs cΛm linearised: P/S = K_aΛ°m"),
    "2023P1_Q6": (["MISSING:solubility of MX with protonation (K_sp, K_a)"], "two-state ratio", "S at pH 7 and pH 2 -> pK_a"),
    "2023P1_Q9": (["MISSING:Z = PV/nRT", 88], "two-state ratio", "real (Z = 0.5) vs ideal molar volume at the same T, P"),
    "2023P1_Q10": ([213, 210], "graph", "Arrhenius plot of k_f, A_f/A_b, K at 500 K -> k_b at 250 K"),
    "2023P1_Q11": ([119, "MISSING:q = nRT ln(V₃/V₂) (isothermal)"], "condition", "adiabatic then isothermal; total heat given"),
    "2023P1_Q12": ([135, 135], "two-state difference", "ΔG°(T₂) − ΔG°(T₁) with T₁ = 2T₂, K read from a plot"),
    "2023P2_Q11": ([61, 66], "inverse", "orbit radii give n (61 inverted) -> λ of the transition"),
    "2023P2_Q12": ([24, 265], "forward", "mixing two urea solutions -> π"),
    "2023P2_Q14": (["MISSING:S(T) = ∫ΔC_p/T dT"], "calculus", "S_β − S_α at 300 K from the value at 600 K"),
    "2023P2_Q15": ([127, 114], "calculus", "ΔH at 600 K = TΔS, then Kirchhoff to 300 K"),
    "2024P1_Q1": ([88, 88, 98], "two-state ratio", "n of X and Y from pressures (88 inverted) -> M -> u_rms ratio"),
    "2024P1_Q8": (["MISSING:ΔH = nC_pΔT along a V–T path"], "graph", "ΔH over X -> Y -> Z read from a V–T diagram"),
    "2024P1_Q9": (["MISSING:rate law from a mechanism (pre-equilibrium)"], "symbolic", "order from the mechanism"),
    "2024P2_Q8": ([35, 35, 3, "MISSING:area per molecule"], "two-state difference",
                  "acid taken − acid left (back titration) -> molecules adsorbed -> area each"),
    "2024P2_Q9": ([262, 262], "two-state ratio", "ΔT_b(X)/ΔT_b(Y) with M and i ratios"),
    "2024P2_Q11": ([227], "forward", "age from the Pb/U mass ratio"),
    "2025_Q8": ([234, "MISSING:I = Q/t"], "inverse", "current for 1 mol Cr³⁺ in 48.25 min (Faraday inverted)"),
    "2025_Q9": (["MISSING:[H⁺] of a very weak acid with water (exact)"], "simultaneous",
                "K_a = 4 × 10⁻¹¹: water's H⁺ cannot be ignored (175 gives the wrong 2.0 × 10⁻⁷)"),
    "2025_Q10": ([103], "symbolic", "vdW as a cubic in V_m: ratio of two coefficients"),
    "2025_Q11": ([11, "MISSING:w = −Δn_gRT"], "forward", "electrolysis of 8 mol H₂O -> 12 mol gas -> work"),
}


def main():
    from core.engine import physical as ph
    from core.engine.base import links, roles_consistent

    def as_chain(steps):
        """The engine steps in order; can the walk build them as one chain? Consecutive steps
        must share a graph node (dst -> src) and link (fields, roles, topics)."""
        txs = [s for s in steps if isinstance(s, int)]
        if any(isinstance(s, str) for s in steps):
            return "no (formula missing)"
        if len(txs) == 1:
            return "single step"
        if len(set(txs)) < len(txs):
            return "no (a step used twice)"
        st = [ph.STEPS[t] for t in txs]
        for a, b in zip(st, st[1:]):
            if a.dst != b.src:
                return f"no ({a.tx} -> {b.tx}: not adjacent in the graph)"
            if not links(a, b, ph.BRIDGES):
                return f"no ({a.tx} -> {b.tx}: does not link)"
        return "yes" if roles_consistent(st) else "no (roles)"

    rows, stats = [], {}
    for qid, (steps, mod, note) in MAP.items():
        chain = as_chain(steps)
        have = sum(1 for s in steps if isinstance(s, int))
        miss = [s.split(":", 1)[1] for s in steps if isinstance(s, str)]
        rows.append((qid, steps, chain, mod, note, miss))
        stats.setdefault("total", 0)
        stats["total"] += 1
        stats["all_in_engine"] = stats.get("all_in_engine", 0) + (not miss)
        stats["walk_chain"] = stats.get("walk_chain", 0) + (chain in ("yes", "single step"))
        stats["forward"] = stats.get("forward", 0) + (mod == "forward")
        stats["forward_and_buildable"] = stats.get("forward_and_buildable", 0) + \
            (mod == "forward" and chain in ("yes", "single step"))
        stats.setdefault("mods", {})
        stats["mods"][mod] = stats["mods"].get(mod, 0) + 1
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "advanced_formula_map.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("# JEE Advanced physical chemistry mapped onto the engine\n\n")
        f.write("Generated by `docs/advanced_formula_map.py` from a hand mapping (2026-10-14). "
                "Steps are engine tx ids in solution order; 'walk chain' says whether the graph walk "
                "could build exactly those steps as one chain.\n\n")
        f.write(f"- questions: {stats['total']}\n")
        f.write(f"- every formula exists in the engine: {stats['all_in_engine']}\n")
        f.write(f"- the walk could build the steps as a chain (or a single step): {stats['walk_chain']}\n")
        f.write(f"- used forward: {stats['forward']}; forward AND buildable by the walk: {stats['forward_and_buildable']}\n")
        f.write("- how the formulas are used: " + ", ".join(f"{k} {v}" for k, v in
                                                          sorted(stats['mods'].items(), key=lambda x: -x[1])) + "\n\n")
        f.write("| Question | Engine steps | Walk chain? | Use | Missing formulas | Note |\n|---|---|---|---|---|---|\n")
        for qid, steps, chain, mod, note, miss in rows:
            f.write(f"| {qid} | {', '.join(str(s) for s in steps if isinstance(s, int)) or '—'} | {chain} | {mod} | "
                    f"{'; '.join(miss) or '—'} | {note} |\n")
    print(stats)
    for qid, steps, chain, mod, note, miss in rows:
        print(f"{qid:12s} {str([s for s in steps if isinstance(s, int)]):22s} {chain:42s} {mod}")


if __name__ == "__main__":
    main()
