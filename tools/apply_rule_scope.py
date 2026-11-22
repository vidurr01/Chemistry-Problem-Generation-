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
    "alcohol_to_alkyl_halide_socl": {"absent": ["carboxylic_acid"]},
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
}

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
        for gname in spec.get("absent", []) + spec.get("requires", []) + spec.get("at_most_one", []):
            assert gname in GROUPS, (eid, gname)
        e.setdefault("chemoselectivity", {"requires_absent": [], "node_redirect": {}, "priority_ref": None})
        e["chemoselectivity"]["requires_absent"] = list(spec.get("absent", []))
        fc = {}
        if spec.get("only"):
            fc["only_smiles"] = list(spec["only"])
        for k in ("requires", "at_most_one"):
            if spec.get(k):
                fc[k] = list(spec[k])
        if spec.get("note"):
            fc["note"] = spec["note"]
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
