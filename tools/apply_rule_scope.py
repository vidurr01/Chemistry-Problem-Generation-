"""
Write the approved organic substrate scopes (docs/organic_rule_scope.md, approved 2026-11-22) into
knowledge/reaction_graph.json: chemoselectivity.requires_absent and firing_condition per edge.
Group names are defined in core/engine/organic/scope.py. Re-running is idempotent (it sets, never appends).

    python tools/apply_rule_scope.py          # write the graph
    python tools/apply_rule_scope.py --check  # exit 1 if the graph differs from SCOPE
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.engine.organic.scope import GROUPS  # noqa: E402

GRAPH = os.path.join(ROOT, "knowledge", "reaction_graph.json")

# groups a strong reagent also attacks (one line each in the scope doc)
LAH = ["aldehyde", "ketone", "carboxylic_acid", "ester", "acid_chloride", "anhydride", "amide", "nitrile",
       "epoxide", "nitro_aliphatic"]
CO = ["aldehyde", "ketone", "ester", "acid_chloride", "anhydride", "amide", "nitrile"]
OXID = ["alkene", "alkyne", "aldehyde", "alcohol_1", "alcohol_2", "benzylic_ch", "phenol", "amine_nh"]


def but(group_list, *keep):
    """The list without the edge's own group(s)."""
    return [g for g in group_list if g not in keep]


# edge id -> {"absent": [...], "only": [...], "requires": [...], "at_most_one": [...], "note": "..."}
SCOPE = {
    # hydrocarbons
    "alkane_to_alkyl_halide_x": {"absent": ["aromatic_ring", "alkene"]},
    "alkene_to_aldehyde_o": {"absent": ["alkyne"]},
    "cycloalkene_to_alkane_o3": {"absent": ["alkyne"]},
    "alkene_to_alkane_h": {"absent": ["alkyne", "nitro", "aldehyde"]},
    "alkene_to_carboxylic_acid_hotkmno4acid": {"absent": but(OXID, "alkene")},
    "alkene_to_epoxide_mcpba": {"absent": ["ketone"]},
    "alkene_to_halohydrin_br": {"absent": ["phenol", "aryl_nh2"]},
    "alkene_to_vicinal_dihalide_x": {"absent": ["alkyne", "phenol", "aryl_nh2"]},
    "alkyne_to_carboxylic_acid_hotkmno4acid": {"absent": but(OXID, "alkyne")},
    "alkyne_to_vinyl_halide_hx1equiv": {"absent": ["alkene"]},
    # alkyl halides
    "alkyl_halide_to_alkane_zn": {"absent": ["vicinal_dihalide"],
                                  "note": "Zn turns a vicinal dihalide into the alkene, not the alkane"},
    "alkyl_halide_to_alkyl_halide_nai": {"absent": ["halide_3"], "note": "SN2: 1° > 2° >> 3°"},
    "alkyl_halide_to_ether_rona": {"absent": ["halide_2", "halide_3"],
                                   "note": "Williamson needs CH3 or 1° R–X (2° gives E2)"},
    "alkyl_halide_to_grignard_mg": {"absent": ["protic", "nitro", "epoxide"] + CO},
    # alcohols, diols, ethers, epoxides
    "alcohol_to_aldehyde_pcc": {"absent": ["alcohol_2"]},
    "alcohol_to_ketone_pcc": {"absent": ["alcohol_1"]},
    "alcohol_to_carboxylic_acid_kmno": {"absent": but(OXID, "alcohol_1")},
    "alcohol_to_alkyl_halide_socl": {"absent": ["carboxylic_acid", "alcohol_3"],
                                     "note": "3° OH eliminates with SOCl2/pyridine (runs 16, 17)"},
    "alcohol_to_carbene_chndiazometh": {"absent": ["carboxylic_acid", "phenol"],
                                        "note": "CH2N2 reactivity RCOOH >> ArOH > ROH"},
    "alcohol_to_ester_rcocl": {"absent": ["amine_nh", "phenol"]},
    "alcohol_to_ether_na": {"absent": ["carboxylic_acid", "phenol", "amine_nh"]},
    "alcohol_to_substituted_benzene_4methylbenze": {"absent": ["amine_nh"]},
    "diol_to_aldehyde_cu": {"absent": ["alcohol_2"]},
    "diol_to_alkane_redp": {"absent": ["aldehyde", "ketone", "carboxylic_acid", "ester", "alkyl_halide"]},
    "diol_to_alkyl_halide_pi": {"absent": ["vicinal_triol"],
                                "note": "glycerol + PI3 ends as allyl iodide, not the triiodide: not modelled"},
    "diol_to_ester_conchno": {"absent": ["aromatic_ring"]},
    "ether_to_alkyl_halide_conchxhihbra": {"absent": ["benzylic_allylic_ether"],
                                           "note": "benzylic/allylic C–O cleaves by SN1 at that carbon"},
    # phenols
    "phenol_to_aldehyde_naoh": {"absent": ["ortho_substituted_phenol"],
                                "note": "2-substituted phenols formylate at ortho and para: a mixture"},
    "substituted_benzene_to_aldehyde_naoh": {"absent": ["ortho_substituted_phenol"]},
    "phenol_to_ester_rcoclacylchl": {"absent": ["alcohol", "amine_nh"]},
    "phenol_to_substituted_benzene_chndiazometh": {"absent": ["carboxylic_acid"]},
    "phenol_to_aryl_halide_pclslowreact": {"absent": ["aldehyde"],
                                           "note": "PCl5 turns CHO into CHCl2 first; Ar-OH is the slow site "
                                                   "(live run 6, 2026-11-24; the author)"},
    # aldehydes and ketones
    "aldehyde_to_alcohol_nabh": {"absent": ["ketone", "acid_chloride"]},
    "aldehyde_to_aldehyde_naohdilute51": {"absent": but(CO, "aldehyde"), "at_most_one": ["aldehyde"]},
    "aldehyde_to_alkane_znhg": {"absent": ["ketone"]},
    "aldehyde_to_amine_h2ptornabh3c": {"absent": ["alkene", "ketone"]},
    "aldehyde_to_cyanohydrin_hcn": {"absent": ["ketone"]},
    "aldehyde_to_diol_lahallylalco": {"requires": ["enal"], "at_most_one": ["aldehyde"],
                                      "absent": but(LAH, "aldehyde")},
    "aldehyde_to_geminal_dihalide_pcl5": {"absent": ["alcohol", "phenol", "carboxylic_acid", "ketone"]},
    "aldehyde_to_imine_rnh": {"absent": ["ketone"]},
    "aldehyde_to_substituted_benzene_naohaqueouss": {"absent": ["hindered_archo"],
                                                     "note": "2,6-disubstituted ArCHO deformylates instead"},
    "ketone_to_alcohol_nabh": {"absent": ["aldehyde", "acid_chloride"]},
    "ketone_to_aldehyde_seo2selenium": {"absent": ["alpha_ch_ch2_ketone"],
                                        "note": "SeO2 prefers an α-CH2; modelled for CH3CO– with no other α-H"},
    "ketone_to_alkane_nhnh": {"absent": ["ester", "alkyl_halide"], "note": "CHO is reduced to CH3 as well"},
    "ketone_to_carbene_methylenepho": {"absent": ["aldehyde"]},
    "ketone_to_cyanohydrin_hcn": {"absent": ["aldehyde", "di_tert_ketone"]},
    "ketone_to_ester_mcpbametachl": {"absent": ["alkene"]},
    "ketone_to_ether_roh": {"absent": ["aldehyde"]},
    "ketone_to_oxime_nhohhcl": {"absent": ["aldehyde"]},
    "nitrile_to_ketone_12ch3mgbr": {"absent": ["protic"] + but(CO, "nitrile")},
    # acids and derivatives
    "acid_chloride_to_alcohol_1lialh4lithi": {"absent": but(LAH, "acid_chloride")},
    "acid_chloride_to_ketone_dimethylcupr": {"absent": ["protic"]},
    "carboxylic_acid_to_acid_chloride_socl": {"absent": ["alcohol"]},
    "carboxylic_acid_to_alcohol_lialh": {"absent": but(LAH, "carboxylic_acid")},
    "carboxylic_acid_to_alkyl_halide_agohtomakeag": {"absent": ["alkene"]},
    "carboxylic_acid_to_amide_nh": {"absent": ["ester"]},
    "carboxylic_acid_to_amine_hn3h2so4": {"absent": ["ketone"]},
    "anhydride_to_alkane_1lialh4exces": {"absent": but(LAH, "anhydride"), "at_most_one": ["anhydride"]},
    "amide_to_amine_lah": {"absent": but(LAH, "amide")},
    "lactam_to_amine_lah": {"absent": but(LAH, "amide")},
    "ester_to_acid_chloride_pcl5": {"absent": ["ester_o_not_primary", "alcohol", "carboxylic_acid", "ketone"],
                                    "note": "clean for R' = CH3 or 1° alkyl"},
    "ester_to_aldehyde_dibalhdiisob": {"absent": ["aldehyde", "ketone"], "at_most_one": ["ester"]},
    "ester_to_carboxylic_acid_h3odiluteaci": {"absent": ["nitrile", "amide"]},
    "ester_to_ester_aqnaoh": {"absent": ["nitrile", "amide", "alkyl_halide"]},
    # aromatics
    "benzene_to_aldehyde_co": {"absent": ["alkoxy_aryl", "phenol", "amine_any", "meta_director"],
                               "note": "Gattermann–Koch: benzene and alkyl/halo benzenes only"},
    "benzene_to_aryl_halide_x": {"absent": ["alkene"]},
    "benzene_to_ketone_rcocl": {"absent": ["meta_director", "amine_any", "phenol"],
                                "note": "Friedel–Crafts fails on deactivated rings and amines"},
    "benzene_to_substituted_benzene_conchno": {"absent": ["aldehyde", "alkene", "alcohol"]},
    "substituted_benzene_to_substituted_benzene_conchno3": {"absent": ["aldehyde", "alkene", "alcohol"],
                                                            "note": "mononitration"},
    "aryl_halide_to_phenol_naoh": {"only": ["Clc1ccccc1", "Brc1ccccc1"],
                                   "note": "benzyne on a substituted ring gives isomer mixtures"},
    "aryl_halide_to_grignard_mgmagnesiumm": {"absent": ["protic", "epoxide"] + CO},
    "aniline_to_diazonium_salt_nano2hclat05": {"absent": ["amine_aliphatic_nh2"]},
    "nitro_compound_to_azo_compound_znnaoh1mol": {"absent": ["aldehyde", "ketone"], "at_most_one": ["nitro"]},
    "nitro_compound_to_aniline_znnaoh2molor": {"absent": ["aldehyde"]},
    # amines, nitriles
    "amine_to_alcohol_nano": {"absent": ["nh2_can_shift"],
                              "note": "only CH3NH2, CH3CH2NH2 and ArCH2NH2: other 1° amines rearrange (mixtures)"},
    "amine_to_amide_rcocl": {"absent": ["alcohol", "phenol"]},
    "nitrile_to_aldehyde_dibalhdiisob": {"absent": ["ester", "ketone", "aldehyde"]},
    "nitrile_to_amine_h": {"absent": ["alkene", "alkyne", "nitro"]},
    "nitrile_to_carboxylic_acid_ho": {"absent": ["ester", "amide"]},
    # added from the concept-book coverage audit (reviewer-approved, 2026-11-26)
    'alkene_to_alcohol_bhthfhonaoh': {'absent': ['acetal', 'acid_chloride', 'activated_cx', 'alcohol_3', 'aldehyde', 'alkyne', 'amide', 'amine_any', 'anhydride', 'benzylic_allylic_ether', 'beta_hydroxy_carbonyl', 'carboxylic_acid', 'conj_cc', 'cyanohydrin', 'epoxide', 'ester', 'gem_dihalide', 'imine', 'ketone', 'nitrile', 'oxime', 'sulfonate_ester', 'vinyl_halide'], 'at_most_one': ['alkene']},
    'acid_chloride_to_aldehyde_hpdbaso': {'absent': ['alkene', 'alkyne', 'nitro', 'aldehyde', 'nitrile', 'alkyl_halide'], 'at_most_one': ['acid_chloride']},
    'diol_to_ketone_conchso': {'absent': ['alkene', 'alkyne', 'aldehyde', 'ketone', 'amine_any', 'phenol', 'carboxylic_acid', 'ester', 'acid_chloride', 'anhydride', 'amide', 'nitrile'], 'note': 'modelled for 3°,3° vicinal diols with one possible migration (the rule refuses the rest)'},
    'alkene_to_alkyl_halide_cl773k': {'absent': ['alkyne', 'benzylic_ch', 'aldehyde', 'alcohol', 'amine_any', 'phenol', 'alkyl_halide', 'ketone', 'carboxylic_acid', 'ester', 'acid_chloride', 'anhydride', 'amide', 'nitrile'], 'at_most_one': ['alkene']},
    'alcohol_to_ether_conchso413k': {'absent': ['isocyanide', 'quaternary_ammonium', 'acetal', 'activated_cx', 'aldehyde', 'alkene', 'alkyne', 'amide', 'amine_any', 'beta_hydroxy_carbonyl', 'cyanohydrin', 'epoxide', 'ester', 'halohydrin', 'imine', 'nitrile', 'oxime', 'phenol'], 'requires': ['alcohol_1'], 'at_most_one': ['alcohol']},
    'grignard_to_alkane_ho': {'note': 'alkyl Grignard reagents (the rule refuses aryl)'},
    'sulfonate_to_nitrile_nacn': {'absent': ['isocyanide', 'quaternary_ammonium', 'alkyl_halide', 'acid_chloride', 'epoxide', 'aldehyde', 'ketone', 'ester', 'anhydride'], 'at_most_one': ['sulfonate_ester']},
    'sulfonate_to_alkyl_halide_nai': {'absent': ['isocyanide', 'quaternary_ammonium', 'alkyl_halide', 'acid_chloride', 'epoxide', 'aldehyde', 'ketone', 'ester', 'anhydride'], 'at_most_one': ['sulfonate_ester']},
    'carboxylic_acid_to_alkane_kolbe': {'absent': ['alkene', 'alkyne', 'alcohol', 'phenol', 'amine_any', 'aldehyde', 'ketone', 'ester', 'alkyl_halide', 'aromatic_ring'], 'at_most_one': ['carboxylic_acid']},
    # concept-book coverage audit, batch 2 (reviewer-approved, 2026-11-26)
    'alkyl_halide_to_amine_potassiumphthalimide': {'absent': ['acid_chloride', 'ester', 'anhydride', 'aldehyde', 'ketone', 'epoxide', 'sulfonate_ester'], 'at_most_one': ['alkyl_halide']},
    'amine_to_alkene_moistagoheat': {'absent': ['alkyl_halide', 'ester', 'acid_chloride', 'aldehyde', 'ketone'], 'requires': ['quaternary_ammonium'], 'at_most_one': ['quaternary_ammonium']},
    'alkyne_to_benzene_redhotfetube': {'note': 'ethyne only (the rule refuses other alkynes)'},
    'substituted_benzene_to_substituted_benzene_dilhsosteam': {'absent': ['ester', 'amide', 'nitrile', 'acetal', 'anhydride', 'acid_chloride'], 'note': 'rings carrying –SO3H (the rule refuses the rest)'},
    'ketone_to_carboxylic_acid_naohheathoo': {'absent': ['ester', 'aldehyde', 'acid_chloride', 'anhydride', 'alkyl_halide']},
    'alcohol_to_aldehyde_activatedmno': {'absent': ['amine_any', 'phenol', 'aldehyde']},
    'alkyl_halide_to_ether_dryago': {'absent': ['acid_chloride', 'ester', 'anhydride', 'aldehyde', 'ketone', 'epoxide', 'sulfonate_ester', 'alcohol'], 'at_most_one': ['alkyl_halide']},
    'isocyanide_to_amine_hpt': {'absent': ['alkene', 'alkyne', 'nitro', 'nitrile', 'aldehyde', 'ketone'], 'at_most_one': ['isocyanide']},
    'aldehyde_to_alkyl_halide_naohaq': {'note': 'chloral only (the rule refuses the rest)'},
    'carboxylic_acid_to_ketone_heatbaoh': {'note': 'hexanedioic and heptanedioic acid only'},
}

# Selectivity audit 2026-11-24 (docs/organic_selectivity_audit.md, groups A and B, approved by the author): the
# same reagent attacks these groups as fast or faster, so the edge must not fire while they are present.
SELECTIVITY = {
    "ether_to_alkyl_halide_conchxhihbra": ["epoxide"],
    "phenol_to_aryl_halide_pclslowreact": ["alcohol", "carboxylic_acid", "ketone"],
    "ester_to_acid_chloride_pcl5": ["aldehyde"],
    "ketone_to_ester_mcpbametachl": ["aldehyde", "amine_any"],
    "alkene_to_epoxide_mcpba": ["aldehyde", "amine_any"],
    "aldehyde_to_acetal_roh2": ["carboxylic_acid", "acid_chloride", "anhydride", "epoxide"],
    "ketone_to_ether_roh": ["carboxylic_acid", "acid_chloride", "anhydride", "epoxide"],
    "aldehyde_to_substituted_benzene_naohaqueouss": ["ester", "acid_chloride", "anhydride", "alkyl_halide"],
    "aldehyde_to_aldehyde_naohdilute51": ["alkyl_halide"],
    "alkyl_halide_to_alcohol_naoh": ["ester", "acid_chloride", "anhydride"],
    "alkyl_halide_to_alkene_alckoh": ["ester", "acid_chloride", "anhydride"],
    "alkyl_halide_to_amine_excessnh": ["acid_chloride", "anhydride", "aldehyde", "epoxide"],
    "alkyl_halide_to_ether_rona": ["ester", "acid_chloride", "anhydride"],
    "alkene_to_alcohol_ho": ["epoxide"],
    "alkene_to_alkyl_halide_hx": ["epoxide"],
    "alkyne_to_vinyl_halide_hx1equiv": ["epoxide"],
    "alkyne_to_geminal_dihalide_hxexcess2equ": ["alkene", "epoxide"],
    "epoxide_to_vicinal_dihalide_hx": ["alkene", "alkyne", "alcohol"],
    "alkyne_to_ketone_ho": ["alkene"],
    "benzene_to_aryl_halide_x": ["alkyne"],
    "carboxylic_acid_to_alkyl_halide_agohtomakeag": ["alkyne"],
    "alkene_to_halohydrin_br": ["aldehyde", "alkyne"],
    "ketone_to_ketone_x2": ["alkene", "alkyne", "phenol", "aryl_nh2"],
    "ketone_to_carboxylic_acid_x2cl2br2ori2": ["methyl_carbinol", "ester", "acid_chloride", "anhydride", "phenol",
                                               "aryl_nh2"],
    "carboxylic_acid_to_carboxylic_acid_x": ["alcohol", "alkene", "alkyne", "ketone"],
    "acid_chloride_to_alcohol_1lialh4lithi": ["alkyl_halide"],
    "carboxylic_acid_to_alcohol_lialh": ["alkyl_halide"],
    "amide_to_amine_lah": ["alkyl_halide"],
    "lactam_to_amine_lah": ["alkyl_halide"],
    "ester_to_aldehyde_dibalhdiisob": ["acid_chloride", "nitrile"],
    "nitrile_to_aldehyde_dibalhdiisob": ["acid_chloride"],
    "nitrile_to_amine_h": ["aldehyde"],
    "aldehyde_to_amine_h2ptornabh3c": ["alkyne", "nitro", "nitrile"],
    "nitrile_to_ketone_12ch3mgbr": ["epoxide"],
    "ketone_to_carbene_methylenepho": ["carboxylic_acid", "alcohol", "phenol"],
    "alkene_to_ether_hgoacrohorhg": ["aldehyde", "ketone", "alkyne"],
    "acid_chloride_to_ketone_dimethylcupr": ["alkyl_halide"],
    "phenol_to_aldehyde_naoh": ["amine_aliphatic_nh2", "aryl_nh2", "ester"],
    "substituted_benzene_to_aldehyde_naoh": ["amine_aliphatic_nh2", "aryl_nh2", "ester"],
    "amine_to_alcohol_nano": ["aryl_nh2"],
    "ester_to_carboxylic_acid_h3odiluteaci": ["acid_chloride", "epoxide"],
    "nitrile_to_carboxylic_acid_ho": ["acid_chloride", "epoxide"],
    "alcohol_to_substituted_benzene_4methylbenze": ["phenol"],
    "benzene_to_ketone_rcocl": ["alcohol"],
    "diol_to_diol_2eqchcooh": ["amine_nh", "phenol"],
    "phenol_to_substituted_benzene_chndiazometh": ["amine_nh", "ester"],
    "aryl_halide_to_grignard_mgmagnesiumm": ["alkyl_halide"],   # a C(sp3)–X takes Mg first (two answers)
}
for _eid, _groups in SELECTIVITY.items():
    _absent = SCOPE.setdefault(_eid, {}).setdefault("absent", [])
    _absent.extend(g for g in _groups if g not in _absent)

# Review of the 62 edges that had no scope (2026-11-24, done by Claude at the author's request; the author may veto):
# limits where the reagent attacks other groups, a note where the rule already fixes the substrate. Left out of
# draws (no entry here): alcohol_to_amine_al2o3450c (a mixture of amines), alkyl_halide_to_ketone_dmsodimethyl
# (Kornblum is for activated halides only), ester_to_ether_conchso (the product drops the skeleton) and
# ether_to_ester_co (industrial, not JEE).
FIXED = "the rule accepts one textbook substrate only"
SAFE = "reviewed: the step needs no other limit"
REVIEW = {
    "acid_chloride_to_amine_nan3h3o": {"absent": ["alkyl_halide", "amine_nh", "alcohol", "phenol", "anhydride",
                                                  "epoxide"], "note": "N3- does SN2; the isocyanate takes OH/NH"},
    "alcohol_to_alkene_conchso": {"absent": ["alkene", "alkyne", "epoxide", "aldehyde", "ester", "nitrile", "amide",
                                             "phenol"]},
    "alcohol_to_sulfonate_conchso": {"requires": ["alcohol_1"], "at_most_one": ["alcohol"],
                                     "absent": ["alcohol_2", "aromatic_ring", "alkene", "alkyne", "epoxide",
                                                "aldehyde"],
                                     "note": "the 383 K hydrogen sulphate is the simple 1° alcohol case (ethanol); "
                                             "2° and benzylic alcohols dehydrate (live run 7)"},
    "aldehyde_to_carboxylic_acid_kmnoortollen": {"absent": ["terminal_alkyne"], "note": "Ag+ takes ≡C–H"},
    "alkane_to_benzene_al2o3cr2o3": {"note": FIXED},
    "alkene_to_diol_oso": {"note": SAFE + " (every C=C is dihydroxylated)"},
    "alkyl_halide_to_acid_chloride_o2": {"note": FIXED},
    "alkyl_halide_to_cycloalkane_mgmagnesiumm": {"absent": ["protic", "epoxide"] + CO},
    "alkyl_halide_to_nitrile_nacn": {"absent": ["acid_chloride", "anhydride", "aldehyde", "epoxide",
                                                "carboxylic_acid"]},
    "alkyl_halide_to_nitro_compound_agno2silvern": {"absent": ["acid_chloride", "anhydride", "carboxylic_acid"]},
    "alkyne_to_alkane_o3": {"absent": ["alkene"]},
    "alkyne_to_alkene_h": {"absent": ["acid_chloride", "nitro"], "note": "Pd/BaSO4 also reduces COCl (Rosenmund)"},
    "amine_to_amine_heatsn2": {"absent": ["acid_chloride", "anhydride", "alkyl_halide", "epoxide"],
                               "at_most_one": ["amine_any"]},
    "amine_to_imine_rcho": {"absent": ["aldehyde", "ketone", "acid_chloride", "anhydride"]},
    "amine_to_isocyanide_carbylaminetest": {"absent": ["alkyl_halide", "ester", "acid_chloride", "anhydride",
                                                       "phenol", "aldehyde"]},
    "amine_to_nitro_compound_kmno4": {"absent": but(OXID, "amine_nh"), "at_most_one": ["amine_any"]},
    "aniline_to_ketone_kmno4heatorh": {"note": FIXED},
    "aniline_to_substituted_benzene_carosacidh2s": {"absent": ["alkene", "aldehyde", "ketone",
                                                               "amine_aliphatic_nh2", "phenol"]},
    "aryl_halide_to_substituted_benzene_naome": {"absent": ["alkyl_halide", "ester", "acid_chloride", "anhydride"]},
    "benzene_to_alcohol_oxirane": {"note": FIXED},
    "benzene_to_alkyl_halide_3cl2": {"note": FIXED},
    "benzene_to_carboxylic_acid_fuminghsoole": {"absent": ["alcohol", "alkene", "alkyne", "epoxide", "aldehyde",
                                                           "nitrile", "ester", "amide", "amine_any"]},
    "benzene_to_phenol_feso": {"note": FIXED},
    "carbohydrate_to_carbohydrate_ch3co2o": {"absent": ["amine_nh", "phenol"]},
    "carboxylic_acid_to_alkane_naoh": {"absent": ["ester", "alkyl_halide", "aldehyde", "acid_chloride", "anhydride",
                                                  "amide", "nitrile"]},
    "carboxylic_acid_to_benzene_naoh": {"absent": ["ester", "alkyl_halide", "aldehyde", "acid_chloride",
                                                   "anhydride", "amide", "nitrile"]},
    "carboxylic_acid_to_anhydride_hso": {"absent": ["alcohol", "amine_nh"]},
    "carboxylic_acid_to_ester_roh": {"absent": ["alcohol", "epoxide", "acid_chloride", "anhydride", "aldehyde"],
                                     "note": "a hydroxy acid closes a lactone instead"},
    "diazonium_salt_to_aryl_halide_cuxsandmeyer": {"absent": ["phenol"], "note": "a phenol couples with ArN2+"},
    "diazonium_salt_to_azo_compound_arohorarnhco": {"absent": ["phenol"]},
    "diazonium_salt_to_naphthalene_alkalinecoup": {"absent": ["phenol"]},
    "diazonium_salt_to_nitrile_nacn": {"absent": ["phenol", "alkyl_halide"]},
    "diazonium_salt_to_phenol_ho": {"absent": ["phenol"]},
    "diazonium_salt_to_substituted_benzene_hpo": {"absent": ["phenol"]},
    "diene_conjugated_to_alkyl_halide_hbr1eq": {"absent": ["epoxide", "alkyne"]},
    "diol_to_aldehyde_hio4periodic": {"absent": ["vicinal_triol"], "note": "the rule cleaves one diol unit"},
    "diol_to_carboxylic_acid_kmno": {"absent": ["vicinal_triol", "alkene", "alkyne", "aldehyde", "benzylic_ch",
                                                "phenol", "aryl_nh2"]},
    "epoxide_to_alcohol_rnh": {"absent": ["acid_chloride", "anhydride", "aldehyde", "ketone", "alkyl_halide"]},
    "epoxide_to_diol_ho": {"absent": ["ester", "acid_chloride", "anhydride", "alkyl_halide"]},
    "epoxide_to_epoxide_h3odiluteaci": {"absent": ["alkene", "acid_chloride", "anhydride"]},
    "epoxide_to_halohydrin_hx": {"absent": ["alkene", "alkyne", "amine_any"]},
    "ester_to_ketone_alcl": {"absent": ["alcohol", "amine_any", "alkene"]},
    "ether_to_phenol_thermalnocat": {"note": SAFE + " (Claisen needs a free ortho C–H; ties are refused)"},
    "grignard_to_alcohol_hcho": {"note": SAFE + " (the Grignard step already excludes protic and C=O groups)"},
    "grignard_to_carboxylic_acid_co": {"note": SAFE + " (the Grignard step already excludes protic and C=O groups)"},
    "isocyanide_to_amine_hydrolysis": {"absent": ["epoxide"]},
    "ketone_to_alkyl_halide_i2": {"absent": ["methyl_carbinol", "ester", "acid_chloride", "anhydride", "phenol",
                                             "aryl_nh2", "aldehyde"]},
    "ketone_to_lactone_diazomethane": {"absent": ["carboxylic_acid", "phenol", "aldehyde"]},
    "naphthalene_to_anhydride_o2": {"note": FIXED},
    "naphthalene_to_naphthalene_conch2so4": {"note": FIXED},
    "phenol_to_benzene_znreductionl": {"absent": ["nitro", "aldehyde", "ketone", "carboxylic_acid", "alkyl_halide"]},
    "phenol_to_geminal_dihalide_kso": {"absent": ["aldehyde", "aryl_nh2", "amine_nh", "alkene"]},
    "phenol_to_ketone_kmnoornacroh": {"note": FIXED},
    "substituted_benzene_to_anhydride_seecondition": {"note": FIXED},
    "substituted_benzene_to_carboxylic_acid_1naoh": {"absent": ["ester", "acid_chloride", "anhydride",
                                                                "alkyl_halide", "aldehyde"]},
    "substituted_benzene_to_ketone_oradicalinit": {"note": FIXED},
    "substituted_benzene_to_phenol_1conch2so4de": {"note": FIXED},
    "vicinal_dihalide_to_alkyne_zndeltaexces": {"note": SAFE},
    # second pass (the selectivity audit's remaining real flags)
    "alkene_to_alkyl_halide_hx": {"absent": ["alcohol"]},
    "alkyne_to_vinyl_halide_hx1equiv": {"absent": ["alcohol"]},
    "alkyne_to_geminal_dihalide_hxexcess2equ": {"absent": ["alcohol"]},
    "alkyl_halide_to_alcohol_naoh": {"absent": ["epoxide"]},
    "alkyl_halide_to_amine_excessnh": {"absent": ["ester"], "note": "excess NH3 also turns esters into amides"},
    "amine_to_alcohol_nano": {"absent": ["phenol"]},
    "aniline_to_diazonium_salt_nano2hclat05": {"absent": ["phenol"], "note": "ArN2+ couples with a phenol"},
    "diol_to_ester_conchno": {"absent": ["aldehyde"]},
    "ester_to_acid_chloride_pcl5": {"absent": ["phenol"]},
    "phenol_to_aldehyde_naoh": {"absent": ["acid_chloride", "anhydride"]},
    "substituted_benzene_to_aldehyde_naoh": {"absent": ["acid_chloride", "anhydride"]},
}
# third pass: every trusted edge's products read by hand (textbook molecule + two mixed molecules). A separate
# dict so that its entries add to REVIEW's instead of replacing them.
PASS3 = {
    "acid_chloride_to_amine_nan3h3o": {"absent": ["aldehyde", "ketone"], "note": "the new NH2 condenses with C=O"},
    "alcohol_to_ether_na": {"absent": ["alkyl_halide"], "note": "a halo-alkoxide closes a ring (THF)"},
    "alkyl_halide_to_ether_rona": {"absent": ["alcohol"]},
    "aldehyde_to_aldehyde_naohdilute51": {"absent": ["amine_nh"]},
    "alkene_to_carboxylic_acid_hotkmno4acid": {"absent": ["acid_chloride", "anhydride"]},
    "alkyne_to_carboxylic_acid_hotkmno4acid": {"absent": ["acid_chloride", "anhydride"]},
    "alcohol_to_carboxylic_acid_kmno": {"absent": ["acid_chloride", "anhydride"]},
    "diol_to_carboxylic_acid_kmno": {"absent": ["acid_chloride", "anhydride"]},
    "benzene_to_ketone_rcocl": {"absent": ["alkyne", "alkene"]},
    "benzene_to_aldehyde_co": {"absent": ["alkyne", "alkene"]},
    "ester_to_acid_chloride_pcl5": {"absent": ["amine_nh"]},
    "carboxylic_acid_to_acid_chloride_socl": {"absent": ["amine_nh"], "note": "ArCOCl + NH2 react together"},
    "phenol_to_aryl_halide_pclslowreact": {"absent": ["ester"]},
    "nitrile_to_amine_h": {"absent": ["alkyl_halide"]},
    "nitrile_to_carboxylic_acid_ho": {"absent": ["alkyl_halide"]},
    "nitrile_to_ketone_12ch3mgbr": {"absent": ["alkyl_halide"]},
    # live run 8: electrophilic additions and 1,2-additions are modelled for isolated C=C / C≡C and C=O only; on a
    # conjugated (Michael acceptor) system the regiochemistry changes (β-attack, 1,4-addition)
    "alkene_to_alcohol_ho": {"absent": ["conj_cc"]},
    "alkene_to_alkyl_halide_hx": {"absent": ["conj_cc"]},
    "alkene_to_halohydrin_br": {"absent": ["conj_cc"]},
    "alkene_to_ether_hgoacrohorhg": {"absent": ["conj_cc"]},
    "alkene_to_epoxide_mcpba": {"absent": ["conj_cc"], "note": "an electron-poor C=C needs H2O2/OH-, not mCPBA"},
    "diene_conjugated_to_alkyl_halide_hbr1eq": {"absent": ["conj_cc"]},
    "alkyne_to_vinyl_halide_hx1equiv": {"absent": ["conj_alkyne"]},
    "alkyne_to_geminal_dihalide_hxexcess2equ": {"absent": ["conj_alkyne"]},
    "alkyne_to_ketone_ho": {"absent": ["conj_alkyne"]},
    "aldehyde_to_cyanohydrin_hcn": {"absent": ["conj_cc"], "note": "CN- adds 1,4 to an enone/enal"},
    "ketone_to_cyanohydrin_hcn": {"absent": ["conj_cc"]},
    "aldehyde_to_imine_rnh": {"absent": ["conj_cc"]},
    "amine_to_imine_rcho": {"absent": ["conj_cc"]},
    "epoxide_to_alcohol_rnh": {"absent": ["conj_cc"]},
    "alkyl_halide_to_amine_excessnh": {"absent": ["conj_cc"]},
}
# Live run 9: gaps the blind step check found (it held these schemes).
RUN9 = {
    "substituted_benzene_to_carboxylic_acid_1naoh": {"absent": ["epoxide"], "note": "hot NaOH opens an epoxide"},
    "phenol_to_aldehyde_naoh": {"absent": ["epoxide"]},
    "substituted_benzene_to_aldehyde_naoh": {"absent": ["epoxide"]},
    "ester_to_ester_aqnaoh": {"absent": ["epoxide"]},
    "aldehyde_to_aldehyde_naohdilute51": {"absent": ["epoxide"]},
    "ether_to_alkyl_halide_conchxhihbra": {"absent": ["alcohol", "alkyl_halide", "sulfonate_ester"],
                                           "note": "HI takes an OH, C–X or OTs before an ether"},
    "alcohol_to_substituted_benzene_4methylbenze": {"at_most_one": ["alcohol"],
                                                    "note": "two different OH: which is tosylated is not settled"},
}

# Live run 12: every scheme was held by the step check; the patterns behind the holds.
def _run12() -> dict:
    import re as _re
    from core.engine.organic.labels import REAGENT_LABEL as _L
    out = {}
    # aqueous / protic acid (incl. an H3O+ work-up) opens an acetal and hydrolyses or rearranges an oxime
    keep = {"aldehyde_to_acetal_roh2", "ketone_to_ether_roh", "ketone_to_oxime_nhohhcl"}
    for eid, lab in _L.items():                     # dropped edges stay out: LEFT_OUT overrides any scope
        if eid not in keep and _re.search(r"H₃O⁺|dil\.|H₂O, warm|Br₂, H₂O|H₂SO₄|HNO₃|HBr|HI\b|HCl|HN₃|HIO₄", lab):
            out[eid] = {"absent": ["acetal", "oxime"]}
    for eid in ("alkene_to_aldehyde_o", "cycloalkene_to_alkane_o3", "alkyne_to_alkane_o3"):   # O3 cleaves C=N too
        out.setdefault(eid, {"absent": []})["absent"] += ["oxime"]
    # two DIFFERENT C–X: which one reacts is not settled (equivalent ones all react, as before); a vicinal
    # dihalide eliminates with these nucleophiles / bases
    for eid in ("alkyl_halide_to_nitrile_nacn", "alkyl_halide_to_nitro_compound_agno2silvern",
                "alkyl_halide_to_alkyl_halide_nai", "alkyl_halide_to_amine_excessnh", "alkyl_halide_to_alcohol_naoh",
                "alkyl_halide_to_ether_rona", "alkyl_halide_to_alkene_alckoh", "alkyl_halide_to_grignard_mg"):
        out.setdefault(eid, {})["equivalent_only"] = ["alkyl_halide"]
        out[eid].setdefault("absent", []).append("vicinal_dihalide")
    # dry HCl adds to a C=C; an ylide / HBr displaces a tosylate; CH2N2 + acid homologates a C=O
    for eid in ("aldehyde_to_acetal_roh2", "ketone_to_ether_roh"):
        out.setdefault(eid, {"absent": []})["absent"] += ["alkene"]
    out.setdefault("ketone_to_carbene_methylenepho", {"absent": []})["absent"] += ["sulfonate_ester", "alkyl_halide"]
    for eid in ("alkene_to_alkyl_halide_hx", "alkyne_to_vinyl_halide_hx1equiv", "alkyne_to_geminal_dihalide_hxexcess2equ",
                "epoxide_to_halohydrin_hx", "epoxide_to_vicinal_dihalide_hx", "diene_conjugated_to_alkyl_halide_hbr1eq"):
        out.setdefault(eid, {"absent": []}).setdefault("absent", []).append("sulfonate_ester")
    out.setdefault("alcohol_to_carbene_chndiazometh", {"absent": []})["absent"] += ["ketone", "aldehyde"]
    return out


RUN12 = _run12()

# Live run 13: the step check's holds, read by hand.
RUN13 = {
    "diol_to_ester_conchno": {"absent": ["alkene", "alkyne", "aromatic_ring", "alcohol_3"],
                              "note": "nitrate esters of simple polyols (glycerol type)"},
    "alkene_to_halohydrin_br": {"absent": ["vinyl_halide"]},
    "alkene_to_alcohol_ho": {"absent": ["vinyl_halide"]},
    "alkene_to_ether_hgoacrohorhg": {"absent": ["vinyl_halide"]},
    "alkene_to_diol_oso": {"absent": ["vinyl_halide"]},
    "alkene_to_epoxide_mcpba": {"absent": ["vinyl_halide"]},
    "alkene_to_alkyl_halide_hx": {"absent": ["dialkyl_ether"], "note": "HBr also cleaves an ether"},
    "alkyne_to_vinyl_halide_hx1equiv": {"absent": ["dialkyl_ether"]},
    "alkyne_to_geminal_dihalide_hxexcess2equ": {"absent": ["dialkyl_ether"]},
    "aldehyde_to_acetal_roh2": {"absent": ["ketone"], "note": "excess MeOH/HCl acetalises a ketone too"},
    "ketone_to_ester_mcpbametachl": {"absent": ["carboxylic_acid"]},
    "ketone_to_ketone_x2": {"absent": ["acetal"]},
}

# Layer 2, the reagent × group table (2026-11-25). Live runs kept finding, one edge at a time, a second group the
# same conditions attack (53 of the 81 steps the blind step check held were still drawable). So the limits now go
# by reagent CLASS: every edge whose conditions fall in a class refuses a molecule carrying any of the class's
# groups, except the group(s) the edge itself acts on (OWN, by the edge's start node). tools/replay_step_holds.py
# re-checks every held step against this.
OWN = {
    "alkyl_halide": {"alkyl_halide", "halide_2", "halide_3", "activated_cx", "gem_dihalide", "vicinal_dihalide"},
    "vicinal_dihalide": {"alkyl_halide", "vicinal_dihalide"},
    "ester": {"ester"}, "nitrile": {"nitrile", "cyanohydrin"}, "alkene": {"alkene"}, "cycloalkene": {"alkene"},
    "diene_conjugated": {"alkene"}, "alkyne": {"alkyne", "terminal_alkyne"}, "epoxide": {"epoxide"},
    "alcohol": {"alcohol", "alcohol_1", "alcohol_2", "alcohol_3", "methyl_carbinol"},
    "diol": {"alcohol", "alcohol_1", "alcohol_2", "alcohol_3"}, "aldehyde": {"aldehyde"},
    "ketone": {"ketone", "alpha_ch_ch2_ketone"}, "amine": {"amine_any", "amine_nh", "amine_aliphatic_nh2"},
    "aniline": {"amine_any", "amine_nh", "aryl_nh2"}, "carboxylic_acid": {"carboxylic_acid"},
    "phenol": {"phenol"}, "amide": {"amide"}, "lactam": {"amide"}, "acid_chloride": {"acid_chloride"},
    "anhydride": {"anhydride"}, "ether": {"dialkyl_ether", "benzylic_allylic_ether", "alkoxy_aryl"},
    "nitro_compound": {"nitro", "nitro_aliphatic"}, "oxime": {"oxime"},
    "sulfonate": {"sulfonate_ester"},            # tosylate SN2 edges (concept-book coverage audit, 2026-11-26)
}
HYDROLYTIC = ["ester", "amide", "nitrile", "acid_chloride", "anhydride", "acetal", "oxime", "imine", "cyanohydrin",
              "gem_dihalide", "activated_cx", "sulfonate_ester", "epoxide", "alcohol_3", "beta_hydroxy_carbonyl",
              "benzylic_allylic_ether", "alkene"]
BASIC = ["ester", "acid_chloride", "anhydride", "halohydrin", "alpha_halo_carbonyl", "cyanohydrin",
         "sulfonate_ester", "gem_dihalide", "epoxide", "alkyl_halide",
         "allylic_halide", "neopentyl_halide"]          # OH⁻ is a nucleophile too: SN2′, no SN2 (live run 2, 11-25)
NUCLEOPHILE = ["sulfonate_ester", "allylic_halide", "neopentyl_halide", "halohydrin", "alpha_halo_carbonyl",
               "epoxide", "acid_chloride", "anhydride", "cyanohydrin"]
LAYER2 = [
    # (what, label regex or explicit edge ids, groups)
    ("aqueous acid, hydrolysing", {"alkyne_to_ketone_ho", "alkene_to_alcohol_ho", "nitrile_to_carboxylic_acid_ho",
                                   "ester_to_carboxylic_acid_h3odiluteaci", "epoxide_to_epoxide_h3odiluteaci",
                                   "isocyanide_to_amine_hydrolysis", "diazonium_salt_to_phenol_ho",
                                   "acid_chloride_to_amine_nan3h3o"}, HYDROLYTIC),
    ("strong acid / HX / acid + alcohol", r"conc\. H|HBr|HI\b|dry HCl|HN₃|Zn–Hg|Sn, conc",
     ["imine", "cyanohydrin", "alcohol_3", "activated_cx", "beta_hydroxy_carbonyl", "halohydrin"]),
    # live run 2 (2026-11-25): acid α-halogenation slows after the first X (a second Br2 does not settle on the
    # same carbon), and Baeyer–Villiger next to a C–X has no settled migrating group
    ("α-halo ketones: no second acid halogenation, no clear Baeyer–Villiger",
     {"ketone_to_ketone_x2", "ketone_to_ester_mcpbametachl"}, ["alpha_halo_carbonyl"]),
    ("HX protonates amines first", r"HBr|HI\b", ["amine_any"]),
    ("acid + methanol: transesterification, other OH", {"aldehyde_to_acetal_roh2", "ketone_to_ether_roh",
                                                        "carboxylic_acid_to_ester_roh"},
     ["ester", "alcohol", "phenol", "activated_cx"]),
    ("hydroxide / alkoxide", r"NaOH|KOH|OH⁻|CH₃ONa|NaOMe", BASIC),
    ("nucleophiles (SN2 / addition)", r"NaCN|KCN|CuCN|AgNO₂|NaI|NH₃|CH₃NH₂|NaN₃|CH₃ONa|CH₃I", NUCLEOPHILE),
    ("CN⁻ and amines also displace C–X", r"KCN|NH₃|CH₃NH₂", ["alkyl_halide"]),
    ("amines are protonated by COOH", r"NH₃|CH₃NH₂", ["carboxylic_acid"]),
    # live run 4 (2026-11-25): CH3NH2 opened an epoxide beside an acetate; NH3/amines turn esters into amides
    # (alkyl_halide_to_amine_excessnh already had this limit, the methylamine edges did not)
    ("ammonia and amines aminolyse esters", r"NH₃|CH₃NH₂", ["ester"]),
    # live run 5 (2026-11-25): Hunsdiecker (Ag2O, Br2) beside a 3° benzylic C–Br (Ag⁺ ionises it), then Zn dust
    # beside a benzylic CH2Br; Tollens' reagent is Ag⁺ in NH3 (both attack C–X)
    ("Ag⁺ pulls the halide off C–X", r"Ag₂O|Tollens", ["alkyl_halide"]),
    ("zinc metal also reduces an activated C–X", r"Zn dust", ["lone_activated_cx"]),
    # live run 6 (2026-11-25): each held by the step check
    ("strong base also attacks a CHO (Cannizzaro / aldol)", r"NaOH|KOH|OH⁻|CH₃ONa|\bNa;", ["aldehyde"]),
    ("Na / alkoxide also deprotonates an α-nitro C–H (the nitronate is alkylated)", r"\bNa;|CH₃ONa",
     ["nitro_aliphatic"]),
    ("Ag₂O oxidises a CHO", r"Ag₂O", ["aldehyde"]),
    ("pyridine is alkylated by an activated C–X", r"pyridine", ["activated_cx"]),
    ("a Grignard reagent attacks a sulfonate ester", r"Mg, dry ether", ["sulfonate_ester"]),
    # live run 9: aqueous/strong acid protonates an amine first
    ("acid protonates amines first", {"alkyne_to_ketone_ho", "alkene_to_alcohol_ho", "alcohol_to_alkene_conchso",
                                      "alcohol_to_sulfonate_conchso"}, ["amine_any"]),
    ("catalytic hydrogenation: hydrogenolysis, C=N", r"(?<![NC])H₂[,/]|H₂$", ["activated_cx", "gem_dihalide", "imine",
                                                                    "oxime"]),
    ("hydride reducers", r"NaBH₄|LiAlH₄|DIBAL", ["imine", "alpha_halo_carbonyl"]),
    ("LiAlH4 reduces tosylates", r"LiAlH₄", ["sulfonate_ester"]),
    ("bromine", r"Br₂", ["amine_any", "imine"]),
    ("acylating / sulfonylating / chlorinating agents take COOH and N–H", r"COCl|TsCl|SOCl₂|\(CH₃CO\)₂O|PCl₅",
     ["carboxylic_acid", "amine_nh"]),
    ("oxidants open epoxides, cleave imines", r"KMnO₄|Cr₂O₇|mCPBA|H₂SO₅", ["epoxide", "imine", "cyanohydrin"]),
    ("Hg²⁺/CH3OH: an OH or COOH in the molecule traps the mercurinium ion", r"Hg\(OAc\)₂",
     ["alcohol", "phenol", "carboxylic_acid", "cyanohydrin", "activated_cx"]),
    ("haloform: Br2/OH⁻ also attacks C=C and C–X", r"Br₂, NaOH|I₂, NaOH", ["alkene", "alkyne", "alkyl_halide",
                                                                         "sulfonate_ester"]),
    ("everything: a C=N or cyanohydrin does not survive", r".", ["imine"]),
]
# electrophilic additions: two DIFFERENT C=C (or C≡C) — which one reacts is not settled (live run 2026-11-25)
ADDITION_EQUIVALENT = {
    "alkene_to_vicinal_dihalide_x": "alkene", "alkene_to_halohydrin_br": "alkene", "alkene_to_alkyl_halide_hx": "alkene",
    "alkene_to_alcohol_ho": "alkene", "alkene_to_ether_hgoacrohorhg": "alkene", "alkene_to_epoxide_mcpba": "alkene",
    "alkyne_to_ketone_ho": "alkyne", "alkyne_to_vinyl_halide_hx1equiv": "alkyne",
    "alkyne_to_geminal_dihalide_hxexcess2equ": "alkyne", "alkyne_to_alkene_h": "alkyne",
}


def _layer2() -> dict:
    import re as _re
    from core.engine.organic.labels import REAGENT_LABEL as _L
    with open(GRAPH, encoding="utf-8") as f:
        start = {e["id"]: e.get("from", "") for e in json.load(f)["edges"]}
    out = {}
    for eid, lab in _L.items():
        own = OWN.get(start.get(eid, ""), set())
        for _what, match, groups in LAYER2:
            hit = eid in match if isinstance(match, set) else bool(_re.search(match, lab))
            if not hit:
                continue
            lst = out.setdefault(eid, {}).setdefault("absent", [])
            lst.extend(g for g in groups if g not in own and g not in lst)
    for eid, g in ADDITION_EQUIVALENT.items():
        out.setdefault(eid, {})["equivalent_only"] = [g]
    out.setdefault("alkene_to_vicinal_dihalide_x", {}).setdefault("absent", []).append("vinyl_halide")
    out.setdefault("alcohol_to_substituted_benzene_4methylbenze", {}).setdefault("absent", []).extend(
        ["alcohol_3", "activated_oh"])
    return out


LAYER2_SCOPE = _layer2()

for _eid, _spec in (list(REVIEW.items()) + list(PASS3.items()) + list(RUN9.items()) + list(RUN12.items())
                    + list(RUN13.items()) + list(LAYER2_SCOPE.items())):
    _cur = SCOPE.setdefault(_eid, {})
    for _k in ("absent", "requires", "at_most_one", "equivalent_only"):
        if _spec.get(_k):
            _lst = _cur.setdefault(_k, [])
            _lst.extend(g for g in _spec[_k] if g not in _lst)
    if _spec.get("note"):
        _cur["note"] = (_cur["note"] + "; " if _cur.get("note") else "") + _spec["note"]

# Groups an edge acts on itself, which the reagent-class layer would otherwise exclude (2026-11-26): chloral IS an
# alpha-halo carbonyl with a CCl3 group; that edge is modelled for chloral only (the rule refuses the rest).
LAYER2_EXEMPT = {"aldehyde_to_alkyl_halide_naohaq": {"alpha_halo_carbonyl", "gem_dihalide", "alkyl_halide"}}
for _eid, _keep in LAYER2_EXEMPT.items():
    SCOPE[_eid]["absent"] = [g for g in SCOPE[_eid].get("absent", []) if g not in _keep]

# Left out of draws after the blind step check (2026-11-24): the textbook outcome is disputed, so a key built on
# it is unsafe. The edge keeps its scope; scope.trusted() refuses it.
LEFT_OUT = {
    "phenol_to_aryl_halide_pclslowreact": "PCl5 barely replaces a phenolic OH (poor yield, phosphate esters); "
                                          "live run 6 and the step check both turned on it",
    # dropped in the review of the 62 unscoped edges (named here so no later block can re-trust them)
    "alcohol_to_amine_al2o3450c": "gives a mixture of amines",
    "alkyl_halide_to_ketone_dmsodimethyl": "Kornblum needs an activated halide",
    "ester_to_ether_conchso": "the product drops the skeleton",
    "ether_to_ester_co": "industrial, not JEE",
    "alcohol_to_carbene_chndiazometh": "O-methylation of an alcohol by CH2N2/HBF4 is outside JEE; the step check "
                                       "read it as a C=O homologation in 4 of 4 held schemes (2026-11-24/25)",
}
for _eid, _why in LEFT_OUT.items():
    SCOPE.setdefault(_eid, {})["left_out"] = _why

# graph text that the approved decisions change (reagents / conditions shown to the writer)
TEXT = {
    "aldehyde_to_carboxylic_acid_kmnoortollen": {
        "reagents": ["Tollens' reagent ([Ag(NH3)2]+, NH3/OH-)", "then H3O+"],
        "conditions": "Tollens' reagent oxidises only the CHO to COO- (silver mirror); acid workup gives RCOOH. "
                      "C=C, OH and ketones are untouched."},
    "substituted_benzene_to_substituted_benzene_conchno3": {
        "reagents": ["conc. HNO3", "conc. H2SO4", "323 K"],
        "conditions": "Mononitration (one NO2) of a monosubstituted benzene: NO2+ enters ortho/para to an o/p "
                      "director (para major) or meta to a meta director."},
}
TX = {"substituted_benzene_to_substituted_benzene_conchno3": [56]}   # 382 (TNT) contradicts mononitration


def build(g: dict) -> dict:
    edges = {e["id"]: e for e in g["edges"]}
    for eid, spec in SCOPE.items():
        e = edges[eid]
        for gname in (spec.get("absent", []) + spec.get("requires", []) + spec.get("at_most_one", [])
                      + spec.get("equivalent_only", [])):
            assert gname in GROUPS, (eid, gname)
        e.setdefault("chemoselectivity", {"requires_absent": [], "node_redirect": {}, "priority_ref": None})
        e["chemoselectivity"]["requires_absent"] = list(spec.get("absent", []))
        fc = {}
        if spec.get("only"):
            fc["only_smiles"] = list(spec["only"])
        for k in ("requires", "at_most_one", "equivalent_only"):
            if spec.get(k):
                fc[k] = list(spec[k])
        if spec.get("note"):
            fc["note"] = spec["note"]
        if spec.get("left_out"):
            fc["left_out"] = spec["left_out"]
        e["firing_condition"] = fc or None
    for eid, fields in TEXT.items():
        edges[eid].update(fields)
    for eid, ids in TX.items():
        edges[eid]["tx_ids"] = ids
    return g


if __name__ == "__main__":
    with open(GRAPH, encoding="utf-8") as f:
        raw = f.read()
    out = json.dumps(build(json.loads(raw)), indent=2, ensure_ascii=False)
    if "--check" in sys.argv:
        sys.exit(0 if out == raw else 1)
    with open(GRAPH, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print(f"scope written for {len(SCOPE)} edges")
