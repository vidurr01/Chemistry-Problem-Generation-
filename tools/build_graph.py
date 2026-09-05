"""
Build reaction_graph.json from concept_book.json.

Strategy:
  1. Define ~55 canonical node IDs (functional group classes).
  2. Normalize every from/to string in the 657 TXs to a canonical node ID.
  3. Group TXs by (from_node, to_node) pair — multiple TXs on same edge become
     conditions_variants or notes.
  4. Write reaction_graph.json with nodes + edges arrays.
  5. Report unmapped strings for manual review.
"""

import json
import os
import re
from collections import defaultdict

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_KG   = os.path.join(_ROOT, "knowledge")

# ── Canonical node definitions ─────────────────────────────────────────────────

NODES = [
    # ── Hydrocarbons ──────────────────────────────────────────────────────────
    {"id": "alkane",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "C-C single bonds only (saturated)",
     "ranking_dimensions": ["radical_stability", "bond_dissociation_energy"],
     "chapter": "Hydrocarbons"},

    {"id": "alkene",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "C=C double bond",
     "ranking_dimensions": ["alkene_stability", "nucleophilicity"],
     "chapter": "Hydrocarbons",
     "stereo_note": "E/Z isomerism; cis/trans from cyclic substrates"},

    {"id": "alkyne",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "C≡C triple bond",
     "ranking_dimensions": ["acidity"],  # terminal alkynes are more acidic
     "chapter": "Hydrocarbons"},

    {"id": "diene_conjugated",    "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "two conjugated C=C (1,3-diene)",
     "ranking_dimensions": ["diene_reactivity"],
     "chapter": "Hydrocarbons"},

    {"id": "diene_isolated",      "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "two non-conjugated C=C (1,4+ diene)",
     "chapter": "Hydrocarbons"},

    {"id": "cycloalkane",         "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "saturated carbocyclic ring",
     "ranking_dimensions": ["ring_strain"],
     "chapter": "Hydrocarbons"},

    {"id": "cycloalkene",         "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "unsaturated carbocyclic ring with C=C",
     "chapter": "Hydrocarbons"},

    # ── Aromatic ─────────────────────────────────────────────────────────────
    {"id": "benzene",             "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "unsubstituted benzene ring",
     "ranking_dimensions": ["eas_reactivity"],
     "chapter": "Aromatic Compounds"},

    {"id": "substituted_benzene", "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "benzene ring with one or more substituents",
     "ranking_dimensions": ["eas_reactivity", "eas_regioselectivity", "acidity", "basicity"],
     "chapter": "Aromatic Compounds",
     "note": "substituent type (EWG/EDG) encoded in edge conditions"},

    {"id": "naphthalene",         "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "fused two-ring aromatic system",
     "ranking_dimensions": ["eas_reactivity"],
     "chapter": "Aromatic Compounds"},

    {"id": "aryl_halide",         "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "Ar-X (halogen directly on benzene ring)",
     "chapter": "Aromatic Compounds",
     "note": "SNAr reactivity depends on EWG ortho/para to X"},

    # ── Halides ───────────────────────────────────────────────────────────────
    {"id": "alkyl_halide",        "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-X (C-X where C is sp3)",
     "ranking_dimensions": ["leaving_group_ability", "sn1_vs_sn2"],
     "chapter": "Alkyl Halides",
     "note": "1°/2°/3° distinction encoded in conditions_variants or edge notes"},

    {"id": "vinyl_halide",        "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "C=C-X (halogen on sp2 carbon)",
     "chapter": "Alkyl Halides"},

    {"id": "vicinal_dihalide",    "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "adjacent C-X, C-X (1,2-dihalide)",
     "chapter": "Alkyl Halides"},

    {"id": "geminal_dihalide",    "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "same carbon C-X₂ (1,1-dihalide)",
     "chapter": "Alkyl Halides"},

    # ── Oxygen compounds ──────────────────────────────────────────────────────
    {"id": "alcohol",             "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-OH (sp3 carbon bearing OH)",
     "ranking_dimensions": ["acidity", "nucleophilicity"],
     "chapter": "Alcohols, Phenols & Ethers",
     "note": "1°/2°/3° distinction encoded in edge conditions"},

    {"id": "phenol",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "Ar-OH (OH directly on aromatic ring)",
     "ranking_dimensions": ["acidity", "eas_reactivity"],
     "chapter": "Alcohols, Phenols & Ethers"},

    {"id": "ether",               "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-O-R' (two carbons flanking O)",
     "chapter": "Alcohols, Phenols & Ethers"},

    {"id": "epoxide",             "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "three-membered cyclic ether (oxirane)",
     "ranking_dimensions": ["ring_strain"],
     "chapter": "Alcohols, Phenols & Ethers"},

    {"id": "diol",                "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "two OH groups (vicinal or geminal)",
     "chapter": "Alcohols, Phenols & Ethers",
     "note": "syn/anti stereochemistry encoded in edge conditions_variants"},

    {"id": "halohydrin",          "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "adjacent C-X and C-OH on same molecule",
     "chapter": "Alkyl Halides"},

    # ── Carbonyl compounds ────────────────────────────────────────────────────
    {"id": "aldehyde",            "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-CHO (carbonyl at terminal carbon)",
     "ranking_dimensions": ["electrophilicity", "oxidation_state"],
     "chapter": "Aldehydes & Ketones"},

    {"id": "ketone",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-CO-R' (carbonyl flanked by two carbons)",
     "ranking_dimensions": ["electrophilicity", "oxidation_state"],
     "chapter": "Aldehydes & Ketones"},

    {"id": "enol",                "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "C=C-OH (tautomer of carbonyl)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "acetal",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-CH(OR')₂ or R₂C(OR')₂ (protected carbonyl)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "cyanohydrin",         "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-C(OH)(CN) (carbonyl + HCN addition product)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "carboxylic_acid",     "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-COOH",
     "ranking_dimensions": ["acidity"],
     "chapter": "Carboxylic Acids & Derivatives"},

    {"id": "ester",               "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-COO-R'",
     "chapter": "Carboxylic Acids & Derivatives"},

    {"id": "amide",               "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-CO-NR'₂ (carbonyl bonded to N)",
     "chapter": "Carboxylic Acids & Derivatives",
     "note": "1°/2°/3° amide distinction in edge conditions"},

    {"id": "acid_chloride",       "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-COCl (acyl chloride)",
     "ranking_dimensions": ["electrophilicity"],
     "chapter": "Carboxylic Acids & Derivatives"},

    {"id": "anhydride",           "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-CO-O-CO-R' (two acyl groups bridged by O)",
     "chapter": "Carboxylic Acids & Derivatives"},

    {"id": "lactone",             "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "cyclic ester (ring containing -CO-O-)",
     "chapter": "Carboxylic Acids & Derivatives"},

    {"id": "lactam",              "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "cyclic amide (ring containing -CO-N-)",
     "chapter": "Carboxylic Acids & Derivatives"},

    # ── Nitrogen compounds ────────────────────────────────────────────────────
    {"id": "amine",               "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-NH₂, R₂NH, or R₃N (N with one/two/three C bonds)",
     "ranking_dimensions": ["basicity", "nucleophilicity"],
     "chapter": "Amines",
     "note": "1°/2°/3° distinction in edge conditions"},

    {"id": "aniline",             "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "Ar-NH₂ (primary amine on aromatic ring)",
     "ranking_dimensions": ["basicity", "eas_reactivity"],
     "chapter": "Amines"},

    {"id": "diazonium_salt",      "type": "stable", "can_be_start": True,  "can_be_end": False,
     "functional_group": "Ar-N₂⁺ (diazonium cation from aromatic amine)",
     "chapter": "Amines",
     "note": "always reacts further; rarely the end-point of a question"},

    {"id": "nitrile",             "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-CN (triple bond to N)",
     "chapter": "Amines"},

    {"id": "nitro_compound",      "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-NO₂ or Ar-NO₂",
     "chapter": "Amines"},

    {"id": "imine",               "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R₂C=NR' (Schiff base, condensation product of carbonyl + amine)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "oxime",               "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R₂C=NOH (condensation of carbonyl + hydroxylamine)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "hydrazone",           "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R₂C=N-NHR' (condensation of carbonyl + hydrazine/semicarbazide)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "isocyanate",          "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-N=C=O",
     "chapter": "Amines"},

    {"id": "isocyanide",          "type": "stable", "can_be_start": False, "can_be_end": True,
     "functional_group": "R-NC (isocyanide/carbylamine)",
     "chapter": "Amines",
     "note": "Formed from primary amines via carbylamine test (CHCl₃/alc.KOH); distinguishes 1° from 2°/3° amines"},

    {"id": "azo_compound",        "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "Ar-N=N-Ar' (coupling product of diazonium + activated ring)",
     "chapter": "Amines"},

    # ── Sulfur / Special ─────────────────────────────────────────────────────
    {"id": "sulfonate",           "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-OTs / R-OMs / R-OTf (alkyl sulfonate ester)",
     "ranking_dimensions": ["leaving_group_ability"],
     "chapter": "Alkyl Halides",
     "note": "excellent leaving group; used when halide is poor LG"},

    # ── Organometallics ───────────────────────────────────────────────────────
    {"id": "grignard",            "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-MgX (carbon nucleophile)",
     "chapter": "Organometallics & Grignard"},

    {"id": "organolithium",       "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "R-Li (even stronger carbon nucleophile than Grignard)",
     "chapter": "Organometallics & Grignard"},

    # ── Biomolecules / Polymers ───────────────────────────────────────────────
    {"id": "amino_acid",          "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "H₂N-CHR-COOH (bifunctional: amine + carboxylic acid)",
     "chapter": "Biomolecules"},

    {"id": "carbohydrate",        "type": "stable", "can_be_start": True,  "can_be_end": True,
     "functional_group": "polyhydroxy aldehyde/ketone (aldose or ketose)",
     "chapter": "Biomolecules"},

    {"id": "polymer",             "type": "stable", "can_be_start": False, "can_be_end": True,
     "functional_group": "repeating monomer units (addition or condensation polymer)",
     "chapter": "Polymers"},

    # ── GOC / Comparison states ───────────────────────────────────────────────
    {"id": "carbocation",         "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "R₃C⁺ (trivalent sp2 carbon with positive charge)",
     "ranking_dimensions": ["carbocation_stability"],
     "chapter": "GOC"},

    {"id": "carbanion",           "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "R₃C⁻ (trivalent sp3 carbon with negative charge)",
     "ranking_dimensions": ["carbanion_stability"],
     "chapter": "GOC"},

    {"id": "radical",             "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "R₃C• (trivalent carbon with one unpaired electron)",
     "ranking_dimensions": ["radical_stability"],
     "chapter": "GOC"},

    {"id": "enolate",             "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "R₂C=C-O⁻ (deprotonated enol, resonance-stabilized anion)",
     "chapter": "Aldehydes & Ketones"},

    {"id": "acetylide_ion",       "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "R-C≡C⁻ (deprotonated terminal alkyne)",
     "chapter": "Hydrocarbons"},

    {"id": "bromonium_ion",       "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "cyclic Br⁺ bridging two carbons (electrophilic addition intermediate)",
     "chapter": "Hydrocarbons"},

    {"id": "carbene",             "type": "intermediate", "can_be_start": False, "can_be_end": False,
     "functional_group": "R₂C: (divalent carbon, two non-bonding electrons)",
     "chapter": "Reaction Mechanisms"},
]

NODE_IDS = {n["id"] for n in NODES}

# ── Normalization map: raw string patterns → canonical node ID ─────────────────

def normalize_node(raw):
    """Map a raw from/to string to a canonical node ID. Returns None if unmappable."""
    s = raw.strip()
    sl = s.lower()

    # Skip strings that are GOC ordering results or analytical outputs (not graph nodes)
    skip_patterns = [
        r"^\+[im] effect",
        r"^-[im] effect",
        r"canonical struct",
        r"^%[chnos]",
        r"tert-butyl > isopropyl",
        r"resonance struct",
        r"electron density",
        r"^\d+ canonical",
        r"^red solution",
        r"^blue liquid",
        r"racemisation|racemization|retention|inversion of config",
        r"dihedral|anti-periplanar requirement",
        r"^2\^[n(p]",
        r"total stereoisomers",
        r"keto.*enol.*tautomer",
        r"→ ethylene.*dehalogen",
        r"via sn1 with.*shift",
        r"via 1,2.*shift",
        r"hofmann.*less substituted.*major",
        r"zaitsev.*more substituted",
        r"alkene product determined by",
        r"dumas method",
        r"alkene \(hofmann",
        r"rearranged product",
    ]
    for pat in skip_patterns:
        if re.search(pat, sl):
            return None

    # Exact matches first
    exact = {
        "alkane": "alkane",
        "alkene": "alkene",
        "alkyne": "alkyne",
        # Simple IUPAC name aliases (common unmapped from_raw strings)
        "ethyne": "alkyne",
        "acetylene": "alkyne",
        "ethene": "alkene",
        "propene": "alkene",
        "but-1-ene": "alkene",
        "but-2-ene": "alkene",
        "benzene": "benzene",
        "phenol": "phenol",
        "epoxide": "epoxide",
        "aldehyde": "aldehyde",
        "ketone": "ketone",
        "nitrile": "nitrile",
        "enol": "enol",
        "alcohol": "alcohol",
        "alcohol (r-oh)": "alcohol",
        "r-oh (alcohol)": "alcohol",
        "alcohol (roh)": "alcohol",
        "r-oh": "alcohol",
        "1° or 2° alcohol": "alcohol",
        "aniline (phnh2)": "aniline",
        "aniline": "aniline",
        "phenylamine": "amine",           # common synonym for aniline/primary aromatic amine
        "alcohol (r-oh) + various dehydrating agents": "alcohol",
        "amine": "amine",
        "primary amine": "amine",
        "secondary amine": "amine",
        "tertiary amine": "amine",
        "alkyl halide": "alkyl_halide",
        "alkyl halide (rx)": "alkyl_halide",
        "r-x (alkyl halide)": "alkyl_halide",
        "alkyl halide (m)": "alkyl_halide",      # Markovnikov product — same class
        "alkyl halide (am)": "alkyl_halide",     # Anti-Markovnikov — same class
        "alcohol (m)": "alcohol",
        "alcohol (am)": "alcohol",
        "diol (syn)": "diol",
        "diol (anti)": "diol",
        "vicinal dihalide": "vicinal_dihalide",
        "geminal dihalide": "geminal_dihalide",
        "bromohydrin": "halohydrin",
        "cyanohydrin": "cyanohydrin",
        "cis-alkene": "alkene",
        "trans-alkene": "alkene",
        "alkene (ch₂=ch₂)": "alkene",
        "acetylide ion": "acetylide_ion",
        "grignard reagent": "grignard",
        "carboxylic acid": "carboxylic_acid",
        "ester": "ester",
        "amide": "amide",
        "acid chloride": "acid_chloride",
        "acid chloride (rcocl)": "acid_chloride",
        "anhydride": "anhydride",
        "aldehyde/ketone": "aldehyde",   # ozonolysis — map to aldehyde (most common product)
        "aldehyde or ketone": "aldehyde",
        "imine": "imine",
        "oxime": "oxime",
        "hydrazone": "hydrazone",
        "lactam (cyclic amide)": "lactam",
        "lactam": "lactam",
        "lactone": "lactone",
        "nitro compound": "nitro_compound",
        "arno2": "nitro_compound",
        "diazonium salt": "diazonium_salt",
        "primary alcohol": "alcohol",
        "secondary alcohol": "alcohol",
        "tertiary alcohol": "alcohol",
        "symmetrical ether (ror)": "ether",
        "ether (williamson)": "ether",
        "alkyl iodide (r-i)": "alkyl_halide",
        "iodide (finkelstein)": "alkyl_halide",
        "isocyanate": "isocyanate",
        "isocyanide": "isocyanide",
        "carbylamine": "isocyanide",
        "polymer": "polymer",
        # Specific compound aliases for frequently unmapped TXs
        "methyl chloride ch3cl": "alkyl_halide",
        "chloroethane": "alkyl_halide",
        "bromoethane": "alkyl_halide",
        "iodomethane": "alkyl_halide",
        "ethylmagnesium chloride": "grignard",
        "phenylmagnesium bromide": "grignard",
        "naphthalen-2-ol": "phenol",
        "2-naphthol": "phenol",
        "beta-naphthol": "phenol",
        "sulfonic acid r-so₃h + nahco₃": "sulfonate",
        "r-oms / r-ots / r-otf (sulfonate ester)": "sulfonate",
        "benzenesulfonic acid": "sulfonate",
        "phenol phoh + naoh": "phenol",
        "alcohol r-oh": "alcohol",
        "alkyl halide r-x": "alkyl_halide",
        "chiral alcohol r-oh": "alcohol",
        "alkene (m)": "alkene",
        "alkene (am)": "alkene",
    }
    if sl in exact:
        return exact[sl]

    # Extract leading class from complex descriptive strings
    # e.g. "Cyclobutyl bromide (or other cyclobutyl halide) treated with..."
    # e.g. "Secondary or tertiary alcohol R-OH treated with..."
    # e.g. "Alkyl halide R-X (primary or secondary) + AgCN..."
    leading_class_patterns = [
        (r"^(primary|secondary|tertiary|acyclic|cyclic|branched|allylic|quaternary)\s+(alkyl\s+halide|halide|bromide|chloride|iodide|substrate|ammonium)", "alkyl_halide"),
        (r"^cyclobutyl\s+(bromide|halide|carbinyl|substrate)",     "alkyl_halide"),
        (r"^cyclohexyl\s+(halide|substrate|quaternary|ammonium|bromide|chloride)", "alkyl_halide"),
        (r"^cyclopentyl\s+(substrate|bearing|halide)",              "alkyl_halide"),
        (r"^norbornyl|exo-norbornyl",                               "alkyl_halide"),
        (r"^alkyl\s+substrate|^r-l\s*\(alkyl|^r-l\s*\(secondary|^r-l\s*\(primary", "alkyl_halide"),
        (r"^(secondary or tertiary|primary or secondary|tertiary)\s+alkyl\s+halide", "alkyl_halide"),
        (r"^acyclic.*alkyl\s+bromide|^acyclic.*alkyl\s+halide|^acyclic.*secondary\s+alkyl", "alkyl_halide"),
        (r"^(secondary|tertiary)\s+or\s+(primary|secondary|tertiary)\s+alcohol", "alcohol"),
        (r"^alcohol\s+(r-oh|secondary|tertiary|primary|r-oh \(chiral)",        "alcohol"),
        (r"^allylic\s+alcohol",                                     "alcohol"),
        (r"^chiral\s+alcohol",                                      "alcohol"),
        (r"^(secondary|tertiary)\s+amine",                          "amine"),
        (r"^primary\s+allylic\s+halide|^(cyclic|branched)\s+allylic\s+halide|^allylic\s+(bromide|halide)", "alkyl_halide"),
        (r"^quaternary\s+ammonium",                                 "amine"),
        (r"^amine\s+n-oxide|^n-alkylanilinium",                     "amine"),
        (r"^tertiary\s+amine\s+\(r3n\)|^(secondary|tertiary)\s+amine",        "amine"),
        (r"^substrate.*poor\s+leaving|^substrate.*acyl\s+leaving|^substrate.*beta-or|^substrate.*c-c\s+sigma", "alkyl_halide"),
        (r"^(vicinal\s+1,2-dihalide|1,2-dihalide|gem-dihalide\s+cyclic|acyl\s+halide\s+series)", "alkyl_halide"),
        (r"^aryl\s+(chloride|halide|bromide|fluoride|iodide)|^halobenzene|^fluorobenzene\s+or\s+any", "aryl_halide"),
        (r"^benzene\s+ring\s+with|^substituted\s+benzene|^asymmetric\s+aryl", "substituted_benzene"),
        (r"^ester\s+r-c|^norbornyl.*ester|^(tertiary|secondary)\s+amide\s+r-c", "ester"),
        (r"^dialkyl\s+ether|^simple\s+dialkyl\s+ether|^cyclic\s+aliphatic\s+ether|^isopropyl\s+methyl\s+ether|^aryl\s+alkyl\s+ether|^phenyl\s+cyclopentyl\s+ether", "ether"),
        (r"^(vicinal\s+diol|spiro\s+compound.*oh|1-phenylethane-1,2-diol)", "diol"),
        (r"^epoxide\s+\(|^symmetrical\s+epoxide|^unsymmetrical\s+epoxide", "epoxide"),
        (r"^fischer_projection",                                    "alkyl_halide"),   # stereochem TX — map to generic alkyl substrate
        (r"^(e2|e1|sn1|sn2)\s+(elimination|on|product|substrate)|^deuterium-labeled\s+substrate|^acyclic.*e2|^rigid.*e2|^same\s+secondary\s+amine.*e2|^acyclic\s+diastere", "alkyl_halide"),
        (r"^carbocation\s+intermediate|^triarylmethyl",            "carbocation"),
        (r"^d-glucose|^d-fructose|^d_glyceraldehyde|^d-galactose", "carbohydrate"),
        (r"^amino\s+alcohol\s+h2n",                                 "alcohol"),
        (r"^ho-\(ch2\)",                                            "alcohol"),
        (r"^1,3-dibromopropane|^1_1_\d|1,3-dihalide|^1,7-dihalo|^1,2,3,4-tetrahalide|^vicinal\s+1,2-dihalide|^vicinal\s+diol", "alkyl_halide"),
        (r"^(2,3-butanediol|1-phenylethane)",                       "diol"),
        (r"^4,4-disubstituted\s+cyclohex",                          "ketone"),
        (r"^(aryl\s+alkyl|phenyl\s+allyl|phenyl\s+cyclopentyl)\s+ether", "ether"),
        (r"^acid\s+derivative|^acyl\s+halide\s+series",             "acid_chloride"),
    ]
    for pattern, node_id in leading_class_patterns:
        if re.search(pattern, sl, re.IGNORECASE):
            return node_id

    # Pattern-based normalization
    patterns = [
        # Alkyl halide variants
        (r"^r-[xl]|^alkyl halide|^alkyl bromide|^alkyl chloride|^alkyl iodide|"
         r"^r-br|^r-cl|^r-i\b|^r-x\b|^haloalkane",                           "alkyl_halide"),
        (r"aryl (halide|chloride|bromide|iodide|fluoride)|^ar-[xf]|"
         r"chlorobenzene|bromobenzene|fluorobenzene|iodobenzene",              "aryl_halide"),
        (r"vinyl halide|alkenyl halide|^[cz]-.*alkene.*halide",                "vinyl_halide"),
        (r"vicinal.*dihalide|1,2-dih|dibromo.*adjacent|gem.*dihalide|"
         r"geminal.*dihalide",                                                  "geminal_dihalide"),
        # Alcohol variants
        (r"^alcohol|^r-oh\b|^primary alcohol|^secondary alcohol|^tertiary alcohol|"
         r"chiral alcohol|^r-oh \(chiral|^r-oh \(primary\)|"
         r"1° or 2° alcohol",                                                  "alcohol"),
        # Alkene
        (r"^(cis|trans|e-|z-|e,z-).*alkene|(e)-.*alkene|"
         r"\balk-\d+-ene\b|\bbut-\d+-ene\b|pent-.*ene\b|hex-.*ene\b|"
         r"methylidene|alkene \(c",                                             "alkene"),
        # Alkyne
        (r"alkyne|but-\d+-yne|pent-\d+-yne|hex-\d+-yne|but-2-yne",           "alkyne"),
        # Dienes
        (r"(buta|penta|hexa)-.*-diene|conjugated diene|1,3-dien",             "diene_conjugated"),
        # Carbonyl compounds
        (r"^aldehyde|^alkanal|ethanal\b|propanal\b|butanal\b|pentanal\b|"
         r"^r-cho|benzaldehyde|aromatic aldehyde",                             "aldehyde"),
        (r"^ketone|^alkanone|propan-2-one|butan-2-one|pentan-2-one|"
         r"cyclohexanone|acetone\b|r-co-r",                                    "ketone"),
        (r"carboxylic acid|alkanoic acid|ethanoic acid|propanoic acid|"
         r"butanoic acid|benzoic acid|r-cooh|rcooh",                           "carboxylic_acid"),
        (r"^ester|ethyl ethanoate|methyl.*anoate|r-coo|rcooh.*r'oh",          "ester"),
        (r"^amide|primary amide|secondary amide|tertiary amide|"
         r"rconh2|rconhr|rconr2",                                              "amide"),
        (r"acid chloride|acyl chloride|acyl halide|rcocl|acetyl chloride",    "acid_chloride"),
        (r"anhydride|acetic anhydride|\(rco\)2o",                             "anhydride"),
        # Aromatic
        (r"naphthalene|naphthyl|1-nitronaphthalene",                          "naphthalene"),
        (r"substituted benzene|toluene|xylene|cumene|methylbenzene|"
         r"dimethylbenzene|nitrobenzene|benzoic acid ring|"
         r"chlorobenzene|bromobenzene|phenyl.*substitut|"
         r"\+m.*benzene|-m.*benzene|edg.*benzene|ewg.*benzene|"
         r"para.*benzene|ortho.*benzene|hydroxybenzene|methoxybenzene",       "substituted_benzene"),
        (r"phenol|hydroxybenzene|ar-oh",                                       "phenol"),
        (r"aniline|aminobenzene|ar-nh2|aromatic.*amine|"
         r"primary aromatic amine",                                             "aniline"),
        (r"diazonium|arn2\+|ar-n2",                                            "diazonium_salt"),
        (r"azo compound|ar-n=n-ar|coupling product",                           "azo_compound"),
        # Nitrogen
        (r"^amine|^primary amine|^secondary amine|^tertiary amine|"
         r"^r-nh2|^r2nh|^r3n\b|^aliphatic amine|"
         r"alkyl amine|r-nh₂",                                                 "amine"),
        (r"nitrile|r-cn|alkyl cyanide|cyano",                                 "nitrile"),
        (r"nitro.*compound|^arno2|^r-no2|nitro.*benzene|nitroalkane",         "nitro_compound"),
        (r"isocyanate|r-nco|rnco",                                             "isocyanate"),
        (r"imine|schiff base|r2c=nr|azomethine",                              "imine"),
        (r"oxime|r2c=noh|carbonyl.*hydroxylamine",                             "oxime"),
        (r"hydrazone|semicarbazone|r2c=n-nh|r2c=nnhr",                        "hydrazone"),
        (r"lactam|cyclic amide",                                               "lactam"),
        (r"lactone|cyclic ester",                                              "lactone"),
        # Organometallics
        (r"grignard|r-mgx|rMgX|organomagnesium",                              "grignard"),
        (r"organolithium|r-li\b|rli\b",                                        "organolithium"),
        # Halogens
        (r"^halohydrin|bromohydrin|chlorohydrin",                             "halohydrin"),
        (r"^vicinal diol|^1,2-diol|^diol\b|ethylene glycol|"
         r"glycerol|propane-1,2,3-triol",                                      "diol"),
        (r"epoxide|oxirane|ethylene oxide|oxacyclopropane",                   "epoxide"),
        (r"^ether\b|^r-o-r|^dialkyl ether|^aryl.*ether|^ether \(",           "ether"),
        (r"^acetal\b|hemiacetal|^r-ch\(or\)",                                 "acetal"),
        (r"^cyanohydrin\b|cyanohydrin",                                        "cyanohydrin"),
        # Cyclic
        (r"^cycloalkane|^cyclohexane|^cyclopentane|^cyclopropane|"
         r"^cyclobutane|^cycloheptane|ring.*saturated",                        "cycloalkane"),
        (r"^cycloalkene|^cyclohexene|^cyclopentene|^cyclopropene|"
         r"ring.*unsaturated.*C=C",                                            "cycloalkene"),
        # Intermediates
        (r"carbocation|carbo.*cation|r3c\+|carbonium|benzylic cation|"
         r"allylic cation",                                                    "carbocation"),
        (r"carbanion|r3c-\b|^r3c⁻",                                           "carbanion"),
        (r"radical\b|r3c•|free radical|allylic radical|benzylic radical",     "radical"),
        (r"enolate|r2c=c-o-\b|alpha.*deprotonated.*carbonyl",                "enolate"),
        (r"acetylide|rc≡c-\b|terminal alkyne.*anion|alkynide",               "acetylide_ion"),
        (r"bromonium|mercurinium|bridged.*halonium",                           "bromonium_ion"),
        (r"carbene|r2c:\b|methylene",                                          "carbene"),
        # Biomolecules
        (r"amino acid|glycine|alanine|phenylalanine|tyrosine|tryptophan|"
         r"serine|cysteine|h2n-chr-cooh",                                      "amino_acid"),
        (r"glucose|fructose|galactose|sucrose|lactose|starch|cellulose|"
         r"carbohydrate|aldose|ketose|monosaccharide|disaccharide|"
         r"d-glucose|d-fructose",                                              "carbohydrate"),
        (r"polymer|polymerisation|polymerization|nylon|dacron|bakelite|"
         r"teflon|pvc|rubber",                                                 "polymer"),
        # Sulfonate
        (r"sulfonate|tosylate|mesylate|triflate|r-ots|r-oms|r-otf",          "sulfonate"),
        # Alkane variants
        (r"^alkane\b|^methane|^ethane|^propane|^butane|^pentane|^hexane|"
         r"^heptane|^octane|^alkyl group added|^r-h\b",                       "alkane"),
    ]

    for pattern, node_id in patterns:
        if re.search(pattern, sl, re.IGNORECASE):
            return node_id

    # Specific IUPAC compound → class
    iupac_map = {
        "propan-2-one": "ketone",
        "ethanal": "aldehyde",
        "propanal": "aldehyde",
        "pentanal": "aldehyde",
        "butanal": "aldehyde",
        "ethanenitrile": "nitrile",
        "propanenitrile": "nitrile",
        "ethanoic acid": "carboxylic_acid",
        "propanoic acid": "carboxylic_acid",
        "butanoic acid": "carboxylic_acid",
        "benzoic acid": "carboxylic_acid",
        "benzaldehyde": "aldehyde",
        "4-nitrobenzaldehyde": "aldehyde",
        "2,2,2-trichloroacetaldehyde": "aldehyde",
        "ethyl ethanoate": "ester",
        "phenyl ethanoate": "ester",
        "acetyl chloride": "acid_chloride",
        "propan-1-ol": "alcohol",
        "propan-2-ol": "alcohol",
        "butan-1-ol": "alcohol",
        "ethanol": "alcohol",
        "methanol": "alcohol",
        "glycerol": "diol",
        "ethylene glycol": "diol",
        "2,3-butanediol": "diol",
        "1-hydroxypropan-2-one": "ketone",
        "cumene": "substituted_benzene",
        "toluene": "substituted_benzene",
        "methylbenzene": "substituted_benzene",
        "1,2-dimethylbenzene": "substituted_benzene",
        "1,3-dimethylbenzene": "substituted_benzene",
        "1,4-dimethylbenzene": "substituted_benzene",
        "diphenylmethane": "substituted_benzene",
        "chlorobenzene": "aryl_halide",
        "bromobenzene": "aryl_halide",
        "fluorobenzene": "aryl_halide",
        "1,2-dichloroethane": "vicinal_dihalide",
        "1-methylaziridine": "epoxide",  # N-aziridine ≈ epoxide class for graph purposes
        "buta-1,3-diene": "diene_conjugated",
        "2-methylbuta-1,3-diene": "diene_conjugated",
        "cyclohexanone": "ketone",
        "butane-2,3-dione": "ketone",
        "2-hydroxybenzoic acid": "carboxylic_acid",
        "2-methoxyphenol": "phenol",
        "2-aminophenol": "aniline",
        "4-aminobenzoic acid": "carboxylic_acid",
        "(z)-but-2-enedioic acid": "carboxylic_acid",
        "acrolein (ch₂=ch-cho)": "aldehyde",
        "naphthalene": "naphthalene",
        "1-nitronaphthalene": "substituted_benzene",
        "but-2-yne": "alkyne",
        "(e)-but-2-ene": "alkene",
        "(z)-but-2-ene": "alkene",
        "(z)-hex-3-ene": "alkene",
        "2-methylpropane": "alkane",
        "propane": "alkane",
        "ethane": "alkane",
        "2-methylprop-1-ene": "alkene",
        "(r)-2-bromobutane": "alkyl_halide",
        "(s)-2-bromobutane": "alkyl_halide",
        "2-bromopropane": "alkyl_halide",
        "2-bromoanisole": "aryl_halide",
        "(e)-but-2-enal": "aldehyde",
        "ccl4": "alkyl_halide",
        "(e)-pent-3-en-2-one": "ketone",
        "1,3-diketone_keto_form_pentane-2,4-dione": "ketone",
        "4-(dimethylamino)benzaldehyde": "aldehyde",
        "1-methylidenebutane": "alkene",
        "cot cyclooctatetraene (8pi, non-aromatic)": "diene_conjugated",
        "2-methylpropane": "alkane",
        "2-chlorocyclohexan-1-one": "ketone",
        "cyclohexanone": "ketone",
        "cyclopentane": "cycloalkane",
        "cyclohexane": "cycloalkane",
        "cyclopropane": "cycloalkane",
        "cyclobutane": "cycloalkane",
        "cyclopentene": "cycloalkene",
        "n-alkylanilinium salt": "aniline",
    }
    sl_stripped = sl.rstrip(".")
    if sl_stripped in iupac_map:
        return iupac_map[sl_stripped]

    # Extended IUPAC/specific compound from-strings
    ext_from_map = {
        "methyl ketone (r-co-ch3)":          "ketone",
        "phosgene (cocl2)":                  "acid_chloride",
        "n-nitroso secondary amine + hcl":   "amine",
        "phenyl ester (ph-o-co-r)":          "ester",
        "cyclopropylcarbinyl cation (c+ adjacent to cyclopropane ring)": "carbocation",
        "cyclobutylcarbinyl cation (cyclobutane ring with exocyclic c+)": "carbocation",
        "cyclopentylcarbinyl cation (cyclopentane ring with exocyclic c+)": "carbocation",
        "cyclopropylcarbinyl cation (cyclopropane with exo c+)": "carbocation",
        "cyclopropylcarbinyl halide (cyclopropyl-ch₂-x)": "alkyl_halide",
        "acetylene (hc≡ch) + ch₂n₂":        "alkyne",
        "cyclopentadiene (sp3 ch2)":         "diene_conjugated",
        "cyclobutadiene (4pi, antiaromatic)": "diene_conjugated",
        "pyruvic acid (ch3cocooh)":          "carboxylic_acid",
        "squaric acid (3,4-dihydroxycyclobutenedione)": "carboxylic_acid",
        "4-phenyl-1-butanol (ph-ch₂ch₂ch₂oh, homobenzylic primary alcohol)": "alcohol",
        "benzyl methyl ketone (phch2-co-ch3)": "ketone",
        "ethyl acetate (ch3cooet)":          "ester",
        "nh3 + excess alkyl halide":         "amine",  # ammonolysis — from = amine (product)
        "tert-butyl ester of pivalic acid (me₃c-cooh + meoh/h₂so₄)": "ester",
        "r-nh₂ (primary aliphatic amine)":  "amine",
        "r-nh₂ (primary amine)":            "amine",
        "r-n₂⁺ (aliphatic diazonium ion)":  "diazonium_salt",
        "r-o-r' (ether)":                   "ether",
        "r-oMs / r-ots / r-otf (sulfonate ester)": "sulfonate",
        "r-r' (alkyl group added)":         "alkane",
        "nitrene r-n: (singlet or triplet, 6e- on n, neutral electrophile)": None,  # skip exotic
    }
    if sl in ext_from_map:
        return ext_from_map[sl]

    # Named product classes that are well-defined but not in exact/pattern matches above
    named_product_map = {
        "aldol product":             "alcohol",      # beta-hydroxy carbonyl → maps to alcohol (OH is new FG)
        "enol ether":                "ether",
        "α-halo acid":               "carboxylic_acid",
        "alpha-halo acid":           "carboxylic_acid",
        "arene":                     "substituted_benzene",
        "sulphonic acid":            "carboxylic_acid",   # sulfonic acid behaves like carboxylic for graph
        "sulfonic acid":             "carboxylic_acid",
        "alkylbenzene":              "substituted_benzene",
        "acylbenzene":               "ketone",            # friedel-crafts acylation product
        "β-halo alcohol":            "halohydrin",
        "beta-halo alcohol":         "halohydrin",
        "β-amino alcohol":           "alcohol",
        "beta-amino alcohol":        "alcohol",
        "cyclic amine":              "amine",
        "azoxybenzene (arn(o)=nar)": "azo_compound",
        "azoxybenzene":              "azo_compound",
        "sodium phenoxide":          "phenol",
        "para-benzoquinone":         "ketone",
        "benzoquinone (p-benzoquinone)": "ketone",
        "benzoquinone":              "ketone",
        "phenyl ester (ph-oac or ph-ocor)": "ester",
        "alpha-halo ether":          "ether",
        "methyl ether (roch₃)":      "ether",
        "alkyl nitrite (r-ono)":     "ester",
        "alkene (saytzeff, e1) — high-temp dehydration": "alkene",
        "symmetrical ether (r-o-r) — mid-temp dehydration": "ether",
        "alkyl hydrogen sulfate (r-o-so₂oh) — low-temp": "sulfonate",
        "acetate ester (r-oac, +42 da per oh) — acetylation": "ester",
        "no reaction":               None,    # skip "no reaction" to nodes
        "oxalamide precipitate":     "amide",
        "n,n-disubstituted oxamide (liquid)": "amide",
        "mixture of amines (preferentially tertiary)": "amine",
        "beta-aminocarbonyl (mannich base)": "amine",
        "cyclic amine":              "amine",
        "two alkyl halides (rx + r'x + pocl₃)": "alkyl_halide",
        "two esters (r''coor' + r-o-co-r'')": "ester",
        "alkene (hofmann = less substituted, major) + hydroxylamine derivative": "alkene",
        "sulphonyl chloride (rso2cl)": "acid_chloride",
        "alkyl sulphonate (r-so2-or')": "sulfonate",
        "thioether (r-s-r')":        "ether",
        "phosphate ester (r-o-po(oh)2)": "ester",
        "xanthate ester":            "ester",
        "dithiocarbamate":           "amide",
        "bischler–napieralski intermediate": "imine",
        "mannich base":              "amine",
        "enamine":                   "amine",
        "quaternary ammonium salt":  "amine",
        "hofmann product":           "amine",
        "carbamate (urethane)":      "amide",
        "urea":                      "amide",
        "guanidine":                 "amide",
        "semicarbazone":             "hydrazone",
        "phenylhydrazone":           "hydrazone",
        "2,4-dnp derivative":        "hydrazone",
        "silver mirror":             None,   # tollens test result — skip
        "brick-red precipitate":     None,   # fehling test — skip
        "alpha-hydroxy ketone":      "ketone",
        "beta-hydroxy ketone":       "ketone",
        "beta-hydroxy aldehyde":     "aldehyde",
        "alpha-beta-unsaturated carbonyl": "ketone",
        "michael adduct":            "ketone",
        "dicarboxylic acid":         "carboxylic_acid",
        "malonic ester":             "ester",
        "acetoacetic ester":         "ester",
        "acyloin":                   "ketone",
        "benzoin":                   "ketone",
        "1,3-diol":                  "diol",
        "triol":                     "diol",
        "diol (anti)":               "diol",
        "diol (syn)":                "diol",
        "bromohydrin":               "halohydrin",
        "chlorohydrin":              "halohydrin",
        "beta-lactam":               "lactam",
        "delta-lactone":             "lactone",
        "gamma-lactone":             "lactone",
        "1-naphthalen-2-ol":         "phenol",
        "beta-naphthol":             "phenol",
        "naphthalene sulfonic acid": "carboxylic_acid",
        "alkene (hofmann)":          "alkene",
        "alkene (zaitsev)":          "alkene",
        "selective reduction of less electron-deficient no2 to nh2": "aniline",
        # Alcohol dehydration variants
        "alkene (saytzeff, e2) — al₂o₃ dehydration":           "alkene",
        "alkene (saytzeff, e2) — pocl₃ dehydration":           "alkene",
        "alkene (hofmann/anti-saytzeff, e1cb) — tho₂ dehydration": "alkene",
        "alkene (saytzeff, e1) — khso₄ dehydration":           "alkene",
        "alkene (saytzeff, e2) — zncl₂ dehydration":           "alkene",
        # Halide products
        "anti-markovnikov alkyl bromide":                       "alkyl_halide",
        "r-cl (retention)":                                     "alkyl_halide",
        "r-cl (retention, sni)":                                "alkyl_halide",
        "alkyl fluoride (r-f)":                                 "alkyl_halide",
        "phosgene (cocl2)":                                     "acid_chloride",
        "chloropicrin (ccl3-no2)":                              "alkyl_halide",
        "chloretone (ccl3-c(ch3)2-oh)":                        "alcohol",
        # Carbonyl products
        "glyoxal (ohc-cho) — oxidative dehydrogenation":       "aldehyde",
        "glyoxal (ohc-cho)":                                    "aldehyde",
        "2 hcooh (formic acid) — oxidative cleavage":           "carboxylic_acid",
        "oxalic acid (hooc-cooh) — oxidation":                  "carboxylic_acid",
        "acetaldehyde (ch₃cho) — dehydration via enol":         "aldehyde",
        "acrolein (ch₂=ch-cho) — dehydration":                  "aldehyde",
        "carboxylate + haloform (chx3)":                        "carboxylic_acid",
        "alpha-mono-haloketone (r-co-ch2x)":                   "ketone",
        "iodoform (chi3) + sodium adipate":                     "alkyl_halide",
        "acetate + iodoform (chi3) [indirect]":                 "alkyl_halide",
        "2 x chi3 + benzoate + acetate":                        "alkyl_halide",
        "oxalate + 2 chi3":                                     "alkyl_halide",
        "benzoate + iodoform (chi3)":                           "carboxylic_acid",
        # Esters
        "glyceryl trinitrate (tng / nitroglycerin / dynamite)": "ester",
        "diethyl carbonate (etocooet)":                         "ester",
        "orthoethylformate (hc(oet)3)":                         "ester",
        "sodium formate (hcooNa)":                              "carboxylic_acid",
        "allyl iodide (ch₂=ch-ch₂i) via deoxygenation":        "alkyl_halide",
        # Amine products
        "mixture of 1°, 2°, 3° amines and quaternary ammonium salt": "amine",
        "para-nitroso primary amine (no migrates n to ring para)": "aniline",
        # Rearrangement products
        "o-hydroxy aryl ketone or p-hydroxy aryl ketone (fries rearrangement)": "ketone",
        "t-buome (tert-butyl methyl ether) + co — aac1 trap":  "ether",
        # Carbocation rearrangements
        "secondary carbocation (2 degree) via 1,2-hydride shift": "carbocation",
        "tertiary carbocation (3 degree) via 1,2-hydride or 1,2-methyl shift": "carbocation",
        "endocyclic carbocation (c+ moves into ring) via 1,2-h shift in ring system": "carbocation",
        "homoallylic/bisected sigma-delocalized cation": "carbocation",
        # Skip values
        "no reaction":                                          None,
        "red color product (aci-form + naoh soluble)":         None,
        "blue/insoluble product with naoh":                    None,
        "red complex [ce(no₃)₄(roh)₃] — can test positive":   None,
        "silver mirror":                                        None,
        "pyrazole (aromatic, major) via cycloaddition":        None,  # exotic
        "squarate dianion (2pi-electron aromatic cyclobutenedione dianion)": None,
        "cyclopentadienyl anion cp- (6pi, aromatic)":          None,
        "cyclobutadienyl dianion cbd2- (6pi, aromatic)":       None,
    }
    if sl in named_product_map:
        return named_product_map[sl]

    # Patterns for specific "to" values that appear frequently
    to_patterns = [
        # Specific alkyl/aryl halides (to values)
        (r"^\(e\)-\d+-bromo|^\(e\)-\d+-chloro|^bromomethane|^2-bromo-2-methyl|"
         r"^2-chloro-2-methyl|^2-chloropropane|^2-nitropropane|^chcl3\b|"
         r"^chloroform|^1,2,3,4,5,6-hexachloro",                              "alkyl_halide"),
        (r"^\(e\)-1-bromo.*but-2-ene|^\(e\)-1,4-dibromobut|"
         r"^3-bromobut-1-ene",                                                 "alkyl_halide"),  # vinyl/allylic halides
        # Specific aromatic products
        (r"^1,1-biphenyl\b|^9-nitroanthracene|^4-hydroxyphenyl ethanone|"
         r"^1-phenylethan-1-one|^1-\(2-hydroxyphenyl\)|^4,4'-diamino|"
         r"^arnhnh|^arnhoh|^arnh2\b",                                          "substituted_benzene"),
        (r"^arnhoh|phenylhydroxylamine",                                       "amine"),
        (r"^arnh2\b|^arnh-nhar|^arnh2.*primary amine",                        "aniline"),
        (r"^arn=nar\b|^azobenzene",                                            "azo_compound"),
        # Specific carboxylic acid products
        (r"^\(e\)-3.*prop-2-enoic acid|^\(e\)-2-methyl.*enoic acid|"
         r"^\(z\)-but-2-enedioic acid|^2-methylpropane-2-sulfonic acid",      "carboxylic_acid"),
        # Specific alcohols
        (r"^2-phenylethanol|^propan-1-ol\b|^butan-1-ol\b|^propan-2-ol\b",    "alcohol"),
        # Rearrangement products — specific carbocation strings
        (r"^\d+-methyl.*ylium|^2-methyl-2-phenyl.*ylium|^1-methyl.*ylium|"
         r"via 1,2-methyl shift|via 1,2-phenyl shift|via 1,2-hydride",       "carbocation"),
        # Ketone products
        (r"^4-methylpent-3-en-2-one|^1,5-keto-enol",                         "ketone"),
        # Alkene products
        (r"^\(e\)-3-phenylprop-2-enoic acid",                                 "carboxylic_acid"),
        (r"^alkene.*hofmann|^alkene.*zaitsev|^alkene.*less\s+substituted|"
         r"^alkene.*more\s+substituted",                                       "alkene"),
        # Silver / analytical outputs — skip
        (r"^silver$|^ag\b|^n2 gas|^(2\s+hcooh|formic acid.*oxidative)",      None),
        # GOC/electronic outputs — skip
        (r"^arnh-nhar\s+\(hydrazobenzene\)",                                  "amine"),
        # Bromomethane → alkyl_halide already caught above
        (r"^2-benzofuran-1,3-dione",                                          "anhydride"),  # phthalic anhydride
        (r"^2-methoxyphenylmagnesium",                                         "grignard"),
        (r"^2_2_dimethylpropane",                                             "alkane"),
        (r"^1_1_dimethylcyclopropane",                                        "cycloalkane"),
        (r"^4-methylpent-3-en-2-one",                                         "ketone"),
        (r"^1-e-naphthalen-2-ol",                                             "phenol"),
        (r"^alkyl nitrite r-ono",                                              "ester"),
        (r"^r-oms|^r-ots|^r-otf\b",                                           "sulfonate"),
        # Carbocation rearrangement "to" strings
        (r"via 1,2-(hydride|methyl|phenyl|aryl|bond)\s+shift|"
         r"cyclopentyl cation|cyclohexyl cation|cyclobutyl cation|"
         r"endocyclic.*cation|ring.expanded.*product",                        "carbocation"),
        # Analytical/test results — skip
        (r"^red\s+(color|solution|complex)|^blue.*insoluble|"
         r"^brick.red|^silver\s+mirror|^can\s+test",                          None),
    ]
    for pattern, node_id in to_patterns:
        if re.search(pattern, sl, re.IGNORECASE):
            return node_id

    return None


# ── Build edges from TXs ──────────────────────────────────────────────────────

def build_edges(txs):
    """Group TXs by (from_node, to_node), build edge objects."""

    # First pass: map all TXs
    mapped = []
    unmapped = []
    for i, tx in enumerate(txs):
        fn = normalize_node(tx["from"])
        tn = normalize_node(tx["to"])
        if fn and tn:
            mapped.append((fn, tn, tx, i))
        else:
            unmapped.append({
                "tx_index": i,
                "from_raw": tx["from"],
                "to_raw":   tx["to"],
                "from_mapped": fn,
                "to_mapped":   tn,
            })

    print(f"Mapped:   {len(mapped)}/{len(txs)} TXs ({100*len(mapped)//len(txs)}%)")
    print(f"Unmapped: {len(unmapped)}/{len(txs)} TXs")

    # Group by (from, to) pair
    groups = defaultdict(list)
    for fn, tn, tx, idx in mapped:
        groups[(fn, tn)].append((tx, idx))

    edges = []
    for (fn, tn), tx_list in sorted(groups.items()):
        # Use first TX as the canonical edge; others become conditions_variants or notes
        primary_tx = tx_list[0][0]

        # Build a compact reagent tag for the primary TX
        primary_reagents = primary_tx.get("reagents", [])
        def reagent_tag(reagents):
            r = reagents[0] if reagents else ""
            return re.sub(r"[^a-zA-Z0-9]", "", r).lower()[:12]
        edge_id = f"{fn}_to_{tn}_{reagent_tag(primary_reagents)}" if primary_reagents else f"{fn}_to_{tn}"

        # Build conditions_variants from TXs with different conditions/reagents
        variants = {}
        notes_list = []
        archetype_set = set()

        for tx, idx in tx_list:
            archs = tx.get("archetype", [])
            archetype_set.update(archs)
            if tx.get("notes"):
                notes_list.append(tx["notes"])

        # If multiple distinct reagent paths, encode as variants
        if len(tx_list) > 1:
            for j, (tx, idx) in enumerate(tx_list):
                reagents_key = ", ".join(tx.get("reagents", []))[:50]
                cond_key = tx.get("conditions", "")[:60].replace(" ", "_").lower()
                # Use reagent or condition as variant key
                var_key = reagents_key or cond_key or f"variant_{j}"
                if j == 0:
                    continue  # skip first — it's the default
                variants[f"reagent_{j}"] = {
                    "reagents":   tx.get("reagents", []),
                    "conditions": tx.get("conditions", "")[:300],
                    "to":         tn,
                    "tx_index":   idx,
                    "note": tx.get("notes", ""),
                }

        edge = {
            "id":      edge_id,
            "from":    fn,
            "to":      tn,
            "reagents":         primary_tx.get("reagents", []),
            "conditions":       primary_tx.get("conditions", "")[:500],
            "firing_condition": None,
            "chapter":          primary_tx.get("conditions", "")[:30],  # placeholder
            "archetype":        sorted(archetype_set),
            "chemoselectivity": {
                "requires_absent": [],
                "node_redirect":   {},
                "priority_ref":    None,
            },
            "tx_ids":           [idx for _, idx in tx_list],
            "meta_tags":        primary_tx.get("meta_tags", {}),
        }

        if variants:
            edge["conditions_variants"] = variants
        if notes_list:
            edge["notes"] = " | ".join(dict.fromkeys(notes_list))  # dedup

        edges.append(edge)

    return edges, unmapped


def main():
    with open(os.path.join(_KG, "concept_book.json"), encoding="utf-8") as f:
        cb = json.load(f)
    txs = cb["structural_operators"]["add_reaction_step"]["valid_transformations"]

    print(f"Total TXs: {len(txs)}")
    edges, unmapped = build_edges(txs)

    # Build final graph
    graph = {
        "version": "0.1",
        "description": "AutoData Reaction Knowledge Graph — JEE Advanced Organic Chemistry",
        "nodes": NODES,
        "edges": edges,
    }

    # Add chapter labels to edges from TX archetype + conditions
    # (Chapter inference: rough heuristic from from/to node)
    chapter_map = {
        ("alkane", "alkyl_halide"):    "Hydrocarbons",
        ("alkene", "alkane"):          "Hydrocarbons",
        ("alkene", "alkyl_halide"):    "Hydrocarbons",
        ("alkene", "diol"):            "Hydrocarbons",
        ("alkene", "epoxide"):         "Hydrocarbons",
        ("alkene", "aldehyde"):        "Hydrocarbons",
        ("alkene", "alcohol"):         "Hydrocarbons",
        ("alkene", "halohydrin"):      "Hydrocarbons",
        ("alkene", "vicinal_dihalide"):"Hydrocarbons",
        ("alkyne", "alkene"):          "Hydrocarbons",
        ("alkyne", "ketone"):          "Hydrocarbons",
        ("alkyne", "acetylide_ion"):   "Hydrocarbons",
        ("alkyl_halide", "alcohol"):   "Alkyl Halides",
        ("alkyl_halide", "alkene"):    "Alkyl Halides",
        ("alkyl_halide", "alkane"):    "Alkyl Halides",
        ("alkyl_halide", "grignard"):  "Organometallics & Grignard",
        ("alkyl_halide", "nitrile"):   "Alkyl Halides",
        ("alkyl_halide", "amine"):     "Amines",
        ("alkyl_halide", "ether"):     "Alcohols, Phenols & Ethers",
        ("alcohol", "aldehyde"):       "Aldehydes & Ketones",
        ("alcohol", "ketone"):         "Aldehydes & Ketones",
        ("alcohol", "carboxylic_acid"):"Carboxylic Acids & Derivatives",
        ("alcohol", "alkene"):         "Hydrocarbons",
        ("alcohol", "alkyl_halide"):   "Alkyl Halides",
        ("alcohol", "ester"):          "Carboxylic Acids & Derivatives",
        ("aldehyde", "carboxylic_acid"):"Aldehydes & Ketones",
        ("aldehyde", "alcohol"):       "Aldehydes & Ketones",
        ("ketone", "alcohol"):         "Aldehydes & Ketones",
        ("aniline", "diazonium_salt"): "Amines",
        ("diazonium_salt", "phenol"):  "Amines",
        ("diazonium_salt", "aryl_halide"):"Amines",
        ("benzene", "substituted_benzene"):"Aromatic Compounds",
        ("nitro_compound", "aniline"): "Amines",
        ("carboxylic_acid", "ester"):  "Carboxylic Acids & Derivatives",
        ("carboxylic_acid", "amide"):  "Carboxylic Acids & Derivatives",
        ("carboxylic_acid", "acid_chloride"):"Carboxylic Acids & Derivatives",
    }

    for edge in graph["edges"]:
        pair = (edge["from"], edge["to"])
        if pair in chapter_map:
            edge["chapter"] = chapter_map[pair]
        else:
            # Fallback: use from-node's chapter
            for n in NODES:
                if n["id"] == edge["from"]:
                    edge["chapter"] = n.get("chapter", "Reaction Mechanisms")
                    break

    with open(os.path.join(_KG, "reaction_graph.json"), "w") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    with open(os.path.join(_KG, "graph_unmapped.json"), "w") as f:
        json.dump(unmapped, f, indent=2, ensure_ascii=False)

    print(f"\nreaction_graph.json: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    print(f"graph_unmapped.json: {len(unmapped)} unmapped TXs for manual review")

    # Summary of edge distribution by (from, to)
    print("\nTop edges by TX count:")
    edge_counts = [(e["id"], len(e["tx_ids"])) for e in graph["edges"]]
    for eid, cnt in sorted(edge_counts, key=lambda x: -x[1])[:20]:
        print(f"  {cnt:3d}x  {eid}")


if __name__ == "__main__":
    main()
